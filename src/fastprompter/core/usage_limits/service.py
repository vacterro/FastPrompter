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

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastprompter.core.usage_limits.model import (
    OK,
    STALE,
    AccountRef,
    UsageSnapshot,
)
from fastprompter.core.usage_limits.providers import UsageProvider
from fastprompter.core.usage_limits.providers.antigravity import AntigravityProvider
from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
from fastprompter.core.usage_limits.providers.codex import CodexProvider
from fastprompter.core.usage_limits.providers.zcode import ZCodeProvider

POOL_SIZE = 3
DEFAULT_REFRESH_SEC = 180
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 600

# How often discovery re-runs on its own. Accounts were discovered once at
# construction, so a CLI or account the user added while FastPrompter was
# running stayed invisible until a restart or a manual Refresh — and installing
# one of those CLIs is exactly what the settings dialog now offers. Discovery is
# pure stat calls (measured 0.7 ms for 5 accounts across 3 providers), so
# folding it into the sweep costs nothing measurable.
REDISCOVER_EVERY_S = 300

# Human label per provider, used to build display names ("Codex 1", "Claude").
_PROVIDER_LABEL = {"codex": "Codex", "claude": "Claude",
                   "antigravity": "Antigravity", "zcode": "ZCode"}

# Discovery order: the account the user actually runs by default first, then
# env/configured overrides, then auto-detected siblings. Ordinals are
# presentation only — identity stays the path hash from model.stable_id_for.
_KIND_ORDER = {"auto_default": 0, "env": 1, "configured": 2, "auto_sibling": 3}


def parse_home_list(raw) -> list[str]:
    """``"D:\\\\a, E:\\\\b"`` / ``"D:\\\\a; E:\\\\b"`` / list -> clean paths."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(p) for p in raw]
    else:
        items = str(raw).replace(";", ",").replace("\n", ",").split(",")
    out: list[str] = []
    for item in items:
        p = item.strip().strip('"').strip("'").strip()
        if p and p not in out:
            out.append(p)
    return out


def apply_display_names(accounts: list[AccountRef]) -> list[AccountRef]:
    """Number accounts per provider so the UI reads "Codex 1", "Codex 2".

    Directory names like ``.codex-account3free`` produce labels such as
    ``Account3Free`` — fine for a tooltip, useless in a 3 px cluster. The
    ordinal is computed from a stable sort (kind, then path), so it does not
    shuffle between runs even though it is not the account's identity.
    """
    groups: dict[str, list[AccountRef]] = {}
    for a in accounts:
        groups.setdefault(a.provider_id, []).append(a)
    renamed: list[AccountRef] = []
    for pid, group in groups.items():
        group = sorted(group, key=lambda a: (_KIND_ORDER.get(a.source_kind, 9),
                                             a.source_path))
        label = _PROVIDER_LABEL.get(pid, pid.title())
        for i, a in enumerate(group, 1):
            name = label if len(group) == 1 else f"{label} {i}"
            renamed.append(dataclasses.replace(a, display_name=name))
    # Keep provider grouping stable for rendering.
    renamed.sort(key=lambda a: (a.provider_id, a.display_name))
    return renamed


@dataclass
class ServiceState:
    accounts: list[AccountRef] = field(default_factory=list)
    snapshots: dict[str, UsageSnapshot] = field(default_factory=dict)  # account.key -> snapshot
    generation: int = 0
    request_id: int = 0  # monotonic sweep request identity (CORE-001)
    status: str = "IDLE"  # IDLE | DISCOVERING | PROBING | BACKOFF
    last_sweep: float = 0.0
    last_discovery: float = 0.0
    next_backoff: float = 0.0
    error: str = ""


class UsageLimitService:
    """Thread-safe service; does not import Qt."""

    def __init__(self, data: dict | None = None):
        self._lock = threading.Lock()
        self._state = ServiceState()
        self._data: dict = data if data is not None else {}
        self._refresh_callbacks: list[callable] = []
        self._closed = False
        self._sweep_threads_count = 0
        self._sweep_pending = False
        self._providers: dict[str, UsageProvider] = self._build_providers()
        self._executor = ThreadPoolExecutor(max_workers=POOL_SIZE)
        self._discover()

    def _build_providers(self) -> dict[str, UsageProvider]:
        """Providers rebuilt from the live profile so config changes apply."""
        return {
            "codex": CodexProvider(
                extra_homes=parse_home_list(self._data.get("limit_codex_homes", ""))
            ),
            "claude": ClaudeProvider(),
            "antigravity": AntigravityProvider(
                data_dir=str(self._data.get("limit_antigravity_dir", "") or "")
            ),
            # ZCode is the only provider that reads its quota over the network,
            # so it is constructed opted-OUT and discovers nothing until the
            # user enables it (see providers/zcode.py).
            "zcode": ZCodeProvider(
                enabled=str(self._data.get("limit_zcode_enabled", "False")) == "True",
                config_path=str(self._data.get("limit_zcode_config", "") or ""),
            ),
        }

    def add_callback(self, cb: callable) -> None:
        """Register a completion callback.

        Callbacks run on the probe worker.  UI consumers must bridge through
        a queued Qt signal rather than touching widgets directly.
        """
        with self._lock:
            if not self._closed:
                self._refresh_callbacks.append(cb)

    # -- reconfiguration ---------------------------------------------------
    def reconfigure(self, data: dict | None = None) -> None:
        """Re-read provider config, rediscover accounts, resweep.

        Called when the user edits the extra Codex homes list. Old snapshots
        are dropped because the accounts themselves may have changed.
        """
        if data is not None:
            self._data = data
        with self._lock:
            # W2-003: increment generation and invalidate in-flight sweeps
            # immediately under lock before slow discovery runs.
            self._state.generation += 1
            self._state.request_id += 1
            self._providers = self._build_providers()
            self._state.snapshots = {}
        self._discover()
        self._fire()
        self.refresh()

    def shutdown(self) -> None:
        """Release the worker pool. Idempotent, non-blocking."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._state.generation += 1
            self._refresh_callbacks.clear()
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

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
        all_accounts = apply_display_names(all_accounts)
        with self._lock:
            self._state.generation = gen
            self._state.accounts = all_accounts
            self._state.last_discovery = time.monotonic()
            self._state.status = "IDLE"

    def discover(self) -> None:
        self._discover()
        self._fire()

    def _rediscover_if_due(self) -> None:
        """Re-scan for accounts periodically, keeping known snapshots.

        Unlike ``reconfigure`` this does NOT drop snapshots: the provider set is
        unchanged, so an account that is still there keeps its last good reading
        instead of blinking back to "not probed yet" every five minutes. An
        account that vanished simply stops being rendered; the stale snapshot it
        left behind is keyed by an account nobody lists any more.
        """
        with self._lock:
            if self._closed:
                return
            last = self._state.last_discovery
            if last and (time.monotonic() - last) < REDISCOVER_EVERY_S:
                return
        before = {a.key for a in self.accounts}
        self._discover()
        if {a.key for a in self.accounts} != before:
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
                last_discovery=self._state.last_discovery,
                next_backoff=self._state.next_backoff,
            )

    # -- probe sweep -------------------------------------------------------
    def refresh(self) -> None:
        """Trigger an async probe sweep fanning out across the thread pool.

        CORE-001 / PERF-001 / PERF-003: each refresh gets an independently monotonic
        ``request_id``. At most 2 coordinator threads may run concurrently (one
        in-flight superseded and one newest); rapid repeated triggers coalesce
        into a single pending follow-up sweep rather than spawning thread storms.
        """
        accounts = self.accounts
        if not accounts:
            return
        with self._lock:
            if self._closed:
                return
            req_id = self._state.request_id + 1
            self._state.request_id = req_id
            gen = self._state.generation
            self._state.status = "PROBING"
            if self._sweep_threads_count >= 2:
                self._sweep_pending = True
                return
            self._sweep_threads_count += 1
        t = threading.Thread(
            target=self._sweep_coordinator, args=(accounts, gen, req_id),
            daemon=True, name="fastprompter-limit-sweep")
        t.start()

    def _sweep_coordinator(self, accounts: list[AccountRef], gen: int, req_id: int) -> None:
        try:
            self._sweep(accounts, gen, req_id)
        finally:
            follow_up = False
            next_accounts = None
            next_gen = 0
            next_req_id = 0
            with self._lock:
                self._sweep_threads_count = max(0, self._sweep_threads_count - 1)
                if self._sweep_pending and not self._closed:
                    self._sweep_pending = False
                    self._sweep_threads_count += 1
                    follow_up = True
                    next_gen = self._state.generation
                    next_req_id = self._state.request_id
                    self._state.status = "PROBING"
            if follow_up:
                next_accounts = self.accounts
                if next_accounts:
                    t = threading.Thread(
                        target=self._sweep_coordinator,
                        args=(next_accounts, next_gen, next_req_id),
                        daemon=True, name="fastprompter-limit-sweep")
                    t.start()
                else:
                    with self._lock:
                        self._sweep_threads_count = max(0, self._sweep_threads_count - 1)
                        if self._state.status == "PROBING":
                            self._state.status = "IDLE"

    def _probe_account(self, account: AccountRef, deadline: float,
                       gen: int, req_id: int) -> UsageSnapshot | None:
        """Probe one account in the thread pool. Aborts early on closure."""
        with self._lock:
            if self._closed or gen < self._state.generation or req_id != self._state.request_id:
                return None
        if not account.enabled:
            return None
        provider = self._providers.get(account.provider_id)
        if provider is None:
            return None
        try:
            return provider.probe(account, deadline)
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("limit probe error for %s", account.key)
            return UsageSnapshot(
                account=account, status="ERROR",
                windows=[], error_code="probe_exception",
                error_summary="unexpected probe exception",
            )

    def _sweep(self, accounts: list[AccountRef], gen: int, req_id: int) -> None:
        deadline = time.monotonic() + (DEFAULT_REFRESH_SEC * 0.9)
        active = [a for a in accounts if a.enabled and a.provider_id in self._providers]
        if not active:
            with self._lock:
                if not self._closed and gen == self._state.generation and req_id == self._state.request_id:
                    self._state.status = "IDLE"
            return

        # PERF-001: fan-out across the worker pool up to POOL_SIZE concurrency.
        # A shutdown can land between the coordinator's closed-check and this
        # submit — the pool is retired without the lock, by contract — and the
        # executor then raises into a daemon thread nobody is watching. There is
        # no result to salvage at that point, so the sweep simply stops: an
        # aborted probe on a closing app is the intended outcome, not an error.
        futures = []
        try:
            for account in active:
                futures.append(self._executor.submit(
                    self._probe_account, account, deadline, gen, req_id))
        except RuntimeError:
            for future in futures:
                future.cancel()
            return
        results: list[UsageSnapshot] = []
        errors = 0
        for f in futures:
            try:
                s = f.result()
                if s is not None:
                    results.append(s)
                    if s.status in ("ERROR", "AUTH_REQUIRED"):
                        errors += 1
            except Exception:
                errors += 1

        with self._lock:
            # CORE-001: only the latest monotonic request under the current
            # configuration generation may commit results and transition state.
            if self._closed or gen < self._state.generation or req_id != self._state.request_id:
                return  # stale/superseded sweep, discard
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
                        banked_resets=prev.banked_resets,
                        provider_metadata=dict(prev.provider_metadata),
                    )
                else:
                    self._state.snapshots[key] = s
            self._state.status = "IDLE"
            self._state.last_sweep = now
            if errors > 0:
                delay = BACKOFF_BASE_S * (2 ** min(errors - 1, 4))
                self._state.next_backoff = now + min(delay, BACKOFF_CAP_S)
                self._state.status = "BACKOFF"
        self._fire()

    # -- auto-refresh scheduler --------------------------------------------
    def schedule_auto(self, interval_s: int | None = None) -> None:
        """Called from a QTimer on the main thread; starts a sweep when
        not backoff-limited (or if interval elapsed since last sweep).

        Rediscovery rides along here rather than on its own timer: it is the
        one place that already knows a sweep is due, and discovery must finish
        before the sweep so a newly installed CLI is probed in the same pass.
        """
        with self._lock:
            state = self._state
            now = time.monotonic()
            if state.status in ("PROBING", "DISCOVERING"):
                return
            if state.status == "BACKOFF" and now < state.next_backoff:
                return
            if state.last_sweep and (now - state.last_sweep) < (interval_s or DEFAULT_REFRESH_SEC) * 0.8:
                return
        self._rediscover_if_due()
        self.refresh()

    def _fire(self) -> None:
        with self._lock:
            if self._closed:
                return
            callbacks = tuple(self._refresh_callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass

    def consume_account_reset(self, account_key: str, credit_id: str | None = None) -> dict:
        """Attempt to consume a banked rate limit reset for an account.

        Finds the matching account, dispatches to provider.consume_reset,
        and triggers a refresh on success.
        """
        with self._lock:
            account = next((a for a in self._state.accounts if a.key == account_key), None)
            if account is None:
                account = next((a for a in self._state.accounts
                               if a.stable_id == account_key or a.provider_id == account_key), None)
        if account is None:
            return {"ok": False, "error": f"Account not found: {account_key}"}

        provider = self._providers.get(account.provider_id)
        if provider is None:
            return {"ok": False, "error": f"No provider registered for {account.provider_id}"}
        if not hasattr(provider, "consume_reset"):
            return {"ok": False, "error": f"Provider {account.provider_id} does not support reset consumption"}

        res = provider.consume_reset(account, credit_id=credit_id)
        if res.get("ok"):
            self.refresh()
        return res

