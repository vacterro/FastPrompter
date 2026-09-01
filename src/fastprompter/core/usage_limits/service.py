"""UsageLimitService — provider-neutral probe coordinator.

Owns:

* enabled provider registry;
* discovered accounts with settings overlay;
* bounded probe executor (thread pool, not one-thread-per-account);
* sweep generation (old results cannot overwrite new);
* automatic refresh with jitter and backoff;
* stale/error state preservation;
* signal bridge to UI.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastprompter.core.usage_limits.model import (
    AccountRef,
    OK,
    STALE,
    UsageSnapshot,
)
from fastprompter.core.usage_limits.providers import UsageProvider
from fastprompter.core.usage_limits.providers.codex import CodexProvider
from fastprompter.core.usage_limits.providers.claude import ClaudeProvider

POOL_SIZE = 3
DEFAULT_REFRESH_SEC = 180
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 600


@dataclass
class ServiceState:
    accounts: list[AccountRef] = field(default_factory=list)
    snapshots: dict[str, UsageSnapshot] = field(default_factory=dict)  # account.key -> snapshot
    generation: int = 0
    status: str = "IDLE"  # IDLE | DISCOVERING | PROBING | BACKOFF
    last_sweep: float = 0.0
    next_backoff: float = 0.0
    error: str = ""


class UsageLimitService:
    """Thread-safe service; does not import Qt."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = ServiceState()
        self._providers: dict[str, UsageProvider] = {
            "codex": CodexProvider(),
            "claude": ClaudeProvider(),
        }
        self._executor = ThreadPoolExecutor(max_workers=POOL_SIZE)
        self._discover()
        self._refresh_callbacks: list[callable] = []

    def add_callback(self, cb: callable) -> None:
        """Called on main-thread after every sweep completes."""
        self._refresh_callbacks.append(cb)

    # -- discovery ---------------------------------------------------------
    def _discover(self) -> None:
        with self._lock:
            gen = self._state.generation + 1
            self._state.status = "DISCOVERING"
        all_accounts: list[AccountRef] = []
        for pid, provider in self._providers.items():
            try:
                all_accounts.extend(provider.discover_accounts())
            except Exception:
                pass
        with self._lock:
            self._state.generation = gen
            self._state.accounts = all_accounts
            self._state.status = "IDLE"

    def discover(self) -> None:
        self._discover()
        self._fire()

    # -- accounts (snapshot) -----------------------------------------------
    @property
    def accounts(self) -> list[AccountRef]:
        with self._lock:
            return list(self._state.accounts)

    @property
    def snapshots(self) -> dict[str, UsageSnapshot]:
        with self._lock:
            return dict(self._state.snapshots)

    @property
    def state_copy(self) -> ServiceState:
        with self._lock:
            return ServiceState(
                accounts=list(self._state.accounts),
                snapshots=dict(self._state.snapshots),
                generation=self._state.generation,
                status=self._state.status,
                last_sweep=self._state.last_sweep,
                next_backoff=self._state.next_backoff,
            )

    # -- probe sweep -------------------------------------------------------
    def refresh(self) -> None:
        """Trigger an async probe sweep from a worker thread."""
        accounts = self.accounts
        if not accounts:
            return
        with self._lock:
            gen = self._state.generation
            self._state.status = "PROBING"
        self._executor.submit(self._sweep, accounts, gen)

    def _sweep(self, accounts: list[AccountRef], gen: int) -> None:
        deadline = time.monotonic() + (DEFAULT_REFRESH_SEC * 0.9)
        results: list[UsageSnapshot] = []
        errors = 0
        for a in accounts:
            if not a.enabled:
                continue
            provider = self._providers.get(a.provider_id)
            if provider is None:
                continue
            try:
                s = provider.probe(a, deadline)
                results.append(s)
                if s.status != OK:
                    errors += 1
            except Exception as exc:
                from fastprompter.core.logging import logger
                logger.exception("limit probe error for %s", a.key)
                errors += 1
        with self._lock:
            if gen < self._state.generation:
                return  # stale sweep, discard
            now = time.monotonic()
            for s in results:
                key = s.account.key
                prev = self._state.snapshots.get(key)
                if s.status == OK:
                    self._state.snapshots[key] = s
                elif prev is not None:
                    # transient failure -> mark STALE, preserve last good
                    self._state.snapshots[key] = UsageSnapshot(
                        account=prev.account, status=STALE,
                        windows=list(prev.windows),
                        plan_type=prev.plan_type,
                        fetched_at=prev.fetched_at,
                        stale_since=now,
                    )
            self._state.status = "IDLE"
            self._state.last_sweep = now
            if errors > 0:
                # exponential backoff
                delay = BACKOFF_BASE_S * (2 ** min(errors - 1, 4))
                self._state.next_backoff = now + min(delay, BACKOFF_CAP_S)
                self._state.status = "BACKOFF"
        self._fire()

    # -- auto-refresh scheduler --------------------------------------------
    def schedule_auto(self, interval_s: int | None = None) -> None:
        """Called from a QTimer on the main thread; starts a sweep when
        not backoff-limited (or if interval elapsed since last sweep)."""
        with self._lock:
            state = self._state
            now = time.monotonic()
            if state.status in ("PROBING", "DISCOVERING"):
                return
            if state.status == "BACKOFF" and now < state.next_backoff:
                return
            if state.last_sweep and (now - state.last_sweep) < (interval_s or DEFAULT_REFRESH_SEC) * 0.8:
                return
        self.refresh()

    def _fire(self) -> None:
        for cb in self._refresh_callbacks:
            try:
                cb()
            except Exception:
                pass