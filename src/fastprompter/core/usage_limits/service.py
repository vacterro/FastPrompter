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
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, field

from fastprompter.core.usage_limits import identity as _identity
from fastprompter.core.usage_limits import sai_accounts as _sai_accounts
from fastprompter.core.usage_limits.model import (
    OK,
    STALE,
    AccountRef,
    UsageSnapshot,
)
from fastprompter.core.usage_limits.providers import UsageProvider
from fastprompter.core.usage_limits.providers._codex_probe import (
    terminate_probe_processes,
)
from fastprompter.core.usage_limits.providers.antigravity import AntigravityProvider
from fastprompter.core.usage_limits.providers.claude import ClaudeProvider
from fastprompter.core.usage_limits.providers.codex import CodexProvider
from fastprompter.core.usage_limits.providers.freebuff import FreebuffProvider
from fastprompter.core.usage_limits.providers.zcode import ZCodeProvider

POOL_SIZE = 3
DEFAULT_REFRESH_SEC = 180
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 600

# Ceiling for one shutdown call. A probe worker only has to notice that its
# child is gone and unwind, which is fast; the bound exists so a wedged
# worker can never hold the process hostage on the way out.
SHUTDOWN_WAIT_S = 3.0

# How often discovery re-runs on its own. Accounts were discovered once at
# construction, so a CLI or account the user added while FastPrompter was
# running stayed invisible until a restart or a manual Refresh — and installing
# one of those CLIs is exactly what the settings dialog now offers. Discovery is
# pure stat calls (measured 0.7 ms for 5 accounts across 3 providers), so
# folding it into the sweep costs nothing measurable.
REDISCOVER_EVERY_S = 300

# Human label per provider, used to build display names ("Codex 1", "Claude").
_PROVIDER_LABEL = {"codex": "Codex", "claude": "Claude",
                   "antigravity": "Antigravity", "zcode": "ZCode",
                   "freebuff": "Freebuff"}

# Discovery order: the account the user actually runs by default first, then
# env/configured overrides, then auto-detected siblings. Ordinals are
# presentation only — identity stays the path hash from model.stable_id_for.
#
# ``config_dir`` / ``config_file`` / ``desktop_only`` are Claude's names for the
# SAME idea as ``auto_default`` — the installation already on this machine — so
# they share ordinal 0. Leaving them unmapped sorted the default account behind
# its own siblings and labelled it "Claude 2".
_KIND_ORDER = {"auto_default": 0, "config_dir": 0, "config_file": 0,
               "desktop_only": 0, "env": 1, "configured": 2,
               "auto_sibling": 3}


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
            canonical = (a.metadata or {}).get("canonical_label")
            if canonical:
                name = canonical
            elif len(group) == 1:
                name = label
            else:
                name = f"{label} {i}"
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
    # Configured execution contexts vs distinct provider identities, plus which
    # accounts provably share one. See ``_rebuild_identity_report``.
    identity_report: dict = field(default_factory=dict)
    # Provider-identity switches seen this session. Fingerprints only.
    identity_events: list = field(default_factory=list)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemon threads not tracked by _python_exit.

    Standard ThreadPoolExecutor registers worker threads in _threads_queues, which
    causes atexit._python_exit() to join() each worker indefinitely even if the app
    requested a bounded exit.
    """

    def _adjust_thread_count(self):
        import concurrent.futures.thread as _cft
        import weakref

        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=_cft._worker,
                args=(weakref.ref(self, weakref_cb), self._work_queue, self._initializer, self._initargs),
                daemon=True,
            )
            t.start()
            self._threads.add(t)


@dataclass(frozen=True)
class QuotaPool:
    """Canonical provider quota pool projection (CORE-001).

    Groups execution contexts that share an authenticated provider identity
    into one quota capacity pool. Unresolved/unverified accounts keep distinct
    pools (absence of proof never merges).
    """
    pool_id: str
    canonical_key: str
    member_keys: tuple[str, ...]
    verified: bool
    fingerprint: str


class UsageLimitService:
    """Thread-safe service; does not import Qt."""

    def __init__(self, data: dict | None = None, *, discover: bool = True):
        self._lock = threading.Lock()
        self._state = ServiceState()
        self._data: dict = data if data is not None else {}
        self._refresh_callbacks: list[callable] = []
        self._closed = False
        # Set before anything else during shutdown so a coordinator already
        # past the ``_closed`` check still refuses to submit new probes.
        self._stopping = threading.Event()
        self._active_futures: set[Future] = set()
        self._sweep_threads_count = 0
        self._sweep_pending = False
        self._sweep_pending_rediscover = False
        self._providers: dict[str, UsageProvider] = self._build_providers()
        self._executor = _DaemonThreadPoolExecutor(max_workers=POOL_SIZE)
        # Library callers historically receive an immediately discovered
        # roster. The Qt shell opts out and starts ``refresh(rediscover=True)``
        # only after its queued callback bridge exists, so filesystem discovery
        # can never stall the GUI thread on a slow/offline account home.
        if discover:
            self._discover()

    def _build_providers(self) -> dict[str, UsageProvider]:
        """Providers rebuilt from the live profile so config changes apply."""
        return {
            "codex": CodexProvider(
                extra_homes=parse_home_list(self._data.get("limit_codex_homes", ""))
            ),
            "claude": ClaudeProvider(
                extra_paths=parse_home_list(self._data.get("limit_claude_homes", ""))
            ),
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
            # Freebuff is the second networked provider, and it stays opt-in
            # for the same reason (see providers/freebuff.py).
            "freebuff": FreebuffProvider(
                enabled=str(self._data.get("limit_freebuff_enabled", "False")) == "True",
                state_path=str(self._data.get("limit_freebuff_state", "") or ""),
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

        Called when the user edits an extra homes list. Old snapshots
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

    def reconfigure_async(self, data: dict | None = None) -> None:
        """Reconfigure without running account discovery on the caller.

        UI code uses this route. Provider objects and invalidation state are
        replaced synchronously under the lock; filesystem discovery and the
        ensuing probes run on the bounded sweep coordinator.
        """
        if data is not None:
            self._data = data
        with self._lock:
            if self._closed:
                return
            self._state.generation += 1
            self._state.request_id += 1
            self._providers = self._build_providers()
            self._state.accounts = []
            self._state.snapshots = {}
            self._state.last_discovery = 0.0
            self._state.status = "DISCOVERING"
        self._fire()
        self.refresh(rediscover=True)

    def shutdown(self, timeout: float = SHUTDOWN_WAIT_S) -> bool:
        """Stop all probing within a bounded time. Idempotent, thread-safe.

        The order is the whole point:

        1. mark stopping, so no further probe is ever submitted and any
           result arriving late is discarded instead of published;
        2. cancel the futures that have not started yet;
        3. terminate the in-flight ``codex`` children — a running probe is
           parked in a response poll and its worker cannot unwind while its
           child lives, so this is what actually frees the pool;
        4. wait for the remaining workers, but only for ``timeout``;
        5. retire the executor.

        Returns True when everything unwound inside the bound. False means a
        worker was still running when the wait expired; the caller may log it
        but must not block further — the pool threads are then abandoned
        deliberately rather than allowed to hold up process exit.

        Safe to call from ``_shutdown_application``, ``aboutToQuit``, the
        window's ``destroyed`` signal and test teardown, in any order and any
        number of times.

        Step 3 is process-wide: it stops every registered probe child, not
        only the ones this instance spawned. The app owns one service, and a
        stray child from a discarded instance is exactly what must not
        survive, so the broader reach is the intent.
        """
        self._stopping.set()
        with self._lock:
            self._closed = True
            self._state.generation += 1
            self._state.request_id += 1
            self._refresh_callbacks.clear()
            self._sweep_pending = False
            self._sweep_pending_rediscover = False
            pending = [f for f in self._active_futures if not f.done()]

        # ``cancel()`` returns False only for a probe that is already running or
        # finished, which is exactly the set worth waiting on. Futures cancelled
        # here must NOT be waited on: cancelling leaves them in state CANCELLED,
        # and ``futures.wait`` counts only CANCELLED_AND_NOTIFIED as done -- a
        # transition that never happens once ``cancel_futures`` drops the work
        # item from the queue. Passing them to the wait burns the whole timeout
        # on futures that are already finished.
        still_running = [f for f in pending if not f.cancel()]
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        terminate_probe_processes()

        unfinished: set[Future] = set()
        if still_running:
            _done, unfinished = futures_wait(
                still_running, timeout=max(0.0, timeout))

        with self._lock:
            # W2-002: retire only done or cancelled futures. Do NOT remove
            # unfinished futures while they are still running, so a repeated
            # shutdown continues to track them within its bounded timeout.
            done_or_cancelled = {f for f in self._active_futures if f.done() or f.cancelled()}
            self._active_futures.difference_update(done_or_cancelled)
            self._state.status = "IDLE"
            active_count = len(self._active_futures)

        if active_count == 0 and not unfinished:
            # Everything is already finished, so this cannot block.
            try:
                self._executor.shutdown(wait=True)
            except Exception:
                pass

        return not bool(unfinished)

    def _retire_future(self, future: Future) -> None:
        """Callback attached to probe futures for clean, decoupled retirement."""
        with self._lock:
            self._active_futures.discard(future)

    # -- discovery ---------------------------------------------------------
    def _discover(self, *, request_id: int | None = None) -> bool:
        with self._lock:
            if self._closed:
                return False
            base_gen = self._state.generation
            providers = tuple(self._providers.items())
            self._state.status = "DISCOVERING"
        all_accounts: list[AccountRef] = []
        for _pid, provider in providers:
            try:
                all_accounts.extend(provider.discover_accounts())
            except Exception:
                pass
        # SAI Accounts is OPTIONAL. This call answers "nothing" when the plane
        # is absent, and even when it answers, it only adds accounts this
        # application does not already have. With no plane installed the list
        # below is byte-for-byte what it was before the federation existed.
        try:
            all_accounts = _sai_accounts.augment(all_accounts, [pid for pid, _ in providers])
        except Exception:
            pass
        all_accounts = apply_display_names(all_accounts)
        with self._lock:
            # A newer configuration/request owns the service now. Never let
            # slow discovery from an old home list replace its roster.
            if (self._closed or self._state.generation != base_gen
                    or (request_id is not None
                        and self._state.request_id != request_id)):
                return False
            self._state.generation = base_gen + 1
            self._state.accounts = all_accounts
            self._state.last_discovery = time.monotonic()
            # Rebuild immediately: a roster change can make two accounts the
            # same identity (or stop being), and the panel must not render a
            # phantom second pool while the first sweep is still running.
            self._rebuild_identity_report()
            self._state.status = "IDLE"
        return True

    def discover(self) -> None:
        self._discover()
        self._fire()

    def _rediscover_if_due(self, *, request_id: int | None = None) -> bool:
        """Re-scan for accounts periodically, keeping known snapshots.

        Unlike ``reconfigure`` this does NOT drop snapshots: the provider set is
        unchanged, so an account that is still there keeps its last good reading
        instead of blinking back to "not probed yet" every five minutes. An
        account that vanished simply stops being rendered; the stale snapshot it
        left behind is keyed by an account nobody lists any more.
        """
        with self._lock:
            if self._closed:
                return False
            last = self._state.last_discovery
            if last and (time.monotonic() - last) < REDISCOVER_EVERY_S:
                return False
        before = {a.key for a in self.accounts}
        if not self._discover(request_id=request_id):
            return False
        if {a.key for a in self.accounts} != before:
            self._fire()
        return True

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
    def refresh(self, rediscover: bool = False) -> None:
        """Trigger an async probe sweep fanning out across the thread pool.

        CORE-001 / PERF-001 / PERF-003: each refresh gets an independently monotonic
        ``request_id``. At most 2 coordinator threads may run concurrently (one
        in-flight superseded and one newest); rapid repeated triggers coalesce
        into a single pending follow-up sweep rather than spawning thread storms.
        """
        accounts = self.accounts
        if not accounts and not rediscover:
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
                self._sweep_pending_rediscover |= bool(rediscover)
                return
            self._sweep_threads_count += 1
        t = threading.Thread(
            target=self._sweep_coordinator, args=(accounts, gen, req_id, rediscover),
            daemon=True, name="fastprompter-limit-sweep")
        t.start()

    def _sweep_coordinator(self, accounts: list[AccountRef], gen: int, req_id: int,
                           rediscover: bool = False) -> None:
        try:
            if rediscover:
                self._rediscover_if_due(request_id=req_id)
                accounts = self.accounts
                with self._lock:
                    if self._closed or req_id != self._state.request_id:
                        return
                    # Discovery advances the configuration generation. This
                    # coordinator owns the following sweep, so use the new one.
                    gen = self._state.generation
            self._sweep(accounts, gen, req_id)
        finally:
            follow_up = False
            next_accounts = None
            next_gen = 0
            next_req_id = 0
            next_rediscover = False
            with self._lock:
                self._sweep_threads_count = max(0, self._sweep_threads_count - 1)
                if self._sweep_pending and not self._closed:
                    self._sweep_pending = False
                    next_rediscover = self._sweep_pending_rediscover
                    self._sweep_pending_rediscover = False
                    self._sweep_threads_count += 1
                    follow_up = True
                    next_gen = self._state.generation
                    next_req_id = self._state.request_id
                    self._state.status = "PROBING"
            if follow_up:
                next_accounts = self.accounts
                if next_accounts or next_rediscover:
                    t = threading.Thread(
                        target=self._sweep_coordinator,
                        args=(next_accounts, next_gen, next_req_id,
                              next_rediscover),
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
        if self._stopping.is_set():
            return None
        with self._lock:
            if self._closed or gen < self._state.generation or req_id != self._state.request_id:
                return None
        if not account.enabled:
            return None
        provider = self._providers.get(account.provider_id)
        if provider is None:
            return None
        if _sai_accounts.is_shared(account):
            # A shared account is read through the plane, which owns its
            # identity and its context. The local provider probe is passed
            # along, not called: the plane may answer "I do not read this
            # provider", and only then is the local reader the right one.
            try:
                return _sai_accounts.probe_shared(
                    account, deadline,
                    local_probe=lambda a, d: provider.probe(a, d))
            except Exception:
                from fastprompter.core.logging import logger
                logger.exception("limit shared probe error for %s", account.key)
                return UsageSnapshot(
                    account=account, status="UNAVAILABLE", windows=[],
                    error_code="shared_probe_exception",
                    error_summary="unexpected shared probe exception",
                )
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
        futures: list[Future] = []
        try:
            for account in active:
                # Submit and register under ONE lock acquisition. `submit()`
                # hands the work to a pool thread immediately, so registering
                # afterwards left a window in which the probe was already
                # running but absent from `_active_futures`; a shutdown
                # snapshot taken in that window missed it, reported
                # "everything unwound" while the probe was still parked, and
                # let the worker outlive the bound. Shutdown sets
                # `_stopping` before it takes the lock, so it now sees either
                # this abort or the fully registered future -- never neither.
                with self._lock:
                    if self._stopping.is_set():
                        raise RuntimeError("usage-limit service is stopping")
                    future = self._executor.submit(
                        self._probe_account, account, deadline, gen, req_id)
                    future.add_done_callback(self._retire_future)
                    futures.append(future)
                    self._active_futures.add(future)
        except RuntimeError:
            for future in futures:
                future.cancel()
            with self._lock:
                self._active_futures.difference_update({f for f in futures if f.done() or f.cancelled()})
            return
        results: list[UsageSnapshot] = []
        errors = 0
        try:
            for f in futures:
                try:
                    s = f.result()
                except CancelledError:
                    # Shutdown reached this probe before it ran. Note that
                    # CancelledError derives from BaseException, so it must be
                    # named explicitly: letting it escape would kill the
                    # coordinator thread and leave an unraisable exception
                    # behind for whoever collects garbage next.
                    continue
                except Exception:
                    errors += 1
                    continue
                if s is not None:
                    results.append(s)
                    if s.status in ("ERROR", "AUTH_REQUIRED"):
                        errors += 1
        finally:
            with self._lock:
                self._active_futures.difference_update({f for f in futures if f.done() or f.cancelled()})

        with self._lock:
            # CORE-001: only the latest monotonic request under the current
            # configuration generation may commit results and transition state.
            if self._closed or gen < self._state.generation or req_id != self._state.request_id:
                return  # stale/superseded sweep, discard
            now = time.monotonic()
            for s in results:
                key = s.account.key
                prev = self._state.snapshots.get(key)
                # Account switch: a different human signed in under this account.
                # The previous reading belongs to the PREVIOUS identity and must
                # never be served for the new one, so it is dropped rather than
                # carried across. Banked resets go with it: they were earned by
                # quota that no longer belongs to this slot.
                if prev is not None and _identity.identity_changed(
                        prev.provider_metadata, s.provider_metadata):
                    self._state.identity_events.append({
                        "account_key": key,
                        "display_name": s.account.display_name,
                        "previous": _identity.fingerprint_of(prev.provider_metadata),
                        "current": _identity.fingerprint_of(s.provider_metadata),
                        "observed_at": time.time(),
                    })
                    prev = None
                if s.status == OK:
                    self._state.snapshots[key] = s
                elif s.status in ("AUTH_REQUIRED", "IDENTITY_MISMATCH") or (prev is not None and prev.status != OK):
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
                        reset_offers=prev.reset_offers,
                    )
                else:
                    self._state.snapshots[key] = s
            self._rebuild_identity_report()
            self._state.status = "IDLE"
            self._state.last_sweep = now
            if errors > 0:
                delay = BACKOFF_BASE_S * (2 ** min(errors - 1, 4))
                self._state.next_backoff = now + min(delay, BACKOFF_CAP_S)
                self._state.status = "BACKOFF"
        self._fire()

    # -- provider identity --------------------------------------------------
    def _rebuild_identity_report(self) -> None:
        """Recompute which accounts are the SAME provider account.

        Two questions are answered here and they must never be collapsed:
        how many execution contexts are configured, and how many distinct
        provider identities those contexts actually represent. Capacity is the
        second number. A roster of two slots that are one Google account has
        one quota pool, and pretending otherwise is what makes a router burn the
        same quota twice while believing it has redundancy.

        Callers hold ``self._lock``.
        """
        accounts = [a for a in self._state.accounts if a.enabled]
        entries = [(a.key, self._state.snapshots[a.key].provider_metadata
                    if a.key in self._state.snapshots else {})
                   for a in accounts]
        duplicates = _identity.duplicate_report(entries)
        by_key = {key: _identity.fingerprint_of(meta) for key, meta in entries}
        pools = self._quota_pools_locked(accounts)
        self._state.identity_report = {
            # Configured execution contexts — what the operator set up.
            "configured": len(accounts),
            # Distinct provider identities — what capacity actually exists.
            "unique_identities": len(pools),
            # Canonical quota pools list (CORE-001)
            "quota_pools": [dataclasses.asdict(p) for p in pools],
            # cache key -> the canonical cache key it shares quota with.
            "shared_with": duplicates,
            "fingerprint_of": by_key,
        }

    def _quota_pools_locked(self, accounts: list[AccountRef] | None = None) -> list[QuotaPool]:
        target_accounts = [a for a in self._state.accounts if a.enabled] if accounts is None else list(accounts)
        snapshots = self._state.snapshots
        entries = [
            (a.key, snapshots[a.key].provider_metadata if a.key in snapshots else {})
            for a in target_accounts
        ]
        groups = _identity.group_by_identity(entries)
        assigned: set[str] = set()
        pools: list[QuotaPool] = []

        # 1. Proven shared / verified identity groups in account order
        for a in target_accounts:
            if a.key in assigned:
                continue
            meta = snapshots.get(a.key).provider_metadata if a.key in snapshots else {}
            fp = _identity.fingerprint_of(meta)
            if fp and fp in groups:
                members = [k for k in groups[fp] if k in {acc.key for acc in target_accounts}]
                if members:
                    canonical = members[0]
                    pools.append(QuotaPool(
                        pool_id=f"fp:{fp}",
                        canonical_key=canonical,
                        member_keys=tuple(members),
                        verified=True,
                        fingerprint=fp,
                    ))
                    assigned.update(members)

        # 2. Unresolved / unverified accounts remain individual pools
        for a in target_accounts:
            if a.key in assigned:
                continue
            pools.append(QuotaPool(
                pool_id=f"unresolved:{a.key}",
                canonical_key=a.key,
                member_keys=(a.key,),
                verified=False,
                fingerprint="",
            ))
            assigned.add(a.key)

        return pools

    def quota_pools(self, accounts: list[AccountRef] | None = None) -> list[QuotaPool]:
        """Canonical quota-pool projection (CORE-001).

        Groups accounts that share a verified provider identity into one
        quota pool. Accounts with unverified/unresolved identities each remain
        in their own distinct pool (absence of proof never merges).
        """
        with self._lock:
            return self._quota_pools_locked(accounts)

    def identity_report(self) -> dict:
        """A snapshot of the identity index: counts, sharing, per-account fp."""
        with self._lock:
            return dict(self._state.identity_report)

    def shared_identity_with(self, account_key: str) -> str:
        """The canonical account key this one shares a provider identity with.

        Empty when the identity is unique or unproven. Unproven NEVER returns a
        peer: "I don't know who this is" must not be reported as "same as
        someone else", which would delete capacity that really exists.
        """
        with self._lock:
            return self._state.identity_report.get("shared_with", {}).get(account_key, "")

    def identity_events(self) -> list[dict]:
        """Provider-identity switches observed, newest last.

        Carries fingerprints only — no token, no address, no quota.
        """
        with self._lock:
            return list(self._state.identity_events)

    # -- auto-refresh scheduler --------------------------------------------
    def schedule_auto(self, interval_s: int | None = None) -> None:
        """Called from a QTimer on the main thread; starts an async sweep when
        not backoff-limited (or if interval elapsed since last sweep).

        Rediscovery rides along inside the background sweep coordinator so
        the main thread does zero filesystem scanning during auto-refresh.
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
        self.refresh(rediscover=True)

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
