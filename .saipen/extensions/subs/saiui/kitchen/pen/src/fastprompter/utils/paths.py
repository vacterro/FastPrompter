import os
import sys
import threading
import time


def _detect_base_dir() -> str:
    """
    Internal: resolve the base directory for bundled assets.

    Priority:
      1. Nuitka onefile temp extraction dir (via __compiled__ + an anchor dir)
      2. Source checkout (go up from src/fastprompter/utils/paths.py)
    """
    if "__compiled__" in globals():
        # Nuitka onefile: bundled data dirs sit alongside the compiled modules
        # in the onefile temp extraction directory. Walk up until we find a
        # parent that has sound/ or _res/ subdir, or hit root.
        candidate = os.path.dirname(os.path.abspath(__file__))
        while True:
            if os.path.isdir(os.path.join(candidate, "sound")) or os.path.isdir(
                os.path.join(candidate, "_res")
            ):
                return candidate
            parent = os.path.dirname(candidate)
            if parent == candidate:  # hit filesystem root
                break
            candidate = parent
        return candidate
    # Running from source: src/fastprompter/utils/paths.py -> project root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


# Cached base dir to avoid repeated filesystem walks
_BASE_DIR = None


def get_base_dir() -> str:
    global _BASE_DIR
    if _BASE_DIR is None:
        _BASE_DIR = _detect_base_dir()
    return _BASE_DIR


def get_exe_dir() -> str:
    """
    Directory containing the executable (for portable DB storage).
    When running from source, returns the project root.
    """
    if "__compiled__" in globals():
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return get_base_dir()


def profile_files_root(base_root: str, profile_id) -> str:
    """The physical File Container root a profile OWNS.

    Profiles are independent workspaces, so their filesystem containers must
    have the same ownership boundary their databases already have:

    * profile 1 keeps the legacy layout (``<base_root>``) so every existing
      install's files keep resolving with no migration.
    * profile 2+ gets its own namespace ``<base_root>/_profiles/p<id>`` — a
      profile can never read, adopt or delete another profile's folders.

    No files are ever copied between profiles; an unnamespaced legacy asset
    belongs to profile 1.
    """
    try:
        pid = int(profile_id or 1)
    except (TypeError, ValueError):
        pid = 1
    if pid <= 1:
        return base_root
    return os.path.join(base_root, "_profiles", f"p{pid}")


def _portable_dir_holds_user_data(d: str) -> bool:
    """True if ``d`` contains (or may contain) FastPrompter user data.

    An uninspectable directory counts as holding data: deciding otherwise
    would silently open a blank AppData profile next to a database the user
    believes is theirs.
    """
    try:
        names = os.listdir(d)
    except OSError:
        return True
    for n in names:
        if n == "files" or n.startswith("local_data") or n.endswith(".db") \
                or n.endswith(".bak"):
            return True
    return False


def _probe_dir_writable(d: str) -> None:
    """Create-and-remove a probe file inside ``d``; raises on failure.

    os.access(exe_dir, W_OK) lies on Windows (it mostly answers True); the
    real test is actually performing the write the app will need.
    """
    import uuid
    probe = os.path.join(d, f".fp-write-probe-{uuid.uuid4().hex[:8]}")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def get_data_dir() -> str:
    """The directory where user data (SQLite DB, files) is stored.

    Prefers the exe-local (portable) ``data/`` dir over %%LOCALAPPDATA%%, with
    an explicit failure policy instead of a blind ``os.access`` guess:

    * CASE A — portable dir does NOT exist and cannot be created/written:
      fall back to AppData (nothing to lose, nothing is hidden).
    * CASE B — portable dir EXISTS and holds (or may hold) FastPrompter user
      data but is no longer writable: FAIL CLOSED. Silently falling back to a
      blank AppData profile would present an empty database as the user's
      data — "everything is gone".
    * CASE C — the portable path exists as a FILE: fail closed if it looks
      like a database (the user's data is ambiguous), else fall back.
    """
    exe_dir = get_exe_dir()
    portable_dir = os.path.join(exe_dir, "data")

    if os.path.isfile(portable_dir):
        # CASE C: a file sits where the data dir belongs. Only a SQLite header
        # makes it ambiguous enough to fail closed; a junk file can be skipped.
        try:
            with open(portable_dir, "rb") as f:
                header = f.read(16)
            is_db = header.startswith(b"SQLite format 3")
        except OSError as e:
            # unreadable file: treat as ambiguous, fail closed
            raise OSError(
                "the portable data path exists but cannot be inspected "
                f"({portable_dir!r}); refusing to start on a blank AppData "
                "profile next to it") from e
        if is_db:
            raise OSError(
                "the portable data path is a FILE containing a database "
                f"({portable_dir!r}); refusing to start on a blank "
                "AppData profile next to it")

    if os.path.isdir(portable_dir):
        # CASE B: the dir exists. Prove we can actually write to it.
        try:
            os.makedirs(portable_dir, exist_ok=True)
            _probe_dir_writable(portable_dir)
            return portable_dir
        except OSError as e:
            if _portable_dir_holds_user_data(portable_dir):
                raise OSError(
                    "the portable data directory is not writable and holds "
                    f"FastPrompter data ({portable_dir!r}); refusing to start "
                    "on a blank AppData profile instead"
                ) from e
            # a provably empty/unusable leftover dir: falling back loses nothing

    # CASE A (or a safe CASE B/C fallback): portable dir absent/empty and not
    # creatable — fall back to AppData.
    try:
        os.makedirs(portable_dir, exist_ok=True)
        _probe_dir_writable(portable_dir)
        return portable_dir
    except OSError:
        pass

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
        data_dir = os.path.join(local_app_data, "FastPrompter")
    else:
        data_dir = os.path.join(os.path.expanduser("~"), ".fastprompter")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_db_path(profile_id=1) -> str:
    db_name = "local_data_v15.db" if profile_id == 1 else f"local_data_v15_p{profile_id}.db"
    return os.path.join(get_data_dir(), db_name)


def get_portable_backup_dir() -> str:
    home = os.path.expanduser("~")
    documents = os.path.join(home, "Documents")
    base = documents if os.path.isdir(documents) else home
    backup_dir = os.path.join(base, ".fastprompter")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def get_resource_path(*args) -> str:
    """Absolute path to a bundled resource (sounds, fonts, icons)."""
    path = os.path.join(get_base_dir(), *args)
    if os.path.exists(path):
        return path
    # Source layout: some resources (e.g. sound/) live in the package dir
    # (src/fastprompter/) rather than the project root.
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alt = os.path.join(pkg_dir, *args)
    return alt if os.path.exists(alt) else path


# --- bounded filesystem probes -------------------------------------------
#
# os.path.exists/os.path.isdir on a dead SMB path can block for MINUTES
# (measured 93s on the developer's machine). Each probe therefore runs on a
# daemon thread, and the caller only waits `timeout`. But a daemon thread is
# not free: a dead connect that never returns keeps its stack forever, and a
# flood of pastes against the same dead share would spawn an unbounded pile.
# So the probe pool is STRICTLY bounded:
#
# * at most ``_MAX_STUCK_PROBES`` OS calls may be in flight at once
#   (BoundedSemaphore); when the capacity is exhausted the caller gets False
#   immediately.
# * one path is never probed twice while its first probe is still running
#   (in-flight dedupe) — no second thread for the same hang.
# * a negative verdict is cached briefly, so repeated identical lookups do
#   not churn the pool.
#
# False always means "not a path": the paste falls through to inserting the
# text verbatim, which is the safe outcome.

_MAX_STUCK_PROBES = 4
_PROBE_SLOTS = threading.BoundedSemaphore(_MAX_STUCK_PROBES)
_PROBE_LOCK = threading.Lock()
_PROBE_INFLIGHT = {}          # key -> started-at (monotonic)
_PROBE_NEGATIVE = {}          # key -> expiry (monotonic)
_PROBE_NEGATIVE_TTL = 5.0
_PROBE_NEGATIVE_MAX = 500


def _probe_key(check, path):
    """Dedupe key for (check-kind, path).

    Never resolves the path (no ``os.fspath``): a hostile path object hangs
    inside ``__fspath__`` and must hang inside the OS call, not in the key.
    """
    kind = getattr(check, "__name__", repr(check))
    if isinstance(path, str):
        return (kind, os.path.normcase(os.path.abspath(os.path.normpath(path))))
    return (kind, repr(path))


def _probe_cached_negative(key, now):
    with _PROBE_LOCK:
        exp = _PROBE_NEGATIVE.get(key)
        if exp is None:
            return False
        if now < exp:
            return True
        _PROBE_NEGATIVE.pop(key, None)
        return False


def exists_within(path: str, timeout: float = 0.25) -> bool:
    r"""os.path.exists() that cannot freeze the caller.

    The editor probes the filesystem on EVERY paste of a short single-line
    string, to turn a pasted path into a markdown link. On Windows that probe
    is not bounded: os.path.exists(r"\\192.0.2.77\share\x") sends the
    calling thread into an SMB connect that took a MEASURED 93 seconds on the
    developer's machine. Run from the GUI thread, that is the whole window
    frozen with "Not Responding" — which is exactly how a user describes a
    paste that "crashes the app".

    A named host that does not resolve fails fast (DNS says no); an IP literal
    that nobody answers does not, and neither does a mapped drive whose server
    went away. So the probe runs on a daemon thread and the answer is only
    used if it arrives in time.

    Timing out returns False, i.e. "not a path": the paste falls through to
    inserting the text verbatim, which is the safe outcome. Stuck probe
    threads are daemons AND capped at ``_MAX_STUCK_PROBES`` (see module
    notes), so a dead share can never accumulate an unbounded pile.
    """
    return _probe_within(os.path.exists, path, timeout)


def isdir_within(path: str, timeout: float = 0.25) -> bool:
    """os.path.isdir() with the same bound as `exists_within`.

    The configured files root is user-chosen through a QFileDialog, so it can
    sit on a share. Checking it is on the silo-refresh path, which means an
    unplugged NAS would stall the UI once per silo.
    """
    return _probe_within(os.path.isdir, path, timeout)


def _probe_within(check, path, timeout):
    """Run `check(path)` on a pooled daemon thread; False if it does not answer.

    Bounded: at most ``_MAX_STUCK_PROBES`` OS calls in flight process-wide;
    once the capacity is exhausted callers get False immediately. The same
    path is never given a second thread while its first probe is still
    running (the in-flight entry lives until the OS call actually returns, so
    a repeated paste against a dead share costs nothing).
    """
    key = _probe_key(check, path)
    now = time.monotonic()
    if _probe_cached_negative(key, now):
        return False
    with _PROBE_LOCK:
        if key in _PROBE_INFLIGHT:
            return False          # already hanging on this exact path
    if not _PROBE_SLOTS.acquire(blocking=False):
        return False              # capacity exhausted: answer False now

    answer = []
    with _PROBE_LOCK:
        _PROBE_INFLIGHT[key] = now

    def probe():
        try:
            answer.append(check(path))
        except (OSError, ValueError):
            answer.append(False)
        finally:
            # the OS call (eventually) returned: release the slot AND the
            # in-flight claim so a later probe of the same path can retry
            with _PROBE_LOCK:
                _PROBE_INFLIGHT.pop(key, None)
            _PROBE_SLOTS.release()

    worker = threading.Thread(target=probe, daemon=True)
    worker.start()
    worker.join(timeout)
    ok = bool(answer) and answer[0]
    if not ok:
        # negative (either genuinely absent, or the caller gave up): cache
        # the conservative verdict briefly so repeat lookups do not churn
        with _PROBE_LOCK:
            # opportunistic bounded sweep for expired entries
            if len(_PROBE_NEGATIVE) > _PROBE_NEGATIVE_MAX:
                now2 = time.monotonic()
                dead = [k for k, exp in list(_PROBE_NEGATIVE.items()) if now2 >= exp]
                for k in dead:
                    _PROBE_NEGATIVE.pop(k, None)
                if len(_PROBE_NEGATIVE) > _PROBE_NEGATIVE_MAX:
                    # still over bound (unique never-revisited keys)
                    for k in list(_PROBE_NEGATIVE.keys())[:100]:
                        _PROBE_NEGATIVE.pop(k, None)
            _PROBE_NEGATIVE[key] = time.monotonic() + _PROBE_NEGATIVE_TTL
    return ok
