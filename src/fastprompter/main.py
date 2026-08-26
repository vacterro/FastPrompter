import copy
import ctypes
import ctypes.wintypes
import datetime
import json
import math
import os
import re
import sys
import time
import zlib

from PyQt6 import sip
from PyQt6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QObject,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# How deep silos may nest: 0 = top level, so 2 allows 1 -> 1.1 -> 1.1.1.
MAX_SILO_DEPTH = 2

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_int,
    ctypes.wintypes.UINT,
    ctypes.wintypes.UINT,
]
user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL

from fastprompter.core import header as header_core
from fastprompter.core.hotkey_filter import HotkeyFilter

# Qt alignment flags keyed by the word stored in ctrl_e_align.
_ALIGN_FLAGS = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight,
    "justify": Qt.AlignmentFlag.AlignJustify,
}
from fastprompter.core.i18n import NATIVE_NAMES as _LANG_NATIVE_NAMES
from fastprompter.core.ipc_server import IpcServer
from fastprompter.core.sound_manager import SoundManager
from fastprompter.core.state import _PER_CATEGORY_STATE_KEYS, FastPrompterState
from fastprompter.core.translations import available_languages, get_language, tr
from fastprompter.theme.themes import THEMES
from fastprompter.ui.cursor_mixin import CursorMixin
from fastprompter.ui.edit_guard import edit_block
from fastprompter.ui.editor import VaultTextEdit
from fastprompter.ui.fancy_zones import FancyZoneOverlay
from fastprompter.ui.formatting_mixin import FormattingMixin
from fastprompter.ui.hotkey_mixin import HotkeyMixin
from fastprompter.ui.markdown_highlighter import MarkdownHighlighter
from fastprompter.ui.pie_menu import QuickListWidget
from fastprompter.ui.resizers import EdgeResizer
from fastprompter.ui.scaling_mixin import ScalingMixin
from fastprompter.ui.search_mixin import SearchMixin
from fastprompter.ui.send_selection_mixin import SendSelectionMixin
from fastprompter.ui.snippet_ops_mixin import SnippetOpsMixin
from fastprompter.ui.snippet_panel import (
    DraggableSiloButton,
    DropVerticalWidget,
    SiloDropWidget,
    SnippetWidget,
    WheelPager,
)
from fastprompter.ui.theme_mixin import ThemeMixin
from fastprompter.ui.tray_mixin import TrayMixin
from fastprompter.ui.watcher_mixin import WatcherMixin
from fastprompter.ui.window_mixin import WindowMixin
from fastprompter.utils.paths import get_data_dir
from fastprompter.utils.textfit import clip_safe_width


class _PreviewTextEdit(QTextEdit):
    """Read-only markdown preview whose links open in the browser.

    This PyQt6 build ships a QTextEdit without setOpenExternalLinks(), so the
    preview cannot rely on Qt's built-in link-following; a left click on an
    anchor opens it directly instead. Dragging to select text is unaffected.
    """

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and not self.textCursor().hasSelection()):
            href = self.anchorAt(event.position().toPoint())
            if href:
                from fastprompter.ui.editor import VaultTextEdit
                url = VaultTextEdit._safe_link_url(QUrl(href))
                if url:
                    VaultTextEdit.authorize_and_open_url(url, self, getattr(self.window(), '_current_lang', 'EN'))
                    event.accept()
                    return
        super().mouseReleaseEvent(event)


class _SettingsGroupBox(QWidget):
    """A settings group that can say how tall it is at a given width.

    A plain QWidget reports one height, so a group handed extra width by the
    flow kept the tall narrow shape it was measured at and the room bought
    nothing - the Editor tab stayed 351px when it could be 272.
    """

    _inner = None
    _chrome_h = 0

    def hasHeightForWidth(self):
        return self._inner is not None

    def heightForWidth(self, width):
        if self._inner is None:
            return super().heightForWidth(width)
        margins = self.layout().contentsMargins() if self.layout() else None
        pad = (margins.left() + margins.right()) if margins else 0
        return self._chrome_h + self._inner.totalHeightForWidth(max(1, width - pad))


def _snapshot_text_size(st):
    """Chars of silo text a data snapshot holds, for the undo/redo size cap."""
    if "_text_size" in st:
        return st["_text_size"]
    size = 0
    for key in ("temp_presets", "archive_temp_presets"):
        d = st.get(key)
        if isinstance(d, dict):
            for cats in d.values():
                if isinstance(cats, (list, tuple)):
                    size += sum(len(t) for t in cats if isinstance(t, str))
        elif isinstance(d, (list, tuple)):
            size += sum(len(t) for t in d if isinstance(t, str))
    cats = st.get("categories")
    if isinstance(cats, dict):
        for slot_list in cats.values():
            if isinstance(slot_list, (list, tuple)):
                for slot in slot_list:
                    if isinstance(slot, dict):
                        text = slot.get("text")
                        if isinstance(text, str):
                            size += len(text)
    st["_text_size"] = size
    return size


def _copy_category_slots(slots):
    """Deep-copy ONE category's slot list for undo/redo snapshots.

    A shallow ``list(...)`` copy would alias the slot DICTS: the live
    category keeps mutating them (snippet edits), so a later undo/redo
    would restore a mid-edit state instead of the captured one. ``None``
    entries stay ``None``.
    """
    if slots is None:
        return None
    return [None if s is None else dict(s) for s in slots]


_SYNC_DEBOUNCE_MS = 200
# bounded final-flush wait at window close; after this the mirror may be
# stale but the SQLite database stays authoritative and shutdown continues
# (with a synchronous last-resort flush of the final snapshot)
_SYNC_SHUTDOWN_TIMEOUT_S = 8.0

# Process-wide shared sync worker (see _sync_ensure_worker): one thread for
# the whole process, never torn down per-window.
_SYNC_SHARED_WORKER = None
_SYNC_SHARED_THREAD = None


def wait_thread_seconds(thread, timeout_s, label="QThread"):
    """Wait for a thread in seconds and log an explicit shutdown outcome.

    Works for both QThread (``.wait(ms)``) and Python ``threading.Thread``
    (``.join(s)``) — the caller's thread contract determines the API used
    (W2-005).
    """
    from fastprompter.core.logging import logger as _log

    try:
        timeout_s = max(0.0, float(timeout_s))
    except (TypeError, ValueError):
        _log.error("%s shutdown FAILED: invalid timeout %r", label, timeout_s)
        return False
    try:
        if hasattr(thread, "wait"):
            stopped = bool(thread.wait(int(timeout_s * 1000)))
        elif hasattr(thread, "join"):
            # W2-005: Python threading.Thread uses join(seconds), not
            # wait(milliseconds). The caller must have already cancelled
            # the thread before calling this.
            thread.join(timeout=timeout_s)
            stopped = not thread.is_alive()
        else:
            _log.error("%s shutdown FAILED: unknown thread type %r",
                        label, type(thread).__name__)
            return False
    except Exception:
        _log.exception("%s shutdown FAILED", label)
        return False
    if stopped:
        _log.info("%s shutdown STOPPED", label)
    else:
        _log.error("%s shutdown TIMED_OUT after %.3f seconds", label, float(timeout_s))
    return stopped


def is_gui_thread():
    """Whether current callback executes on QApplication's owner thread."""
    app = QApplication.instance()
    return app is None or QThread.currentThread() is app.thread()


def sync_shutdown_global():
    """Stop the process-wide sync worker thread at application exit.

    Explicit, bounded, and never reliant on interpreter destruction: the
    thread's event loop is asked to quit and we wait a bounded window. A
    worker stuck in a write cannot be interrupted, so a timeout is accepted
    at app exit (a leak, never a hang).

    The globals are nulled so a mid-session teardown can spawn a fresh worker
    next time; the retired wrappers are kept for the process lifetime so
    Python teardown cannot destroy a worker whose thread was stopped
    mid-reference (an access-violation class).
    """
    global _SYNC_SHARED_WORKER, _SYNC_SHARED_THREAD
    thread = _SYNC_SHARED_THREAD
    worker = _SYNC_SHARED_WORKER
    success = True
    if thread is not None and thread.isRunning():
        thread.quit()
        success = wait_thread_seconds(
            thread, _SYNC_SHUTDOWN_TIMEOUT_S, "Sync worker"
        )
    if success:
        _SYNC_SHARED_WORKER = None
        _SYNC_SHARED_THREAD = None
        if worker is not None or thread is not None:
            _RETIRED_WORKERS.append((worker, thread))
    return success


import threading

_SYNC_WRITE_LOCK = threading.RLock()
_SYNC_REQUEST_LOCK = threading.Lock()
_SYNC_WRITE_SEQ = 0
_SYNC_LATEST_REQUESTED = {}


def _sync_register_snapshot(snapshot):
    """Give a snapshot physical publication ownership for its destinations."""
    global _SYNC_WRITE_SEQ
    with _SYNC_REQUEST_LOCK:
        if snapshot.get("_write_seq") is None:
            _SYNC_WRITE_SEQ += 1
            snapshot["_write_seq"] = _SYNC_WRITE_SEQ
        seq = snapshot["_write_seq"]
        for dest in snapshot.get("files", ()):
            key = os.path.normcase(os.path.abspath(dest))
            _SYNC_LATEST_REQUESTED[key] = max(
                seq, _SYNC_LATEST_REQUESTED.get(key, 0)
            )
    return snapshot


def _sync_snapshot_is_latest(snapshot, dest):
    seq = snapshot.get("_write_seq")
    key = os.path.normcase(os.path.abspath(dest))
    with _SYNC_REQUEST_LOCK:
        return seq is not None and _SYNC_LATEST_REQUESTED.get(key) == seq


def _sync_mechanical_write(snapshot, lock_timeout_s=None):
    """Mechanically writes a sync snapshot, protected by a process-level lock.
    Returns (written: list, errors: list)."""
    _sync_register_snapshot(snapshot)
    written = []
    errors = []
    # Revalidate EVERY destination against the captured root AT MUTATION
    # TIME: a containment decision made at capture can be minutes old, and
    # a junction/symlink swapped in between could otherwise redirect the
    # write outside the root. Reparse-aware, not lexical.
    from fastprompter.utils.path_safety import is_within_captured_root
    root = snapshot.get("root") or ""
    root_identity = snapshot.get("root_identity") or ""

    if lock_timeout_s is None:
        acquired = _SYNC_WRITE_LOCK.acquire()
    else:
        acquired = _SYNC_WRITE_LOCK.acquire(
            timeout=max(0.0, float(lock_timeout_s))
        )
    if not acquired:
        return [], [("", "physical Sync write lock timed out")]
    try:
        for dest, text in snapshot["files"].items():
            if not is_within_captured_root(root, root_identity, dest):
                errors.append((dest, "destination resolves outside the sync "
                                     "root or the captured root changed"))
                continue
            if not _sync_snapshot_is_latest(snapshot, dest):
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                # A newer generation may have arrived while this temp file was
                # written. Stale physical writers may never publish over it.
                key = os.path.normcase(os.path.abspath(dest))
                with _SYNC_REQUEST_LOCK:
                    if _SYNC_LATEST_REQUESTED.get(key) != snapshot.get("_write_seq"):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        continue
                    os.replace(tmp, dest)
                    # PERF-009: this snapshot is still the newest owner of
                    # the destination and has now physically published;
                    # retire the registry entry so the process-global map
                    # stays bounded by current destinations + active work.
                    if _SYNC_LATEST_REQUESTED.get(key) == snapshot.get("_write_seq"):
                        _SYNC_LATEST_REQUESTED.pop(key, None)
                written.append(dest)
            except OSError as exc:
                errors.append((dest, str(exc)))
    finally:
        _SYNC_WRITE_LOCK.release()
    return written, errors

class _SyncWorker(QObject):
    """Writes a captured sync snapshot on its own thread.

    The snapshot is IMMUTABLE: every containment and identity decision (safe
    filesystem names, canonical root check, skip-unchanged) was made on the
    GUI thread at capture time. The worker performs only mechanical atomic
    file writes and reports which paths it wrote; a stale generation is never
    merged into the current cache by the GUI side.

    The dispatch->run connection is made by the factory AFTER moveToThread:
    PyQt captures the receiver's thread affinity at CONNECT time, and a
    self-connection made before moveToThread runs ``_run`` on the GUI thread.
    """

    dispatch = pyqtSignal(object, int)             # snapshot, generation
    done = pyqtSignal(int, object, object, object)  # gen, snapshot, written, errors

    def __init__(self):
        super().__init__()

    def _run(self, snapshot, gen):
        written, errors = _sync_mechanical_write(snapshot)
        self.done.emit(gen, snapshot, written, errors)


class _PortableBackupWorker(QObject):
    """Exports a portable Markdown snapshot on its own thread.

    The snapshot is IMMUTABLE (deep-copied at capture). The connection to the
    run slot is made AFTER moveToThread so the export really happens off the
    GUI save path."""

    dispatch = pyqtSignal(object, int)             # snapshot, generation
    done = pyqtSignal(int, object, bool, object)   # gen, snapshot, ok, error

    def __init__(self):
        super().__init__()

    def _run(self, snapshot, gen):
        from fastprompter.utils import portable_backup as _pb
        try:
            # The snapshot carries the immutable profile_id; the export MUST
            # be namespaced by it, or every Profile-2+ snapshot would publish
            # into Profile-1's legacy flat day directory. Never derive the
            # profile from a second source that could disagree with the
            # snapshot (P0-4).
            profile_id = int(snapshot.get("profile_id", 1))
            _pb._do_export(snapshot, profile_id=profile_id)
            self.done.emit(gen, snapshot, True, None)
        except Exception as exc:
            self.done.emit(gen, snapshot, False, str(exc))


class _PortableBackupCompletionRelay(QObject):
    """GUI-affine owner for portable-backup scheduler completion state."""

    def complete(self, gen, snapshot, ok, err):
        _backup_on_done(gen, snapshot, ok, err)


class _TypoScanWorker(QObject):
    """PERF-005: runs the O(document) typo tokenization + dictionary pass
    on its own thread. The GUI captures an immutable text snapshot plus the
    document revision and silo identity; only a result whose identity AND
    document revision still match may ever paint spans."""

    scan = pyqtSignal(int, str, object)   # request_id, text, dictionary
    scanned = pyqtSignal(int, list)       # request_id, [(start, end), ...]

    def _run(self, request_id, text, dictionary):
        from fastprompter.core import typecheck as tc
        spans = []
        try:
            if len(text) <= 500000:
                spans = [(s, e) for _w, s, e in
                         tc.find_unknown(text, dictionary)]
        except Exception:
            spans = []
        self.scanned.emit(request_id, spans)


class _WatcherArmWorker(QObject):
    """PERF-004: enumerates the recursive watch-directory list OFF the GUI
    thread. The walk + exclude matching is O(project tree); running it
    inline used to hitch every project/profile switch on large trees.

    The result carries the generation token captured at dispatch; a stale
    completion (a newer arm happened meanwhile) is dropped by the GUI side.
    """

    enumerate = pyqtSignal(int, str, list)   # gen, root, exclude patterns
    enumerated = pyqtSignal(int, str, list)  # gen, root, dirs

    def _run(self, gen, root, exclude):
        from fastprompter.core import project_sync as ps
        dirs = [root]
        try:
            for dirpath, dirnames, _files in os.walk(root):
                # PERF-002: cooperative cancellation at directory boundaries. A
                # stale/aborted walk can stop early instead of finishing a whole
                # O(tree) traversal whose result will be discarded anyway.
                if getattr(self, "_cancel", False):
                    return
                dirnames[:] = [d for d in dirnames
                               if not ps.match_exclude(
                                   os.path.relpath(
                                       os.path.join(dirpath, d),
                                       root).replace("\\", "/"),
                                   exclude)]
                dirs.append(dirpath)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("watcher arm enumeration failed", exc_info=True)
        if getattr(self, "_cancel", False):
            return
        self.enumerated.emit(gen, root, dirs)


class _TransactionRefused(RuntimeError):
    """W2-003/W2-004: the FILESYSTEM half of a composite transaction refused
    (collision, missing source, transient OSError). The logical half must
    not commit either — the caller leaves the undo/redo stacks exactly as
    they were so the user can retry."""


class _SyncPushWorker(QObject):
    """T-1039/PERF-004 + CORE-001: performs the mechanical Sync-Project

    Jobs are IMMUTABLE at capture — ONE authoritative 8-field schema used by
    EVERY enqueue/requeue path (fresh bindings, established pushes and
    conflict "app wins" requeues alike, CORE-004):

        ``(key, path, text, eol, expect_digest, lease, max_bytes, had_bom)``

    where ``expect_digest`` is the digest of the content the disk was last
    known to hold, ``lease`` is the binding lease captured at queue time and
    ``had_bom`` is the UTF-8 BOM state the write must preserve.

    Results carry the SAME shape for every status:
        ``(key, path, text, status, detail)``
    where ``detail`` is ``None``, the written text, or a
    ``(disk_text, disk_eol, disk_bom)`` tuple for equal/conflict — the
    CURRENT disk BOM travels with the result so BOM ownership never goes
    stale (CORE-004).

    CORE-001: a queued job is a stale captured intent. Before ANY mutation
    the worker re-reads the file ON THIS THREAD (never the GUI thread) and:

    * rejects the job when its lease is no longer current (unlink/archive/
      repoint/folder change happened meanwhile);
    * skips the write when the disk already equals the desired text
      (PERF-003: equality must not become a physical rewrite);
    * refuses to overwrite and reports ``conflict`` when the disk differs
      from BOTH the expected baseline and the desired text — a two-sided
      edit that only the user may resolve;
    * otherwise performs the atomic replace.

    Ownership decisions that need widgets stay on the GUI completion side.
    """

    dispatch = pyqtSignal(object, object, object)  # jobs, leases dict, commit gate
    done = pyqtSignal(object)       # list of (key, path, text, status, detail)

    def _run(self, jobs, leases, gate):
        from fastprompter.core import project_sync as ps
        # W2-003: a terminal DB restore has committed and the in-memory state
        # is stale. Any job still in flight must NOT publish the stale text to
        # disk — mark it stale (no write) so the restored DB stays authoritative.
        suppress = bool(getattr(self, "_suppress", False))
        results = []
        for job in jobs:
            # CORE-004: schema validation BEFORE destructuring. A malformed
            # job can never again raise outside the per-job try and kill the
            # whole batch (which wedged _push_inflight forever).
            if not (isinstance(job, (tuple, list)) and len(job) == 8):
                from fastprompter.core.logging import logger
                logger.error("sync push job rejected: expected 8-field "
                             "schema, got %d field(s)", len(job) if isinstance(
                                 job, (tuple, list)) else -1)
                continue
            key, path, text, eol, expect, lease, max_bytes, had_bom = job
            try:
                current_lease = leases.get(key, 0) if leases else 0
                if current_lease != (lease or 0):
                    results.append((key, path, text, "stale", None))
                    continue
                if suppress:
                    # W2-003: do not mutate the filesystem with stale RAM.
                    results.append((key, path, text, "stale", None))
                    continue
                cur = ps.read_text_file(path, max_bytes)
                if cur is None:
                    if os.path.exists(path):
                        # binary or unreadable: never overwrite blindly
                        results.append((key, path, text, "gone", None))
                        continue
                    # destination vanished: recreate it with the silo text,
                    # exactly like the historical unconditional write did.
                    # CORE-003: the recreate is itself a filesystem mutation,
                    # so it must pass through the commit gate and re-validate
                    # the lease one final time (invalidating the binding bumps
                    # the lease under the same gate, so a stale job can never
                    # begin/complete the recreate after invalidation).
                    with gate:
                        if leases.get(key, 0) != (lease or 0):
                            results.append(
                                (key, path, text, "stale", None))
                            continue
                        written = ps.write_text_file(
                            path, text, eol, write_bom=had_bom)
                    results.append(
                        (key, path, text,
                         "ok" if written is not None else "error", written))
                    continue
                dtxt, deol, dbom = cur
                if dtxt == text:
                    # CORE-004: equality reports the CURRENT disk BOM too —
                    # a BOM-only metadata change must not go unnoticed.
                    results.append(
                        (key, path, text, "equal", (deol, dbom)))
                    continue
                ddigest = FastPrompter._sync_side_digest(dtxt)
                if expect is not None and ddigest != expect:
                    # two-sided edit: disk moved away from our baseline while
                    # this job was in flight — no silent overwrite
                    results.append(
                        (key, path, text, "conflict", (dtxt, deol, dbom)))
                    continue
                # CORE-003: the physical replace is merged with the final lease
                # check into one ownership operation. A binding invalidation
                # bumps the lease under this same gate; if it already did, no
                # older lease may begin the write once invalidation completes.
                with gate:
                    if leases.get(key, 0) != (lease or 0):
                        results.append((key, path, text, "stale", None))
                        continue
                    written = ps.write_text_file(
                        path, text, eol, write_bom=had_bom)
                results.append(
                    (key, path, text,
                     "ok" if written is not None else "error", written))
            except Exception as exc:
                from fastprompter.core.logging import logger
                logger.warning("sync push write failed for %s: %s", path, exc)
                results.append((key, path, text, "error", None))
        self.done.emit(results)


# Process-wide portable-backup worker + per-profile coalescing state.
#
# Coalescing and throttle are PER PROFILE: a newer snapshot of profile A may
# supersede an older pending snapshot of profile A, but it can never throw
# away a pending snapshot of profile B. Jobs drain FIFO by first-requested
# profile; the single worker runs one job at a time.
_BACKUP_WORKER = None
_BACKUP_THREAD = None
_BACKUP_COMPLETION_RELAY = None
_BACKUP_PENDING = {}          # profile_id -> newest snapshot for that profile
_BACKUP_INFLIGHT = {}         # profile_id -> gen of the job currently running
_BACKUP_NEWEST_GEN = {}       # profile_id -> gen of the newest request seen
_BACKUP_GEN = 0
_BACKUP_LAST_SUCCESS_GEN = 0
_BACKUP_LAST_FAILED_GEN = 0
_BACKUP_SINK_INSTALLED = False
_BACKUP_SHUTDOWN_TIMEOUT_S = 5.0

# Retired worker/thread wrappers kept alive for the process lifetime: Python
# teardown destroying a worker whose thread was stopped mid-reference is an
# access-violation class, and a stopped-thread wrapper that lives until exit
# is clean.
_RETIRED_WORKERS = []


def _backup_ensure_worker():
    global _BACKUP_COMPLETION_RELAY, _BACKUP_WORKER, _BACKUP_THREAD
    if _BACKUP_WORKER is None:
        thread = QThread()
        thread.setObjectName("fastprompter-backup")
        worker = _PortableBackupWorker()
        relay = _PortableBackupCompletionRelay()
        worker.moveToThread(thread)
        worker.dispatch.connect(worker._run)   # AFTER moveToThread: queued
        worker.done.connect(relay.complete)
        thread.start()
        _BACKUP_WORKER = worker
        _BACKUP_THREAD = thread
        _BACKUP_COMPLETION_RELAY = relay
    return _BACKUP_WORKER


def _backup_drain():
    """Start the next queued job, one per profile, FIFO by first-requested
    profile. A job is only started when the worker is idle, so the drain
    never overlaps two jobs on the single worker thread."""
    global _BACKUP_PENDING, _BACKUP_INFLIGHT, _BACKUP_GEN, _BACKUP_NEWEST_GEN
    if _BACKUP_INFLIGHT:
        return
    if not _BACKUP_PENDING:
        return
    profile_id, snap = next(iter(_BACKUP_PENDING.items()))
    del _BACKUP_PENDING[profile_id]
    _BACKUP_GEN += 1
    gen = _BACKUP_GEN
    snap["_gen"] = gen
    _BACKUP_NEWEST_GEN[profile_id] = gen
    _BACKUP_INFLIGHT[profile_id] = gen
    _backup_ensure_worker().dispatch.emit(snap, gen)


def _backup_on_done(gen, snapshot, ok, err):
    """A snapshot finished. Advances only THIS profile's throttle on success;
    a stale or failed completion still drains the newest pending (the sync
    lesson). A failure of one profile never touches another profile's
    throttle or pending queue."""
    global _BACKUP_INFLIGHT, _BACKUP_LAST_FAILED_GEN, _BACKUP_LAST_SUCCESS_GEN
    from fastprompter.core.logging import logger as _log
    from fastprompter.utils import portable_backup as _pb

    if not is_gui_thread():
        _log.critical("portable backup completion rejected outside GUI thread")
        return

    profile_id = int(snapshot.get("profile_id", 1))
    if _BACKUP_INFLIGHT.get(profile_id) == gen:
        del _BACKUP_INFLIGHT[profile_id]

    # CORE-003: retire active marker and, if a newer request was coalesced
    # while this snapshot ran, dispatch the newest snapshot immediately and
    # do NOT establish throttle for the obsolete generation.
    try:
        from fastprompter.utils import portable_backup as _pb2
        _pb2.backup_finished(profile_id=profile_id)
    except Exception:
        from fastprompter.core.logging import logger as _log2
        _log2.exception("portable backup finish hook failed")

    # Whether this completed gen is still the newest outstanding request:
    # check both the worker's newest-gen and any pending queue (including the
    # portable layer's pending data) — an obsolete success must not throttle.
    has_pending_newer = (
        profile_id in _BACKUP_PENDING
        or profile_id in _pb._backup_newer_wanted
        or profile_id in getattr(_pb, "_backup_pending_data", {})
    )
    is_newest = _BACKUP_NEWEST_GEN.get(profile_id) == gen and not has_pending_newer

    if ok:
        _BACKUP_LAST_SUCCESS_GEN = max(_BACKUP_LAST_SUCCESS_GEN, gen)
        if is_newest:
            _pb.mark_backup_success(profile_id=profile_id)
            # PERF-003: the async success represents this snapshot's exported
            # content generation (and today's date) — future settings-only
            # saves with an already-represented generation may skip capture.
            try:
                _pb._mark_exported(profile_id, snapshot.get("_content_gen"))
            except Exception:
                pass
    else:
        _BACKUP_LAST_FAILED_GEN = max(_BACKUP_LAST_FAILED_GEN, gen)
        _log.error("portable backup failed in the worker: %s", err)
        if is_newest:
            _pb.clear_throttle(profile_id=profile_id)

    _backup_drain()


def _portable_backup_dispatch(snapshot):
    """The sink installed into portable_backup: coalesce per profile +
    dispatch async. A newer snapshot of the same profile supersedes an older
    pending one; different profiles are independent jobs."""
    profile_id = int(snapshot.get("profile_id", 1))
    _BACKUP_PENDING[profile_id] = snapshot
    _backup_drain()


def _install_portable_backup_sink():
    """Route portable backups through the shared worker, once per process."""
    global _BACKUP_SINK_INSTALLED
    if _BACKUP_SINK_INSTALLED:
        return
    from fastprompter.utils import portable_backup as _pb
    _pb.set_backup_sink(_portable_backup_dispatch)
    _BACKUP_SINK_INSTALLED = True


def backup_worker_shutdown_global():
    """Bounded shutdown of the portable-backup worker at app exit.

    On clean shutdown globals are nulled so a mid-session teardown can spawn a
    fresh worker. On timeout the live owner remains installed and the caller
    keeps the writer mutex. Retired wrappers are kept process-lifetime:
    Python teardown destroying a worker whose thread was stopped mid-reference
    is an access-violation class, and a stopped-thread wrapper that lives
    until exit is clean.

    Portable backup is secondary; on clean shutdown any pending snapshot is
    intentionally dropped. The primary SQLite database is already committed.
    """
    global _BACKUP_COMPLETION_RELAY, _BACKUP_WORKER, _BACKUP_THREAD
    global _BACKUP_PENDING, _BACKUP_INFLIGHT, _BACKUP_NEWEST_GEN
    thread = _BACKUP_THREAD
    worker = _BACKUP_WORKER
    success = True
    if thread is not None and thread.isRunning():
        thread.quit()
        success = wait_thread_seconds(
            thread, _BACKUP_SHUTDOWN_TIMEOUT_S, "portable backup worker"
        )
    if success:
        _BACKUP_WORKER = None
        _BACKUP_THREAD = None
        _BACKUP_COMPLETION_RELAY = None
        _BACKUP_PENDING = {}
        _BACKUP_INFLIGHT = {}
        _BACKUP_NEWEST_GEN = {}
        if worker is not None or thread is not None:
            _RETIRED_WORKERS.append((worker, thread))
    return success


class FastPrompter(
    QMainWindow,
    CursorMixin,
    FormattingMixin,
    HotkeyMixin,
    ScalingMixin,
    SearchMixin,
    SendSelectionMixin,
    SnippetOpsMixin,
    ThemeMixin,
    TrayMixin,
    WatcherMixin,
    WindowMixin,
):
    # Live settings accessors used by the UI mixins.
    @property
    def _font_size(self):
        try:
            return int(float(self.data.get("font_size", 11)))
        except Exception:
            return 11

    @property
    def _font_family(self):
        """The family to RENDER with.

        Stored value is the plain name the user picked ("Verdana"); this
        resolves it to their crisp "<name>_m1" bitmap build when one is
        installed, so picking Verdana actually paints Verdana_m1. The combo
        box and saved settings keep the plain name — only rendering swaps.
        """
        from fastprompter.utils.fonts import resolve_family
        return resolve_family(self.data.get("font_family", "Verdana"))

    @property
    def _ui_scale(self):
        try:
            return float(self.data.get("ui_scale", 0.5))
        except Exception:
            return 1.0

    @property
    def _button_scale(self):
        try:
            return float(self.data.get("button_scale", 1.0))
        except Exception:
            return 1.0

    @property
    def _sidebar_right(self):
        return self.data.get("sidebar_right", "False") == "True"

    @property
    def _always_on_top(self):
        return self.data.get("always_on_top", "True") == "True"

    @property
    def _normal_window(self):
        return self.data.get("normal_window", "False") == "True"

    @property
    def _tray_visible(self):
        return self.data.get("tray_visible", "True") == "True"


    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        # QApplication.instance().installEventFilter(self)
        self.ignore_focus_loss, self.registered_hotkeys, self._db_dirty = False, [], False
        self._focus_lock_count = 0
        # False until the window has genuinely been in front once;
        # see changeEvent - startup deactivation must not hide it.
        self._ever_activated = False
        # When the window last took the foreground, and whether the user
        # ASKED for it (hotkey / tray) rather than it appearing at launch.
        # changeEvent reads both to tell a click-away from a flicker.
        self._activated_at = 0.0
        self._user_summoned = False

        self.editing_snippet = None
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self._auto_save_tick)
        self.auto_save_timer.start(10000)

        self._preview_connected = False
        self._fancy_zones = FancyZoneOverlay(self)
        self.timers = []
        self._timer_test_jobs = {}   # parented QTimers for Test-notification probes
        self.current_pages, self.silo_page, self.ui_scale = {}, 0, 0.5
        self.arc_silo_page, self.arc_page = 0, 0
        self.is_locked, self._suspend_cache, self._locked_geometry = False, False, None
        self._initializing_ui, self._suspend_temp_sync = True, True

        self.silo_last_edited = {}  # {slot_index: timestamp} for color-last-edited system
        self._visible_silos = 10  # dynamically adjusted
        self._snippet_widget_cache = {}  # {(cat, idx): widget} for O(1) lookup

        self.setup_single_instance_server()
        self.state = FastPrompterState()
        # PERF-001: the GUI build dispatches the throttled .bak refresh to the
        # background worker — a full-database copy+validation must never run
        # on the save critical path (it held State._lock and hitched the UI).
        self.state.background_backups = True
        self.data = self.state.data
        # W2-006: reconcile any crash-consistent retirement journal left
        # by a process death between a folder rename and its in-memory log
        # append. Idempotent; runs before any UI is built.
        try:
            from fastprompter.ui.snippet_ops_mixin import _reconcile_retirement_journal
            _reconcile_retirement_journal(
                self._files_root(), self.data,
                owner_is_live=self._retirement_owner_is_live)
        except Exception:
            from fastprompter.core.logging import logger
            logger.warning("retirement journal reconciliation skipped",
                           exc_info=True)
        from fastprompter.core.timers import load_timers
        self.timers = load_timers(self.data.get("timers"))
        from fastprompter.core.watcher.queue import load_queues
        self.prompt_queues = load_queues(self.data.get("watcher_queues"))
        # on_tab_changed rebinds this to the active category as soon as the
        # UI is up; this is only the pre-UI starting point
        from fastprompter.core.pomodoro import ProductivityTimer
        self.productivity_timer = ProductivityTimer.from_dict(
            self.data.get("productivity_timer"))
        self._pomo_last_tick = None
        self.conn = self.state.conn
        import threading
        self._undo_save_lock = threading.Lock()
        self._undo_save_threads = set()
        self._undo_save_jobs = {}
        self._undo_pending_jobs = {}
        self._undo_save_failed = False
        # T-817: ONE coalescing undo writer. Dispatches feed the newest
        # snapshot per path into `_undo_save_backlog`; a single persistent
        # thread drains it. The condition serializes backlog updates with the
        # writer's wait/exit so a dispatch can never race a dying writer into
        # losing a snapshot.
        self._undo_save_backlog = {}
        self._undo_save_cv = threading.Condition()
        self._undo_save_writer = None
        self._undo_save_quit = False
        self._load_undo_state()
        self.sound_manager = SoundManager(self, self.data)
        # One owner for the sound-event mapping. This was written out here as
        # well, which is how the two copies drift: the module function also
        # heals overrides that point at a file the library no longer has.
        from fastprompter.core.sound_manager import migrate_sound_settings
        migrate_sound_settings(self.data, self.sound_manager._sounds_dir)

        # Ensure cs_style key exists
        if "cs_style" not in self.data:
            self.data["cs_style"] = "False"
        self._theme_cache, self._theme_cache_name = THEMES["Default"], None
        self._custom_colors_cache, self._custom_colors_cache_key = {}, None
        self._font_cache_key, self._cached_main_font = None, None
        try:
            self.active_temp_slot = int(self.data.get("active_temp_slot", 0))
        except Exception:
            self.active_temp_slot = 0
        # Per-category pins/last-edited stores (aliased per tab like
        # temp_presets_all); migrate the old flat keys into the first tab.
        first_cat = (self.data.get("cats_order") or ["Code"])[0]
        pall = self.data.get("pinned_silos_all")
        if not isinstance(pall, dict):
            pall = {}
        if not pall and isinstance(self.data.get("pinned_silos"), list) and self.data["pinned_silos"]:
            pall[first_cat] = list(self.data["pinned_silos"])
        self.data["pinned_silos_all"] = pall
        eall = self.data.get("silo_last_edited_all")
        if not isinstance(eall, dict):
            eall = {}
        if not eall and self.data.get("silo_last_edited"):
            eall[first_cat] = self.data["silo_last_edited"]
        norm = {}
        for c, d in eall.items():
            try:
                norm[c] = {int(k): int(v) for k, v in d.items()}
            except Exception:
                norm[c] = {}
        self.data["silo_last_edited_all"] = norm
        self.silo_last_edited = norm.setdefault(first_cat, {})
        self.data["pinned_silos"] = pall.setdefault(first_cat, [])
        tall = self.data.get("silo_ticked_all")
        if not isinstance(tall, dict):
            tall = {}
        if not tall and isinstance(self.data.get("silo_ticked"), list) and self.data["silo_ticked"]:
            tall[first_cat] = list(self.data["silo_ticked"])
        self.data["silo_ticked_all"] = tall
        self.data["silo_ticked"] = tall.setdefault(first_cat, [])
        # Per-slot unique file-folder names {slot: name} per category
        fdall = self.data.get("silo_folders_all")
        if not isinstance(fdall, dict):
            fdall = {}
        if not fdall and isinstance(self.data.get("silo_folders"), dict) and self.data["silo_folders"]:
            fdall[first_cat] = self.data["silo_folders"]
        self.data["silo_folders_all"] = fdall
        self.data["silo_folders"] = fdall.setdefault(first_cat, {})
        # Silo hierarchy: {parent: [children]} per category; JSON round-trips
        # dict keys as strings — normalize everything back to int.
        call = self.data.get("silo_children_all")
        if not isinstance(call, dict):
            call = {}
        if not call and isinstance(self.data.get("silo_children"), dict) and self.data["silo_children"]:
            call[first_cat] = self.data["silo_children"]
        norm_call = {}
        for c, cmap in call.items():
            try:
                norm_call[c] = {int(k): [int(x) for x in v] for k, v in cmap.items()}
            except Exception:
                norm_call[c] = {}
        self.data["silo_children_all"] = norm_call
        self.data["silo_children"] = norm_call.setdefault(first_cat, {})
        coll_all = self.data.get("silo_collapsed_all")
        if not isinstance(coll_all, dict):
            coll_all = {}
        if not coll_all and isinstance(self.data.get("silo_collapsed"), list) and self.data["silo_collapsed"]:
            coll_all[first_cat] = [int(x) for x in self.data["silo_collapsed"]]
        self.data["silo_collapsed_all"] = coll_all
        self.data["silo_collapsed"] = coll_all.setdefault(first_cat, [])
        # Per-slot project folder/executable links per category. This alias
        # was missing at boot (only wired in on_tab_changed), so on any
        # session where the user never switched tabs, saved paths lived in
        # the flat key only; the moment a tab switch DID happen it got
        # clobbered by the still-empty _all store -> "unreliable" paths.
        ppall = self.data.get("silo_project_paths_all")
        if not isinstance(ppall, dict):
            ppall = {}
        if not ppall and isinstance(self.data.get("silo_project_paths"), dict) and self.data["silo_project_paths"]:
            ppall[first_cat] = self.data["silo_project_paths"]
        self.data["silo_project_paths_all"] = ppall
        self.data["silo_project_paths"] = ppall.setdefault(first_cat, {})
        # Per-slot silo colours per category. `silo_colors_all` has been in
        # the schema (and in the rename/delete remaps) all along, but nothing
        # ever wrote to it and nothing aliased it: the colours lived in the
        # flat key alone, shared by every tab. A silo is identified by its
        # SLOT INDEX, so slot 3's colour followed the user from one tab to
        # the next and landed on whatever silo happened to sit at 3 there -
        # "duplicated into a completely different place", and gone again the
        # moment the other tab's slot 3 was recoloured.
        call_c = self.data.get("silo_colors_all")
        if not isinstance(call_c, dict):
            call_c = {}
        if not call_c and isinstance(self.data.get("silo_colors"), dict) and self.data["silo_colors"]:
            # the existing flat colours were set while looking at some tab;
            # first_cat is the only honest guess, and losing them silently
            # would be worse than putting them on one tab
            call_c[first_cat] = dict(self.data["silo_colors"])
        self.data["silo_colors_all"] = call_c
        self.data["silo_colors"] = call_c.setdefault(first_cat, {})

        # Per-category user-defined sidebar gaps (T-590): a gap renders below
        # the silo whose slot index is listed. Slot-keyed exactly like
        # silo_colors, so the existing reorder/delete remap keeps a gap
        # attached to its position without any code of its own.
        gaps_all = self.data.get("silo_gaps_all")
        if not isinstance(gaps_all, dict):
            gaps_all = {}
        self.data["silo_gaps_all"] = gaps_all
        self.data["silo_gaps"] = gaps_all.setdefault(first_cat, [])
        apall = self.data.get("archive_project_paths_all")
        if not isinstance(apall, dict):
            apall = {}
        if not apall and isinstance(self.data.get("archive_project_paths"), dict) and self.data["archive_project_paths"]:
            apall[first_cat] = self.data["archive_project_paths"]
        self.data["archive_project_paths_all"] = apall
        self.data["archive_project_paths"] = apall.setdefault(first_cat, {})

        # Per-slot silo type ("text", "kanban", "table")
        type_all = self.data.get("silo_type_all")
        if not isinstance(type_all, dict):
            type_all = {}
        if not type_all and isinstance(self.data.get("silo_types"), dict) and self.data["silo_types"]:
            type_all[first_cat] = self.data["silo_types"]
        self.data["silo_type_all"] = type_all
        self.data["silo_types"] = type_all.setdefault(first_cat, {})

        self._current_lang = get_language(self.data)
        self.init_ui()
        self.init_tray()
        self.setup_global_shortcuts()
        self._apply_tooltips()
        # Delay global hotkey binding until after UI initialization to prevent race conditions causing silent crashes (Debater Constraint)
        QTimer.singleShot(100, lambda: not sip.isdeleted(self) and self.register_all_hotkeys())

        self._switch_to_slot(self.active_temp_slot, initial=True)
        self._initializing_ui, self._suspend_temp_sync = False, False
        # ONE profile-runtime application path, shared with change_profile:
        # data-derived state, persisted undo, sound, language, widget values,
        # font/theme, hotkeys, watcher. No second boot implementation.
        self._apply_profile_runtime_state()
        saved_blink = self.data.get("cursor_blink_ms")
        if saved_blink is not None:
            try:
                QApplication.setCursorFlashTime(int(saved_blink))
            except (TypeError, ValueError):
                pass

        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.enforce_topmost)
        if self.data.get("always_on_top", "True") == "True":
            self.topmost_timer.start(30000)

        self.date_timer = QTimer(self)
        self.date_timer.timeout.connect(self._update_date_label)
        self.date_timer.timeout.connect(self._check_timers)
        self.date_timer.start(1000)
        self._update_date_label()

        # --- typecheck (typo checker) ------------------------------------
        # Default OFF (see Settings > Editor > Typos). Debounced so a typing
        # burst runs the dictionary scan once, never per keystroke.
        self._typo_timer = QTimer(self)
        self._typo_timer.setSingleShot(True)
        self._typo_timer.setInterval(450)
        self._typo_timer.timeout.connect(self._typo_check_tick)
        self._typo_dict_cache = None

        # --- Sync-Project / per-silo file links ---------------------------
        # ONE QFileSystemWatcher serves both: the active category's sync
        # folder (project_sync + project_sync_map) and every per-silo linked
        # file (silo_links). Only the ACTIVE category is watched; switching
        # tabs re-arms the path set (_start_project_watcher).
        self._project_sync_watcher = QFileSystemWatcher(self)
        self._project_sync_watcher.fileChanged.connect(self._on_sync_file_changed)
        self._project_sync_watcher.directoryChanged.connect(self._on_sync_dir_changed)
        # external changes are debounced: editors write files in chunks, so a
        # burst of fileChanged signals must coalesce into ONE apply pass
        self._sync_apply_timer = QTimer(self)
        self._sync_apply_timer.setSingleShot(True)
        self._sync_apply_timer.setInterval(350)
        self._sync_apply_timer.timeout.connect(self._apply_external_sync)
        # app->file pushes are debounced too (1.5s after the last keystroke)
        self._sync_push_timer = QTimer(self)
        self._sync_push_timer.setSingleShot(True)
        self._sync_push_timer.setInterval(1500)
        self._sync_push_timer.timeout.connect(self._push_sync_files_active)
        # absolute path -> text we last wrote/applied to that file; used to
        # tell OUR writes apart from external edits
        self._sync_last_applied = {}
        self._sync_pending_apply = False
        self._sync_changed_files = set()
        self._sync_dir_changed = False
        # T-1039/PERF-004: mechanical app->file writes run on a dedicated
        # worker thread; EOL learned at read/apply time is cached per owner.
        self._sync_eol_cache = {}
        # CORE-007: mirror of _sync_eol_cache carrying whether each binding's
        # source file carried a UTF-8 BOM, so an app->file push re-emits it.
        self._sync_bom_cache = {}
        self._push_worker = None
        self._push_thread = None
        self._push_inflight = False
        self._push_jobs_pending = {}
        # CORE-001: binding lease per baseline key. A queued/running push job
        # carries the lease captured at queue time; an ownership transition
        # (unlink, archive, repoint, folder change) bumps the lease so a
        # stale in-flight job is rejected BEFORE it mutates the file.
        self._sync_leases: dict = {}
        # CORE-001: destinations that exist but were rejected as unsafe text
        # (binary, over the size cap, or invalid UTF-8). A fresh binding must
        # never silently overwrite them, so they are flagged and skipped until
        # the file becomes a safe text target again or the binding is replaced.
        self._sync_unsafe_bindings: set = set()
        # CORE-003 commit gate is installed immediately after this block by the
        # audit implementation (see _sync_commit_gate).
        # PERF-004: recursive watch-list enumeration runs on its own worker
        # CORE-003: the single ownership/commit gate shared by the push
        # worker's final filesystem mutation and every binding invalidation.
        import threading as _threading
        self._sync_commit_gate = _threading.Lock()
        self._pw_gen = 0
        self._pw_worker = None
        self._pw_thread = None
        # PERF-002: one-inflight / one-latest-pending arming. A newer re-arm
        # while an enumeration is still walking the tree overwrites the single
        # pending request instead of queuing a whole extra O(tree) walk; the
        # completed walk (if stale) is dropped by the gen check and only the
        # newest pending generation is ever dispatched.
        self._pw_inflight = False
        self._pw_pending = None
        # session-scoped "skip for now" set for two-sided edit conflicts:
        # (owner -> (file_digest, silo_digest)) the user chose not to resolve.
        # As long as neither side changes, no nagging; a change re-prompts.
        self._sync_conflict_skipped: dict = {}

        # --- passed-event attention (red date label) ----------------------
        # One-shot timers that fired and were NOT acknowledged (Dismiss).
        # Snoozing, deleting, disabling or acknowledging removes them;
        # otherwise the date label stays red so a missed event is not
        # forgotten (see missed_attention in core/timers.py).
        self._missed_timer_ids: set = set()

        self.place_window()

    def _clock_time_fmt(self, show_secs=False):
        """strftime format for hh:mm[:ss], honoring the 12h/AM-PM setting."""
        ampm = self.data.get("date_ampm", "False") == "True"
        if ampm:
            return "%I:%M:%S %p" if show_secs else "%I:%M %p"
        return "%H:%M:%S" if show_secs else "%H:%M"

    def _update_date_label(self):
        if hasattr(self, "analog_clock"):
            self.analog_clock.sync()
        show_date = self.data.get("show_date_rect", "True") == "True"
        if not show_date:
            self.lbl_date.setVisible(False)
            return

        self.lbl_date.setVisible(True)
        now = datetime.datetime.now()
        # The full clock (seconds + day word) must fit even at the Ctrl+Q
        # quarter-FullHD snap — dense mode wins the pixels from buttons and
        # paddings, never by silently dropping what the user enabled.
        show_secs = self.data.get("date_seconds", "True") == "True"
        show_word = self.data.get("date_daypart", "True") == "True"
        text_month = self.data.get("date_text_month", "False") == "True"
        ampm = self.data.get("date_ampm", "False") == "True"
        if getattr(self, "_header_ultra", False):
            # portrait sliver: the clock keeps only DD.MM - hh:mm
            show_secs = show_word = text_month = False
        m_fmt = "%d %b" if text_month else "%d.%m"
        t_fmt = self._clock_time_fmt(show_secs)
        dt_str = now.strftime(f"{m_fmt} - {t_fmt}")
        ampm_ref = " PM" if ampm else ""
        if show_secs:
            ref_str = ("00 MMM - 00:00:00" if text_month else "00.00 - 00:00:00") + ampm_ref
        else:
            ref_str = ("00 MMM - 00:00" if text_month else "00.00 - 00:00") + ampm_ref
        if show_word:
            use_emoji = self.data.get("date_emoji", "False") == "True"
            if use_emoji:
                emoji = {"Morning": "🌅", "Day": "☀️", "Evening": "🌇", "Night": "🌙"}.get(self._day_part(now.hour), "")
                dt_str += f" {emoji}"
                ref_str += " ☀️"
            else:
                dt_str += f" · {tr(self._day_part(now.hour), self._current_lang)}"
                ref_str += " · Morning"

        if self.lbl_date.text() != dt_str:
            from PyQt6.QtGui import QFontMetrics
            f = QFont(self.lbl_date.font())
            f.setPixelSize(11)  # the app stylesheet renders 11px regardless of QFont
            fm = QFontMetrics(f)
            pad = 0 if getattr(self, "_header_dense", False) else 8
            needed_width = fm.horizontalAdvance(ref_str) + pad
            if self.lbl_date.minimumWidth() != needed_width:
                self.lbl_date.setMinimumWidth(needed_width)
                self.lbl_date.setMaximumWidth(needed_width + pad)
                from PyQt6.QtCore import Qt
                self.lbl_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_date.setText(dt_str)

        self._apply_date_alert_style()
        self._update_timer_label()

    def _missed_attention(self):
        """One-shot timers that passed and were not acknowledged yet."""
        missed_ids = getattr(self, "_missed_timer_ids", None)
        if missed_ids is None:
            return []  # early init: the alert set does not exist yet
        if not self.data.get("passed_alert_enabled", "True") == "True":
            return []
        try:
            from fastprompter.core.timers import missed_attention
            return missed_attention(getattr(self, "timers", []), missed_ids)
        except Exception:
            return []

    def _apply_date_alert_style(self):
        """Colour the date/time label when a passed event needs attention.

        The colour is user-controllable (``passed_event_color``, default
        reddish). The alert survives density re-layouts because this runs on
        every 1s tick (and after any density flip). Right-click the label to
        clear the alert without touching the timers.
        """
        lbl = getattr(self, "lbl_date", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        pad = "1px" if getattr(self, "_header_dense", False) else "4px"
        missed = self._missed_attention()
        if missed:
            color = self.data.get("passed_event_color", "#e05555") or "#e05555"
            lbl.setStyleSheet(
                f"padding: 0 {pad}; color: {color}; font-weight: bold;")
            tip = tr("Current date and time\nClick to manage timers and limit resets\n"
                     "Shift+Click: add Temp Timer time\n"
                     "Ctrl+Shift+Click: remove Temp Timer",
                     getattr(self, "_current_lang", "EN"))
            n = len(missed)
            tip += "\n" + tr("⚠ {0} passed event(s) not acknowledged — click to manage, right-click to clear",
                             getattr(self, "_current_lang", "EN")).format(n)
            if lbl.toolTip() != tip:
                lbl.setToolTip(tip)
        else:
            lbl.setStyleSheet(f"padding: 0 {pad};")
            base = tr("Current date and time\nClick to manage timers and limit resets\n"
                      "Shift+Click: add Temp Timer time\n"
                      "Ctrl+Shift+Click: remove Temp Timer",
                      getattr(self, "_current_lang", "EN"))
            if lbl.toolTip() != base:
                lbl.setToolTip(base)

    def _date_label_menu(self, pos):
        """Right-click on the date label: manage timers / clear the alert."""
        menu = QMenu(self)
        menu.setFont(QApplication.font())
        lang = getattr(self, "_current_lang", "EN")
        menu.addAction(tr("⏰ Manage timers…", lang), self.open_timer_dialog)
        if self._missed_attention():
            menu.addSeparator()
            menu.addAction(tr("✓ Clear passed-event alert", lang),
                           self._clear_missed_alert)
        menu.exec(self.lbl_date.mapToGlobal(pos))

    def _clock_label_clicked(self, event):
        """Route clock clicks to timer management or Temp Timer actions."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        modifiers = event.modifiers()
        if (modifiers & Qt.KeyboardModifier.ControlModifier
                and modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.remove_temp_timer()
            return
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.add_temp_timer()
            return
        self.open_timer_dialog()

    def _clear_missed_alert(self):
        """Acknowledge every passed event at once (right-click escape hatch)."""
        self._missed_timer_ids.clear()
        self._apply_date_alert_style()

    def _ack_missed(self, timer):
        """The toast's Dismiss button: acknowledge THIS passed event."""
        if timer is not None:
            self._missed_timer_ids.discard(timer.id)
        self._apply_date_alert_style()

    def _update_timer_label(self):
        """Show the soonest timer beside the clock, coloured by urgency."""
        lbl = getattr(self, "lbl_timer", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        from fastprompter.core.duration import format_remaining
        from fastprompter.core.timers import next_due

        # A temporary focus timer is an explicit user activity and owns the
        # countdown spot while it is alive.  It must not mutate or hide the
        # normal alarm that happened to be there before Shift+Click.
        temp = self._temp_timer()
        if (temp is not None and temp.enabled and not temp.fired
                and temp.show_in_top_bar
                and not getattr(self, "_header_ultra", False)):
            rem = temp.remaining()
            text = format_remaining(
                rem, short=getattr(self, "_header_dense", False),
                minutes=self.data.get("timer_show_minutes", "False") == "True")
            if not getattr(self, "_header_dense", False):
                name = temp.name if len(temp.name) <= 14 else temp.name[:13] + "…"
                text = f"{name} {text}"
            lbl.setText(text)
            lbl.setToolTip(
                f"{temp.summary()}\n{temp.target.strftime('%d.%m %H:%M')}\n"
                + tr("Shift+Click the clock to add time\n"
                     "Ctrl+Shift+Click the clock to remove Temp Timer",
                     getattr(self, "_current_lang", "EN")))
            lbl.setStyleSheet(
                f"padding: 0 4px; font-weight: bold; color: {temp.display_color()};")
            lbl.setVisible(True)
            return

        # a running work/break phase outranks a distant alarm: it is the one
        # counting down right now, and it is the one being watched
        pomo = getattr(self, "productivity_timer", None)
        if (pomo is not None and pomo.state != "idle"
                and not getattr(self, "_header_ultra", False)):
            from fastprompter.core.pomodoro import PHASE_BREAK, format_clock
            lbl.setText(format_clock(pomo.remaining))
            lbl.setToolTip(pomo.describe() + "\n" + tr(
                "Click to manage timers", getattr(self, "_current_lang", "EN")))
            colour = "#e0a03c" if pomo.phase == PHASE_BREAK else "#6aa9ff"
            if pomo.alarm_pending:
                colour = "#e05555"
            elif not pomo.running:
                colour = "#888888"
            lbl.setStyleSheet(
                f"padding: 0 4px; font-weight: bold; color: {colour};")
            lbl.setVisible(True)
            return

        nxt = next_due(getattr(self, "timers", []), topbar_only=True)
        if nxt is None or getattr(self, "_header_ultra", False):
            lbl.setVisible(False)
            return
        rem = nxt.remaining()
        short = getattr(self, "_header_dense", False)
        text = format_remaining(
            rem, short=short,
            minutes=self.data.get("timer_show_minutes", "False") == "True")
        if not short:
            name = nxt.name if len(nxt.name) <= 14 else nxt.name[:13] + "…"
            text = f"{name} {text}"
        lbl.setText(text)
        # A rolling window needs to say that it rolls: "in 12m" alone leaves
        # you guessing whether that is the reset or the one after it.
        from fastprompter.core.timers import describe
        tip = [describe(nxt), nxt.target.strftime("%d.%m %H:%M")]
        if nxt.description:
            tip.append(nxt.description)
        tip.append(tr("Click to manage timers",
                      getattr(self, "_current_lang", "EN")))
        lbl.setToolTip("\n".join(tip))
        lbl.setStyleSheet(
            f"padding: 0 4px; font-weight: bold; color: {nxt.display_color()};")
        lbl.setVisible(True)

    def _temp_timer(self):
        """Return the one persisted express/focus timer, if any."""
        return next((t for t in getattr(self, "timers", [])
                     if getattr(t, "temporary", False)), None)

    def temp_timer_template(self):
        """Settings used when Shift+Click creates a fresh temp timer."""
        raw = self.data.get("temp_timer_settings")
        if not isinstance(raw, dict):
            raw = {}

        def flag(key, default):
            value = raw.get(key, default)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() not in {"", "0", "false", "no", "off"}
            return bool(value)

        try:
            increment = max(1, int(raw.get("increment_minutes", 15)))
        except (TypeError, ValueError):
            increment = 15
        try:
            volume = max(0, min(10, int(raw.get("volume", 5))))
        except (TypeError, ValueError):
            volume = 5
        name = raw.get("name")
        description = raw.get("description")
        sound = raw.get("sound")
        color_mode = raw.get("color_mode")
        sound_mode = raw.get("sound_mode")
        rules = raw.get("sound_rules")
        return {
            "name": str(name or "Temp Timer"),
            "description": str(description or ""),
            "increment_minutes": increment,
            "delete_after_fire": flag("delete_after_fire", False),
            "sound": sound if isinstance(sound, str) and sound else "tick",
            "volume": volume,
            "color_mode": color_mode if isinstance(color_mode, str)
            and color_mode in {"temperature", "static"} else "temperature",
            "show_notification": flag("show_notification", True),
            "show_in_top_bar": flag("show_in_top_bar", True),
            "sound_mode": sound_mode if isinstance(sound_mode, str)
            and sound_mode in {"single", "pool"} else "single",
            "sound_rules": [dict(r) for r in (rules if isinstance(rules, list) else [])
                            if isinstance(r, dict)],
        }

    def configure_temp_timer(self, settings):
        """Persist the express timer template and update its live instance."""
        current = self.temp_timer_template()
        current.update(settings or {})
        try:
            current["increment_minutes"] = max(
                1, int(current.get("increment_minutes", 15)))
        except (TypeError, ValueError):
            current["increment_minutes"] = 15
        current["name"] = str(current.get("name") or "Temp Timer")
        current["description"] = str(current.get("description") or "")
        for key, default in (("delete_after_fire", False),
                             ("show_notification", True),
                             ("show_in_top_bar", True)):
            value = current.get(key, default)
            if isinstance(value, str):
                value = value.strip().lower() not in {"", "0", "false", "no", "off"}
            current[key] = bool(value)
        self.data["temp_timer_settings"] = current
        temp = self._temp_timer()
        if temp is not None:
            for key in ("name", "description", "sound", "volume", "color_mode",
                        "show_notification", "show_in_top_bar", "sound_mode",
                        "sound_rules", "delete_after_fire"):
                if key in current:
                    setattr(temp, key, current[key])
            self.save_timers_to_data()
        else:
            self.mark_dirty("settings")

    def add_temp_timer(self, minutes=None, settings=None):
        """Create or extend the one-shot focus timer by *minutes*.

        Existing future time is extended, never replaced. A fired/done temp
        timer is re-armed from now, which makes a later Shift+Click useful.
        """
        from fastprompter.core.timers import Timer
        import datetime as _datetime

        cfg = self.temp_timer_template()
        if settings:
            cfg.update(settings)
            self.configure_temp_timer(cfg)
            cfg = self.temp_timer_template()
        try:
            minutes = max(1, int(minutes or cfg["increment_minutes"]))
        except (TypeError, ValueError):
            minutes = 15
        now = _datetime.datetime.now()
        temp = self._temp_timer()
        if temp is None:
            temp = Timer(
                name=cfg["name"],
                description=cfg["description"],
                target=now + _datetime.timedelta(minutes=minutes),
                repeat="once",
                sound=cfg["sound"],
                volume=cfg["volume"],
                color_mode=cfg["color_mode"],
                show_notification=cfg["show_notification"],
                show_in_top_bar=cfg["show_in_top_bar"],
                sound_mode=cfg["sound_mode"],
                sound_rules=cfg["sound_rules"],
                temporary=True,
                delete_after_fire=cfg["delete_after_fire"],
            )
            self.timers.append(temp)
        elif temp.fired or not temp.enabled:
            temp.target = now + _datetime.timedelta(minutes=minutes)
            temp.fired = False
            temp.enabled = True
        else:
            temp.snooze(minutes, now=now)
        self.save_timers_to_data()
        self._update_timer_label()
        try:
            self.play_sound("timer_start")
        except Exception:
            pass
        return temp

    def remove_temp_timer(self):
        """Remove the express timer, including a completed one."""
        temp = self._temp_timer()
        if temp is None:
            return False
        self.timers = [t for t in self.timers if t is not temp]
        self.save_timers_to_data()
        self._update_timer_label()
        return True

    # (button, normal label, dense label) — dense squeezes into a
    # Ctrl+Q quarter-FullHD window without hiding anything
    _DENSE_LABELS = (
        ("btn_new", "NEW", "NEW"),
        ("btn_save", "Save", "Save"),
        ("btn_clear_fmt", "Clear Fmt", "CF"),
        ("btn_add_line", "Line", "─"),
        ("btn_copy", "Copy", "⧉"),
        ("btn_clear", "Clear", "✕"),
        ("btn_home", "Home", "⇤"),
        ("btn_end", "End", "⇥"),
    )

    def _apply_header_density(self):
        """Pack the header for small windows (Ctrl+Q quarter-FullHD and
        below): hard-clamp text-button widths to their label, shorten the
        widest labels, and let the date clock degrade (day word first,
        then seconds). Nothing gets hidden — only tightened."""
        # A theme change defers this via QTimer.singleShot, so the window can
        # be gone before it runs and self.width() would hit a dead C++ object.
        if sip.isdeleted(self):
            return
        # Compare against the width the header EFFECTIVELY has: at 150% every
        # widget is half again as big, so a 960px window has as much usable
        # room as a 640px one at 100%. Measuring raw pixels kept it in the
        # dense tier there, the header asked for 1085px inside 956, and Qt
        # squeezed the labels - the clipped "NEW" and "21.0" in the report.
        w = self.width()
        try:
            scale = self._effective_scale()
        except Exception:
            scale = 1.0
        # Only correct UPWARDS. Above 100% the widgets really do grow, so a
        # 960px window has the usable room of 640px and must drop a tier.
        # Below 100% they stop shrinking at MIN_BTN_PX and the fixed label
        # widths, so dividing there would claim room that does not exist -
        # measured: at 50% it left the header asking for 1381px inside 956.
        effective = w / scale if scale > 1.0 else w
        dense = effective < 1280
        flipped = getattr(self, "_header_dense", None) != dense
        if flipped:
            self._header_dense = dense
            # Zero: the bar is tinted lighter than the widgets on it, so any
            # spacing showed as a 1px line of tint in EVERY gap - 31 of them,
            # measured. Buttons carry their own borders, so flush is the
            # classic toolbar look rather than a crowded one.
            self.header_layout.setSpacing(0)

        # Ultra tier (portrait / 9:16 slivers): only the essentials survive —
        # tabs, NEW/Save, a short DD.MM - hh:mm clock, line counter, ⚙.
        # Formatting stays reachable via hotkeys and the context menu.
        # Dense hides the ten widgets in _DENSE_HIDDEN — Clear Fmt, Line,
        # Home/End, Underline, Strike, Copy and the three aligns — all
        # reachable from the editor's right-click menu or a hotkey. (This
        # comment used to claim only Clear Fmt and Line were hidden, which
        # made the dense tier look broken whenever someone compared it
        # against the list.) The bullet-toggle stays; it drops only in ultra.
        ultra = effective < 700
        ultra_flipped = getattr(self, "_header_ultra", None) != ultra
        self._header_ultra = ultra

        # Visibility is derived from the CURRENT tier on every pass, and in
        # ONE decision per widget. Gated on a tier flip it depended on the
        # history of flips instead of the width, so a theme change (which
        # resets the cached tier) made buttons vanish that had been visible
        # at that same width. Two loops would not do either: the lists
        # overlap, and "hide for dense" then "show for not-ultra" cancel out.
        # Sizes and labels are deliberately NOT touched here - those still
        # follow `flipped`, because re-applying them every pass resets the
        # button fonts the theme just set.
        if ultra:
            hidden_now = set(self._ULTRA_HIDDEN) | set(self._DENSE_HIDDEN)
        elif dense:
            hidden_now = set(self._DENSE_HIDDEN)
        else:
            hidden_now = set()
        for name in dict.fromkeys(self._DENSE_HIDDEN + self._ULTRA_HIDDEN):
            wdg = getattr(self, name, None)
            if wdg is not None and not sip.isdeleted(wdg):
                wdg.setVisible(name not in hidden_now)
        if hasattr(self, "_counter_sep"):
            self._counter_sep.setVisible(not ultra)
        if ultra_flipped:
            self._update_date_label()

        # widths recompute every pass while dense — the font can change
        # after the flag flips (scale/theme), stale metrics overshoot
        for name, normal, short in self._DENSE_LABELS:
            btn = getattr(self, name, None)
            if btn is None or sip.isdeleted(btn):
                continue
            if flipped:
                btn.setText(short if dense else normal)
            if dense:
                btn.setFixedWidth(clip_safe_width(btn.text(), btn.font()))
            elif flipped:
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
        for name in ("btn_bullet_toggle",):
            bt = getattr(self, name, None)
            if bt is None or sip.isdeleted(bt):
                continue
            if dense:
                bt.setFixedWidth(clip_safe_width(bt.text(), bt.font()))
            elif flipped:
                bt.setMinimumWidth(0)
                bt.setMaximumWidth(16777215)
        if flipped:
            self._update_date_label()
        import os as _os
        if _os.environ.get("FP_DENSITY_DEBUG"):
            from fastprompter.core.logging import logger
            logger.debug(f"DENSITY dense={dense} flipped={flipped} save px={self.btn_save.font().pixelSize()} save minW={self.btn_save.minimumWidth()}")
        if flipped:
            # format squares squeeze 24 -> 20 in dense
            for name in ("btn_bold", "btn_italic", "btn_under", "btn_strike",
                         "btn_header", "btn_settings_toggle", "btn_settings_toggle_right", "btn_help",
                         "btn_pin_top", "btn_line_nums",
                         "btn_add_tab", "btn_del_tab", "btn_sidebar_toggle"):
                btn = getattr(self, name, None)
                if btn is None or sip.isdeleted(btn):
                    continue
                if dense:
                    # 18 was hard-coded, which ignored the UI scale AND the
                    # app's own MIN_BTN_PX floor. At 50% the buttons are
                    # already floored to 20, so squeezing them to 18 put an
                    # 11px glyph in an 18px box with borders - the reported
                    # "chewed up" icons. Scale it, and never go under the
                    # floor that exists to keep glyphs legible.
                    squeezed = max(self.MIN_BTN_PX,
                                   int(round(18 * self._effective_scale())))
                    btn.setFixedSize(squeezed, squeezed)
                else:
                    self.apply_button_size(btn, 24, 24)
            # tabs scroll inside a bounded strip when space is tight
            # (inline QSS re-enables the scroller arrows the theme hides)
            if hasattr(self, "cat_combo"):
                if dense:
                    self.cat_combo.setStyleSheet("")
                    self.cat_combo.setMinimumWidth(0)
                    self.cat_combo.setMaximumWidth(100)
                else:
                    self.cat_combo.setStyleSheet("")
                    self.cat_combo.setMinimumWidth(0)
                    self.cat_combo.setMaximumWidth(16777215)
            if hasattr(self, "lbl_date"):
                self.lbl_date.setStyleSheet(
                    "padding: 0 1px;" if dense else "padding: 0 4px;")
            if hasattr(self, "lbl_line_count"):
                self.lbl_line_count.setStyleSheet(
                    "padding: 0 1px; font-weight: bold;" if dense
                    else "padding: 0 4px; font-weight: bold;")
            if hasattr(self, "_counter_sep"):
                # a couple spare px for the date widget's text-month growth
                self._counter_sep.setFixedSize(1 if dense else 3, 16)
        if flipped or getattr(self, "_last_density_width", None) != w:
            self._last_density_width = w
            self._update_date_label()
            self._update_line_count_label()

        self._enforce_header_priority_fit()
        self._refresh_overflow_button()
        # The density tiers re-set widths and fonts, so the label-fit
        # guarantee has to be re-checked AFTER them — this runs on a 0ms
        # singleShot from apply_theme, i.e. after the theme's own fit pass,
        # and would otherwise silently undo it.
        if hasattr(self, "enforce_button_fit"):
            self.enforce_button_fit()

    # Buttons the density tiers pull out of the header. They stay reachable
    # through the "»" overflow menu — see _refresh_overflow_button.
    # btn_vision is here because the same three modes are always one click
    # away in the settings footer's preview combo — the button is a shortcut,
    # not the only route, so it is fair game for the narrow tier.
    _DENSE_HIDDEN = ("btn_clear_fmt", "btn_add_line", "btn_home", "btn_end",
                     "btn_under", "btn_strike", "btn_copy", "btn_vision",
                     "btn_align_left", "btn_align_center", "btn_align_right")
    _ULTRA_HIDDEN = ("btn_bold", "btn_italic", "btn_under", "btn_strike",
                     "btn_header", "btn_quote",
                     "btn_align_left", "btn_align_center", "btn_align_right",
                     "btn_copy", "btn_clear",
                     "btn_bullet_toggle", "btn_home", "btn_end", "btn_pin_top",
                     "btn_line_nums", "btn_help", "btn_trash", "btn_toggle_search",
                     "btn_arc_snip", "btn_toggle_archive", "btn_toggle_snippets", "btn_project_folder",
                     "btn_project_run", "btn_files")

    # ---- per-silo view state (cursor, selection, scroll, margin marks) ----
    def _silo_state_key(self, slot=None, is_archive=None):
        cat = self.get_current_category() or ""
        if slot is None:
            slot = getattr(self, "active_temp_slot", 0)
        if is_archive is None:
            is_archive = getattr(self, "active_is_archive", False)
        return cat, f"{'a' if is_archive else 's'}{slot}"

    def _silo_state_map(self):
        m = self.data.get("silo_view_state_all")
        if not isinstance(m, dict):
            m = {}
            self.data["silo_view_state_all"] = m
        return m

    def capture_silo_state(self, slot=None, is_archive=None):
        """Remember where the user was in this silo, so coming back lands
        exactly where they left instead of jumping to the top or bottom."""
        # Re-stamp queue lines from their anchors while this document is still
        # in front (T-756): a stale line would mis-fire after the switch.
        self._sync_active_queue_lines()
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return
        cat, key = self._silo_state_key(slot, is_archive)
        if not cat:
            return
        cur = ta.textCursor()
        try:
            marks, heat, folded = ta.collect_view_metadata()
        except Exception:
            marks, heat, folded = {}, {}, []
            
        entry = {
            "anchor": cur.anchor(),
            "pos": cur.position(),
            "scroll": ta.verticalScrollBar().value(),
        }
        if marks:
            entry["marks"] = {str(k): v for k, v in marks.items()}
        if heat:
            entry["heat"] = {str(k): v for k, v in heat.items()}
        if folded:
            entry["folded"] = folded
            
        # Fingerprint the text this cursor belongs to: the saved offsets are
        # only meaningful against the EXACT text they were captured from.
        # restore_silo_state refuses to clamp them into a changed document
        # (T-720), so capture must record what "the same text" means.
        try:
            doc = ta.document()
            current_rev = doc.revision()
            if getattr(ta, "_last_fingerprint_rev", -1) == current_rev:
                entry["text_len"] = ta._last_fingerprint_len
                entry["text_crc"] = ta._last_fingerprint_crc
            else:
                text = doc.toPlainText()
                ta._last_fingerprint_len = len(text)
                ta._last_fingerprint_crc = zlib.crc32(text.encode("utf-8", "replace"))
                ta._last_fingerprint_rev = current_rev
                entry["text_len"] = ta._last_fingerprint_len
                entry["text_crc"] = ta._last_fingerprint_crc
        except Exception as exc:
            from fastprompter.core.logging import logger as _log
            _log.warning("silo state fingerprint update failed: %s", exc)
        m = self._silo_state_map()
        cat_map = m.setdefault(cat, {})
        if cat_map.get(key) != entry:
            cat_map[key] = entry
            self.mark_dirty("settings")

    def restore_silo_state(self, slot=None, is_archive=None):
        """Put the cursor, selection, scroll and margin marks back."""
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return False
        cat, key = self._silo_state_key(slot, is_archive)
        entry = (self._silo_state_map().get(cat) or {}).get(key)
        if not isinstance(entry, dict):
            return False

        try:
            ta.apply_line_marks({int(k): v for k, v in (entry.get("marks") or {}).items()})
        except Exception:
            pass
        try:
            ta.apply_line_heat({int(k): v for k, v in (entry.get("heat") or {}).items()})
        except Exception:
            pass

        # Restore fold state: collapse anchors whose text matches saved list.
        try:
            folded = entry.get("folded")
            if folded and isinstance(folded, list):
                doc = ta.document()
                if doc and not sip.isdeleted(doc):
                    b = doc.begin()
                    while b.isValid():
                        if b.text().strip() in folded and not (max(0, b.userState()) & ta.FOLD_BIT):
                            ta.toggle_fold(b)
                        b = b.next()
        except Exception:
            pass

        doc_len = ta.document().characterCount() - 1
        # T-720: the saved offsets belong to the text they were captured
        # against. If that text changed (an edit between sessions, a reload,
        # an undo that rewrote the doc), clamping the OLD offset into the NEW
        # document lands the caret mid-word. Fall back to the caller's own
        # Start/End rule instead. Entries written before this fingerprint
        # existed carry neither field and keep the old clamp behaviour.
        if "text_len" in entry and "text_crc" in entry:
            try:
                text = ta.document().toPlainText()
                if len(text) != entry["text_len"] or zlib.crc32(
                        text.encode("utf-8", "replace")) != entry["text_crc"]:
                    return False
            except Exception:
                # T-1030: an unreadable fingerprint is a mismatch, not a
                # free pass -- falling through here would apply stale
                # offsets against changed text, the exact bug T-720 guards.
                return False
        try:
            anchor = max(0, min(int(entry.get("anchor", 0)), doc_len))
            pos = max(0, min(int(entry.get("pos", 0)), doc_len))
        except (TypeError, ValueError):
            return False
        if pos == 0 and anchor == 0:
            # marks and heat are already restored above; only the cursor is
            # unset, so let the caller apply its own Start/End rule
            return False

        cur = ta.textCursor()
        cur.setPosition(anchor)
        if pos != anchor:  # a real selection, not just a caret
            cur.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
        else:
            cur.setPosition(pos)
        ta.setTextCursor(cur)
        try:
            ta.verticalScrollBar().setValue(int(entry.get("scroll", 0)))
        except (TypeError, ValueError):
            pass
        return True

    # ---- timers / limit resets ---------------------------------------
    def save_timers_to_data(self):
        from fastprompter.core.timers import save_timers
        self.data["timers"] = save_timers(self.timers)
        self.mark_dirty("settings")

    def save_productivity_timer(self):
        self.data["productivity_timer"] = self.productivity_timer.to_dict()
        self.mark_dirty("settings")

    def on_productivity_changed(self):
        """Anything that starts, pauses or resets it lands here."""
        self._pomo_last_tick = None      # don't bill the user for idle time
        self.save_productivity_timer()
        self._update_timer_label()

    def _tick_productivity(self):
        """Advance the work/break timer from the same 1s tick as the clock.

        Fed real elapsed time rather than a flat second: if the app stalls or
        the machine sleeps, the countdown must still be right afterwards.
        """
        timer = getattr(self, "productivity_timer", None)
        if timer is None:
            return
        import time as _t
        now = _t.monotonic()
        last, self._pomo_last_tick = self._pomo_last_tick, now
        if not timer.running:
            return
        if last is None:
            return                        # first tick after starting
        for phase in timer.tick(now - last):
            self._notify_productivity(phase)
        self.save_productivity_timer()

    def _notify_productivity(self, phase):
        """Sound + popup when a work or break phase ends."""
        from fastprompter.core.pomodoro import PHASE_WORK
        lang = getattr(self, "_current_lang", "EN")
        title = (tr("Work phase over", lang) if phase == PHASE_WORK
                 else tr("Break over", lang))
        try:
            self.play_sound("clear")
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("productivity sound failed")
        try:
            if hasattr(self, "tray_icon") and not sip.isdeleted(self.tray_icon):
                self.tray_icon.showMessage(
                    title, self.productivity_timer.describe(),
                    self.tray_icon.icon(), 10000)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("productivity notification failed")

    # ---- prompt queue -------------------------------------------------
    def save_prompt_queues(self):
        """Write the queues back, per category.

        Every other slot-keyed map is stored as `<key>_all[category]` and
        rebound on a tab change; a queue that skipped that would follow the
        user across categories and show another tab's backlog.
        """
        # Re-stamp the active silo's item lines from their anchors BEFORE the
        # numbers go stale in the store (T-756).
        self._sync_active_queue_lines()
        from fastprompter.core.watcher.queue import save_queues
        raw = save_queues(self.prompt_queues)
        self.data["watcher_queues"] = raw
        cat = self.get_current_category() or ""
        # Must be a dict to index into. An older build wrote this key as
        # str(dict) (it was missing from state.py's json save list), so a DB
        # from then reloads it as a STRING and one Alt+C died here with
        # "'str' object does not support item assignment". Heal it in place
        # rather than trusting the load path alone.
        bucket = self.data.get("watcher_queues_all")
        if not isinstance(bucket, dict):
            bucket = {}
            self.data["watcher_queues_all"] = bucket
        bucket[cat] = raw
        # PERF-002: queue data is in the settings JSON domain
        self.mark_dirty("settings")

    def _queue_slot_key(self):
        """Which silo's queue Alt+C fills. Archive silos keep their own."""
        slot = getattr(self, "active_temp_slot", 0)
        prefix = "a" if getattr(self, "active_is_archive", False) else ""
        return f"{prefix}{slot}"

    def _sync_active_queue_lines(self):
        """Resolve every anchored queue item's LIVE line and text before the
        document is left or persisted (T-756).

        An item is anchored to its BLOCK, so editing above it does not break
        the reference — but ``item.line`` is a 1-based snapshot that goes
        stale the moment lines shift. An inactive silo resolves by line
        number, so a stale line sends the WRONG text after a switch. The
        block is the truth; re-stamp line + text from it while we still can.
        """
        try:
            queue = self.prompt_queues.get(self._queue_slot_key())
            if not queue:
                return
            blocks = self.text_area.blocks_for_queue_items([item.id for item in queue])
            for item in queue:
                block = blocks.get(item.id)
                if block is not None:
                    item.line = block.blockNumber() + 1
                    item.text = block.text().strip()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("queue line sync failed", exc_info=True)

    def queue_current_line(self):
        """Alt+C: put the line under the caret into this silo's queue.

        The item is anchored to the BLOCK, not to a line number, so editing
        the note above it does not point the queue at the wrong text.
        """
        from fastprompter.core.watcher.queue import QueueItem, queue_for

        text, block = self.text_area.queue_current_line()
        if not text:
            return None

        item = QueueItem(text,
                         skill=self.data.get("watcher_skill", ""),
                         line=block.blockNumber() + 1)
        queue_for(self.prompt_queues, self._queue_slot_key()).append(item)
        self.text_area.set_queue_anchor(block, item.id)
        self.save_prompt_queues()
        self.play_click_sound()
        return item

    def silo_queue_label(self, slot):
        """A silo's name for the master view: its first non-empty line.

        The text comes from `temp_presets` rather than from a document,
        because silo_docs are created lazily and most silos have none.
        """
        presets = self.data.get(
            "archive_temp_presets" if str(slot).startswith("a") else "temp_presets") or []
        index = int(str(slot).lstrip("a") or 0)
        if not (0 <= index < len(presets)):
            return f"Silo {index + 1}"
        raw = presets[index] or ""
        first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        if first.startswith("#"):
            first = first.lstrip("#").lstrip()
        return first[:48] or f"Silo {index + 1}"

    def silo_queue_labels(self):
        return {slot: self.silo_queue_label(slot) for slot in self.prompt_queues}

    def queue_items_live_text(self, slot, items):
        """The text these items would send right now, resolved in a single batch.
        Returns {item: (text, detached)}."""
        result = {}
        active = (str(slot) == self._queue_slot_key())
        
        if active:
            blocks = self.text_area.blocks_for_queue_items([item.id for item in items])
            for item in items:
                block = blocks.get(item.id)
                if block is not None:
                    text = block.text().strip()
                    result[item] = (text or item.text, False)
                else:
                    # A snapshot item (line 0, e.g. one moved in from another silo)
                    # owns its text even with no anchor in the document; only a
                    # source-referenced item whose block is gone is detached (T-756).
                    result[item] = (item.text, bool(item.line))
            return result

        presets = self.data.get(
            "archive_temp_presets" if str(slot).startswith("a") else "temp_presets") or []
        index = int(str(slot).lstrip("a") or 0)
        lines = None
        if 0 <= index < len(presets):
            lines = (presets[index] or "").splitlines()
            
        for item in items:
            if lines is not None and item.line:
                if 0 < item.line <= len(lines):
                    text = lines[item.line - 1].strip()
                    if text:
                        result[item] = (text, False)
                        continue
            # Nothing to read it from. A source-referenced item (line > 0) that
            # cannot be resolved is DETACHED — a stale snapshot is not live and
            # must not be sent as if it were (T-756). A snapshot item (line 0,
            # usually moved in from elsewhere) has no source, so it survives.
            result[item] = (item.text, bool(item.line))
            
        return result

    def queue_item_live_text(self, slot, item):
        """The text this item would send right now."""
        return self.queue_items_live_text(slot, [item])[item]

    def open_queue_dialog(self, master=False):
        """Open the prompt-queue panel.

        `master=True` lands on the "All silos" tab — the cross-silo view
        reachable from inside the dialog.
        """
        from fastprompter.ui.queue_panel import QueueDialog
        self._increment_focus_lock()
        try:
            QueueDialog(self, start_tab=1 if master else 0).exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
        self.save_prompt_queues()

    def open_queue_master(self):
        """Alt+Shift+C: open the prompt queue on the All Silos tab."""
        self.open_queue_dialog(master=True)

    # ---- hashtags -----------------------------------------------------
    def open_hashtag_dialog(self, tag=None):
        from fastprompter.ui.hashtag_dialog import HashtagDialog
        self._increment_focus_lock()
        try:
            HashtagDialog(self, tag).exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)

    def jump_to_silo_line(self, silo_idx, line_no):
        """Open a silo and put the caret on a 1-based line."""
        presets = self.data.get("temp_presets") or []
        if not (0 <= silo_idx < len(presets)):
            return False
        if silo_idx != getattr(self, "active_temp_slot", -1):
            self._switch_to_slot(silo_idx)
        block = self.text_area.document().findBlockByNumber(max(0, line_no - 1))
        if not block.isValid():
            return False
        cursor = QTextCursor(block)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        return True

    def open_timer_dialog(self, initial_tab: int | str = 0):
        from fastprompter.ui.timer_dialog import TimerDialog
        self._increment_focus_lock()
        try:
            TimerDialog(self, initial_tab=initial_tab).exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
        self.save_timers_to_data()
        self.save_productivity_timer()
        self._update_date_label()

    # ---- Interval Notifications (user-declared recurring reminders) ----
    # Deliberately OUTSIDE the timer model: these never appear in the main
    # timer list, never toast by default, and never touch timer persistence.

    _INTERVAL_NOTIF_DEFAULT = {
        "id": "interval_default_1",
        "name": "Hourly Reminder",
        "minutes": 60,
        "enabled": True,
        "sound": "newday",
        "volume": 1,
        "show_notification": False,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
        "last_fired": 0.0,
        "last_fired_minute": "",
    }

    def _interval_notifs(self):
        rules = self.data.get("interval_notifs")
        if not isinstance(rules, list):
            rules = [dict(self._INTERVAL_NOTIF_DEFAULT)]
            self.data["interval_notifs"] = rules
            self.mark_dirty()
        return rules

    def _check_interval_notifs(self):
        """Fire every enabled rule whose interval has elapsed or reached
        its clock boundary. Runs on the same 1s tick as the clock."""
        try:
            rules = self._interval_notifs()
        except Exception:
            return
        import datetime as _dt
        import time as _time

        now_dt = _dt.datetime.now()
        now_ts = _time.time()
        minute_key = now_dt.strftime("%Y-%m-%d %H:%M")
        minute_of_day = now_dt.hour * 60 + now_dt.minute

        dirty = False
        # Topmost priority: collect all that would fire this second, fire only first
        candidates = []
        for idx, rule in enumerate(rules):
            try:
                if not rule.get("enabled"):
                    continue
                # Active hours check (if not all-day)
                if not rule.get("all_day", True):
                    start_m = int(rule.get("start_minute", 0))
                    end_m = int(rule.get("end_minute", 1439))
                    if start_m <= end_m:
                        if not (start_m <= minute_of_day <= end_m):
                            continue
                    else:
                        if not (minute_of_day >= start_m or minute_of_day <= end_m):
                            continue

                minutes = max(1, int(rule.get("minutes") or 60))
                align_mode = str(rule.get("align_mode", "clock"))

                would_fire = False
                if align_mode == "clock":
                    if minutes <= 60 and 60 % minutes == 0:
                        if now_dt.minute % minutes == 0 and now_dt.second == 0:
                            if rule.get("last_fired_minute") != minute_key:
                                would_fire = True
                    elif minutes % 60 == 0:
                        hours = minutes // 60
                        if now_dt.minute == 0 and now_dt.second == 0 and now_dt.hour % hours == 0:
                            if rule.get("last_fired_minute") != minute_key:
                                would_fire = True
                else:
                    last = float(rule.get("last_fired") or 0.0)
                    if last == 0.0:
                        rule["last_fired"] = now_ts
                        dirty = True
                        continue
                    if now_ts - last >= minutes * 60.0:
                        would_fire = True
                if would_fire:
                    candidates.append((idx, rule))
            except Exception:
                from fastprompter.core.logging import logger
                logger.debug("interval notification failed", exc_info=True)
        if candidates:
            # sort by original order (topmost first) — list is already in order
            candidates.sort(key=lambda x: x[0])
            winner = candidates[0][1]
            winner["last_fired"] = now_ts
            if winner.get("align_mode", "clock") == "clock":
                winner["last_fired_minute"] = minute_key
            dirty = True
            self._fire_interval_notif(winner)
            # suppress lower-priority colliding rules for this tick
            for _, r in candidates[1:]:
                r["last_fired"] = now_ts
                if r.get("align_mode", "clock") == "clock":
                    r["last_fired_minute"] = minute_key
                dirty = True
        if dirty:
            self.mark_dirty()

    def _fire_interval_notif(self, rule):
        """Sound (default newday @ vol 0.5) + optional notification."""
        ref = str(rule.get("sound") or "newday")
        try:
            raw = rule.get("volume", 0.5)
            fv = float(raw)
            if fv > 1.0 and fv <= 10.0 and float(fv).is_integer():
                fv = fv / 10.0
            level = max(0.0, min(1.0, fv))
        except (TypeError, ValueError):
            level = 0.5
        self.sound_manager.play_sound_ref(ref, level)
        if rule.get("show_notification"):
            try:
                from PyQt6.QtWidgets import QSystemTrayIcon
                if (getattr(self, "tray_icon", None)
                        and QSystemTrayIcon.isSystemTrayAvailable()):
                    self.tray_icon.showMessage(
                        str(rule.get("name") or "Hourly Reminder"),
                        tr("Interval reached", self._current_lang),
                        QSystemTrayIcon.MessageIcon.Information, 4000)
            except Exception:
                pass

    def _check_timers(self):
        """Fire anything due. Called from the same 1s tick as the clock."""
        tick_pomo = getattr(self, "_tick_productivity", None)
        if callable(tick_pomo):
            try:
                tick_pomo()
            except Exception:
                pass
        chk_interval = getattr(self, "_check_interval_notifs", None)
        if callable(chk_interval):
            try:
                chk_interval()
            except Exception:
                pass
        from fastprompter.core.timers import collect_due

        if not getattr(self, "timers", None):
            return
        now = datetime.datetime.now()
        due = collect_due(self.timers, now)
        if not due:
            return
        self.save_timers_to_data()
        for t in due:
            # The SAME clock sample drives sound-time selection and firing,
            # so a repeating timer (already advanced to its NEXT occurrence by
            # collect_due) is judged against the moment it actually went off.
            try:
                self._notify_timer(t, fired_at=now)
            except Exception:
                # T-1007: one bad timer must never swallow the rest of the
                # due batch — its sound/notification failing is its problem.
                from fastprompter.core.logging import logger
                logger.debug("timer notification failed for %s", t.name)
            if (getattr(t, "temporary", False)
                    and getattr(t, "delete_after_fire", False)):
                self.timers = [live for live in self.timers if live.id != t.id]
                self._missed_timer_ids.discard(t.id)
        if any(getattr(t, "temporary", False)
               and getattr(t, "delete_after_fire", False) for t in due):
            self.save_timers_to_data()
        # Tiny timer fakes and headless integrations may implement firing
        # without the top-bar widget; firing must not depend on that view.
        updater = getattr(self, "_update_timer_label", None)
        if updater is not None:
            updater()

    def _notify_timer(self, timer, fired_at=None):
        """Sound + an actionable popup. Never steals focus mid-typing.

        The two behaviour toggles are independent:
          * show_notification False -> no toast AND no tray fallback (one
            switch means the visual notification is off everywhere).
          * show_in_top_bar False -> still fires and may still notify; only
            the top-bar countdown is suppressed.
        Sound is chosen by the timer's own policy and played through the
        explicit-volume path, so it never mutates the global sound settings.
        """
        fired_at = fired_at or datetime.datetime.now()
        self._play_timer_sound(timer, fired_at)
        from fastprompter.core.timers import REPEAT_NONE
        # The red date alert is a state indicator, not a duplicate of the
        # popup. A calendar event still needs attention when the user chose
        # silent notifications, so register it before the popup early-return.
        if timer.repeat == REPEAT_NONE:
            missed = getattr(self, "_missed_timer_ids", None)
            if missed is not None:
                missed.add(timer.id)
        if not timer.show_notification:
            # visual notification intentionally off — no popup, no tray
            return
        from fastprompter.ui.timer_toast import show_toast
        # A fired ONE-SHOT timer whose moment passed enters the "missed" set:
        # the date label turns red (user-chosen colour) until the event is
        # snoozed, deleted, disabled or explicitly acknowledged (Dismiss).
        # Repeating timers are never "missed" — they roll to their next
        # occurrence and the top bar shows that instead.
        toast = show_toast(self, timer, on_snooze=self._snooze_timer,
                           on_dismiss=getattr(self, "_ack_missed", None))
        if toast is None:
            # popup unavailable (no screen / teardown) — fall back to the tray
            try:
                if hasattr(self, "tray_icon") and not sip.isdeleted(self.tray_icon):
                    lang = getattr(self, "_current_lang", "EN")
                    self.tray_icon.showMessage(
                        tr("Timer", lang), timer.summary(),
                        self.tray_icon.icon(), 10000)
            except Exception:
                from fastprompter.core.logging import logger
                logger.debug("timer tray notification failed")

    def _play_timer_sound(self, timer, fired_at=None) -> bool:
        """Select and play the timer's sound through the ONE canonical path.

        Picks the sound with ``choose_timer_sound`` (single sound or the
        random pool) and plays it via the explicit-volume ``play_sound_ref``,
        which never mutates the global sound settings. Returns False when the
        timer is silent (empty pool / no eligible rule) or playback failed.
        """
        fired_at = fired_at or datetime.datetime.now()
        from fastprompter.core.timers import choose_timer_sound
        choice = choose_timer_sound(timer, fired_at)
        if choice is None:
            return False
        ref, level = choice
        return self.sound_manager.play_sound_ref(ref, level)

    def _snooze_timer(self, timer, minutes):
        """Snooze a fired timer from its toast.

        A fired REPEATING timer has already advanced to its NEXT occurrence
        (collect_due rolls it before the toast shows), so snoozing the object
        itself would shift the whole series. A one-shot reminder is created
        for THIS occurrence and the series is left alone; one-shot timers
        keep the legacy re-arm behaviour.

        Refuses timers that are no longer owned by the current profile: an
        old profile's toast must never mutate the new profile's data.
        """
        if timer not in self.timers:
            return
        from fastprompter.core.timers import REPEAT_NONE, snooze_clone
        if timer.repeat != REPEAT_NONE:
            clone = snooze_clone(timer, minutes)
            self.timers.append(clone)
        else:
            # re-arming the SAME timer: it is no longer a missed passed event
            missed = getattr(self, "_missed_timer_ids", None)
            if missed is not None:
                missed.discard(timer.id)
            timer.snooze(minutes)
        self.save_timers_to_data()
        self._update_date_label()

    def test_timer_notification(self, timer, delay_seconds=5):
        """Fire a throwaway copy shortly, so the user can check sound and
        popup before trusting a real timer to it.

        Copies the FULL behaviour (sound, volume, sound_mode, pool rules,
        show_notification, colour) so the preview is honest. It is never
        persisted. If Show notification is OFF the probe is still built — the
        timer's own toggle decides whether the test pops a window, exactly as
        a real fire would: a notification-off test is a sound-only check.
        """
        import datetime

        from fastprompter.core.timers import Timer

        lang = getattr(self, "_current_lang", "EN")
        probe = Timer(
            name=timer.name or tr("Test", lang),
            description=timer.description or tr("Test notification", lang),
            target=datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds),
            repeat=timer.repeat,
            sound=timer.sound,
            volume=timer.volume,
            color_mode=timer.color_mode,
            color=timer.color,
            kind=timer.kind,
            show_notification=timer.show_notification,
            show_in_top_bar=timer.show_in_top_bar,
            sound_mode=timer.sound_mode,
            sound_rules=[dict(r) for r in timer.sound_rules],
        )
        # deliberately NOT added to self.timers — a test must not survive a
        # restart or show up in the countdown beside the clock
        delay_ms = max(0, int(delay_seconds * 1000))
        job = QTimer(self)                 # parented: destroyed with the window
        job.setSingleShot(True)
        job.timeout.connect(lambda: self._fire_timer_test_job(job))
        job.start(delay_ms)
        # the probe's identity is bound to the PROFILE that pressed Test: if
        # the profile switches before the job fires, the notification must
        # not land in the new profile
        self._timer_test_jobs[job] = (probe, id(self.data))
        return probe

    def _fire_timer_test_job(self, job):
        """Deliver a Test notification, unless the profile moved on."""
        entry = self._timer_test_jobs.pop(job, None)
        if entry is None:
            return
        probe, data_id = entry
        if data_id != id(self.data):
            return                    # profile switched since Test was pressed
        try:
            self._notify_timer(probe)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("timer test notification failed")

    def _cancel_timer_test_jobs(self):
        """Retire every pending Test notification (profile switch, shutdown)."""
        jobs = getattr(self, "_timer_test_jobs", None)
        if not jobs:
            return
        for job in list(jobs):
            try:
                job.stop()
            except RuntimeError:
                pass
        jobs.clear()

    def _fit_settings_tabs(self, index=None):
        """Size the settings tabs to the page actually on screen."""
        tabs = getattr(self, "settings_tabs", None)
        if tabs is None or sip.isdeleted(tabs):
            return
        if index is None:
            index = tabs.currentIndex()
        for i in range(tabs.count()):
            page = tabs.widget(i)
            if page is None:
                continue
            if i == index:
                policy = QSizePolicy(QSizePolicy.Policy.Preferred,
                                     QSizePolicy.Policy.Maximum)
                policy.setHeightForWidth(True)
                page.setSizePolicy(policy)
            else:
                page.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Ignored)
        # sizeHint() can't know the width, and a wrapping layout's height
        # depends entirely on it — so measure the visible page at the width
        # it actually has and cap the tabs there.
        page = tabs.currentWidget()
        if page is not None and page.layout() is not None:
            inner = page.layout()
            # Measure against the widest thing that already knows its size.
            # tabs.width() is ~100px while the window is still being built,
            # and a FlowLayout measured at 100px answers with the height of a
            # single tall column — which then became the panel's maximum.
            frame = getattr(self, "mini_settings_frame", None)
            widths = [tabs.width()]
            if frame is not None and not sip.isdeleted(frame):
                widths.append(frame.width() - 8)
            widths.append(self.width() - 16)
            avail = max(120, max(widths) - 12)
            try:
                needed = inner.totalHeightForWidth(avail)
            except (AttributeError, TypeError):
                needed = page.sizeHint().height()
            bar = tabs.tabBar().sizeHint().height() if tabs.tabBar() else 24
            tabs.setMaximumHeight(max(60, needed + bar + 10))
        tabs.updateGeometry()

        # The footer's own wrapping row has to be re-measured too. It is a
        # FlowLayout, so its height is a function of a width it only learns
        # when the frame is laid out — and on the FIRST fit it is still
        # carrying the height it had at the previous width. Measured: 194px
        # of footer against a 163px hint on the Window tab, i.e. ~100px of
        # dead panel under the checkboxes, which is precisely the complaint
        # T-605 was filed for and precisely what a single pass cannot see.
        frame = getattr(self, "mini_settings_frame", None)
        if frame is None or sip.isdeleted(frame):
            return
        for child in frame.children():
            # children() also hands back LAYOUTS, which have no geometry of
            # their own — the first cut of this crashed on QVBoxLayout
            if not isinstance(child, QWidget):
                continue
            inner = child.layout()
            if inner is not None and inner.hasHeightForWidth():
                inner.invalidate()
                child.updateGeometry()
        if frame.layout() is not None:
            frame.layout().invalidate()
            frame.layout().activate()

    def pick_hover_colour(self):
        from PyQt6.QtWidgets import QColorDialog

        current = self.data.get("hover_line_color", "auto")
        start = QColor(current) if QColor(current).isValid() else QColor("#6aa9ff")
        self._increment_focus_lock()
        try:
            chosen = QColorDialog.getColor(start, self, tr(
                "Hover line colour", getattr(self, "_current_lang", "EN")))
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
        if chosen.isValid():
            self.data["hover_line_color"] = chosen.name()
            self.mark_dirty()
            self.text_area.viewport().update()

    def reset_hover_colour(self):
        """Back to following the theme accent."""
        self.data["hover_line_color"] = "auto"
        self.mark_dirty()
        self.text_area.viewport().update()

    def _sync_snippets_toggle_button(self):
        btn = getattr(self, "btn_toggle_snippets", None)
        if btn is None or sip.isdeleted(btn):
            return
        hidden = self.data.get("snippets_hidden", "False") == "True"
        if btn.isChecked() != hidden:
            btn.blockSignals(True)
            btn.setChecked(hidden)
            btn.blockSignals(False)

    def toggle_snippets_panel(self):
        """Hide/show the snippets panel and make it stick across refreshes."""
        hidden = self.data.get("snippets_hidden", "False") != "True"
        self.data["snippets_hidden"] = "True" if hidden else "False"
        # write it straight into this project's session, so it survives a
        # restart even if the user never switches projects afterwards
        self.capture_silo_session()
        self.play_tick_sound(not hidden)
        self.mark_dirty()
        self.refresh_snippets_panel()
        self._sync_snippets_toggle_button()

    def save_line_marks(self):
        """Called by the editor whenever a margin mark changes."""
        self.capture_silo_state()
        # PERF-002: line marks are view metadata (settings domain)
        self.mark_dirty("settings")

    def _apply_code_font(self):
        """Code blocks default to Consolas; opt out to use the editor font.

        Forced monospace looks wrong next to Verdana body text, so
        `code_monospace = False` renders code in whatever font the user
        actually picked.
        """
        hl = getattr(self, "highlighter", None)
        if hl is None or sip.isdeleted(hl):
            return
        mono = self.data.get("code_monospace", "True") == "True"
        hl.update_code_font(None if mono else self._font_family)

    def _overflow_hidden_buttons(self):
        """Header buttons currently pulled out by the density tiers."""
        out = []
        for name in dict.fromkeys(self._ULTRA_HIDDEN + self._DENSE_HIDDEN):
            btn = getattr(self, name, None)
            if btn is None or sip.isdeleted(btn) or not btn.isHidden():
                continue
            if not btn.isEnabled():
                continue
            out.append((name, btn))
        return out

    def _refresh_overflow_button(self):
        """Show '»' only while something is actually hidden."""
        btn = getattr(self, "btn_overflow", None)
        if btn is None or sip.isdeleted(btn):
            return
        btn.setVisible(bool(self._overflow_hidden_buttons()))

    # Short menu labels. Tooltips are written to explain a button to someone
    # who has never seen it ("Files—asset drawer for the active silo (drop in
    # / drag out /…"), which reads like a wall of text in a menu — these are
    # the two-word versions, grouped so related actions sit together.
    _OVERFLOW_LABELS = (
        ("btn_bold", "Bold"),
        ("btn_italic", "Italic"),
        ("btn_under", "Underline"),
        ("btn_strike", "Strikethrough"),
        ("btn_header", "Header"),
        ("btn_quote", "Quote"),
        ("btn_align_left", "Align left"),
        ("btn_align_center", "Align center"),
        ("btn_align_right", "Align right"),
        ("btn_bullet_toggle", "Bullets"),
        ("btn_clear_fmt", "Clear formatting"),
        ("btn_add_line", "Insert divider"),
        (None, None),  # separator
        ("btn_copy", "Copy all"),
        ("btn_clear", "Clear text"),
        ("btn_home", "Go to start"),
        ("btn_end", "Go to end"),
        (None, None),
        ("btn_toggle_search", "Search"),
        ("btn_files", "Files"),
        ("btn_project_folder", "Project folder"),
        ("btn_project_run", "Run project"),
        (None, None),
        ("btn_toggle_snippets", "Show snippets"),
        ("btn_arc_snip", "Archive this"),
        ("btn_toggle_archive", "Show archive"),
        ("btn_trash", "Trash"),
        (None, None),
        ("btn_pin_top", "Always on top"),
        ("btn_line_nums", "Line numbers"),
        ("btn_help", "Help"),
    )

    def _show_overflow_menu(self):
        """Every button the narrow header dropped, in one popup.

        Without this the formatting/navigation buttons are simply gone below
        700px — reachable only if you happen to know the hotkey.
        """
        from PyQt6.QtWidgets import QMenu

        hidden = dict(self._overflow_hidden_buttons())
        if not hidden:
            return
        lang = getattr(self, "_current_lang", "EN")
        menu = QMenu(self)
        pending_sep = False
        for name, label in self._OVERFLOW_LABELS:
            if name is None:
                pending_sep = bool(menu.actions())
                continue
            btn = hidden.pop(name, None)
            if btn is None:
                continue
            if pending_sep:
                menu.addSeparator()
                pending_sep = False
            act = menu.addAction(tr(label, lang))
            act.setEnabled(btn.isEnabled())
            act.triggered.connect(btn.click)
        # anything not in the table above still shows up, just unlabelled-ish
        for name, btn in hidden.items():
            act = menu.addAction(name.replace("btn_", "").replace("_", " ").title())
            act.triggered.connect(btn.click)
        if not menu.actions():
            return
        menu.exec(self.btn_overflow.mapToGlobal(
            self.btn_overflow.rect().bottomLeft()))

    def _enforce_header_priority_fit(self):
        """Last-resort guard so the clock and date always survive.

        The dense/ultra tiers hide widgets at FIXED px thresholds, which
        assume particular font metrics — on a machine with different DPI or
        font scaling the header can still overflow past the window edge even
        after the ultra hide-list has run, silently pushing the clock and
        date off-screen (they aren't 'hidden', just laid out past the right
        border). If the header still doesn't fit, shed low-priority widgets
        one at a time until it does. The clock and date are never in that
        list — the user asked for them to have absolute priority.
        """
        header = getattr(self, "header_widget", None)
        if header is None or sip.isdeleted(header):
            return
        # token count goes first: it is the most optional of the cluster
        drop_order = ("lbl_token_count", "btn_settings_toggle_right",
                      "_counter_sep", "lbl_line_count")
        widgets = [getattr(self, name, None) for name in drop_order]
        if any(w is None or sip.isdeleted(w) for w in widgets):
            return
        available = header.width()
        if available <= 0:
            return
        # Restore only what THIS guard hid on a previous pass — never
        # un-hide what the dense/ultra tier deliberately hid, or the two
        # fight each other.
        previously_hidden = getattr(self, "_priority_fit_hidden", ())
        for name in previously_hidden:
            w = getattr(self, name, None)
            if w is None or sip.isdeleted(w):
                continue
            if (name == "lbl_token_count"
                    and self.data.get("show_token_count", "False") != "True"):
                continue        # the user turned it off; do not resurrect it
            w.setVisible(True)
        self.header_layout.activate()

        now_hidden = []
        for name, w in zip(drop_order, widgets):
            if header.sizeHint().width() <= available:
                break
            # isHidden(), not isVisible(): isVisible() is False whenever any
            # ancestor is hidden (e.g. the whole window is tucked away in the
            # tray), which would make this guard silently do nothing.
            if w.isHidden():
                continue  # already hidden by the tier — leave it alone
            w.setVisible(False)
            now_hidden.append(name)
            self.header_layout.activate()
        self._priority_fit_hidden = tuple(now_hidden)

    @staticmethod
    def _day_part(hour):
        """Word for the time of day shown in the date widget."""
        if 5 <= hour < 12:
            return "Morning"
        if 12 <= hour < 17:
            return "Day"
        if 17 <= hour < 23:
            return "Evening"
        return "Night"

    def toggle_hide_on_clickout(self):
        """Alt+A: flip the Hide on Click-Out behavior from anywhere."""
        if hasattr(self, "cb_focus"):
            self.cb_focus.setChecked(not self.cb_focus.isChecked())
            self.play_tick_sound(self.cb_focus.isChecked())

    def _increment_focus_lock(self):
        """Counted ignore_focus_loss: overlapping dialogs each take a lock;
        the flag drops only when the LAST 300ms release fires (no race)."""
        self._focus_lock_count = getattr(self, "_focus_lock_count", 0) + 1
        self.ignore_focus_loss = True

    def _decrement_focus_lock(self):
        self._focus_lock_count = max(0, getattr(self, "_focus_lock_count", 0) - 1)
        if self._focus_lock_count == 0:
            self.ignore_focus_loss = False

    def _bring_to_front(self):
        """Re-assert foreground + z-order after an op that can drop it.

        A data undo rebuilds the category bar and swaps the active document,
        which on Windows can shove the window to the BACK of the z-order
        (Ctrl+Z "fell behind the other windows"). The focus lock only stops
        the hide-on-click-out; it does NOT keep the window on top, so we must
        explicitly raise it again."""
        try:
            if self.isVisible() and not self.isMinimized():
                self.raise_()
                self.activateWindow()
        except Exception:
            pass

    def _pin_top_toggled(self, checked):
        """Header 📌 mirrors the Always-on-Top setting checkbox."""
        if hasattr(self, "cb_top") and self.cb_top.isChecked() != checked:
            self.cb_top.setChecked(checked)  # cb_top's handler does the work
        else:
            self.toggle_aot(checked)

    def _toolbar_tokens(self):
        """Movable header items, one entry per token/attr. _counter_sep and
        the two spacers are represented by sentinel tokens."""
        from fastprompter.ui.toolbar_reorder import DEFAULT_TOOLBAR_ORDER
        return DEFAULT_TOOLBAR_ORDER

    def set_auto_bullet(self, enabled):
        """Single owner of the auto-bullet mode.

        The toolbar button and the editor's context menu each used to flip
        `data["auto_bullet"]` themselves, and only the button called
        mark_dirty() — so switching it on from the context menu worked until
        the next restart and left the button's tooltip lying.
        """
        enabled = bool(enabled)
        self.data["auto_bullet"] = "True" if enabled else "False"
        self._refresh_bullet_toggle()
        self.mark_dirty()
        return enabled

    def _refresh_bullet_toggle(self):
        btn = getattr(self, "btn_bullet_toggle", None)
        if btn is None or sip.isdeleted(btn):
            return
        on = self.data.get("auto_bullet", "False") == "True"
        btn.setChecked(on)
        btn.setToolTip(
            f"Auto-Bullet (Right-Click): {'ON' if on else 'OFF'}\n"
            "Left-Click: Convert selected lines between dashes and bullets.")

    def _toolbar_order_list(self):
        """Saved order, validated + self-healed against the default so a
        stale/partial value can never drop or duplicate a button."""
        default = self._toolbar_tokens()
        raw = (self.data.get("toolbar_order") or "").strip()
        # Migrate old btn_launcher by removing it
        if "btn_launcher" in raw:
            raw = raw.replace("btn_launcher", "")
        saved = [t for t in raw.split(",") if t]
        valid, seen = [], set()
        # keep saved tokens that are still real; drop unknowns/dupes
        for t in saved:
            if t == "<stretch>":
                valid.append(t)
            elif (t == "<sep>" or getattr(self, t, None) is not None) and t not in seen:
                valid.append(t)
                seen.add(t)
        if not valid:
            return list(default)        # nothing saved: the default IS the order

        # add any default tokens missing from the saved order. NOT blindly at
        # the end: a token added in a later version (cat_numbox next to
        # cat_combo, lbl_token_count next to lbl_line_count) landed after the
        # help button for everyone with a saved order, which reads as the
        # feature being broken. Put it back beside the neighbour it was
        # defined next to, and only fall back to the end.
        #
        # The anchor search MUST see the stretches. Skipping them put every
        # token defined after a "<stretch>" in front of it, which collapses
        # the whole right-hand cluster leftwards and leaves a dead gap at the
        # right edge — the exact symptom this was reported for.
        stretch_needed = default.count("<stretch>") - valid.count("<stretch>")
        for pos, t in enumerate(default):
            if t == "<stretch>":
                if stretch_needed > 0:
                    valid.append(t)
                    stretch_needed -= 1
                continue
            if t in seen:
                continue
            anchor = -1
            stretches_before = 0
            for prev in reversed(default[:pos]):
                if prev == "<stretch>":
                    # the n-th stretch of `default` is the n-th of `valid`
                    n = default[:pos].count("<stretch>") - stretches_before - 1
                    idx = [i for i, v in enumerate(valid) if v == "<stretch>"]
                    if 0 <= n < len(idx):
                        anchor = idx[n]
                        break
                    stretches_before += 1
                    continue
                if prev in valid:
                    anchor = valid.index(prev)
                    break
            if anchor >= 0:
                valid.insert(anchor + 1, t)
            else:
                valid.append(t)
            seen.add(t)
        return valid

    def _toolbar_widget_for(self, token):
        if token == "<sep>":
            return getattr(self, "_counter_sep", None)
        return getattr(self, token, None)

    def toolbar_token_of(self, widget):
        """Reverse map a widget back to its token (drag source id)."""
        for t in self._toolbar_tokens():
            if t not in ("<stretch>",) and self._toolbar_widget_for(t) is widget:
                return t
        return None

    def _toolbar_gap(self, i):
        """Reusable expanding gap widget for the i-th <stretch>. Real widget
        (not a bare spacer) so it's a visible, droppable zone in customize
        mode — the user can see exactly where the flexible fill lives."""
        gaps = getattr(self, "_toolbar_gaps", None)
        if gaps is None:
            gaps = self._toolbar_gaps = []
        while len(gaps) <= i:
            g = QWidget(self.header_widget)
            g.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            g.setMinimumWidth(6)
            g._is_toolbar_gap = True
            gaps.append(g)
        return gaps[i]

    def _style_toolbar_gaps(self, on):
        for g in getattr(self, "_toolbar_gaps", []):
            if on:
                g.setStyleSheet(
                    "border: 1px dashed #C0A060; border-radius: 0; margin: 3px 2px;")
                g.setToolTip(tr("Flexible gap — drop buttons on either side to "
                                "change which zone they sit in", getattr(self, "_current_lang", "EN")))
            else:
                g.setStyleSheet("")
                g.setToolTip("")

    def apply_toolbar_order(self, save=False):
        """Rebuild the header layout from the saved token order.

        The sidebar toggle is not part of the order: it is an edge control
        that sits on whichever side the sidebar is on, so it is detached
        with everything else and re-placed at the end.
        """
        lay = self.header_layout
        while lay.count():  # detach everything, edge controls included
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(self.header_widget)
        if not self._sidebar_right:
            self._place_sidebar_toggle(False)
        order = self._toolbar_order_list()
        stretch_i = 0
        for tok in order:
            if tok == "<stretch>":
                lay.addWidget(self._toolbar_gap(stretch_i))
                stretch_i += 1
                continue
            w = self._toolbar_widget_for(tok)
            if w is not None:
                lay.addWidget(w)
        # reset button is a fixed trailing control, never part of the order
        if hasattr(self, "btn_toolbar_reset"):
            lay.addWidget(self.btn_toolbar_reset)
        self._place_files_button(self._sidebar_right)
        if self._sidebar_right:
            self._place_sidebar_toggle(True)
        self._style_toolbar_gaps(self.data.get("customize_toolbar", "False") == "True")
        if save:
            self.data["toolbar_order"] = ",".join(order)
            self.mark_dirty()
        # widths/visibility depend on width tier — re-pack after reorder
        # (skipped during initial header build, before the editor exists)
        if hasattr(self, "text_area"):
            self._header_dense = None
            self._apply_header_density()

    def _toolbar_seq_token(self, w):
        """Token for any header widget: button id, '<sep>', or '<stretch>'."""
        if getattr(w, "_is_toolbar_gap", False):
            return "<stretch>"
        if w is getattr(self, "_counter_sep", None):
            return "<sep>"
        return self.toolbar_token_of(w)

    def reorder_toolbar_token(self, token, drop_x):
        """Move `token` to where the pointer released it.

        Works on the SAVED order, not on the visible row. Rebuilding from
        what happens to be on screen quietly dropped every button the
        density packer had hidden at that window width; they came back at
        whatever position the self-heal in `_toolbar_order_list` chose, so
        one drag re-arranged buttons the user had never touched and the same
        drag "worked" or "didn't" depending on how wide the window was.

        Only the drop POSITION is read from the layout: the first visible
        item whose centre is right of the cursor is what the token lands in
        front of. Hidden items keep their place around it.
        """
        order = self._toolbar_order_list()
        if token not in order:
            return

        # order index -> centre x, for the items actually on screen
        stretch_seen = 0
        visible = []
        for i, tok in enumerate(order):
            if tok == "<stretch>":
                w = self._toolbar_gap(stretch_seen)
                stretch_seen += 1
            else:
                w = self._toolbar_widget_for(tok)
            # isVisibleTo, not isVisible: the latter is False for every child
            # while the window itself is hidden (headless tests, a tray-hidden
            # window), which would empty this list and send every drop to the
            # end of the row.
            if (w is None or sip.isdeleted(w)
                    or not w.isVisibleTo(self.header_widget)):
                continue
            visible.append((i, w.x() + w.width() / 2))

        insert_at = len(order)
        for i, cx in visible:
            if drop_x < cx:
                insert_at = i
                break

        src = order.index(token)
        order.pop(src)
        if src < insert_at:
            insert_at -= 1
        order.insert(max(0, min(len(order), insert_at)), token)

        self.data["toolbar_order"] = ",".join(order)
        self.apply_toolbar_order()
        self.mark_dirty()

    def on_customize_toolbar_toggled(self, checked):
        self.data["customize_toolbar"] = "True" if checked else "False"
        self.mark_dirty()
        self.refresh_toolbar_customize_state()

    def refresh_toolbar_customize_state(self):
        """Install/refresh drag filters + cursors for the customize toggle,
        and show/hide the in-header Reset button + visible gaps."""
        on = self.data.get("customize_toolbar", "False") == "True"
        flt = getattr(self, "_toolbar_reorder_filter", None)
        for tok in self._toolbar_tokens():
            if tok in ("<stretch>", "<sep>"):
                continue
            w = self._toolbar_widget_for(tok)
            if w is None:
                continue
            if flt is not None:
                w.removeEventFilter(flt)
                if on:
                    w.installEventFilter(flt)
            w.setCursor(Qt.CursorShape.SizeAllCursor if on else Qt.CursorShape.ArrowCursor)
        self._style_toolbar_gaps(on)
        if hasattr(self, "btn_toolbar_reset"):
            self.btn_toolbar_reset.setVisible(on)

    def reset_toolbar_order(self):
        self.data["toolbar_order"] = ""
        self.apply_toolbar_order(save=True)

    def set_line_numbers(self, enabled):
        """Single source of truth for the line-number gutter. Applies the
        render, then force-syncs BOTH the header # button and the settings
        checkbox (signals blocked) so they can never drift out of step —
        that drift used to make the first # click a silent no-op."""
        self.on_line_numbers_toggled(enabled)
        for w in (getattr(self, "btn_line_nums", None), getattr(self, "cb_line_numbers", None)):
            if w is not None and not sip.isdeleted(w) and w.isChecked() != enabled:
                w.blockSignals(True)
                w.setChecked(enabled)
                w.blockSignals(False)

    def _line_nums_btn_toggled(self, checked):
        """Header # button: fast toggle for the line-number gutter."""
        self.set_line_numbers(checked)

    # How long a verdict about the custom files root is trusted before it is
    # probed again. _files_root() is called from the silo-refresh path, once
    # per silo, so an unbounded-but-uncached probe would still stutter.
    _FILES_ROOT_RECHECK = 5.0

    def _files_root(self):
        """The File Container root THIS PROFILE owns.

        Profile 1 keeps the legacy layout; profiles 2+ are namespaced under
        ``<base>/_profiles/p<id>`` (see ``profile_files_root``), so profiles
        can never read/adopt/delete each other's silo folders, trash or
        restore targets.

        P0-5 fail-closed rule: a CUSTOM root that is configured but
        temporarily unreachable is NEVER silently replaced by the default
        local root. Substituting the default would create a shadow copy of
        the user's assets (split-brain storage): mutations would start
        landing in a second location while the share still holds the real
        data. Instead the custom path is returned as-is — mutations fail
        closed (OSError, logged, nothing created locally), reads find
        nothing until the share returns, and the configured path stays
        untouched.
        """
        custom = (self.data.get("files_root") or "").strip()
        # local import: tests (and this method's own callers) point the data
        # dir at a private temp root without touching the module binding
        from fastprompter.utils.paths import get_data_dir, profile_files_root
        if custom:
            # bounded probe: warms the availability cache without blocking
            # the GUI (and keeps the offline state observable for the UI)
            self._custom_files_root_usable(custom)
            return profile_files_root(
                custom, getattr(getattr(self, "state", None), "profile_id", 1))
        return profile_files_root(
            os.path.join(get_data_dir(), "files"),
            getattr(getattr(self, "state", None), "profile_id", 1))

    def _custom_files_root_usable(self, custom):
        """Is the configured files root reachable, without betting the UI on it?

        The root is user-chosen through a QFileDialog, so it can be a share.
        `os.path.isdir` on a share whose server has gone away blocks the GUI
        thread exactly the way the paste probe did — measured at 93s there.
        The fallback to the local data dir is what the old code did anyway,
        after the block; bounding the probe only removes the freeze.

        Cached for a few seconds because the answer is asked for once per
        silo during a refresh, and 0.25s x 20 silos is its own stutter.
        """
        from fastprompter.utils.paths import isdir_within

        now = time.monotonic()
        cached = getattr(self, "_files_root_probe", None)
        if (cached and cached[0] == custom
                and now - cached[1] < self._FILES_ROOT_RECHECK):
            return cached[2]
        usable = isdir_within(custom)
        self._files_root_probe = (custom, now, usable)
        return usable

    def _category_files_dir(self, cat):
        """Physical folder component for a logical category, STABLE across
        renames and COLLISION-SAFE across look-alike names.

        ``silo_slug`` is lossy (Japanese/emoji collapse, punctuation
        collapses, long prefixes truncate, case aliases) and must NOT be used
        as unique identity: "A:B" and "AB" would alias one folder. The
        persistent ``category_file_dirs`` map owns identity instead:

        * NEW category  -> collision-resistant component (readable prefix +
          stable digest when needed), unique among claimed components.
        * EXISTING category with a legacy ``silo_slug`` folder on disk that is
          unambiguously unclaimed by any OTHER category -> adopt it (the
          legacy layout keeps working).
        * RENAME -> the logical key changes, the physical component stays.
        * DELETE -> resolve the physical component BEFORE state removal.

        Ambiguous legacy dirs are never auto-merged: they stay on disk, and
        the category gets a fresh component (recovery is logged, files are
        preserved).

        Returns None when the configured custom root is currently
        unreachable AND the category has no persisted component yet: a fresh
        allocation would only persist a component for a folder that cannot
        be created, and on a dead share isdir() lies. Callers must treat
        None as "no filesystem access right now" (fail closed, never create
        or claim). An already-persisted component is returned even while the
        root is down: it is identity data, not a filesystem probe (P1-4)."""
        mapping = self.data.setdefault("category_file_dirs", {})
        if not isinstance(mapping, dict):
            mapping = self.data["category_file_dirs"] = {}
        comp = mapping.get(cat)
        if comp:
            return comp
        custom = (self.data.get("files_root") or "").strip()
        if custom and not self._custom_files_root_usable(custom):
            from fastprompter.core.logging import logger
            logger.warning(
                "files root %s unreachable; refusing to allocate a folder "
                "component for category %r", custom, cat)
            return None
        comp = self._allocate_category_dir(cat, mapping)
        mapping[cat] = comp
        self.mark_dirty()
        return comp

    def _allocate_category_dir(self, cat, mapping):
        """Allocate (or legacy-adopt) a distinct physical component for a
        category that has none yet. Never returns a component another
        category owns or reserves."""
        from fastprompter.ui.file_container import silo_slug
        from fastprompter.utils.path_safety import alloc_fs_names, fs_component
        from fastprompter.utils.paths import isdir_within

        root = self._files_root()
        # components already owned by the persistent map, plus every OTHER
        # category's legacy slug (a live claim even without a folder yet —
        # two slug-colliding categories make the dir ambiguous for both).
        # All claims are compared NORMALIZED (P1-5): Windows treats "Case"
        # and "case" as the same directory, and a case-sensitive set would
        # let the second component escape the collision loop and alias the
        # first on disk.
        claimed = {os.path.normcase(v) for v in mapping.values()}
        for other in self.data.get("cats_order", []) or []:
            if other == cat or mapping.get(other):
                continue
            claimed.add(os.path.normcase(silo_slug(other)))

        legacy = silo_slug(cat)
        if (legacy and os.path.normcase(legacy) not in claimed
                and isdir_within(os.path.join(root, legacy))):
            return legacy          # unambiguous adoption of the legacy dir

        # collision-safe allocation over EVERY logical category that will ever
        # need a component — cats_order, the already-mapped keys, and the one
        # being allocated. A name set that skipped any of those could alias on
        # Windows (case-only differences collapse through os.path.normcase)
        # even though alloc_fs_names never collides within its input set.
        cats = [c for c in (self.data.get("cats_order", []) or []) if isinstance(c, str)]
        for k in mapping:
            if k not in cats:
                cats.append(k)
        if cat not in cats:
            cats.append(cat)
        comps = alloc_fs_names(cats)
        base = comps.get(cat) or fs_component(cat, fallback="unnamed")[0]
        comp, n = base, 2
        while os.path.normcase(comp) in claimed:
            comp = f"{base}-{n}"
            n += 1
        return comp

    def _silo_folder_name(self, slot_idx, is_archive=False):
        """Stable, UNIQUE folder name for a silo's files. Keyed by slot (not
        title) so two silos that share a title — or two empty ones — never
        collide into the same folder (which made files 'jump' to a neighbor).
        Names stay readable (title slug), disambiguated with -2/-3 on clash,
        and are remembered per slot so a retitle doesn't strand the files.
        Archive silos keep the plain title scheme (static, low-risk)."""
        from fastprompter.ui.file_container import silo_slug
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        in_range = 0 <= slot_idx < len(presets)
        text = presets[slot_idx] if in_range else ""
        base = silo_slug(text)
        cat = self.get_current_category()
        if is_archive:
            fmap = self.data.setdefault("archive_silo_folders", {})
        else:
            fmap = self.data.setdefault("silo_folders", {})
        key = str(slot_idx)
        probe_memo = {}
        def _probe_exists(n):
            if n not in probe_memo:
                probe_memo[n] = self._folder_on_disk(cat, n)
            return probe_memo[n]
        if key in fmap and fmap[key]:
            # keep the assigned name, but follow a genuine retitle when the
            # new title's slug is free (readability) — otherwise stay put
            cur = fmap[key]
            cur_base = cur.rsplit("-", 1)[0] if cur[-1:].isdigit() and "-" in cur else cur
            if base != cur_base:
                taken = {v for k, v in fmap.items() if k != key}
                if base not in taken and not _probe_exists(base):
                    # P0-6: mapping follows the PHYSICAL rename, never leads
                    # it. Only a confirmed rename (or a genuinely absent old
                    # folder on a reachable root) advances the map; a failed
                    # rename keeps the OLD mapping exactly.
                    result = self._rename_silo_folder(cat, cur, base)
                    if result in ("RENAMED", "NOT_NEEDED"):
                        fmap[key] = base
                        self.mark_dirty()
            return fmap[key]
        # first assignment: adopt an existing on-disk folder if it's unclaimed,
        # else pick a unique name
        taken = set(fmap.values())
        if base not in taken and _probe_exists(base):
            fmap[key] = base
            self.mark_dirty()
            return base
        name, n = base, 2
        while name in taken:
            name = f"{base}-{n}"
            n += 1
        # Only COMMIT a name once the silo is real: it has text, or it
        # already owns a folder on disk. The panel asks for a name for every
        # visible slot (tooltips, file counters, empty rows), and recording
        # those filled the map with untitled-4..untitled-10 for silos that
        # do not exist yet. Answer the question, just don't write it down.
        if not in_range or not (text.strip() or _probe_exists(name)):
            return name
        fmap[key] = name
        self.mark_dirty()
        return name

    def _folder_on_disk(self, cat, name):
        comp = self._category_files_dir(cat)
        if comp is None:
            return False   # root unreachable: no folder claim is answerable
        child = os.path.join(self._files_root(), comp, name)
        custom = (self.data.get("files_root") or "").strip()
        if custom:
            if not self._custom_files_root_usable(custom):
                return False
            from fastprompter.utils.paths import isdir_within
            return isdir_within(child)
        return os.path.isdir(child)

    def _restore_trash_file_container(self, md_basename, text, inserted_slot):
        """CORE-006: restore the File Container folder for a trashed silo using
        its EXACT delete-time association (never a ``silo_slug`` guess).

        Returns the allocated physical folder name on success, or ``None`` when
        there is no recoverable folder for this text (the caller then reports a
        partial/no-folder restore rather than a false success).

        The recovered directory is moved into the CURRENT category's physical
        component under a COLLISION-SAFE name (the same contract a normal silo
        uses) and that exact name is written into the inserted slot's map.
        """
        link = self.data.get("trash_text_folder") or {}
        val = link.get(md_basename)
        if not val:
            return None
        log = self.data.get("folder_trash_log") or []
        # CORE-001: ONE canonical decoder for the trash link -> journal
        # mapping, shared with TrashDialog's rollback capture. The new
        # absolute-path format matches its own retirement record by exact
        # original path; the legacy basename format keeps a basename
        # fallback. Exactly one recoverable record is consumed and every
        # unrelated entry is preserved.
        from fastprompter.ui.snippet_ops_mixin import resolve_trash_link
        selected, remaining = resolve_trash_link(val, log)
        if selected is None:
            return None  # no recoverable folder for this exact association
        orig, trashed = selected[0], selected[1]
        if not os.path.isdir(trashed):
            return None

        cat = self.get_current_category() or ""
        comp = self._category_files_dir(cat)
        if comp is None:
            from fastprompter.core.logging import logger
            logger.warning("trash folder restore skipped: no component for %r",
                           cat)
            return None
        cat_dir = os.path.join(self._files_root(), comp)
        try:
            os.makedirs(cat_dir, exist_ok=True)
        except OSError:
            return None
        # CORE-001: the original folder NAME comes from the selected
        # retirement record's original path — never from a caller-local
        # variable that does not exist in this scope.
        folder_name = os.path.basename(os.path.abspath(str(orig)))
        # CORE-006: collision-safe allocation reuses the original folder name
        # but suffixes (-2/-3) when that name is already taken on disk or
        # claimed by another slot in this category.
        taken = {v for v in (self.data.get("silo_folders_all", {})
                             .get(cat, {}) or {}).values()}
        name = folder_name
        n = 2
        while name in taken or os.path.isdir(os.path.join(cat_dir, name)):
            name = f"{folder_name}-{n}"
            n += 1
        dest = os.path.join(cat_dir, name)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.rename(trashed, dest)
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning("trash folder restore failed for %r: %s",
                           folder_name, e)
            return None
        # commit the exact allocated name into the inserted slot's map
        fmap_all = self.data.setdefault("silo_folders_all", {}).setdefault(cat, {})
        fmap_all[str(inserted_slot)] = name
        if cat == self.get_current_category():
            self.data.setdefault("silo_folders", {})[str(inserted_slot)] = name
        # consume exactly the selected retirement entry
        self.data["folder_trash_log"] = remaining
        # CORE-003: the text->folder association is consumed once the folder
        # it referenced has been restored (no stale/ambiguous link lingers).
        self.data.get("trash_text_folder", {}).pop(md_basename, None)
        self.mark_dirty()
        return name

    def _rename_silo_folder(self, cat, old_name, new_name):
        """Rename a silo's physical folder; returns an explicit status so the
        caller can make the mapping update TRANSACTIONAL:

        "RENAMED"     physical rename performed
        "NOT_NEEDED"  the old folder does not exist (root reachable), so no
                      physical rename is required — adopting the new name is
                      safe
        "FAILED"      OSError, destination appeared, or the custom root is
                      unreachable — the OLD mapping must be kept exactly
        """
        # A configured custom root that is temporarily unreachable must NOT be
        # read as "old folder absent": on a dead share isdir() lies, and the
        # rename would silently detach the mapping from the real folder. The
        # guard runs BEFORE any filesystem probe or component allocation
        # (P1-4).
        custom = (self.data.get("files_root") or "").strip()
        if custom and not self._custom_files_root_usable(custom):
            return "FAILED"
        base = os.path.join(self._files_root(), self._category_files_dir(cat))
        old_dir, new_dir = os.path.join(base, old_name), os.path.join(base, new_name)
        try:
            if not os.path.isdir(old_dir):
                return "NOT_NEEDED"
            if os.path.exists(new_dir):
                # destination appeared (race): never clobber, never remap
                return "FAILED"
            os.rename(old_dir, new_dir)
            return "RENAMED"
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning(f"Silo folder rename {old_dir} -> {new_dir} failed: {e}")
            return "FAILED"

    def _silo_folder_dir(self, slot_idx, is_archive=False):
        """Absolute path to a silo's files folder (unique per slot), inside
        the CURRENT category's physical directory. None when the custom root
        is unreachable and no component exists — callers must treat it as
        "no filesystem access right now" (P1-4)."""
        comp = self._category_files_dir(self.get_current_category())
        if comp is None:
            return None
        return os.path.join(self._files_root(), comp,
                            self._silo_folder_name(slot_idx, is_archive))

    def _restore_trashed_folders(self, cat):
        """Undo helper: for every silo folder the restored map expects, if it's
        missing on disk but was moved to _trash by a delete/clear, move it back.
        Files are never lost — worst case they stay in _trash for manual rescue.
        Both the normal and the archive folder maps count (T-755)."""
        log = self.data.get("folder_trash_log", [])
        if not log:
            return
        comp = self._category_files_dir(cat)
        if comp is None:
            # root down: the trash entries stay in the log untouched and are
            # retried when the root is reachable again
            return
        cat_dir = os.path.join(self._files_root(), comp)
        fmap = self.data.get("silo_folders", {})
        amap = self.data.get("archive_silo_folders", {})
        if not isinstance(fmap, dict) or not isinstance(amap, dict):
            return
        wanted = {os.path.abspath(os.path.join(cat_dir, name)) for name in fmap.values()}
        wanted |= {os.path.abspath(os.path.join(cat_dir, name)) for name in amap.values()}
        remaining = []
        for original, trashed in log:
            if original in wanted and not os.path.exists(original) and os.path.isdir(trashed):
                try:
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    os.rename(trashed, original)
                    continue  # restored — drop from the log
                except OSError as e:
                    from fastprompter.core.logging import logger
                    logger.warning(f"Could not restore folder {trashed} -> {original}: {e}")
            remaining.append((original, trashed))
        self.data["folder_trash_log"] = remaining
        self.mark_dirty()

    # ------------------------------------------------------------------
    # W2-001: retirement COMMIT-vs-ROLLBACK arbitration support.
    # ------------------------------------------------------------------

    def _retirement_owner_is_live(self, original):
        """True when DURABLE state still maps ``original`` to a live owner.

        Called during startup reconciliation with a record's original folder
        path. The durable state at startup IS what was just loaded from
        SQLite: if its per-category folder maps still reference this exact
        component + folder name, the logical deletion never committed and
        the physical move must be rolled back. Anything unresolvable (path
        outside the current files root, unknown component) reports NOT-live,
        which adopts the record into the recovery log — never stranding it
        in a journal nobody can interpret."""
        try:
            root = os.path.abspath(self._files_root())
            orig = os.path.abspath(str(original))
        except Exception:
            return False
        if not orig.lower().startswith(root.lower() + os.sep):
            return False
        rel = os.path.relpath(orig, root)
        parts = rel.split(os.sep)
        if len(parts) != 2:
            return False
        comp, name = parts
        cfd = self.data.get("category_file_dirs") or {}
        cats = [c for c, v in cfd.items() if v == comp]
        for cat in cats:
            for key in ("silo_folders_all", "archive_silo_folders_all"):
                m = (self.data.get(key) or {}).get(cat) or {}
                if isinstance(m, dict) and name in m.values():
                    return True
        return False

    # ------------------------------------------------------------------
    # W2-002: File Container session revocation on destructive transitions.
    # ------------------------------------------------------------------

    def _detach_file_container_for(self, folder_path):
        """Revoke an open File Container session bound to ``folder_path``.

        A floating drawer may legitimately stay open on a merely non-active
        silo, but once its storage owner is deleted/retired/moved the panel's
        mutation lease must die with it: the next import would otherwise
        ``_ensure_folder`` the retired path back into existence."""
        panel = getattr(self, "_file_container", None)
        if panel is None:
            return
        from PyQt6 import sip as _sip
        if _sip.isdeleted(panel):
            return
        fld = getattr(panel, "folder", None)
        if not fld or not folder_path:
            return
        try:
            if (os.path.normcase(os.path.abspath(fld))
                    == os.path.normcase(os.path.abspath(folder_path))):
                panel.detach_session()
        except OSError:
            pass

    def _detach_file_container_under(self, root_path):
        """Revoke any open File Container session under ``root_path``."""
        panel = getattr(self, "_file_container", None)
        if panel is None:
            return
        from PyQt6 import sip as _sip
        if _sip.isdeleted(panel):
            return
        fld = getattr(panel, "folder", None)
        if not fld or not root_path:
            return
        try:
            f_norm = os.path.normcase(os.path.abspath(fld))
            r_norm = os.path.normcase(os.path.abspath(root_path))
            if f_norm == r_norm or f_norm.startswith(r_norm.rstrip(os.sep) + os.sep):
                panel.detach_session()
        except OSError:
            pass

    def _revoke_container_for_old_files_root(self, old_root):
        """A Files Folder reconfiguration invalidates every session whose
        resolved storage lived under the OLD root."""
        self._detach_file_container_under(old_root)

    # ------------------------------------------------------------------
    # PERF-004: one-way mirror dirty routing.
    # ------------------------------------------------------------------

    _MIRROR_SETTINGS_KEYS = frozenset({
        "cats_order",
        "silo_project_paths_all",
        "silo_links_all",
        "project_sync_map_all",
        "category_file_dirs",
    })

    def _mirror_settings_dirty(self):
        """True when THIS save committed a settings key the mirror derives
        paths/topology from (sync root/mode, project order, link maps)."""
        keys = getattr(self.state, "last_save_settings_keys", None) or []
        for k in keys:
            if k.startswith("sync_") or k in self._MIRROR_SETTINGS_KEYS:
                return True
        return False

    def invalidate_file_count_cache(self, path):
        """Invalidate the file count cache for a specific folder path."""
        if hasattr(self, "_file_count_cache") and path in self._file_count_cache:
            del self._file_count_cache[path]

    def _on_file_count_result(self, path, count, slot_idx, is_archive, category,
                              profile_id):
        if hasattr(self, "_pending_file_counts"):
            self._pending_file_counts.discard(path)
        if not hasattr(self, "_file_count_cache"):
            self._file_count_cache = {}
        self._file_count_cache[path] = count

        # P1-5/P1-4: the label is applied ONLY when the ownership context at
        # dispatch time still matches at result time. The cache is keyed by
        # the unique folder path, so it is safe either way — but the BUTTON
        # is addressed by slot index, and a slow count from silo A's folder
        # landing after the user switched category (or space, or PROFILE)
        # would paint silo B's button with silo A's number. The profile id
        # is immutable, so it can never be claimed by a later profile.
        if profile_id != getattr(getattr(self, "state", None), "profile_id", None):
            return
        if category != self.get_current_category():
            return
        if is_archive != getattr(self, "active_is_archive", False):
            return
        # folder-level revalidation: the same slot+category+profile can still
        # own a DIFFERENT folder after a slot shuffle — the counted path must
        # be exactly what the slot owns right now
        if path != self._silo_folder_dir(slot_idx, is_archive):
            return

        # P1-4: archive results target the ARCHIVE button row, silo results
        # the silo row — they used to share the silo row and painted archive
        # counts onto matching silo buttons.
        buttons = getattr(self, "archive_buttons" if is_archive else "silo_buttons", None)
        if buttons is None:
            return
        for btn in buttons:
            if getattr(btn, "global_idx", -1) == slot_idx and not btn.isHidden():
                lbl = getattr(btn, "_lbl_file_count", None)
                if lbl:
                    if count > 0:
                        lbl.setText(f"📁 {count}")
                        lbl.show()
                    else:
                        lbl.hide()
                break

    def _silo_file_count(self, slot_idx, is_archive=False):
        path = self._silo_folder_dir(slot_idx, is_archive)
        if not path:
            # P0-5: offline custom root — nothing to count, no worker
            return 0
        if not hasattr(self, "_file_count_cache"):
            self._file_count_cache = {}
            self._pending_file_counts = set()

        if path in self._file_count_cache:
            return self._file_count_cache[path]

        if path not in self._pending_file_counts:
            self._pending_file_counts.add(path)

            import weakref

            from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal
            if not hasattr(self, "file_count_loaded"):
                from PyQt6.QtCore import QObject
                class Signals(QObject):
                    file_count_loaded = pyqtSignal(str, int, int, bool, str, int)
                self._file_count_signals = Signals()
                self.file_count_loaded = self._file_count_signals.file_count_loaded
                self.file_count_loaded.connect(self._on_file_count_result)

            # the ownership context is captured HERE, on the GUI thread; the
            # worker must never dereference the window (P1-5). Profile id is
            # immutable (never reused across profiles), so a result can never
            # be claimed by a later profile that happens to have the same
            # slot indices (P1-4).
            category = self.get_current_category()
            profile_id = getattr(getattr(self, "state", None), "profile_id", None)

            class Worker(QRunnable):
                def __init__(self, p, s, cat, is_arc, prof, app_ref):
                    super().__init__()
                    self.p = p
                    self.s = s
                    self.cat = cat
                    self.is_arc = is_arc
                    self.prof = prof
                    self.app_ref = app_ref
                def run(self):
                    import os
                    try:
                        c = len(os.listdir(self.p))
                    except OSError:
                        c = 0

                    app = self.app_ref()
                    if app:
                        from PyQt6 import sip
                        if not sip.isdeleted(app):
                            try:
                                app.file_count_loaded.emit(
                                    self.p, c, self.s, self.is_arc, self.cat,
                                    self.prof)
                            except RuntimeError:
                                pass

            worker = Worker(path, slot_idx, category, is_archive, profile_id,
                            weakref.ref(self))
            QThreadPool.globalInstance().start(worker)

        return 0

    def pick_files_root(self):
        """Settings: let the user choose where silo file containers live."""
        from PyQt6.QtWidgets import QFileDialog
        start = self._files_root()
        path = QFileDialog.getExistingDirectory(self, "Folder for silo files", start)
        if path:
            # W2-002: re-rooting invalidates every open session resolved under
            # the OLD root — a drawer bound there must not keep writing into
            # storage that no longer backs its owner.
            self._revoke_container_for_old_files_root(start)
            self.data["files_root"] = path
            self.mark_dirty()
            self._update_files_button()
            self.refresh_temp_presets()

    def reset_files_root(self):
        self._revoke_container_for_old_files_root(self._files_root())
        self.data["files_root"] = ""
        self.mark_dirty()
        self._update_files_button()

    def open_sound_settings_dialog(self):
        """Open the comprehensive sound settings dialog."""
        from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

        # The modal takes the foreground, which is a deactivation as far as
        # the main window is concerned — without the lock, Hide on Click-Out
        # hid everything behind the dialog and closing it left the user
        # staring at a desktop where nothing reacted any more.
        self._increment_focus_lock()
        try:
            dialog = SoundSettingsDialog(self, self.data, self.sound_manager)
            dialog.exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
        # Force sync: ensure sound_manager sees updated data
        self.sound_manager._data = self.data
        self.refresh_temp_presets()

    def add_files_to_active_silo(self, paths):
        """Drop target helper: put files into the active silo's container
        and show the drawer so the user sees where they landed."""
        is_archive = getattr(self, "active_is_archive", False)
        self.open_file_container(is_archive=is_archive)
        self._file_container.import_paths(paths)

    def add_links_to_active_silo(self, paths):
        """Drop target helper: put file links into the active silo's container
        and show the drawer so the user sees where they landed."""
        is_archive = getattr(self, "active_is_archive", False)
        self.open_file_container(is_archive=is_archive)
        self._file_container.import_links(paths)

    def _update_project_buttons(self, is_archive=None):
        if is_archive is None:
            is_archive = getattr(self, "active_is_archive", False)
        # CORE-012: normal and archive keep separate project-path namespaces;
        # the buttons reflect the active namespace, never a numeric slot alone.
        store = self.data.get("archive_project_paths" if is_archive else "silo_project_paths", {})
        paths = store.get(str(self.active_temp_slot), {}) if isinstance(store, dict) else {}
        if not isinstance(paths, dict):
            paths = {}

        has_folder = bool(paths.get("folder"))
        has_exe = bool(paths.get("executable"))

        if hasattr(self, "btn_project_folder"):
            self.btn_project_folder.setVisible(has_folder)
        if hasattr(self, "btn_project_run"):
            self.btn_project_run.setVisible(has_exe)

    def _update_files_button(self):
        """Refresh the header 📁 button: live file count + breakdown tooltip."""
        if not hasattr(self, "btn_files"):
            return
        is_archive = getattr(self, "active_is_archive", False)
        idx = self.active_temp_slot
        folder = self._silo_folder_dir(idx, is_archive)
        lang = getattr(self, '_current_lang', 'EN')
        base_tt = tr("Files—asset drawer for the active silo (drop in / drag out /\npreview / export; plain folder in data/files)\n\n", lang)
        if not folder:
            # P0-5: offline custom root — no async summary, no worker
            self.btn_files.setText("📁")
            self.btn_files.setToolTip(base_tt + "0 item(s)")
            return
        n = self._silo_file_count(idx, is_archive)
        self.btn_files.setText(f"📁{n}" if n else "📁")
        if getattr(self, "_header_dense", False):
            self.btn_files.setFixedWidth(
                self.btn_files.fontMetrics().horizontalAdvance(self.btn_files.text()) + 8)

        self.btn_files.setToolTip(base_tt + f"{n} item(s)")

        # Dispatch async detailed summary
        if not hasattr(self, "_pending_tooltips"):
            self._pending_tooltips = set()
            self._tooltip_cache = {}

        if folder in self._tooltip_cache:
            # TTL check
            import time
            hit_time, hit_text = self._tooltip_cache[folder]
            if time.time() - hit_time < 30.0:
                self.btn_files.setToolTip(base_tt + hit_text)
                return

        if folder not in self._pending_tooltips:
            self._pending_tooltips.add(folder)

            import weakref

            from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal
            if not hasattr(self, "tooltip_loaded"):
                from PyQt6.QtCore import QObject
                class Signals(QObject):
                    tooltip_loaded = pyqtSignal(str, str, int, bool, str, int)
                self._tooltip_signals = Signals()
                self.tooltip_loaded = self._tooltip_signals.tooltip_loaded
                self.tooltip_loaded.connect(self._on_tooltip_result)

            # ownership context captured HERE on the GUI thread (P1-6);
            # profile id captured too (P1-4)
            category = self.get_current_category()
            profile_id = getattr(getattr(self, "state", None), "profile_id", None)

            class Worker(QRunnable):
                def __init__(self, p, s, l, cat, is_arc, prof, app_ref):
                    super().__init__()
                    self.p = p
                    self.s = s
                    self.l = l
                    self.cat = cat
                    self.is_arc = is_arc
                    self.prof = prof
                    self.app_ref = app_ref
                def run(self):
                    from fastprompter.ui.file_container import folder_summary
                    try:
                        res = folder_summary(self.p, lang=self.l)
                    except Exception:
                        res = ""
                    app = self.app_ref()
                    if app:
                        from PyQt6 import sip
                        if not sip.isdeleted(app):
                            try:
                                app.tooltip_loaded.emit(
                                    self.p, res, self.s, self.is_arc, self.cat,
                                    self.prof)
                            except RuntimeError:
                                pass

            worker = Worker(folder, idx, lang, category, is_archive, profile_id,
                            weakref.ref(self))
            QThreadPool.globalInstance().start(worker)

    def _on_tooltip_result(self, folder, res, slot_idx, is_archive, category,
                           profile_id):
        if hasattr(self, "_pending_tooltips"):
            self._pending_tooltips.discard(folder)
        if not hasattr(self, "_tooltip_cache"):
            self._tooltip_cache = {}
        import time
        self._tooltip_cache[folder] = (time.time(), res)
        # P1-6/P1-4: apply the tooltip ONLY when the ownership context at
        # dispatch time still matches: a slow summary from silo A must not
        # paint silo B's (or another category's, or another PROFILE's) button
        # after the user switched away.
        if profile_id != getattr(getattr(self, "state", None), "profile_id", None):
            return
        if category != self.get_current_category():
            return
        if is_archive != getattr(self, "active_is_archive", False):
            return
        if folder != self._silo_folder_dir(slot_idx, is_archive):
            return
        if getattr(self, "active_temp_slot", -1) == slot_idx and hasattr(self, "btn_files"):
            lang = getattr(self, '_current_lang', 'EN')
            base_tt = tr("Files—asset drawer for the active silo (drop in / drag out /\npreview / export; plain folder in data/files)\n\n", lang)
            self.btn_files.setToolTip(base_tt + res)

    def _launch_silo_executable(self, is_archive=None):
        import os

        from fastprompter.core.logging import logger
        if is_archive is None:
            is_archive = getattr(self, "active_is_archive", False)
        store = self.data.get("archive_project_paths" if is_archive else "silo_project_paths", {})
        paths = store.get(str(self.active_temp_slot), {}) if isinstance(store, dict) else {}
        exe = paths.get("executable") if isinstance(paths, dict) else None
        if not exe or not os.path.exists(exe):
            logger.info("No executable configured or file does not exist.")
            return

        try:
            # Setting working directory to the directory of the executable
            exe_dir = os.path.dirname(exe)
            os.startfile(exe, cwd=exe_dir)
        except OSError as e:
            logger.error(f"Failed to launch executable: {e}")

    def _open_silo_project_folder(self, is_archive=None):
        import os

        from fastprompter.core.logging import logger
        if is_archive is None:
            is_archive = getattr(self, "active_is_archive", False)
        store = self.data.get("archive_project_paths" if is_archive else "silo_project_paths", {})
        paths = store.get(str(self.active_temp_slot), {}) if isinstance(store, dict) else {}
        folder = paths.get("folder") if isinstance(paths, dict) else None
        if not folder or not os.path.isdir(folder):
            logger.info("No project folder configured or directory does not exist.")
            return

        try:
            os.startfile(folder)
        except OSError as e:
            logger.error(f"Failed to open project folder: {e}")

    def open_silo_settings(self, global_idx=None, is_archive=None):
        if global_idx is None:
            global_idx = self.active_temp_slot
        if is_archive is None:
            is_archive = getattr(self, "active_is_archive", False)
        from fastprompter.ui.silo_settings_dialog import SiloSettingsDialog
        dlg = SiloSettingsDialog(self, global_idx, is_archive)
        self._increment_focus_lock()
        try:
            accepted = dlg.exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)
        if accepted:
            # Trigger refresh to show/hide the buttons
            if global_idx == self.active_temp_slot and is_archive == getattr(self, "active_is_archive", False):
                self._update_project_buttons(is_archive)

    def files_docked(self):
        """Files panel lives in the splitter rather than in its own window."""
        return self.data.get("file_panel_docked", "False") == "True"

    def _ensure_file_container(self):
        """The panel, built once, parked on whichever side it belongs to."""
        from fastprompter.ui.file_container import FileContainerPanel
        panel = getattr(self, "_file_container", None)
        if panel is None or sip.isdeleted(panel):
            panel = self._file_container = FileContainerPanel(self)
            panel.docked = False
        want_docked = self.files_docked()
        if bool(panel.docked) != want_docked:
            panel.set_docked(want_docked, self.files_dock)
            if want_docked:
                self.files_dock_layout.addWidget(panel)
                panel.show()
            else:
                self._show_files_dock(False)
        return panel

    def _show_files_dock(self, visible, title=""):
        """Show/hide the docked files pane, restoring its saved width."""
        dock = getattr(self, "files_dock", None)
        if dock is None or sip.isdeleted(dock):
            return
        if visible and not self.files_docked():
            return
        idx = self.splitter.indexOf(dock)
        centre = self.splitter.indexOf(self.center_panel)
        if not visible:
            # Read the sizes BEFORE hiding: a hidden splitter child reports 0.
            sizes = self.splitter.sizes()
            freed = sizes[idx] if 0 <= idx < len(sizes) else 0
            if freed >= 60:
                self.data["files_dock_width"] = str(freed)
            dock.setVisible(False)
            self.data["files_dock_open"] = "False"
            if freed and 0 <= centre < len(sizes):
                # Hand the width back to the CENTRE pane. Left to itself Qt
                # gives a hidden child's space to whoever has stretch, which
                # here is the silo sidebar — so it grew a little wider every
                # single time the files pane was closed.
                sizes[centre] += freed
                sizes[idx] = 0
                self.splitter.setSizes(sizes)
            # The floating panel plays this from closeEvent, which a DOCKED
            # panel never gets: it is hidden, not closed. So opening the
            # sidebar had a sound and closing it had silence.
            if freed and hasattr(self, "sound_manager"):
                self.sound_manager.play("chest_close")
            return
        dock.setVisible(True)
        self.data["files_dock_open"] = "True"
        sizes = self.splitter.sizes()
        if 0 <= idx < len(sizes) and sizes[idx] < 60:
            try:
                width = max(120, min(600, int(self.data.get("files_dock_width", 220))))
            except (TypeError, ValueError):
                width = 220
            if 0 <= centre < len(sizes):
                sizes[centre] = max(160, sizes[centre] - width)
            sizes[idx] = width
            self.splitter.setSizes(sizes)

    def cycle_vision_mode(self):
        """Step the view mode: Source View -> Live Preview -> Reading."""
        combo = getattr(self, "preview_combo", None)
        if combo is None or sip.isdeleted(combo) or combo.count() == 0:
            return
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
        self._refresh_vision_button()

    def _refresh_vision_button(self):
        btn = getattr(self, "btn_vision", None)
        combo = getattr(self, "preview_combo", None)
        if btn is None or sip.isdeleted(btn) or combo is None or sip.isdeleted(combo):
            return
        mode = combo.currentData() or combo.currentText()
        btn.setToolTip(tr(
            "Vision: {}\nClick to cycle Source View / Live Preview / Reading",
            getattr(self, "_current_lang", "EN")).format(
                tr(str(mode), getattr(self, "_current_lang", "EN"))))

    def _place_files_button(self, is_right):
        """Keep 📁 on the side its panel opens on.

        The files dock sits opposite the silo sidebar, so with the sidebar on
        the right the button belongs next to the settings gear on the left —
        beside the edge the panel actually appears at.
        """
        btn = getattr(self, "btn_files", None)
        layout = getattr(self, "header_layout", None)
        anchor = getattr(self, "btn_settings_toggle_right", None)
        if btn is None or layout is None:
            return
        if not is_right or anchor is None:
            return          # left sidebar: the order list already placed it
        idx = layout.indexOf(anchor)
        if idx < 0:
            return
        layout.removeWidget(btn)
        layout.insertWidget(layout.indexOf(anchor), btn)

    def _sync_files_dock_to_active_silo(self):
        """An OPEN files sidebar has to follow the silo you switch to.

        As a floating drawer, a panel left pointing at the previous silo was
        merely stale — you had to go find it. As a permanent sidebar it is
        wrong and dangerous: what it shows is what a drop lands in, so a
        stale panel silently files your drop under another silo.
        """
        if not self.files_docked():
            return
        dock = getattr(self, "files_dock", None)
        if dock is None or sip.isdeleted(dock) or dock.isHidden():
            return
        panel = getattr(self, "_file_container", None)
        if panel is None or sip.isdeleted(panel):
            return
        self.open_file_container()

    def toggle_file_container(self):
        """The 📁 button: a toggle when docked, 'open/raise' when floating."""
        if self.files_docked():
            dock = getattr(self, "files_dock", None)
            # isHidden(), not isVisible(): isVisible() is False whenever an
            # ancestor is hidden (window in the tray), which would turn the
            # toggle into "always open"
            if dock is not None and not dock.isHidden():
                # _show_files_dock(False) saves the width AND hands the freed
                # space to the CENTRE pane. The old inline close let Qt give
                # a hidden child's room to whoever has stretch — the silo
                # sidebar — which grew a little wider every single time the
                # file manager was opened and closed (T-721 fixed the
                # auto-hide path, but not the 📁 toggle).
                self._show_files_dock(False)
                self.mark_dirty()
                return
        self.open_file_container()

    def _on_files_dock_toggled(self, checked):
        self.data["file_panel_docked"] = "True" if checked else "False"
        panel = getattr(self, "_file_container", None)
        was_open = panel is not None and not sip.isdeleted(panel) and panel.isVisible()
        self._ensure_file_container()
        if was_open:
            self.open_file_container()
        self.mark_dirty()

    def open_file_container(self, global_idx=None, is_archive=False):
        from fastprompter.ui.file_container import silo_slug
        if global_idx is None:
            global_idx = self.active_temp_slot
            is_archive = getattr(self, "active_is_archive", False)
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        text = presets[global_idx] if 0 <= global_idx < len(presets) else ""
        panel = self._ensure_file_container()
        folder = self._silo_folder_dir(global_idx, is_archive)
        if folder is None:
            # P0-5: the custom files root is offline and the category has no
            # persisted component — fail closed, never bind a dead path.
            from fastprompter.core.logging import logger as _log
            _log.warning("file container cannot open: files root unavailable "
                         "for slot %d (archive=%s)", global_idx, is_archive)
            panel.detach_session()
            return
        panel.open_for(folder, title=silo_slug(text))

    def _begin_batch_update(self):
        """Suppress paints + snapshot overlay as backup."""
        if not hasattr(self, "left_panel"): return
        self.setUpdatesEnabled(False)
        snap = self.left_panel.grab()
        self._sidebar_snap = QLabel(self.left_panel)
        self._sidebar_snap.setPixmap(snap)
        self._sidebar_snap.setGeometry(self.left_panel.rect())
        self._sidebar_snap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sidebar_snap.show()
        self._sidebar_snap.raise_()

    def _end_batch_update(self):
        """Re-enable paints — naturally batched by Qt's backing store."""
        if not hasattr(self, "left_panel"): return
        if hasattr(self, "_sidebar_snap") and self._sidebar_snap is not None:
            self._sidebar_snap.hide()
            self._sidebar_snap.deleteLater()
            self._sidebar_snap = None
        self.setUpdatesEnabled(True)

    def _update_active_silo_ui(self, raw=None):
        """Refresh the active silo button's label/style from ``raw`` text.

        PERF-001: callers that already own a current whole-document snapshot
        (``cache_current_text`` after its debounce fires) pass it in — the
        old signature re-materialized the SAME QTextDocument with a second
        O(document) ``toPlainText()`` on the GUI thread for every settled
        typing burst. Independent callers keep the fallback extraction."""
        idx = getattr(self, "active_temp_slot", -1)
        if idx < 0 or getattr(self, "active_is_archive", False) or getattr(self, "editing_snippet", None):
            return
        if not hasattr(self, "silo_buttons"):
            return
        btn = None
        for b in self.silo_buttons:
            if getattr(b, "global_idx", -1) == idx and not b.isHidden():
                btn = b
                break
        if not btn:
            return

        if raw is None:
            raw = self.text_area.toPlainText()
        text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
        if text.startswith("#"):
            text = text[1:].lstrip()

        last = getattr(btn, "_last_state", None)
        if not last: return
        (old_label, _, _, font_family, scale, _, _, _, _, _, is_child, fcount, has_children, is_collapsed, _, _, is_pinned, _, _) = last

        import re
        m = re.match(r'^(↳\s*[\d\.]+)(:\s*.*)?$', old_label)
        if m:
            prefix = m.group(1)
            label = f"{prefix}: {text}" if text else prefix
        else:
            m = re.match(r'^([\d\.]+)(:\s*.*)?$', old_label)
            if m:
                prefix = m.group(1)
                label = f"{prefix}: {text}" if text else prefix
            else:
                label = text

        line_count = raw.count("\n") + 1 if raw.strip() else 0
        line_str = str(line_count) if line_count > 0 else ""

        theme_name = self.data.get("theme", "Default")
        from fastprompter.theme.themes import THEMES
        active_color = THEMES.get(theme_name, THEMES["Default"]).get("active_temp_color", "#444444")
        bg_color = active_color
        if text and idx in getattr(self, "silo_last_edited", {}):
            bg_color = self._overlay_silo_bg(bg_color, self.silo_last_edited[idx])

        title_bold = (self.data.get("bold_hash_titles", "True") == "True" and raw.lstrip().startswith("#"))
        has_hash = (raw.lstrip().startswith("#") and self.data.get("silo_color_box", "True") == "True")
        silo_colors = self.data.get("silo_colors", {})
        if not isinstance(silo_colors, dict): silo_colors = {}
        color_hex = silo_colors.get(str(idx), "") if has_hash else ""

        btn.update_data(label, idx, bg_color, font_family, scale, line_str, True, title_bold, is_child, fcount, has_children, is_collapsed, has_hash, color_hex, is_pinned)

    def mark_dirty(self, domain=None):
        self.state.mark_dirty(domain)

    def _auto_save_tick(self):
        if not getattr(self.state, "has_pending_changes", getattr(self.state, "_db_dirty", False)):
            return
        self.save_data_to_db()

    def play_sound(self, name):
        self.sound_manager.play(name)

    def play_click_sound(self):
        self.sound_manager.play_click()

    def play_tick_sound(self, on=True):
        self.sound_manager.play_tick(bool(on))

    # Which shortcuts get a sound of their own. Everything else falls back to
    # the generic `hotkey` event, which ships DISABLED — a sound on literally
    # every shortcut, on by default, is a reason to switch sound off entirely.
    HOTKEY_SOUND_EVENTS = {
        "hk_undo": "undo",
        "Ctrl+Y": "redo",
        "Ctrl+Shift+Z": "redo",
        "Ctrl+A": "select_all",
        "hk_settings": "settings",
        "hk_help": "help",
        "F1": "help",
        "hk_new_snippet": "new",
        "hk_save_snippet": "save",
        "hk_bold": "bold",
        "hk_italic": "italic",
        "hk_underline": "underline",
        "hk_header": "header",
        "hk_divider": "divider",
        "hk_snap": "snap",
        "hk_find": "find",
        "hk_replace": "replace",
        "hk_focus": "focus",
        "hk_export_silo": "export",
        "hk_quit": "quit",
        "Ctrl+T": "strike",
        "lock_window_hotkey": "lock",
        "always_on_top_hotkey": "lock",
        "toggle_sidebar_hotkey": "sidebar",
    }

    # Actions that make their own sound from INSIDE, on every route they can
    # be reached by — Ctrl+Z also arrives straight from the editor's
    # keyPressEvent (editor.py:2796), which never passes through
    # add_shortcut. Wrapping these as well played two sounds for one
    # keystroke on the shortcut path and one on the editor path: the sound
    # belongs to the action, not to the key.
    HOTKEY_SOUND_SELF = frozenset({
        "hk_undo", "Ctrl+Y", "Ctrl+Shift+Z",
        # select_empty_silo and save_snippet play their own sounds ("new" /
        # "snippet") internally — the wrapper's "new"/"save" event would fire
        # on top of them and make one key press two sounds.
        "hk_new_snippet", "hk_save_snippet",
        # open_help_dialog plays its own tick internally; F1/hk_help would
        # double it with the wrapper's "help" event.
        "hk_help", "F1",
    })

    def sound_event_for_hotkey(self, key):
        """The sound event a shortcut should request. Never None: an action
        with no event of its own is still a hotkey."""
        return self.HOTKEY_SOUND_EVENTS.get(key, "hotkey")

    def _with_hotkey_sound(self, key, slot):
        """Wrap a shortcut's slot so pressing it makes a sound.

        Wrapping at the ONE place shortcuts are registered is the difference
        between "every hotkey has a sound" and "the eleven hotkeys somebody
        remembered to edit" — the next shortcut anyone adds is covered
        without them knowing this exists. The sound goes first so it is not
        swallowed when the slot opens a modal.
        """
        if key in self.HOTKEY_SOUND_SELF:
            return slot
        event = self.sound_event_for_hotkey(key)

        def _run():
            try:
                self.play_sound(event)
            except Exception:
                pass
            return slot()

        return _run

    def _deferred_silo_refresh(self, attempts=10):
        """Called once after the window layout is computed to set correct silo count."""
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            self._update_visible_silo_count()
            self.refresh_temp_presets()
        elif attempts > 0:
            # Layout not ready yet, try again
            QTimer.singleShot(50, lambda: not sip.isdeleted(self) and self._deferred_silo_refresh(attempts - 1))
    def _update_visible_silo_count(self):
        if hasattr(self, "silos_widget") and self.silos_widget.height() > 0:
            estimate = int(24 * getattr(self, "_ui_scale", 0.5))
            for btn in getattr(self, "silo_buttons", []):
                bh = btn.height() if btn.isVisible() else btn.sizeHint().height()
                if bh > 0:
                    estimate = bh
                    break
            spacing = 2
            self._visible_silos = max(
                1, (self.silos_widget.height() + spacing) // (estimate + spacing)
            )
        else:
            self._visible_silos = 10

    def setup_single_instance_server(self):
        self.ipc = IpcServer(self.show_window)
        self.ipc.setup()

    # init_db removed, moved to FastPrompterState

    def get_current_context_key(self):
        if getattr(self, "editing_snippet", None):
            cat, idx = self.editing_snippet
            return f"snippet:{cat}:{idx}"
        else:
            return f"silo:{self.active_temp_slot}"

    def save_data_to_db(self, force=False):
        # Capture the current silo's view state so the saved position,
        # cursor, and scroll survive restart.
        if not getattr(self, "_suspend_cache", False) and hasattr(self, "text_area"):
            self.capture_silo_state(self.active_temp_slot,
                                    getattr(self, "active_is_archive", False))
            # and WHICH silo that was, for this project — the outer half of
            # "put me back where I left off"
            self.capture_silo_session()
        if hasattr(self, "text_area"):
            cached = getattr(self, "_last_cached_text", None)
            current_text = self.text_area.toPlainText() if cached is None else cached
            self._last_cached_text = None
        else:
            current_text = self.data.get("last_text", "")
        self._last_saved_text = current_text

        # CORE-001: the live editor owner must be flushed synchronously before
        # EVERY authoritative save. Snippet mode copies the exact editor text
        # into the referenced snippet (updating last-edited metadata and the
        # snippets domain dirty flag); silo mode keeps the established
        # per-slot behaviour under its suspension guards.
        if (
            not getattr(self, "_suspend_cache", False)
            and not getattr(self, "_initializing_ui", False)
            and not getattr(self, "_suspend_temp_sync", False)
        ):
            self._flush_live_editor(current_text)

        self.data["window_locked"] = "True" if getattr(self, "is_locked", False) else "False"

        ui_settings = {
            "last_tab_idx": str(self.data["last_tab_idx"]),
            "active_temp_slot": str(self.active_temp_slot),
            "last_geometry": self.data.get("last_geometry", ""),
            "font_size": str(self.font_spin.value())
            if hasattr(self, "font_spin")
            else str(self.data.get("font_size", 11)),
            "preview_mode": (self.preview_combo.currentData() or self.preview_combo.currentText())
            if hasattr(self, "preview_combo")
            else self.data.get("preview_mode", "None"),
            "paste_mode": self.data.get("paste_mode", "Plain"),
            "tray_visible": str(self.cb_tray.isChecked())
            if hasattr(self, "cb_tray")
            else self.data.get("tray_visible", "True"),
            "close_on_focus_loss": str(self.cb_focus.isChecked())
            if hasattr(self, "cb_focus")
            else self.data.get("close_on_focus_loss", "True"),
            "ctrl_c_closes": str(self.cb_ctrl_c.isChecked())
            if hasattr(self, "cb_ctrl_c")
            else self.data.get("ctrl_c_closes", "True"),
            "silo_last_edited": getattr(self, "silo_last_edited", {}),
        }

        ok = bool(self.state.save_data_to_db(current_text, ui_settings,
                                              force=force))
        # P0-2: the filesystem mirror must only be published when the
        # authoritative SQLite save SUCCEEDED. A failed commit stays dirty and
        # retryable; dispatching a mirror snapshot would let the disk copy
        # become newer than the DB it is documented to mirror.
        if ok:
            # W2-001: a successful durable commit is the ONLY moment journal
            # records whose recovery pairs are now persisted may be retired.
            try:
                from fastprompter.ui.snippet_ops_mixin import (
                    _ack_retirement_journal,
                )
                _ack_retirement_journal(self._files_root(), self.data)
            except Exception:
                pass
            # PERF-004: the one-way mirror gets its own dirty routing,
            # separate from generic DB dirtiness. A settings-only save must
            # not rebuild the whole hierarchy snapshot; mirror-visible
            # settings changes (root/mode/topology maps) still do.
            if (force
                    or getattr(self.state, "last_save_had_silo_text", False)
                    or self._mirror_settings_dirty()):
                self.sync_to_disk()
            # PERF-004: Sync-Project / per-silo links publish silo text to disk
            # only when THIS save actually touched a silo-text domain, or a
            # forced save demands it. A settings-only persistence (font size,
            # geometry, a checkbox) must not traverse every bound file and
            # perform stat/read work on the GUI thread for no text to publish.
            # App-side text edits are covered independently by the 1.5s typing
            # debounce (_sync_push_timer / _on_text_changed).
            if force or getattr(self.state, "last_save_had_silo_text", False):
                self._push_sync_files()
        return ok

    # =====================================================================
    # Typecheck (typo checker) — core/typecheck.py holds the logic, this
    # is the UI wiring: debounced scan, underline spans, context menu,
    # whole-project report, user dictionary.
    # =====================================================================

    def _typo_dictionary(self):
        """The dictionary for the current profile: base words + UI vocab of
        every app language + the user's own words. Cached until it grows."""
        if self._typo_dict_cache is None:
            from fastprompter.core import typecheck as tc
            from fastprompter.core.typecheck_words import BASE_WORDS
            user_words = self.data.get("typo_user_words") or []
            if not isinstance(user_words, list):
                user_words = []
            self._typo_dict_cache = tc.Dictionary(
                base_words=BASE_WORDS,
                ui_words=tc.ui_vocabulary(),
                user_words=user_words,
            )
        return self._typo_dict_cache

    def _typo_check_tick(self):
        """Debounced: scan the ACTIVE document and paint underline spans.

        Runs on a 450ms timer after typing and on silo/tab switches. When
        the feature is off the spans are cleared so no stale underlines
        linger after a settings toggle.

        PERF-005: the tokenization/dictionary pass is O(document) and used
        to run right here, on the GUI thread — a ~500k-character document
        hitched the UI for ~100ms on every typing pause. The scan now runs
        on a worker over an immutable text snapshot; the result paints only
        when the document revision, silo identity and feature flag are all
        still current. A stale result is discarded, never applied to newer
        text or another silo/profile."""
        editor = getattr(self, "text_area", None)
        if editor is None or sip.isdeleted(editor):
            return
        if self.data.get("typo_check_enabled", "False") != "True":
            self._typo_apply_spans([])
            # PERF-003: drop any queued snapshot — the feature is off, so no
            # scan should be pending or start.
            self._typo_pending = None
            return
        try:
            from fastprompter.core import typecheck as _tc  # noqa: F401
            text = editor.toPlainText()
            doc_rev = editor.document().revision()
            ident = (self.get_current_category() or "",
                     getattr(self, "active_temp_slot", -1),
                     bool(getattr(self, "active_is_archive", False)))
            self._typo_request_seq = getattr(self, "_typo_request_seq", 0) + 1
            request_id = self._typo_request_seq
            dictionary = self._typo_dictionary()
            # PERF-003: one physical scan in flight + at most one newest
            # pending snapshot. A burst of rechecks must not queue N full
            # O(document) passes — only the first and the final requested
            # states are ever scanned; intermediate snapshots are dropped.
            if self._typo_inflight is not None:
                self._typo_pending = (request_id, text, dictionary,
                                       ident, doc_rev)
                return
            worker = self._ensure_typo_worker()
            worker.scan.emit(request_id, text, dictionary)
            # remember what this in-flight scan was taken against
            self._typo_inflight = (request_id, ident, doc_rev)
        except Exception:
            self._typo_apply_spans([])

    def _typo_apply_spans(self, spans):
        """Paint spans onto the live editor (GUI thread)."""
        editor = getattr(self, "text_area", None)
        if editor is not None and not sip.isdeleted(editor):
            editor._typo_spans = spans
            editor._typo_color = self.data.get("typo_color", "#e05555")
            try:
                editor.viewport().update()
            except Exception:
                pass

    def _ensure_typo_worker(self):
        """PERF-005: the persistent typo-scan worker thread."""
        if getattr(self, "_typo_worker", None) is None:
            thread = QThread()
            thread.setObjectName("fastprompter-typo-scan")
            worker = _TypoScanWorker()
            worker.moveToThread(thread)
            worker.scan.connect(worker._run)   # AFTER moveToThread: queued
            worker.scanned.connect(self._on_typo_scanned)
            thread.start()
            self._typo_worker = worker
            self._typo_thread = thread
        return self._typo_worker

    def _dispatch_pending_typo_scan(self):
        """PERF-003: start the single queued newest snapshot (if any) now that
        the previous physical scan has retired. Guarantees at most one in
        flight and one pending, so a burst of rechecks never queues more than
        two full O(document) passes."""
        pending = getattr(self, "_typo_pending", None)
        if pending is None:
            return
        self._typo_pending = None
        if self.data.get("typo_check_enabled", "False") != "True":
            return
        _rid, _text, _dict, _ident, _rev = pending
        self._typo_inflight = (_rid, _ident, _rev)
        worker = self._ensure_typo_worker()
        worker.scan.emit(_rid, _text, _dict)

    def _on_typo_scanned(self, request_id, spans):
        """A scan finished. Apply it ONLY when it is still the newest
        request AND the world it was captured against has not moved: same
        silo identity, same document revision, feature still enabled."""
        from fastprompter.main import is_gui_thread
        if not is_gui_thread():
            from fastprompter.core.logging import logger
            logger.critical("typo scan completion rejected outside GUI "
                            "thread")
            return
        inflight = getattr(self, "_typo_inflight", None)
        if inflight is None or inflight[0] != request_id:
            return  # superseded by a newer scan
        _rid, ident, doc_rev = inflight
        self._typo_inflight = None
        # PERF-003: the in-flight scan is done — launch the single queued
        # snapshot (if any) before evaluating this result, so the newest
        # requested document state is never skipped.
        self._dispatch_pending_typo_scan()
        if self.data.get("typo_check_enabled", "False") != "True":
            return
        cur_ident = (self.get_current_category() or "",
                     getattr(self, "active_temp_slot", -1),
                     bool(getattr(self, "active_is_archive", False)))
        if cur_ident != ident:
            return  # the user switched silos/projects meanwhile
        editor = getattr(self, "text_area", None)
        if editor is None or sip.isdeleted(editor):
            return
        try:
            if editor.document().revision() != doc_rev:
                return  # typed again since the snapshot — next tick owns it
        except Exception:
            return
        self._typo_apply_spans(spans)

    def typo_worker_shutdown(self, timeout_s=2.0):
        """Bounded stop of the typo-scan thread at exit."""
        thread = getattr(self, "_typo_thread", None)
        if thread is None or not thread.isRunning():
            self._typo_thread = None
            self._typo_worker = None
            return True
        thread.quit()
        stopped = wait_thread_seconds(thread, timeout_s,
                                      "typo scan worker")
        if stopped:
            _RETIRED_WORKERS.append(getattr(self, "_typo_worker", None))
            _RETIRED_WORKERS.append(thread)
            self._typo_thread = None
            self._typo_worker = None
        else:
            from fastprompter.core.logging import logger
            logger.warning("typo scan worker shutdown TIMED_OUT; live "
                           "worker/thread retained")
        return stopped

    def _add_typo_word(self, word):
        """Remember a word (lowercased) so the checker never flags it again."""
        word = (word or "").strip().lower()
        if not word:
            return
        # NB: no ``or []`` here — when the stored list is empty it is falsy
        # and the ``or`` would hand us a throwaway copy, so the append below
        # would never reach the persisted store.
        words = self.data.get("typo_user_words")
        if not isinstance(words, list):
            words = []
            self.data["typo_user_words"] = words
        if word not in words:
            words.append(word)
        self._typo_dict_cache = None  # the pool grew — rebuild on next use
        self.mark_dirty()
        self._typo_check_tick()

    def clear_typo_words(self):
        """Settings button: forget every word the user added."""
        lang = getattr(self, "_current_lang", "EN")
        reply = QMessageBox.question(
            self, tr("Clear my words", lang),
            tr("Forget every word you added to the dictionary?", lang),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.data["typo_user_words"] = []
        self._typo_dict_cache = None
        self.mark_dirty()
        self._typo_check_tick()

    def _save_sync_include(self):
        raw = self.ed_sync_include.text().strip()
        self.data.update({"sync_include": raw})
        cfg = self._sync_config()
        if cfg is not None:
            from fastprompter.core import project_sync as ps
            cfg["include"] = ps.parse_ext_list(raw)
            self.data.setdefault("project_sync_all", {})[
                self.get_current_category() or ""] = cfg
            self._rescan_project_sync()
        self.mark_dirty()

    def _save_sync_exclude(self):
        raw = self.ed_sync_exclude.text().strip()
        self.data.update({"sync_exclude": raw})
        cfg = self._sync_config()
        if cfg is not None:
            from fastprompter.core import project_sync as ps
            cfg["exclude"] = ps.parse_exclude_list(raw)
            self.data.setdefault("project_sync_all", {})[
                self.get_current_category() or ""] = cfg
            self._rescan_project_sync()
        self.mark_dirty()

    def _save_sync_recursive(self, checked):
        """Apply the folder-depth setting to the active Sync-Project too."""
        self.data.update({"sync_recursive": "True" if checked else "False"})
        cfg = self._sync_config()
        if cfg is not None:
            cfg["recursive"] = bool(checked)
            self.data.setdefault("project_sync_all", {})[
                self.get_current_category() or ""] = cfg
            self._rescan_project_sync()
            self._start_project_watcher()
        self.mark_dirty()

    def pick_passed_colour(self):
        from PyQt6.QtWidgets import QColorDialog
        lang = getattr(self, "_current_lang", "EN")
        col = QColorDialog.getColor(
            QColor(self.data.get("passed_event_color", "#e05555")),
            self, tr("Pick Color", lang))
        if col.isValid():
            self.data["passed_event_color"] = col.name()
            btn = getattr(self, "btn_passed_colour", None)
            if btn is not None and not sip.isdeleted(btn):
                btn.setText(col.name())
            self.mark_dirty()
            self._apply_date_alert_style()

    def reset_passed_colour(self):
        self.data["passed_event_color"] = "#e05555"
        btn = getattr(self, "btn_passed_colour", None)
        if btn is not None and not sip.isdeleted(btn):
            btn.setText("#e05555")
        self.mark_dirty()
        self._apply_date_alert_style()

    def pick_typo_colour(self):
        from PyQt6.QtWidgets import QColorDialog
        lang = getattr(self, "_current_lang", "EN")
        col = QColorDialog.getColor(
            QColor(self.data.get("typo_color", "#e05555")),
            self, tr("Pick Color", lang))
        if col.isValid():
            self.data["typo_color"] = col.name()
            btn = getattr(self, "btn_typo_colour", None)
            if btn is not None and not sip.isdeleted(btn):
                btn.setText(col.name())
            self.mark_dirty()
            self._typo_check_tick()

    def build_spelling_menu(self, menu, pos):
        """Editor right-click: suggestions + add-to-dictionary for the word
        under the cursor. Adds nothing when the feature is off or the cursor
        is not on a flagged word."""
        if self.data.get("typo_check_enabled", "False") != "True":
            return False
        spans = getattr(self.text_area, "_typo_spans", None)
        if not spans:
            return False
        pos_abs = self.text_area.textCursor().position()
        hit = None
        for s, e in spans:
            if s <= pos_abs <= e:
                hit = (s, e)
                break
        if hit is None:
            return False
        start, end = hit
        word = self.text_area.toPlainText()[start:end]
        if not word:
            return False
        lang = getattr(self, "_current_lang", "EN")
        menu.addSeparator()
        head = menu.addAction(tr("✏ Typo:", lang) + f" «{word}»")
        head.setEnabled(False)
        for sug in self._typo_dictionary().suggest(word):
            menu.addAction(
                f"    {sug}",
                lambda _c=False, s=sug: self._replace_typo_word(start, end, s))
        act = menu.addAction(tr("✓ Add to dictionary", lang))
        act.triggered.connect(lambda _c=False: self._add_typo_word(word))
        return True

    def _replace_typo_word(self, start, end, replacement):
        """Swap a flagged word for a suggestion (one undo step)."""
        editor = self.text_area
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        from fastprompter.ui.edit_guard import edit_block
        with edit_block(cursor, editor):
            cursor.insertText(replacement)
        self._typo_check_tick()

    def check_project_typos(self):
        """Project context menu: typecheck EVERY silo of this project."""
        from fastprompter.ui.typo_check_dialog import TypoCheckDialog
        self.ignore_focus_loss = True
        try:
            TypoCheckDialog(self).exec()
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()

    # =====================================================================
    # Sync-Project + per-silo file links.
    # core/project_sync.py holds the pure logic (scan, match, EOL, atomic
    # write); this is the Qt wiring: QFileSystemWatcher, debounce timers,
    # the slot<->file mapping, push (app->file) and apply (file->app).
    # =====================================================================

    def _ensure_temp_presets(self):
        """The ACTIVE category's silo-text list, guaranteed stored.

        ``self.data.get("temp_presets") or []`` silently fabricates a
        throwaway list whenever the store is empty — every mutation then
        lands in an orphan and the silo text vanishes. Callers that MUTATE
        must hold the persisted container, so create-and-store instead."""
        presets = self.data.get("temp_presets")
        if not isinstance(presets, list):
            presets = []
            self.data["temp_presets"] = presets
        return presets

    def _sync_config(self):
        """The active category's Sync-Project config dict, or None."""
        cfg = self.data.get("project_sync")
        if not isinstance(cfg, dict) or not cfg.get("root"):
            return None
        return cfg

    def _sync_root(self):
        cfg = self._sync_config()
        return os.path.abspath(cfg["root"]) if cfg else None

    def _sync_include(self):
        from fastprompter.core import project_sync as ps
        cfg = self._sync_config() or {}
        inc = cfg.get("include")
        if not isinstance(inc, list):
            inc = ps.parse_ext_list(self.data.get("sync_include", ""))
        return inc or list(ps.DEFAULT_INCLUDE)

    def _sync_exclude(self):
        from fastprompter.core import project_sync as ps
        cfg = self._sync_config() or {}
        exc = cfg.get("exclude")
        if not isinstance(exc, list):
            exc = ps.parse_exclude_list(self.data.get("sync_exclude", ""))
        # An explicit [] in an active project means the user intentionally
        # cleared the exclude field; do not silently restore the defaults.
        if isinstance(cfg.get("exclude"), list):
            return list(exc)
        return exc or list(ps.DEFAULT_EXCLUDE)

    def _sync_recursive(self):
        cfg = self._sync_config() or {}
        if "recursive" in cfg:
            value = cfg["recursive"]
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "on"}
            return bool(value)
        return self.data.get("sync_recursive", "True") == "True"

    def _sync_max_bytes(self):
        try:
            return max(1024, int(self.data.get("sync_max_kb", "512"))) * 1024
        except (TypeError, ValueError):
            return 512 * 1024

    def _sync_file_for_slot(self, slot):
        """Absolute path of the Sync-Project file bound to ``slot``."""
        root = self._sync_root()
        if not root:
            return None
        rel = (self.data.get("project_sync_map") or {}).get(str(slot))
        if not rel:
            return None
        from fastprompter.core import project_sync as ps
        return ps.resolve_relative_path(root, rel)

    def _link_file_for_slot(self, slot):
        """Absolute path of the per-silo linked file, or None."""
        path = (self.data.get("silo_links") or {}).get(str(slot))
        return path if isinstance(path, str) and path else None

    def _sync_binding_path_for_cat(self, cat, slot):
        """CORE-004: resolve the bound file for an IMMUTABLE captured category.

        Completion handlers must never use the active-category flat aliases
        (``silo_links`` / ``project_sync_map``) as ownership proof for an
        asynchronous push result: the user may have switched category while
        the job was in flight. Resolve from the per-category stores instead."""
        links = (self.data.get("silo_links_all") or {}).get(cat, {})
        path = links.get(str(slot))
        if isinstance(path, str) and path:
            return path
        rel = (self.data.get("project_sync_map_all") or {}).get(cat, {}).get(
            str(slot))
        if not rel:
            return None
        pscfg = (self.data.get("project_sync_all") or {}).get(cat) or {}
        root = pscfg.get("root")
        if not root:
            return None
        from fastprompter.core import project_sync as ps
        return ps.resolve_relative_path(os.path.abspath(root), rel)

    def _sync_current_text_for_cat(self, cat, slot):
        """CORE-004: the silo text that currently owns ``(cat, slot)``.

        Returns the live editor text when the binding is the active category's
        active, non-archive, non-snippet slot; otherwise the stored preset for
        that captured category. Returns ``None`` only when the slot is absent —
        callers treat ``None`` as "ownership moved, skip"."""
        active = getattr(self, "active_temp_slot", -1)
        editing = getattr(self, "editing_snippet", None)
        arc = getattr(self, "active_is_archive", False)
        if (cat == self.get_current_category() and slot == active
                and not editing and not arc):
            try:
                return self.text_area.toPlainText()
            except Exception:
                return None
        presets = (self.data.get("temp_presets_all") or {}).get(cat, [])
        if isinstance(slot, int) and 0 <= slot < len(presets):
            return presets[slot] or ""
        return None

    def _silo_is_synced(self, slot):
        return (self._sync_file_for_slot(slot) is not None
                or self._link_file_for_slot(slot) is not None)

    def _sync_baseline_key(self, slot, path, cat=None):
        """W2-004: the logical owner of a sync baseline, not just the path.

        ``_sync_last_applied`` is a process-wide dict. Keying it by path alone
        lets a baseline produced by project/silo A leak into project/silo B:
        B then classifies A's write as its own and silently overwrites a
        real two-sided conflict. The owner is ``(category, slot,
        canonical_path)`` — category resolves to the active category when the
        caller has no explicit one.
        """
        if cat is None:
            cat = self.get_current_category() or ""
        canonical = os.path.normcase(os.path.abspath(path))
        return (cat, int(slot) if isinstance(slot, int) else str(slot),
                canonical)

    @staticmethod
    def _sync_side_digest(text):
        """PERF-007: compact, stable content digest for skip-cache identity.

        Length + a small cryptographic digest: collision-resistant enough for
        conflict identity while never retaining the full document body in
        session metadata."""
        import hashlib
        data = (text or "").encode("utf-8", "replace")
        return (len(data), hashlib.blake2b(data, digest_size=16).digest())

    def _sync_baseline_value(self, slot, path):
        """Return a canonical baseline, healing legacy raw-text entries.

        Older sessions and early link code stored the full text here. Keep
        those sessions safe: convert the value once instead of treating a
        raw string as a digest and incorrectly declaring the silo dirty.
        """
        key = self._sync_baseline_key(slot, path)
        value = self._sync_last_applied.get(key)
        if isinstance(value, str):
            value = self._sync_side_digest(value)
            self._sync_last_applied[key] = value
        return value

    def _sync_lease(self, key):
        """CORE-001: the current binding lease for a baseline key."""
        return self._sync_leases.get(key, 0)

    def _sync_invalidate_binding(self, idx, path):
        """CORE-001: an ownership transition on (idx, path).

        Drops the session baseline/EOL metadata, bumps the binding lease so
        any queued or in-flight push job carrying the old lease is rejected
        before it can mutate the file, and removes any pending job for the
        same owner."""
        links = self.data.get("silo_links") or {}
        mapping = self.data.setdefault("project_sync_map", {})
        if str(idx) not in links and str(idx) not in mapping:
            # only invalidate when this slot still owns the path
            pass
        key = self._sync_baseline_key(idx, path)
        self._sync_last_applied.pop(key, None)
        self._sync_eol_cache.pop(key, None)
        # CORE-003: BOM state belongs to the binding like EOL — a reused
        # logical key must not inherit stale BOM from an earlier owner.
        self._sync_bom_cache.pop(key, None)
        self._sync_unsafe_bindings.discard(key)
        # CORE-003: bump the lease under the shared commit gate so the
        # transition is atomic with the worker's final mutation. Once this
        # block completes, no in-flight job carrying the old lease can begin
        # (or finish) a write, because the worker re-checks the lease inside
        # the same gate immediately before its filesystem mutation.
        with self._sync_commit_gate:
            self._sync_leases[key] = self._sync_leases.get(key, 0) + 1
        self._push_jobs_pending.pop(key, None)

    def _sync_flag_unsafe_binding(self, key, path):
        """CORE-001: a fresh-binding read found the destination exists but is
        not safe text (binary/over-limit/invalid UTF-8). Record it so the next
        push round (and this one) never silently overwrites it, but do NOT
        establish a baseline that would legitimise the overwrite."""
        self._sync_unsafe_bindings.add(key)
        # Drop any pending job that would try to recreate the file; the
        # established-binding worker also refuses to overwrite an existing
        # unsafe target, so the flag is the authoritative fresh-binding guard.
        self._push_jobs_pending.pop(key, None)
        from fastprompter.core.logging import logger
        logger.debug("sync unsafe binding flagged: %s", os.path.basename(path))

    def _silo_clean(self, slot, path):
        """True when ``slot`` holds NO app-side text newer than what we last
        wrote to ``path`` — i.e. an external change may be applied safely.

        The active silo's live editor text is the authority; for inactive
        silos the stored text is. If we never touched the path, the silo is
        considered clean (a fresh binding)."""
        applied = self._sync_baseline_value(slot, path)
        if applied is None:
            return True
        # T-1037: baselines are compact (len, blake2b) digests, not bodies.
        if (slot == getattr(self, "active_temp_slot", -1)
                and not getattr(self, "editing_snippet", None)
                and not getattr(self, "active_is_archive", False)):
            try:
                return self._sync_side_digest(self.text_area.toPlainText()) == applied
            except Exception:
                return False
        presets = self._ensure_temp_presets()
        if 0 <= slot < len(presets):
            return self._sync_side_digest(presets[slot]) == applied
        return True

    def _sync_conflict_choice(self, path, slot, file_text, silo_text, cat=None):
        """Resolve a two-sided edit conflict, remembering "skip for now".

        A conflict is a bound file whose content differs from its silo while
        we have NO session baseline for it (e.g. both were edited while the
        app was closed) — neither side can be judged newer, so silently
        picking one would lose the other's work.

        Returns ``'app'`` (the silo text wins), ``'file'`` (the file text
        wins) or ``None`` when the user chose to skip for now. A skipped
        conflict is recorded as ``(owner, path, file_text, silo_text)`` so it
        stops nagging until one of the two sides changes — and W2-004 scopes
        the skip to its logical owner, so one category's "skip" can never
        suppress another category's conflict on the same physical file.
        """
        owner = self._sync_baseline_key(slot, path, cat)
        # PERF-007: at most ONE skipped-conflict record per logical owner.
        # A dict keyed by owner holds the compact digests of the two sides;
        # re-skipping the SAME unchanged conflict is a hit, and any change on
        # either side replaces the record instead of accumulating history.
        skipped = getattr(self, "_sync_conflict_skipped", None)
        if not isinstance(skipped, dict):
            self._sync_conflict_skipped = {}
            skipped = self._sync_conflict_skipped
        digest = self._sync_side_digest
        entry = (digest(file_text), digest(silo_text))
        if skipped.get(owner) == entry:
            return None
        choice = self._sync_ask_conflict(path, slot, file_text, silo_text)
        if choice is None:
            skipped[owner] = entry
        return choice

    def _sync_ask_conflict(self, path, slot, file_text, silo_text):
        """The modal "which side wins?" dialog. Returns 'app' | 'file' | None."""
        lang = getattr(self, "_current_lang", "EN")

        def _preview(s):
            s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
            s = "\n".join(line for line in s.split("\n") if line.strip())
            return (s[:200] + "…") if len(s) > 200 else (s or "—")

        box = QMessageBox(self)
        box.setWindowTitle(tr("Sync conflict", lang))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(tr(
            "The file and its silo were both changed and cannot be merged "
            "automatically.\n\n{}\n\nWhich version should win?", lang)
            .format(os.path.basename(path)))
        box.setInformativeText(tr(
            "App version (silo {}):\n{}\n\nFile version:\n{}", lang)
            .format(slot + 1, _preview(silo_text), _preview(file_text)))
        btn_app = box.addButton(tr("Keep app version", lang),
                                QMessageBox.ButtonRole.AcceptRole)
        btn_file = box.addButton(tr("Keep file version", lang),
                                 QMessageBox.ButtonRole.AcceptRole)
        # the skip button needs no reference: any click that is neither
        # "app" nor "file" (skip, or the dialog was dismissed) means None
        box.addButton(tr("Skip for now", lang),
                      QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_app)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_app:
            return "app"
        if clicked is btn_file:
            return "file"
        return None

    def _drop_slot_bindings(self, idx):
        """Unbind a silo from its file(s) WITHOUT touching the files.

        Used when a silo's text is about to be replaced by something that is
        not an edit (archiving): the file on disk must survive untouched."""
        links = self.data.get("silo_links") or {}
        path = links.pop(str(idx), None)
        if path:
            self._sync_invalidate_binding(idx, path)
        mapping = self.data.setdefault("project_sync_map", {})
        rel = mapping.pop(str(idx), None)
        if rel and self._sync_root():
            from fastprompter.core import project_sync as ps
            path = ps.resolve_relative_path(self._sync_root(), rel)
            if path:
                self._sync_invalidate_binding(idx, path)

    def _push_sync_files_active(self):
        """PERF-002: the 1.5s typing debounce publishes ONLY the active
        silo's binding — the slot the keystrokes actually landed in — not
        every bound silo in the project."""
        try:
            active = getattr(self, "active_temp_slot", -1)
        except Exception:
            active = -1
        self._push_sync_files(slots=None if active < 0 else {active})

    def _push_sync_files(self, slots=None):
        """App -> file: write bound silos' text to their files.

        ``slots=None`` reconciles EVERY bound silo (force saves, project
        switches, shutdown); a set of slots publishes only those owners
        (PERF-002: the typing debounce and silo navigation must not pay
        CPU proportional to the whole project's bound bytes).

        Runs on the 1.5s typing debounce and after every silo-text DB save
        (PERF-004: a settings-only save never reaches here). The ACTIVE
        silo's live editor text wins over the cached copy.

        T-1039: plain changed writes (baseline already established) are
        handed to the dedicated worker thread -- encode/temp/replace never
        block the GUI. Each job carries the expected disk digest and the
        binding lease captured NOW; the worker re-validates both before it
        mutates anything (CORE-001). Fresh bindings (no baseline yet) keep
        the synchronous read+conflict path, because the conflict dialog is
        inherently a GUI decision and such bindings are rare. Unchanged
        bindings are skipped by digest equality alone, with no per-file stat.
        """
        if not hasattr(self, "_sync_last_applied"):
            return
        if getattr(self, "_initializing_ui", False):
            return
        if getattr(self, "_suppress_sync_push", False):
            # W2-001: during a category-delete ownership transition the flat
            # aliases may still point at the dying category's structures;
            # publishing them must be impossible.
            return
        try:
            presets = self._ensure_temp_presets()
            active = getattr(self, "active_temp_slot", -1)
            editing_snippet = getattr(self, "editing_snippet", None)
            from fastprompter.core import project_sync as ps
            max_bytes = self._sync_max_bytes()
            all_slots = range(len(presets)) if slots is None else sorted(
                s for s in set(slots) if isinstance(s, int))
            for slot in all_slots:
                if not (0 <= slot < len(presets)):
                    continue
                path = self._link_file_for_slot(slot) or self._sync_file_for_slot(slot)
                if not path:
                    continue
                text = presets[slot] or ""
                if (slot == active and not editing_snippet
                        and not getattr(self, "active_is_archive", False)):
                    try:
                        text = self.text_area.toPlainText()
                    except Exception:
                        # T-1030: editor unavailable -- keep the preset text
                        # out of the comparison and skip this slot this
                        # round instead of writing from a stale buffer.
                        continue
                key = self._sync_baseline_key(slot, path)
                digest = self._sync_side_digest(text)
                baseline = self._sync_baseline_value(slot, path)
                if baseline == digest:
                    # PERF-004/T-1039: digest equality alone proves we wrote
                    # exactly this content; no per-file stat is needed.
                    continue
                if baseline is None:
                    # Fresh binding: read + possible two-sided conflict. This
                    # needs the GUI (dialog), so it stays on this thread; it
                    # happens once per binding, not per keystroke.
                    eol = "\n"
                    had_bom = False
                    approved_digest = None
                    read = ps.read_text_file(path, max_bytes)
                    if read is not None:
                        # CORE-001: a previously-flagged unsafe target is now
                        # safe text again; clear the flag so it participates
                        # normally in future fresh-binding rounds.
                        self._sync_unsafe_bindings.discard(key)
                        eol = read[1]
                        self._sync_eol_cache[key] = eol
                        # CORE-007: remember the source BOM so the app->file
                        # push below re-emits it instead of dropping it.
                        had_bom = read[2]
                        self._sync_bom_cache[key] = had_bom
                        if read[0] != text:
                            choice = self._sync_conflict_choice(
                                path, slot, read[0], text)
                            if choice == "file":
                                # the file text wins: pull it into the silo
                                self._sync_last_applied[key] = \
                                    self._sync_side_digest(read[0])
                                presets[slot] = read[0]
                                if (slot == active and not editing_snippet
                                        and not getattr(self, "active_is_archive",
                                                        False)):
                                    self._set_plain_text_clean(
                                        self.text_area, read[0])
                                continue
                            if choice != "app":
                                continue  # skipped for now — leave both sides
                            # "app": the user approved overwriting the file AS
                            # IT WAS when the dialog opened. Remember the exact
                            # approved baseline to re-validate at mutation time.
                            approved_digest = self._sync_side_digest(read[0])
                        else:
                            # PERF-003: fresh revalidation found the file
                            # ALREADY equal to the silo. Establish the
                            # baseline (digest + EOL) and stop — equality
                            # must never become a physical rewrite.
                            self._sync_leases.setdefault(key, 0)
                            self._sync_last_applied[key] = digest
                            continue
                    else:
                        # read_text_file returned None. This collapses several
                        # materially different states — missing/inaccessible,
                        # over-limit, binary/NUL, or invalid UTF-8 — into one.
                        self._sync_leases.setdefault(key, 0)
                        if os.path.exists(path):
                            # CORE-001: destination exists but is an unsafe
                            # text target. Do NOT overwrite it and do NOT
                            # establish an optimistic baseline.
                            from fastprompter.core.logging import logger
                            logger.warning(
                                "sync fresh binding refused: destination exists "
                                "but is not safe text (%s); left unchanged",
                                os.path.basename(path))
                            self._sync_flag_unsafe_binding(key, path)
                            continue
                        # Genuinely missing destination: approve recreation.
                        # approved_digest stays None (file absent) so the
                        # mutation-time revalidation refuses if another process
                        # creates it first.

                    # CORE-005: mutation-time revalidation. The approval (or the
                    # missing-file decision) was made against the file state
                    # read ABOVE. Re-read the destination immediately before the
                    # write; if it changed from the approved baseline — a newer
                    # external edit, or a file that appeared where none was —
                    # REFUSE to clobber it and re-evaluate on the next round.
                    _reval = ps.read_text_file(path, max_bytes)
                    if _reval is not None:
                        _cur_d = self._sync_side_digest(_reval[0])
                    else:
                        _cur_d = None if not os.path.exists(path) else "<unsafe>"
                    if _cur_d != approved_digest:
                        self._sync_leases.setdefault(key, 0)
                        if _reval is not None or os.path.exists(path):
                            self._sync_flag_unsafe_binding(key, path)
                        continue
                    # baseline still matches the approval: safe to publish.
                    self._sync_leases.setdefault(key, 0)
                    lease = self._sync_lease(key)
                    written = ps.write_text_file(
                        path, text, eol, write_bom=had_bom)
                    if written is not None:
                        self._sync_leases[key] = lease + 1
                        self._sync_last_applied[key] = \
                            self._sync_side_digest(written)
                else:
                    # Established binding whose app side changed: use the EOL
                    # learned when this file was last read/applied. The job
                    # carries the CURRENT baseline digest as its expectation
                    # plus the CURRENT lease — CORE-001's mutation-time gate.
                    eol = self._sync_eol_cache.get(key, "\n")
                    expect = baseline
                    lease = self._sync_lease(key)
                    had_bom = self._sync_bom_cache.get(key, False)
                    self._push_jobs_pending[key] = (
                        key, path, text, eol, expect, lease, max_bytes,
                        had_bom)
                    continue
            self._dispatch_push_jobs()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("push sync files failed", exc_info=True)

    def _push_wait_idle(self, timeout_s: float = 5.0):
        """T-1039 test/shutdown helper: pump Qt events until the push worker
        has drained every pending and inflight batch (or timeout).

        Returns ``True`` only when BOTH no in-flight worker job AND no pending
        (GUI-owned) batch remain after completion callbacks have been pumped.
        A timed-out drain returns ``False`` — the caller must not treat a
        stopped thread as a clean drain when work is still queued."""
        import time as _time
        from PyQt6.QtWidgets import QApplication
        if not self._push_inflight and not self._push_jobs_pending:
            return True
        deadline = _time.monotonic() + max(0.0, float(timeout_s))
        while (self._push_inflight or self._push_jobs_pending) \
                and _time.monotonic() < deadline:
            QApplication.processEvents()
            _time.sleep(0.01)
        QApplication.processEvents()
        return not self._push_inflight and not self._push_jobs_pending

    def _wait_for_push_idle(self, timeout_s: float = 5.0):
        """CORE-005: bounded drain of the Sync-Project push pipeline.

        Returns ``True`` when the pipeline reached idle. ``change_profile``
        uses the result to decide whether it may safely replace ``self.data``:
        an old-profile push that cannot drain keeps the old profile active
        rather than letting its completion be evaluated against the new
        profile's aliases."""
        return self._push_wait_idle(timeout_s=timeout_s)

    def _ensure_push_worker(self):
        """T-1039: lazily start the single Sync-Project push worker thread."""
        if self._push_worker is None:
            thread = QThread()
            thread.setObjectName("fastprompter-sync-push")
            worker = _SyncPushWorker()
            # W2-003: a terminal restore sets this so any in-flight job refuses
            # to publish stale pre-restore memory to disk.
            worker._suppress = False
            worker.moveToThread(thread)
            worker.dispatch.connect(worker._run)   # AFTER moveToThread: queued
            worker.done.connect(self._on_push_done)
            thread.start()
            self._push_worker = worker
            self._push_thread = thread
        return self._push_worker

    def _dispatch_push_jobs(self):
        """Hand the newest pending jobs to the worker, coalescing while a
        previous batch is still in flight (the newest desired text always
        wins for a given binding key). The live leases dict travels with the
        batch so the worker can reject a stale binding at mutation time."""
        if self._push_inflight or not self._push_jobs_pending:
            return
        jobs = list(self._push_jobs_pending.values())
        self._push_jobs_pending.clear()
        self._push_inflight = True
        self._ensure_push_worker().dispatch.emit(
            jobs, self._sync_leases, self._sync_commit_gate)

    def _on_push_done(self, results):
        """Worker finished one batch (GUI thread via queued signal).

        CORE-001 completion rules per job status:
        * ``ok``      — a physical write happened. The session baseline moves
          ONLY when the binding still resolves to the same path AND the silo
          still wants exactly the text that was sent.
        * ``equal``   — the disk already held the desired text; record the
          baseline without any write (PERF-003).
        * ``conflict``— a two-sided edit was detected BEFORE mutation. Route
          it through the normal GUI conflict resolution; nothing was
          overwritten.
        * ``stale``/``gone``/``error`` — drop silently (logged); the next
          push round or external-apply pass owns the truth.
        """
        self._push_inflight = False
        try:
            for key, path, text, status, detail in results:
                if status == "ok":
                    written = detail
                    if written is None:
                        continue
                    cat, slot, canon = key
                    # CORE-004: resolve the binding through the IMMUTABLE
                    # captured category, never the currently active flat aliases.
                    cur_path = self._sync_binding_path_for_cat(cat, slot)
                    if cur_path is None or os.path.normcase(
                            os.path.abspath(cur_path)) != canon:
                        continue  # binding moved/re-pointed mid-flight
                    cur_text = self._sync_current_text_for_cat(cat, slot)
                    if cur_text is None:
                        continue
                    if self._sync_side_digest(cur_text) != self._sync_side_digest(text):
                        continue  # edited again since dispatch -- next push owns it
                    self._sync_last_applied[key] = self._sync_side_digest(written)
                elif status == "equal":
                    # CORE-004: detail is (deol, dbom)
                    deol, dbom = (detail if isinstance(detail, (tuple, list))
                                  and len(detail) >= 2
                                  else ((detail or "\n"), False))
                    cat, slot, canon = key
                    # CORE-004: resolve through the immutable captured category.
                    cur_path = self._sync_binding_path_for_cat(cat, slot)
                    if cur_path is None or os.path.normcase(
                            os.path.abspath(cur_path)) != canon:
                        continue
                    cur_text = self._sync_current_text_for_cat(cat, slot)
                    if cur_text is None:
                        continue
                    if self._sync_side_digest(cur_text) != self._sync_side_digest(text):
                        continue
                    self._sync_eol_cache[key] = deol
                    self._sync_bom_cache[key] = bool(dbom)
                    self._sync_last_applied[key] = self._sync_side_digest(text)
                elif status == "conflict":
                    dtxt, deol, dbom = (
                        detail if isinstance(detail, (tuple, list))
                        and len(detail) >= 3 else (detail[0], detail[1], False)
                        if isinstance(detail, (tuple, list)) and len(detail) == 2
                        else ("", "\n", False))
                    self._resolve_push_conflict(key, path, text, dtxt, deol,
                                                dbom)
                else:
                    from fastprompter.core.logging import logger
                    logger.debug("sync push job dropped (%s): %s",
                                 status, os.path.basename(path))
            self._dispatch_push_jobs()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("sync push completion failed", exc_info=True)

    def _resolve_push_conflict(self, key, path, text, disk_text, disk_eol,
                               disk_bom=False):
        """CORE-001: resolve a worker-detected two-sided edit on the GUI
        thread. Nothing was overwritten by the worker; this mirrors the
        fresh-binding conflict flow so both paths share one decision.

        CORE-004: the CURRENT disk BOM travels through every outcome — the
        "file" adoption and the "app wins" requeue both carry it, so a
        BOM-only metadata change can never be silently reverted by a later
        app write."""
        try:
            cat, slot, canon = key
            # CORE-004: resolve through the immutable captured category, never
            # the active flat aliases; a category switch while in flight must
            # not apply another category's conflict result to the visible silo.
            cur_path = self._sync_binding_path_for_cat(cat, slot)
            if cur_path is None or os.path.normcase(
                    os.path.abspath(cur_path)) != canon:
                return  # ownership moved while we were in flight
            presets = (self.data.get("temp_presets_all") or {}).get(cat, [])
            if not (isinstance(slot, int) and 0 <= slot < len(presets)):
                return
            active = getattr(self, "active_temp_slot", -1)
            editing_snippet = getattr(self, "editing_snippet", None)
            is_active = (cat == self.get_current_category() and slot == active
                         and not editing_snippet
                         and not getattr(self, "active_is_archive", False))
            if is_active:
                try:
                    silo_text = self.text_area.toPlainText()
                except Exception:
                    return
            else:
                silo_text = presets[slot] or ""
            if self._sync_side_digest(silo_text) != self._sync_side_digest(text):
                return  # the silo moved on — the next push round owns it
            choice = self._sync_conflict_choice(path, slot, disk_text, silo_text,
                                                cat)
            if choice == "file":
                presets[slot] = disk_text
                if is_active:
                    self._set_plain_text_clean(self.text_area, disk_text)
                self._sync_eol_cache[key] = disk_eol
                self._sync_bom_cache[key] = bool(disk_bom)
                self._sync_last_applied[key] = \
                    self._sync_side_digest(disk_text)
                if is_active:
                    self.refresh_temp_presets()
                return
            if choice != "app":
                return  # skipped for now — leave both sides alone
            # "app": the silo text wins. Re-baseline onto the CURRENT disk
            # content and queue an authorised rewrite of exactly that delta.
            self._sync_eol_cache[key] = disk_eol
            self._sync_bom_cache[key] = bool(disk_bom)
            self._sync_last_applied[key] = self._sync_side_digest(disk_text)
            expect = self._sync_last_applied[key]
            lease = self._sync_lease(key)
            # CORE-004: the requeue uses the SAME authoritative 8-field job
            # schema as every other enqueue path, carrying the currently
            # accepted disk BOM.
            self._push_jobs_pending[key] = (
                key, path, silo_text, disk_eol, expect, lease,
                self._sync_max_bytes(), bool(disk_bom))
            self._dispatch_push_jobs()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("sync push conflict resolution failed",
                         exc_info=True)

    def _push_shutdown(self, timeout_s=_SYNC_SHUTDOWN_TIMEOUT_S):
        """T-1039: drain then retire the Sync-Project push worker thread.

        Runs at application exit after the final save. Pending and in-flight
        app->file writes are pumped to completion (bounded) so the newest
        silo text is not silently lost, then the worker thread is asked to
        quit and joined within the bound.

        CORE-005: a worker stuck in a write cannot be interrupted. On
        timeout the live worker/thread references are RETAINED (never
        dropped) — destroying the Python wrappers while the native QThread
        still runs is an access-violation class failure — and failure is
        reported so the caller refuses clean retirement. A confirmed stop
        retires the wrappers into the process-lifetime leak list first.
        """
        if self._push_thread is None or not self._push_thread.isRunning():
            if self._push_worker is not None:
                _RETIRED_WORKERS.append(self._push_worker)
            if self._push_thread is not None:
                _RETIRED_WORKERS.append(self._push_thread)
            self._push_worker = None
            self._push_thread = None
            return True
        try:
            if getattr(self, "_restore_stale_memory", False):
                # W2-003: a restored DB is authoritative; the pre-restore
                # memory must not be published. Drop any queued stale jobs and
                # tell the worker to refuse in-flight writes, then drain.
                self._push_jobs_pending = {}
                if self._push_worker is not None:
                    self._push_worker._suppress = True
            if not self._push_inflight and self._push_jobs_pending:
                self._dispatch_push_jobs()
            # W2-004: _push_wait_idle returns a TRUTHFUL boolean. A stopped
            # thread is NOT equivalent to a logical drain: the queue's next-
            # dispatch transition is owned by the GUI-thread completion
            # callback, so the shutdown boundary can terminate the worker
            # between an older batch's physical completion and the newest
            # coalesced batch's dispatch — silently leaving the linked file
            # stale while SQLite holds newer text.
            drained = self._push_wait_idle(timeout_s=float(timeout_s))
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("sync push drain during shutdown failed", exc_info=True)
            drained = False
        # W2-004: if work is still queued/pending after the bounded drain, do
        # NOT report clean retirement. Retain the live worker/thread references
        # and return False so the caller never treats stale pending work as
        # committed.
        if not drained or self._push_jobs_pending or self._push_inflight:
            from fastprompter.core.logging import logger
            logger.warning(
                "sync push shutdown did not fully drain (pending/in-flight "
                "work remains); worker/thread retained (leak, never lose data)")
            return False
        thread = self._push_thread
        worker = self._push_worker
        if thread.isRunning():
            thread.quit()
            stopped = wait_thread_seconds(
                thread, timeout_s, "Sync push worker")
        else:
            stopped = True
        if not stopped:
            # CORE-005: keep the exact live objects referenced on the owner.
            # Nulling them here would let teardown destroy a running QThread.
            from fastprompter.core.logging import logger
            logger.warning("sync push worker shutdown TIMED_OUT; live "
                           "worker/thread retained (leak, never hang)")
            return False
        _RETIRED_WORKERS.append(worker)
        _RETIRED_WORKERS.append(thread)
        self._push_worker = None
        self._push_thread = None
        return True

    def _ensure_watcher_arm_worker(self):
        """PERF-004: the persistent watcher-arming worker thread."""
        if getattr(self, "_pw_worker", None) is None:
            thread = QThread()
            thread.setObjectName("fastprompter-watcher-arm")
            worker = _WatcherArmWorker()
            worker.moveToThread(thread)
            worker.enumerate.connect(worker._run)  # AFTER moveToThread
            worker.enumerated.connect(self._on_watcher_arm_enumerated)
            thread.start()
            self._pw_worker = worker
            self._pw_thread = thread
        return self._pw_worker

    def _request_watcher_arm(self, gen, root, exclude):
        """PERF-002: dispatch a recursive arm enumeration with one-inflight /
        one-latest-pending semantics. If an enumeration is already running, the
        newest (gen, root, exclude) overwrites a single pending request instead
        of queuing another full-tree walk. The next completion dispatches only
        the newest pending generation."""
        if self._pw_inflight:
            self._pw_pending = (gen, root, exclude)
            return
        worker = self._ensure_watcher_arm_worker()
        if worker is not None:
            worker._cancel = False
        self._pw_inflight = True
        worker.enumerate.emit(gen, root, exclude)

    def _on_watcher_arm_enumerated(self, gen, root, dirs):
        """The recursive watch list is ready. Apply it ONLY when still
        current (no newer arm happened meanwhile), then trigger one
        coalesced reconciliation so a change that occurred during the walk
        cannot be lost (the root itself was watched synchronously)."""
        # PERF-002: this completion frees the inflight slot; dispatch the single
        # newest pending re-arm (if any) before any further arming.
        self._pw_inflight = False
        if gen != getattr(self, "_pw_gen", 0):
            self._dispatch_pending_watcher_arm()
            return  # stale: a newer arm owns the watcher
        if not hasattr(self, "_project_sync_watcher"):
            self._dispatch_pending_watcher_arm()
            return
        try:
            if dirs:
                self._project_sync_watcher.addPaths(dirs)
            self._on_sync_dir_changed(root)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("watcher arm completion failed", exc_info=True)
        self._dispatch_pending_watcher_arm()

    def _dispatch_pending_watcher_arm(self):
        """PERF-002: fire the single newest pending re-arm, if one was coalesced
        while the previous enumeration was still walking the tree."""
        pending = self._pw_pending
        self._pw_pending = None
        if pending is None:
            return
        gen, root, exclude = pending
        worker = self._ensure_watcher_arm_worker()
        if worker is not None:
            worker._cancel = False
        self._pw_inflight = True
        worker.enumerate.emit(gen, root, exclude)

    def _watcher_arm_shutdown(self, timeout_s=2.0):
        """Bounded stop of the watcher-arm enumeration thread at exit.

        PERF-002: signal cooperative cancellation first so a stale in-flight
        traversal stops at its next directory boundary instead of forcing the
        shutdown to hit its timeout."""
        thread = getattr(self, "_pw_thread", None)
        if thread is None or not thread.isRunning():
            self._pw_thread = None
            self._pw_worker = None
            self._pw_pending = None
            self._pw_inflight = False
            return True
        worker = getattr(self, "_pw_worker", None)
        if worker is not None:
            worker._cancel = True
        self._pw_pending = None
        thread.quit()
        stopped = wait_thread_seconds(thread, timeout_s,
                                      "watcher arm worker")
        if stopped:
            _RETIRED_WORKERS.append(worker)
            _RETIRED_WORKERS.append(thread)
            self._pw_thread = None
            self._pw_worker = None
            self._pw_inflight = False
        else:
            from fastprompter.core.logging import logger
            logger.warning("watcher arm worker shutdown TIMED_OUT; live "
                           "worker/thread retained")
        return stopped

    def _start_project_watcher(self):
        """Re-arm the QFileSystemWatcher for the ACTIVE category: the sync
        folder (recursively, per settings) plus every per-silo linked file.

        PERF-004: the root and the per-silo links are armed synchronously
        (cheap, and the root must be watched immediately); the recursive
        directory expansion — an O(project tree) walk with exclude matching
        that used to hitch project/profile switches on large trees — runs on
        the arm worker under a generation token. A stale completion (a newer
        re-arm happened meanwhile) never replaces a newer path set.
        """
        if not hasattr(self, "_project_sync_watcher"):
            return
        try:
            watcher = self._project_sync_watcher
            for p in watcher.directories():
                watcher.removePath(p)
            for p in watcher.files():
                watcher.removePath(p)
            self._pw_gen = getattr(self, "_pw_gen", 0) + 1
            root = self._sync_root()
            live = self.data.get("sync_live_watch", "True") == "True"
            if root and live and os.path.isdir(root):
                try:
                    watcher.addPath(root)
                except Exception:
                    pass
                if self._sync_recursive():
                    gen = self._pw_gen
                    # PERF-002: one-inflight / one-latest-pending arming so a
                    # burst of category/profile switches cannot queue full-tree
                    # walks faster than they complete.
                    self._request_watcher_arm(
                        gen, root, list(self._sync_exclude()))
            for slot in range(len(self.data.get("temp_presets") or [])):
                p = self._link_file_for_slot(slot)
                if p:
                    try:
                        watcher.addPath(p)
                    except Exception:
                        pass
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("start project watcher failed", exc_info=True)

    def _on_sync_file_changed(self, path):
        """Any file in the watched set changed: debounce ONE apply pass.

        PERF-003: the changed path is retained (not discarded) so the apply
        pass can read ONLY the affected bound files instead of rescanning the
        whole project."""
        if not self._sync_pending_apply:
            self._sync_pending_apply = True
            self._sync_apply_timer.start()
        if isinstance(path, str) and path:
            self._sync_changed_files.add(os.path.normcase(path))

    def _on_sync_dir_changed(self, path):
        """A directory changed (new/removed subfolder): coalesce watcher
        rebuild + discovery into the apply pass (PERF-003)."""
        self._sync_dir_changed = True
        self._on_sync_file_changed(path)

    def _apply_external_change(self, slot, path, text, eol, presets, active,
                               editing_snippet, applied):
        """Apply ONE external file change to its silo, resolving conflicts.

        Shared by the Sync-Project map and the per-silo link branches of
        ``_apply_external_sync``. Rules:
        * content equal to what we last wrote/applied is OUR OWN write — no-op;
        * a silo with newer app-side text is skipped (the app side wins
          while it is being typed; the next external change retries);
        * NO session baseline + differing file/silo text is a two-sided
          conflict: the user picks a winner instead of one side silently
          clobbering the other (``_sync_resolve_conflict``).
        """
        key = self._sync_baseline_key(slot, path)
        if self._sync_baseline_value(slot, path) == self._sync_side_digest(text):
            return
        # T-1039: remember this file's EOL so a later app->file push never
        # needs a full read just to rediscover it.
        self._sync_eol_cache[key] = eol
        if not self._silo_clean(slot, path):
            return  # the app side is newer (typing) — retry later
        if self._sync_baseline_value(slot, path) is None:
            # No baseline this session: a difference between the file and the
            # silo is a two-sided conflict (e.g. both edited while the app
            # was closed), not a normal external edit.
            silo_text = presets[slot] if 0 <= slot < len(presets) else ""
            if (slot == active and not editing_snippet
                    and not getattr(self, "active_is_archive", False)):
                try:
                    if self.text_area.toPlainText() != silo_text:
                        return  # the user is typing — app side wins for now
                except Exception:
                    # T-1030: editor unavailable -- app side is unknown, so
                    # skip this external apply instead of guessing it is
                    # clean; the next external change retries.
                    return
            if silo_text != text:
                choice = self._sync_conflict_choice(
                    path, slot, text, silo_text)
                if choice == "app":
                    # the silo text wins: write it back to the file
                    try:
                        from fastprompter.core import project_sync as ps
                        written = ps.write_text_file(
                            path, silo_text, eol,
                            write_bom=self._sync_bom_cache.get(key, False))
                    except Exception as exc:
                        # T-1030: the user picked a winner -- a silent write
                        # failure would leave the file on the loser text
                        # while the baseline claims it resolved.
                        from fastprompter.core.logging import logger
                        logger.warning(
                            "sync: failed to write silo text back to %s: %s",
                            path, exc)
                        return
                    if written is not None:
                        self._sync_last_applied[key] = self._sync_side_digest(written)
                    return
                if choice != "file":
                    return  # skipped for now — leave both sides alone
                # "file": fall through and pull the file text into the silo
        self._sync_last_applied[key] = self._sync_side_digest(text)
        applied[slot] = text

    def _apply_external_sync(self):
        """File -> app: pull external edits from disk into the silos.

        Debounced (350ms). Rules:
        * content equal to what we last wrote/applied is OUR OWN write — no-op;
        * a silo with newer app-side text is skipped (the app side wins
          while it is being typed; the next external change retries);
        * new files matching the filters claim the first free slot;
        * files deleted on disk drop their mapping entry (silo text stays);
        * no baseline + differing file/silo text is a two-sided conflict
          resolved by the user (``_sync_resolve_conflict``).
        """
        self._sync_pending_apply = False
        changed = self._sync_changed_files
        self._sync_changed_files = set()
        dir_changed = self._sync_dir_changed
        self._sync_dir_changed = False
        try:
            # Per-silo links work WITHOUT a Sync-Project folder, so the
            # guard must not bail just because there is no folder config.
            if not self._sync_config() and not (self.data.get("silo_links") or {}):
                return
            from fastprompter.core import project_sync as ps
            presets = self._ensure_temp_presets()
            active = getattr(self, "active_temp_slot", -1)
            editing_snippet = getattr(self, "editing_snippet", None)
            applied: dict[int, str] = {}
            mapping_changed = False

            # PERF-003: a directory-structure change forces a full discovery
            # pass; a plain file-change batch does NOT. When only files
            # changed, restrict the project-map read to exactly the affected
            # bound files instead of rescanning the whole project.
            file_only = bool(changed) and not dir_changed

            # --- project map: external edits to bound files ---------------
            root = self._sync_root()
            if root and os.path.isdir(root):
                mapping = self.data.setdefault("project_sync_map", {})
                for slot_key in list(mapping.keys()):
                    rel = mapping[slot_key]
                    path = ps.resolve_relative_path(root, rel)
                    if path is None:
                        # A stale/corrupt mapping must never escape the
                        # selected root. Keep the silo text, drop only the
                        # unsafe binding.
                        mapping.pop(slot_key, None)
                        mapping_changed = True
                        continue
                    try:
                        slot = int(slot_key)
                    except (TypeError, ValueError):
                        continue
                    if file_only and os.path.normcase(path) not in changed:
                        continue
                    if not os.path.exists(path):
                        mapping.pop(slot_key, None)
                        mapping_changed = True
                        self._sync_invalidate_binding(slot, path)
                        continue
                    read = ps.read_text_file(path, self._sync_max_bytes())
                    if read is None:
                        continue
                    text, _eol, _had_bom = read
                    self._sync_bom_cache[
                        self._sync_baseline_key(slot, path)] = _had_bom
                    self._apply_external_change(
                        slot, path, text, _eol, presets, active,
                        editing_snippet, applied)

                # --- new files -> new silos --------------------------------
                # PERF-001: discovery is O(project tree). Run it only for a
                # directory-structure event (or a defensive empty batch);
                # a plain file-change batch already knows the affected path.
                if dir_changed or not changed:
                    files = ps.scan_folder(root, self._sync_include(),
                                           self._sync_exclude(),
                                           recursive=self._sync_recursive(),
                                           max_bytes=self._sync_max_bytes())
                    mapped = set(mapping.values())
                    new_files = [f for f in files if f not in mapped]
                    if new_files:
                        for rel, slot in zip(
                                new_files,
                                ps.free_slots(mapping, len(presets), len(new_files))):
                            path = ps.resolve_relative_path(root, rel)
                            if path is None:
                                continue
                            read = ps.read_text_file(path, self._sync_max_bytes())
                            if read is None:
                                continue
                            text, eol, had_bom = read
                            while len(presets) <= slot:
                                presets.append("")
                            presets[slot] = text
                            mapping[str(slot)] = rel
                            key = self._sync_baseline_key(slot, path)
                            self._sync_eol_cache[key] = eol
                            self._sync_bom_cache[key] = had_bom
                            self._sync_last_applied[key] = \
                                self._sync_side_digest(text)
                            applied[slot] = text

            # --- per-silo links --------------------------------------------
            links = self.data.get("silo_links") or {}
            for slot_key, path in list(links.items()):
                if not isinstance(path, str) or not path:
                    continue
                if file_only and os.path.normcase(path) not in changed:
                    continue
                if not os.path.exists(path):
                    continue
                read = ps.read_text_file(path, self._sync_max_bytes())
                if read is None:
                    continue
                text, _eol, _had_bom = read
                try:
                    slot = int(slot_key)
                except (TypeError, ValueError):
                    continue
                self._sync_bom_cache[
                    self._sync_baseline_key(slot, path)] = _had_bom
                self._apply_external_change(
                    slot, path, text, _eol, presets, active,
                    editing_snippet, applied)

            # --- publish into the silos -------------------------------------
            if not applied:
                if mapping_changed:
                    self.mark_dirty()
                    self.refresh_temp_presets()
                return
            for slot, text in applied.items():
                if 0 <= slot < len(presets):
                    presets[slot] = text
                    if (slot == active and not editing_snippet
                            and not getattr(self, "active_is_archive", False)):
                        self._set_plain_text_clean(self.text_area, text)
            self.mark_dirty()
            self.refresh_temp_presets()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("apply external sync failed", exc_info=True)

    # ---- Sync-Project user actions (project tab context menu) -------------

    def _convert_project_to_sync(self):
        """Bind this project tab to a folder: each text file becomes a silo."""
        lang = getattr(self, "_current_lang", "EN")
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self, tr("Convert to Sync-Project", lang),
                tr("Make this project a Sync-Project?\n\n"
                   "Each text file in a folder you choose becomes a silo, "
                   "edited on both sides in real time (folder → silo and "
                   "silo → folder).\n\n"
                   "• the first silos bind to the folder's files (name order);\n"
                   "• extra files become new silos (up to 100);\n"
                   "• silos without a matching file keep their text.\n\n"
                   "The folder can be changed later, and the project can be "
                   "unlinked any time — silos keep their text.", lang),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._change_project_sync_folder()

    def _change_project_sync_folder(self):
        """Pick the sync folder and (re)bind every file to a silo."""
        lang = getattr(self, "_current_lang", "EN")
        cfg = self._sync_config() or {}
        old_root = cfg.get("root") or self.data.get("sync_path", "") or None
        start = cfg.get("root") or self.data.get("sync_path", "") \
            or os.path.expanduser("~")
        self.ignore_focus_loss = True
        try:
            d = QFileDialog.getExistingDirectory(
                self, tr("Choose sync folder", lang), start)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if not d:
            return
        from fastprompter.core import project_sync as ps
        root = os.path.abspath(d)
        files = ps.scan_folder(root, self._sync_include(), self._sync_exclude(),
                               recursive=self._sync_recursive(),
                               max_bytes=self._sync_max_bytes())
        if not files:
            QMessageBox.information(
                self, tr("Sync-Project", lang),
                tr("No text files found in that folder with the current "
                   "include/exclude settings.", lang))
            return
        cat = self.get_current_category() or ""
        cfg = {
            "root": root,
            "recursive": self._sync_recursive(),
            "include": self._sync_include(),
            "exclude": self._sync_exclude(),
            "enabled": True,
        }
        self.data["project_sync"] = cfg
        self.data.setdefault("project_sync_all", {})[cat] = cfg
        presets = self._ensure_temp_presets()
        mapping = self.data.setdefault("project_sync_map", {})
        # CORE-001: repointing the folder invalidates every OLD binding's
        # lease so a queued/running job cannot write into the previous root.
        # Goes through the canonical invalidation primitive (lease bump under
        # the commit gate + baseline/EOL/BOM cleanup), which reaches jobs
        # ALREADY dispatched to the worker, not just queued ones.
        if old_root:
            for old_slot, old_rel in list(mapping.items()):
                old_path = ps.resolve_relative_path(old_root, old_rel)
                if old_path is None:
                    continue
                try:
                    _sk = int(old_slot)
                except (TypeError, ValueError):
                    _sk = old_slot
                self._sync_invalidate_binding(_sk, old_path)
        for old_key in list(self._push_jobs_pending):
            self._push_jobs_pending.pop(old_key, None)
            # bump under the gate too: an in-flight job for a key whose
            # pending entry was dropped must still be rejected
            with self._sync_commit_gate:
                self._sync_leases[old_key] = self._sync_leases.get(old_key, 0) + 1
        self.data.setdefault("project_sync_map_all", {})[cat] = mapping
        mapping.clear()
        for slot, rel in enumerate(files):
            if slot >= self.MAX_SILOS_PER_CATEGORY:
                break
            path = ps.resolve_relative_path(root, rel)
            if path is None:
                continue
            read = ps.read_text_file(path, self._sync_max_bytes())
            if read is None:
                continue
            text, eol, had_bom = read
            while len(presets) <= slot:
                presets.append("")
            presets[slot] = text
            mapping[str(slot)] = rel
            key = self._sync_baseline_key(slot, path)
            self._sync_eol_cache[key] = eol
            self._sync_bom_cache[key] = had_bom
            self._sync_last_applied[key] = self._sync_side_digest(text)
        self.mark_dirty()
        self.save_data_to_db(force=True)
        self._start_project_watcher()
        self._update_project_tooltip()
        self.refresh_temp_presets()
        # the ACTIVE silo's editor may hold text the folder just replaced
        active = getattr(self, "active_temp_slot", -1)
        if (0 <= active < len(presets)
                and not getattr(self, "editing_snippet", None)
                and not getattr(self, "active_is_archive", False)):
            self._set_plain_text_clean(self.text_area, presets[active] or "")
        n = len(mapping)
        QMessageBox.information(
            self, tr("Sync-Project", lang),
            tr("This project is now a Sync-Project.\n"
               "{} file(s) bound to silos — changes now sync both ways in "
               "real time.", lang).format(n))

    def _rescan_project_sync(self):
        """Re-read the folder: bind new files, drop deleted ones."""
        if not self._sync_config():
            return
        try:
            from fastprompter.core import project_sync as ps
            root = self._sync_root()
            if not root or not os.path.isdir(root):
                return
            files = ps.scan_folder(root, self._sync_include(),
                                   self._sync_exclude(),
                                   recursive=self._sync_recursive(),
                                   max_bytes=self._sync_max_bytes())
            mapping = self.data.setdefault("project_sync_map", {})
            for key in list(mapping.keys()):
                rel = mapping[key]
                if rel not in files:
                    path = ps.resolve_relative_path(root, rel)
                    mapping.pop(key, None)
                    if path is None:
                        continue
                    try:
                        _sk = int(key)
                    except (TypeError, ValueError):
                        _sk = key
                    self._sync_invalidate_binding(_sk, path)
            mapped = set(mapping.values())
            new_files = [f for f in files if f not in mapped]
            if new_files:
                presets = self._ensure_temp_presets()
                for rel, slot in zip(
                        new_files,
                        ps.free_slots(mapping, len(presets), len(new_files))):
                    path = ps.resolve_relative_path(root, rel)
                    if path is None:
                        continue
                    read = ps.read_text_file(path, self._sync_max_bytes())
                    if read is None:
                        continue
                    text, eol, had_bom = read
                    while len(presets) <= slot:
                        presets.append("")
                    presets[slot] = text
                    mapping[str(slot)] = rel
                    key = self._sync_baseline_key(slot, path)
                    self._sync_eol_cache[key] = eol
                    self._sync_bom_cache[key] = had_bom
                    self._sync_last_applied[key] = self._sync_side_digest(text)
            self.mark_dirty()
            self.refresh_temp_presets()
            self._start_project_watcher()
            self._update_project_tooltip()
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("rescan project sync failed", exc_info=True)

    def _unlink_project_sync(self):
        """Stop syncing this project. Silos and their text stay as they are."""
        lang = getattr(self, "_current_lang", "EN")
        reply = QMessageBox.question(
            self, tr("Unlink Sync-Project", lang),
            tr("Stop syncing this project with its folder?\n\n"
               "The silos and their text stay exactly as they are; only the "
               "live two-way sync is turned off.", lang),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        cat = self.get_current_category() or ""
        cfg = self._sync_config()
        if cfg:
            root = os.path.abspath(cfg["root"])
            mapping = self.data.get("project_sync_map") or {}
            for rel in mapping.values():
                from fastprompter.core import project_sync as ps
                p2 = ps.resolve_relative_path(root, rel)
                if p2 is None:
                    continue
                for _k in [k for k in self._sync_last_applied
                           if isinstance(k, tuple) and k[2] == os.path.normcase(p2)]:
                    # CORE-001: canonical invalidation bumps the lease under the
                    # commit gate and clears baseline/EOL/BOM — this reaches
                    # jobs ALREADY dispatched to the worker, not just queued ones.
                    self._sync_invalidate_binding(_k[1], p2)
                for _pk in [k for k in self._push_jobs_pending
                            if isinstance(k, tuple) and k[2] == os.path.normcase(p2)]:
                    self._push_jobs_pending.pop(_pk, None)
        self.data["project_sync"] = {}
        self.data.setdefault("project_sync_all", {})[cat] = {}
        mapping = self.data.get("project_sync_map")
        if isinstance(mapping, dict):
            mapping.clear()
        self.data.setdefault("project_sync_map_all", {})[cat] = {}
        self.mark_dirty()
        self._start_project_watcher()
        self._update_project_tooltip()
        self.refresh_temp_presets()

    def _update_project_tooltip(self):
        """The project combo tooltip announces an active Sync-Project."""
        combo = getattr(self, "cat_combo", None)
        if combo is None or sip.isdeleted(combo):
            return
        lang = getattr(self, "_current_lang", "EN")
        base = tr("Projects — mouse wheel switches tabs", lang)
        cfg = self._sync_config()
        if cfg:
            n = len(self.data.get("project_sync_map") or {})
            combo.setToolTip(
                tr("Sync-Project: {}\n{} file(s) bound — edits sync both "
                   "ways in real time.", lang).format(cfg.get("root", ""), n)
                + "\n" + base)
        else:
            combo.setToolTip(base)

    # ---- per-silo file link (silo context menu) ----------------------------

    def _link_silo_to_file(self, idx):
        """Bind ONE silo to ONE file, both sides, live."""
        lang = getattr(self, "_current_lang", "EN")
        self.ignore_focus_loss = True
        try:
            path, _f = QFileDialog.getOpenFileName(
                self, tr("Sync/Link this silo with…", lang), "",
                tr("Text files (*.txt *.md *.markdown *.py *.js *.ts *.json "
                   "*.yaml *.yml *.toml *.ini *.cfg *.csv *.html *.css *.xml "
                   "*.log *.sh *.bat *.ps1 *.sql);;All files (*.*)", lang))
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if not path:
            return
        from fastprompter.core import project_sync as ps
        path = os.path.abspath(path)
        read = ps.read_text_file(path, self._sync_max_bytes())
        if read is None:
            QMessageBox.information(
                self, tr("Link silo", lang),
                tr("That file cannot be read as text (too large or binary).",
                   lang))
            return
        text, eol, had_bom = read
        presets = self.data.get("temp_presets") or []
        if not (0 <= idx < len(presets)):
            return
        cat = self.get_current_category() or ""
        links = self.data.setdefault("silo_links", {})
        self.data.setdefault("silo_links_all", {})[cat] = links
        # CORE-001: invalidate existing binding for this slot before
        # overwriting — an already-dispatched worker job for the old path
        # must be rejected by the lease gate.
        old_path = links.get(str(idx))
        if old_path:
            self._sync_invalidate_binding(idx, old_path)
        links[str(idx)] = path
        # the file is the source of truth at link time
        presets[idx] = text
        key = self._sync_baseline_key(idx, path)
        self._sync_eol_cache[key] = eol
        self._sync_bom_cache[key] = bool(had_bom)
        self._sync_last_applied[key] = self._sync_side_digest(text)
        self.mark_dirty()
        self.refresh_temp_presets()
        if idx == getattr(self, "active_temp_slot", -1):
            self._set_plain_text_clean(self.text_area, text)
        self._start_project_watcher()
        self._typo_check_tick()

    def _unlink_silo_file(self, idx):
        """Stop syncing ONE silo with its file. The silo text stays."""
        links = self.data.get("silo_links")
        if not isinstance(links, dict):
            return
        path = links.pop(str(idx), None)
        if path:
            self._sync_invalidate_binding(idx, path)
        self.mark_dirty()
        self.refresh_temp_presets()
        self._start_project_watcher()

    # -- T-591: one-way mirror of silo text onto disk -------------------------
    def _sync_name_for(self, idx, presets):
        from fastprompter.ui.file_container import silo_slug
        raw = presets[idx] if 0 <= idx < len(presets) else ""
        return f"{idx + 1:02d}_{silo_slug(raw) or 'blank'}"

    def _sync_rel_paths(self):
        """{slot: relative path} for the active category. Children nest under
        their parent's folder; a broken parent chain falls back to flat."""
        presets = self.data.get("temp_presets", [])
        # silo_children keys are ints in memory but strings once the map has
        # been through a JSON round-trip, so coerce both ends.
        parent_of = {}
        for parent, kids in (self._children_map() or {}).items():
            try:
                p = int(parent)
            except (TypeError, ValueError):
                continue
            for k in kids or ():
                try:
                    parent_of[int(k)] = p
                except (TypeError, ValueError):
                    continue
        # PERF-002: compute each slot's folder name exactly ONCE per snapshot
        # (silo_slug now only inspects the first line, but climbing an N-deep
        # ancestor chain must not recompute a slot's name up to O(N) times).
        names = [self._sync_name_for(i, presets) for i in range(len(presets))]
        out = {}
        for i in range(len(presets)):
            parts, cur, seen = [names[i]], i, {i}
            while cur in parent_of:
                cur = parent_of[cur]
                if cur in seen or not (0 <= cur < len(presets)):
                    break          # cycle or dangling parent: stop climbing
                seen.add(cur)
                parts.append(names[cur])
            out[i] = os.path.join(*reversed(parts))
        return out

    def _sync_init(self):
        if getattr(self, "_sync_gen", None) is not None:
            return
        self._sync_gen = 0
        self._sync_owner = object()
        self._sync_inflight_gen = 0
        self._sync_inflight_profile = None
        self._sync_inflight_root = None
        self._sync_completed_gen = 0
        self._sync_pending = None
        self._sync_pending_hold = {}
        self._sync_shutting_down = False
        # W2-003: a process-wide "restored DB committed, RAM is stale" teardown
        # state. restore_backup sets this the instant a DB restore commits (or
        # a terminal connection-reopen failure occurs) so every external writer
        # — the sync mirror and the Sync-Project push pipeline — can suppress
        # publishing the stale pre-restore memory instead of overwriting the
        # authoritative restored state.
        self._restore_stale_memory = False
        self._sync_worker = None
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(_SYNC_DEBOUNCE_MS)
        self._sync_timer.timeout.connect(self._sync_dispatch_pending)

    @property
    def _sync_busy(self):
        return self._sync_inflight_gen > 0

    @_sync_busy.setter
    def _sync_busy(self, value):
        # Allow backward compatibility for tests that mock _sync_busy
        if value:
            if self._sync_inflight_gen == 0:
                self._sync_inflight_gen = self._sync_gen or 1
        else:
            self._sync_inflight_gen = 0

    def _capture_sync_snapshot(self, force=False):
        """Build the immutable write list for one sync run.

        Fast (no disk writes) and the ONLY place containment/identity is
        decided: safe filesystem components for project names, canonical
        sync-root check, skip-unchanged against the written cache. The result
        is handed to the worker untouched.
        """
        mode = self.data.get("sync_mode", "Off")
        root = str(self.data.get("sync_path", "") or "").strip()
        if mode not in ("Silo", "Hierarchy") or not root:
            return None
        from fastprompter.utils.path_safety import (
            alloc_fs_names,
            capture_resolved_root,
            is_within,
        )
        presets = self.data.get("temp_presets", [])
        if mode == "Silo":
            slots = [self.active_temp_slot]
        else:
            slots = [i for i in range(len(presets)) if presets[i].strip()]
        rels = self._sync_rel_paths()
        cache = getattr(self, "_sync_written", None)
        if cache is None:
            cache = self._sync_written = {}
        cat = self.get_current_category() or ""
        cat_comps = alloc_fs_names(self.data.get("cats_order", []) or [])
        cat_comp = cat_comps.get(cat, cat)
        files = {}
        current_dests = set()
        for i in slots:
            if not (0 <= i < len(presets)):
                continue
            text = presets[i]
            if mode == "Hierarchy" and not text.strip():
                continue
            rel = rels.get(i, self._sync_name_for(i, presets))
            dest = os.path.join(root, cat_comp, rel + ".md")
            # canonical containment, never a prefix check
            if not is_within(root, dest):
                from fastprompter.core.logging import logger
                logger.warning("sync_to_disk rejected %r: outside the sync root",
                               dest)
                continue
            current_dests.add(dest)
            if not force and cache.get(dest) == text:
                continue           # unchanged since the last mirror
            files[dest] = text
        if not files:
            if not current_dests or set(cache.keys()) == current_dests:
                return None
            # need metadata-only snapshot to prune stale cache entries
            return {"files": {}, "current_dests": current_dests, "root": root,
                    "root_identity": capture_resolved_root(root),
                    "profile": getattr(getattr(self, "state", None),
                                        "profile_id", None)}
        return {"files": files, "current_dests": current_dests, "root": root,
                "root_identity": capture_resolved_root(root),
                "profile": getattr(getattr(self, "state", None),
                                    "profile_id", None)}

    def _sync_on_profile_change(self):
        """The active profile switched: any in-flight snapshot belongs to the
        OLD profile and must not be interpreted as the new one's generation;
        the new profile must not inherit the old one's written-cache.

        The FINAL old-profile snapshot (just captured by the window's
        save_data_to_db(force=True) before the switch) is NOT dropped here:
        it is dispatched immediately, bypassing the debounce. The snapshot
        carries its own profile/root, so the worker writes ONLY the old
        profile's paths, and its generation predates the new profile's, so
        its result is never merged into the new profile's written-cache.
        """
        self._sync_init()
        self._sync_gen += 1
        pending = self._sync_pending
        try:
            if self._sync_timer is not None:
                self._sync_timer.stop()
        except Exception:
            pass
        self._sync_pending = None
        # Do NOT touch _sync_inflight_gen: a physical worker might still be writing.
        self._sync_written = {}
        if pending is not None:
            if self._sync_busy:
                # The worker is mid-write for the OLD profile. The final
                # old-profile snapshot is held keyed by ITS profile instead
                # of being dropped (P0-2): _sync_on_done drains the hold for
                # the profile that just completed FIRST, then plain pending,
                # so the old profile's last typed text still reaches its
                # mirror after the switch.
                self._sync_pending_hold[pending.get("profile")] = pending
            else:
                self._sync_dispatch_snapshot(pending)

    def sync_to_disk(self, force=False):
        """Mirror the current silo (or the whole hierarchy) to sync_path.

        One-way, app -> disk. Never reads back, never deletes: a stale file
        from a renamed silo is left alone rather than risking user data.

        The write list is captured synchronously (containment + identity
        decided here), then written on the sync worker thread, coalesced: a
        newer snapshot supersedes an older pending one, and a stale result is
        never merged into the current cache. During shutdown no new work is
        queued — the close path must not leave a worker touching a dying
        window."""
        if getattr(self, "_sync_shutting_down", False):
            return
        snap = self._capture_sync_snapshot(force)
        if snap is None:
            return
        self._sync_init()
        self._sync_gen += 1
        snap["gen"] = self._sync_gen
        snap["owner"] = self._sync_owner
        _sync_register_snapshot(snap)
        self._sync_pending = snap
        self._sync_timer.start()

    def _sync_dispatch_snapshot(self, snap):
        """Dispatch one specific snapshot to the worker (one at a time).

        Unlike `_sync_dispatch_pending`, the snapshot is not taken from
        `_sync_pending` — the caller (profile switch drain, shutdown hold)
        may already hold it elsewhere. Returns False when the worker is
        busy and the caller must keep the snapshot for later.
        """
        if snap is None:
            return False
        self._sync_init()
        if self._sync_busy:
            return False
        if self._sync_inflight_gen != 0:
            raise RuntimeError("attempted dispatch while physical job inflight")
        self._sync_inflight_gen = snap["gen"]
        self._sync_inflight_profile = snap.get("profile")
        self._sync_inflight_root = snap.get("root")
        self._sync_ensure_worker().dispatch.emit(snap, snap["gen"])
        return True

    def _sync_dispatch_pending(self):
        """Push the newest pending snapshot to the worker (one at a time)."""
        self._sync_init()
        if self._sync_pending is None or self._sync_busy:
            return
        snap = self._sync_pending
        self._sync_pending = None
        self._sync_dispatch_snapshot(snap)

    def _sync_ensure_worker(self):
        """The process-wide sync worker, created once per process.

        A per-WINDOW worker thread died with its window, and destroying a
        QThread while its event loop is winding down is an abort class of its
        own. One shared thread, started lazily and left running for the
        process lifetime, never has to survive a window teardown: each window
        connects its own result slot, and the generation token in every
        snapshot already makes cross-window results stale-safe.
        """
        global _SYNC_SHARED_WORKER, _SYNC_SHARED_THREAD
        if _SYNC_SHARED_WORKER is None:
            thread = QThread()
            thread.setObjectName("fastprompter-sync")
            worker = _SyncWorker()
            worker.moveToThread(thread)
            worker.dispatch.connect(worker._run)   # AFTER moveToThread: queued
            thread.start()
            _SYNC_SHARED_WORKER = worker
            _SYNC_SHARED_THREAD = thread
        # a window reconnects when the shared worker was torn down and
        # recreated (global shutdown), otherwise its done slot would never fire
        if (getattr(self, "_sync_done_worker", None)
                is not _SYNC_SHARED_WORKER):
            _SYNC_SHARED_WORKER.done.connect(self._sync_on_done)
            self._sync_done_worker = _SYNC_SHARED_WORKER
        return _SYNC_SHARED_WORKER

    def _sync_on_done(self, gen, snapshot, written, errors):
        """The worker's result, applied on the GUI thread.

        A result is merged into the written cache ONLY when its generation is
        still current; a newer snapshot superseded this one, or the root
        changed, or the app is shutting down -> the stale result is dropped.
        (Other windows' snapshots carry different generations and are dropped
        here the same way.)

        Whether or not the result is stale, the NEWEST pending snapshot must
        be dispatched once the worker frees up: a stale completion must never
        strand newer work. The drain lives OUTSIDE the stale guard so no early
        return can bypass it.
        """
        if not is_gui_thread():
            from fastprompter.core.logging import logger as _log
            _log.critical("Sync completion rejected outside GUI thread")
            return
        if snapshot.get("owner") is not self._sync_owner:
            return
        current_profile = getattr(getattr(self, "state", None), "profile_id", None)
        current_root = str(self.data.get("sync_path", "") or "").strip()
        is_current = (
            gen == self._sync_gen
            and snapshot.get("profile") == current_profile
            and os.path.normcase(os.path.abspath(snapshot.get("root") or ""))
            == os.path.normcase(os.path.abspath(current_root))
        )
        if is_current:
            cache = getattr(self, "_sync_written", None)
            if cache is None:
                cache = self._sync_written = {}
            for dest in written:
                cache[dest] = snapshot["files"].get(dest, "")
            # PERF-009/PERF-001: prune the written-cache to the COMPLETE
            # current destination set, not the delta. Historical
            # destinations (renamed silos, changed hierarchy) no longer
            # addressable must not keep full text in RAM; the one-way disk
            # mirrors themselves are intentionally never deleted.
            current_dests = snapshot.get("current_dests")
            if current_dests is None:
                # backward compat: older snapshots without current_dests
                current_dests = set(snapshot.get("files", ()))
            else:
                current_dests = set(current_dests)
                # ensure successfully written dests are considered current
                # even if the snapshot was a delta
                current_dests.update(snapshot.get("files", {}).keys())
            for stale in [k for k in cache if k not in current_dests]:
                del cache[stale]
            for dest, err in errors:
                from fastprompter.core.logging import logger
                logger.warning("sync_to_disk failed for %s: %s", dest, err)
        owns_inflight = (
            gen == self._sync_inflight_gen
            and snapshot.get("profile") == self._sync_inflight_profile
            and snapshot.get("root") == self._sync_inflight_root
        )
        if owns_inflight:
            self._sync_completed_gen = gen
            self._sync_inflight_gen = 0
            self._sync_inflight_profile = None
            self._sync_inflight_root = None
        if owns_inflight:
            # Drain the hold for the profile that JUST completed first: its
            # final snapshot predates any newer pending one and must reach
            # the disk even when a profile switch caught the worker busy
            # (P0-2). Only then fall back to the plain newest pending — and
            # finally to the newest REMAINING held snapshot, so a profile we
            # switched away from (A→B→A) still mirrors its last text instead
            # of sitting in the hold until shutdown.
            self._sync_init()
            held = self._sync_pending_hold.pop(snapshot.get("profile"), None)
            if held is not None:
                self._sync_dispatch_snapshot(held)
            elif self._sync_pending is not None:
                self._sync_dispatch_pending()
            elif self._sync_pending_hold:
                newest = max(self._sync_pending_hold.items(),
                             key=lambda kv: kv[1]["gen"])
                self._sync_pending_hold.pop(newest[0])
                self._sync_dispatch_snapshot(newest[1])

    def _sync_shutdown(self, timeout_s=_SYNC_SHUTDOWN_TIMEOUT_S):
        """Flush the FINAL mirror at window close, then retire.

        The window's save path calls sync_to_disk() one last time BEFORE this,
        so the final committed DB state has a pending mirror. A normal close
        must NOT discard it: stop accepting new jobs, capture the final
        committed snapshot, coalesce it with whatever is pending, flush the
        newest through the worker with a bounded wait, then retire.

        The flush is bounded: a slow or hung filesystem yields a logged
        degraded mirror AFTER the deadline — the SQLite database remains
        authoritative and shutdown continues. Forced process kill stays
        outside this guarantee.
        """
        self._sync_init()
        self._sync_shutting_down = True
        try:
            if self._sync_timer is not None:
                self._sync_timer.stop()
        except Exception:
            pass

        # W2-003: a restored DB has been committed and the in-memory (RAM)
        # state is stale. Never publish the stale memory back to the mirror —
        # the restored DB is authoritative and any post-restore publication
        # must not receive the pre-restore text. Retire the worker cleanly
        # without capturing/sending a final snapshot.
        if getattr(self, "_restore_stale_memory", False):
            from fastprompter.core.logging import logger as _log
            _log.info("sync shutdown skipped final mirror: restore committed, "
                      "RAM is stale")
            self._sync_pending = None
            return True

        # final committed snapshot, coalesced over any pending job
        final = self._capture_sync_snapshot(force=True)
        if final is not None:
            self._sync_gen += 1
            final["gen"] = self._sync_gen
            final["owner"] = self._sync_owner
            _sync_register_snapshot(final)
            self._sync_pending = final
        if not self._sync_busy and self._sync_pending is not None:
            self._sync_dispatch_pending()

        # bounded wait for the flush; the worker's completion drains anything
        # still queued, and this pump lets that happen
        from PyQt6.QtWidgets import QApplication
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while self._sync_busy and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        if self._sync_busy:
            # the worker did not finish within the bound (contention, a slow
            # prior job): flush the final snapshot SYNCHRONOUSLY as the last
            # guarantee. The window is closing; determinism beats async here,
            # and the same reparse-checked atomic write path is used. A
            # genuinely hung filesystem makes this write fail fast and log;
            # the SQLite database stays authoritative.
            from fastprompter.core.logging import logger as _log
            snap = final if final is not None else self._sync_pending
            if snap is not None:
                _log.warning("sync worker did not drain during shutdown; "
                             "attempting the final snapshot synchronously")
                written, errors = _sync_mechanical_write(snap, lock_timeout_s=0.5)
                for dest in written:
                    self._sync_written[dest] = snap["files"][dest]
                if errors:
                    _log.error("sync fallback encountered errors; DEGRADED MIRROR, "
                               "SQLite remains authoritative: %s", errors)

        if self._sync_busy:
            from fastprompter.core.logging import logger as _log2
            _log2.warning("sync flush timed out during shutdown; the disk "
                          "mirror may be stale — the SQLite database is "
                          "authoritative")
            # W2-002: do not discard final pending while busy and fallback
            # did not publish; retain for drain after old writer retires
            return False
        self._sync_pending = None
        # Never falsify physical ownership. A timed-out worker remains inflight
        # until its real done signal arrives (or global shutdown stops it).
        return True
    def init_ui(self):
        flags = Qt.WindowType.Window
        if self.data.get("normal_window", "False") != "True":
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.data.get("always_on_top", "True") == "True":
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setMinimumSize(480, 320)

        self.setMouseTracking(True)
        self._initializing_ui, self._suspend_temp_sync = True, True

        self._resizers = {
            "left": EdgeResizer(self, "left"),
            "right": EdgeResizer(self, "right"),
            "top": EdgeResizer(self, "top"),
            "bottom": EdgeResizer(self, "bottom"),
            "topleft": EdgeResizer(self, "topleft"),
            "topright": EdgeResizer(self, "topright"),
            "bottomleft": EdgeResizer(self, "bottomleft"),
            "bottomright": EdgeResizer(self, "bottomright"),
        }

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(2)

        self.header_widget = QWidget()
        # A plain QWidget ignores a stylesheet background unless this is set —
        # without it apply_theme()'s #HeaderBar tint is a silent no-op.
        self.header_widget.setObjectName("HeaderBar")
        self.header_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(0)   # see _apply_header_density

        self.btn_sidebar_toggle = QPushButton("☰")
        self.apply_button_size(self.btn_sidebar_toggle, 24, 24)
        self.btn_sidebar_toggle.setToolTip(tr(
            "Toggle Sidebar (Alt+D)\nShow or hide the right/left sidebar containing snippets and silos.",
            getattr(self, "_current_lang", "EN")))
        self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar_visibility)
        self.header_layout.addWidget(self.btn_sidebar_toggle)

        self.cat_combo = QComboBox()

        for cat in self.visible_categories():
            self.cat_combo.addItem(cat, cat)
        self.cat_combo.currentIndexChanged.connect(self.on_tab_changed)

        self.cat_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cat_combo.customContextMenuRequested.connect(self.show_cat_context_menu)

        self.cat_numbox = QWidget()
        # A grid, not a row: the project cap is 100, and 100 boxes in one
        # QHBoxLayout is ~2200px of header that simply runs off the window.
        # Wraps every `numbox_per_row` buttons instead (user-configurable).
        from PyQt6.QtWidgets import QGridLayout
        self._cat_numbox_layout = QGridLayout(self.cat_numbox)
        self._cat_numbox_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_numbox_layout.setSpacing(1)
        self._cat_num_buttons: list[QPushButton] = []
        self._rebuild_cat_numbox()

        # The number row FOLLOWS the combo instead of being rebuilt by hand at
        # every call site. Four places changed the project list without
        # touching it — add, delete, rename, and opening Trash — so a new
        # project simply did not get a button until the Number Tabs switch was
        # flipped twice. Sprinkling four more calls would leave the fifth site
        # anyone writes next year broken in exactly the same way; listening to
        # the model covers those too.
        model = self.cat_combo.model()
        model.rowsInserted.connect(self._schedule_numbox_rebuild)
        model.rowsRemoved.connect(self._schedule_numbox_rebuild)
        model.dataChanged.connect(self._schedule_numbox_rebuild)

        numbox_on = self.data.get("numbox_tabs", "False") == "True"
        self.cat_combo.setVisible(not numbox_on)
        self.cat_numbox.setVisible(numbox_on)

        self.btn_new = QPushButton(tr("NEW", getattr(self, "_current_lang", "EN")))
        self.btn_new.setToolTip(
            tr("NEW ({})", self._current_lang).format(self.data.get('hk_new_snippet', 'Ctrl+N'))
            + "\n" + tr("Right-click: new silo at the bottom", self._current_lang))
        self.apply_button_size(self.btn_new, 24)
        self.btn_new.setMinimumWidth(80)
        self.btn_new.clicked.connect(lambda: self.select_empty_silo(insertion=None))
        # Middle-click is a shortcut, not a second way to do the same thing:
        # it skips the empty silo and offers the templates straight away.
        self.btn_new.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_new.installEventFilter(self)
        # right-click creates from the BOTTOM instead of the top (T-598).
        # Preset menu is exclusively middle-click (eventFilter); right-click
        # is exactly one bottom-insert action — no dual wiring (CORE-016).
        self.btn_new.customContextMenuRequested.connect(
            lambda *_a: self.append_empty_silo())

        self.btn_save = QPushButton(tr("Save", getattr(self, "_current_lang", "EN")))
        self.btn_save.setToolTip(tr("Save ({})", self._current_lang).format(self.data.get('hk_save_snippet', 'Ctrl+S')))
        self.apply_button_size(self.btn_save, 24)
        self.btn_save.clicked.connect(self.save_snippet)

        self.btn_home = QPushButton(tr("Home", getattr(self, "_current_lang", "EN")))
        self.btn_home.setToolTip(tr("Home (Home)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_home, 24)
        self.btn_home.clicked.connect(self.move_cursor_home)

        self.btn_end = QPushButton(tr("End", getattr(self, "_current_lang", "EN")))
        self.btn_end.setToolTip(tr("Jump to End\nMove cursor to the bottom of the document.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_end, 24)
        self.btn_end.clicked.connect(self.move_cursor_end)

        self.btn_add_line = QPushButton(tr("Line", getattr(self, "_current_lang", "EN")))
        self.btn_add_line.setToolTip(tr(
            "Insert Line (Ctrl+W)\nInsert a spaced --- divider and start a fresh bullet.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_add_line, 24)
        self.btn_add_line.clicked.connect(self.insert_add_line)

        # Vision: the preview_combo's three modes as one cycling button, for
        # people who want the mode switch on the toolbar rather than in the
        # settings footer. The combo stays the data layer — this only drives
        # its index, so there is one source of truth for the mode.
        self.btn_vision = QPushButton("👁")
        self.apply_button_size(self.btn_vision, 24, 24)
        # a tooltip from the start: _refresh_vision_button only runs once the
        # mode changes, and a header button with no tooltip is a dead control
        self.btn_vision.setToolTip(tr(
            "Vision\nClick to cycle Source View / Live Preview / Reading",
            getattr(self, "_current_lang", "EN")))
        self.btn_vision.clicked.connect(self.cycle_vision_mode)

        self.btn_bullet_toggle = QPushButton("-→•")
        self.apply_button_size(self.btn_bullet_toggle, 24)
        self.btn_bullet_toggle.setCheckable(True)
        self.btn_bullet_toggle.setChecked(self.data.get("auto_bullet", "False") == "True")

        def _bullet_mousePress(event):
            if event.button() == Qt.MouseButton.RightButton:
                self.set_auto_bullet(
                    self.data.get("auto_bullet", "False") != "True")
                self.play_click_sound()
                event.accept()
            else:
                QPushButton.mousePressEvent(self.btn_bullet_toggle, event)

        self.btn_bullet_toggle.mousePressEvent = _bullet_mousePress

        def _on_bullet_left_click():
            # Left click naturally toggles the checked state, revert it to actual auto_bullet mode.
            self.btn_bullet_toggle.setChecked(self.data.get("auto_bullet", "False") == "True")
            self.toggle_bullet_conversion()

        self._refresh_bullet_toggle()
        self.btn_bullet_toggle.clicked.connect(_on_bullet_left_click)

        self.btn_bold = QPushButton(tr("B", getattr(self, "_current_lang", "EN")))
        self.btn_bold.setToolTip(tr("Bold ({})\nMake selected text bold.", self._current_lang).format(self.data.get('hk_bold', 'Ctrl+B')))
        self.apply_button_size(self.btn_bold, 24, 24)
        f = QFont(self.btn_bold.font()); f.setBold(True); self.btn_bold.setFont(f)
        self.btn_bold.clicked.connect(lambda: self.apply_format("bold"))

        self.btn_italic = QPushButton(tr("I", getattr(self, "_current_lang", "EN")))
        self.btn_italic.setToolTip(tr("Italic ({})\nMake selected text italic.", self._current_lang).format(self.data.get('hk_italic', 'Ctrl+I')))
        self.apply_button_size(self.btn_italic, 24, 24)
        f = QFont(self.btn_italic.font()); f.setItalic(True); self.btn_italic.setFont(f)
        self.btn_italic.clicked.connect(lambda: self.apply_format("italic"))

        self.btn_under = QPushButton(tr("U", getattr(self, "_current_lang", "EN")))
        self.btn_under.setToolTip(tr("Underline ({})\nMake selected text underlined.", self._current_lang).format(self.data.get('hk_underline', 'Ctrl+U')))
        self.apply_button_size(self.btn_under, 24, 24)
        f = QFont(self.btn_under.font()); f.setUnderline(True); self.btn_under.setFont(f)
        self.btn_under.clicked.connect(lambda: self.apply_format("underline"))

        self.btn_strike = QPushButton(tr("S", getattr(self, "_current_lang", "EN")))
        self.btn_strike.setToolTip(tr("Strikethrough (Ctrl+T)\nCross out selected text.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_strike, 24, 24)
        f = QFont(self.btn_strike.font()); f.setStrikeOut(True); self.btn_strike.setFont(f)
        self.btn_strike.clicked.connect(lambda: self.apply_format("strike"))

        self.btn_header = QPushButton(tr("H", getattr(self, "_current_lang", "EN")))
        self.btn_header.setToolTip(tr(
            "Header (Ctrl+E)\nTitle the line: # + bold + underline + timestamp,\n"
            "then land 2 lines below on a fresh bullet.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_header, 24, 24)
        f = QFont(self.btn_header.font()); f.setBold(True); f.setUnderline(True); self.btn_header.setFont(f)
        self.btn_header.clicked.connect(self.apply_header_timestamp)

        self.btn_quote = QPushButton("❞")
        self.btn_quote.setToolTip(tr(
            "Quote (Ctrl+Shift+Q)\nWrap the selected lines as a '> ' quote block.\n"
            "A quote of 2+ lines collapses to one line like a footnote.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_quote, 24, 24)
        self.btn_quote.clicked.connect(self.toggle_quote_conversion)

        self.btn_align_left = QPushButton(tr("L", getattr(self, "_current_lang", "EN")))
        self.btn_align_left.setToolTip(tr(
            "Align Left\nAlign selected blocks to the left.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_align_left, 24, 24)
        self.btn_align_left.clicked.connect(lambda: self._on_selection_align("left"))

        self.btn_align_center = QPushButton(tr("C", getattr(self, "_current_lang", "EN")))
        self.btn_align_center.setToolTip(tr(
            "Align Center\nCenter the selected blocks.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_align_center, 24, 24)
        self.btn_align_center.clicked.connect(lambda: self._on_selection_align("center"))

        self.btn_align_right = QPushButton(tr("R", getattr(self, "_current_lang", "EN")))
        self.btn_align_right.setToolTip(tr(
            "Align Right\nAlign selected blocks to the right.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_align_right, 24, 24)
        self.btn_align_right.clicked.connect(lambda: self._on_selection_align("right"))

        self.btn_clear_fmt = QPushButton(tr("Clear Fmt", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fmt.setToolTip(tr("Clear Format\nRemove all explicit font styling from text.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_clear_fmt, 24)
        self.btn_clear_fmt.clicked.connect(self.clear_formatting)



        self.btn_settings_toggle = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle, 24, 24)
        self.btn_settings_toggle.setToolTip(tr(
            "Settings\nConfigure hotkeys, theme, fonts, and UI scaling.", getattr(self, "_current_lang", "EN")))
        self.btn_settings_toggle.clicked.connect(self.toggle_mini_settings)

        self.btn_settings_toggle_right = QPushButton("⚙")
        self.apply_button_size(self.btn_settings_toggle_right, 24, 24)
        self.btn_settings_toggle_right.setToolTip(self.btn_settings_toggle.toolTip())
        self.btn_settings_toggle_right.clicked.connect(self.toggle_mini_settings)

        self.btn_help = QPushButton("❓")
        self.btn_help.setToolTip(tr("Help — every hotkey, gesture and feature (click)", getattr(self, "_current_lang", "EN")))
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button_size(self.btn_help, 24, 24)
        self.btn_help.clicked.connect(self.open_help_dialog)

        self.btn_copy = QPushButton(tr("Copy", getattr(self, "_current_lang", "EN")))
        self.btn_copy.setToolTip(tr("Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_copy, 26)
        self.btn_copy.clicked.connect(self.copy_context_to_clipboard)
        self.btn_copy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_copy.customContextMenuRequested.connect(self.copy_context_and_close)

        self.btn_clear = QPushButton(tr("Clear", getattr(self, "_current_lang", "EN")))
        self.btn_clear.setToolTip(tr("Clear (Ctrl+Shift+C)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_clear, 26)
        self.btn_clear.clicked.connect(self.clear_text)

        self.btn_files = QPushButton("📁")
        self.btn_files.setToolTip(tr(
            "Files\nAsset drawer for the active silo: drop any files in,\n"
            "drag them out, preview, export. Stored as a plain folder\n"
            "in data/files — readable outside FastPrompter.", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_files, 24)
        self.btn_files.clicked.connect(self.toggle_file_container)

        self.btn_project_run = QPushButton("▶️")
        self.btn_project_run.setToolTip(tr("Run Executable", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_project_run, 20)
        self.btn_project_run.clicked.connect(self._launch_silo_executable)
        self.btn_project_run.hide()

        self.btn_project_folder = QPushButton("🗂️")
        self.btn_project_folder.setToolTip(tr("Open Project Folder", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_project_folder, 20)
        self.btn_project_folder.clicked.connect(self._open_silo_project_folder)
        self.btn_project_folder.hide()

        self.btn_trash = QPushButton("🗑️")
        self.apply_button_size(self.btn_trash, 20, 20)
        self.btn_trash.setToolTip(tr("Open Trash", getattr(self, "_current_lang", "EN")))
        self.btn_trash.clicked.connect(self.open_trash)

        self.btn_toggle_search = QPushButton("⌕")
        self.apply_button_size(self.btn_toggle_search, 20, 20)
        self.btn_toggle_search.setCheckable(True)
        self.btn_toggle_search.setToolTip(tr("Show / hide find and replace", getattr(self, "_current_lang", "EN")))

        self.btn_arc_snip = QPushButton("📥")
        self.apply_button_size(self.btn_arc_snip, 20, 20)
        self.btn_arc_snip.setToolTip(tr("Archive Active Snippet or Silo", getattr(self, "_current_lang", "EN")))
        self.btn_arc_snip.clicked.connect(self.archive_active_item)

        self.btn_toggle_snippets = QPushButton("🗒")
        self.apply_button_size(self.btn_toggle_snippets, 20, 20)
        self.btn_toggle_snippets.setCheckable(True)
        self.btn_toggle_snippets.setToolTip(tr(
            "Show / hide the snippets panel", getattr(self, "_current_lang", "EN")))
        self.btn_toggle_snippets.clicked.connect(self.toggle_snippets_panel)

        self.btn_toggle_archive = QPushButton("📦")
        self.apply_button_size(self.btn_toggle_archive, 20, 20)
        self.btn_toggle_archive.setToolTip(tr("Toggle Archives", getattr(self, "_current_lang", "EN")))
        self.btn_toggle_archive.setCheckable(True)
        # Navigation
        self.header_layout.addWidget(self.cat_combo)
        self.header_layout.addWidget(self.cat_numbox)

        self.header_layout.addWidget(self.btn_new)
        self.header_layout.addWidget(self.btn_save)

        # Cursor nav sits next to New/Save (used together while writing)
        self.header_layout.addWidget(self.btn_home)
        self.header_layout.addWidget(self.btn_end)

        # Formatting and editing
        self.header_layout.addStretch(1)
        self.header_layout.addWidget(self.btn_bold)
        self.header_layout.addWidget(self.btn_italic)
        self.header_layout.addWidget(self.btn_under)
        self.header_layout.addWidget(self.btn_strike)
        self.header_layout.addWidget(self.btn_header)
        self.header_layout.addWidget(self.btn_quote)
        self.header_layout.addWidget(self.btn_align_left)
        self.header_layout.addWidget(self.btn_align_center)
        self.header_layout.addWidget(self.btn_align_right)

        # Overflow: at narrow widths the density tiers drop most of the
        # header, so surface everything they dropped in one menu.
        self.btn_overflow = QPushButton("»")
        self.btn_overflow.setToolTip(tr(
            "More\nButtons hidden because the window is narrow.",
            getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_overflow, 24, 24)
        self.btn_overflow.clicked.connect(self._show_overflow_menu)
        self.btn_overflow.setVisible(False)
        self.header_layout.addWidget(self.btn_overflow)
        self.header_layout.addWidget(self.btn_clear_fmt)
        self.header_layout.addWidget(self.btn_add_line)
        self.header_layout.addWidget(self.btn_bullet_toggle)
        self.header_layout.addWidget(self.btn_copy)
        self.header_layout.addWidget(self.btn_clear)
        # btn_files lives in the sidebar next to the archive buttons

        # Status cluster (right): clock | pins | line counter | settings
        self.header_layout.addStretch(1)
        from fastprompter.ui.analog_clock import MiniAnalogClock
        self.analog_clock = MiniAnalogClock(self)
        self.analog_clock.setToolTip(tr(
            "Current time (analog)\nClick to manage Interval Notifications",
            getattr(self, "_current_lang", "EN")))
        self.header_layout.addWidget(self.analog_clock)

        self.lbl_date = QLabel("")
        self.lbl_date.setToolTip(tr(
            "Current date and time\nClick to manage timers and limit resets\n"
            "Shift+Click: add Temp Timer time\n"
            "Ctrl+Shift+Click: remove Temp Timer",
            getattr(self, "_current_lang", "EN")))
        self.lbl_date.setStyleSheet("padding: 0 4px;")
        self.lbl_date.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_date.mousePressEvent = self._clock_label_clicked
        # Right-click: acknowledge/clear the passed-event red alert, or open
        # the timer manager (see _apply_date_alert_style).
        self.lbl_date.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lbl_date.customContextMenuRequested.connect(self._date_label_menu)
        self.header_layout.addWidget(self.lbl_date)

        # nearest live timer, right beside the clock
        self.lbl_timer = QLabel("")
        self.lbl_timer.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.lbl_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_timer.mousePressEvent = self._clock_label_clicked
        self.lbl_timer.setVisible(False)
        self.header_layout.addWidget(self.lbl_timer)

        self.btn_pin_top = QPushButton("📌")
        self.btn_pin_top.setCheckable(True)
        self.btn_pin_top.setChecked(self.data.get("always_on_top", "True") == "True")
        self.btn_pin_top.setToolTip(tr("Always on Top — keep the window above all others", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_pin_top, 20, 20)
        self.btn_pin_top.toggled.connect(self._pin_top_toggled)
        self.header_layout.addWidget(self.btn_pin_top)

        self.btn_line_nums = QPushButton("#")
        self.btn_line_nums.setCheckable(True)
        self.btn_line_nums.setChecked(self.data.get("show_line_numbers", "False") == "True")
        self.btn_line_nums.setToolTip(tr(
            "Show / hide the line-number gutter\n(click the gutter to place colored margin marks)", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_line_nums, 20, 20)
        self.btn_line_nums.toggled.connect(self._line_nums_btn_toggled)
        self.header_layout.addWidget(self.btn_line_nums)

        # Kept as a tiny invisible spacer so the toolbar-order "<sep>" token
        # still resolves; the visible divider line was removed per request.
        self._counter_sep = QFrame()
        self._counter_sep.setFrameShape(QFrame.Shape.NoFrame)
        self._counter_sep.setFixedSize(3, 16)
        self.header_layout.addWidget(self._counter_sep)

        self.lbl_line_count = QLabel("")
        self.lbl_line_count.setToolTip(tr("Line count of the open silo/snippet", getattr(self, "_current_lang", "EN")))
        self.lbl_line_count.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.header_layout.addWidget(self.lbl_line_count)

        # Token estimate, right beside the line count — same cluster, same
        # question ("how big is this silo"), just the unit an LLM charges in.
        self.lbl_token_count = QLabel("")
        self.lbl_token_count.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.lbl_token_count.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_token_count.mousePressEvent = lambda _e: self._cycle_token_mode()
        self.lbl_token_count.setVisible(
            self.data.get("show_token_count", "False") == "True")
        self.header_layout.addWidget(self.lbl_token_count)

        self.header_layout.addWidget(self.btn_settings_toggle)
        self.header_layout.addWidget(self.btn_help)

        # Reset-layout button — a fixed trailing control, shown only while
        # Customize Toolbar is on (re-added by apply_toolbar_order each rebuild)
        self.btn_toolbar_reset = QPushButton("↺")
        self.btn_toolbar_reset.setToolTip(tr("Reset the toolbar to its default order", getattr(self, "_current_lang", "EN")))
        self.apply_button_size(self.btn_toolbar_reset, 20, 20)
        self.btn_toolbar_reset.clicked.connect(self.reset_toolbar_order)
        self.btn_toolbar_reset.setVisible(False)
        self.header_layout.addWidget(self.btn_toolbar_reset)
        self.main_layout.addWidget(self.header_widget)

        # Apply any saved custom toolbar order, then arm drag-reorder
        from fastprompter.ui.toolbar_reorder import install_toolbar_reorder
        self.apply_toolbar_order()
        install_toolbar_reorder(self)

        self.mini_settings_frame = QFrame(self)
        self.mini_settings_frame.setVisible(False)

        self.font_combo = QComboBox()
        self.font_combo.addItems(
            [
                "Verdana",
                "Tahoma",
                "Consolas",
                "Calibri",
                "Times New Roman",
                "Arial",
                "Segoe UI",
                "Courier New",
            ]
        )
        saved_font = self.data.get("font_family", "Verdana")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self.change_font_family)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 48)
        try:
            self.font_spin.setValue(int(self.data.get("font_size", "11")))
        except Exception:
            self.font_spin.setValue(11)
        self.font_spin.valueChanged.connect(self.change_font_size)

        self.preview_combo = QComboBox()
        # The English mode name is stored as itemData and is the SINGLE source
        # of truth: the display text is translated per-language, but every
        # lookup (change_preview_mode, saved-value match) reads itemData so a
        # translated combo never breaks the mode logic or gets stuck in a
        # foreign language.
        for _mode in ("Source View", "Live Preview", "Reading"):
            self.preview_combo.addItem(_mode, _mode)
        self._retranslate_preview_combo(getattr(self, "_current_lang", "EN"))
        self.preview_combo.setToolTip(tr(
            "Source View: Plain text editor\n"
            "Live Preview: Editor with live markdown highlights (default)\n"
            "Reading: Read-only rendered markdown view", getattr(self, "_current_lang", "EN")))
        # Map old saved values to new
        _view_map = {"None": "Source View", "Raw": "Source View", "Markdown": "Reading"}
        saved_preview = self.data.get("preview_mode", "Live Preview")
        saved_preview = _view_map.get(saved_preview, saved_preview)  # migrate old values
        idx = self.preview_combo.findData(saved_preview)
        if idx < 0:
            idx = 1  # default to Live Preview
        self.preview_combo.setCurrentIndex(idx)
        self.preview_combo.currentIndexChanged.connect(self.change_preview_mode)

        self.cb_theme = QComboBox()
        self.cb_theme.addItems(
            [
                "Default",
                "Golden Vintage",
                "Golden Default",
                "Vintage Dark",
                "Vintage Classic",
                "Dark 2 (OLED)",
                "Dracula",
                "Nord",
                "Solarized Dark",
                "Custom",
            ]
        )
        saved_theme = self.data.get("theme", "Default")
        idx = self.cb_theme.findText(saved_theme)
        if idx >= 0:
            self.cb_theme.setCurrentIndex(idx)
        self.cb_theme.currentTextChanged.connect(self.change_theme)

        # Removed broken preset_combo — it didn't work

        def make_action_checkbox(text, callback):
            btn = QPushButton(text)
            btn.clicked.connect(lambda: (self.play_tick_sound(), callback()))
            btn._en_text = text
            return btn

        self.btn_hotkeys = make_action_checkbox("Keys", self.open_hotkey_settings)
        self.btn_hotkeys.setToolTip(tr("Configure Global Hotkeys (Settings Cog)", getattr(self, "_current_lang", "EN")))
        self.btn_colors = make_action_checkbox("RGB", self.open_color_settings)
        self.btn_colors.setToolTip(tr("Custom Theme Colors (Color Palette)", getattr(self, "_current_lang", "EN")))
        self.btn_backup = make_action_checkbox("BkUp", self.backup_db)
        self.btn_backup.setToolTip(tr("Backup the database", getattr(self, "_current_lang", "EN")))
        self.btn_restore = make_action_checkbox("Rstr", self.restore_db)
        self.btn_restore.setToolTip(tr("Restore the database from a backup", getattr(self, "_current_lang", "EN")))

        try:
            current_scale_pct = int(float(self.data.get("ui_scale", "0.5")) * 100)
        except Exception:
            current_scale_pct = 100
        self.btn_button_scale = make_action_checkbox(
            f"Scale: {current_scale_pct}%", self.cycle_button_scale
        )
        self.btn_button_scale.setToolTip(tr(
            "Scale the whole program: 50 / 75 / 100 / 125 / 150%\n"
            "(fine-tune with Ctrl+Plus / Ctrl+Minus)", getattr(self, "_current_lang", "EN"))
        )

        # Load custom font button
        self.btn_load_font = QPushButton(tr("+ Font", getattr(self, "_current_lang", "EN")))
        self.btn_load_font.setFixedWidth(52)
        self.btn_load_font.setToolTip(tr("Load a custom .ttf/.otf font file", getattr(self, "_current_lang", "EN")))
        self.btn_load_font.clicked.connect(self.load_custom_font)

        self.btn_clear_fonts = QPushButton(tr("× Fonts", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fonts.setFixedWidth(54)
        self.btn_clear_fonts.setToolTip(tr("Clear all custom fonts from combo (reset to defaults)", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fonts.clicked.connect(self.clear_custom_fonts)

        # Volume control
        self.spin_volume = QSpinBox()
        self.spin_volume.setRange(1, 10)
        try:
            self.spin_volume.setValue(int(self.data.get("sound_volume", "5")))
        except Exception:
            self.spin_volume.setValue(5)
        self.spin_volume.setFixedWidth(42)
        self.spin_volume.setToolTip(tr("Click sound volume (1-10)", getattr(self, "_current_lang", "EN")))
        self.spin_volume.valueChanged.connect(
            lambda v: (self.data.update({"sound_volume": str(v)}), self.mark_dirty())
        )

        # --- Settings panel: hidden by default, toggled by the gear button. ---
        # Top row: appearance & actions. Below: toggles grouped by purpose.
        # Gathered as a flat list, not a fixed QHBoxLayout: 17 controls in
        # one rigid row is what forced the whole panel to ~1800px wide.
        # FlowLayout wraps them instead (see below).
        self._appearance_items = []
        appearance_row = self._appearance_items
        appearance_row.append(QLabel(tr("Font:", getattr(self, "_current_lang", "EN"))))
        appearance_row.append(self.font_combo)
        appearance_row.append(self.font_spin)
        appearance_row.append(self.btn_load_font)
        appearance_row.append(self.btn_clear_fonts)
        pass  # spacing handled by the flow layout
        appearance_row.append(QLabel(tr("Theme:", getattr(self, "_current_lang", "EN"))))
        appearance_row.append(self.cb_theme)
        appearance_row.append(self.btn_colors)

        self.btn_drop_zones = make_action_checkbox("Drop Zones", self.open_drop_zones_settings)
        self.btn_drop_zones.setToolTip(tr("Customize Drop Zones", getattr(self, "_current_lang", "EN")))
        appearance_row.append(self.btn_drop_zones)
        pass  # spacing handled by the flow layout
        appearance_row.append(QLabel(tr("View:", getattr(self, "_current_lang", "EN"))))
        appearance_row.append(self.preview_combo)
        appearance_row.append(self.btn_button_scale)
        pass  # spacing handled by the flow layout
        appearance_row.append(QLabel(tr("Language:", getattr(self, "_current_lang", "EN"))))
        self.cb_language = QComboBox()
        # Every language the i18n pack can serve, shown by its native name +
        # a drawn flag icon, keyed on the code (stored as itemData so the
        # display text is free to be localized without breaking the lookup).
        from PyQt6.QtCore import QSize

        from fastprompter.ui.flags import flag_icon
        self.cb_language.setIconSize(QSize(18, 12))
        for code in available_languages():
            native = _LANG_NATIVE_NAMES.get(code, code)
            label = native if code in ("EN",) else f"{native} ({code})"
            ic = flag_icon(code)
            if ic is not None:
                self.cb_language.addItem(ic, label, code)
            else:
                self.cb_language.addItem(label, code)
        saved_lang = self.data.get("language", "EN")
        saved_idx = self.cb_language.findData(saved_lang)
        if saved_idx >= 0:
            self.cb_language.setCurrentIndex(saved_idx)
        self.cb_language.currentIndexChanged.connect(
            lambda i: self._on_language_changed(self.cb_language.itemData(i) or "EN")
        )
        appearance_row.append(self.cb_language)
        pass  # stretch handled by the flow layout
        appearance_row.append(self.btn_hotkeys)
        appearance_row.append(self.btn_backup)
        appearance_row.append(self.btn_restore)

        def create_footer_cb(text, tooltip, checked, callback):
            cb = QCheckBox(text)
            cb.setToolTip(tooltip)
            cb.setChecked(checked)
            if callback:
                cb.toggled.connect(self.play_tick_sound)
                cb.toggled.connect(callback)
            cb._en_text = text
            cb._en_tooltip = tooltip
            return cb

        self.cb_top = create_footer_cb(
            "📌 Always on Top",
            "Keep the window above all others",
            self.data.get("always_on_top", "True") == "True",
            self.toggle_aot,
        )
        self.cb_lock_window = create_footer_cb(
            "🔒 Lock Window",
            "Freeze the window's position and size",
            self.data.get("window_locked", "False") == "True",
            self.set_lock_state,
        )
        self.cb_normal_window = create_footer_cb(
            "🪟 Normal Window",
            "Use a standard OS window frame and taskbar entry",
            self.data.get("normal_window", "False") == "True",
            self.apply_window_flags,
        )
        self.cb_tray = create_footer_cb(
            "📉 Tray Icon",
            "Keep an icon in the system tray",
            self.data.get("tray_visible", "True") == "True",
            self.on_tray_toggled,
        )
        self.cb_sidebar = create_footer_cb(
            "▶ Sidebar Right",
            "Move the snippet/silo sidebar to the right side",
            self.data.get("sidebar_right", "False") == "True",
            self.toggle_sidebar_position,
        )
        self.cb_custom_cursors = create_footer_cb(
            "\u2196 My Cursors",
            "Use the cursor set the program has copied.\n"
            "First time on, it copies your current Windows set.\n"
            "Animated cursors keep their default shape - Qt cannot read them.",
            self.data.get("custom_cursors", "False") == "True",
            self.toggle_custom_cursors,
        )
        self.cb_focus = create_footer_cb(
            "👁 Hide on Click-Out",
            "Hide the window when you click outside of it\nGlobal toggle: Alt+A",
            self.data.get("close_on_focus_loss", "True") == "True",
            self.mark_dirty,
        )
        self.cb_snippet_arrows = create_footer_cb(
            "↕ Snippet Arrows",
            "Show the ▲ ▶ ▼ paste buttons on snippet rows\n"
            "(insert at top / at cursor / at bottom)",
            self.data.get("snippet_arrows", "False") == "True",
            lambda checked: (
                self.data.update({"snippet_arrows": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_snippets_panel()
            ),
        )
        self.cb_silo_ticks = create_footer_cb(
            "✅ Silo Ticks",
            "Show the ✅ done-mark button when hovering a silo.\n"
            "Off by default — Ctrl+Shift+click a silo toggles its tick either way.",
            self.data.get("silo_ticks_enabled", "False") == "True",
            lambda checked: (
                self.data.update({"silo_ticks_enabled": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
            ),
        )
        self.cb_ctrl_c = create_footer_cb(
            "📋 Ctrl+C Hides",
            "Copying with Ctrl+C also hides the window\n(copy & get back to work in one stroke)",
            self.data.get("ctrl_c_closes", "True") == "True",
            self.mark_dirty,
        )
        self.cb_lock_cursor = create_footer_cb(
            "🖱 Open at Cursor",
            "The hotkey opens the window at your mouse cursor",
            self.data.get("lock_to_cursor", "False") == "True",
            self.on_lock_cursor_toggled,
        )
        self.cb_customize_toolbar = create_footer_cb(
            "🧩 Customize Toolbar",
            "Drag the top-bar buttons to reorder them. Dashed boxes are\n"
            "flexible gaps — drop a button on either side to move it between\n"
            "the left / centre / right zones. Use the ↺ button (or right-click\n"
            "this text) to reset to the default order.",
            self.data.get("customize_toolbar", "False") == "True",
            self.on_customize_toolbar_toggled,
        )
        self.cb_numbox_tabs = create_footer_cb(
            "# Number Tabs",
            "Show numbered boxes instead of the project dropdown",
            self.data.get("numbox_tabs", "False") == "True",
            self._toggle_numbox_mode,
        )
        # Number-box geometry. With the project cap at 100 these are what keep
        # the row from running off the header, so they live beside the toggle.
        self.spin_numbox_per_row = QSpinBox()
        self.spin_numbox_per_row.setRange(1, 100)
        self.spin_numbox_per_row.setToolTip(tr(
            "How many number boxes per row before they wrap", self._current_lang))
        self.spin_numbox_per_row.setValue(self.numbox_per_row())
        self.spin_numbox_per_row.valueChanged.connect(
            lambda v: self._on_numbox_geometry_changed("numbox_per_row", v))
        self.spin_numbox_size = QSpinBox()
        self.spin_numbox_size.setRange(14, 40)
        self.spin_numbox_size.setSuffix(" px")
        self.spin_numbox_size.setToolTip(tr(
            "Size of one number box", self._current_lang))
        self.spin_numbox_size.setValue(self.numbox_button_size())
        self.spin_numbox_size.valueChanged.connect(
            lambda v: self._on_numbox_geometry_changed("numbox_btn_size", v))
        numbox_row = QHBoxLayout()
        numbox_row.setContentsMargins(0, 0, 0, 0)
        numbox_row.setSpacing(4)
        numbox_row.addWidget(QLabel(tr("Per row:", self._current_lang)))
        numbox_row.addWidget(self.spin_numbox_per_row)
        numbox_row.addWidget(QLabel(tr("Size:", self._current_lang)))
        numbox_row.addWidget(self.spin_numbox_size)
        numbox_row.addStretch(1)

        self.cb_window_presets = create_footer_cb(
            "🗔 Ctrl+Q Presets",
            "Add a 'Presets' page to the Ctrl+Q picker holding your own\n"
            "saved window positions (S saves, Del removes, 1-0 applies)",
            self.data.get("window_presets_enabled", "True") == "True",
            lambda checked: (
                self.data.update(
                    {"window_presets_enabled": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_files_dock = create_footer_cb(
            "🗂 Files Sidebar",
            "Keep the silo file panel docked as a collapsible sidebar on the\n"
            "side opposite the silo list, instead of a separate window.\n"
            "The 📁 button then opens and closes it.",
            self.data.get("file_panel_docked", "False") == "True",
            self._on_files_dock_toggled,
        )
        self.cb_toolbar_bottom = create_footer_cb(
            "⬇ Toolbar at Bottom",
            "Put the toolbar under the editor instead of above it.\n"
            "Same buttons, same order — only the side changes.",
            self.data.get("toolbar_position", "top") == "bottom",
            self.apply_toolbar_position,
        )
        self.cb_fast_zones = create_footer_cb(
            "⚡ Fast Ctrl+Q",
            "Skip the zone picker: every Ctrl+Q jumps straight to the next\n"
            "zone of the page chosen below and cycles through them",
            self.data.get("fancyzones_fast", "False") == "True",
            lambda checked: (
                self.data.update(
                    {"fancyzones_fast": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_fast_zone_page = QComboBox()
        self.cb_fast_zone_page.setToolTip(tr(
            "Which page Fast mode cycles through", self._current_lang))
        self._reload_fast_zone_pages()
        self.cb_fast_zone_page.currentIndexChanged.connect(
            self._on_fast_zone_page_changed)
        fast_row = QHBoxLayout()
        fast_row.setContentsMargins(0, 0, 0, 0)
        fast_row.setSpacing(4)
        fast_row.addWidget(QLabel(tr("Fast page:", self._current_lang)))
        fast_row.addWidget(self.cb_fast_zone_page)
        fast_row.addStretch(1)

        self.btn_manage_presets = QPushButton(tr("Manage presets", self._current_lang))
        self.btn_manage_presets.setToolTip(tr(
            "Reorder, rename, re-capture or delete your Ctrl+Q window presets",
            self._current_lang))
        self.btn_manage_presets.clicked.connect(self.open_window_presets)
        self.cb_customize_toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cb_customize_toolbar.customContextMenuRequested.connect(
            lambda _p: self.reset_toolbar_order())
        self.cb_silo_home = create_footer_cb(
            "🏠 Silos at Start",
            "Place the cursor at the top of a silo when opening it",
            self.data.get("silo_home", "False") == "True",
            self.on_silo_home_toggled,
        )
        self.cb_portable_backup = create_footer_cb(
            "💾 Auto Backup (.md)",
            "Mirror silos & snippets as Markdown files to Documents\\.fastprompter\\",
            self.data.get("portable_backup_enabled", "True") == "True",
            lambda checked: (
                self.data.update({"portable_backup_enabled": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_wrap = create_footer_cb(
            "↩ Word Wrap",
            "Wrap long lines instead of scrolling horizontally",
            self.data.get("word_wrap", "True") == "True",
            self.on_wrap_toggled,
        )
        self.cb_line_heat = create_footer_cb(
            "🌡 Line Heat",
            "Tint lines you edited recently, cooling as they age.\n"
            "Shows at a glance where you have just been working.",
            self.data.get("line_heat", "False") == "True",
            lambda checked: (
                self.data.update({"line_heat": "True" if checked else "False"})
                or self.mark_dirty()
                or self.text_area.viewport().update()
            ),
        )
        self.cb_hover_line = create_footer_cb(
            "🖱 Hover Line",
            "Faintly brighten the line under the mouse cursor",
            self.data.get("hover_line", "True") == "True",
            lambda checked: (
                self.data.update({"hover_line": "True" if checked else "False"})
                or self.mark_dirty()
                or self.text_area.viewport().update()
            ),
        )
        self.cb_code_monospace = create_footer_cb(
            "⌨ Monospace Code",
            "Render `code` and ``` blocks in Consolas.\n"
            "Off: use the editor's own font instead.",
            self.data.get("code_monospace", "True") == "True",
            lambda checked: (
                self.data.update({"code_monospace": "True" if checked else "False"})
                or self.mark_dirty()
                or self._apply_code_font()
            ),
        )
        self.cb_line_numbers = create_footer_cb(
            "🔢 Line Numbers",
            "Show a line-number gutter\n(click it to place colored margin marks)",
            self.data.get("show_line_numbers", "False") == "True",
            self.set_line_numbers,  # routes through the single source of truth
        )
        self.cb_code_gutter = create_footer_cb(
            "🔢 Auto # on Code",
            "Auto-show line numbers inside ``` code blocks even when the gutter\n"
            "is off. Off by default so the Line Numbers toggle stays a clean on/off.",
            self.data.get("code_auto_gutter", "False") == "True",
            lambda checked: (
                self.data.update({"code_auto_gutter": "True" if checked else "False"})
                or self.mark_dirty()
                or self.text_area.update_line_number_area_width()
                or self.text_area.line_number_area.update()
            ),
        )
        # keep the header pin button in sync with the always-on-top checkbox
        self.cb_top.toggled.connect(
            lambda c: hasattr(self, "btn_pin_top") and self.btn_pin_top.setChecked(c))

        self.cb_line_marks = create_footer_cb(
            "🔴 Line Marks",
            "Enable click-to-mark in line numbers (Red dot, Yellow Rhombus, Blue square)",
            self.data.get("line_marks", "False") == "True",
            lambda checked: self.data.update({"line_marks": "True" if checked else "False"})
                            or self.mark_dirty()
                            or (self.text_area.line_number_area.update() if hasattr(self, "text_area") and hasattr(self.text_area, "line_number_area") else None)
        )

        self.cb_token_count = create_footer_cb(
            "\ud83d\udd22 Token Counter",
            "Show an estimated input-token count beside the line count",
            self.data.get("show_token_count", "False") == "True",
            lambda checked: (
                self.data.update(
                    {"show_token_count": "True" if checked else "False"})
                or self._update_token_count_label()
                or self.mark_dirty()
            ),
        )
        self.cb_token_mode = QComboBox()
        self.cb_token_mode.addItem(tr("chars", self._current_lang), "chars")
        self.cb_token_mode.addItem(tr("words", self._current_lang), "words")
        mode = self.data.get("token_mode", "chars")
        self.cb_token_mode.setCurrentIndex(1 if mode == "words" else 0)
        self.cb_token_mode.setToolTip(tr(
            "How the estimate is weighted: characters per token,\n"
            "or tokens per word", self._current_lang))
        self.cb_token_mode.currentIndexChanged.connect(self._on_token_mode_changed)
        from PyQt6.QtWidgets import QDoubleSpinBox
        self.spin_token_weight = QDoubleSpinBox()
        self.spin_token_weight.setRange(0.1, 20.0)
        self.spin_token_weight.setSingleStep(0.1)
        self.spin_token_weight.setDecimals(2)
        self.spin_token_weight.setToolTip(tr(
            "Chars per token (chars mode) or tokens per word (words mode).\n"
            "Defaults: 4.0 and 1.33", self._current_lang))
        try:
            self.spin_token_weight.setValue(float(self.data.get("token_weight", 4.0)))
        except (TypeError, ValueError):
            self.spin_token_weight.setValue(4.0)
        self.spin_token_weight.valueChanged.connect(self._on_token_weight_changed)
        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.setSpacing(4)
        token_row.addWidget(QLabel(tr("Tokens by:", self._current_lang)))
        token_row.addWidget(self.cb_token_mode)
        token_row.addWidget(self.spin_token_weight)
        token_row.addStretch(1)

        # "\u2192 Ctrl+E Center" used to live here. It was the two-state face of
        # an alignment that is now chosen per line - title, rule and bullet
        # each on their own - in the Ctrl+E\u2026 dialog, and a checkbox has
        # nowhere to put right or justified. Two controls for one setting,
        # one of which could only ever tell half the truth. The ctrl_e_center
        # KEY is still read (see core/header.read_settings) so a profile
        # saved with it keeps its centring.
        self.cb_zebra = create_footer_cb(
            "🦓 Zebra Stripes",
            "Lightly shade every other line for readability",
            self.data.get("zebra_lines", "False") == "True",
            lambda checked: (
                self.data.update({"zebra_lines": "True" if checked else "False"})
                or self.text_area.viewport().update()
                or self.mark_dirty()
            ),
        )
        self.cb_hide_shortkeys = create_footer_cb(
            "⌨ Hide Key Hints",
            "Hide the F1-F10 shortcut labels on snippet buttons",
            self.data.get("hide_shortkeys", "False") == "True",
            self.on_hide_shortkeys_toggled,
        )
        # Text alignment combo
        self.lbl_align = QLabel(tr("Align:", self._current_lang))
        self.cb_align_combo = QComboBox()
        self.cb_align_combo.addItem(tr("Left", self._current_lang), "left")
        self.cb_align_combo.addItem(tr("Center", self._current_lang), "center")
        self.cb_align_combo.addItem(tr("Right", self._current_lang), "right")
        saved_align = self.data.get("text_align", "left")
        idx = self.cb_align_combo.findData(saved_align)
        if idx >= 0:
            self.cb_align_combo.setCurrentIndex(idx)
        self.cb_align_combo.currentIndexChanged.connect(self._on_align_changed)

        # How a pasted image lands. "Pill" is the collapsed golden chip you
        # can click to open; the other two are for people who want the raw
        # markdown or just the path.
        self.lbl_img_paste = QLabel(tr("Pasted image:", self._current_lang))
        self.cb_img_paste = QComboBox()
        self.cb_img_paste.addItem(tr("Pill (clickable)", self._current_lang), "pill")
        self.cb_img_paste.addItem(tr("Markdown link", self._current_lang), "link")
        self.cb_img_paste.addItem(tr("Plain path", self._current_lang), "path")
        self.cb_img_paste.setToolTip(tr(
            "Pill: ![](...) — collapses to a clickable chip\n"
            "Markdown link: [name](...) — plain link text\n"
            "Plain path: the file path on its own", self._current_lang))
        _idx = self.cb_img_paste.findData(self.data.get("image_paste_style", "pill"))
        if _idx >= 0:
            self.cb_img_paste.setCurrentIndex(_idx)
        self.cb_img_paste.currentIndexChanged.connect(
            lambda i: (self.data.update(
                {"image_paste_style": self.cb_img_paste.itemData(i) or "pill"})
                or self.mark_dirty()))

        # Silos down the side, or across the top as tabs.
        self.lbl_silo_mode = QLabel(tr("Silos:", self._current_lang))
        self.cb_silo_mode = QComboBox()
        self.cb_silo_mode.addItem(tr("Sidebar", self._current_lang), "sidebar")
        self.cb_silo_mode.addItem(tr("Horizontal tabs", self._current_lang), "tabs")
        self.cb_silo_mode.setToolTip(tr(
            "Sidebar: the usual column down the left\n"
            "Horizontal tabs: a strip above the editor — child silos have no\n"
            "room on a bar, so they move into the parent's right-click menu",
            self._current_lang))
        _idx = self.cb_silo_mode.findData(self.data.get("silo_tabs_mode", "sidebar"))
        if _idx >= 0:
            self.cb_silo_mode.setCurrentIndex(_idx)
        self.cb_silo_mode.currentIndexChanged.connect(
            lambda i: self.apply_silo_tabs_mode(
                (self.cb_silo_mode.itemData(i) or "sidebar") == "tabs"))

        self.cb_double_line = create_footer_cb(
            "⇕ Double-Space Lists",
            "With Auto-Bullet on, Enter after a list item adds a blank\n"
            "line before the next bullet — spaced, easy-to-read lists",
            self.data.get("bullet_double_line", "False") == "True",
            lambda checked: (
                self.data.update({"bullet_double_line": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_bold_titles = create_footer_cb(
            "𝗕 Bold # Titles",
            "Bold the sidebar title of silos and snippets whose\n"
            "content starts with a '#' markdown header",
            self.data.get("bold_hash_titles", "True") == "True",
            lambda checked: (
                self.data.update({"bold_hash_titles": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
                or self.refresh_snippets_panel()
                or self.refresh_archive_panel()
            ),
        )
        self.cb_silo_pinned_gap = create_footer_cb(
            "➖ Pinned Gap",
            "Show a visual separator between pinned and unpinned silos",
            self.data.get("silo_pinned_gap", "True") == "True",
            lambda checked: (
                self.data.update({"silo_pinned_gap": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
                or self.refresh_snippets_panel()
            ),
        )
        self.cb_conceal = create_footer_cb(
            "👁 Hide Markup (Live)",
            "Obsidian-style Live Preview: hide **, *, __, ~~ and ` markers so\n"
            "the text reads as rendered. The line the caret is on still shows\n"
            "its markers, so it stays editable.",
            self.data.get("live_preview_conceal", "False") == "True",
            lambda checked: (
                self.data.update({"live_preview_conceal": "True" if checked else "False"})
                or self.mark_dirty()
                or self._apply_conceal_mode()
            ),
        )
        self.cb_hr_visual = create_footer_cb(
            "➖ Render HR Lines",
            "Render ---/***/___ dividers as crisp visual lines instead of raw text",
            self.data.get("hr_visual_line", "True") == "True",
            lambda checked: (
                self.data.update({"hr_visual_line": "True" if checked else "False"})
                or self.mark_dirty()
                or (getattr(self, "highlighter", None) and self.highlighter.update_hr_as_line(checked))
                or (hasattr(self, "text_area") and hasattr(self.text_area, "viewport") and self.text_area.viewport().update())
            ),
        )
        self.cb_date_rect = create_footer_cb(
            "📅 Show Date Widget",
            "Show a floating date and time rectangle in the top-right\n"
            "corner of the text editor",
            self.data.get("show_date_rect", "True") == "True",
            lambda checked: (
                self.data.update({"show_date_rect": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_timer_minutes = create_footer_cb(
            "⏳ Timer Minutes",
            "Always show minutes in the top-right timer countdown\n"
            "(otherwise a long timer reads just '4d' or '2h')",
            self.data.get("timer_show_minutes", "False") == "True",
            lambda checked: (
                self.data.update(
                    {"timer_show_minutes": "True" if checked else "False"})
                or self._update_timer_label()
                or self.mark_dirty()
            ),
        )
        self.cb_date_seconds = create_footer_cb(
            "⏱ Date Seconds",
            "Show seconds in the date widget (hh:mm:ss instead of hh:mm)",
            self.data.get("date_seconds", "True") == "True",
            lambda checked: (
                self.data.update({"date_seconds": "True" if checked else "False"})
                or self.mark_dirty()
            ),
        )
        self.cb_analog_clock = create_footer_cb(
            "🕒 Analog Clock",
            "Show a mini analog clock (hour + minute hands)\nnext to the date widget",
            self.data.get("analog_clock", "False") == "True",
            lambda checked: (
                self.data.update({"analog_clock": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_daypart = create_footer_cb(
            "🌞 Day Word",
            "Show the time-of-day word (Morning / Day / Evening / Night)\n"
            "after the clock in the date widget",
            self.data.get("date_daypart", "True") == "True",
            lambda checked: (
                self.data.update({"date_daypart": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_emoji = create_footer_cb(
            "🎭 Emoji Day State",
            "Show an emoji (🌅/☀️/🌇/🌙) instead of the time-of-day word",
            self.data.get("date_emoji", "False") == "True",
            lambda checked: (
                self.data.update({"date_emoji": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_text_month = create_footer_cb(
            "🔤 Text Month",
            "Show month as text instead of numbers (17 Jul instead of 17.07)",
            self.data.get("date_text_month", "False") == "True",
            lambda checked: (
                self.data.update({"date_text_month": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_date_ampm = create_footer_cb(
            "🕐 12-Hour Clock",
            "Show time as 09:05 PM instead of 21:05 — applies to the date\n"
            "widget, Ctrl+E headers and the end-of-line timestamp",
            self.data.get("date_ampm", "False") == "True",
            lambda checked: (
                self.data.update({"date_ampm": "True" if checked else "False"})
                or self.mark_dirty()
                or self._update_date_label()
            ),
        )
        self.cb_sound = create_footer_cb(
            "🔊 UI Sounds",
            "Play click sounds for buttons and actions.\n"
            "You can place your own .wav files in the 'sound' folder to override:\n"
            "• newbutton1.wav (New button)\n"
            "• savebutton1.wav (Save button)\n"
            "• button1.wav (Click/Silo)\n"
            "• button2.wav (Snippet)\n"
            "• tickbox1.wav (Checkbox)\n"
            "• delete1.wav (Delete)\n"
            "• clear1.wav (Clear)",
            self.data.get("sound_ui", "False") == "True",
            self.on_sound_toggled,
        )
        self.cb_typewriter = create_footer_cb(
            "⌨ Typewriter",
            "Play a typewriter tick for every typed character.\n"
            "Place 'type1.wav' in the 'sound' folder to use your own typing sound.",
            self.data.get("sound_typewriter", "False") == "True",
            self.on_typewriter_toggled,
        )
        self.cb_trash_vision = create_footer_cb(
            "🗑 Trash Vision",
            "Show the Trash category for deleted snippets",
            self.data.get("trash_vision", "False") == "True",
            self.toggle_trash_vision,
        )
        self.cb_silo_color_box = create_footer_cb(
            "🎨 Silo Color Box",
            "Show the little clickable color box on '#' silos\n"
            "(click to cycle colors, right-click for the full picker)",
            self.data.get("silo_color_box", "True") == "True",
            lambda checked: (
                self.data.update({"silo_color_box": "True" if checked else "False"})
                or self.mark_dirty()
                or self.refresh_temp_presets()
            ),
        )

        div_row = QHBoxLayout()
        div_row.setContentsMargins(0, 0, 0, 0)
        div_row.setSpacing(4)
        lbl_div = QLabel(tr("Line button gaps:", getattr(self, "_current_lang", "EN")))
        lbl_div.setToolTip(tr(
            "Blank lines the Line button and the toolbar divider put around ---.\n"
            "Ctrl+W does NOT read these - it has its own per-scenario spacing in\n"
            "the Ctrl+W... dialog, which is why changing these here did nothing.",
            getattr(self, "_current_lang", "EN")))
        div_row.addWidget(lbl_div)
        self.spin_div_before = QSpinBox()
        self.spin_div_before.setRange(0, 6)
        self.spin_div_before.setToolTip(tr("Lines before ---", getattr(self, "_current_lang", "EN")))
        try:
            self.spin_div_before.setValue(int(self.data.get("divider_lines_before", 2)))
        except (TypeError, ValueError):
            self.spin_div_before.setValue(2)
        self.spin_div_before.valueChanged.connect(
            lambda v: (self.data.update({"divider_lines_before": str(v)}), self.mark_dirty())
        )
        div_row.addWidget(self.spin_div_before)
        self.spin_div_after = QSpinBox()
        self.spin_div_after.setRange(1, 6)
        self.spin_div_after.setToolTip(tr("Lines after --- (before the fresh bullet)", getattr(self, "_current_lang", "EN")))
        try:
            self.spin_div_after.setValue(int(self.data.get("divider_lines_after", 3)))
        except (TypeError, ValueError):
            self.spin_div_after.setValue(3)
        self.spin_div_after.valueChanged.connect(
            lambda v: (self.data.update({"divider_lines_after": str(v)}), self.mark_dirty())
        )
        div_row.addWidget(self.spin_div_after)
        div_row.addStretch(1)

        # ── Smart Ctrl+W — open full dialog ──
        ctrlw_btn_row = QHBoxLayout()
        ctrlw_btn_row.setContentsMargins(0, 0, 0, 0)
        ctrlw_btn_row.setSpacing(4)
        self.btn_ctrlw_settings = QPushButton(tr("Ctrl+W…", getattr(self, "_current_lang", "EN")))
        self.btn_ctrlw_settings.setToolTip(tr(
            "Configure Smart Ctrl+W behavior per context scenario:\n"
            "• Divider insertion and bullet\n"
            "• Blank-line spacing (global or per scenario)\n"
            "• Action when pressing on an existing divider",
            getattr(self, "_current_lang", "EN")))
        self.btn_ctrlw_settings.clicked.connect(self.open_ctrlw_settings)
        ctrlw_btn_row.addWidget(self.btn_ctrlw_settings)
        self.btn_altw_settings = QPushButton(tr("Alt+W…", getattr(self, "_current_lang", "EN")))
        self.btn_altw_settings.setToolTip(tr(
            "Alt+W is Ctrl+W turned around: the new point goes ABOVE the\n"
            "line you are on and the existing text moves down.\n"
            "Same settings, kept separately so the two directions can be\n"
            "tuned apart.",
            getattr(self, "_current_lang", "EN")))
        self.btn_altw_settings.clicked.connect(self.open_altw_settings)
        ctrlw_btn_row.addWidget(self.btn_altw_settings)
        ctrlw_btn_row.addStretch(1)

        files_row = QHBoxLayout()
        files_row.setContentsMargins(0, 0, 0, 0)
        files_row.setSpacing(4)
        self.btn_files_root = QPushButton(tr("Files Folder…", getattr(self, "_current_lang", "EN")))
        self.btn_files_root.setToolTip(tr(
            "Choose where silo file containers are stored.\n"
            "Default: data/files next to the app.",
            getattr(self, "_current_lang", "EN")))
        self.btn_files_root.clicked.connect(self.pick_files_root)
        files_row.addWidget(self.btn_files_root)
        btn_files_root_reset = QPushButton("↺")
        btn_files_root_reset.setToolTip(tr("Reset silo files location to the default data/files", getattr(self, "_current_lang", "EN")))
        btn_files_root_reset.setFixedWidth(24)
        btn_files_root_reset.clicked.connect(self.reset_files_root)
        files_row.addWidget(btn_files_root_reset)
        files_row.addStretch(1)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(QLabel(tr("Volume:", getattr(self, "_current_lang", "EN"))))
        vol_row.addWidget(self.spin_volume)
        vol_row.addStretch(1)

        # Sound settings button
        self.btn_sound_settings = QPushButton(tr("Sound Settings...", getattr(self, "_current_lang", "EN")))
        self.btn_sound_settings.clicked.connect(self.open_sound_settings_dialog)
        self.btn_sound_settings._en_text = "Sound Settings..."
        _sound_btn_tip = ("Every sound the app makes: pick the file, the volume "
                          "and whether it plays at all, per event")
        self.btn_sound_settings.setToolTip(
            tr(_sound_btn_tip, getattr(self, "_current_lang", "EN")))
        self.btn_sound_settings._en_tooltip = _sound_btn_tip

        # CS 1.6 UI style checkbox
        self.cb_cs_style = create_footer_cb(
            "CS 1.6 UI Style",
            "Use Counter-Strike 1.6 style sounds for silo interactions:\n"
            "• Hover: buttonrollover.wav\n"
            "• Click: buttonclick.wav\n"
            "• Release: buttonclickrelease.wav",
            self.data.get("cs_style", "False") == "True",
            self.on_cs_style_toggled,
        )
        self.cb_cs_style._en_text = "CS 1.6 UI Style"
        self.cb_cs_style._en_tooltip = "Use Counter-Strike 1.6 style sounds for silo interactions:\n• Hover: buttonrollover.wav\n• Click: buttonclick.wav\n• Release: buttonclickrelease.wav"

        self.spin_cursor_blink = QSpinBox()
        self.spin_cursor_blink.setRange(0, 2000)
        self.spin_cursor_blink.setSingleStep(50)
        self.spin_cursor_blink.setSuffix(" ms")
        self.spin_cursor_blink.setSpecialValueText(tr("No blink", self._current_lang))
        self.spin_cursor_blink.setToolTip(tr(
            "Cursor blink cycle (ms). 0 = solid, no blink.\n"
            "Default: 530 on Windows.", self._current_lang))
        try:
            self.spin_cursor_blink.setValue(int(self.data.get("cursor_blink_ms",
                                           QApplication.cursorFlashTime())))
        except (TypeError, ValueError):
            self.spin_cursor_blink.setValue(530)
        self.spin_cursor_blink.valueChanged.connect(self._on_cursor_blink_changed)
        blink_row = QHBoxLayout()
        blink_row.setContentsMargins(0, 0, 0, 0)
        blink_row.setSpacing(4)
        blink_row.addWidget(QLabel(tr("Cursor blink:", self._current_lang)))
        blink_row.addWidget(self.spin_cursor_blink)
        blink_row.addStretch(1)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(4)
        lbl_hdr = QLabel(tr("Header Fmt:", getattr(self, "_current_lang", "EN")))
        lbl_hdr.setToolTip(tr(
            "Template for the Ctrl+E header.\n"
            "{text} — the line's text\n{time} — timestamp\n"
            "{state} — Morning / Day / Evening / Night\n"
            "Markdown markers (** __ etc.) are yours to add or drop.",
            getattr(self, "_current_lang", "EN")))
        hdr_row.addWidget(lbl_hdr)
        self.le_hdr_fmt = QLineEdit()
        self.le_hdr_fmt.setPlaceholderText("{text} ({time})")
        self.le_hdr_fmt.setText(self.data.get("ctrl_e_format", "{text} ({time})"))
        self.le_hdr_fmt.textChanged.connect(
            lambda v: (self.data.update({"ctrl_e_format": v}), self.mark_dirty())
        )
        hdr_row.addWidget(self.le_hdr_fmt)
        btn_hdr_edit = QPushButton(tr("Edit…", getattr(self, "_current_lang", "EN")))
        btn_hdr_edit.setToolTip(tr("Open the header format editor (placeholders, presets, live preview)", getattr(self, "_current_lang", "EN")))
        btn_hdr_edit.setFixedWidth(44)
        btn_hdr_edit.clicked.connect(self.open_header_format_editor)
        hdr_row.addWidget(btn_hdr_edit)


        def _settings_group(title, items, min_width=0):
            """A titled box of related controls, wrapping inside itself.

            The tabs used to be one flat flow of every control they owned, so
            "Always on Top" sat beside "Silo Color Box" and the cursor buttons,
            and a row that did not divide evenly left a stripe of dead panel on
            the right. Grouping gives the eye somewhere to land and lets the
            groups themselves flow into the space instead of the gaps.
            """
            box = _SettingsGroupBox()
            box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box.setObjectName("SettingsGroup")
            # Theme-neutral on purpose: a translucent wash reads as a panel
            # on every one of the shipped skins, where a fixed colour would
            # have to be re-picked for each and would go wrong on the next.
            box.setStyleSheet(
                "#SettingsGroup { background: rgba(255,255,255,0.035);"
                " border: 1px solid rgba(255,255,255,0.07); }")
            col = QVBoxLayout(box)
            col.setContentsMargins(5, 2, 5, 3)
            col.setSpacing(1)
            header = QLabel(tr(title, self._current_lang))
            header._en_text = title
            header.setStyleSheet(
                "font-weight: bold; color: #9a8b5f; padding: 0;")
            col.addWidget(header)
            inner = flow_widget(items, h_spacing=10, v_spacing=3)
            if min_width:
                inner.setMinimumWidth(min_width)
            col.addWidget(inner)
            # so a widened group re-flows its contents into fewer rows
            # instead of keeping the tall narrow shape it had at hint width
            box._inner = inner
            box._chrome_h = header.sizeHint().height() + 3 + 2 + 4
            box.setSizePolicy(QSizePolicy.Policy.Preferred,
                              QSizePolicy.Policy.Maximum)
            box._weight = len(items)
            return box

        # --- UI gaps: silo spacing + splitter handle width ---
        gap_row = QHBoxLayout()
        gap_row.setContentsMargins(0, 0, 0, 0)
        gap_row.setSpacing(4)
        lbl_gap = QLabel(tr("UI Gaps:", self._current_lang))
        lbl_gap.setStyleSheet("color: #808080;")
        gap_row.addWidget(lbl_gap)

        self.spin_silo_gap = QSpinBox()
        self.spin_silo_gap.setRange(0, 50)
        self.spin_silo_gap.setToolTip(tr("Silo Gap Height", self._current_lang))
        try:
            self.spin_silo_gap.setValue(int(self.data.get("silo_gap_height", 8)))
        except (TypeError, ValueError):
            self.spin_silo_gap.setValue(8)

        def _update_gap(v):
            self.data.update({"silo_gap_height": str(v)})
            if hasattr(self, "silo_gap_widget"):
                self.silo_gap_widget.setFixedHeight(v)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setFixedHeight(v)
            self.mark_dirty()
            # user-defined gaps (T-590) share this height, so repaint them too
            if self.data.get("silo_gaps"):
                self.refresh_temp_presets()

        self.spin_silo_gap.valueChanged.connect(_update_gap)
        gap_row.addWidget(self.spin_silo_gap)

        self.spin_drag_width = QSpinBox()
        self.spin_drag_width.setRange(1, 50)
        self.spin_drag_width.setToolTip(tr("Splitter Handle Width", self._current_lang))
        try:
            self.spin_drag_width.setValue(int(self.data.get("splitter_width", 1)))
        except (TypeError, ValueError):
            self.spin_drag_width.setValue(1)

        def _update_drag(v):
            self.data.update({"splitter_width": str(v)})
            if hasattr(self, "splitter"):
                self.splitter.setHandleWidth(v)
            self.mark_dirty()

        self.spin_drag_width.valueChanged.connect(_update_drag)
        gap_row.addWidget(self.spin_drag_width)
        gap_row.addStretch(1)

        # --- T-591: mirror silo text onto disk ---
        sync_row = QHBoxLayout()
        sync_row.setSpacing(4)
        lbl_sync = QLabel(tr("Sync to disk:", self._current_lang))
        lbl_sync.setStyleSheet("color: #808080;")
        sync_row.addWidget(lbl_sync)

        self.combo_sync_mode = QComboBox()
        self.combo_sync_mode.addItems(["Off", "Silo", "Hierarchy"])
        self.combo_sync_mode.setToolTip(tr(
            "Off: no mirror.\n"
            "Silo: keep a copy of the current silo on disk.\n"
            "Hierarchy: mirror every silo, children in subfolders.\n"
            "One-way (app to disk) — files are never read back or deleted.",
            self._current_lang))
        mode_now = self.data.get("sync_mode", "Off")
        if mode_now not in ("Off", "Silo", "Hierarchy"):
            mode_now = "Off"
        self.combo_sync_mode.setCurrentText(mode_now)
        self.combo_sync_mode.currentTextChanged.connect(
            lambda m: (self.data.update({"sync_mode": m}), self.mark_dirty(),
                       self.sync_to_disk(force=True)))
        sync_row.addWidget(self.combo_sync_mode)

        self.btn_sync_path = QPushButton(tr("Folder…", self._current_lang))
        self.btn_sync_path.setToolTip(self.data.get("sync_path", "") or tr("No folder chosen", self._current_lang))

        def _pick_sync_path():
            self.ignore_focus_loss = True
            try:
                d = QFileDialog.getExistingDirectory(
                    self, tr("Choose sync folder", self._current_lang),
                    self.data.get("sync_path", "") or "")
            finally:
                self.ignore_focus_loss = False
            if d:
                self.data.update({"sync_path": d})
                self.btn_sync_path.setToolTip(d)
                self.mark_dirty()
                self.sync_to_disk(force=True)

        self.btn_projects_mgr = QPushButton(tr("Projects…", self._current_lang))
        self.btn_projects_mgr.setToolTip(tr(
            "Choose which projects appear in the tab list", self._current_lang))
        self.btn_projects_mgr.clicked.connect(self.open_projects_manager)
        sync_row.addWidget(self.btn_projects_mgr)
        self.btn_sync_path.clicked.connect(_pick_sync_path)
        sync_row.addWidget(self.btn_sync_path)
        sync_row.addStretch(1)

        # --- hover line + line heat tuning ---
        lbl_heat = QLabel(tr("Line tint:", self._current_lang))
        lbl_heat.setStyleSheet("color: #808080;")

        def _pct_spin(key, default, tip, suffix="%"):
            spin = QSpinBox()
            spin.setRange(1, 60)
            spin.setSuffix(suffix)
            spin.setToolTip(tr(tip, self._current_lang))
            try:
                spin.setValue(int(self.data.get(key, default)))
            except (TypeError, ValueError):
                spin.setValue(default)

            def _upd(v):
                self.data.update({key: str(v)})
                self.mark_dirty()
                self.text_area.viewport().update()

            spin.valueChanged.connect(_upd)
            return spin

        self.spin_hover_opacity = _pct_spin(
            "hover_line_opacity", 10, "Hover line opacity")
        self.spin_heat_strength = _pct_spin(
            "line_heat_strength", 18, "Line heat strength")

        self.spin_heat_minutes = QSpinBox()
        self.spin_heat_minutes.setRange(1, 43200)
        self.spin_heat_minutes.setSuffix(tr(" min", self._current_lang))
        self.spin_heat_minutes.setToolTip(tr(
            "How long a line stays tinted after you edit it", self._current_lang))
        try:
            self.spin_heat_minutes.setValue(int(self.data.get("line_heat_minutes", 1440)))
        except (TypeError, ValueError):
            self.spin_heat_minutes.setValue(1440)

        def _upd_minutes(v):
            self.data.update({"line_heat_minutes": str(v)})
            self.mark_dirty()
            self.text_area.viewport().update()

        self.spin_heat_minutes.valueChanged.connect(_upd_minutes)

        self.cb_heat_palette = QComboBox()
        self.cb_heat_palette.setToolTip(tr(
            "Colour spectrum for edited lines.\nAuto follows the theme accent.",
            self._current_lang))
        for label, val in (("Warm", "warm"), ("Cool", "cool"), ("Auto", "accent")):
            self.cb_heat_palette.addItem(tr(label, self._current_lang), val)
        cur_pal = self.data.get("line_heat_palette", "warm")
        pal_idx = self.cb_heat_palette.findData(cur_pal)
        if pal_idx >= 0:
            self.cb_heat_palette.setCurrentIndex(pal_idx)

        def _upd_pal(i):
            self.data.update({"line_heat_palette": self.cb_heat_palette.itemData(i)})
            self.mark_dirty()
            self.text_area.viewport().update()

        self.cb_heat_palette.currentIndexChanged.connect(_upd_pal)

        self.btn_hover_colour = QPushButton(tr("Hover colour", self._current_lang))
        self.btn_hover_colour.setToolTip(tr(
            "Pick the hover highlight colour.\n"
            "Right-click to go back to following the theme.",
            self._current_lang))
        self.btn_hover_colour.clicked.connect(self.pick_hover_colour)
        self.btn_hover_colour.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_hover_colour.customContextMenuRequested.connect(
            lambda _p: self.reset_hover_colour())

        # --- typecheck (typo checker): dictionary underlines, default OFF ---
        self.cb_typo_check = create_footer_cb(
            "✏ Typo check (dictionary)",
            "Underline words the built-in dictionary does not know, with "
            "right-click suggestions and an 'add to dictionary' entry.\n"
            "Off by default. Smart skips: code fences, URLs, identifiers, "
            "acronyms; non-Latin scripts are only judged once the "
            "dictionary covers them.",
            self.data.get("typo_check_enabled", "False") == "True",
            lambda checked: (self.data.update(
                {"typo_check_enabled": "True" if checked else "False"})
                or self.mark_dirty()
                or self._typo_check_tick()),
        )
        self.btn_typo_colour = QPushButton(tr("Underline colour", self._current_lang))
        self.btn_typo_colour.setToolTip(tr(
            "Pick the colour of the typo underlines", self._current_lang))
        self.btn_typo_colour.clicked.connect(self.pick_typo_colour)
        self.btn_typo_colour._en_text = "Underline colour"
        self.btn_typo_colour._en_tooltip = "Pick the colour of the typo underlines"
        self.btn_typo_clear = QPushButton(tr("Clear my words", self._current_lang))
        self.btn_typo_clear.setToolTip(tr(
            "Forget every word you added to the dictionary", self._current_lang))
        self.btn_typo_clear.clicked.connect(self.clear_typo_words)
        self.btn_typo_clear._en_text = "Clear my words"
        self.btn_typo_clear._en_tooltip = "Forget every word you added to the dictionary"

        # --- passed events: the date counter turns red when a set event's
        # time has passed and was not acknowledged (colour is user-pickable)
        self.cb_passed_alert = create_footer_cb(
            "⚠ Passed-event alert",
            "Colour the date/time counter when a calendar event's time has "
            "passed and was not acknowledged — so a missed event is not "
            "forgotten. Right-click the date label to clear it.",
            self.data.get("passed_alert_enabled", "True") == "True",
            lambda checked: (self.data.update(
                {"passed_alert_enabled": "True" if checked else "False"})
                or self.mark_dirty()
                or self._apply_date_alert_style()),
        )
        self.btn_passed_colour = QPushButton(
            tr("Alert colour", self._current_lang))
        self.btn_passed_colour.setToolTip(tr(
            "Colour of the date counter when an event has passed\n"
            "(right-click to reset to the default red)", self._current_lang))
        self.btn_passed_colour.clicked.connect(self.pick_passed_colour)
        self.btn_passed_colour.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_passed_colour.customContextMenuRequested.connect(
            lambda _p: self.reset_passed_colour())
        self.btn_passed_colour._en_text = "Alert colour"
        self.btn_passed_colour._en_tooltip = (
            "Colour of the date counter when an event has passed\n"
            "(right-click to reset to the default red)")

        # --- Sync-Project settings: include/exclude + live behaviour -------
        self.cb_sync_recursive = create_footer_cb(
            "📁 Include subfolders",
            "Watch the whole folder tree (on) or only the top folder (off)",
            self.data.get("sync_recursive", "True") == "True",
            self._save_sync_recursive,
        )
        self.cb_sync_live = create_footer_cb(
            "👁 Watch live",
            "Apply external file changes in real time. Off: the folder is "
            "only read when you convert or re-scan the project.",
            self.data.get("sync_live_watch", "True") == "True",
            lambda checked: (self.data.update(
                {"sync_live_watch": "True" if checked else "False"})
                or self.mark_dirty()
                or self._start_project_watcher()),
        )
        self.spin_sync_max_kb = QSpinBox()
        self.spin_sync_max_kb.setRange(8, 10240)
        self.spin_sync_max_kb.setSuffix(" KB")
        self.spin_sync_max_kb.setToolTip(tr(
            "Files larger than this are not synced", self._current_lang))
        try:
            self.spin_sync_max_kb.setValue(int(self.data.get("sync_max_kb", "512")))
        except (TypeError, ValueError):
            self.spin_sync_max_kb.setValue(512)

        def _upd_sync_max(v):
            self.data.update({"sync_max_kb": str(v)})
            if self._sync_config():
                self._rescan_project_sync()
            self.mark_dirty()

        self.spin_sync_max_kb.valueChanged.connect(_upd_sync_max)
        lbl_sync_max = QLabel(tr("Max file size:", self._current_lang))
        lbl_sync_max._en_text = "Max file size:"

        self.ed_sync_include = QLineEdit(self.data.get("sync_include", ""))
        self.ed_sync_include.setPlaceholderText(".txt .md .py .js …")
        self.ed_sync_include.setToolTip(tr(
            "File extensions treated as text, separated by spaces or commas",
            self._current_lang))
        self.ed_sync_include.setMaximumWidth(360)
        self.ed_sync_include.editingFinished.connect(self._save_sync_include)
        self.ed_sync_include._en_tooltip = (
            "File extensions treated as text, separated by spaces or commas")
        lbl_sync_inc = QLabel(tr("Include extensions:", self._current_lang))
        lbl_sync_inc._en_text = "Include extensions:"

        self.ed_sync_exclude = QLineEdit(self.data.get("sync_exclude", ""))
        self.ed_sync_exclude.setPlaceholderText("node_modules, .git, *.min.js …")
        self.ed_sync_exclude.setToolTip(tr(
            "Names or patterns never synced: directories by name, files via "
            "wildcards (e.g. *.min.js)", self._current_lang))
        self.ed_sync_exclude.setMaximumWidth(360)
        self.ed_sync_exclude.editingFinished.connect(self._save_sync_exclude)
        self.ed_sync_exclude._en_tooltip = (
            "Names or patterns never synced: directories by name, files via "
            "wildcards (e.g. *.min.js)")
        lbl_sync_exc = QLabel(tr("Exclude names/patterns:", self._current_lang))
        lbl_sync_exc._en_text = "Exclude names/patterns:"


        # Tabs instead of three side-by-side columns. Three columns need the
        # full panel width to be readable at all; one tab at a time stays
        # legible in a narrow window, and FlowLayout reflows each tab down to
        # a single column rather than clipping the right-hand side.
        from fastprompter.ui.flow_layout import flow_widget

        def _tab(items):
            """One settings tab: its groups, wrapping and filling the width.

            A plain flow left the right-hand third of the panel empty on
            every tab (measured: the Clock tab used 449px of 956) because a
            flow packs to content width and stops. Fixed columns fixed that
            but demanded 1037px of window - the panel has to survive a narrow
            window too. So the groups wrap like anything else, and the
            leftover width of each row is handed TO the groups on it.
            """
            host = QWidget()
            host.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Maximum)
            outer = QVBoxLayout(host)
            outer.setContentsMargins(4, 4, 4, 4)
            outer.setSpacing(3)
            outer.addWidget(flow_widget(items, h_spacing=6, v_spacing=4,
                                        stretch_items=True))
            return host

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setDocumentMode(True)
        # Never taller than the tab actually needs. QTabWidget expands
        # vertically by default, so in a QVBoxLayout it happily swallowed
        # hundreds of pixels of empty panel below a single row of checkboxes.
        self.settings_tabs.setSizePolicy(QSizePolicy.Policy.Preferred,
                                         QSizePolicy.Policy.Maximum)
        # (attribute, english title) — kept for retranslation
        self._settings_tab_titles = ("Window", "Editor", "Clock", "Data")

        # Toolbar order had its own reset; splitter widths, sidebar side and
        # window size had none, so a window dragged somewhere unusable could
        # only be fixed by deleting the database.
        self.btn_copy_cursors = QPushButton(tr("Copy my set", self._current_lang))
        self.btn_copy_cursors.setToolTip(tr(
            "Copy your current Windows cursors INTO the program.\n"
            "The program then keeps using them even if you change\n"
            "the system scheme later. Press again to re-copy.",
            self._current_lang))
        self.btn_copy_cursors.clicked.connect(lambda: self.capture_cursor_set())

        self.btn_install_cursors = QPushButton(tr("Set in system", self._current_lang))
        self.btn_install_cursors.setToolTip(tr(
            "Install the program's copied set as the Windows default\n"
            "(asks first). Right-click: open the full cursor set online.",
            self._current_lang))
        self.btn_install_cursors.clicked.connect(self.install_cursors_to_system)

        def _cursor_btn_mouse(event):
            if event.button() == Qt.MouseButton.RightButton:
                from fastprompter.ui.cursor_theme import DEVIANTART_URL
                QDesktopServices.openUrl(QUrl(DEVIANTART_URL))
                event.accept()
                return
            QPushButton.mousePressEvent(self.btn_install_cursors, event)

        self.btn_install_cursors.mousePressEvent = _cursor_btn_mouse

        self.btn_reset_layout = QPushButton(tr("Reset UI Layout", self._current_lang))
        self.btn_reset_layout.setToolTip(tr(
            "Put the toolbar, sidebar and window size back to defaults.\n"
            "Text, snippets and silos are not touched.", self._current_lang))
        self.btn_reset_layout.clicked.connect(self.reset_ui_layout)

        # Grouped by what the control DOES, not by the order it happened to
        # be written in. Before this, Window held window behaviour, silo
        # colours, the toolbar switch and the cursor buttons in one
        # undifferentiated row.
        self.settings_tabs.addTab(_tab([
            _settings_group("Window behaviour", [
                self.cb_top, self.cb_lock_window, self.cb_normal_window,
                self.cb_tray,
            ]),
            _settings_group("Layout", [
                self.cb_sidebar, self.cb_customize_toolbar,
                self.cb_numbox_tabs, numbox_row, self.cb_files_dock,
                self.cb_toolbar_bottom, self.btn_reset_layout,
            ]),
            _settings_group("Window presets", [
                self.cb_window_presets, self.btn_manage_presets,
                self.cb_fast_zones, fast_row,
            ]),
            _settings_group("Silo look", [
                self.cb_silo_color_box, self.cb_trash_vision,
            ]),
            _settings_group("Mouse cursors", [
                self.cb_custom_cursors, self.btn_copy_cursors,
                self.btn_install_cursors,
            ]),
        ]), tr("Window", self._current_lang))

        self.settings_tabs.addTab(_tab([
            _settings_group("Dividers & headers", [
                div_row, ctrlw_btn_row, hdr_row, self.cb_hr_visual, self.cb_conceal,
            ]),
            _settings_group("Typing", [
                self.cb_focus, self.cb_wrap, self.cb_ctrl_c,
                self.cb_lock_cursor, self.cb_double_line, blink_row,
            ]),
            _settings_group("Line appearance", [
                self.cb_line_numbers, self.cb_line_marks, self.cb_zebra,
                self.cb_bold_titles, self.lbl_align, self.cb_align_combo,
            ]),
            _settings_group("Line metadata", [
                self.lbl_img_paste, self.cb_img_paste,
                self.cb_token_count, token_row,
            ]),
            # split in two: eight controls in one group stretched to 186px
            # tall beside 49px neighbours, which is the ragged look the panel
            # was reported for
            _settings_group("Line heat", [
                self.cb_line_heat, lbl_heat, self.spin_heat_strength,
                self.spin_heat_minutes, self.cb_heat_palette,
            ]),
            _settings_group("Hover line", [
                self.cb_hover_line, self.spin_hover_opacity,
                self.btn_hover_colour,
            ]),
            _settings_group("Code blocks", [
                self.cb_code_gutter, self.cb_code_monospace,
            ]),
            _settings_group("Typos", [
                self.cb_typo_check, self.btn_typo_colour,
                self.btn_typo_clear,
            ]),
        ]), tr("Editor", self._current_lang))

        # Clock/date settings used to be buried in "Window" — seven of them,
        # which is what made that group unreadable.
        self.settings_tabs.addTab(_tab([
            _settings_group("Clock", [
                self.cb_analog_clock, self.cb_date_rect, self.cb_date_seconds,
                self.cb_date_ampm, self.cb_timer_minutes,
            ]),
            _settings_group("Date", [
                self.cb_date_daypart, self.cb_date_emoji,
                self.cb_date_text_month,
            ]),
            _settings_group("Passed events", [
                self.cb_passed_alert, self.btn_passed_colour,
            ]),
        ]), tr("Clock", self._current_lang))

        self.settings_tabs.addTab(_tab([
            _settings_group("Silo list", [
                self.cb_silo_home, self.cb_silo_pinned_gap, self.cb_silo_ticks,
                self.cb_snippet_arrows, self.cb_hide_shortkeys, gap_row,
                self.lbl_silo_mode, self.cb_silo_mode,
            ]),
            _settings_group("Sound", [
                self.cb_sound, self.cb_typewriter, vol_row,
                self.cb_cs_style, self.btn_sound_settings,
            ]),
            _settings_group("Files & backup", [
                self.cb_portable_backup, files_row, sync_row,
            ]),
            _settings_group("Sync-Project", [
                self.cb_sync_live, self.cb_sync_recursive,
                lbl_sync_max, self.spin_sync_max_kb,
                lbl_sync_inc, self.ed_sync_include,
                lbl_sync_exc, self.ed_sync_exclude,
            ]),
        ]), tr("Data", self._current_lang))

        # A QTabWidget reserves room for its TALLEST page on every tab, so a
        # one-row tab still showed a screenful of nothing. Let only the
        # visible page claim space and re-fit on each switch.
        self.settings_tabs.currentChanged.connect(self._fit_settings_tabs)
        self._fit_settings_tabs(self.settings_tabs.currentIndex())

        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFrameShadow(QFrame.Shadow.Sunken)

        v_layout = QVBoxLayout(self.mini_settings_frame)
        v_layout.setContentsMargins(4, 2, 4, 3)
        v_layout.setSpacing(3)
        v_layout.addWidget(flow_widget(appearance_row, h_spacing=4))
        v_layout.addWidget(hline)
        v_layout.addWidget(self.settings_tabs)

        # Hidden by default — the gear button reveals it
        self.mini_settings_frame.setVisible(self.data.get("hide_extra", "True") != "True")

        # Hug the content: spare vertical space belongs to the editor below,
        # not to a settings panel showing one row of checkboxes.
        self.mini_settings_frame.setSizePolicy(QSizePolicy.Policy.Preferred,
                                               QSizePolicy.Policy.Maximum)
        self.main_layout.addWidget(self.mini_settings_frame)
        # self.main_layout.addWidget(self.left_panel)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.main_layout.addWidget(self.splitter, 1)   # takes all spare height
        self.splitter.setOpaqueResize(True)
        try:
            self.splitter.setHandleWidth(int(self.data.get("splitter_width", 1)))
        except (TypeError, ValueError):
            self.splitter.setHandleWidth(1)

        self.left_panel = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel)
        self.left_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel_layout.setSpacing(0)

        # Files dock: the third splitter pane, always on the side the silo
        # sidebar is NOT on. Empty (and hidden) until the file panel is
        # actually docked into it — the floating drawer is still the default.
        self.files_dock = QWidget()
        self.files_dock_layout = QVBoxLayout(self.files_dock)
        self.files_dock_layout.setContentsMargins(0, 0, 0, 0)
        self.files_dock_layout.setSpacing(0)
        self.files_dock.hide()

        self.snippets_section = QWidget()
        self.snippets_section_layout = QVBoxLayout(self.snippets_section)
        self.snippets_section_layout.setContentsMargins(0, 0, 0, 0)
        self.snippets_section_layout.setSpacing(1)


        self.search_bar = QLineEdit()
        self.search_bar.setToolTip(tr("Search snippets", getattr(self, "_current_lang", "EN")))
        self.search_bar.setPlaceholderText(tr("Search...", getattr(self, "_current_lang", "EN")))
        self.search_bar.setFixedHeight(20)

        saved_search_visible = self.data.get("search_visible", "False") == "True"
        self.btn_toggle_search.setChecked(saved_search_visible)
        self.search_bar.setVisible(saved_search_visible)
        self.btn_toggle_search.toggled.connect(self.on_search_toggle)

        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(150)
        self._search_debounce_timer.timeout.connect(self.refresh_snippets_panel)
        self.search_bar.textChanged.connect(self._search_debounce_timer.start)
        self.snippets_section_layout.addWidget(self.search_bar)

        self.btn_page_up = QPushButton("▲")
        self.btn_page_up.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_page_up.setMinimumWidth(10)
        self.apply_button_size(self.btn_page_up, 16)
        self.btn_page_up.clicked.connect(lambda: self.change_page(-1))
        self.snippets_section_layout.addWidget(self.btn_page_up)

        self.snippets_widget = DropVerticalWidget(self)
        self.snippet_buttons = []
        for _ in range(10):
            w = SnippetWidget(self)
            w.hide()
            self.snippets_widget.layout.addWidget(w)
            self.snippet_buttons.append(w)
        self.snippets_section_layout.addWidget(self.snippets_widget)

        self.btn_page_down = QPushButton("▼")
        self.btn_page_down.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_page_down.setMinimumWidth(10)
        self.apply_button_size(self.btn_page_down, 16)
        self.btn_page_down.clicked.connect(lambda: self.change_page(1))
        self.snippets_section_layout.addWidget(self.btn_page_down)
        self.left_panel_layout.addWidget(self.snippets_section, 0)

        self.archive_section = QWidget()
        self.archive_section.setObjectName("ArchiveSection")
        self.archive_section_layout = QVBoxLayout(self.archive_section)
        self.archive_section_layout.setContentsMargins(0, 0, 0, 0)
        self.archive_section_layout.setSpacing(1)

        arc_header = QHBoxLayout()
        arc_header.setContentsMargins(0, 0, 0, 0)
        self.arc_label = QLabel(tr("Archive", getattr(self, "_current_lang", "EN")))
        arc_header.addWidget(self.arc_label)
        arc_header.addStretch()
        self.archive_section_layout.addLayout(arc_header)

        self.btn_arc_page_up = QPushButton("▲")
        self.apply_button_size(self.btn_arc_page_up, 16)
        self.btn_arc_page_up.clicked.connect(lambda: self.change_arc_page(-1))
        self.archive_section_layout.addWidget(self.btn_arc_page_up)

        self.archive_widget = SiloDropWidget(self, is_archive=True)
        self.archive_buttons = []
        for _ in range(50):
            btn = DraggableSiloButton(self, is_archive=True)
            btn.setMinimumHeight(14)
            btn.hide()
            self.archive_widget.layout.addWidget(btn)
            self.archive_buttons.append(btn)
        self.archive_section_layout.addWidget(self.archive_widget)

        self.btn_arc_page_down = QPushButton("▼")
        self.apply_button_size(self.btn_arc_page_down, 16)
        self.btn_arc_page_down.clicked.connect(lambda: self.change_arc_page(1))
        self.archive_section_layout.addWidget(self.btn_arc_page_down)

        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        self.btn_toggle_archive.setChecked(saved_arc_visible)
        self.archive_section.setVisible(saved_arc_visible)
        self.btn_toggle_archive.toggled.connect(self.on_archive_toggle)

        self.silos_section = QWidget()
        self.silos_section_layout = QVBoxLayout(self.silos_section)
        self.silos_section_layout.setContentsMargins(0, 0, 0, 0)
        self.silos_section_layout.setSpacing(1)

        self.btn_silo_up = QPushButton("▲")
        self.btn_silo_up.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_silo_up.setMinimumWidth(10)
        self.apply_button_size(self.btn_silo_up, 16)
        self.btn_silo_up.clicked.connect(lambda: self.change_silo_page(-1))
        self.silos_section_layout.addWidget(self.btn_silo_up)

        self.silos_widget = SiloDropWidget(self)
        self.silo_buttons = []
        # Create enough silo buttons - _update_visible_silo_count will adjust
        for _ in range(50):
            btn = DraggableSiloButton(self)
            btn.setMinimumHeight(14)
            btn.hide()
            self.silos_widget.layout.addWidget(btn)
            self.silo_buttons.append(btn)
        self.silos_section_layout.addWidget(self.silos_widget)

        self.btn_silo_down = QPushButton("▼")
        self.btn_silo_down.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_silo_down.setMinimumWidth(10)
        self.apply_button_size(self.btn_silo_down, 16)
        self.btn_silo_down.clicked.connect(lambda: self.change_silo_page(1))
        self.silos_section_layout.addWidget(self.btn_silo_down)

        self.sections_gap_widget = QFrame(self)
        self.sections_gap_widget.setFixedHeight(8)
        self.sections_gap_widget.setStyleSheet("margin: 2px 8px; background: transparent;")
        self.sections_gap_widget.hide()
        self.left_panel_layout.addWidget(self.sections_gap_widget)

        self.left_panel_layout.addWidget(self.silos_section, 1)

        # Mouse-wheel paging over the sidebar sections and tabs;
        # Ctrl+wheel walks the silo selection one by one.
        WheelPager(self.silos_section, self.change_silo_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.archive_section, self.change_arc_page, ctrl_callback=self.navigate_silo)
        WheelPager(self.snippets_section, self.change_page)
        WheelPager(self.cat_combo, self._wheel_switch_tab)
        WheelPager(self.cat_numbox, self._wheel_switch_tab)
        wheel_hint = (
            "\nTip: mouse wheel over the list scrolls pages;"
            "\nCtrl+wheel selects the previous/next silo."
        )
        self.btn_silo_up.setToolTip("Previous silo page" + wheel_hint)
        self.btn_silo_down.setToolTip("Next silo page" + wheel_hint)
        self.btn_page_up.setToolTip("Previous snippet page" + wheel_hint)
        self.btn_page_down.setToolTip("Next snippet page" + wheel_hint)
        self.btn_arc_page_up.setToolTip("Previous archive page" + wheel_hint)
        self.btn_arc_page_down.setToolTip("Next archive page" + wheel_hint)
        self.cat_combo.setToolTip(tr("Projects — mouse wheel switches tabs", getattr(self, "_current_lang", "EN")))

        self.archive_section.setParent(self.left_panel)
        self.archive_section.raise_()

        self.silos_section.setVisible(False)
        self.center_panel = QWidget()
        self.center_layout = QVBoxLayout(self.center_panel)
        self.center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_layout.setSpacing(2)

        self.search_frame = QFrame()
        self.search_frame.setObjectName("SearchFrame")
        self.search_frame.setVisible(False)
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(4, 2, 4, 2)
        search_layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Find...", getattr(self, "_current_lang", "EN")))
        self.search_input.returnPressed.connect(self.find_next)
        search_layout.addWidget(self.search_input)

        self.btn_find_prev = QPushButton("◄")
        self.btn_find_prev.setToolTip(tr("Find previous match", getattr(self, "_current_lang", "EN")))
        self.btn_find_prev.clicked.connect(self.find_prev)
        self.apply_button_size(self.btn_find_prev, 24, 24)
        search_layout.addWidget(self.btn_find_prev)

        self.btn_find_next = QPushButton("►")
        self.btn_find_next.setToolTip(tr("Find next match", getattr(self, "_current_lang", "EN")))
        self.btn_find_next.clicked.connect(self.find_next)
        self.apply_button_size(self.btn_find_next, 24, 24)
        search_layout.addWidget(self.btn_find_next)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText(tr("Replace with...", getattr(self, "_current_lang", "EN")))
        search_layout.addWidget(self.replace_input)

        self.btn_replace = QPushButton(tr("Rpl", getattr(self, "_current_lang", "EN")))
        self.btn_replace.setToolTip(tr("Replace the current match", getattr(self, "_current_lang", "EN")))
        self.btn_replace.clicked.connect(self.replace_text)
        self.apply_button_size(self.btn_replace, 24)
        search_layout.addWidget(self.btn_replace)

        self.btn_replace_all = QPushButton(tr("Rpl All", getattr(self, "_current_lang", "EN")))
        self.btn_replace_all.setToolTip(tr("Replace every match in this silo", getattr(self, "_current_lang", "EN")))
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.apply_button_size(self.btn_replace_all, 24)
        search_layout.addWidget(self.btn_replace_all)

        self.btn_close_search = QPushButton("✕")
        self.apply_button_size(self.btn_close_search, 24, 24)
        self.btn_close_search.setToolTip(tr("Close the search bar", getattr(self, "_current_lang", "EN")))
        self.btn_close_search.clicked.connect(self.close_search)
        search_layout.addWidget(self.btn_close_search)

        self.center_layout.addWidget(self.search_frame)

        self.text_area = VaultTextEdit(self)

        self.text_area.installEventFilter(self)
        self.setMouseTracking(True)
        self.highlighter = MarkdownHighlighter(base_font_size=11)
        self.highlighter.setDocument(self.text_area.document())
        self.highlighter.set_skip_large(True)
        self.highlighter.update_hr_as_line(self.data.get("hr_visual_line", "True") == "True")
        self._apply_code_font()
        self._current_lang = get_language(self.data)
        self.apply_wrap_mode()
        self.text_area.setPlaceholderText(tr("Think deeply.", getattr(self, "_current_lang", "EN")))
        self.text_area.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )  # Socratic: Smart visual wrap without corrupting text
        self.text_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Use a debounce timer to avoid text input stutter from cache sync
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(800)
        self._cache_timer.timeout.connect(self._on_cache_timer)
        self.text_area.textChanged.connect(self._on_text_changed)

        self._LARGE_DOC_THRESHOLD = 500000  # chars (raised 100x for large file support)
        self._cache_timer_interval = 800

        try:
            font_size = int(self.data.get("font_size", 11))
        except Exception:
            font_size = 11
        from fastprompter.utils.fonts import no_aa, resolve_family
        font = no_aa(QFont(
            resolve_family(self.data.get("font_family", "Verdana")), font_size))
        self.text_area.setFont(font)

        self.silo_docs = [None] * len(self.data.get("temp_presets", []))
        self.archive_docs = [None] * len(self.data.get("archive_temp_presets", []))

        self.snippet_docs = {}

        from PyQt6.QtWidgets import QStackedWidget
        self.silo_view = QStackedWidget()

        self.text_area_wrapper = QWidget()
        self.text_area_layout = QVBoxLayout(self.text_area_wrapper)
        self.text_area_layout.setContentsMargins(0, 0, 0, 0)
        self.text_area_layout.setSpacing(0)

        self.text_area_layout.addWidget(self.text_area, 1)

        self.preview_area = _PreviewTextEdit()
        self.preview_area.setReadOnly(True)
        self.preview_area.setVisible(False)
        self.preview_area.setFont(font)
        self.text_area_layout.addWidget(self.preview_area, 1)

        self.silo_view.addWidget(self.text_area_wrapper) # page 0

        from fastprompter.ui.kanban_widget import KanbanBoardWidget
        from fastprompter.ui.table_widget import TableGridWidget
        self.kanban_widget = KanbanBoardWidget(self)
        self.kanban_widget.changed.connect(lambda markdown: self._on_visual_widget_changed(markdown))
        self.kanban_widget.undoRequested.connect(self.text_area.undo)
        self.silo_view.addWidget(self.kanban_widget) # page 1

        self.table_widget = TableGridWidget(self)
        self.table_widget.changed.connect(lambda markdown: self._on_visual_widget_changed(markdown))
        self.table_widget.undoRequested.connect(self.text_area.undo)
        # the page has to be re-picked when the TEXT stops matching the type,
        # not only when the silo is switched
        self.text_area.textChanged.connect(self._schedule_silo_type_recheck)
        self.silo_view.addWidget(self.table_widget) # page 2

        self.center_layout.addWidget(self.silo_view, 1)


        # Use custom EdgeResizer instead of QSizeGrip

        # Edge resizers

        self.apply_sidebar_position()
        # The checkbox is built pre-ticked from saved data, which does not
        # fire its callback, so a restart left the cursors stock until the
        # toggle was flipped by hand.
        self.apply_custom_cursors()

        safe_idx = max(0, min(self.data.get("last_tab_idx", 0), self.cat_combo.count() - 1))
        if self.cat_combo.count() > 0:
            self.cat_combo.setCurrentIndex(safe_idx)

        self._trim_archive()
        self.refresh_snippets_panel()
        # Sidebar or tab strip is part of the layout the user left behind,
        # and it moves silos_section, so it has to run before the refresh
        # that measures the panel it now lives in.
        if self.silo_tabs_mode():
            self.apply_silo_tabs_mode(True)
        if self.toolbar_at_bottom():
            self.apply_toolbar_position(True)
        self.refresh_temp_presets()
        QTimer.singleShot(0, lambda: not sip.isdeleted(self) and self._deferred_silo_refresh())
        # a files sidebar left open is part of the layout the user left
        if (self.files_docked()
                and self.data.get("files_dock_open", "False") == "True"):
            QTimer.singleShot(0, lambda: not sip.isdeleted(self)
                              and self.open_file_container())
        self.change_preview_mode(self.preview_combo.currentIndex())
        self.on_tray_toggled(self.cb_tray.isChecked())
        self.set_lock_state(self.cb_lock_window.isChecked())
        self.apply_scaled_ui()
        self.apply_font()

        self.splitter.splitterMoved.connect(self.on_splitter_moved)

        self._silo_resize_debounce_timer = QTimer(self)
        self._silo_resize_debounce_timer.setSingleShot(True)
        self._silo_resize_debounce_timer.setInterval(100)
        self._silo_resize_debounce_timer.timeout.connect(self.refresh_temp_presets)

        self.silos_widget.installEventFilter(self)
        self.left_panel.installEventFilter(self)

    def change_profile(self, idx):
        self.play_sound("profile")
        # W2-002: an armed watcher with a send physically in the air must
        # reach a terminal state BEFORE the outgoing profile's final save.
        # A success arriving after ``self.data`` moved to profile B would
        # otherwise update only abandoned memory while disk kept PENDING —
        # and switching back would resend an already-delivered prompt. The
        # quiesce is bounded and refuses (leaving A fully active) when the
        # send does not resolve; nothing is disarmed mid-send on refusal.
        _weng = getattr(self, "_watcher_engine", None)
        self._watcher_quiesced_for_switch = False
        if _weng is not None and (
                _weng.armed or getattr(self, "_watcher_send_physical_tokens",
                                       None)):
            if not self._watcher_begin_quiesce():
                from fastprompter.core.logging import logger as _wlog
                _wlog.warning("profile switch refused: watcher send still "
                              "in flight after the quiesce bound")
                return
            # W2-001 coordination: we have now PAUSED the watcher run. If the
            # switch is later refused (save/undo/push failure), resume it so
            # profile A stays fully active rather than silently disarmed.
            self._watcher_quiesced_for_switch = True
        self.commit_current_text()
        # MAIN owns the final UI-aware save of the OLD profile — it alone
        # knows the live editor/widget state. The state layer is told NOT to
        # issue its own hidden second save (save_current=False): two owners of
        # pre-switch persistence would double the backup/sync side effects.
        if not self.save_data_to_db(force=True):
            # P0-1: the old profile's final save FAILED — refuse to leave it.
            # A must stay entirely active and dirty; do not touch the DB path
            # or rebind any runtime/UI object.
            from fastprompter.core.logging import logger as _plog
            _plog.error("profile switch aborted: old profile save failed")
            # W2-001: the paused watcher must be resumed, not left silently
            # disarmed/stranded — profile A stays fully active and armed.
            if getattr(self, "_watcher_quiesced_for_switch", False):
                try:
                    self._watcher_rollback_quiesce()
                except Exception:
                    pass
                self._watcher_quiesced_for_switch = False
            return
        # Bound-retire any old-profile undo writer still in flight BEFORE the
        # db path changes, so its captured target is still the old profile's
        # (P0-2: the path is captured pre-thread; this just lets it finish).
        #
        # W2-003: this IS a real pre-switch gate. If the outgoing profile's
        # newest undo snapshot could not be published safely, refuse the switch
        # outright: keep profile A active, retain its in-memory undo/redo
        # stacks, and do NOT call state.switch_profile. Roll the watcher back
        # to its pre-quiesce run when we paused it above.
        if not self._wait_for_undo_saves():
            from fastprompter.core.logging import logger as _ulog
            _ulog.error(
                "profile switch aborted: old-profile undo history could not "
                "be retired safely; old profile kept active")
            if getattr(self, "_watcher_quiesced_for_switch", False):
                try:
                    self._watcher_rollback_quiesce()
                except Exception:
                    pass
                self._watcher_quiesced_for_switch = False
            return

        # CORE-005: the forced save above may have dispatched Sync-Project
        # push jobs that carry the OLD profile's binding ownership. Quiesce the
        # push pipeline BEFORE replacing self.data: an old-profile job that is
        # still in flight when switch_profile() swaps the data would be
        # evaluated against the new profile's aliases (the per-category stores
        # are themselves per-profile). Require a truthful idle; on timeout keep
        # the old profile fully active rather than risking a cross-profile
        # mutation.
        if not self._wait_for_push_idle(timeout_s=5.0):
            from fastprompter.core.logging import logger as _plog
            _plog.warning(
                "profile switch refused: Sync-Project push did not drain "
                "within the bound; old profile kept active")
            # W2-001: resume the paused watcher — the switch was refused, so
            # profile A and its exact watcher run must remain active.
            if getattr(self, "_watcher_quiesced_for_switch", False):
                try:
                    self._watcher_rollback_quiesce()
                except Exception:
                    pass
                self._watcher_quiesced_for_switch = False
            return

        # W2-001: do NOT teardown old-profile runtime before the state switch
        # succeeds. The File Container, timer jobs and toasts stay alive while
        # the switch is tentative; they are torn down only after State has
        # atomically moved to B.
        try:
            self.state.switch_profile(idx + 1, save_current=False)
        except Exception:
            # W2-001: switch failed — resume the paused watcher so profile A
            # stays fully active (mirror of the undo/push refusal path).
            if getattr(self, "_watcher_quiesced_for_switch", False):
                try:
                    self._watcher_rollback_quiesce()
                except Exception:
                    pass
                self._watcher_quiesced_for_switch = False
            raise
        # W2-001: the enclosing transaction committed — perform the
        # irreversible watcher disarm now (the pause we took before the
        # switch is only resolved on success).
        if getattr(self, "_watcher_quiesced_for_switch", False):
            try:
                self._watcher_commit_quiesce()
            except Exception:
                pass
        self._watcher_quiesced_for_switch = False

        # State is now on B — safe to detach old-profile runtime.
        if hasattr(self, "_file_container") and self._file_container:
            self._file_container.detach_session()

        self._cancel_timer_test_jobs()
        try:
            from fastprompter.ui.timer_toast import TimerToast
            TimerToast.close_for_main(self)
        except Exception:
            pass
        # The final old-profile mirror snapshot is dispatched immediately (not
        # dropped) here; the new profile's mirror starts with a fresh cache.
        self._sync_on_profile_change()
        self.data = self.state.data
        visible = self.visible_categories()
        idx = min(self.data.get("last_tab_idx", 0), max(0, len(visible) - 1))
        cat = visible[idx] if visible else "Text"
        # the new profile's data came straight from JSON, so int-keyed maps
        # arrive stringified — normalise before anything indexes them
        self._normalise_int_keys("silo_last_edited_all")
        self._normalise_int_keys("silo_children_all")
        self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(cat, {})

        # Rebuild document caches for the new profile
        self.silo_docs = [None] * len(self.data.get("temp_presets", []))
        self.archive_docs = [None] * len(self.data.get("archive_temp_presets", []))
        self.snippet_docs.clear()

        # Rebind every profile-owned runtime object (data-derived state,
        # persisted undo, sound, language, widget values, hotkeys, watcher)
        # from the ACTIVE profile's data — one shared path, no per-profile
        # boot code duplicated here.
        self._apply_profile_runtime_state()

        # Re-populate UI
        self.silo_page = 0
        self.arc_silo_page = 0
        self.btn_toggle_archive.setChecked(False)
        self.refresh_temp_presets()
        self.build_categories()
        self.text_area.document().clearUndoRedoStacks()

        # Back to the silo this project was left on — including the archive,
        # which used to be dropped on every start. Falls back to the old global
        # active_temp_slot for a database written before silo_session_all.
        session = self._silo_session()
        if "slot" not in session:
            try:
                session["slot"] = int(self.data.get("active_temp_slot", 0))
            except (TypeError, ValueError):
                session["slot"] = 0
        slot_val = self.restore_silo_session()
        self._switch_to_slot(slot_val, initial=True,
                             is_archive=getattr(self, "active_is_archive", False))

        # Category selection contract: build_categories() above already
        # populated the combo from visible_categories() (category name as
        # itemData) and selected index 0 = the FIRST VISIBLE project, firing
        # on_tab_changed exactly once. There is no persisted per-profile
        # "last active project", so the first visible project IS the
        # contract — addressed by combo identity (_cat_at -> itemData), never
        # by a raw cats_order row index (hidden projects shift visible
        # indices). This used to be a fake "Switch to Text category" loop
        # whose condition included cats_order[0], so it always re-selected
        # row 0 and re-fired on_tab_changed — dead code, removed.

        # A File Container panel still pointed at the OLD profile's folder must
        # not keep showing it — worse, a drop into a stale panel would land in
        # the previous profile's silo folder. Rebind an open panel to the new
        # profile's active silo; a closed one stays closed.
        panel = getattr(self, "_file_container", None)
        if panel is not None and not sip.isdeleted(panel):
            was_open = panel.isVisible()
            dock = getattr(self, "files_dock", None)
            if (not was_open and self.files_docked()
                    and dock is not None and not dock.isHidden()):
                was_open = True
            if was_open:
                self.open_file_container()
            else:
                panel.hide()
                panel.folder = ""

    def _apply_profile_runtime_state(self):
        """Rebind every profile-owned runtime object from the ACTIVE self.data.

        This is the ONE profile-runtime application path: startup calls it at
        the end of construction, and ``change_profile`` calls it after the DB
        switch, so a persisted setting can never silently become
        "startup-only profile state". Widgets are NEVER rebuilt; values are
        re-stamped with signals blocked so no handler can write the previous
        profile's widget state into the new profile's data (the
        save_data_to_db() widget-read leak), then runtime effects are applied
        from the new values.

        It also fail-closes automation: an armed watcher from the old profile
        is disarmed here, and native hotkeys are re-registered so only the
        ACTIVE profile's keys are live.
        """
        data = self.data

        # -- data-derived runtime objects ----------------------------------
        from fastprompter.core.pomodoro import ProductivityTimer
        from fastprompter.core.timers import load_timers
        from fastprompter.core.watcher.queue import load_queues
        self.timers = load_timers(data.get("timers"))
        self.prompt_queues = load_queues(data.get("watcher_queues"))
        self.productivity_timer = ProductivityTimer.from_dict(
            data.get("productivity_timer"))
        self._pomo_last_tick = None

        # -- persisted undo for THIS profile --------------------------------
        self._undo_kinds().clear()
        self._load_undo_state()

        # -- sound ownership -------------------------------------------------
        self.sound_manager._data = data
        from fastprompter.core.sound_manager import migrate_sound_settings
        migrate_sound_settings(data, self.sound_manager._sounds_dir)

        # -- language --------------------------------------------------------
        self._current_lang = get_language(data)
        self._apply_tooltips()
        self._retranslate_preview_combo(self._current_lang)
        self._apply_settings_language()

        # -- persisted widget values -> widgets ------------------------------
        self._resync_profile_widgets()

        # -- font / theme ----------------------------------------------------
        self.apply_font()
        self.apply_theme()

        # -- hotkeys: the old profile's native registrations must die --------
        self.unregister_all_hotkeys()
        self.register_all_hotkeys()

        # -- watcher: fail closed; do NOT auto-arm ----------------------------
        # Observe mode is a separate loop from arming: disarming only stops the
        # SEND engine, it does NOT stop an in-progress Observe. Switching
        # profiles must stop BOTH so a Profile-A adapter/probes/timer cannot
        # survive into Profile B (W-09/P1). No auto-restart in the new profile.
        if hasattr(self, "watcher_stop_observing"):
            self.watcher_stop_observing()
        self.watcher_disarm("profile switch")

        # -- profile-scoped runtime state -------------------------------------
        # The missed-event alert, the typecheck dictionary cache and the
        # sync "last applied" baselines all belong to ONE profile's data;
        # the sync watcher paths are re-derived from the new profile's
        # active category below. Guarded: at startup this runs BEFORE the
        # attributes are created (they are made at the end of __init__).
        if hasattr(self, "_missed_timer_ids"):
            self._missed_timer_ids.clear()
        if hasattr(self, "_typo_dict_cache"):
            self._typo_dict_cache = None
        if hasattr(self, "_sync_last_applied"):
            self._sync_last_applied.clear()
        self._start_project_watcher()

    def _resync_profile_widgets(self):
        """Re-stamp persisted widget values from the active profile's data.

        Every value that save_data_to_db() reads from a widget (font_size,
        preview_mode, tray_visible, close_on_focus_loss, ctrl_c_closes) must
        already equal the active profile's data BEFORE any save — otherwise
        saving profile B would write profile A's widget values into B. Signals
        are blocked while re-stamping so handlers cannot write stale values
        back; handlers with a live runtime effect are then re-applied from the
        new value.
        """
        data = self.data

        # (widget attr, data key, data default) — the full persisted checkbox
        # inventory created from self.data in the settings panel. A future
        # widget-backed persisted setting MUST be added here, or it silently
        # becomes "startup-only profile state" (P2-19 registry guard).
        _CHECKS = (
            ("cb_top", "always_on_top", "True"),
            ("cb_lock_window", "window_locked", "False"),
            ("cb_normal_window", "normal_window", "False"),
            ("cb_tray", "tray_visible", "True"),
            ("cb_sidebar", "sidebar_right", "False"),
            ("cb_custom_cursors", "custom_cursors", "False"),
            ("cb_focus", "close_on_focus_loss", "True"),
            ("cb_snippet_arrows", "snippet_arrows", "False"),
            ("cb_silo_ticks", "silo_ticks_enabled", "False"),
            ("cb_ctrl_c", "ctrl_c_closes", "True"),
            ("cb_lock_cursor", "lock_to_cursor", "False"),
            ("cb_customize_toolbar", "customize_toolbar", "False"),
            ("cb_numbox_tabs", "numbox_tabs", "False"),
            ("cb_window_presets", "window_presets_enabled", "True"),
            ("cb_files_dock", "file_panel_docked", "False"),
            ("cb_toolbar_bottom", "toolbar_position", "top"),
            ("cb_fast_zones", "fancyzones_fast", "False"),
            ("cb_silo_home", "silo_home", "False"),
            ("cb_portable_backup", "portable_backup_enabled", "True"),
            ("cb_wrap", "word_wrap", "True"),
            ("cb_line_heat", "line_heat", "False"),
            ("cb_hover_line", "hover_line", "True"),
            ("cb_code_monospace", "code_monospace", "True"),
            ("cb_line_numbers", "show_line_numbers", "False"),
            ("cb_code_gutter", "code_auto_gutter", "False"),
            ("cb_line_marks", "line_marks", "False"),
            ("cb_token_count", "show_token_count", "False"),
            ("cb_zebra", "zebra_lines", "False"),
            ("cb_hide_shortkeys", "hide_shortkeys", "False"),
            ("cb_double_line", "bullet_double_line", "False"),
            ("cb_bold_titles", "bold_hash_titles", "False"),
            ("cb_silo_pinned_gap", "silo_pinned_gap", "False"),
            ("cb_conceal", "live_preview_conceal", "False"),
            ("cb_hr_visual", "hr_visual_line", "True"),
            ("cb_date_rect", "show_date_rect", "True"),
            ("cb_timer_minutes", "timer_show_minutes", "False"),
            ("cb_date_seconds", "date_seconds", "False"),
            ("cb_analog_clock", "analog_clock", "False"),
            ("cb_date_daypart", "date_daypart", "False"),
            ("cb_date_emoji", "date_emoji", "True"),
            ("cb_date_text_month", "date_text_month", "False"),
            ("cb_date_ampm", "date_ampm", "False"),
            ("cb_sound", "sound_ui", "True"),
            ("cb_typewriter", "sound_typewriter", "False"),
            ("cb_trash_vision", "trash_vision", "False"),
            ("cb_silo_color_box", "silo_color_box", "False"),
            ("cb_cs_style", "cs_style", "False"),
            ("cb_typo_check", "typo_check_enabled", "False"),
            ("cb_passed_alert", "passed_alert_enabled", "True"),
            ("cb_sync_recursive", "sync_recursive", "True"),
            ("cb_sync_live", "sync_live_watch", "True"),
        )
        for attr, key, default in _CHECKS:
            w = getattr(self, attr, None)
            if w is None or sip.isdeleted(w):
                continue
            if key == "toolbar_position":
                value = data.get(key, default) == "bottom"
            else:
                value = data.get(key, default) == "True"
            w.blockSignals(True)
            try:
                w.setChecked(value)
            finally:
                w.blockSignals(False)

        # Combos/spins whose value save_data_to_db() reads or applies live.
        if hasattr(self, "font_spin") and not sip.isdeleted(self.font_spin):
            try:
                size = int(float(data.get("font_size", 11)))
            except (TypeError, ValueError):
                size = 11
            self.font_spin.blockSignals(True)
            self.font_spin.setValue(size)
            self.font_spin.blockSignals(False)
        if hasattr(self, "font_combo") and not sip.isdeleted(self.font_combo):
            saved = data.get("font_family", "Verdana")
            if self.font_combo.findText(saved) >= 0:
                self.font_combo.blockSignals(True)
                self.font_combo.setCurrentText(saved)
                self.font_combo.blockSignals(False)
        if hasattr(self, "preview_combo") and not sip.isdeleted(self.preview_combo):
            _view_map = {"None": "Source View", "Raw": "Source View",
                         "Markdown": "Reading"}
            saved = data.get("preview_mode", "Live Preview")
            saved = _view_map.get(saved, saved)
            idx = self.preview_combo.findData(saved)
            if idx < 0:
                idx = 1  # default to Live Preview
            self.preview_combo.blockSignals(True)
            self.preview_combo.setCurrentIndex(idx)
            self.preview_combo.blockSignals(False)
        if hasattr(self, "cb_theme") and not sip.isdeleted(self.cb_theme):
            idx = self.cb_theme.findText(data.get("theme", "Default"))
            if idx >= 0:
                self.cb_theme.blockSignals(True)
                self.cb_theme.setCurrentIndex(idx)
                self.cb_theme.blockSignals(False)

        # Live runtime effects, applied from the NEW values. Handlers are
        # idempotent (they re-write the same data value) — exactly what a
        # user toggle would do, but programmatic.
        if hasattr(self, "cb_tray") and not sip.isdeleted(self.cb_tray):
            self.on_tray_toggled(data.get("tray_visible", "True") == "True")
        if hasattr(self, "cb_top") and not sip.isdeleted(self.cb_top):
            self.toggle_aot(data.get("always_on_top", "True") == "True")
        if hasattr(self, "cb_lock_window") and not sip.isdeleted(self.cb_lock_window):
            self.set_lock_state(data.get("window_locked", "False") == "True")
        if hasattr(self, "cb_normal_window") and not sip.isdeleted(self.cb_normal_window):
            self.apply_window_flags()
        if hasattr(self, "cb_sidebar") and not sip.isdeleted(self.cb_sidebar):
            self.toggle_sidebar_position(data.get("sidebar_right", "False") == "True")
        if hasattr(self, "cb_wrap") and not sip.isdeleted(self.cb_wrap):
            self.on_wrap_toggled(data.get("word_wrap", "True") == "True")
        if hasattr(self, "cb_line_numbers") and not sip.isdeleted(self.cb_line_numbers):
            self.set_line_numbers(data.get("show_line_numbers", "False") == "True")
        if hasattr(self, "cb_numbox_tabs") and not sip.isdeleted(self.cb_numbox_tabs):
            self._toggle_numbox_mode(data.get("numbox_tabs", "False") == "True")
        if hasattr(self, "cb_toolbar_bottom") and not sip.isdeleted(self.cb_toolbar_bottom):
            self.apply_toolbar_position(data.get("toolbar_position", "top") == "bottom")
        if hasattr(self, "cb_files_dock") and not sip.isdeleted(self.cb_files_dock):
            self._on_files_dock_toggled(data.get("file_panel_docked", "False") == "True")
        if hasattr(self, "cb_lock_cursor") and not sip.isdeleted(self.cb_lock_cursor):
            self.on_lock_cursor_toggled(data.get("lock_to_cursor", "False") == "True")
        if hasattr(self, "cb_silo_home") and not sip.isdeleted(self.cb_silo_home):
            self.on_silo_home_toggled(data.get("silo_home", "False") == "True")
        if hasattr(self, "cb_customize_toolbar") and not sip.isdeleted(self.cb_customize_toolbar):
            self.on_customize_toolbar_toggled(
                data.get("customize_toolbar", "False") == "True")
        # Custom cursors: apply SILENTLY (the toggle handler can pop a modal
        # capture dialog — not allowed during a programmatic switch).
        if hasattr(self, "apply_custom_cursors"):
            self.apply_custom_cursors()
        # Preview mode effect, from the re-stamped combo (itemData is the
        # single source of truth).
        if hasattr(self, "preview_combo") and not sip.isdeleted(self.preview_combo):
            self.change_preview_mode(self.preview_combo.currentIndex())

    def insert_timestamp_at_end(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = " " if cursor.block().text().strip() else ""
        cursor.insertText(f"{prefix}{ts}")
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def open_header_format_editor(self):
        """Open the comprehensive Ctrl+E header template editor."""
        from fastprompter.ui.header_format_dialog import HeaderFormatDialog
        prev = getattr(self, "ignore_focus_loss", False)
        self.ignore_focus_loss = True
        try:
            HeaderFormatDialog(self).exec()
        finally:
            self.ignore_focus_loss = prev

    def open_ctrlw_settings(self, upward=False):
        """Open the per-scenario Smart Line dialog.

        `upward` is Alt+W: the same page against its own key set, because
        the two directions are tuned apart.
        """
        from fastprompter.ui.ctrlw_settings import CtrlWSettingsDialog
        prev = getattr(self, "ignore_focus_loss", False)
        self.ignore_focus_loss = True
        try:
            CtrlWSettingsDialog(
                self, prefix="altw" if upward else "ctrlw", upward=upward).exec()
        finally:
            self.ignore_focus_loss = prev

    def open_altw_settings(self):
        """Open the Alt+W (upward Smart Line) dialog."""
        self.open_ctrlw_settings(upward=True)

    @staticmethod
    def _has_header_above(block):
        """True if any earlier line in this silo is already a '# ' header."""
        b = block.previous()
        while b.isValid():
            if b.text().lstrip().startswith("#"):
                return True
            b = b.previous()
        return False

    def _strip_header_line(self, cursor, sel):
        """Turn a header line back into plain text. True if it did.

        Removes the hashes, the trailing timestamp the header was stamped
        with, and any centring, so the line is genuinely plain again rather
        than plain-looking but still centred.
        """
        import re as _re

        from fastprompter.ui.editor import TS_STAMP_LINE_RE

        stripped = sel.strip()
        marker = _re.match(r"^(#{1,6})\s+", stripped)
        if not marker:
            return False

        body = stripped[marker.end():]
        # the stamp this feature appends, with or without its brackets
        body = _re.sub(r"\s*\(" + TS_STAMP_LINE_RE.pattern + r"\)\s*$", "", body)
        body = _re.sub(r"\s*" + TS_STAMP_LINE_RE.pattern + r"\s*$", "", body)
        body = body.strip()

        # Remove from centered_blocks tracking so reload doesn't re-center
        old_block_text = cursor.block().text()
        if old_block_text:
            try:
                centered = json.loads(self.data.get("centered_blocks", "[]"))
                if old_block_text in centered:
                    centered.remove(old_block_text)
                    self.data["centered_blocks"] = json.dumps(centered)
            except (json.JSONDecodeError, ValueError):
                self.data["centered_blocks"] = "[]"

        cursor.insertText(body)
        plain = QTextBlockFormat()
        plain.setAlignment(Qt.AlignmentFlag.AlignLeft)
        QTextCursor(cursor.block()).mergeBlockFormat(plain)

        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontUnderline(False)
        line = QTextCursor(cursor.block())
        line.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        line.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                          QTextCursor.MoveMode.KeepAnchor)
        line.mergeCharFormat(fmt)
        self.mark_dirty()
        return True

    def apply_header_timestamp(self):
        """Ctrl+E: Apply user-defined header formatting and timestamp at end of current line."""
        cursor = self.text_area.textCursor()
        # keep_view replaces a narrower guard that only restored the scroll
        # when the reflow landed on EXACTLY 0 — a reflow that merely moved the
        # view a few hundred pixels was left alone, which is the other half of
        # "the view jumps around when I format".
        from fastprompter.ui.edit_guard import keep_view

        with keep_view(self.text_area):
            with edit_block(cursor, self.text_area):
                self._apply_header_timestamp_locked(cursor)

    def _apply_header_timestamp_locked(self, cursor):
        """Body of apply_header_timestamp, run inside one undo step."""
        # Select entire line
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        sel = cursor.selectedText()

        if not sel.strip():
            return

        template = self.data.get("ctrl_e_format", "{text} ({time})")

        try:
            from fastprompter.ui.header_format_dialog import LEGACY_TEMPLATE_MIGRATION
            if template in LEGACY_TEMPLATE_MIGRATION:
                template = LEGACY_TEMPLATE_MIGRATION[template]
                self.data["ctrl_e_format"] = template
                self.mark_dirty()
        except ImportError:
            pass

        full_template = template if template.startswith("# ") else f"# {template}"

        # Pressing Ctrl+E on a line that is ALREADY a header strips it back to plain
        import re as _hdr_re
        _stripped = sel.strip()
        if _hdr_re.match(r"^(#{1,6})\s+", _stripped):
            _next_block = cursor.block().next()
            # Ctrl+E on a header takes the header off, whatever is below it.
            # It used to add a --- instead when there was none, which broke
            # the toggle: with the rule switched off in settings, the key
            # could no longer undo its own work.
            # Try to match the stamped format first to extract just the text
            stamped_pattern = re.escape(full_template)
            stamped_pattern = stamped_pattern.replace(re.escape("{text}"), r"(.*?)")
            stamped_pattern = stamped_pattern.replace(re.escape("{time}"), r".*?")
            stamped_pattern = stamped_pattern.replace(re.escape("{state}"), r".*?")
            stamped_pattern = f"^{stamped_pattern}$"
            stamped_match = re.match(stamped_pattern, _stripped)
            if stamped_match:
                _clean_sel = stamped_match.group(1)
            else:
                # Fallback: extract text before timestamp pattern " (..."
                fallback_match = re.match(r"^#\s*(.+?)\s+\(.*?\)$", _stripped)
                if fallback_match:
                    _clean_sel = fallback_match.group(1).strip()
                else:
                    # Last resort: just strip the header marker
                    _clean_sel = _hdr_re.sub(r"^(#{1,6})\s+", "", _stripped, count=1).strip()
            plain = QTextCharFormat()
            cursor.insertText(_clean_sel, plain)
            # Clear any center alignment from the block when reverting
            plain_block = QTextBlockFormat()
            plain_block.setAlignment(Qt.AlignmentFlag.AlignLeft)
            cursor.mergeBlockFormat(plain_block)
            # Remove horizontal rule if it exists on the next line
            if _next_block.isValid() and re.match(r"^\s*-{3,}\s*$", _next_block.text()):
                cursor.setPosition(_next_block.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.deleteChar()
                # Also remove the second newline if it exists
                _after_rule = cursor.block().next()
                if _after_rule.isValid() and not _after_rule.text().strip():
                    cursor.setPosition(_after_rule.position())
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
            self.mark_dirty()
            return

        pattern = re.escape(full_template)
        pattern = pattern.replace(re.escape("{text}"), r"(.*?)")
        pattern = pattern.replace(re.escape("{time}"), r".*?")
        pattern = pattern.replace(re.escape("{state}"), r".*?")
        pattern = f"^{pattern}$"

        m = re.match(pattern, sel)
        if m:
            clean_sel = m.group(1)
            plain = QTextCharFormat()
            cursor.insertText(clean_sel, plain)
            # Clear any center alignment from the block when reverting
            plain_block = QTextBlockFormat()
            plain_block.setAlignment(Qt.AlignmentFlag.AlignLeft)
            cursor.mergeBlockFormat(plain_block)
            # Remove horizontal rule if it exists on the next line
            _next_block = cursor.block().next()
            if _next_block.isValid() and re.match(r"^\s*-{3,}\s*$", _next_block.text()):
                cursor.setPosition(_next_block.position())
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                # Remove the extra newline that remains
                cursor.deleteChar()
            self.mark_dirty()
            return



        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 12: daypart = "Morning"
        elif 12 <= h < 17: daypart = "Day"
        elif 17 <= h < 22: daypart = "Evening"
        else: daypart = "Night"

        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        ts = now.strftime(f"{m_fmt} - {self._clock_time_fmt()}")

        # {state} in the template takes over the day word; otherwise the
        # legacy behavior prefixes it inside {time} when Day Word is on
        if "{state}" in template:
            time_str = ts
        else:
            time_str = f"{daypart} {ts}" if self.data.get("date_daypart", "True") == "True" else ts

        # Strip any existing header hashes or list bullets so they don't get trapped
        clean_sel = re.sub(r'^(?:#+\s*|[-*•●+]\s+)+', '', sel).strip()
        if not clean_sel:
            clean_sel = sel.strip()

        # By default only the FIRST header in a silo carries the timestamp —
        # it dates the note, and every later header is just a section marker.
        # "Stamp every header" in the settings turns that off.
        cfg = header_core.read_settings(self.data)
        # Ctrl+E on a line that was ALREADY a bullet turns that bullet into
        # the header — it does not also leave a fresh empty bullet under it.
        # Pressing it on an item in the middle of a list used to cut the list
        # in half with a stray "• " the user then had to delete by hand; the
        # line they pressed it on is the one they wanted to become a title.
        if re.match(r'^\s*[-*•●+]\s+', sel):
            cfg = {**cfg, "bullet": False}
        if self._has_header_above(cursor.block()) and not cfg["stamp_every"]:
            formatted_text = f"# {clean_sel}"
        else:
            formatted_text = header_core.header_line(
                template, clean_sel, time_str, daypart)

        cursor.insertText(formatted_text)

        # Save header info for centering and persistence. Centering must
        # happen AFTER the bullet insert below — QTextCursor.insertText()
        # inherits the current block's QTextBlockFormat into any new block
        # it creates via \n, so centering before the bullet would leak
        # center alignment onto the empty lines and the bullet point.
        want_center = cfg["align"] == "center"
        hdr_block_number = cursor.block().blockNumber()
        hdr_text = cursor.block().text()

        # Everything under the title comes from core/header.build_block, so
        # the settings preview and this insert cannot drift apart. It used
        # to be a hardcoded "\n---\n" plus a four-way search for blank lines
        # to reuse; the reuse made the result depend on what happened to sit
        # below the cursor, which is exactly why the shape was unpredictable.
        roles = header_core.build_block_roles(cfg, "")
        below = [line for line, _r in roles[1:]]
        plain = QTextCharFormat()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.setCharFormat(plain)
        if below:
            cursor.insertText("\n" + "\n".join(below), plain)

        # Align each line of the block by what it IS — title, rule or bullet
        # — now that they all exist. Done afterwards on purpose: a block
        # created by \n inherits the previous block's QTextBlockFormat, so
        # aligning as we go would smear the title's alignment down the gap
        # and onto whatever the user types next.
        doc = self.text_area.document()
        for offset, (_line, role) in enumerate(roles):
            align = header_core.align_of(cfg, role)
            if align == "left":
                continue
            blk = doc.findBlockByNumber(hdr_block_number + offset)
            if blk.isValid():
                bfmt = QTextBlockFormat()
                bfmt.setAlignment(_ALIGN_FLAGS[align])
                QTextCursor(blk).mergeBlockFormat(bfmt)

        # Land on the bullet. It used to be the last line written, so the
        # insert left the caret there by itself; with a gap or a closing
        # rule configured below it, the caret would be stranded at the
        # bottom of the block instead of on the line to type on.
        caret_blk = doc.findBlockByNumber(
            hdr_block_number + header_core.caret_line(cfg))
        if caret_blk.isValid():
            cursor.setPosition(caret_blk.position() + len(caret_blk.text()))
        # Only centring is persisted: centered_blocks is a list of block
        # texts the loader re-centres, and it has no room for a direction.
        if want_center:
            if hdr_text:
                try:
                    centered = json.loads(self.data.get("centered_blocks", "[]"))
                    if hdr_text and hdr_text not in centered:
                        centered.append(hdr_text)
                        self.data["centered_blocks"] = json.dumps(centered)
                except (json.JSONDecodeError, ValueError):
                    self.data["centered_blocks"] = "[]"

        self.text_area.setTextCursor(cursor)
        self.text_area.setCurrentCharFormat(plain)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

    def _retranslate_preview_combo(self, lang):
        """Set each View-combo item's display text from its English itemData.

        itemData stays English (the lookup key); only the visible label is
        localized. Translating from the base — not the current display text —
        is what lets the combo recover when you switch away from a language
        whose script it can't reverse-map (e.g. Arabic -> grandpa/RU)."""
        combo = getattr(self, "preview_combo", None)
        if combo is None or sip.isdeleted(combo):
            return
        combo.blockSignals(True)
        for i in range(combo.count()):
            base = combo.itemData(i) or combo.itemText(i)
            combo.setItemText(i, tr(base, lang))
        combo.blockSignals(False)

    def _on_language_changed(self, lang):
        """Handle language combo change: persist and refresh UI text."""
        if lang == self._current_lang:
            return
        self._current_lang = lang
        self.data["language"] = lang
        self.mark_dirty()
        self._apply_settings_language()

    def _apply_settings_language(self):
        """Re-apply translations to all settings widgets."""
        lang = self._current_lang
        # Translate _settings_group headers — find the header QLabels in mini_settings_frame
        for child in self.mini_settings_frame.findChildren(QLabel):
            en = getattr(child, "_en_text", None) or child.text()
            # Only translate known labels (those that are group headers or static labels)
            translated = tr(en, lang)
            if translated != en:
                child.setText(translated)

        # Translate all checkboxes in the settings panel
        for cb_name in ("cb_top", "cb_lock_window", "cb_normal_window", "cb_tray",
                        "cb_sidebar", "cb_focus", "cb_snippet_arrows", "cb_silo_ticks",
                        "cb_ctrl_c", "cb_lock_cursor", "cb_silo_home", "cb_portable_backup",
                        "cb_wrap", "cb_line_numbers", "cb_line_marks", "cb_zebra", "cb_hide_shortkeys",
                        "cb_double_line", "cb_bold_titles", "cb_silo_pinned_gap",
                        "cb_date_rect", "cb_date_seconds", "cb_analog_clock",
                        "cb_date_daypart", "cb_date_emoji", "cb_date_text_month", "cb_date_ampm", "cb_sound",
                        "cb_typewriter", "cb_trash_vision", "cb_silo_color_box",
                        "cb_typo_check", "cb_passed_alert", "cb_sync_recursive",
                        "cb_sync_live"):
            cb = getattr(self, cb_name, None)
            if cb is not None and not sip.isdeleted(cb):
                en_text = getattr(cb, "_en_text", None)
                if en_text:
                    cb.setText(tr(en_text, lang))
                en_tip = getattr(cb, "_en_tooltip", None)
                if en_tip:
                    cb.setToolTip(tr(en_tip, lang))

        # Translate action buttons
        for ac_name in ("btn_hotkeys", "btn_colors", "btn_backup", "btn_restore",
                        "btn_typo_colour", "btn_typo_clear", "btn_passed_colour"):
            ac = getattr(self, ac_name, None)
            if ac is not None and not sip.isdeleted(ac):
                en_text = getattr(ac, "_en_text", None)
                if en_text:
                    ac.setText(tr(en_text, lang))

        # Translate button_scale text (has dynamic percentage)
        if hasattr(self, "btn_button_scale") and not sip.isdeleted(self.btn_button_scale):
            try:
                pct = int(float(self.data.get("ui_scale", "0.5")) * 100)
            except Exception:
                pct = 100
            self.btn_button_scale.setText(f"{tr('Scale', lang)}: {pct}%")

        # Translate static labels
        static_labels = [
            "Font:", "Theme:", "View:",
            "Language:", "Volume:", "Line gaps:",
            "Header Fmt:",
            "Window", "Editor",
            "Data && Appearance", "Data & Appearance"
        ]
        from fastprompter.core.translations import _DATA
        rev_data = {v: k for k, v in _DATA.items()}
        for child in self.mini_settings_frame.findChildren(QLabel):
            txt = child.text()
            en_txt = rev_data.get(txt, txt)
            if en_txt in static_labels:
                child.setText(tr(en_txt, lang))

        # Translate spinbox tooltips
        if hasattr(self, "spin_div_before") and not sip.isdeleted(self.spin_div_before):
            self.spin_div_before.setToolTip(tr("Lines before ---", lang))
        if hasattr(self, "spin_div_after") and not sip.isdeleted(self.spin_div_after):
            self.spin_div_after.setToolTip(tr("Lines after --- (before the fresh bullet)", lang))
        if hasattr(self, "btn_ctrlw_settings") and not sip.isdeleted(self.btn_ctrlw_settings):
            self.btn_ctrlw_settings.setText(tr("Ctrl+W…", lang))
            self.btn_ctrlw_settings.setToolTip(tr(
                "Configure Smart Ctrl+W behavior per context scenario:\n"
                "• Divider insertion and bullet\n"
                "• Blank-line spacing (global or per scenario)\n"
                "• Action when pressing on an existing divider", lang))
        if hasattr(self, "spin_volume") and not sip.isdeleted(self.spin_volume):
            self.spin_volume.setToolTip(tr("Click sound volume (1-10)", lang))

        # Translate files_row buttons
        if hasattr(self, "btn_files_root") and not sip.isdeleted(self.btn_files_root):
            self.btn_files_root.setText(tr("Files Folder...", lang))
            self.btn_files_root.setToolTip(
                tr("Choose where silo file containers are stored.\nDefault: data/files next to the app.", lang))

        # Translate preview combo items from their English base (itemData),
        # never from the current — possibly already-translated — display text.
        if hasattr(self, "preview_combo") and not sip.isdeleted(self.preview_combo):
            self._retranslate_preview_combo(lang)
            self.preview_combo.setToolTip(
                tr("Source View: Plain text editor\nLive Preview: Editor with live markdown highlights (default)\nReading: Read-only rendered markdown view", lang))

        # Translate _day_part used in _update_date_label
        self._update_date_label()

        # Translate sidebar tooltips
        for attr_name, en_val, tip_attr in (
            ("btn_trash", "Open Trash", "toolTip"),
            ("btn_arc_snip", "Archive Active Snippet or Silo", "toolTip"),
            ("btn_toggle_archive", "Toggle Archives", "toolTip"),
            ("search_bar", "Search snippets", "toolTip"),
            ("search_bar", "Search...", "placeholderText"),
        ):
            wdg = getattr(self, attr_name, None)
            if wdg is not None and not sip.isdeleted(wdg):
                if tip_attr == "toolTip":
                    wdg.setToolTip(tr(en_val, lang))
                elif tip_attr == "placeholderText":
                    wdg.setPlaceholderText(tr(en_val, lang))

        # Re-apply hotkey tooltips (cheat sheet on Keys button)
        if hasattr(self, '_apply_tooltips'):
            self._apply_tooltips()

        # T-404: Live FULL-UI retranslation for header buttons
        btn_configs = [
            ("btn_sidebar_toggle", None, "Toggle Sidebar (Alt+D)\nShow or hide the right/left sidebar containing snippets and silos.", None),
            ("btn_new", "NEW", "NEW ({})", "hk_new_snippet"),
            ("btn_save", "Save", "Save ({})", "hk_save_snippet"),
            ("btn_home", "Home", "Home (Home)", None),
            ("btn_end", "End", "Jump to End\nMove cursor to the bottom of the document.", None),
            ("btn_add_line", "Line", "Insert Line (Ctrl+W)\nInsert a spaced --- divider and start a fresh bullet.", None),
            ("btn_bold", "B", "Bold ({})\nMake selected text bold.", "hk_bold"),
            ("btn_italic", "I", "Italic ({})\nMake selected text italic.", "hk_italic"),
            ("btn_under", "U", "Underline ({})\nMake selected text underlined.", "hk_underline"),
            ("btn_strike", "S", "Strikethrough (Ctrl+T)\nCross out selected text.", None),
            ("btn_header", "H", "Header (Ctrl+E)\nTitle the line: # + bold + underline + timestamp,\nthen land 2 lines below on a fresh bullet.", None),
            ("btn_clear_fmt", "Clear Fmt", "Clear Format\nRemove all explicit font styling from text.", None),
            ("btn_settings_toggle", None, "Settings\nConfigure hotkeys, theme, fonts, and UI scaling.", None),
            ("btn_settings_toggle_right", None, "Settings\nConfigure hotkeys, theme, fonts, and UI scaling.", None),
            ("btn_help", None, "Help — every hotkey, gesture and feature (click)", None),
            ("btn_copy", "Copy", "Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter", None),
            ("btn_clear", "Clear", "Clear (Ctrl+Shift+C)", None),
            ("btn_files", None, "Files\nAsset drawer for the active silo: drop any files in,\ndrag them out, preview, export. Stored as a plain folder\nin data/files — readable outside FastPrompter.", None),
            ("btn_project_run", None, "Run Executable", None),
            ("btn_project_folder", None, "Open Project Folder", None),
            ("btn_trash", None, "Open Trash", None),
            ("btn_arc_snip", None, "Archive Active Snippet or Silo", None),
            ("btn_toggle_archive", None, "Toggle Archives", None),
        ]

        for attr_name, text_base, tip_base, hk_key in btn_configs:
            btn = getattr(self, attr_name, None)
            if btn is not None and not sip.isdeleted(btn):
                if text_base:
                    btn.setText(tr(text_base, lang))
                if tip_base:
                    if hk_key:
                        btn.setToolTip(tr(tip_base, lang).format(self.data.get(hk_key, "")))
                    else:
                        btn.setToolTip(tr(tip_base, lang))

        if hasattr(self, "btn_bullet_toggle") and not sip.isdeleted(self.btn_bullet_toggle):
            state_str = tr("ON", lang) if self.data.get("auto_bullet", "False") == "True" else tr("OFF", lang)
            tt = tr("Auto-Bullet (Right-Click): {}\nLeft-Click: Convert selected lines between dashes and bullets.", lang)
            self.btn_bullet_toggle.setToolTip(tt.format(state_str))

        if hasattr(self, "retranslate_tray"):
            self.retranslate_tray()
        if hasattr(self, "_file_container") and self._file_container and not sip.isdeleted(self._file_container):
            if hasattr(self._file_container, "set_language"):
                self._file_container.set_language(lang)

    def on_splitter_moved(self, pos, index):
        is_right = getattr(self, "_sidebar_right", False)
        self.data["splitter_sizes_right" if is_right else "splitter_sizes_left"] = self.splitter.sizes()
        self.mark_dirty()

    def open_drop_zones_settings(self):
        from fastprompter.ui.drop_overlay import DropZonesDialog
        dlg = DropZonesDialog(self)
        self._increment_focus_lock()
        try:
            dlg.exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)

    def swap_temp_slots(self, idx1, idx2, is_archive=False):
        if idx1 == idx2:
            return
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap temp slots")
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= idx1 < len(temps) and 0 <= idx2 < len(temps)):
            return

        from PyQt6.QtGui import QTextDocument

        while len(docs) <= max(idx1, idx2):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            if len(docs) < len(temps):
                d.setPlainText(temps[len(docs)])
            docs.append(d)

        self._suspend_cache = True
        temps[idx1], temps[idx2] = temps[idx2], temps[idx1]
        docs[idx1], docs[idx2] = docs[idx2], docs[idx1]

        if getattr(self, "active_is_archive", False) == is_archive:
            if getattr(self, "active_temp_slot", -1) == idx1:
                self.active_temp_slot = idx2
            elif getattr(self, "active_temp_slot", -1) == idx2:
                self.active_temp_slot = idx1
        # Both spaces: the archive used to swap TEXT only and left its folders
        # and queues on the old slot (T-754).
        self._remap_silo_indices(lambda i: idx2 if i == idx1 else idx1 if i == idx2 else i,
                                 is_archive=is_archive)
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_archive:
            self.refresh_archive_panel()

    def _rebind_visible_lists(self, temp=None, archive=None):
        """Rebind data['temp_presets']/['archive_temp_presets'] AND the
        per-category backing store together — DB saves and tab switches read
        from temp_presets_all, so a bare rebind orphans the data."""
        cat = self.get_current_category()
        if temp is not None:
            self.data["temp_presets"] = temp
            if cat and "temp_presets_all" in self.data:
                self.data["temp_presets_all"][cat] = temp
        if archive is not None:
            self.data["archive_temp_presets"] = archive
            if cat and "archive_temp_presets_all" in self.data:
                self.data["archive_temp_presets_all"][cat] = archive

    # Every piece of state keyed by SILO SLOT INDEX, and how it is shaped.
    # A silo has no stable id — it is identified purely by its position — so
    # any reorder/insert/delete has to rewrite ALL of these in lockstep.
    # Miss one and a silo silently inherits another's colour, pin, files or
    # cursor. Keeping the list here (and asserting it in a test) is what
    # stops the next map from being forgotten.
    #   int_list   : [3, 7]                 -> values are indices
    #   int_dict   : {3: v}                 -> int keys
    #   str_dict   : {"3": v}               -> stringified int keys
    #   parent_map : {"3": [4, 5]}          -> both key and values are indices
    # The optional third element names the KEY NAMESPACE for a str_dict:
    #   "numeric"  : keys are plain slot numbers ("3")
    #   "a"        : keys are archive-prefixed ("a3")
    # watcher_queues is DUAL-namespaced — normal silos own "N", archived silos
    # own "aN" — so it is registered in BOTH tables with its own namespace and
    # a remap never touches the other space's keys (T-754).
    _SILO_INDEX_STATE = (
        # {slot: [item, ...]} on purpose - the same shape as silo_colors, so
        # reordering or deleting silos remaps the queues through the existing
        # str_dict handling instead of needing code of its own.
        ("watcher_queues", "str_dict", "numeric"),
        ("silo_last_edited", "int_dict"),
        ("pinned_silos", "int_list"),
        ("silo_ticked", "int_list"),
        ("silo_collapsed", "int_list"),
        ("silo_children", "parent_map"),
        ("silo_colors", "str_dict", "numeric"),
        ("silo_folders", "str_dict", "numeric"),
        ("silo_project_paths", "str_dict", "numeric"),
        ("silo_types", "str_dict", "numeric"),
        # T-704 reverses T-593's carve-out, by the user's own call. Leaving
        # silo_gaps out produced the WORST of both readings, not the
        # positional one it was aiming for: the gap is stored as a slot
        # index, so a reorder moved it along with its silo anyway, while a
        # delete or an insert renumbered every slot around it and parked it
        # under a stranger. A gap now belongs to the silo it was placed
        # under and is remapped with everything else — put one under
        # "bravo" and it stays under "bravo".
        ("silo_gaps", "int_list"),
        ("silo_gap_names", "str_dict", "numeric"),
        # per-silo file link (single file) and Sync-Project slot->file map:
        # both follow the silo's identity through reorder/delete/undo
        ("silo_links", "str_dict", "numeric"),
        ("project_sync_map", "str_dict", "numeric"),
    )

    # The archive is its own index space with its own slot-keyed stores.
    # Reordering archived silos used to move only the TEXT, leaving these
    # behind — an archived silo would inherit another one's files folder.
    # watcher_queues here carries the "aN" half of the dual namespace, so an
    # archive reorder/delete/insert follows the queue along with the text.
    _ARCHIVE_INDEX_STATE = (
        ("archive_silo_folders", "str_dict", "numeric"),
        ("archive_project_paths", "str_dict", "numeric"),
        ("watcher_queues", "str_dict", "a"),
    )

    # Every per-CATEGORY store (defined in core.state so it is testable
    # Qt-free). rename_category / del_category move or delete the whole set in
    # lockstep; a store left off this list keeps its data under the OLD project
    # name after a rename, or leaves an orphan behind after a delete (T-758).
    # The invariant test asserts the registry covers every live *_all key.
    _PER_CATEGORY_STATE_KEYS = _PER_CATEGORY_STATE_KEYS

    # Maximum number of silos per category across BOTH index spaces. Slots
    # are 0..MAX_SILOS_PER_CATEGORY-1. This is a hard persistence contract:
    # the DB stores temp_presets_v2 / archive_temp_presets_v2 with slot < 100,
    # categories[cat] is a fixed [None]*100 list, and temp_presets_all is
    # truncated to this length on load. EVERY insertion path must obey it
    # through the single canonical boundary below — never an ad-hoc
    # `if len(...) < 100`, never a silent `pop()` eviction of another silo.
    MAX_SILOS_PER_CATEGORY = 100

    # -- canonical capacity boundary -------------------------------------
    # One place that decides WHERE a silo may be created and whether it may be
    # created at all. Used by every insert/duplicate/child/archive/transfer/
    # restore path so the 100-slot invariant has exactly one implementation.
    def _silo_capacity(self, is_archive=False):
        key = "archive_temp_presets" if is_archive else "temp_presets"
        return len(self.data.get(key) or [])

    def _silo_at_capacity(self, is_archive=False):
        return self._silo_capacity(is_archive) >= self.MAX_SILOS_PER_CATEGORY

    def _slot_has_identity(self, idx, is_archive=False):
        """Whether slot idx owns any identity-bearing entry (CORE-003)."""
        table = self._ARCHIVE_INDEX_STATE if is_archive else self._SILO_INDEX_STATE
        for entry in table:
            key, kind = entry[0], entry[1]
            ns = entry[2] if len(entry) > 2 else "numeric"
            container = getattr(self, key, None) if key == "silo_last_edited" else self.data.get(key)
            if container is None:
                continue
            if kind == "int_list":
                if isinstance(container, list) and idx in container:
                    return True
            elif kind == "int_dict":
                if isinstance(container, dict) and (idx in container or str(idx) in container):
                    return True
            elif kind == "str_dict":
                if not isinstance(container, dict):
                    continue
                if ns == "a":
                    if f"a{idx}" in container:
                        return True
                else:
                    if str(idx) in container:
                        return True
            elif kind == "parent_map":
                if not isinstance(container, dict):
                    continue
                if idx in container:
                    return True
                for kids in container.values():
                    if isinstance(kids, (list, tuple)) and idx in kids:
                        return True
        view = self.data.get("silo_view_state_all")
        if isinstance(view, dict):
            cat = self.get_current_category()
            entries = view.get(cat) if isinstance(view.get(cat), dict) else None
            if isinstance(entries, dict) and f"{'a' if is_archive else 's'}{idx}" in entries:
                return True
        return False

    def _slot_is_pristine(self, idx, is_archive=False):
        return not self._slot_has_identity(idx, is_archive)

    def _acquire_silo_slot(self, is_archive=False, allow_reuse_empty=True):
        """The ONE canonical insertion boundary.

        Returns the slot index a new silo may occupy, or ``None`` if the
        insertion must be REFUSED (space full and no reusable empty slot).

        When ``allow_reuse_empty`` is True an existing blank slot is preferred
        over growing the list, so callers never implicitly evict another
        silo's data. The returned slot is the index to insert at / reuse; it
        never mutates any existing slot or its state, and it never removes a
        silo to make room. Callers must refuse (without touching the source)
        when this returns ``None``.

        This is the only place that understands the 100-slot limit.
        """
        key = "archive_temp_presets" if is_archive else "temp_presets"
        presets = self.data.get(key) or []
        if allow_reuse_empty:
            for i, p in enumerate(presets):
                if not (p or "").strip() and self._slot_is_pristine(i, is_archive):
                    return i
        if len(presets) >= self.MAX_SILOS_PER_CATEGORY:
            return None
        return len(presets)

    def _remove_silo_view_key(self, idx, is_archive=False):
        """Forget the deleted slot's saved cursor/view state before any remap."""
        store = self.data.get("silo_view_state_all")
        if not isinstance(store, dict):
            return
        entries = store.get(self.get_current_category())
        if not isinstance(entries, dict):
            return
        entries.pop(("a" if is_archive else "s") + str(idx), None)

    def _remove_silo_index_key(self, idx, is_archive=False):
        """Drop the DELETED slot's own key from every slot-index-keyed store
        BEFORE any remap runs.

        The delete remap maps the deleted slot and its successor onto the
        SAME key; which survives then depends on dict insertion order, so a
        deleted silo's colour/queue/type could resurrect over its successor
        (or the successor's data could be lost). Removing the deleted key
        first turns the remap into a clean down-shift with no collision —
        identical results regardless of dictionary order. Shared by every
        deletion path through drop_silo_state (P0-4)."""
        table = self._ARCHIVE_INDEX_STATE if is_archive else self._SILO_INDEX_STATE
        skey = str(idx)
        akey = "a" + skey
        for entry in table:
            key = entry[0]
            kind = entry[1]
            namespace = entry[2] if len(entry) > 2 else "numeric"
            container = getattr(self, key, None) if key == "silo_last_edited" else None
            if not isinstance(container, dict):
                container = self.data.get(key)
            if container is None:
                continue
            if kind in ("str_dict", "int_dict"):
                if namespace == "a":
                    container.pop(akey, None)
                else:
                    container.pop(idx, None)
                    container.pop(skey, None)
        self._remove_silo_view_key(idx, is_archive=is_archive)

    def drop_silo_state(self, idx, is_archive=False):
        """Slot `idx` is going away: forget its state, pull the rest up one.

        The membership lists need the slot REMOVED, not remapped — a remap
        lambda cannot express "delete", and leaving `idx` pinned would pin
        whichever silo slid into its place. The keyed stores are safe to
        remap: `idx` and `idx + 1` both land on `idx` and the survivor wins.

        Lives here so that every path which removes a silo shares it. It used
        to be written out inside del_silo, and move_preset_cross_category —
        dragging a silo into a snippet category — did not do it at all, so the
        silo list shifted while the colours, types and project paths stayed on
        their old numbers.
        """
        if not is_archive:
            pinned = self.data.get("pinned_silos", [])
            if isinstance(pinned, list) and idx in pinned:
                pinned.remove(idx)
            ticked = self.data.get("silo_ticked", [])
            if isinstance(ticked, list) and idx in ticked:
                ticked.remove(idx)
            cmap = self.data.get("silo_children", {})
            if isinstance(cmap, dict):
                cmap.pop(idx, None)     # deleting a parent promotes its children
                for kids in cmap.values():
                    if idx in kids:
                        kids.remove(idx)
            collapsed = self.data.get("silo_collapsed", [])
            if isinstance(collapsed, list) and idx in collapsed:
                collapsed.remove(idx)
            # the gap belonged to THIS silo (T-704), so it leaves with it —
            # remapping alone would hand it to whoever slides into the slot
            gaps = self.data.get("silo_gaps", [])
            if isinstance(gaps, list) and idx in gaps:
                gaps.remove(idx)
                names = self.data.setdefault("silo_gap_names_all", {}).setdefault(self.get_current_category(), {})
                if str(idx) in names:
                    del names[str(idx)]
                self.data["silo_gap_names"] = names
        # remove the deleted slot's OWN dict keys before the down-shift so the
        # remap cannot collide the deleted entry with its successor (P0-4)
        self._remove_silo_index_key(idx, is_archive=is_archive)
        self._remap_silo_indices(lambda i: i - 1 if i > idx else i,
                                 is_archive=is_archive)

    def open_silo_slot(self, idx, is_archive=False):
        """A silo is being inserted at `idx`: push everything from there down."""
        self._remap_silo_indices(lambda i: i + 1 if i >= idx else i,
                                 is_archive=is_archive)

    def _remap_silo_indices(self, remap, is_archive=False):
        """Apply an index remap to every slot-index-keyed store.

        Mutates in place: these containers are aliases into per-category
        stores, so rebinding them would orphan the data."""
        table = self._ARCHIVE_INDEX_STATE if is_archive else self._SILO_INDEX_STATE
        for entry in table:
            key = entry[0]
            kind = entry[1]
            namespace = entry[2] if len(entry) > 2 else "numeric"
            # `silo_last_edited` is also exposed as an attribute, and callers
            # (including tests) sometimes REBIND that attribute rather than
            # mutating it — at which point it is no longer the same object as
            # data[...]. The attribute is what the app actually reads, so it
            # wins; see the temp_presets aliasing trap for the same hazard.
            container = getattr(self, key, None) if key == "silo_last_edited" else None
            if not isinstance(container, dict):
                container = self.data.get(key)
            if container is None:
                continue
            try:
                if kind == "int_list":
                    if isinstance(container, list):
                        # W2-002: filter invalid members per-element so one bad
                        # entry cannot abort the whole valid remap; valid ints
                        # still shift correctly.
                        cleaned = []
                        for i in container:
                            if isinstance(i, int) and i >= 0:
                                try:
                                    cleaned.append(remap(i))
                                except Exception:
                                    cleaned.append(i)
                        container[:] = cleaned
                elif kind == "int_dict":
                    if isinstance(container, dict):
                        moved = {remap(k): v for k, v in container.items()}
                        container.clear()
                        container.update(moved)
                elif kind == "str_dict":
                    if isinstance(container, dict):
                        moved = {}
                        for k, v in container.items():
                            if namespace == "a":
                                # archive-namespaced: only "aN" keys move
                                if isinstance(k, str) and k[:1] == "a" and k[1:].isdigit():
                                    try:
                                        moved["a" + str(remap(int(k[1:])))] = v
                                        continue
                                    except (TypeError, ValueError):
                                        pass
                            elif isinstance(k, int) or (isinstance(k, str) and k.lstrip("-").isdigit()):
                                # normal-namespaced: only plain slot numbers move
                                try:
                                    moved[str(remap(int(k)))] = v
                                    continue
                                except (TypeError, ValueError):
                                    pass
                            moved[k] = v   # foreign-namespace or junk key: as-is
                        container.clear()
                        container.update(moved)
                elif kind == "parent_map":
                    if isinstance(container, dict):
                        moved = {}
                        for parent, kids in container.items():
                            try:
                                new_parent = remap(int(parent))
                            except (TypeError, ValueError):
                                new_parent = parent
                            moved[new_parent] = [remap(int(k)) for k in kids]
                        container.clear()
                        container.update(moved)
            except Exception:
                from fastprompter.core.logging import logger
                logger.warning("failed to remap silo state %r", key)

        # keep data in step when the attribute is a separate object
        if not is_archive:
            attr = getattr(self, "silo_last_edited", None)
            stored = self.data.get("silo_last_edited")
            if isinstance(attr, dict) and isinstance(stored, dict) and attr is not stored:
                stored.clear()
                stored.update(attr)

        self._remap_silo_view_state(remap, is_archive=is_archive)

    def _remap_silo_view_state(self, remap, is_archive=False):
        """View state has its own shape: per category, keys like 's3'/'a3'.

        Only the half being reordered moves — shuffling active silos must
        not disturb the archive's saved cursors, and vice versa.
        """
        store = self.data.get("silo_view_state_all")
        if not isinstance(store, dict):
            return
        cat = self.get_current_category()
        entries = store.get(cat)
        if not isinstance(entries, dict):
            return
        prefix = "a" if is_archive else "s"
        moved = {}
        for key, value in entries.items():
            if isinstance(key, str) and key[:1] == prefix and key[1:].isdigit():
                try:
                    moved[f"{prefix}{remap(int(key[1:]))}"] = value
                    continue
                except (TypeError, ValueError):
                    pass
            moved[key] = value
        entries.clear()
        entries.update(moved)

    def handle_pinned_drop(self, source_idx, boundary_idx=None, swap_idx=None):
        """Reorder the pinned section by drag and drop.

        Every index is looked up defensively: this runs from a drop event,
        where the payload can name a silo that was pinned when the drag
        started but isn't any more, or the silo itself. Dropping something
        onto itself used to remove it and then look it up again, which threw
        ValueError straight out of the event handler and killed the app.
        """
        pinned = self._slot_list("pinned_silos")

        def commit(changed):
            if changed:
                self.mark_dirty()
                self.refresh_temp_presets()
            return changed

        if swap_idx is not None:
            if source_idx == swap_idx:
                return False                     # onto itself: nothing to do
            if source_idx in pinned and swap_idx in pinned:
                i1, i2 = pinned.index(source_idx), pinned.index(swap_idx)
                pinned[i1], pinned[i2] = pinned[i2], pinned[i1]
                return commit(True)
            return False

        if boundary_idx is not None:
            if source_idx == boundary_idx:
                return False                     # onto itself: nothing to do
            if boundary_idx in pinned:
                # work out WHERE before mutating, or removing the source can
                # invalidate the boundary we are about to look up
                target = pinned.index(boundary_idx)
                if source_idx in pinned:
                    current = pinned.index(source_idx)
                    pinned.pop(current)
                    if current < target:
                        target -= 1              # list shifted under us
                pinned.insert(min(target, len(pinned)), source_idx)
                return commit(True)
            if source_idx in pinned:
                pinned.remove(source_idx)        # dropped outside the section
                return commit(False)
            return False

        if source_idx in pinned:
            pinned.remove(source_idx)
            return commit(False)
        return False

    def move_temp_to_index(self, from_idx, to_idx, is_archive=False):
        """Move a silo to a new position, shifting the others (drop 'between' silos)."""
        if from_idx == to_idx:
            return
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        docs = self.archive_docs if is_archive else self.silo_docs
        if not (0 <= from_idx < len(temps)):
            return
        to_idx = max(0, min(len(temps) - 1, to_idx))
        if from_idx == to_idx:
            return
        self.add_data_undo_state("Move silo")

        from PyQt6.QtGui import QTextDocument

        while len(docs) <= max(from_idx, to_idx):
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            if len(docs) < len(temps):
                d.setPlainText(temps[len(docs)])
            docs.append(d)

        self._suspend_cache = True
        temps.insert(to_idx, temps.pop(from_idx))
        docs.insert(to_idx, docs.pop(from_idx))

        def remap(i):
            if i == from_idx:
                return to_idx
            if from_idx < to_idx and from_idx < i <= to_idx:
                return i - 1
            if to_idx < from_idx and to_idx <= i < from_idx:
                return i + 1
            return i

        if getattr(self, "active_is_archive", False) == is_archive:
            self.active_temp_slot = remap(getattr(self, "active_temp_slot", 0))
        self._remap_silo_indices(remap, is_archive=is_archive)
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        if is_archive:
            self.refresh_archive_panel()

    def _recalc_native_frame(self):
        """Make Windows re-compute the non-client area after a style change.

        Turning "Normal Window" on set WS_CAPTION correctly on the very first
        click — measured — and yet no title bar appeared: the window rect and
        the client rect stayed identical, because Windows does not recompute
        the frame just because the style word changed. The caption only
        showed up on the NEXT toggle, which is the "it takes three clicks"
        report. SWP_FRAMECHANGED is the message that forces the recompute.
        """
        try:
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                int(self.winId()), 0, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("could not force a frame recalculation", exc_info=True)

    def _restore_frame_position(self, frame_before, client_size):
        """Put the window back where it was, measured by its FRAME.

        Neither naive restore works on its own: setGeometry pins the CLIENT,
        so gaining a caption pushes the whole window down by its height, and
        move() pins the FRAME, so losing the caption pulls it up. Both walked
        the window across the screen a step per toggle — measured +4/+23 one
        way and -4 the other. Anchoring the frame and deriving the client
        offset from the margins the new frame actually has keeps it still.
        """
        from PyQt6.QtCore import QRect
        margins = self.frameGeometry()
        client = self.geometry()
        dx = client.left() - margins.left()
        dy = client.top() - margins.top()
        target = QRect(frame_before.left() + dx, frame_before.top() + dy,
                       client_size.width(), client_size.height())
        if target == client:
            return
        self.setGeometry(target)

    def apply_window_flags(self, _=None):
        self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"
        self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"
        flags = Qt.WindowType.Window
        normal = self.cb_normal_window.isChecked()
        if not normal:
            flags |= Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        # Skip HWND recreation if flags haven't actually changed
        current = self.windowFlags()
        # Strip WindowStaysOnTopHint from comparison — AOT handled separately via SetWindowPos
        current_stripped = current & ~Qt.WindowType.WindowStaysOnTopHint
        if current_stripped == flags:
            # Only AOT state may differ — handle via SetWindowPos
            if self._always_on_top:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001
                    )
                except Exception:
                    pass
            return
        self.unregister_all_hotkeys()
        was_visible = self.isVisible()
        # setWindowFlags recreates the native window; the resulting
        # activation-change would trigger the click-out auto-hide and make
        # the toggle look broken. Suppress it until the dust settles.
        self._increment_focus_lock()
        geo = self.geometry()
        frame_before = self.frameGeometry()
        # Anti-flashbang: the recreated native window first paints with the
        # default (white) background brush before the stylesheet kicks in.
        # Paint it in the theme's window color instead.
        m_bg = re.search(
            r"QWidget\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{3,8})",
            QApplication.instance().styleSheet(),
        )
        if m_bg:
            from PyQt6.QtGui import QPalette
            pal = self.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor(m_bg.group(1)))
            self.setPalette(pal)
            self.setAutoFillBackground(True)
        self.setUpdatesEnabled(False)
        self.hide()  # explicit hide forces a clean native-frame rebuild
        self.setWindowFlags(flags)
        self.setWindowTitle("FastPrompter")
        self.setGeometry(geo)
        if was_visible:
            self.show()
            self.setUpdatesEnabled(True)
            self._recalc_native_frame()
            # let Qt learn the new frame margins before they are read back
            QApplication.processEvents()
            self._restore_frame_position(frame_before, geo.size())
            self.repaint()
            self.raise_()
            self.activateWindow()
        else:
            self.setUpdatesEnabled(True)
            # New native handle: re-assert always-on-top on it
            if self._always_on_top and not normal:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        int(self.winId()), -1, 0, 0, 0, 0, 0x0002 | 0x0001
                    )
                except Exception:
                    pass
        QTimer.singleShot(300, self._decrement_focus_lock)
        self.register_all_hotkeys()
        self.mark_dirty()

    def _remap_snippet_owner(self, cat, remap):
        """W2-001: after a structural snippet move/rename, keep the live
        editor owner and its cached QTextDocument pointing at the SAME
        logical object.

        ``remap(old_index)`` returns the new index for a snippet that
        stayed in ``cat``, or None when that snippet left this collection
        (its cached doc is dropped / editing is exited).
        """
        es = getattr(self, "editing_snippet", None)
        if es and es[0] == cat:
            new_i = remap(es[1])
            if new_i is None:
                self.cancel_editing()
            else:
                self.editing_snippet = (cat, new_i)
                self.btn_save.setText(
                    tr("Update", getattr(self, "_current_lang", "EN")))
        docs = getattr(self, "snippet_docs", {})
        prefix = cat + "_"
        for k in list(docs.keys()):
            if not k.startswith(prefix):
                continue
            try:
                i = int(k[len(prefix):])
            except ValueError:
                continue
            new_i = remap(i)
            if new_i is None:
                del docs[k]
            elif new_i != i:
                docs[f"{cat}_{new_i}"] = docs.pop(k)

    def move_preset_to_index(self, category, from_idx, to_idx):
        if from_idx == to_idx:
            return
        self.add_data_undo_state("Move preset")
        slots = self.data["categories"][category]
        item = slots.pop(from_idx)
        slots.insert(to_idx, item)
        # W2-001: remap the live editor owner + snippet doc cache with the
        # reorder so a later debounce/save addresses the same logical
        # snippet, never a neighbour.
        def _shift(i):
            if i == from_idx:
                return to_idx
            if from_idx < to_idx:
                if from_idx < i <= to_idx:
                    return i - 1
            elif to_idx <= i < from_idx:
                return i + 1
            return i
        self._remap_snippet_owner(category, _shift)
        self.mark_dirty()
        self.refresh_snippets_panel()

    def move_preset_cross_category(self, from_cat, from_idx, to_cat, to_idx):
        # -- validate source, destination, target index AND capacity BEFORE
        #    any undo snapshot or source mutation. A stale target category, an
        #    invalid index, or a full destination must refuse with the source
        #    and destination left byte-identical and no undo entry written.
        if from_cat == "silo":
            src_arr = self.data["temp_presets"]
            src_docs = self.silo_docs
            src_arc = False
            if not (0 <= from_idx < len(src_arr)):
                return
            # W2-004: refuse silo -> SNIPPET conversion when the source
            # silo owns a mapped File Container that actually exists on disk.
            # Snippets have no attachment ownership; dropping the silo
            # identity would orphan the assets. A name-only reservation
            # (auto-assigned by _silo_folder_name) does not count — it's
            # the directory with bytes that must not be orphaned.
            # (Silo -> silo/archive moves keep the identity and stay allowed.)
            if to_cat not in ("silo", "arcsilo"):
                cur_cat = self.get_current_category() or ""
                folder_map = self.data.get("silo_folders_all", {}).get(cur_cat, {})
                if isinstance(folder_map, dict) and str(from_idx) in folder_map:
                    folder_dir = self._silo_folder_dir(from_idx)
                    if folder_dir is not None and os.path.isdir(folder_dir):
                        return
        elif from_cat == "arcsilo":
            src_arr = self.data.get("archive_temp_presets", [])
            src_docs = self.archive_docs
            src_arc = True
            if not (0 <= from_idx < len(src_arr)):
                return
            # W2-004: same guard for archive silos
            if to_cat not in ("silo", "arcsilo"):
                cur_cat = self.get_current_category() or ""
                folder_map = self.data.get("archive_silo_folders_all", {}).get(cur_cat, {})
                if isinstance(folder_map, dict) and str(from_idx) in folder_map:
                    folder_dir = self._silo_folder_dir(from_idx, is_archive=True)
                    if folder_dir is not None and os.path.isdir(folder_dir):
                        return
        else:
            cats = self.data.get("categories", {})
            if from_cat not in cats or not (0 <= from_idx < len(cats[from_cat])):
                return
            src_arr = None
            src_docs = None
            src_arc = None

        if to_cat == "silo":
            dst_arr = self.data["temp_presets"]
        elif to_cat == "arcsilo":
            dst_arr = self.data.setdefault("archive_temp_presets", [])
        else:
            cats = self.data.get("categories", {})
            if to_cat not in cats:
                return
            dst_arr = cats[to_cat]
            # W2-002: snippet categories are fixed at 100 slots. A full
            # destination (no free slot) cannot accept a move, so refuse
            # BEFORE any undo snapshot or source/destination mutation.
            if None not in dst_arr:
                return

        # a silo/arcsilo destination may not exceed the 100-slot contract
        if to_cat in ("silo", "arcsilo"):
            if len(dst_arr) >= self.MAX_SILOS_PER_CATEGORY:
                return
        # target index must be in range for the chosen destination
        if not (0 <= to_idx <= len(dst_arr)):
            return

        # -- all validated: now take the undo snapshot and mutate ----------
        self.add_data_undo_state("Move preset cross category")

        if from_cat in ("silo", "arcsilo"):
            text = src_arr.pop(from_idx)
            if from_idx < len(src_docs):
                src_docs.pop(from_idx)
            self.drop_silo_state(from_idx, is_archive=src_arc)
            item = {"name": text[:20], "text": text}
            if src_arc is False and not getattr(self, "active_is_archive", False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = (
                        max(0, self.active_temp_slot - 1) if self.data["temp_presets"] else 0
                    )
            elif src_arc is True and getattr(self, "active_is_archive", False):
                if from_idx < self.active_temp_slot:
                    self.active_temp_slot -= 1
                elif from_idx == self.active_temp_slot:
                    self.active_temp_slot = (
                        max(0, self.active_temp_slot - 1)
                        if self.data["archive_temp_presets"]
                        else 0
                    )
        else:
            item = self.data["categories"][from_cat].pop(from_idx)
            slots = self.data["categories"][from_cat]
            if len(slots) < 100:
                slots.append(None)

        if to_cat == "silo":
            # push the existing silos' state down BEFORE the slot exists
            self.open_silo_slot(to_idx)
            self.data["temp_presets"].insert(to_idx, item["text"] if item else "")
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            doc.setPlainText(item["text"] if item else "")
            self.silo_docs.insert(to_idx, doc)
        elif to_cat == "arcsilo":
            if "archive_temp_presets" not in self.data:
                self.data["archive_temp_presets"] = []
            self.open_silo_slot(to_idx, is_archive=True)
            self.data["archive_temp_presets"].insert(to_idx, item["text"] if item else "")
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            doc.setPlainText(item["text"] if item else "")
            self.archive_docs.insert(to_idx, doc)
        else:
            slots = self.data["categories"][to_cat]
            # W2-002: canonical 100-slot snippet invariant. A snippet
            # destination never grows past 100. Place the item into a free
            # (None) slot -- to_idx when it is free, else the first free
            # slot -- so the array length is unchanged. (Validation above
            # already refused a destination with no free slot.)
            if None not in slots:
                # defensive: should not happen post-validation
                if self.data_undo_stack:
                    self.data_undo_stack.pop()
                self._save_undo_state()
                return
            if 0 <= to_idx < len(slots) and slots[to_idx] is None:
                target = to_idx
            else:
                target = slots.index(None)
            slots[target] = item
            # W2-001: keep the live editor owner + doc cache with the
            # moved snippet. The source collection shifts down above the
            # popped index; the edited doc relocates to (to_cat, target).
            if from_cat not in ("silo", "arcsilo"):
                self._remap_snippet_owner(
                    from_cat,
                    lambda i: None if i == from_idx
                    else (i - 1 if i > from_idx else i))
                es = getattr(self, "editing_snippet", None)
                if es and es[0] == from_cat and es[1] == from_idx:
                    old_key = f"{from_cat}_{from_idx}"
                    docs = getattr(self, "snippet_docs", {})
                    if old_key in docs:
                        docs[f"{to_cat}_{target}"] = docs.pop(old_key)
                    self.editing_snippet = (to_cat, target)
                    self.btn_save.setText(
                        tr("Update", getattr(self, "_current_lang", "EN")))

        self._trim_archive()
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def swap_cross_temp_slots(self, source_idx, target_idx, source_is_archive, target_is_archive):
        if not getattr(self, "editing_snippet", None):
            target = self.data[
                "archive_temp_presets"
                if getattr(self, "active_is_archive", False)
                else "temp_presets"
            ]
            slot = getattr(self, "active_temp_slot", 0)
            if 0 <= slot < len(target):
                target[slot] = self.text_area.toPlainText()
        self.add_data_undo_state("Swap cross temp slots")
        source_arr = (
            self.data["archive_temp_presets"] if source_is_archive else self.data["temp_presets"]
        )
        target_arr = (
            self.data["archive_temp_presets"] if target_is_archive else self.data["temp_presets"]
        )
        source_docs = self.archive_docs if source_is_archive else self.silo_docs
        target_docs = self.archive_docs if target_is_archive else self.silo_docs

        # We need to make sure arrays are long enough
        while len(source_arr) <= source_idx:
            source_arr.append("")
        while len(target_arr) <= target_idx:
            target_arr.append("")

        from PyQt6.QtGui import QTextDocument

        while len(source_docs) <= source_idx:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            source_docs.append(d)
        while len(target_docs) <= target_idx:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            target_docs.append(d)

        source_arr[source_idx], target_arr[target_idx] = (
            target_arr[target_idx],
            source_arr[source_idx],
        )
        source_docs[source_idx], target_docs[target_idx] = (
            target_docs[target_idx],
            source_docs[source_idx],
        )

        # Cross-space swap is a MOVE, not a copy: every piece of slot-indexed
        # identity-owned state must travel with the text it describes, or a
        # swapped silo inherits a stranger's folder/project path/queue (T-754).
        s_key, t_key = str(source_idx), str(target_idx)
        s_qkey = "a" + s_key if source_is_archive else s_key
        t_qkey = "a" + t_key if target_is_archive else t_key

        def _swap_between(source_map, source_key, target_map, target_key):
            if not isinstance(source_map, dict) or not isinstance(target_map, dict):
                return
            if source_map is target_map:
                if source_key in source_map or target_key in target_map:
                    source_map[source_key], source_map[target_key] = (
                        source_map[target_key], source_map[source_key])
                return
            s_val = source_map.pop(source_key, None)
            t_val = target_map.pop(target_key, None)
            if t_val is not None:
                source_map[source_key] = t_val
            if s_val is not None:
                target_map[target_key] = s_val

        _swap_between(
            self.data.get("archive_silo_folders" if source_is_archive else "silo_folders", {}),
            s_key,
            self.data.get("archive_silo_folders" if target_is_archive else "silo_folders", {}),
            t_key,
        )
        _swap_between(
            self.data.get("archive_project_paths" if source_is_archive else "silo_project_paths", {}),
            s_key,
            self.data.get("archive_project_paths" if target_is_archive else "silo_project_paths", {}),
            t_key,
        )
        _swap_between(self.data.get("watcher_queues", {}), s_qkey,
                      self.data.get("watcher_queues", {}), t_qkey)

        # Per-category view state: "sN" normal / "aN" archive, same dict.
        store = self.data.get("silo_view_state_all")
        if isinstance(store, dict):
            cat = self.get_current_category()
            entries = store.get(cat)
            if isinstance(entries, dict):
                s_vkey = "s" + s_key if not source_is_archive else "a" + s_key
                t_vkey = "s" + t_key if not target_is_archive else "a" + t_key
                _swap_between(entries, s_vkey, entries, t_vkey)

        # W2-001: if the ACTIVE document participated in the swap, rebind
        # the active space/index so persistence writes to the same logical
        # silo instead of following the old slot coordinates.
        active_arc = bool(getattr(self, "active_is_archive", False))
        active_slot = getattr(self, "active_temp_slot", 0)
        if (active_arc, active_slot) == (source_is_archive, source_idx):
            self.active_is_archive = target_is_archive
            self.active_temp_slot = target_idx
            self._switch_to_slot(target_idx, initial=True,
                                 is_archive=target_is_archive)
        elif (active_arc, active_slot) == (target_is_archive, target_idx):
            self.active_is_archive = source_is_archive
            self.active_temp_slot = source_idx
            self._switch_to_slot(source_idx, initial=True,
                                 is_archive=source_is_archive)

        self._trim_archive()
        self.mark_dirty()
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def _on_selection_align(self, align):
        """Apply block alignment to all blocks spanned by the selection."""
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return
        cursor = ta.textCursor()
        if not cursor.hasSelection():
            return
        doc = ta.document()
        if doc is None or sip.isdeleted(doc):
            return
        al = {"left": Qt.AlignmentFlag.AlignLeft,
              "center": Qt.AlignmentFlag.AlignCenter,
              "right": Qt.AlignmentFlag.AlignRight}.get(align)
        if al is None:
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        block = doc.findBlock(start)
        last = doc.findBlock(end)
        updates = {}
        while block.isValid():
            bfmt = QTextBlockFormat()
            bfmt.setAlignment(al)
            QTextCursor(block).mergeBlockFormat(bfmt)
            bt = block.text()
            if bt:
                updates[bt] = align
            if block == last:
                break
            block = block.next()

        self._save_aligned_blocks(updates)
        # If user left-aligned a center-tagged header, clean centered_blocks
        if align == "left":
            self._clean_centered_blocks(updates)
        self.mark_dirty()

    def _save_aligned_blocks(self, updates):
        """Merge new alignments into data['aligned_blocks'] dict."""
        try:
            store = json.loads(self.data.get("aligned_blocks", "{}"))
        except (json.JSONDecodeError, ValueError):
            store = {}
        for k, v in updates.items():
            if v == "left":
                store.pop(k, None)
            else:
                store[k] = v
        self.data["aligned_blocks"] = json.dumps(store)

    def _clean_centered_blocks(self, updates):
        """Remove blocks from centered_blocks when user left-aligns them."""
        try:
            c = json.loads(self.data.get("centered_blocks", "[]"))
        except (json.JSONDecodeError, ValueError):
            return
        before = len(c)
        c = [t for t in c if t not in updates]
        if len(c) != before:
            self.data["centered_blocks"] = json.dumps(c)

    def _restore_aligned_blocks(self):
        """Re-apply saved per-block alignment after document load."""
        try:
            store = json.loads(self.data.get("aligned_blocks", "{}"))
        except (json.JSONDecodeError, ValueError):
            return
        if not store:
            return
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return
        doc = ta.document()
        if doc is None or sip.isdeleted(doc):
            return
        al_map = {"center": Qt.AlignmentFlag.AlignCenter,
                  "right": Qt.AlignmentFlag.AlignRight,
                  "left": Qt.AlignmentFlag.AlignLeft}
        block = doc.begin()
        while block.isValid():
            align = store.get(block.text())
            if align:
                qa = al_map.get(align)
                if qa:
                    bfmt = QTextBlockFormat()
                    bfmt.setAlignment(qa)
                    QTextCursor(block).mergeBlockFormat(bfmt)
            block = block.next()

    def _on_cursor_blink_changed(self, ms):
        self.data["cursor_blink_ms"] = str(ms)
        QApplication.setCursorFlashTime(ms)
        self.mark_dirty()

    def _on_align_changed(self, idx):
        align = self.cb_align_combo.itemData(idx) or "left"
        self.data["text_align"] = align
        self._apply_text_alignment()
        self.mark_dirty()

    def _on_ctrl_e_center_toggled(self, checked):
        """Centre the Ctrl+E title, as the removed footer checkbox did.

        The checkbox is gone - alignment is per line in the Ctrl+E… dialog
        now - but this stays as the single-switch entry point: it is what a
        hotkey or a restored profile would call, and it has to write BOTH
        keys, because read_settings prefers ctrl_e_align once one exists.
        Unticking returns to left; a checkbox has nowhere to record that the
        user had picked right or justified.
        """
        self.data["ctrl_e_center"] = "True" if checked else "False"
        self.data["ctrl_e_align"] = "center" if checked else "left"
        self.mark_dirty()

    def _restore_centered_blocks(self):
        """Re-apply center alignment to blocks tracked in centered_blocks."""
        try:
            centered = json.loads(self.data.get("centered_blocks", "[]"))
        except (json.JSONDecodeError, ValueError):
            centered = []
        if not centered:
            return
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return
        doc = ta.document()
        if doc is None or sip.isdeleted(doc):
            return
        block = doc.begin()
        while block.isValid():
            if block.text() in centered:
                bfmt = QTextBlockFormat()
                bfmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
                QTextCursor(block).mergeBlockFormat(bfmt)
            block = block.next()

    def _apply_text_alignment(self):
        """Apply the saved text alignment to the active QTextDocument."""
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return
        doc = ta.document()
        if doc is None or sip.isdeleted(doc):
            return
        align_val = self.data.get("text_align", "left")
        if align_val == "center":
            opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        elif align_val == "right":
            opt = QTextOption(Qt.AlignmentFlag.AlignRight)
        else:
            opt = QTextOption(Qt.AlignmentFlag.AlignLeft)
        # Preserve the word wrap mode from the existing doc option
        old = doc.defaultTextOption()
        opt.setWrapMode(old.wrapMode())
        doc.setDefaultTextOption(opt)

    def on_wrap_toggled(self, checked):
        self.data["word_wrap"] = "True" if checked else "False"
        self.apply_wrap_mode()
        self.mark_dirty()

    def on_line_numbers_toggled(self, checked):
        self.data["show_line_numbers"] = "True" if checked else "False"
        self.text_area.update_line_number_area_width()
        self.text_area.line_number_area.update()
        self.mark_dirty()

    def apply_wrap_mode(self):
        wrap = self.data.get("word_wrap", "True") == "True"
        self.text_area.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if wrap else QTextEdit.LineWrapMode.NoWrap
        )

    def open_help_dialog(self):
        """Open the comprehensive help window (hotkeys, gestures, features)."""
        self.play_tick_sound()
        dlg = getattr(self, "_help_dialog", None)
        if dlg is None or sip.isdeleted(dlg):
            from fastprompter.ui.help_dialog import HelpDialog
            dlg = HelpDialog(self)
            self._help_dialog = dlg
        self._increment_focus_lock()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        QTimer.singleShot(300, self._decrement_focus_lock)

    def open_hotkey_settings(self):
        from fastprompter.ui.settings import HotkeySettingsDialog
        dlg = HotkeySettingsDialog(self)
        self.ignore_focus_loss = True
        try:
            dlg.exec()
        finally:
            self.ignore_focus_loss = False

    # Snapshot keys that are bookkeeping, not user data. They MUST be left out
    # of every equality test, or each snapshot differs from every other one and
    # the no-op guards below silently stop guarding anything.
    _SNAPSHOT_META = ("_seq", "_doc_id", "_text_steps")

    def _active_doc(self):
        area = getattr(self, "text_area", None)
        if area is None:
            return None
        try:
            return area.document()
        except RuntimeError:          # C++ side already gone (shutdown)
            return None

    def _text_undo_steps(self):
        """How many undo steps the OPEN document has — the ordering key that
        tells a data action apart from the typing that followed it."""
        doc = self._active_doc()
        try:
            return doc.availableUndoSteps() if doc is not None else 0
        except (RuntimeError, AttributeError):
            return 0

    def _stamp_snapshot(self, snap):
        """Attach the ordering metadata Ctrl+Z routing reads back later."""
        snap["_seq"] = self._bump_action_seq()
        doc = self._active_doc()
        snap["_doc_id"] = id(doc) if doc is not None else 0
        snap["_text_steps"] = self._text_undo_steps()
        return snap

    def _same_snapshot(self, a, b):
        keys = set(a) | set(b)
        return all(a.get(k) == b.get(k) for k in keys if k not in self._SNAPSHOT_META)

    def _live_text_into(self, snap):
        """Fold the OPEN editor's text into a snapshot.

        `temp_presets` only receives the active silo's text when something
        flushes it, and most callers of `add_data_undo_state` never do. A
        snapshot taken between flushes is therefore stale by exactly what the
        user has typed since — and restoring it DELETES that typing with
        nothing left to bring it back. That is the reported catastrophe:
        "undo returned the deleted text and ate the text I had just written".
        Carrying the live text also makes the redo push a true 'before' state,
        so anything a data undo overwrites is one Ctrl+Y away."""
        area = getattr(self, "text_area", None)
        if area is None:
            return
        try:
            live = area.toPlainText()
        except RuntimeError:
            return
        editing = snap.get("editing_snippet")
        if editing:
            slots = snap.get("categories", {}).get(editing[0])
            if (isinstance(slots, list) and isinstance(editing[1], int)
                    and 0 <= editing[1] < len(slots)
                    and isinstance(slots[editing[1]], dict)):
                slots[editing[1]]["text"] = live
            return
        key = "archive_temp_presets" if snap.get("active_is_archive") else "temp_presets"
        target = snap.get(key)
        slot = snap.get("active_temp_slot", 0)
        if isinstance(target, list) and isinstance(slot, int) and 0 <= slot < len(target):
            target[slot] = live

    def _snapshot_current(self):
        pinned = self.data.get("pinned_silos", [])

        # O(1) per-slot deep copy for categories since they rarely change;
        # deepcopy is too slow, but the slot DICTS must not be aliased
        cats_copy = {k: _copy_category_slots(v)
                     for k, v in self.data.get("categories", {}).items()}

        # Fast 2-level copy for {str: list/dict} maps — avoids copy.deepcopy overhead
        def _copy2(d):
            if not isinstance(d, dict):
                return {}
            out = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    out[k] = dict(v)
                elif isinstance(v, list):
                    out[k] = list(v)
                else:
                    out[k] = v
            return out

        snap = {
            "categories": cats_copy,
            "cats_order": list(self.data.get("cats_order", [])),
            "category": self.get_current_category(),
            "temp_presets": list(self.data.get("temp_presets", [])),
            "archive_temp_presets": list(self.data.get("archive_temp_presets", [])),
            "active_temp_slot": self.active_temp_slot,
            "active_is_archive": getattr(self, "active_is_archive", False),
            "editing_snippet": getattr(self, "editing_snippet", None),
            "pinned_silos": list(pinned) if isinstance(pinned, list) else [],
            "silo_ticked": list(self.data.get("silo_ticked", [])),
            "silo_children": _copy2(self.data.get("silo_children", {})),
            "silo_collapsed": list(self.data.get("silo_collapsed", [])),
            "silo_folders": dict(self.data.get("silo_folders", {})),
            "silo_last_edited": dict(getattr(self, "silo_last_edited", {})),
            # The rest of _SILO_INDEX_STATE. Deleting a silo REMAPS these down
            # by one; undo used to restore only the text, so every colour,
            # project path, silo type and watcher queue below the deleted slot
            # stayed shifted — permanently, and silently. Measured: delete silo
            # 0 of three, undo, and silo 0 wears silo 1's colour.
            "silo_colors": dict(self.data.get("silo_colors", {})),
            "silo_project_paths": _copy2(self.data.get("silo_project_paths", {})),
            "silo_types": dict(self.data.get("silo_types", {})),
            "watcher_queues": _copy2(self.data.get("watcher_queues", {})),
            # per-silo file link + Sync-Project slot map: identity-owned, so
            # a delete/undo must restore them exactly like colours/types
            "silo_links": dict(self.data.get("silo_links", {})),
            "project_sync_map": _copy2(self.data.get("project_sync_map", {})),
            # The archive's own index-keyed stores (T-754): an archive
            # delete/reorder/transfer must undo back to the exact folders and
            # project paths the text had, not just restore the text.
            "archive_silo_folders": dict(self.data.get("archive_silo_folders", {})),
            "archive_project_paths": _copy2(self.data.get("archive_project_paths", {})),
            # Per-category cursor/view state (T-755): archive ops used to
            # undo the text but leave the saved cursors shifted.
            "view_state": _copy2(
                self.data.get("silo_view_state_all", {}).get(self.get_current_category(), {})),
            # T-704 made gaps ride with their silo, but the undo snapshot never
            # carried them: a gap move had no undo entry at all, so Ctrl+Z after
            # one popped an UNRELATED older action instead.
            "silo_gaps": [i for i in (self.data.get("silo_gaps") or []) if isinstance(i, int)],
            "silo_gap_names": dict(self.data.get("silo_gap_names") or {}),
            # category -> physical folder component: without it, undoing a
            # category delete re-allocates a NEW folder component and the
            "category_file_dirs": dict(self.data.get("category_file_dirs") or {}),
        }
        self._live_text_into(snap)
        # PERF-006: the size cap must count the WHOLE snapshot -- including
        # category snippet text, which the old partial sum omitted, making
        # the 20M cap ineffective for the largest duplicated component.
        snap["_text_size"] = _snapshot_text_size(snap)
        return snap

    def _snapshot_is_noop(self, state, now=None):
        """True when restoring this snapshot would change no user data.

        Compared field by field against a snapshot of NOW. The old version
        looked at six of the eighteen keys, so an action that only moved a gap,
        recoloured, ticked, nested or retyped a silo read as a "no-op" — and
        `undo_action`'s skip loop then DISCARDED it and walked back into an
        OLDER snapshot, restoring that snapshot's text over the user's. A key
        the incoming state does not carry at all (an entry written by an older
        build) counts as different, so it is restored rather than thrown away:
        never discard a snapshot on a guess."""
        if state.get("_switch"):
            # PERF-006: a navigation record always moves the active slot
            return False
        if now is None:
            now = self._snapshot_current()
        for key, value in now.items():
            if key in self._SNAPSHOT_META or key == "category":
                continue
            if key not in state or state[key] != value:
                return False
        return True

    def _snapshot_is_valid(self, state):
        """Executable-snapshot schema check (CORE-014).

        A persisted undo entry may be valid JSON of the right container shape
        and still not be executable: ``_apply_data_state`` indexes mandatory
        keys and binds editing state, so a truncated/foreign entry must never
        reach apply. Requires the mandatory fields with their outer types, a
        well-formed categories map (str keys, slot lists of None or
        name/text-carrying dicts), and well-typed editing/active-slot state.
        Entries failing this are discarded by the ONE quarantine policy at
        load/apply time, never partially applied."""
        if not isinstance(state, dict):
            return False
        if state.get("_switch"):
            # PERF-006 compact navigation record
            return (isinstance(state.get("active_temp_slot"), int)
                    and isinstance(state.get("active_is_archive"), bool))
        for key, expected in (("categories", dict),
                              ("temp_presets", list),
                              ("archive_temp_presets", list)):
            if not isinstance(state.get(key), expected):
                return False
        for cat, slots in state["categories"].items():
            if not isinstance(cat, str) or not isinstance(slots, list):
                return False
            if len(slots) > 100:
                return False
            for item in slots:
                if item is None:
                    continue
                if not isinstance(item, dict):
                    return False
                if not isinstance(item.get("name"), str) or not isinstance(item.get("text"), str):
                    return False
        edit = state.get("editing_snippet")
        if edit is not None:
            if not (isinstance(edit, (list, tuple)) and len(edit) == 2
                    and isinstance(edit[0], str) and isinstance(edit[1], int)):
                return False
            # CORE-008: the editing category must exist and the slot index
            # must be IN RANGE. A negative index survives the old `< len`
            # check via Python's wrap-around and indexes the WRONG silo; an
            # out-of-range index raises IndexError at apply time. Reject both.
            cat = edit[0]
            cdata = state.get("categories", {}).get(cat)
            if not isinstance(cdata, list) or not (0 <= edit[1] < len(cdata)):
                return False
        slot = state.get("active_temp_slot", 0)
        # CORE-008: a negative active slot wraps around in `categories[cat]`
        # / `temp_presets[slot]` indexing and mutates another silo. Non-negative
        # is the only safe value; the apply path already guards the upper bound
        # with `< len`.
        if not isinstance(slot, int) or slot < 0:
            return False
        # CORE-008: a composite transfer entry must carry a valid destination
        # identity and a transfer-store namespace that is a strict subset of
        # the canonical `_TRANSFER_STORE_KEYS`, with per-category value shapes
        # (None / dict / list) — never a foreign top-level key or scalar that
        # would replace an unrelated application store at apply time.
        if state.get("_transfer"):
            if not isinstance(state.get("_transfer_dst_cat"), str):
                return False
            dst_stores = state.get("_transfer_dst_before")
            if not isinstance(dst_stores, dict):
                return False
            for key, value in dst_stores.items():
                if key not in self._TRANSFER_STORE_KEYS:
                    return False
                if value is not None and not isinstance(value, (dict, list)):
                    return False
        # W2-004: an attached merge ledger must be a well-formed list of
        # exact path pairs — anything else is refused before the physical
        # reversal could act on garbage coordinates.
        if state.get("_merge_ledger") is not None:
            ledger = state["_merge_ledger"]
            if not isinstance(ledger, list):
                return False
            for pair in ledger:
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                        and all(isinstance(p, str) and p for p in pair)):
                    return False
        # PERF-002: compact metadata records carry their own schema.
        if state.get("_compact") is not None:
            kind = state.get("_compact")
            if kind not in self._COMPACT_META_KINDS:
                return False
            coords = state.get("coords")
            if kind == "theme":
                if coords is not None or not isinstance(
                        state.get("old"), str) \
                        or not isinstance(state.get("new", ""), str):
                    return False
            elif kind in ("tick", "pin"):
                if not isinstance(coords, int) or coords < 0:
                    return False
            elif kind == "gap_name":
                if not (isinstance(coords, (list, tuple)) and len(coords) == 2
                        and isinstance(coords[0], str)
                        and isinstance(coords[1], int) and coords[1] >= 0):
                    return False
        return True

    def _bump_action_seq(self):
        """Monotonic ordering for text edits vs data actions — wall-clock
        time ties on Windows' timer granularity and breaks Ctrl+Z routing."""
        self._action_seq = getattr(self, "_action_seq", 0) + 1
        return self._action_seq

    def _undo_prefers_data(self):
        """Ctrl+Z reverses the NEWEST action, whichever kind it was.

        Every data snapshot records how many undo steps the open document had
        when it was pushed, so "did the user type after this data action?" is a
        comparison rather than a guess. The old version compared two counters
        and then LATCHED onto the data stack after the first data undo ("keep
        data undo fresh"), so a second Ctrl+Z restored an ever-older snapshot
        straight over text typed since — unrecoverable text loss, which is the
        whole reason this ticket exists."""
        stack = getattr(self, "data_undo_stack", None)
        if not stack:
            return False
        top = stack[-1]
        doc = self._active_doc()
        if doc is None:
            return True
        if top.get("_doc_id") != id(doc):
            # The snapshot was stamped against a document we are not looking
            # at. _switch_to_slot re-stamps its "Switch silo" entry to the
            # TARGET document, so what reaches here is either a snippet edit
            # or a stack reloaded from disk, where the stored _doc_id is a
            # Python id() from another process and is garbage in this one.
            # Any undo steps the ACTIVE document has right now were made
            # AFTER that snapshot — they are the newest action, and firing a
            # data undo over them restores the snapshot's stale text and
            # wipes their history. The old unconditional `return True` did
            # exactly that after every restart: type, Ctrl+Z, and the text
            # was gone with nothing left to bring it back (T-734). Prefer
            # text undo whenever the active document has steps; a bare
            # document leaves the data action as the only honest reversal.
            return not doc.isUndoAvailable()
        return self._text_undo_steps() <= top.get("_text_steps", 0)

    def _smart_undo(self):
        """Ctrl+Z: data undo (silo clear/delete/move/gap) or text undo."""
        if getattr(self, "_in_smart_undo", False):
            return
        self._in_smart_undo = True
        self._increment_focus_lock()
        try:
            kinds = self._undo_kinds()
            if self._undo_prefers_data():
                if self.undo_action():
                    kinds.append("data")
                    return
            doc = self._active_doc()
            if doc is not None and doc.isUndoAvailable():
                self.text_area.undo()
                self.text_area.invalidate_word_count()
                self.play_sound("undo")
                kinds.append("text")
            elif self.undo_action():
                kinds.append("data")
                self.play_sound("undo")
            else:
                self.statusBar().showMessage(tr("Nothing to undo", getattr(self, "_current_lang", "EN")), 2000)
        finally:
            self._in_smart_undo = False
            # A data undo rebuilds documents, switches silos and re-flows the
            # list — any of which can queue a transient window deactivation.
            # The deactivation event is DELIVERED asynchronously (next event
            # loop pass), so releasing the focus lock synchronously here would
            # let changeEvent -> hide_and_save run with the lock already gone
            # ("Ctrl+Z closed the program"). Release it deferred, like every
            # other undo-adjacent lock, so it covers the queued event.
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._decrement_focus_lock)
            # The lock only stops the HIDE; it does not stop Windows from
            # dropping the window to the back of the z-order. Re-assert the
            # foreground right away (the rebuild is synchronous, so any
            # deactivation it caused has already landed) and again after the
            # lock releases, to cover any straggler event still in the queue.
            self._bring_to_front()
            QTimer.singleShot(320, self._bring_to_front)

    def _undo_kinds(self):
        """What each Ctrl+Z actually reversed, newest last — the only thing
        that lets Ctrl+Y put the same actions back in the same order."""
        if not isinstance(getattr(self, "_undo_kind_stack", None), list):
            self._undo_kind_stack = []
        return self._undo_kind_stack

    def _smart_redo(self):
        """Ctrl+Y / Ctrl+Shift+Z: mirror of `_smart_undo`, step for step."""
        if getattr(self, "_in_smart_redo", False):
            return
        self._in_smart_redo = True
        self._increment_focus_lock()
        try:
            kinds = self._undo_kinds()
            kind = kinds.pop() if kinds else None
            doc = self._active_doc()
            if kind == "text":
                if doc is not None and doc.isRedoAvailable():
                    self.text_area.redo()
                    self.text_area.invalidate_word_count()
                    self.play_sound("redo")
                    return
                if self.redo_action():
                    return
                self.statusBar().showMessage(tr("Nothing to redo", getattr(self, "_current_lang", "EN")), 2000)
                return
            if kind == "data":
                if self.redo_action():
                    return
                self.statusBar().showMessage(tr("Nothing to redo", getattr(self, "_current_lang", "EN")), 2000)
                return
            # No recorded history (fresh session, or the stacks were trimmed):
            # data first, text as the fallback, so nothing is unreachable.
            if self.redo_action():
                return
            if doc is not None and doc.isRedoAvailable():
                self.text_area.redo()
                self.text_area.invalidate_word_count()
                self.play_sound("redo")
                return
            self.statusBar().showMessage(tr("Nothing to redo", getattr(self, "_current_lang", "EN")), 2000)
        finally:
            self._in_smart_redo = False
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._decrement_focus_lock)
            # Same z-order fix as _smart_undo: a data redo rebuilds the lists
            # and can drop the window behind others. Keep it on top.
            self._bring_to_front()
            QTimer.singleShot(320, self._bring_to_front)

    def undo_action(self):
        if hasattr(self, "data_undo_stack") and self.data_undo_stack:
            if not hasattr(self, "data_redo_stack"):
                self.data_redo_stack = []
            # Skip no-op snapshots, but ONLY within the current tab —
            # a snapshot from another tab is never comparable to the
            # currently visible lists and must be restored, not judged
            cur_cat = self.get_current_category()
            # One snapshot of NOW serves the whole skip loop AND becomes the
            # redo entry — taking it per iteration deep-copies every silo's
            # text on every step of a walk that can be 50 long.
            now = self._snapshot_current()
            state = self.data_undo_stack.pop()
            while (
                self.data_undo_stack
                and (state.get("category") == cur_cat
                     and self._snapshot_is_noop(state, now)
                     or not self._snapshot_is_valid(state))
            ):
                state = self.data_undo_stack.pop()
            if not self._snapshot_is_valid(state):
                self._save_undo_state()
                return False
            if state.get("category") == cur_cat and self._snapshot_is_noop(state, now):
                return False
            # PERF-006: a redo of a Switch-silo action is itself a COMPACT
            # navigation record targeting the CURRENT (post-undo) slot, so
            # Ctrl+Y never deep-copies the whole data universe either.
            # W2-003/W2-004: the physical half of a composite transaction
            # (cross-project transfer, nested-silo merge reversal) resolves
            # BEFORE the logical half commits. A refused inverse must leave
            # the stacks exactly as they were so the action stays retryable.
            try:
                self._apply_data_state(state)
            except _TransactionRefused as e:
                from fastprompter.core.logging import logger
                logger.warning(
                    "undo refused: composite filesystem half failed (%s); "
                    "state unchanged", e)
                self.data_undo_stack.append(state)
                return False
            if state.get("_compact"):
                # PERF-002: the redo of a compact record is its inverse —
                # same kind/coords, values swapped.
                redo_state = self._stamp_snapshot({
                    "_compact": state["_compact"],
                    "coords": state.get("coords"),
                    "old": state.get("new"),
                    "new": state.get("old"),
                })
            elif state.get("_switch"):
                redo_state = self._stamp_snapshot({
                    "_switch": True,
                    "category": self.get_current_category(),
                    "active_temp_slot": self.active_temp_slot,
                    "active_is_archive": bool(
                        getattr(self, "active_is_archive", False)),
                })
            else:
                redo_state = self._stamp_snapshot(now)
                if state.get("_transfer"):
                    # CORE-008: the redo entry is the AFTER half of the same
                    # composite — source-side current state plus the captured
                    # post-transfer destination stores — so one Ctrl+Y recreates
                    # exactly one transfer.
                    redo_state["_transfer"] = True
                    redo_state["_transfer_dst_cat"] = state.get("_transfer_dst_cat")
                    redo_state["_transfer_dst_before"] = copy.deepcopy(
                        state.get("_transfer_dst_after") or {})
                    # CORE-004: invert the folder orientation back to FORWARD
                    # (src -> dst) so the redo re-performs the physical move.
                    fp = state.get("_transfer_folder")
                    redo_state["_transfer_folder"] = (
                        (fp[1], fp[0], fp[3], fp[2])
                        if isinstance(fp, (tuple, list)) and len(fp) == 4
                        else None)
                if state.get("_merge_ledger"):
                    # W2-004: redo re-performs the merge by carrying the
                    # INVERTED ledger; apply's preflight reverses pairs, so
                    # (orig, published) becomes (published, orig).
                    redo_state["_merge_ledger"] = [
                        [pair[1], pair[0]] for pair in state["_merge_ledger"]
                        if isinstance(pair, (tuple, list)) and len(pair) == 2]
            self.data_redo_stack.append(redo_state)

            MAX_CHARS = 20_000_000
            while len(self.data_redo_stack) > 50:
                self.data_redo_stack.pop(0)

            while len(self.data_redo_stack) > 1 and sum(_snapshot_text_size(s) for s in self.data_redo_stack) > MAX_CHARS:
                self.data_redo_stack.pop(0)
            self.play_sound("undo")
            # NOT a fresh bump: latching the data stack "fresh" here is what
            # made every following Ctrl+Z overwrite newer text (see
            # _undo_prefers_data). Inherit the restored action's own position.
            self._last_data_action_time = state.get("_seq", 0)
            self._save_undo_state()
            return True
        # Text undo is handled natively by QTextEdit via VaultTextEdit.keyPressEvent
        return False

    def redo_action(self):
        if hasattr(self, "data_redo_stack") and self.data_redo_stack:
            if not hasattr(self, "data_undo_stack"):
                self.data_undo_stack = []
            while self.data_redo_stack and not self._snapshot_is_valid(self.data_redo_stack[-1]):
                from fastprompter.core.logging import logger
                logger.error("discarding invalid redo snapshot (CORE-014)")
                self.data_redo_stack.pop()
            if not self.data_redo_stack:
                return False
            undo_state = self._stamp_snapshot(self._snapshot_current())
            state = self.data_redo_stack.pop()
            # W2-003/W2-004: physical-first, fail-closed. A refused composite
            # leaves both stacks exactly as they were (retryable).
            try:
                self._apply_data_state(state)
            except _TransactionRefused as e:
                from fastprompter.core.logging import logger
                logger.warning(
                    "redo refused: composite filesystem half failed (%s); "
                    "state unchanged", e)
                self.data_redo_stack.append(state)
                return False
            self.data_undo_stack.append(undo_state)
            self.play_sound("redo")
            self._last_data_action_time = undo_state["_seq"]
            self._save_undo_state()
            return True
        # Text redo is handled natively by QTextEdit via VaultTextEdit.keyPressEvent
        return False

    def _composite_physical_preflight(self, state):
        """W2-003/W2-004: perform the physical inverse of a composite
        transaction BEFORE its logical half commits.

        * ``_transfer``: the recorded (reversed) folder tuple is renamed
          back. A destination collision, a missing source with no published
          side, or an OSError refuses the WHOLE transaction.
        * ``_merge_ledger``: every successful merge move is reversed
          exactly, newest first, no-clobber — a collision at any original
          path refuses the whole reversal.

        Returns True; raises _TransactionRefused when the inverse cannot be
        performed safely (the caller must not commit the logical half).
        Already-reversed pairs are skipped so a preflight retry after an
        interrupted run stays idempotent."""
        fp = state.get("_transfer_folder")
        if state.get("_transfer") and isinstance(fp, (tuple, list)) \
                and len(fp) == 4:
            from_dir, to_dir = fp[0], fp[1]
            if os.path.isdir(from_dir):
                if os.path.exists(to_dir):
                    raise _TransactionRefused(
                        f"transfer undo collision: {to_dir} already exists")
                try:
                    os.makedirs(os.path.dirname(to_dir), exist_ok=True)
                    os.rename(from_dir, to_dir)
                except OSError as e:
                    raise _TransactionRefused(
                        f"transfer folder restore {from_dir} -> {to_dir} "
                        f"failed: {e}")
            elif not os.path.exists(to_dir):
                raise _TransactionRefused(
                    "transfer orientation impossible: neither "
                    f"{from_dir} nor {to_dir} exists")
        ledger = state.get("_merge_ledger")
        if ledger:
            for pair in reversed(ledger):
                if not (isinstance(pair, (tuple, list)) and len(pair) == 2):
                    continue
                orig, pub = pair[0], pair[1]
                if not os.path.lexists(pub):
                    continue          # nothing landed / already reverted
                if os.path.lexists(orig):
                    raise _TransactionRefused(
                        f"merge undo collision: {orig} already exists")
                try:
                    os.makedirs(os.path.dirname(orig), exist_ok=True)
                    os.rename(pub, orig)
                except OSError as e:
                    raise _TransactionRefused(
                        f"merge undo {pub} -> {orig} failed: {e}")
        return True

    def _apply_data_state(self, state):
        if not self._snapshot_is_valid(state):
            # CORE-014: never partially apply a foreign/truncated entry. One
            # explicit policy: discard with a log line, live data untouched.
            from fastprompter.core.logging import logger
            logger.error("refusing to apply invalid undo snapshot (CORE-014); live data untouched")
            return
        if state.get("_switch"):
            # PERF-006: a compact navigation record reverses ONLY the switch
            # -- it never mutates text, stores or per-category state.
            self.active_temp_slot = state.get("active_temp_slot", 0)
            self.active_is_archive = bool(state.get("active_is_archive", False))
            self._switch_to_slot(self.active_temp_slot, initial=True,
                                 is_archive=self.active_is_archive)
            self.refresh_temp_presets()
            return
        if state.get("_compact"):
            # PERF-002: a compact metadata record reverses exactly one tiny
            # reversible value (tick/pin/theme/gap-name); nothing else moves.
            self._apply_compact_meta(state, state.get("old"))
            self.refresh_temp_presets()
            return
        # W2-003/W2-004: composite transactions resolve their FILESYSTEM half
        # before ANY logical state is rebound. A refused inverse raises and
        # the caller leaves every stack untouched (fail-closed).
        self._composite_physical_preflight(state)
        self.data["categories"] = state["categories"]
        if state.get("cats_order"):
            self.data["cats_order"] = list(state["cats_order"])
        # Rebuild the tab bar FIRST — it resets the current index to 0 and
        # would otherwise clobber the tab jump and orphan the restored lists
        self.build_categories()

        # The action may have happened on another tab — return to it, and
        # rebind the per-category backing store; DB saves read from
        # temp_presets_all, so without this the restored data is lost.
        snap_cat = state.get("category")
        if snap_cat and snap_cat in self.data.get("cats_order", []):
            idx = self.combo_index_for_category(snap_cat)
            if idx < 0:
                # P1-1: the undo target is HIDDEN, so the combo cannot show
                # it. One explicit policy instead of binding a different
                # visible project to the restored stores: unhide it — an
                # undo is a user-visible restore and the project must be
                # reachable again.
                hidden = self.hidden_categories()
                if snap_cat in hidden:
                    hidden.remove(snap_cat)
                self.rebuild_cat_combo(keep=snap_cat)
                idx = self.combo_index_for_category(snap_cat)
            if idx >= 0 and self.cat_combo.currentIndex() != idx:
                self.cat_combo.blockSignals(True)
                self.cat_combo.setCurrentIndex(idx)
                self.cat_combo.blockSignals(False)
            self.data["last_tab_idx"] = idx

        self.data["temp_presets"] = state["temp_presets"]
        self.data["archive_temp_presets"] = state["archive_temp_presets"]
        if snap_cat and "temp_presets_all" in self.data:
            self.data["temp_presets_all"][snap_cat] = self.data["temp_presets"]
            self.data["archive_temp_presets_all"][snap_cat] = self.data["archive_temp_presets"]
        if snap_cat:
            plist = self.data.setdefault("pinned_silos_all", {}).setdefault(snap_cat, [])
            plist[:] = list(state.get("pinned_silos", []))
            self.data["pinned_silos"] = plist
            tlist = self.data.setdefault("silo_ticked_all", {}).setdefault(snap_cat, [])
            tlist[:] = list(state.get("silo_ticked", []))
            self.data["silo_ticked"] = tlist
            cmap = self.data.setdefault("silo_children_all", {}).setdefault(snap_cat, {})
            cmap.clear()
            cmap.update(copy.deepcopy(state.get("silo_children", {})))
            self.data["silo_children"] = cmap
            clist = self.data.setdefault("silo_collapsed_all", {}).setdefault(snap_cat, [])
            clist[:] = list(state.get("silo_collapsed", []))
            self.data["silo_collapsed"] = clist
            fdict = self.data.setdefault("silo_folders_all", {}).setdefault(snap_cat, {})
            fdict.clear()
            fdict.update(dict(state.get("silo_folders", {})))
            self.data["silo_folders"] = fdict
            # Gaps are slot-keyed like everything above (T-704) and were the
            # one store the snapshot never carried. `is not None` for the same
            # reason as the colours below: an entry written by an older build
            # has no such key, and clearing on a missing key would DELETE the
            # user's gaps instead of leaving them alone.
            saved_gaps = state.get("silo_gaps")
            if saved_gaps is not None:
                glist = self.data.setdefault("silo_gaps_all", {}).setdefault(snap_cat, [])
                glist[:] = [i for i in saved_gaps if isinstance(i, int)]
                self.data["silo_gaps"] = glist
            saved_gap_names = state.get("silo_gap_names")
            if saved_gap_names is not None:
                gn = self.data.setdefault("silo_gap_names_all", {}).setdefault(snap_cat, {})
                gn.clear()
                gn.update(saved_gap_names)
                self.data["silo_gap_names"] = gn
            # the category's physical folder component must come back with it:
            # trash-restore resolves the folder through this map, so a deleted
            # category's files must land in the SAME directory they left.
            # Merge (snapshot wins for keys it has) so entries allocated AFTER
            # the snapshot survive an unrelated undo.
            cfm = self.data.setdefault("category_file_dirs", {})
            cfm.update(state.get("category_file_dirs") or {})
            edict = self.data.setdefault("silo_last_edited_all", {}).setdefault(snap_cat, {})
            edict.clear()
            edict.update(state.get("silo_last_edited", {}))
            self.silo_last_edited = edict
            # The stores that a delete remaps but undo used to leave shifted.
            # `is not None` on purpose: an undo entry written by an older build
            # has no such key, and clearing on a missing key would DELETE the
            # user's colours instead of leaving them alone.
            for key, store in (("silo_colors", "silo_colors_all"),
                               ("silo_project_paths", "silo_project_paths_all"),
                               ("silo_types", "silo_type_all"),
                               ("watcher_queues", "watcher_queues_all"),
                               ("archive_silo_folders", "archive_silo_folders_all"),
                               ("archive_project_paths", "archive_project_paths_all"),
                               ("silo_links", "silo_links_all"),
                               ("project_sync_map", "project_sync_map_all")):
                saved = state.get(key)
                if saved is None:
                    continue
                live = self.data.setdefault(store, {}).setdefault(snap_cat, {})
                live.clear()
                live.update(copy.deepcopy(saved))
                self.data[key] = live
            # Per-category cursor/view state. `is not None`: an undo entry from
            # an older build has no such key, and clearing on a missing key
            # would DELETE the user's saved cursors instead of leaving them.
            saved_view = state.get("view_state")
            if saved_view is not None:
                vstore = self.data.setdefault("silo_view_state_all", {}).setdefault(snap_cat, {})
                vstore.clear()
                vstore.update(copy.deepcopy(saved_view))
            # Restore files from _trash LAST, after EVERY per-category map
            # (including the archive folder map above) has been rebound: the
            # restore resolves original paths through these maps, so running
            # it early left archive folders stranded in _trash — text came
            # back but the archive's files stayed gone.
            self._restore_trashed_folders(snap_cat)
        # CORE-008: composite cross-project entry — restore the DESTINATION
        # half symmetrically. The entry carries the destination stores to
        # restore: pre-transfer in the undo stack, post-transfer in the redo
        # stack (undo_action stamps the after half into the redo entry).
        if state.get("_transfer"):
            dst_cat = state.get("_transfer_dst_cat")
            dst_stores = state.get("_transfer_dst_before")
            if isinstance(dst_cat, str) and isinstance(dst_stores, dict):
                for all_key, value in dst_stores.items():
                    store = self.data.setdefault(all_key, {})
                    if not isinstance(store, dict):
                        store = self.data[all_key] = {}
                    if value is None:
                        store.pop(dst_cat, None)
                    else:
                        store[dst_cat] = copy.deepcopy(value)
                # The flat aliases never point at the destination (it is not
                # the current category by construction), so no rebinding here;
                # a later category switch binds the restored stores.
                # CORE-004: the physical folder move is part of the SAME
                # transaction. The folder tuple is oriented for the move this
                # apply performs (reversed for UNDO, forward for REDO), so the
                # bytes follow the store state exactly. Best-effort: a missing
                # source or an already-present destination is left untouched
                # rather than clobbered.
                folder = state.get("_transfer_folder")
                if isinstance(folder, (tuple, list)) and len(folder) == 4:
                    from_dir, to_dir = folder[0], folder[1]
                    if os.path.isdir(from_dir) and not os.path.exists(to_dir):
                        try:
                            os.rename(from_dir, to_dir)
                        except OSError as e:
                            from fastprompter.core.logging import logger
                            logger.error(
                                "transfer folder restore %s -> %s failed: %s",
                                from_dir, to_dir, e)
        from PyQt6.QtGui import QTextDocument

        while len(self.silo_docs) < len(self.data["temp_presets"]):
            self.silo_docs.append(None)
        while len(self.silo_docs) > len(self.data["temp_presets"]):
            self.silo_docs.pop()
        for i, txt in enumerate(self.data["temp_presets"]):
            if self.silo_docs[i] is not None and self.silo_docs[i].toPlainText() != txt:
                self._set_plain_text_clean(self.silo_docs[i], txt)
        while len(self.archive_docs) < len(self.data["archive_temp_presets"]):
            self.archive_docs.append(None)
        while len(self.archive_docs) > len(self.data["archive_temp_presets"]):
            self.archive_docs.pop()
        for i, txt in enumerate(self.data["archive_temp_presets"]):
            if self.archive_docs[i] is not None and self.archive_docs[i].toPlainText() != txt:
                self._set_plain_text_clean(self.archive_docs[i], txt)
        active_is_archive = state.get("active_is_archive", False)
        active_slot = state.get("active_temp_slot", 0)
        editing = state.get("editing_snippet", None)
        self.mark_dirty()
        if editing:
            self._suspend_cache = True
            self.text_area.blockSignals(True)
            snippet_key = f"{editing[0]}_{editing[1]}"
            cat_data = self.data["categories"].get(editing[0])
            slot = cat_data[editing[1]] if cat_data and editing[1] < len(cat_data) else None
            if slot and snippet_key in self.snippet_docs:
                doc = self.snippet_docs[snippet_key]
                if doc.toPlainText() != slot.get("text", ""):
                    self._set_plain_text_clean(doc, slot["text"])
                self.text_area.set_active_document(doc)
            else:
                doc = QTextDocument()
                doc.setDefaultFont(self.text_area.font())
                if slot:
                    doc.setPlainText(slot.get("text", ""))
                self.text_area.set_active_document(doc)
            self.text_area.blockSignals(False)
            self._restore_centered_blocks()
            self._restore_aligned_blocks()
            self.editing_snippet = editing
            self.btn_save.setText(tr("Save Snippet", getattr(self, "_current_lang", "EN")))
            theme_name = self.data.get("theme", "Default")
            if theme_name in THEMES:
                self.btn_save.setStyleSheet(THEMES[theme_name].get("btn_save_snippet", ""))
            self._suspend_cache = False
        else:
            self._suspend_cache = True
            self.cancel_editing()
            self.active_is_archive = active_is_archive
            if active_is_archive:
                if active_slot < len(self.data["archive_temp_presets"]):
                    self._switch_to_slot(active_slot, initial=True, is_archive=True)
            elif active_slot < len(self.data["temp_presets"]):
                self._switch_to_slot(active_slot, initial=True)
            self._suspend_cache = False
        self.refresh_temp_presets()
        self.refresh_archive_panel()

    def toggle_trash_vision(self, checked):
        self.data["trash_vision"] = "True" if checked else "False"
        if checked:
            if "Trash" not in self.data["categories"]:
                self.data["categories"]["Trash"] = []
            if "Trash" not in self.data["cats_order"]:
                self.data["cats_order"].append("Trash")
        else:
            if "Trash" in self.data["cats_order"]:
                self.data["cats_order"].remove("Trash")
        self.mark_dirty()
        self.refresh_categories()

    def on_sound_toggled(self, checked):
        """Handle UI sound toggle."""
        self.data["sound_ui"] = "True" if checked else "False"
        self.mark_dirty()

    def on_typewriter_toggled(self, checked):
        """Handle typewriter sound toggle."""
        self.data["sound_typewriter"] = "True" if checked else "False"
        self.mark_dirty()

    def on_cs_style_toggled(self, checked):
        """Handle CS 1.6 UI style toggle."""
        self.data["cs_style"] = "True" if checked else "False"

        # Apply or restore CS style sounds
        sound_events = self.data.setdefault("sound_events", {})
        if not isinstance(sound_events, dict):
            sound_events = {}
            self.data["sound_events"] = sound_events

        # cs_style/ is a real subfolder — these three used to be named as if
        # they sat at the top level, which after the library rename pointed
        # the whole style at files that do not exist.
        cs_mappings = {
            "hover": "cs_style/buttonrollover.wav",
            "click": "cs_style/buttonclick.wav",
            "button_click": "cs_style/buttonclick.wav",
            "button_release": "cs_style/buttonclickrelease.wav",
        }

        if checked:
            # Save current mappings before applying CS style
            saved_mappings = self.data.setdefault("saved_sound_mappings", {})
            for event in cs_mappings.keys():
                if event in sound_events and isinstance(sound_events[event], dict):
                    saved_mappings[event] = sound_events[event].get("file", "")

            # Apply CS style
            for event, sound_file in cs_mappings.items():
                if event not in sound_events:
                    sound_events[event] = {}
                if not isinstance(sound_events[event], dict):
                    sound_events[event] = {}
                sound_events[event]["file"] = sound_file
                sound_events[event]["enabled"] = "True"
        else:
            # Restore previous mappings
            saved_mappings = self.data.get("saved_sound_mappings", {})
            if not isinstance(saved_mappings, dict):
                saved_mappings = {}
            for event in cs_mappings.keys():
                if event in saved_mappings:
                    # saved_mappings[event] is a string (the file name) or empty
                    if saved_mappings[event]:
                        if event not in sound_events:
                            sound_events[event] = {}
                        if not isinstance(sound_events[event], dict):
                            sound_events[event] = {}
                        sound_events[event]["file"] = saved_mappings[event]
                    else:
                        # Was using default, remove override
                        if event in sound_events and isinstance(sound_events[event], dict) and "file" in sound_events[event]:
                            del sound_events[event]["file"]

        self.mark_dirty()
        self.build_categories()
        self.mark_dirty()

    def _save_undo_state(self):
        if not hasattr(self, "_undo_timer"):
            from PyQt6.QtCore import QTimer
            self._undo_timer = QTimer(self)
            self._undo_timer.setSingleShot(True)
            self._undo_timer.setInterval(1000)
            self._undo_timer.timeout.connect(self._dispatch_undo_save)
        # P0-2/P1-8: the target path AND the stacks are captured HERE, at ARM
        # time, coalesced per undo file. The old code captured the path at
        # dispatch (1s later), so a profile switch inside the debounce window
        # filed the outgoing profile's undo snapshot into the INCOMING
        # profile's undo file. Re-arming for the same path replaces the
        # pending snapshot (debounce coalescing preserved); a switch arms a
        # different path and gets its own snapshot.
        db_path = getattr(self.state, "db_path", "")
        if not db_path:
            return
        undo_path = os.path.splitext(db_path)[0] + "_undo.json"
        self._undo_pending_jobs[undo_path] = {
            "undo": list(getattr(self, "data_undo_stack", [])),
            "redo": list(getattr(self, "data_redo_stack", [])),
        }
        if not self._undo_timer.isActive():
            self._undo_timer.start()

    def _dispatch_undo_save(self):
        """Persist pending undo snapshots through ONE coalescing writer.

        Deliberate design (Phase-11 inventory): undo history is SECONDARY
        data. The write is atomic (temp + os.replace), so an interrupted
        write can never corrupt the file — a forced exit mid-write loses at
        most the latest PERSISTED UNDO HISTORY, never primary data. The
        SQLite database and the daily Markdown snapshots remain authoritative.
        No QWidget is touched from the thread.

        T-817: the old code spawned a fresh daemon thread per dispatch; when
        JSON/disk work outran the 1 s debounce the threads piled up, each
        carrying its own snapshot, all serialized behind ``_undo_save_lock``.
        Every dispatch now coalesces into ``_undo_save_backlog`` — the newest
        pending snapshot per undo path (arm-time capture preserved, P1-8) —
        and hands the whole backlog to AT MOST ONE physical writer thread
        (``fastprompter-undo-write``), which is persistent: it waits on
        ``_undo_save_cv`` and only exits after ``_wait_for_undo_saves`` has
        signalled quit with an empty backlog, so a snapshot can never be lost
        to a dying-writer race.

        The thread is registered in ``_undo_save_threads`` BEFORE start and
        removes itself in ``finally``, so ``_wait_for_undo_saves`` observes
        every real writer and a clean drain is a fact, not an empty-set
        coincidence (P1-2). A publication failure is recorded on the window
        so a shutdown cannot claim a clean undo drain that never happened
        (P1-3)."""
        import threading
        if self._undo_timer is not None:
            self._undo_timer.stop()
        pending = getattr(self, "_undo_pending_jobs", {})
        if not pending:
            return
        self._undo_pending_jobs = {}
        # P1-8: failure is tracked PER JOB, not on one window-wide flag. The
        # flag stays as a compat backstop for ``_shutdown_application``; the
        # writer's job record in ``_undo_save_jobs`` carries the truth.
        self._undo_save_failed = False
        cv = getattr(self, "_undo_save_cv", None)
        with cv:
            self._undo_save_backlog.update(pending)
            writer = getattr(self, "_undo_save_writer", None)
            if writer is None or not writer.is_alive():
                self._undo_save_quit = False
                self._undo_save_writer = threading.Thread(
                    target=self._undo_writer_loop, daemon=True,
                    name="fastprompter-undo-write")
                self._undo_save_threads.add(self._undo_save_writer)
                self._undo_save_jobs[self._undo_save_writer] = {"ok": True}
                self._undo_save_writer.start()
            else:
                cv.notify_all()

    def _undo_writer_loop(self):
        """Single physical undo writer: pops the newest snapshot per path,
        publishes it atomically, waits for more work until told to quit."""
        import threading
        cv = getattr(self, "_undo_save_cv", None)
        try:
            while True:
                with cv:
                    backlog = self._undo_save_backlog
                    if not backlog:
                        if getattr(self, "_undo_save_quit", False):
                            break
                        cv.wait()
                        continue
                    path, job = backlog.popitem()
                self._write_undo_file(path, job)
        finally:
            threads = getattr(self, "_undo_save_threads", None)
            if threads is not None:
                threads.discard(threading.current_thread())
            # The job record is LEFT in place (pruned by
            # _wait_for_undo_saves): popping it here would erase the
            # very failure a later dispatch's flag reset depends on.

    def _write_undo_file(self, undo_path, job):
        """Publish one snapshot atomically; record failure per job (P1-3)."""
        import json
        import os
        import threading
        try:
            # Cap the persisted snapshots to prevent bloat (H-302)
            undo_data = job["undo"][-10:]
            redo_data = job["redo"][-10:]
            tmp_path = undo_path + ".tmp"

            # Serialize the save and make it atomic (H-301)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"undo": undo_data, "redo": redo_data}, f)
            try:
                os.replace(tmp_path, undo_path)
            except OSError as exc:
                # The previous final undo file stays untouched; the temp is
                # removed so no stray file can be mistaken for published
                # state. The failure is recorded and logged — a silent `pass`
                # made callers believe the drain succeeded (P1-3).
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
                job_rec = self._undo_save_jobs.get(threading.current_thread())
                if job_rec is not None:
                    job_rec["ok"] = False
                self._undo_save_failed = True
                from fastprompter.core.logging import logger
                logger.error(
                    "Failed to publish undo state to %s: %s; the "
                    "previous undo file is untouched",
                    undo_path, exc)
        except Exception:
            job_rec = self._undo_save_jobs.get(threading.current_thread())
            if job_rec is not None:
                job_rec["ok"] = False
            self._undo_save_failed = True
            from fastprompter.core.logging import logger
            logger.exception("Failed to save undo state.")

    def _wait_for_undo_saves(self, timeout_s=2.0):
        """Force the newest pending undo snapshot out, then wait bounded
        time for every tracked undo-file writer to retire.

        A pending 1s debounce timer is force-dispatched HERE so the latest
        undo history cannot be dropped by an immediate switch/exit. The wait
        joins the REAL tracked writers (the threads were never registered
        before, so the old wait observed an empty set); the result is False
        when a writer is still alive after the deadline OR any tracked writer
        reported a publication failure (P1-2/P1-3)."""
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        timer = getattr(self, "_undo_timer", None)
        if timer is not None and timer.isActive():
            self._dispatch_undo_save()
        writer = getattr(self, "_undo_save_writer", None)
        cv = getattr(self, "_undo_save_cv", None)
        if writer is not None and writer.is_alive() and cv is not None:
            with cv:
                self._undo_save_quit = True
                cv.notify_all()
            writer.join(max(0.0, deadline - time.monotonic()))
        threads = getattr(self, "_undo_save_threads", set())
        threads.difference_update(t for t in threads if not t.is_alive())
        if threads:
            return False
        jobs = getattr(self, "_undo_save_jobs", {})
        had_failure = any(not job.get("ok", True) for job in jobs.values())
        # prune dead job records regardless of failure, so a later successful
        # retry can report clean (W2-003). Live writer's record is kept.
        for t in [t for t in list(jobs.keys()) if not t.is_alive()]:
            jobs.pop(t, None)
        if had_failure:
            return False
        return not getattr(self, "_undo_save_failed", False)

    def _load_undo_state(self):
        """Load THIS profile's persisted undo file (keyed off the CURRENT
        state.db_path). A malformed or foreign file yields an empty stack —
        never a stack that mixes profiles."""
        import json
        import os
        try:
            db_path = getattr(self.state, "db_path", "")
            if not db_path:
                return
            undo_path = os.path.splitext(db_path)[0] + "_undo.json"
            if os.path.exists(undo_path):
                with open(undo_path, encoding="utf-8") as f:
                    raw = json.load(f)
                # validate shape: undo/redo must be LISTS. A structurally
                # foreign or corrupt file must not be adopted silently.
                undo = raw.get("undo", []) if isinstance(raw, dict) else []
                redo = raw.get("redo", []) if isinstance(raw, dict) else []
                if not isinstance(undo, list) or not isinstance(redo, list):
                    raise ValueError("undo file has non-list stacks")
                # CORE-014: one quarantine policy — entries that pass the JSON
                # container check but fail the executable-snapshot schema are
                # discarded here, never handed to apply.
                self.data_undo_stack = [s for s in undo
                                        if isinstance(s, dict) and self._snapshot_is_valid(s)]
                self.data_redo_stack = [s for s in redo
                                        if isinstance(s, dict) and self._snapshot_is_valid(s)]
            else:
                self.data_undo_stack = []
                self.data_redo_stack = []
        except Exception as e:
            from fastprompter.core.logging import logger
            logger.error(f"Failed to load undo state: {e}")
            self.data_undo_stack = []
            self.data_redo_stack = []

    def add_data_undo_state(self, _action_name=""):
        """Push a before-state snapshot of the current data.

        Returns the pushed snapshot, or None when the new state equals the
        top of the stack and nothing was pushed (dedup). `_switch_to_slot`
        uses the return value to re-stamp its "Switch silo" entry against
        the document it lands on; callers that do not care may ignore it.
        """
        if not hasattr(self, "data_undo_stack"):
            self.data_undo_stack = []
        if not hasattr(self, "data_redo_stack"):
            self.data_redo_stack = []
        if _action_name == "Switch silo":
            # PERF-006: navigation undo is a COMPACT record, not a deep
            # copy of the whole data universe. It carries only the
            # coordinates needed to reverse the switch plus routing metadata;
            # Ctrl+Z of a pure switch must never depend on unrelated
            # snippet/silo content. Full mutation snapshots are reserved for
            # operations that actually change data.
            state = {
                "_switch": True,
                "category": self.get_current_category(),
                "active_temp_slot": self.active_temp_slot,
                "active_is_archive": bool(
                    getattr(self, "active_is_archive", False)),
                "editing_snippet": getattr(self, "editing_snippet", None),
            }
        else:
            state = self._snapshot_current()
        # Never push a snapshot identical to the top — no-op pileups make
        # the skip logic walk into unrelated (even cross-tab) history.
        # Compared without the ordering metadata, which differs every time.
        if self.data_undo_stack and self._same_snapshot(self.data_undo_stack[-1], state):
            return None
        self._stamp_snapshot(state)
        self.data_undo_stack.append(state)
        self._push_undo_state(state, _action_name)
        return state

    # ------------------------------------------------------------------
    # PERF-002: compact metadata undo records.
    # ------------------------------------------------------------------

    _COMPACT_META_KINDS = frozenset({"tick", "pin", "theme", "gap_name"})

    def add_compact_meta_undo(self, kind, coords, old):
        """Push a CONSTANT-SIZE undo record for one tiny reversible value.

        A tick, pin, theme switch or gap rename used to deep-copy the entire
        project (every category's snippet slots, every silo's text, all
        ownership maps) just to remember one bool/string — and the persisted
        undo JSON then re-serialized that whole universe up to ten times.
        Compact records store only the operation kind, its owner coordinates
        and the pre-action value; ``_finish_compact_meta_undo`` stamps the
        post-action value so Ctrl+Y can rebuild the inverse without ever
        touching unrelated content. Reserved for operations that CANNOT
        remap slot ownership or mutate text/filesystem state."""
        if kind not in self._COMPACT_META_KINDS:
            raise ValueError(f"unknown compact undo kind: {kind!r}")
        if not hasattr(self, "data_undo_stack"):
            self.data_undo_stack = []
        if not hasattr(self, "data_redo_stack"):
            self.data_redo_stack = []
        state = {"_compact": kind, "coords": coords, "old": old}
        self._stamp_snapshot(state)
        self.data_undo_stack.append(state)
        self.data_redo_stack.clear()
        self._undo_kinds().clear()
        self._last_data_action_time = state["_seq"]
        return state

    def _finish_compact_meta_undo(self, state, new):
        """Stamp the post-mutation value onto a compact record."""
        if state is not None and isinstance(state, dict):
            state["new"] = new
            self._save_undo_state()
        return state

    def _apply_compact_meta(self, state, target_value):
        """Apply one compact metadata record's value (GUI thread)."""
        kind = state.get("_compact")
        coords = state.get("coords")
        if kind == "tick":
            lst = self._slot_list("silo_ticked")
            idx = coords
            if target_value:
                if idx not in lst:
                    lst.append(idx)
            elif idx in lst:
                lst.remove(idx)
        elif kind == "pin":
            lst = self._slot_list("pinned_silos")
            idx = coords
            if target_value:
                if idx not in lst:
                    lst.insert(0, idx)
            elif idx in lst:
                lst.remove(idx)
        elif kind == "theme":
            self.data["theme"] = target_value
            self._refresh_theme_cache()
            self.apply_theme()
        elif kind == "gap_name":
            cat, slot = coords
            names_all = self.data.setdefault("silo_gap_names_all", {})
            names = names_all.setdefault(cat, {})
            if target_value:
                names[str(slot)] = target_value
            else:
                names.pop(str(slot), None)
            self.data["silo_gap_names"] = names
        self.mark_dirty()

    def _push_undo_state(self, state, _action_name=""):
        """Shared undo-stack housekeeping: enforce caps, invalidate redo and
        the recorded undo order, bump routing metadata, persist.

        CORE-008: composite cross-project entries (which carry both owners)
        are pushed through this same helper so every stack gets exactly ONE
        logical entry and identical cap/redo semantics.
        """
        # Enforce caps (50 items max, ~20MB max)
        MAX_CHARS = 20_000_000
        while len(self.data_undo_stack) > 50:
            self.data_undo_stack.pop(0)

        while len(self.data_undo_stack) > 1 and sum(_snapshot_text_size(s) for s in self.data_undo_stack) > MAX_CHARS:
            self.data_undo_stack.pop(0)
        self.data_redo_stack.clear()
        # A new action invalidates the recorded undo order too, or Ctrl+Y would
        # try to replay steps that no longer have anything behind them.
        self._undo_kinds().clear()
        # Lets Ctrl+Z pick data undo over text undo when this action is newer
        self._last_data_action_time = state["_seq"]
        self._save_undo_state()
        return state

    def combo_index_for_category(self, name):
        """Return the QComboBox row index for a given category identity.

        -1 when the category is NOT in the combo (hidden or unknown) — the
        old ``0`` fallback silently bound a DIFFERENT visible project
        (P1-1)."""
        idx = self.cat_combo.findData(name)
        return idx if idx >= 0 else -1

    def build_categories(self):
        """Rebuild the tab bar from the VISIBLE projects.

        It used to iterate cats_order raw, which quietly undid T-599: every
        caller (profile switch, undo restore, the Trash toggle) brought
        hidden projects straight back into the combo."""
        self.cat_combo.blockSignals(True)
        while self.cat_combo.count() > 0:
            self.cat_combo.removeItem(0)
        for cat in self.visible_categories():
            self.cat_combo.addItem(cat, cat)
        self.cat_combo.blockSignals(False)
        # BEFORE the index change: setCurrentIndex fires on_tab_changed, which
        # highlights the number buttons — doing it after left that pass
        # painting the OLD row a beat before it was thrown away.
        self._rebuild_cat_numbox()
        if self.cat_combo.count() > 0:
            self.cat_combo.setCurrentIndex(0)
        self.refresh_snippets_panel()

    def _rebuild_cat_numbox(self):
        if not hasattr(self, "cat_numbox"):
            return
        layout = self._cat_numbox_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                # takeAt drops it from the LAYOUT but not from the parent, and
                # deleteLater only schedules the destructor — so without this
                # the button stays in self.findChildren(QWidget) while already
                # dead on the C++ side. theme_mixin's font/theme pass walks
                # exactly that list calling styleSheet()/unpolish/polish, and
                # touching a destroyed object there is an access violation,
                # not an exception: the process dies with no traceback.
                w.setParent(None)
                w.deleteLater()
        self._cat_num_buttons = []
        cats = self.visible_categories()
        per_row = self.numbox_per_row()
        size = self.numbox_button_size()
        for i, cat in enumerate(cats):
            btn = QPushButton(str(i + 1))
            btn.setFixedSize(size, size)
            btn.setCheckable(True)
            btn.setToolTip(f"{i + 1}: {cat}")
            idx = i
            btn.clicked.connect(lambda _c, n=idx: self._cat_numbox_clicked(n))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, n=idx: self._cat_numbox_context(n, pos))
            layout.addWidget(btn, i // per_row, i % per_row)
            self._cat_num_buttons.append(btn)
        self._update_cat_numbox_active()

    def _schedule_numbox_rebuild(self, *_args):
        """Rebuild the number row once, after the combo has settled.

        Clearing and refilling the combo fires a signal per row, and each
        rebuild throws away and recreates every button — so this coalesces to
        one pass on the next tick instead of N passes mid-edit.
        """
        if sip.isdeleted(self) or getattr(self, "_numbox_rebuild_pending", False):
            return
        self._numbox_rebuild_pending = True

        def run():
            if sip.isdeleted(self):
                return
            self._numbox_rebuild_pending = False
            self._rebuild_cat_numbox()

        QTimer.singleShot(0, run)

    def numbox_per_row(self):
        """How many number boxes fit on one row before wrapping (1..100)."""
        try:
            return max(1, min(100, int(self.data.get("numbox_per_row", 10))))
        except (TypeError, ValueError):
            return 10

    def numbox_button_size(self):
        """Edge length of one number box, in px (14..40)."""
        try:
            return max(14, min(40, int(self.data.get("numbox_btn_size", 22))))
        except (TypeError, ValueError):
            return 22

    def _cat_numbox_clicked(self, idx):
        if 0 <= idx < self.cat_combo.count():
            self.cat_combo.setCurrentIndex(idx)

    def _cat_numbox_context(self, idx, pos):
        if 0 <= idx < self.cat_combo.count():
            self.cat_combo.setCurrentIndex(idx)
            # the click landed on the BUTTON, so the button is the anchor —
            # switching first can rebuild the row, so re-read it by index
            if 0 <= idx < len(self._cat_num_buttons):
                self.show_cat_context_menu(pos, anchor=self._cat_num_buttons[idx])

    def _update_cat_numbox_active(self):
        if not hasattr(self, "_cat_num_buttons"):
            return
        idx = self.cat_combo.currentIndex()
        for i, btn in enumerate(self._cat_num_buttons):
            btn.setChecked(i == idx)

    def _reload_fast_zone_pages(self):
        """Refill the Fast-mode page picker. The Presets page only exists
        once the user has saved one, so this is re-run after the presets
        dialog rather than built once."""
        combo = getattr(self, "cb_fast_zone_page", None)
        if combo is None or sip.isdeleted(combo):
            return
        from fastprompter.ui.fancy_zones import layouts_for
        current = self.data.get("fancyzones_layout", "")
        combo.blockSignals(True)
        combo.clear()
        names = [name for name, _zones in layouts_for(self.data)]
        for name in names:
            combo.addItem(tr(name, self._current_lang), name)
        if current in names:
            combo.setCurrentIndex(names.index(current))
        combo.blockSignals(False)

    def _on_fast_zone_page_changed(self, idx):
        name = self.cb_fast_zone_page.itemData(idx)
        if not name:
            return
        self.data["fancyzones_layout"] = name
        # a different page has a different number of zones, so the remembered
        # position in the cycle no longer means anything
        self.data["fancyzones_fast_idx"] = "-1"
        self.mark_dirty()

    def open_window_presets(self):
        from fastprompter.ui.window_presets_dialog import WindowPresetsDialog
        self._increment_focus_lock()
        try:
            WindowPresetsDialog(self).exec()
        finally:
            # the Presets page appears/disappears with the preset list, so the
            # Fast-mode page picker has to be refilled after this dialog
            self._reload_fast_zone_pages()
            QTimer.singleShot(300, self._decrement_focus_lock)

    def _on_token_mode_changed(self, idx):
        mode = self.cb_token_mode.itemData(idx) or "chars"
        self.data["token_mode"] = mode
        self.data["token_weight"] = "4.0" if mode == "chars" else "1.33"
        self.spin_token_weight.blockSignals(True)
        self.spin_token_weight.setValue(float(self.data["token_weight"]))
        self.spin_token_weight.blockSignals(False)
        self._update_token_count_label()
        self.mark_dirty()

    def _on_token_weight_changed(self, value):
        self.data["token_weight"] = str(float(value))
        self._update_token_count_label()
        self.mark_dirty()

    def _cycle_token_mode(self):
        """Click the token label to flip chars <-> words weighting."""
        modes = self.TOKEN_MODES
        cur = self.data.get("token_mode", "chars")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else modes[0]
        self.data["token_mode"] = nxt
        # the default weight differs per mode, so reset it with the mode
        self.data["token_weight"] = "4.0" if nxt == "chars" else "1.33"
        if hasattr(self, "cb_token_mode"):
            self.cb_token_mode.setCurrentIndex(modes.index(nxt))
        if hasattr(self, "spin_token_weight"):
            self.spin_token_weight.setValue(float(self.data["token_weight"]))
        self._update_token_count_label()
        self.mark_dirty()

    def _on_numbox_geometry_changed(self, key, value):
        # stored as a string like every other settings value — the DB layer
        # round-trips strings, and the readers above int() them back
        self.data[key] = str(int(value))
        self._rebuild_cat_numbox()
        self.mark_dirty()

    def _toggle_numbox_mode(self, checked):
        self.data["numbox_tabs"] = "True" if checked else "False"
        self.cat_combo.setVisible(not checked)
        self.cat_numbox.setVisible(checked)
        if checked:
            self._rebuild_cat_numbox()
        self.mark_dirty()

    def _sync_silo_folder(self, cat, old_text, new_text):
        """No-op. Folder identity is owned by the per-slot silo_folders map
        (see _silo_folder_name), which follows retitles itself; a title-based
        rename here would fight the map (and re-allocate category folders).
        Kept only because callers still invoke it on the retitle path."""
        return

    def _flush_live_editor(self, current_text):
        """Copy the live editor text into its owning store.

        Snippet mode writes the exact editor text into the referenced
        snippet, refreshes its last-edited metadata and marks the snippets
        domain dirty when the value changed. Silo mode keeps the established
        per-slot alias behaviour. This is the single synchronous owner flush
        used by every authoritative save and owner transition."""
        if self.editing_snippet:
            cat_snip, idx = self.editing_snippet
            if cat_snip in self.data["categories"] and self.data["categories"][cat_snip][idx]:
                item = self.data["categories"][cat_snip][idx]
                old_text = item.get("text")
                if old_text != current_text:
                    item["text"] = current_text
                    item["last_edited"] = int(time.time())
                    self.mark_dirty("snippets")
        else:
            is_arc = getattr(self, "active_is_archive", False)
            target = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
            if 0 <= self.active_temp_slot < len(target):
                old_text = target[self.active_temp_slot]
                target[self.active_temp_slot] = current_text
                if current_text != old_text:
                    self.mark_dirty("arc" if is_arc else "temp")
                    self.silo_last_edited[self.active_temp_slot] = int(time.time())
                    self._update_active_silo_ui()

    def commit_current_text(self):
        """Commit the current text to the active slot."""
        if getattr(self, "_initializing_ui", False):
            return
        current_text = self.text_area.toPlainText()
        self._flush_live_editor(current_text)

    def open_color_settings(self):
        from fastprompter.ui.settings import ColorConfigDialog
        dlg = ColorConfigDialog(self)
        self.ignore_focus_loss = True
        try:
            dlg.exec()
        finally:
            self.ignore_focus_loss = False

    def backup_db(self):
        from fastprompter.ui.backup_dialog import BackupDialog

        dlg = BackupDialog(self)
        self._increment_focus_lock()
        try:
            dlg.exec()
        finally:
            QTimer.singleShot(300, self._decrement_focus_lock)

    def restore_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Backup", "", "SQLite DB (*.db *.bak);;All Files (*)"
        )
        if not path:
            return
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                tr("Confirm", self._current_lang),
                tr("App will restart. Proceed?", self._current_lang),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                db_path = self.state.db_path
                # CORE-002: a refused restore leaves the ORIGINAL file untouched,
                # so the safest recovery of the user's unsaved edits is to commit
                # the current memory to that same file BEFORE any destructive
                # runtime change. If that commit fails, abort the restore while
                # the live connection is still open — never strand a failed
                # save behind a closed connection.
                if not self.save_data_to_db(force=True):
                    from fastprompter.core.logging import logger as _log
                    _log.error("Restore aborted: live save failed; the live "
                               "database is unchanged")
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang),
                        tr("Restore aborted — your current data could not be "
                           "saved; nothing was touched.", self._current_lang))
                    return
                # T-809: the watcher must quiesce BEFORE we close the live DB or
                # replace it. A failed quiesce aborts the restore (the restored
                # file is already on disk, but we must not strand the app running
                # on stale in-memory state against it, nor bypass the barrier).
                if hasattr(self, "_watcher_begin_quiesce"):
                    try:
                        restored_quiesced = self._watcher_begin_quiesce()
                    except Exception:
                        restored_quiesced = False
                else:
                    restored_quiesced = True
                if not restored_quiesced:
                    from fastprompter.core.logging import logger as _log
                    _log.error("Restore aborted: watcher did not quiesce; the live database is unchanged")
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang),
                        tr("Restore aborted — the watcher was still busy; try "
                           "again once it settles.", self._current_lang))
                    return
                # close the live connection FIRST: SQLite keeps the file
                # locked while a connection is open
                if self.state.conn:
                    self.state.conn.close()
                    self.state.conn = None
                self.conn = None
                time.sleep(0.1)
                from fastprompter.core.state import (
                    FatalRestoreError,
                    RestoreError,
                    restore_database,
                )
                try:
                    restore_database(path, db_path)
                except FatalRestoreError as e:
                    # The live database could not be left consistent in-process
                    # (the swap failed AND the WAL/SHM could not be rolled
                    # back). It was repaired from the safety snapshot on disk,
                    # but per T-808 we must NOT reopen the live incarnation
                    # here — a restart reloads the repaired file. Do not call
                    # init_db; keep the connection closed.
                    #
                    # CORE-009: follow the state contract — this is a TERMINAL
                    # transition. The in-memory (RAM) edits must NOT be written
                    # back over the now-repaired on-disk DB, so mark logical
                    # persistence finalized (the controlled quit path then skips
                    # the final save) and exit through quit_app(), leaving the
                    # user to restart on the known-good database.
                    from fastprompter.core.logging import logger as _log
                    _log.exception("restore failed fatally: %s", e)
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang),
                        tr("Restore failed and the live database could not be "
                           "left consistent. It has been repaired from the "
                           "automatic safety snapshot on disk — restart "
                           "FastPrompter to reload it.", self._current_lang))
                    self._restore_stale_memory = True
                    self._logical_finalized = True
                    self._watcher_commit_quiesce()
                    self.quit_app()
                    return
                except RestoreError as e:
                    # CORE-002: the original file is untouched. The in-memory
                    # state we just committed is the authoritative latest — do
                    # NOT reload disk via init_db (that would discard the RAM
                    # edits and clear dirty).
                    #
                    # CORE-009: regaining a valid persistence connection is
                    # mandatory before resuming an editable runtime. Only
                    # reopen-then-resume when the reopen SUCCEEDED; a failed
                    # reopen leaves conn=None and must NOT resume editing
                    # (which would then run disconnected and silently lose
                    # work). On failure enter the same terminal/exit path.
                    from fastprompter.core.logging import logger as _log
                    _log.exception("restore refused: %s", e)
                    if not self._reopen_live_connection():
                        _log.error("restore refused but live connection could "
                                   "not be reopened; entering terminal state")
                        QMessageBox.critical(
                            self, tr("Error", self._current_lang),
                            tr("Restore refused and the database connection "
                               "could not be reopened. FastPrompter will close "
                               "to avoid losing data — restart it.",
                               self._current_lang))
                        self._restore_stale_memory = True
                        self._logical_finalized = True
                        self._watcher_commit_quiesce()
                        self.quit_app()
                        return
                    self._resume_watcher_runtime()
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang),
                        tr("Restore refused — your current database was left "
                           "untouched:\n{}", self._current_lang).format(e))
                    return
                # P0: successful restore is a terminal, already-committed
                # transition. The on-disk DB is now the restored copy and the
                # in-memory state is stale with its connection closed. Do NOT
                # run the normal final-save path — it would rewrite the old
                # memory over the restored file, or refuse and strand the app
                # running on stale data against a replaced database. Mark
                # logical persistence finalized ONLY AFTER the successful restore
                # (the quiesce barrier above already passed) and quit straight
                # through the physical teardown without any further save.
                #
                # W2-002: the restored DB is authoritative, so the pre-restore
                # RAM must never publish again. Activate the terminal stale-RAM
                # guard THE INSTANT the restore commits — before quit_app enters
                # shutdown, which can otherwise capture a stale mirror snapshot
                # or drain stale Sync-Project writes over the restored state.
                self._restore_stale_memory = True
                self._logical_finalized = True
                # W2-001: the restore committed — resolve the paused watcher by
                # performing the irreversible disarm now.
                self._watcher_commit_quiesce()
                self.quit_app()
        except Exception as e:
            QMessageBox.critical(self, tr("Error", self._current_lang), tr("Failed to restore backup:\n{}", self._current_lang).format(e))
            # CORE-002/CORE-009: a hard failure must also roll the runtime back
            # to the pre-restore state — keep the live memory and reopen the
            # connection. Only resume the watcher when the reopen actually
            # succeeded; a failed reopen is a terminal transition that must not
            # leave the app editable against a disconnected database.
            if not self._reopen_live_connection():
                from fastprompter.core.logging import logger as _log
                _log.error("restore hard-failure and live connection could not "
                           "be reopened; entering terminal state")
                self._restore_stale_memory = True
                self._logical_finalized = True
                self.quit_app()
                return
            self._resume_watcher_runtime()
        finally:
            self.ignore_focus_loss = False

    def _reopen_live_connection(self):
        """Reopen the live SQLite connection to the SAME db_path without
        reloading disk (CORE-002). Use after a refused/failed restore where
        the original file is untouched and the in-memory state is still
        authoritative — reloading via init_db would discard the RAM edits.

        Returns True only when a usable connection was established; callers
        must NOT resume an editable runtime (CORE-009) on False.
        """
        import sqlite3
        try:
            conn = sqlite3.connect(self.state.db_path, check_same_thread=False)
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            self.state.conn = conn
            self.conn = conn
            return True
        except Exception as e:
            from fastprompter.core.logging import logger as _log
            _log.exception("failed to reopen live connection after restore "
                           "refusal: %s", e)
            self.state.conn = None
            self.conn = None
            return False

    def _resume_watcher_runtime(self):
        """Resume the watcher loop after a refused/failed restore or a
        refused profile switch (CORE-002 / CORE-005).

        CORE-005: rollback ownership belongs to ONE implementation. While
        `_watcher_quiescing` is set this delegates to the canonical
        `_watcher_rollback_quiesce`, which restarts the timer AND clears the
        flag — the legacy timer-only resume left the flag set forever, so an
        armed, running watcher silently dropped every future dispatch.
        Outside a quiesce it keeps the historical behaviour of restarting an
        armed engine's tick timer."""
        try:
            if getattr(self, "_watcher_quiescing", False):
                self._watcher_rollback_quiesce()
                return
            engine = getattr(self, "_watcher_engine", None)
            if engine is not None and getattr(engine, "armed", False):
                self._watcher_start_timer()
        except Exception:
            from fastprompter.core.logging import logger as _log
            _log.exception("failed to resume watcher runtime after restore "
                           "refusal")

    def fill_silo_from_preset(self, idx, text):
        """Drop a template into silo `idx`, as ONE undoable action."""
        presets = self.data.get("temp_presets", [])
        if not (0 <= idx < len(presets)):
            return
        # P2: validate the slot bounds BEFORE pushing undo history. A stale
        # menu/action index must not create and persist an undo step that
        # perturbs Ctrl+Z ordering when no application state changes.
        self.add_data_undo_state("Silo preset")
        presets[idx] = text
        if 0 <= idx < len(self.silo_docs) and self.silo_docs[idx] is not None:
            self._set_plain_text_clean(self.silo_docs[idx], text)
        if idx == self.active_temp_slot and not getattr(self, "active_is_archive", False):
            self._set_plain_text_clean(self.text_area, text)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _add_silo_preset_actions(self, menu, on_pick):
        """Fill `menu` with one action per template. Returns how many."""
        from fastprompter.core.silo_presets import load_presets

        entries = load_presets()
        for label, text in entries:
            menu.addAction(label, lambda t=text: on_pick(t))
        return len(entries)

    def show_new_silo_presets(self, pos=None):
        """Middle-click on NEW: pick a template and create the silo with it."""
        from PyQt6.QtGui import QCursor

        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())
        if not self._add_silo_preset_actions(menu, self._new_silo_with_text):
            return
        # popup(), not exec(): this is raised from a mouse-release handler, and
        # exec() spins its own event loop that BLOCKS the caller until the menu
        # closes. Measured the hard way — a suite run stopped dead at 79% with
        # zero CPU for fifteen minutes because a test reached this method.
        self._new_preset_menu = menu          # keep it alive; WA_DeleteOnClose frees it
        menu.popup(pos if pos is not None else QCursor.pos())

    def _new_silo_with_text(self, text):
        self.select_empty_silo(insertion="top")
        self.fill_silo_from_preset(self.active_temp_slot, text)

    def toolbar_at_bottom(self):
        return self.data.get("toolbar_position", "top") == "bottom"

    def apply_toolbar_position(self, bottom=None):
        """Toolbar above the editor or below it.

        `main_layout` is the central QVBoxLayout — header, mini settings,
        splitter — so this is a move within one layout, not a rebuild: every
        button keeps its widget, its order and its drag-reorder wiring.
        """
        if bottom is None:
            bottom = self.toolbar_at_bottom()
        bottom = bool(bottom)
        self.data["toolbar_position"] = "bottom" if bottom else "top"
        hw = getattr(self, "header_widget", None)
        if hw is None or sip.isdeleted(hw):
            return
        self.main_layout.removeWidget(hw)
        if bottom:
            self.main_layout.addWidget(hw)
        else:
            self.main_layout.insertWidget(0, hw)
        self.mark_dirty()

    def silo_tabs_mode(self):
        return self.data.get("silo_tabs_mode", "sidebar") == "tabs"

    def apply_silo_tabs_mode(self, tabs=None):
        """Silos as the left sidebar, or as a horizontal tab strip.

        The SAME widgets move between two hosts: nothing is rebuilt, so the
        drag machinery, the page buttons and every refresh path keep working
        in both modes — `SiloDropWidget.set_horizontal` only swaps the axis.
        Children have no room on a bar, so in tab mode they are reached
        through the parent's context menu (see `show_temp_menu`).
        """
        if tabs is None:
            tabs = self.silo_tabs_mode()
        tabs = bool(tabs)
        self.data["silo_tabs_mode"] = "tabs" if tabs else "sidebar"
        section = getattr(self, "silos_section", None)
        if section is None:
            return
        was_visible = section.isVisible()
        self.silos_widget.set_horizontal(tabs)
        # The page buttons are the same buttons, pointing a different way.
        self.btn_silo_up.setText("◀" if tabs else "▲")
        self.btn_silo_down.setText("▶" if tabs else "▼")
        if tabs:
            self.left_panel_layout.removeWidget(section)
            self.silos_section_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            section.setMaximumHeight(64)
            self.center_layout.insertWidget(0, section)
        else:
            self.center_layout.removeWidget(section)
            self.silos_section_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            section.setMaximumHeight(16777215)
            self.left_panel_layout.addWidget(section, 1)
        # A tab strip that is not on screen is not a tab strip; in sidebar
        # mode keep whatever visibility the panel already had.
        section.setVisible(True if tabs else was_visible)
        self.refresh_temp_presets()
        self.mark_dirty()

    def _position_archive_overlay(self):
        if not hasattr(self, "archive_section") or not hasattr(self, "left_panel"):
            return
        self.archive_section.setFixedWidth(self.left_panel.width())
        self.archive_section.adjustSize()
        ah = self.archive_section.sizeHint().height()
        lh = self.left_panel.height()
        self.archive_section.move(0, max(0, lh - ah))
        self.archive_section.raise_()

    def on_archive_toggle(self, checked):
        self.play_sound("archive")
        self.data["archive_visible"] = "True" if checked else "False"
        self.archive_section.setVisible(checked)
        if checked:
            self._position_archive_overlay()

        if self.btn_toggle_archive.isChecked() != checked:
            self.btn_toggle_archive.blockSignals(True)
            self.btn_toggle_archive.setChecked(checked)
            self.btn_toggle_archive.blockSignals(False)

        self.mark_dirty()
        self.text_area.setFocus()

    def move_cursor_home(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def move_cursor_end(self):
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()

    def moveEvent(self, event):
        if getattr(self, "is_locked", False) and getattr(self, "_locked_geometry", None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()
        super().moveEvent(event)

    def closeEvent(self, event):
        # never exit leaving the user's desktop minimised on our account
        self.exit_zen_solo()
        # P0-6: quit_app already ran the final save while the event loop was
        # alive (watcher quiesced first); a second save here would race the
        # post-loop teardown, so it is skipped when the pre-quit finalize
        # succeeded.
        if not getattr(self, "_logical_finalized", False):
            saved = True
            try:
                saved = self.save_data_to_db(force=True)
            except Exception:
                from fastprompter.core.logging import logger
                logger.exception("closeEvent: final save failed")
                saved = False
            if not saved:
                # P0: a failed save must not vanish behind a closed/hidden
                # window. Ignore the close, keep and raise the window so the
                # dirty state stays visible and the user can retry or save.
                event.ignore()
                self.show()
                self.raise_()
                self.activateWindow()
                return
        # configured to survive the loss of its last window
        # (setQuitOnLastWindowClosed(False)) and the tray reopens it, so
        # retiring the watcher worker and the Sync writer here would leave a
        # reopened resident process permanently retired. Worker retirement
        # belongs exclusively to _shutdown_application, which runs the same
        # close as part of the single canonical quiesce path.
        super().closeEvent(event)

    def resizeEvent(self, event):
        if getattr(self, "is_locked", False) and getattr(self, "_locked_geometry", None):
            if self.geometry() != self._locked_geometry:
                self.setGeometry(self._locked_geometry)
                return
        self._update_last_geometry()

        # Update edge resizers
        if hasattr(self, "_resizers"):
            t = 6
            w, h = self.width(), self.height()
            self._resizers["left"].setGeometry(0, t, t, h - 2 * t)
            self._resizers["right"].setGeometry(w - t, t, t, h - 2 * t)
            self._resizers["top"].setGeometry(t, 0, w - 2 * t, t)
            self._resizers["bottom"].setGeometry(t, h - t, w - 2 * t, t)
            self._resizers["topleft"].setGeometry(0, 0, t, t)
            self._resizers["topright"].setGeometry(w - t, 0, t, t)
            self._resizers["bottomleft"].setGeometry(0, h - t, t, t)
            self._resizers["bottomright"].setGeometry(w - t, h - t, t, t)
            for r in self._resizers.values():
                r.raise_()

        self._apply_header_density()
        # a wrapping settings panel changes height when the window changes width
        if getattr(self, "mini_settings_frame", None) is not None and                 not sip.isdeleted(self.mini_settings_frame) and                 self.mini_settings_frame.isVisible():
            self._fit_settings_tabs()
        super().resizeEvent(event)

    # def nativeEvent(self, eventType, message):
    #     return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        if sip.isdeleted(self):
            return
        if getattr(self, "is_locked", False):
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if sip.isdeleted(self):
            return
        if getattr(self, "is_locked", False):
            return

        if event.buttons() == Qt.MouseButton.LeftButton:
            if hasattr(self, "_drag_pos"):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()

    def mouseReleaseEvent(self, event):
        if sip.isdeleted(self):
            return
        if hasattr(self, "_drag_pos"):
            del self._drag_pos
            event.accept()

    def showEvent(self, event):
        """Stamp when the window became visible.

        changeEvent uses it as a grace period for the LAUNCH show: a
        foreground flicker right after startup must not count as the user
        clicking away. A show the user asked for skips it — see
        `show_window`.
        """
        self._shown_at = time.time()
        super().showEvent(event)
        # The panel is measured against a WIDTH, and during construction the
        # tabs are still a few pixels wide — a wrapping row measured there
        # reports the height it would need in a sliver, which is how a fresh
        # launch came up with a screenful of dead panel under two rows of
        # checkboxes. The first real geometry only exists now, so re-fit once
        # the event loop has laid the window out.
        if getattr(self, "mini_settings_frame", None) is not None:
            QTimer.singleShot(0, self._fit_settings_tabs)

    def changeEvent(self, event):
        # Zen solo swept the user's desktop clean on our behalf; the moment
        # this window stops being what they are looking at, put it back.
        if getattr(self, "zen_solo", False):
            if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
                self.exit_zen_solo()
            elif (event.type() in (QEvent.Type.ActivationChange,
                                   QEvent.Type.WindowDeactivate)
                    and not self.isActiveWindow()):
                self.exit_zen_solo(grace=True)
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowDeactivate):
            if self.isActiveWindow():
                # The user has it in front now; from here a deactivation is a
                # real "clicked away" and hide-on-focus-loss means something.
                self._ever_activated = True
                self._activated_at = time.time()
            if not self.isActiveWindow() and not self.isMinimized() and self.isVisible():
                # Startup is NOT a focus loss. Windows refuses the foreground
                # to a process launched in the background, so show() was
                # followed straight away by a deactivation and the window hid
                # itself about two seconds in - the app looked like it never
                # started. Measured: visible at t+4s, gone by t+6s.
                if not getattr(self, "_ever_activated", False):
                    return super().changeEvent(event)
                # The foreground can also flicker: the window takes focus for
                # an instant at launch and Windows hands it straight back to
                # whatever started it. That set _ever_activated and the next
                # deactivation hid the window anyway, so a grace period after
                # it is shown covers the flicker without weakening the real
                # click-away behaviour.
                #
                # The grace is for the LAUNCH show only. A window the user
                # summoned with Alt+X is one they are looking at on purpose,
                # and clicking away a moment later has to hide it at once —
                # the blanket grace made the setting look dead for the first
                # two seconds of every summon, which is most of them.
                shown_at = getattr(self, "_shown_at", 0.0)
                if (
                    not getattr(self, "_user_summoned", False)
                    and shown_at
                    and (time.time() - shown_at) < 2.0
                ):
                    return super().changeEvent(event)
                # A summon still has to survive an activation that never
                # settled: SetForegroundWindow can be handed back within a
                # frame or two. No human clicks away that fast, so a short
                # settle window costs nothing and keeps the flicker covered
                # on the summon path too.
                activated_at = getattr(self, "_activated_at", 0.0)
                if activated_at and (time.time() - activated_at) < 0.25:
                    return super().changeEvent(event)
                if getattr(self, "cb_focus", None) and self.cb_focus.isChecked():
                    if (
                        not getattr(self, "ignore_focus_loss", False)
                        and not getattr(self, "is_locked", False)
                        and not self._foreground_is_our_own_window()
                    ):
                        self.hide_and_save()
        super().changeEvent(event)

    def _foreground_is_our_own_window(self):
        """True when the foreground went to another window of OURS.

        "Click-Out" means the user left the app, not that they reached for
        its own furniture. The undocked file container, the pie menu, the
        zone overlay, Help, every dialog — taking focus there deactivates
        the main window exactly like clicking on Notepad does, and hiding
        it dropped the window out from under whatever the user had just
        opened. The ~30 counted focus locks cover the call sites we drive
        ourselves; this covers the ones the USER clicks on directly, and
        anything added later without a lock.
        """
        app = QApplication.instance()
        if app is None:
            return False
        # Menus and modal dialogs never become activeWindow().
        if app.activePopupWidget() is not None or app.activeModalWidget() is not None:
            return True
        active = app.activeWindow()
        if active is None or sip.isdeleted(active):
            # Nothing of ours is in front — the foreground left the app.
            return False
        return active is not self

    def eventFilter(self, obj, event):
        if sip.isdeleted(self) or (obj and sip.isdeleted(obj)):
            return False

        if (obj is getattr(self, "btn_new", None)
                and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.MiddleButton):
            self.show_new_silo_presets(event.globalPosition().toPoint())
            return True

        if obj == getattr(self, "silos_widget", None) and event.type() == QEvent.Type.Resize:
            self._update_visible_silo_count()
            if hasattr(self, "_silo_resize_debounce_timer"):
                self._silo_resize_debounce_timer.start()
            return False

        if obj == getattr(self, "left_panel", None) and event.type() == QEvent.Type.Resize:
            self._position_archive_overlay()
            return False

        if (
            event.type() == QEvent.Type.MouseButtonPress
            and getattr(event, "button", lambda: 0)() == Qt.MouseButton.RightButton
        ):
            if not getattr(self, "is_locked", False):
                self._text_drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return False
        elif (
            event.type() == QEvent.Type.MouseMove
            and getattr(event, "buttons", lambda: 0)() & Qt.MouseButton.RightButton
        ):
            if not getattr(self, "is_locked", False) and hasattr(self, "_text_drag_pos"):
                self.move(event.globalPosition().toPoint() - self._text_drag_pos)
                return True
        elif (
            event.type() == QEvent.Type.MouseButtonRelease
            and getattr(event, "button", lambda: 0)() == Qt.MouseButton.RightButton
        ):
            if hasattr(self, "_text_drag_pos"):
                delattr(self, "_text_drag_pos")
                return False
        return super().eventFilter(obj, event)

    def show_cat_context_menu(self, pos, anchor=None):
        """`anchor` is the widget `pos` is relative to. It defaults to the
        combo, but in number-box mode the combo is HIDDEN — mapToGlobal on a
        hidden widget lands the menu somewhere off in the corner, so the
        number button that was right-clicked passes itself in."""
        if not hasattr(self, "cat_combo"): return
        idx = self.cat_combo.currentIndex()
        if idx >= len(self.data.get("cats_order", [])):
            return

        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setFont(QApplication.font())
        lang = getattr(self, "_current_lang", "EN")
        menu.addAction(tr("➕ Add New Project Tab", lang), self.add_category)
        menu.addAction(tr("✏️ Rename Project Tab", lang), self.rename_category)
        menu.addAction(tr("❌ Delete Project Tab", lang), self.del_category)
        menu.addSeparator()
        # Sync-Project: bind this project tab to a folder and read it as
        # silos, two-way, in real time (revertable via Unlink).
        if self._sync_config():
            menu.addAction(tr("🔄 Re-scan folder", lang), self._rescan_project_sync)
            menu.addAction(tr("📂 Change folder…", lang), self._change_project_sync_folder)
            menu.addAction(tr("🔌 Unlink Sync-Project (keep silos)", lang),
                           self._unlink_project_sync)
        else:
            menu.addAction(tr("📁 Convert to Sync-Project…", lang),
                           self._convert_project_to_sync)
        # whole-project typecheck report (same dictionary as the live
        # underlines — see Settings > Editor > Typos)
        menu.addAction(tr("🔍 Check Typos in this project…", lang),
                       self.check_project_typos)
        menu.exec((anchor or self.cat_combo).mapToGlobal(pos))

    def rename_category(self):
        if self.cat_combo.count() == 0:
            return
        idx = self.cat_combo.currentIndex()
        if idx >= len(self.data.get("cats_order", [])):
            return
        old_cat = self._cat_at(idx)
        if old_cat is None:
            return

        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "Rename Tab", "Enter new tab name:", text=old_cat)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name and name.strip() and name.strip() != old_cat:
            new_cat = name.strip()
            if new_cat in self.data["cats_order"]:
                QMessageBox.information(self, tr("Error", self._current_lang), tr("A tab with this name already exists.", self._current_lang))
                return
            if old_cat not in self.data["cats_order"]:
                # P0-3: the combo row and cats_order may diverge (hidden
                # categories). Renaming by ROW used to hit a different
                # project; rename by IDENTITY only, and refuse when the
                # identity is gone instead of guessing a row.
                from fastprompter.core.logging import logger as _lg
                _lg.error("rename_category: %r not found in cats_order; "
                          "rename aborted", old_cat)
                return

            self.add_data_undo_state("Rename category")
            # position of the OLD name, not the combo row: the two are no
            # longer guaranteed to line up (see _cat_at)
            self.data["cats_order"][self.data["cats_order"].index(old_cat)] = new_cat

            # "categories" holds the snippets themselves and must move with
            # the tab; everything else is the per-category registry.
            _all_keys = ["categories"] + list(self._PER_CATEGORY_STATE_KEYS)
            for key in _all_keys:
                if key in self.data and old_cat in self.data[key]:
                    self.data[key][new_cat] = self.data[key].pop(old_cat)
            # the PHYSICAL folder component follows the rename: the logical
            # key changes, the on-disk folder stays exactly where it is
            # (T-790 — a retitle must not strand the files)
            cfm = self.data.get("category_file_dirs")
            if isinstance(cfm, dict) and old_cat in cfm:
                cfm[new_cat] = cfm.pop(old_cat)

            if old_cat in self.current_pages:
                self.current_pages[new_cat] = self.current_pages.pop(old_cat)

            self.cat_combo.setItemText(idx, new_cat)
            # the row carries its own name for lookups — leaving the old one
            # here would make _cat_at resolve a project that no longer exists
            self.cat_combo.setItemData(idx, new_cat)
            # W2-001: the live editor owner and its doc cache follow the
            # rename, so continuing to type still addresses the same snippet.
            es = getattr(self, "editing_snippet", None)
            if es and es[0] == old_cat:
                self.editing_snippet = (new_cat, es[1])
            docs = getattr(self, "snippet_docs", {})
            old_prefix = old_cat + "_"
            for k in list(docs.keys()):
                if k.startswith(old_prefix):
                    docs[new_cat + "_" + k[len(old_prefix):]] = docs.pop(k)
            self.mark_dirty()

    def add_category(self):
        self.play_sound("new")
        if len(self.data["cats_order"]) >= 100:
            QMessageBox.information(
                self, tr("Tab Limit", self._current_lang), tr("Maximum of 100 projects. Remove one first.", self._current_lang)
            )
            return
        self.ignore_focus_loss = True
        try:
            name, ok = QInputDialog.getText(self, "New Tab", "Enter tab name:")
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if ok and name and name.strip() not in self.data["cats_order"]:
            self.add_data_undo_state("Add category")
            name = name.strip()
            self.data["cats_order"].append(name)
            self.data["categories"][name] = [None] * 100
            self.cat_combo.addItem(name, name)
            self.cat_combo.setCurrentIndex(self.cat_combo.count() - 1)
            self.mark_dirty()

    def del_category(self):
        self.play_sound("delete")
        if self.cat_combo.count() <= 1:
            return
        idx = self.cat_combo.currentIndex()
        cat = self._cat_at(idx)
        if cat is None:
            return
        self.ignore_focus_loss = True
        try:
            reply = QMessageBox.question(
                self,
                tr("Delete Tab", self._current_lang),
                tr("Nuke '{}' and all snippets?", self._current_lang).format(cat),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()
        if reply == QMessageBox.StandardButton.Yes:
            # Snapshot BEFORE any retirement: the undo restore needs the
            # folder mappings intact so trash-restore knows where files
            # belong. Captured now; popped again if retirement fails.
            pushed = self.add_data_undo_state("Delete category")

            # 1. Retire every physical file container for this category. The
            # category's PHYSICAL root is resolved from the persistent mapping
            # while the state still exists, and every normal + archive silo
            # folder under it is retired through the canonical container
            # primitive (moved to the profile-scoped _trash, undo-restorable).
            # No hand-built files_root + name joins: those used to miss the
            # category directory entirely and could trash the WRONG folder.
            from fastprompter.ui.file_container import silo_slug
            cat_dir = self._category_files_dir(cat)
            root = self._files_root()
            trash_targets = []
            fmap = self.data.get("silo_folders_all", {}).get(cat, {})
            amap = self.data.get("archive_silo_folders_all", {}).get(cat, {})
            trash_targets.extend(fmap.values() if isinstance(fmap, dict) else [])
            trash_targets.extend(amap.values() if isinstance(amap, dict) else [])

            # Archive silos without explicit folder mappings use their title slug
            for text in self.data.get("archive_temp_presets_all", {}).get(cat, []):
                if text and text.strip():
                    trash_targets.append(silo_slug(text))

            retired = []
            failed = []
            if cat_dir is None and trash_targets:
                # P0-5: the category's physical folder cannot be resolved
                # (custom root offline, no persisted component) while folder
                # mappings still exist — fail closed: nothing is retired and
                # nothing is deleted, the ownership knowledge stays.
                failed.append(("<unresolved>", "ROOT_UNAVAILABLE"))
            elif cat_dir is not None:
                for folder_name in set(trash_targets):
                    if not folder_name:
                        continue
                    d = os.path.join(root, cat_dir, folder_name)
                    status = self._delete_file_container(cat, d)
                    if status in ("MOVED_TO_TRASH", "EMPTY_REMOVED",
                                  "CONFIRMED_ABSENT"):
                        retired.append(d)
                    else:
                        failed.append((d, status))
            from fastprompter.core.logging import logger as _lg
            if not retired and not failed:
                _lg.info("category delete: no file containers found for %r "
                         "(physical dir %r under %r)", cat, cat_dir, root)
            if failed:
                # P0-1: ABORT the deletion. A category whose physical
                # retirement could not be secured must not be removed —
                # dropping the logical state would silently discard the
                # ownership knowledge that says where the surviving assets
                # live. Folders already retired are ROLLED BACK out of
                # _trash first (P0-4); entries that cannot be restored stay
                # in the log and maps so recovery still knows where the
                # assets are. Nothing is removed: the tab stays, the
                # just-pushed undo snapshot is popped so Ctrl+Z does not
                # replay a deletion that never happened.
                _lg.warning("category delete ABORTED: %d folder(s) not "
                            "retired (%s) for %r; rolling back %d already "
                            "retired folder(s)",
                            len(failed), failed, cat, len(retired))
                stuck = 0
                if retired:
                    try:
                        _restored, stuck = self._rollback_category_retirements(
                            os.path.join(root, cat_dir) if cat_dir else None)
                    except Exception:
                        _lg.exception("category rollback itself failed for "
                                      "%r; its log entries and maps were "
                                      "kept", cat)
                        stuck = len(retired)
                if stuck:
                    _lg.error("category delete ABORTED with %d folder(s) "
                              "still in _trash for %r; their log entries "
                              "and maps were kept so recovery still knows "
                              "where the assets are", stuck, cat)
                if pushed is not None and self.data_undo_stack and \
                        self.data_undo_stack[-1] is pushed:
                    self.data_undo_stack.pop()
                self._save_undo_state()
                return

            # 2. Cleanup all category state from DB (AFTER retirement resolved
            # the physical paths, so nothing is left half-retired). A failure
            # here — between the physical retirement and the state removal —
            # rolls the ALREADY-RETIRED folders back out of _trash instead of
            # leaving them stranded: the undo snapshot can then restore the
            # category with its files already home (P0-8).
            # W2-002: every File Container session resolved under this
            # category's physical directory just lost its storage owner.
            if cat_dir is not None and hasattr(self, "_detach_file_container_under"):
                self._detach_file_container_under(os.path.join(root, cat_dir))
            # W2-007: capture the exact pre-cleanup logical/UI state so a
            # failure mid-cleanup can restore every field (never persist a
            # half-deleted category). Only discard the undo snapshot after
            # both physical rollback AND logical restore have succeeded.
            _before_cleanup = {
                "cats_order": list(self.data.get("cats_order", [])),
                "category": copy.deepcopy(
                    self.data.get("categories", {}).get(cat)),
                "per_cat": {
                    k: copy.deepcopy(self.data.get(k, {}).get(cat))
                    for k in self._PER_CATEGORY_STATE_KEYS
                },
                "cat_file_dirs": copy.deepcopy(
                    self.data.get("category_file_dirs", {}).get(cat)),
                "current_page": copy.deepcopy(self.current_pages.get(cat)),
            }
            # W2-001: flush the VICTIM while its identity AND runtime aliases
            # are still valid — after the structural mutation below a generic
            # selection signal would persist victim-owned objects under the
            # survivor's name.
            try:
                self.commit_current_text()
                self.capture_silo_session(cat)
                self.save_prompt_queues()
            except Exception:
                from fastprompter.core.logging import logger as _fl
                _fl.debug("victim flush before category delete failed",
                          exc_info=True)
            try:
                # P0-3: remove by IDENTITY, never by combo row — the row and
                # cats_order diverge when categories are hidden, and pop(idx)
                # used to delete the WRONG project.
                self.data["cats_order"].remove(cat)
                self.data.get("categories", {}).pop(cat, None)

                _all_keys = list(self._PER_CATEGORY_STATE_KEYS)
                for key in _all_keys:
                    self.data.get(key, {}).pop(cat, None)
                # the physical-dir mapping is dropped ONLY when every folder was
                # retired (or confirmed absent); a failed retirement keeps it so
                # recovery still knows where the assets are
                if not failed:
                    self.data.get("category_file_dirs", {}).pop(cat, None)

                if cat in self.current_pages:
                    del self.current_pages[cat]
                # W2-001: removing the SELECTED row would synchronously emit
                # currentIndexChanged, running the generic switch handler in
                # the window where identity is half-mutated (survivor name,
                # victim-owned aliases). Block the signal, then bind the
                # survivor EXPLICITLY through the normal ownership path below.
                self.cat_combo.blockSignals(True)
                try:
                    self.cat_combo.removeItem(idx)
                finally:
                    self.cat_combo.blockSignals(False)
                self.mark_dirty()
            except Exception:
                from fastprompter.core.logging import logger as _lg
                _lg.exception(
                    "category delete of %r failed during state cleanup; "
                    "rolling back the physical retirement of its folders",
                    cat)
                try:
                    # CORE-007: capture the physical rollback outcome. Physical
                    # recovery is half of the transaction; a partial rollback
                    # (stuck > 0) that leaves folders stranded in _trash must
                    # NOT discard the durable pre-delete undo snapshot.
                    _restored, _stuck = self._rollback_category_retirements(
                        os.path.join(root, cat_dir) if cat_dir else None)
                except Exception:
                    _lg.exception("category rollback itself failed for %r",
                                  cat)
                    _restored, _stuck = 0, -1
                # W2-007/W2-005: restore the EXACT pre-cleanup logical/UI
                # state. The undo snapshot must NOT be discarded until the
                # before-state has been demonstrably restored (rollback ->
                # restore -> verify -> pop; never a silent pop on failure).
                restored_ok = False
                try:
                    bc = _before_cleanup
                    # cats_order: restore cat to its original position
                    co = bc["cats_order"]
                    self.data["cats_order"] = co
                    cats = self.data.setdefault("categories", {})
                    if bc["category"] is not None:
                        cats[cat] = bc["category"]
                    elif cat in cats:
                        cats.pop(cat, None)
                    for k, v in bc["per_cat"].items():
                        store = self.data.setdefault(k, {})
                        if v is None:
                            store.pop(cat, None)
                        else:
                            store[cat] = v
                    cfd = self.data.setdefault("category_file_dirs", {})
                    if bc["cat_file_dirs"] is not None:
                        cfd[cat] = bc["cat_file_dirs"]
                    if bc["current_page"] is not None:
                        self.current_pages[cat] = bc["current_page"]
                    # combo: re-insert the removed row at its original index.
                    # W2-005: deleting the LAST row makes idx == count, and
                    # Qt insertion AT count is valid — the old strict `<`
                    # guard silently dropped the row there.
                    if self.cat_combo.findData(cat) < 0 and \
                            0 <= idx <= self.cat_combo.count():
                        self.cat_combo.insertItem(idx, cat, cat)
                    # W2-005: declare rollback complete only when every
                    # essential invariant really holds again. CORE-007: physical
                    # recovery is the other half of the transaction, so a
                    # partial filesystem rollback (stuck > 0) keeps the snapshot
                    # retained even when the logical/UI facts look fine.
                    restored_ok = (
                        cat in self.data.get("cats_order", [])
                        and cat in self.data.setdefault("categories", {})
                        and self.cat_combo.findData(cat) >= 0
                        and _stuck == 0
                    )
                except Exception:
                    _lg.exception(
                        "W2-007: category restore FAILED for %r", cat)
                    restored_ok = False
                if restored_ok:
                    # undo snapshot is popped ONLY after a verified restore
                    if pushed is not None and self.data_undo_stack and \
                            self.data_undo_stack[-1] is pushed:
                        self.data_undo_stack.pop()
                else:
                    # fail closed: keep the durable pre-delete snapshot so
                    # Ctrl+Z can still fully recover the partial rollback
                    _lg.error(
                        "W2-005: category %r rollback INCOMPLETE; the "
                        "pre-delete undo snapshot was RETAINED for recovery",
                        cat)
                self._save_undo_state()
                raise

            # W2-001: bind the surviving category EXPLICITLY by stable
            # identity through the normal ownership path. last_tab_idx is
            # neutralised first so the generic prev-flush cannot resolve a
            # WRONG outgoing project from the stale row index (the victim's
            # state was already flushed above while its aliases were valid).
            new_idx = self.cat_combo.currentIndex()
            if new_idx < 0:
                new_idx = min(idx, max(0, self.cat_combo.count() - 1))
                self.cat_combo.setCurrentIndex(new_idx)
            self.data["last_tab_idx"] = -1
            self._suppress_sync_push = True
            try:
                self.on_tab_changed(new_idx)
            finally:
                self._suppress_sync_push = False

    def _rollback_category_retirements(self, cat_dir):
        """P0-8: move every _trash entry that belongs to a category's physical
        directory back to its original path, when that category's deletion
        failed after the folders were retired.

        Returns (restored, stuck). Entries whose trash copy is gone and whose
        original is still missing — or whose restore raises — STAY in the log
        (recovery still knows where the assets were) and the rollback is
        logged as partial."""
        log = self.data.get("folder_trash_log", [])
        if not log or not cat_dir:
            return 0, 0
        root = os.path.abspath(cat_dir).rstrip("\\/") + os.sep
        remaining, restored, stuck = [], 0, 0
        for original, trashed in log:
            if not os.path.abspath(original).startswith(root):
                remaining.append((original, trashed))
                continue
            if not os.path.isdir(trashed):
                if os.path.exists(original):
                    restored += 1          # already back; drop the entry
                    continue
                stuck += 1                 # trash copy vanished; keep entry
                remaining.append((original, trashed))
                continue
            if os.path.exists(original):
                restored += 1              # already in place; drop the entry
                continue
            try:
                os.makedirs(os.path.dirname(original), exist_ok=True)
                os.rename(trashed, original)
                restored += 1
            except OSError as e:
                from fastprompter.core.logging import logger
                logger.warning("category rollback: could not restore %s -> "
                               "%s: %s", trashed, original, e)
                stuck += 1
                remaining.append((original, trashed))
        if stuck:
            from fastprompter.core.logging import logger
            logger.error("category rollback PARTIAL: %d folder(s) restored, "
                         "%d still in _trash (%s); their log entries were "
                         "kept", restored, stuck, cat_dir)
        elif restored:
            from fastprompter.core.logging import logger
            logger.info("category rollback: %d folder(s) moved back from "
                        "_trash", restored)
        self.data["folder_trash_log"] = remaining
        self.mark_dirty()
        # W2-001: every fully-restored retirement's durable journal claim is
        # retired with it — a later startup must not resurrect these moves.
        try:
            from fastprompter.ui.snippet_ops_mixin import _purge_retirement_record
            for original, trashed in log:
                if os.path.abspath(original).startswith(root) \
                        and (original, trashed) not in remaining:
                    try:
                        _purge_retirement_record(self._files_root(), trashed)
                    except Exception:
                        pass
        except Exception:
            pass
        return restored, stuck

    def _wheel_switch_tab(self, direction):
        """Mouse wheel over the tab bar switches projects."""
        idx = self.cat_combo.currentIndex() + direction
        if 0 <= idx < self.cat_combo.count():
            self.cat_combo.setCurrentIndex(idx)

    def _on_escape(self):
        """Esc closes the search bar first; a second Esc hides the window."""
        self.play_sound("escape")
        if hasattr(self, "search_frame") and self.search_frame.isVisible():
            self.close_search()
            return
        self.hide_and_save()

    def hidden_categories(self):
        """Projects the user unchecked in the projects manager (T-599).

        Hiding only affects the combo; nothing is deleted and every store
        keeps its data. The ACTIVE project is never hidden, and the last
        visible one cannot be hidden either — that would leave no way back."""
        h = self.data.get("hidden_categories")
        if not isinstance(h, list):
            h = self.data["hidden_categories"] = []
        return h

    def visible_categories(self):
        hidden = set(self.hidden_categories())
        cats = [c for c in self.data.get("cats_order", []) if c not in hidden]
        return cats or list(self.data.get("cats_order", []))

    def rebuild_cat_combo(self, keep=None):
        """Repopulate the combo from visible_categories, preserving the
        selected PROJECT (not its row index)."""
        keep = keep or self.get_current_category()
        combo = self.cat_combo
        combo.blockSignals(True)
        try:
            combo.clear()
            for name in self.visible_categories():
                combo.addItem(name, name)
            idx = combo.findData(keep)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            combo.blockSignals(False)
        self._rebuild_cat_numbox()
        self.on_tab_changed(combo.currentIndex(), prev_identity=keep)

    def open_projects_manager(self):
        """Check/uncheck which projects appear in the combo, and reorder them."""
        from PyQt6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            QVBoxLayout,
        )
        le = getattr(self, "_current_lang", "EN")
        cur = self.get_current_category()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Projects", le))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(tr("Untick a project to hide it from the tab list. "
                                "Nothing is deleted - its silos stay put.\n"
                                "Use ▲ ▼ to change the order of the tabs.", le)))
        lst = QListWidget()
        hidden = set(self.hidden_categories())
        for name in self.data.get("cats_order", []):
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if name in hidden
                             else Qt.CheckState.Checked)
            if name == cur:
                # hiding the project you are standing in would yank the
                # ground out from under the editor
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                it.setCheckState(Qt.CheckState.Checked)
            lst.addItem(it)
        lay.addWidget(lst)

        def _move(step):
            row = lst.currentRow()
            new = row + step
            if row < 0 or not (0 <= new < lst.count()):
                return
            # takeItem drops the check state on some styles, so carry it over
            item = lst.takeItem(row)
            lst.insertItem(new, item)
            lst.setCurrentRow(new)

        move_row = QHBoxLayout()
        btn_up = QPushButton("▲")
        btn_up.setToolTip(tr("Move this project up", le))
        btn_up.clicked.connect(lambda: _move(-1))
        btn_down = QPushButton("▼")
        btn_down.setToolTip(tr("Move this project down", le))
        btn_down.clicked.connect(lambda: _move(1))
        move_row.addWidget(btn_up)
        move_row.addWidget(btn_down)
        move_row.addStretch(1)
        lay.addLayout(move_row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self.ignore_focus_loss = True
        try:
            ok = dlg.exec()
        finally:
            self.ignore_focus_loss = False
        if not ok:
            return
        new_hidden = [lst.item(i).text() for i in range(lst.count())
                      if lst.item(i).checkState() == Qt.CheckState.Unchecked]
        if len(new_hidden) >= len(self.data.get("cats_order", [])):
            return                      # refuse to hide every project
        self.hidden_categories()[:] = new_hidden

        # Order follows the list. Rebound in place rather than reassigned:
        # data["cats_order"] is aliased elsewhere, and swapping the object
        # would orphan those readers on the old list.
        new_order = [lst.item(i).text() for i in range(lst.count())]
        old_order = self.data.get("cats_order", [])
        if sorted(new_order) == sorted(old_order) and new_order != old_order:
            old_order[:] = new_order
        self.mark_dirty()
        self.rebuild_cat_combo(keep=cur)
        self._rebuild_cat_numbox()

    def _silo_session(self, cat=None):
        """Per-project "where I was": active silo, archive or not, which page.

        All three used to be single global values. Switching projects clamped
        the slot to the new project's length and carried it straight over, so
        leaving project A on silo 7 and coming back landed you wherever
        project B had left the number — and `active_is_archive` and the page
        were not saved at all, so every restart dropped you in the normal list
        on page one. The cursor and scroll INSIDE a silo were already
        per-project (silo_view_state_all); this is the outer half of it.

        One key rather than three `_all` maps on purpose: a slot-keyed store
        that someone forgets to register is exactly how silo_type_all was lost
        (H-653).
        """
        cat = cat or self.get_current_category()
        store = self.data.get("silo_session_all")
        if not isinstance(store, dict):       # an older DB wrote it with str()
            store = {}
            self.data["silo_session_all"] = store
        entry = store.get(cat)
        if not isinstance(entry, dict):
            entry = {}
            store[cat] = entry
        return entry

    def capture_silo_session(self, cat=None):
        """Record where the user is, for the project they are in."""
        if not cat and not self.get_current_category():
            return
        entry = self._silo_session(cat)
        entry["slot"] = int(getattr(self, "active_temp_slot", 0) or 0)
        entry["archive"] = bool(getattr(self, "active_is_archive", False))
        # Snippets shown/hidden is per PROJECT too (T-713): one project is a
        # snippet library and the next is a scratchpad, and a single global
        # flag made every switch fight the user for the panel.
        entry["snippets_hidden"] = (
            self.data.get("snippets_hidden", "False") == "True")
        # The page is NOT stored: _switch_to_slot derives it from the slot
        # (idx // visible), so restoring the slot restores the page. Keeping a
        # copy would be a second source of truth that can disagree.

    def restore_silo_session(self, cat=None):
        """Put the user back where they left this project. Returns the slot.

        Every value is clamped to what the project actually holds now: silos
        can be deleted while you are elsewhere, and a stale slot must land on
        a real one rather than out of range.
        """
        entry = self._silo_session(cat)
        archive = bool(entry.get("archive", False))
        presets = self.data.get("archive_temp_presets" if archive else "temp_presets") or []
        if archive and not presets:
            archive = False
            presets = self.data.get("temp_presets") or []
        try:
            slot = int(entry.get("slot", 0))
        except (TypeError, ValueError):
            slot = 0
        slot = max(0, min(slot, len(presets) - 1)) if presets else 0
        self.active_is_archive = archive
        self.active_temp_slot = slot
        # Absent means "this project has never said", which must leave the
        # panel as it is — a database written before T-713 has no entry, and
        # defaulting it would slam every project's snippets shut on upgrade.
        if "snippets_hidden" in entry:
            self.data["snippets_hidden"] = (
                "True" if entry["snippets_hidden"] else "False")
        return slot

    def _cat_at(self, idx):
        """Category name for a combo row.

        The combo row index used to be assumed identical to the cats_order
        index everywhere, which is only true while every project is shown in
        order. Anything that hides or reorders a row (T-599) would silently
        make get_current_category() return the WRONG project, and silos would
        be written into it. Each row now carries its own name; the positional
        read stays as the fallback for rows created before that."""
        try:
            name = self.cat_combo.itemData(idx)
        except Exception:
            name = None
        if isinstance(name, str) and name in self.data.get("categories", {}):
            return name
        cats = self.data.get("cats_order", [])
        # idx may arrive as a STRING: last_tab_idx is written to the settings
        # table with str() and is only coerced back on load, so an in-memory
        # value after a save is "0", and `0 <= "0"` is a TypeError.
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return None
        return cats[idx] if 0 <= idx < len(cats) else None

    def on_tab_changed(self, index, prev_identity=None):
        if index < 0:
            return
        # Record where the project being LEFT was, before the aliases move.
        # Not get_current_category(): the combo has already been set to the
        # new row by the time this signal fires, so that would file the
        # outgoing slot under the incoming project. last_tab_idx is still the
        # old row — unless the caller knows the old project by IDENTITY:
        # after a combo rebuild the old ROW is gone, and _cat_at(last_tab_idx)
        # would resolve a DIFFERENT project (P1-1), so rebuild_cat_combo passes
        # the kept project's name instead.
        if prev_identity is not None:
            prev_cat = prev_identity
        else:
            prev_cat = self._cat_at(self.data.get("last_tab_idx", -1))
        if prev_cat:
            self.capture_silo_session(prev_cat)
            # CORE-001 / W2-001: before leaving a project, persist its queue
            # while the source-block anchors are still live in the document.
            # A running watcher must never drain the NEW project's slot through
            # the stale active alias; pinning is per-project, not per-slot-key.
            self.save_prompt_queues()
        self.data["last_tab_idx"] = index
        self.commit_current_text()
        # Flush the project we are LEAVING to its synced files while its
        # per-category aliases are still bound to it.
        self._push_sync_files()
        self.cancel_editing()

        # Switch Silos to the new Tab's hierarchy
        cat = self._cat_at(index)
        if cat is None:
            return
        if "temp_presets_all" in self.data:
            # ONE authoritative alias binder: every per-category flat alias
            # (silos, pins, ticks, children, colours, gaps, folders, project
            # paths, watcher queues, types, ...) is re-bound to `cat` here.
            from fastprompter.core.state import bind_active_category
            bind_active_category(self.data, cat)
            from fastprompter.core.watcher.queue import load_queues
            self.prompt_queues = load_queues(self.data["watcher_queues"])
            self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(
                cat, {}
            )

            # Rebuild document caches for the new silos
            self.silo_docs = [None] * len(self.data["temp_presets"])
            self.archive_docs = [None] * len(self.data["archive_temp_presets"])

            # Land where this project was left, not where the last one was.
            slot = self.restore_silo_session(cat)
            self._switch_to_slot(slot, initial=True,
                                 is_archive=getattr(self, "active_is_archive", False))
            self.refresh_temp_presets()

        # The sync watcher follows the ACTIVE category: stop watching the
        # old project's folder, watch the new one's. The typo dictionary
        # follows the UI language, so it is shared — but the new document
        # needs a fresh check pass.
        self._start_project_watcher()
        self._update_project_tooltip()
        # The combo can emit currentIndexChanged while init_ui is still
        # constructing the window. The typo timer is created immediately
        # after init_ui, so an early tab switch must not crash startup.
        if hasattr(self, "_typo_timer"):
            self._typo_timer.start()

        self._update_cat_numbox_active()
        self.refresh_snippets_panel()
        # PERF-002: project switch is settings-domain navigation
        self.mark_dirty("settings")
        self.text_area.setFocus()

    def change_page(self, delta):
        cat = self.get_current_category()
        if not cat or cat not in self.data.get("categories", {}):
            return
        active = sum(1 for s in self.data["categories"][cat] if s is not None)
        max_page = max(0, math.ceil(active / 10.0) - 1)
        new_page = self.current_pages.get(cat, 0) + delta
        if 0 <= new_page <= max_page:
            self.current_pages[cat] = new_page
            self.refresh_snippets_panel()

    def change_arc_page(self, delta):
        total = len(self.data.get("archive_temp_presets", []))
        visible_count = 10
        max_page = max(0, math.ceil(total / max(1, visible_count)) - 1)
        new_page = getattr(self, "arc_silo_page", 0) + delta
        if 0 <= new_page <= max_page:
            self.arc_silo_page = new_page
            self.data["arc_silo_page"] = new_page
            self.refresh_archive_panel()

    def darken_color(self, hex_color, factor=0.75):
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c + c for c in hex_color)
        r, g, b = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _snippet_query(self):
        """Active snippet filter. A hidden search bar NEVER filters —
        stale text in a closed bar used to silently hide snippets."""
        if self.search_bar.isHidden():
            return ""
        return self.search_bar.text().strip().lower()

    def _match_snippet_query(self, query, s):
        if not query:
            return True
        text = (s.get("name", "") + " " + s.get("text", "")).lower()
        for term in query.split():
            if term not in text:
                return False
        return True

    def refresh_snippets_panel(self):
        if self._suspend_cache or self._initializing_ui:
            return
        # User-hidden wins over everything below. Without this the panel
        # reappears on the next refresh (silo switch, search, edit...), which
        # is what made an earlier version of this toggle unreliable.
        if self.data.get("snippets_hidden", "False") == "True":
            self.snippets_section.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self._sync_snippets_toggle_button()
            self.refresh_archive_panel()
            return
        cat = self.get_current_category()
        if not cat:
            self.snippets_section.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self.refresh_archive_panel()
            return

        query = self._snippet_query()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if self._match_snippet_query(query, s):
                    active_items.append((i, s))

        total_active = len(active_items)
        if total_active == 0:
            self.snippets_widget.setVisible(False)
            self.btn_page_up.setVisible(False)
            self.btn_page_down.setVisible(False)
            if hasattr(self, "sections_gap_widget"):
                self.sections_gap_widget.setVisible(False)
            self.refresh_archive_panel()
            return

        self.snippets_section.setVisible(True)
        self.snippets_widget.setVisible(True)
        self._sync_snippets_toggle_button()
        if hasattr(self, "sections_gap_widget"):
            self.sections_gap_widget.setVisible(self.data.get("silo_pinned_gap", "True") == "True")
        page = min(self.current_pages.get(cat, 0), max(0, math.ceil(total_active / 10.0) - 1))
        self.current_pages[cat] = page

        start_idx = page * 10
        page_items = active_items[start_idx : start_idx + 10]

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        preset_colors = THEMES[theme_name]["preset_colors"]
        font_family = self._font_family
        hide_keys = self.data.get("hide_shortkeys", "False") == "True"

        try:
            scale = float(self.data.get("ui_scale", "0.5"))
        except Exception:
            scale = 1.0

        self._snippet_widget_cache.clear()
        for i, w in enumerate(self.snippet_buttons):
            if i < len(page_items):
                global_idx, item = page_items[i]
                d_idx = i + 1
                key_label = (
                    ""
                    if hide_keys
                    else (
                        f"[{d_idx % 10 if d_idx % 10 != 0 else 0}] "
                        if d_idx <= 10
                        else f"[{d_idx}] "
                    )
                )
                # tolerate old/foreign entries (e.g. a pre-fix Trash-category
                # item saved with "title" instead of "name") instead of crashing
                disp = item.get("name") or item.get("title") or "Untitled"
                color = preset_colors[global_idx % len(preset_colors)]
                is_editing = self.editing_snippet and self.editing_snippet == (cat, global_idx)
                last_ts = item.get("last_edited", 0)
                if last_ts and not is_editing:
                    diff = time.time() - last_ts
                    custom = self._get_custom_colors()
                    if diff < 60:
                        overlay = QColor(custom.get("overlay_new", "#7a5555"))
                    elif diff < 3600:
                        overlay = QColor(custom.get("overlay_recent", "#7a6a40"))
                    elif diff < 86400:
                        overlay = QColor(custom.get("overlay_day", "#6a6a30"))
                    elif diff < 4233600:
                        overlay = QColor(custom.get("overlay_old", "#40556a"))
                    else:
                        overlay = None
                    if overlay:
                        base = QColor(color)
                        color = self.blend_colors(base, overlay, 0.15)

                w.update_data(
                    f"{key_label}{disp}", cat, global_idx, item["text"], color, font_family, scale,
                    title_bold=(
                        self.data.get("bold_hash_titles", "True") == "True"
                        and item["text"].lstrip().startswith("#")
                    ),
                )
                self._snippet_widget_cache[(cat, global_idx)] = (
                    w.main_btn if hasattr(w, "main_btn") else w
                )
                w.show()
            else:
                if hasattr(w, "main_btn"):
                    w.main_btn.global_idx = -1
                    w.main_btn.setText("")
                    w.main_btn.full_text = ""
                w.hide()

        self.btn_page_up.setEnabled(page > 0)
        self.btn_page_down.setEnabled(page < math.ceil(total_active / 10.0) - 1)
        show_pagination = math.ceil(total_active / 10.0) > 1
        self.btn_page_up.setVisible(show_pagination)
        self.btn_page_down.setVisible(show_pagination)

        self.snippets_widget.adjustSize()
        self.snippets_section.adjustSize()
        if getattr(self, "left_widget", None) and self.left_widget.parentWidget():
            self.left_widget.parentWidget().updateGeometry()

    def refresh_archive_panel(self):
        self._trim_archive()
        total = len(self.data.get("archive_temp_presets", []))
        if total == 0:
            self.archive_section.setVisible(False)
            return

        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        self.archive_section.setVisible(saved_arc_visible)

        visible_count = 10
        max_page = max(0, math.ceil(total / max(1, visible_count)) - 1)

        needs_visible = max_page > 0
        self.btn_arc_page_up.setVisible(needs_visible)
        self.btn_arc_page_down.setVisible(needs_visible)

        self.arc_silo_page = min(getattr(self, "arc_silo_page", 0), max_page)
        self.btn_arc_page_up.setEnabled(self.arc_silo_page > 0)
        self.btn_arc_page_down.setEnabled(self.arc_silo_page < max_page)

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        inactive_color = THEMES[theme_name]["inactive_temp_color"]
        active_color = THEMES[theme_name]["active_temp_color"]

        custom_colors = self._get_custom_colors()
        if "edit_bg" in custom_colors:
            active_color = custom_colors["edit_bg"]

        try:
            scale = float(self.data.get("ui_scale", "0.5"))
        except Exception:
            scale = 1.0
        font_family = self._font_family

        start_idx = self.arc_silo_page * visible_count

        for i, btn in enumerate(self.archive_buttons):
            slot_idx = start_idx + i
            if i >= visible_count or slot_idx >= total:
                btn.hide()
                continue
            raw = self.data["archive_temp_presets"][slot_idx]
            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            display_idx = slot_idx + 1
            line_count = raw.count("\n") + 1 if raw.strip() else 0
            line_str = str(line_count) if line_count > 0 else ""

            fcount = self._silo_file_count(slot_idx, is_archive=True)
            if fcount > 0:
                line_str = f"📁{fcount} " + line_str if line_str else f"📁{fcount}"
            label = f"{display_idx}: {text}" if text else f"{display_idx}"
            is_active = (
                getattr(self, "active_is_archive", False)
                and (slot_idx == self.active_temp_slot)
                and not getattr(self, "editing_snippet", None)
            )
            bg_color = active_color if is_active else inactive_color
            title_bold = (
                self.data.get("bold_hash_titles", "True") == "True"
                and raw.lstrip().startswith("#")
            )
            btn.update_data(label, slot_idx, bg_color, font_family, scale, line_count_str=line_str, is_pushed=is_active, title_bold=title_bold)
            btn.show()

        # The rows used to OVERLAP: measured 4 buttons of 21px landing at
        # y = 0, 2, 4, 6 inside a 42px archive_widget, i.e. two rows of space
        # for four rows of content — which is the "empty box with slivers
        # down the left" the archive rendered as. adjustSize() alone cannot
        # fix it: it asks a layout that has not been re-run since the buttons
        # were shown, so the hint it copies is the old, too-small one. Pin the
        # height the rows actually need, then let the section follow.
        lay = self.archive_widget.layout
        shown = [b for b in self.archive_buttons if not b.isHidden()]
        if shown:
            row_h = max(b.sizeHint().height() for b in shown)
            m = lay.contentsMargins()
            self.archive_widget.setMinimumHeight(
                len(shown) * row_h
                + lay.spacing() * max(0, len(shown) - 1)
                + m.top() + m.bottom()
            )
        else:
            self.archive_widget.setMinimumHeight(0)
        self.archive_widget.updateGeometry()
        self.archive_widget.adjustSize()
        # activate() AFTER the resize, never before: run against the old,
        # too-small height it is exactly what put four 21px rows at
        # y = 0, 2, 4, 6 on top of each other.
        lay.activate()
        self.archive_section.adjustSize()
        # The overlay is placed by hand, so a taller panel has to be re-placed
        # or it keeps the height it had before the rows grew.
        self._position_archive_overlay()

    def _rollback_file_retirement(self, rec):
        """Undo a single folder retirement recorded by ``_trim_archive``.

        Only a MOVED_TO_TRASH move needs reversing (EMPTY_REMOVED /
        CONFIRMED_ABSENT touched nothing). The folder is moved back from its
        trash location to the original path and the matching recovery-log
        entry is dropped, so a failed trim leaves the archive exactly as it
        found it. Rollback failure is logged and the recovery record is kept,
        never swallowed."""
        idx, folder, trash_entry, retire = rec
        if retire != "MOVED_TO_TRASH" or not trash_entry:
            return
        original, dest = trash_entry
        from fastprompter.core.logging import logger
        try:
            import os
            if os.path.isdir(dest):
                from fastprompter.ui.file_container import (
                    _move_into_container,
                    capture_resolved_root,
                )
                root = self._files_root()
                _move_into_container(dest, original, root, capture_resolved_root(root))
        except Exception:
            logger.exception("archive trim rollback FAILED moving %s back to %s",
                             dest, original)
            return
        log = self.data.get("folder_trash_log", [])
        if trash_entry in log:
            try:
                log.remove(trash_entry)
            except ValueError:
                pass
        # W2-001: the durable journal claim must die with the rolled-back
        # move, or a later startup reconciliation resurrects a retirement
        # that was already reversed.
        try:
            from fastprompter.ui.snippet_ops_mixin import _purge_retirement_record
            _purge_retirement_record(self._files_root(), dest)
        except Exception:
            logger.exception("retirement journal purge failed for %s", dest)

    def _trim_archive(self):
        entries = self.data.get("archive_temp_presets", [])
        if not entries:
            return

        empty_indices = [i for i, item in enumerate(entries) if not item.strip()]
        if not empty_indices:
            return

        # One trim == one retirement transaction. Retire EVERY empty slot's
        # folder first, but DO NOT drop the slot's mappings yet. Record each
        # successful original->trash action so a later failure can roll the
        # prior ones back. Only after ALL retirements succeed do we drop the
        # slots and their mappings (P0-3).
        retired = []  # (idx, folder, trash_entry_or_None, status)
        for idx in empty_indices:
            folder = self._silo_folder_dir(idx, is_archive=True)
            if folder is None:
                retire = "ROOT_UNAVAILABLE"
                trash_entry = None
            else:
                log_before = len(self.data.get("folder_trash_log", []))
                retire = self._delete_file_container(
                    self.get_current_category(), folder)
                trash_entry = None
                if retire == "MOVED_TO_TRASH":
                    log = self.data.get("folder_trash_log", [])
                    if len(log) > log_before:
                        trash_entry = log[-1]
                        # rename for clarity in the record
                        trash_entry = (log[-1][0], log[-1][1])
            if retire in ("FAILED", "ROOT_UNAVAILABLE"):
                for rec in reversed(retired):
                    self._rollback_file_retirement(rec)
                from fastprompter.core.logging import logger
                logger.warning(
                    "archive trim ABORTED at slot %d: folder retirement %s; "
                    "rolled back %d prior move(s), no archive slot dropped",
                    idx, retire, len(retired))
                return
            retired.append((idx, folder, trash_entry, retire))

        # all retired cleanly: now drop the slots, mappings and docs together
        for idx, _f, _t, _r in retired:
            self.data.get("archive_silo_folders", {}).pop(str(idx), None)
            self.data.get("archive_project_paths", {}).pop(str(idx), None)

        # W2-002: the retired folders' sessions (if a drawer was open on one)
        # lose their mutation lease together with their storage owner.
        if hasattr(self, "_detach_file_container_for"):
            for _idx, folder, trash_entry, retire in retired:
                if retire in ("MOVED_TO_TRASH", "EMPTY_REMOVED") and folder:
                    try:
                        self._detach_file_container_for(folder)
                    except Exception:
                        pass

        for idx in reversed(empty_indices):
            self.drop_silo_state(idx, is_archive=True)
            entries.pop(idx)
            if hasattr(self, "archive_docs") and idx < len(self.archive_docs):
                self.archive_docs.pop(idx)

        self._rebind_visible_lists(archive=entries)
        if getattr(self, "active_is_archive", False):
            old_idx = getattr(self, "active_temp_slot", -1)
            shift = sum(1 for i in empty_indices if i < old_idx)
            if old_idx in empty_indices:
                if entries:
                    self.active_temp_slot = 0
                else:
                    self.active_is_archive = False
                    self.active_temp_slot = max(
                        0, min(self.active_temp_slot, len(self.data.get("temp_presets", [""])) - 1)
                    )
            else:
                self.active_temp_slot = max(0, old_idx - shift)
        self.mark_dirty()

    # move_preset_to_index is defined earlier in the class (uses pop+insert with undo)

    def change_silo_page(self, delta):
        last_used = -1
        total_silos = len(self.data["temp_presets"])
        for i in range(total_silos - 1, -1, -1):
            if self.data["temp_presets"][i].strip():
                last_used = i
                break

        # Determine the maximum slot currently visible/accessible
        visible_silos = max(last_used + 1, self.active_temp_slot + 1, self._visible_silos)
        max_page = max(0, math.ceil(visible_silos / max(1, self._visible_silos)) - 1)
        new_page = self.silo_page + delta
        if 0 <= new_page <= max_page:
            self.silo_page = new_page
            self.refresh_temp_presets()

    def navigate_silo(self, delta):
        """Move silo selection up/down the sidebar (Alt+Up / Alt+Down)."""
        is_arc = getattr(self, "active_is_archive", False)
        presets = self.data["archive_temp_presets" if is_arc else "temp_presets"]
        if not presets:
            return
        if is_arc:
            order = list(range(len(presets)))
        else:
            # Follow the visual order: pinned silos first, then the rest
            pinned = self.data.get("pinned_silos", [])
            if isinstance(pinned, str):
                import ast

                try:
                    pinned = ast.literal_eval(pinned)
                except Exception:
                    pinned = []
            total = len(presets)
            order = [p for p in pinned if p < total] + [
                j for j in range(total) if j not in pinned
            ]
        try:
            pos = order.index(self.active_temp_slot)
        except ValueError:
            pos = 0
        new_pos = max(0, min(len(order) - 1, pos + delta))
        if order[new_pos] != self.active_temp_slot or self.editing_snippet:
            self._switch_to_slot(order[new_pos], is_archive=is_arc)

    def _switch_to_slot(self, idx, initial=False, is_archive=False):
        if is_archive:
            self.arc_silo_page = idx // 10
        else:
            self.silo_page = idx // max(1, self._visible_silos)

        was_editing_snippet = bool(getattr(self, "editing_snippet", None))
        was_archive = getattr(self, "active_is_archive", False)
        # PERF-002: the owner we are leaving (valid before any reassignment)
        outgoing_slot = getattr(self, "active_temp_slot", -1)

        # remember where we were before the document underneath us changes
        if not initial and not was_editing_snippet:
            self.capture_silo_state(self.active_temp_slot, was_archive)

        if not initial:
            self.play_click_sound()
            self._cache_timer.stop()
            if was_editing_snippet:
                self.save_snippet(silent=True)
            elif was_archive:
                new_txt = self.text_area.toPlainText()
                if new_txt.strip() and 0 <= self.active_temp_slot < len(
                    self.data.get("archive_temp_presets", [])
                ):
                    old_arc_txt = self.data["archive_temp_presets"][self.active_temp_slot]
                    self._sync_silo_folder(
                        self.get_current_category(),
                        old_arc_txt,
                        new_txt,
                    )
                    self.data["archive_temp_presets"][self.active_temp_slot] = new_txt
                    # PERF-002: mark the archive domain when text changed
                    if new_txt != old_arc_txt:
                        self.mark_dirty("arc")
            else:
                old_slot = self.active_temp_slot
                new_text = self.text_area.toPlainText()
                if 0 <= old_slot < len(self.data["temp_presets"]):
                    old_text = self.data["temp_presets"][old_slot]
                    self._sync_silo_folder(self.get_current_category(), old_text, new_text)
                    self.data["temp_presets"][old_slot] = new_text
                    if new_text != old_text:
                        self.silo_last_edited[old_slot] = int(time.time())
                        # PERF-002: the text changed, mark the silo domain
                        self.mark_dirty("temp")

        if not is_archive:
            if "temp_presets" not in self.data or not self.data["temp_presets"]:
                self._rebind_visible_lists(temp=[""])
            if idx >= len(self.data["temp_presets"]):
                idx = max(0, len(self.data["temp_presets"]) - 1)
        else:
            if "archive_temp_presets" not in self.data or not self.data["archive_temp_presets"]:
                self._rebind_visible_lists(archive=[""])
            if idx >= len(self.data["archive_temp_presets"]):
                idx = max(0, len(self.data["archive_temp_presets"]) - 1)

        # If we are already on this silo and not editing a snippet, early return
        if (
            not initial
            and not was_editing_snippet
            and self.active_temp_slot == idx
            and getattr(self, "active_is_archive", False) == is_archive
        ):
            self._begin_batch_update()
            try:
                self.text_area.setFocus()
                self.text_area.ensureCursorVisible()
                if is_archive:
                    self.refresh_archive_panel()
                else:
                    self.refresh_temp_presets()
            finally:
                self._end_batch_update()
            return

        if not initial:
            switch_snap = self.add_data_undo_state("Switch silo")
        else:
            switch_snap = None

        self._begin_batch_update()
        try:
            self.cancel_editing(silent=True)
            self.active_temp_slot = idx
            self.active_is_archive = is_archive

            self._suspend_cache = True
            try:
                self.text_area.blockSignals(True)

                if is_archive:
                    while len(self.archive_docs) <= idx:
                        self.archive_docs.append(None)

                    if self.archive_docs[idx] is None:
                        from PyQt6.QtGui import QTextDocument
                        d = QTextDocument()
                        d.setDefaultFont(self.text_area.font())
                        self.archive_docs[idx] = d
                    doc = self.archive_docs[idx]

                    archive = self.data.get("archive_temp_presets", [])
                    if idx >= len(archive):
                        archive = archive + [""] * (idx + 1 - len(archive))
                        self._rebind_visible_lists(archive=archive)
                    new_text = archive[idx]
                else:
                    if idx >= len(self.silo_docs):
                        while len(self.silo_docs) <= idx:
                            self.silo_docs.append(None)

                    if self.silo_docs[idx] is None:
                        from PyQt6.QtGui import QTextDocument
                        d = QTextDocument()
                        d.setDefaultFont(self.text_area.font())
                        self.silo_docs[idx] = d
                    doc = self.silo_docs[idx]

                    new_text = self.data["temp_presets"][idx]

                if doc.toPlainText() != new_text:
                    self._set_plain_text_clean(doc, new_text)

                self.text_area.set_active_document(doc)
                # The "Switch silo" snapshot was stamped against the document
                # we were LEAVING (add_data_undo_state ran before the swap).
                # Ctrl+Z routing compares the ACTIVE document's undo steps
                # against the snapshot's, so the snapshot must carry the
                # document we landed on and its step count at that moment —
                # otherwise every Ctrl+Z after a switch+type fires a data
                # undo that restores the pre-switch snapshot and wipes the
                # text typed since (T-734: "half the text is gone").
                if switch_snap is not None:
                    switch_snap["_doc_id"] = id(doc)
                    switch_snap["_text_steps"] = self._text_undo_steps()
                # Text alignment must be re-applied per-document
                self._apply_text_alignment()
                self._restore_centered_blocks()
                self._restore_aligned_blocks()

                # "Silos at Start" (silo_home) means always open at the top,
                # so it must OVERRIDE the remembered cursor/scroll. A plain
                # restore would win for any silo last edited below the top
                # (i.e. almost always) and the setting would do nothing.
                if self.data.get("silo_home", "False") == "True":
                    # restore marks/heat/folds, then force the top
                    self.restore_silo_state(idx, is_archive)
                    self.text_area.moveCursor(QTextCursor.MoveOperation.Start)
                elif not self.restore_silo_state(idx, is_archive):
                    self.text_area.moveCursor(QTextCursor.MoveOperation.End)
            finally:
                self.text_area.blockSignals(False)
                self._suspend_cache = False

            self.refresh_temp_presets()
            self.refresh_archive_panel()
            self.update_preview()
            self._update_line_count_label()
            self._update_files_button()
            self._sync_files_dock_to_active_silo()
            self._update_project_buttons(is_archive)
            cur_text = new_text
            self._apply_silo_type(idx, is_archive, cur_text)
            # seed the live folder-sync baseline for the new silo
            from fastprompter.ui.file_container import silo_slug as _sl2
            self._active_silo_slug = _sl2(
                cur_text[:cur_text.index("\n")] if "\n" in cur_text else cur_text)
            # the silo we just LEFT was flushed into temp_presets above —
            # push it to its file now (Sync-Project / per-silo links) and
            # re-run the typo check on the silo we landed on.
            # PERF-002: publish ONLY the outgoing owner — navigation must
            # not reconcile every bound silo in the project.
            self._push_sync_files(
                slots=None if outgoing_slot < 0 else {outgoing_slot})
            if hasattr(self, "_typo_timer"):
                self._typo_timer.start()
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            if not initial:
                # PERF-002: navigation is settings-domain state
                self.mark_dirty("settings")
        finally:
            self._end_batch_update()

    def _on_visual_widget_changed(self, new_text):
        if getattr(self, "_suspend_temp_sync", False) or getattr(self, "_suspend_cache", False):
            return
        if self.text_area.toPlainText() != new_text:
            # Use QTextCursor so that the change is recorded in the undo stack
            from fastprompter.ui.edit_guard import edit_block
            cursor = self.text_area.textCursor()
            cursor.select(cursor.SelectionType.Document)
            self._syncing_from_visual = True
            try:
                with edit_block(cursor, self.text_area):
                    cursor.insertText(new_text)
            finally:
                self._syncing_from_visual = False
            self.mark_dirty()

    def _seed_silo_structure(self, idx, tgt_type, text, is_archive):
        """Give a silo the structure its new type needs. False = nothing added.

        Returns None when the user backed out, so the caller leaves the type
        alone. A silo that ALREADY holds a board or a table is never touched:
        the transform is a change of view, not a rewrite of the text.
        """
        if tgt_type == "text":
            return False
        from fastprompter.ui import silo_region

        # For the OPEN silo the editor is the live text and temp_presets lags
        # behind it until the next save or switch. Seeding from the lagging
        # copy wrote the new structure onto a stale base and left the editor
        # showing something else entirely — measured in the transform fuzz:
        # presets held a table while the editor still held prose.
        if idx == getattr(self, "active_temp_slot", -1) and not is_archive:
            text = self.text_area.toPlainText()

        lines = text.split("\n")
        has_structure = (silo_region.board_region(lines) if tgt_type == "kanban"
                         else silo_region.table_region(lines)) is not None
        if has_structure:
            return False

        if text.strip():
            # There IS text, and it is not a board/table: say what will happen
            # rather than silently appending under someone's notes.
            from PyQt6.QtWidgets import QMessageBox
            what = "board" if tgt_type == "kanban" else "table"
            reply = QMessageBox.question(
                self, f"Transform to {what.title()}",
                f"This silo has no {what} yet. Add an empty one below the "
                f"text that is already there?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                return None

        if tgt_type == "kanban":
            from fastprompter.ui import silo_kanban as sk
            block = sk.new_board()
        else:
            from fastprompter.ui import silo_table as st
            block = st.render(st.new_table(2, 3))

        body = (text.rstrip() + "\n\n" if text.strip() else "") + "\n".join(block)
        presets = (self.data["archive_temp_presets"] if is_archive
                   else self.data["temp_presets"])
        while len(presets) <= idx:
            presets.append("")
        presets[idx] = body
        if idx == getattr(self, "active_temp_slot", -1) and not is_archive:
            self._set_plain_text_clean(self.text_area, body)
        self.mark_dirty()
        return True

    def _apply_silo_type(self, idx, is_archive, text=None):
        if is_archive:
            self.silo_view.setCurrentIndex(0)
            return

        stype = self.data.get("silo_types", {}).get(str(idx), "text")
        if text is None:
            text = self.text_area.toPlainText()

        # The recorded type is the user's INTENT; the text is the truth, and
        # the two drift apart in ordinary use — undo restores the previous
        # text without restoring the previous type, and a paste or a clear
        # can leave a "kanban" silo holding prose. Showing a board widget for
        # a silo with no board is confusing at best, and it hands that widget
        # a document it does not own. Found by fuzzing the transform path:
        # 17 mismatches in 220 steps, e.g. type "table" over a live board.
        if stype in ("kanban", "table"):
            self._silo_structure_ok = self._silo_has_structure(stype, text)
            if not self._silo_structure_ok:
                stype = "text"

        if stype == "kanban":
            self.silo_view.setCurrentIndex(1)
            self.kanban_widget.load_markdown(text)
            self._rendered_visual_text = text
        elif stype == "table":
            self.silo_view.setCurrentIndex(2)
            self.table_widget.load_markdown(text)
            self._rendered_visual_text = text
        else:
            self.silo_view.setCurrentIndex(0)
            self._rendered_visual_text = None

    def _schedule_silo_type_recheck(self):
        """Re-pick the view when the text stops matching the silo's type.

        PERF-003: coalesced — typing bursts restart a single-shot timer and
        only the newest text after the burst is parsed, matching
        _schedule_visual_rebuild's 300 ms window.
        """
        from PyQt6.QtCore import QTimer
        t = getattr(self, "_silo_type_recheck_timer", None)
        if t is None or sip.isdeleted(t):
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(300)
            t.timeout.connect(self._flush_silo_type_recheck)
            self._silo_type_recheck_timer = t
        t.start()

    def _flush_silo_type_recheck(self):
        if sip.isdeleted(self) or getattr(self, "_syncing_from_visual", False):
            return
        idx = getattr(self, "active_temp_slot", -1)
        if idx < 0 or getattr(self, "active_is_archive", False):
            return
        stype = self.data.get("silo_types", {}).get(str(idx), "text")
        if stype not in ("kanban", "table"):
            return
        text = self.text_area.toPlainText()
        ok = self._silo_has_structure(stype, text)
        if ok == getattr(self, "_silo_structure_ok", None):
            return
        self._silo_structure_ok = ok
        self._apply_silo_type(idx, False, text=text)

    def _flush_silo_type_recheck_sync(self):
        """Synchronous flush for explicit transitions needing immediate view."""
        t = getattr(self, "_silo_type_recheck_timer", None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        self._flush_silo_type_recheck()

    @staticmethod
    def _silo_has_structure(stype, text):
        """Does this text actually hold the thing its type claims?

        An EMPTY silo counts as ready for either: that is the transform's own
        starting point, and the widget seeds it.
        """
        from fastprompter.ui import silo_region
        if not text.strip():
            return True
        lines = text.split("\n")
        if stype == "kanban":
            return silo_region.board_region(lines) is not None
        return silo_region.table_region(lines) is not None

    def _switch_to_arc_slot(self, idx):
        self._switch_to_slot(idx, is_archive=True)

    def open_trash(self):
        if "Trash" not in self.data["categories"]:
            self.data["categories"]["Trash"] = []
        if "Trash" not in self.data["cats_order"]:
            self.data["cats_order"].append("Trash")
            self.cat_combo.addItem("Trash", "Trash")
        idx = self.combo_index_for_category("Trash")
        if idx < 0:
            # P1-1: Trash is hidden — it was just appended to cats_order but
            # the combo only shows visible projects. Rebuild with Trash kept.
            self.rebuild_cat_combo(keep="Trash")
            idx = self.combo_index_for_category("Trash")
        if idx < 0:
            return
        if self.cat_combo.currentIndex() == idx:
            # We are already in Trash; toggle back
            prev_idx = getattr(self, "_pre_trash_cat_idx", 0)
            if prev_idx == idx or prev_idx >= self.cat_combo.count():
                prev_idx = 0
            self.cat_combo.setCurrentIndex(prev_idx)
        else:
            self._pre_trash_cat_idx = self.cat_combo.currentIndex()
            self.cat_combo.setCurrentIndex(idx)

    def refresh_temp_presets(self):
        total = len(self.data["temp_presets"])
        if total == 0:
            self.silos_section.setVisible(False)
            return
        if not hasattr(self, "silos_widget") or not hasattr(self, "silo_buttons"):
            return

        self.silos_section.setVisible(True)

        self._update_visible_silo_count()
        max_page = max(0, math.ceil(total / max(1, self._visible_silos)) - 1)
        self.silo_page = min(self.silo_page, max_page)

        self.btn_silo_up.setVisible(max_page > 0)
        self.btn_silo_down.setVisible(max_page > 0)
        self.btn_silo_up.setEnabled(self.silo_page > 0)
        self.btn_silo_down.setEnabled(self.silo_page < max_page)

        theme_name = self.data.get("theme", "Default")
        if theme_name not in THEMES:
            theme_name = "Default"
        active_color = THEMES[theme_name]["active_temp_color"]
        inactive_color = THEMES[theme_name]["inactive_temp_color"]

        try:
            scale = float(self.data.get("ui_scale", "0.5"))
        except Exception:
            scale = 1.0
        font_family = self._font_family

        start_idx = self.silo_page * self._visible_silos

        pinned_list = self.data.get("pinned_silos", [])
        if isinstance(pinned_list, str):
            import ast
            try:
                pinned_list = ast.literal_eval(pinned_list)
            except Exception:
                pinned_list = []

        children_map = self._children_map()
        collapsed = set(self.data.get("silo_collapsed", []))

        # O(1) Cache for hierarchy (Task 11)
        cache_key = (tuple(pinned_list), tuple((k, tuple(v)) for k, v in children_map.items()), tuple(sorted(collapsed)), total)
        if not hasattr(self, "_hierarchy_cache") or getattr(self, "_hierarchy_cache_key", None) != cache_key:
            all_kids = {k for kids in children_map.values() for k in kids}
            unpinned = [j for j in range(total) if j not in pinned_list and j not in all_kids]
            top_order = [p for p in pinned_list if p < total and p not in all_kids] + unpinned
            display_order = []
            child_of = {}
            label_of = {}
            def _emit(idx, label, depth):
                if not (0 <= idx < total):
                    return
                display_order.append(idx)
                label_of[idx] = label
                if idx in collapsed or depth >= MAX_SILO_DEPTH:
                    return
                for rank, kid in enumerate(children_map.get(idx, []), start=1):
                    if 0 <= kid < total and kid != idx:
                        child_of[kid] = idx
                        _emit(kid, f"{label}.{rank}", depth + 1)
            for pos, t in enumerate(top_order, start=1):
                _emit(t, str(pos), 0)
            self._hierarchy_cache = (display_order, child_of, label_of, all_kids)
            self._hierarchy_cache_key = cache_key

        display_order, child_of, label_of, all_kids = self._hierarchy_cache

        # pagination follows what's actually displayed (collapse shrinks it)
        max_page = max(0, math.ceil(len(display_order) / max(1, self._visible_silos)) - 1)
        self.silo_page = min(self.silo_page, max_page)
        self.btn_silo_up.setVisible(max_page > 0)
        self.btn_silo_down.setVisible(max_page > 0)
        self.btn_silo_up.setEnabled(self.silo_page > 0)
        self.btn_silo_down.setEnabled(self.silo_page < max_page)
        self.btn_page_up.setEnabled(self.silo_page > 0)
        self.btn_page_down.setEnabled(self.silo_page < max_page)
        start_idx = self.silo_page * self._visible_silos
        if not hasattr(self, "silo_gap_widget"):
            from PyQt6.QtWidgets import QFrame
            self.silo_gap_widget = QFrame(self)
            self.silo_gap_widget.setFixedHeight(8)
            self.silo_gap_widget.setStyleSheet("margin: 2px 8px; background: transparent;")
            self.silos_widget.layout.addWidget(self.silo_gap_widget)

        self.silos_widget.layout.removeWidget(self.silo_gap_widget)
        self.silo_gap_widget.hide()

        first_unpinned_ui_index = -1
        show_gap = self.data.get("silo_pinned_gap", "True") == "True"

        for i, btn in enumerate(self.silo_buttons):
            disp_pos = start_idx + i
            if disp_pos >= len(display_order) or i >= self._visible_silos:
                btn.hide()
                continue
            slot_idx = display_order[disp_pos]
            raw = self.data["temp_presets"][slot_idx]
            is_pinned = slot_idx in pinned_list
            is_child = slot_idx in child_of
            kids = children_map.get(slot_idx, [])

            if not is_pinned and not is_child and first_unpinned_ui_index == -1 and pinned_list:
                first_unpinned_ui_index = i

            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            if text.startswith("#"):
                text = text[1:].lstrip()

            # labels were built by the hierarchy walk above, so a
            # grandchild reads 1.1.1 rather than being mislabelled 1.1
            display_idx = label_of.get(slot_idx)
            if display_idx is None:
                display_idx = (pinned_list.index(slot_idx) + 1 if is_pinned
                               else unpinned.index(slot_idx) + 1
                               if slot_idx in unpinned else slot_idx + 1)

            line_count = raw.count("\n") + 1 if raw.strip() else 0
            line_str = str(line_count) if line_count > 0 else ""

            # the rightmost 📁N button carries the file count — the text
            # counter stays lines-only (no duplicated 📁)
            fcount = self._silo_file_count(slot_idx)
            # No "📌 " text prefix — the pin button itself is the indicator
            # and its click unpins (see DraggableSiloButton.update_data)
            if is_child:
                label = f"↳ {display_idx}: {text}" if text else f"↳ {display_idx}"
            else:
                label = f"{display_idx}: {text}" if text else f"{display_idx}"
            # a silo bound to a file (Sync-Project or per-silo link) shows a
            # 🔗 so it reads as "this row is synced" at a glance
            if self._silo_is_synced(slot_idx):
                label += " 🔗"
            is_active = (
                (not getattr(self, "active_is_archive", False))
                and (slot_idx == self.active_temp_slot)
                and not getattr(self, "editing_snippet", None)
            )
            bg_color = active_color if is_active else inactive_color
            if text and slot_idx in self.silo_last_edited:
                bg_color = self._overlay_silo_bg(bg_color, self.silo_last_edited[slot_idx])
            title_bold = (
                self.data.get("bold_hash_titles", "True") == "True"
                and raw.lstrip().startswith("#")
            )
            has_hash = (
                raw.lstrip().startswith("#")
                and self.data.get("silo_color_box", "True") == "True"
            )
            silo_colors = self.data.get("silo_colors", {})
            if not isinstance(silo_colors, dict):
                silo_colors = {}
            color_hex = silo_colors.get(str(slot_idx), "") if has_hash else ""
            btn.update_data(label, slot_idx, bg_color, font_family, scale, line_count_str=line_str, is_pushed=is_active, title_bold=title_bold, is_child=is_child, fcount=fcount, has_children=len(kids)>0, is_collapsed=slot_idx in collapsed, has_hash=has_hash, color_hex=color_hex, is_pinned=is_pinned)

        if show_gap and first_unpinned_ui_index != -1:
            # layout contains the buttons, so insertWidget at first_unpinned_ui_index puts it before that button
            # Note: since we removed it, the buttons are contiguous at indices 0..N
            self.silos_widget.layout.insertWidget(first_unpinned_ui_index, self.silo_gap_widget)
            self.silo_gap_widget.show()

        # -- user-defined gaps (T-590) --------------------------------------
        # A spacer below each visible silo whose slot is in silo_gaps. Pooled
        # frames, re-placed by live layout index each refresh so they coexist
        # with the pinned/unpinned divider above.
        self.prune_silo_gaps()
        gaps = self.data.get("silo_gaps") or []
        pool = getattr(self, "_user_gap_widgets", None)
        if pool is None:
            pool = self._user_gap_widgets = []
        for gw in pool:
            self.silos_widget.layout.removeWidget(gw)
            gw.hide()
        if gaps:
            try:
                gap_h = int(self.data.get("silo_gap_height", 8))
            except (TypeError, ValueError):
                gap_h = 8
            # Floor of 6px is a minimum hit target, not styling: the bar is
            # transparent and lives in a layout cell, so there is no way to
            # give it a grab zone bigger than its own height (a taller widget
            # changes the visible gap, and negative stylesheet margins are
            # unreliable in Qt). At 2px the Ctrl+drag handle was unusable.
            gap_h = max(6, min(80, gap_h))
            from fastprompter.ui.snippet_panel import SiloGapBar
            need = 0
            for i, btn in enumerate(self.silo_buttons):
                disp_pos = start_idx + i
                if disp_pos >= len(display_order) or i >= self._visible_silos:
                    continue
                if display_order[disp_pos] not in gaps:
                    continue
                while len(pool) <= need:
                    f = SiloGapBar(self, self)
                    f.setObjectName("SiloUserGap")
                    f.setStyleSheet("margin: 0px 8px; background: transparent;")
                    pool.append(f)
                gw = pool[need]
                need += 1
                # the bar has to know which row it is parked under, so a
                # Ctrl+drag can rewrite that anchor
                gw.slot_idx = display_order[disp_pos]
                
                names = self.data.get("silo_gap_names") or {}
                gap_name = names.get(str(gw.slot_idx), "")
                gw.setText(gap_name)
                
                if gap_name:
                    h = max(24, gap_h)
                    gw.setFixedHeight(h)
                    from PyQt6.QtGui import QFont
                    font = gw.font()
                    font.setBold(True)
                    font.setPointSize(max(8, int(self.data.get("font_size", 11)) - 1))
                    gw.setFont(font)
                    
                    try:
                        t_name = self.data.get("theme", "Default")
                        raw = THEMES.get(t_name, THEMES.get("Default", {})).get("raw_colors", {})
                        fg = raw.get("fg", "#888888")
                        border = raw.get("border", "#555555")
                    except Exception:
                        fg, border = "#888888", "#555555"
                        
                    gw.setStyleSheet(f"color: {fg}; margin: 2px 8px 0px 8px; border-bottom: 1px solid {border};")
                else:
                    gw.setFixedHeight(gap_h)
                    gw.setStyleSheet("margin: 0px 8px; background: transparent; border: none;")
                # park the bar after the anchor's whole expanded subtree so a
                # gap on a parent never splits it from its own children
                end_pos = self._subtree_end(disp_pos, display_order, child_of)
                anchor_btn, anchor_i = btn, end_pos - start_idx
                if 0 <= anchor_i < min(len(self.silo_buttons), self._visible_silos):
                    cand = self.silo_buttons[anchor_i]
                    if not cand.isHidden():
                        anchor_btn = cand
                self.silos_widget.layout.insertWidget(
                    self.silos_widget.layout.indexOf(anchor_btn) + 1, gw)
                gw.show()

    def _overlay_silo_bg(self, bg_color, last_ts):
        diff = time.time() - last_ts
        custom = self._get_custom_colors()
        if diff < 60:
            overlay = QColor(custom.get("overlay_new", "#6a5555"))
        elif diff < 3600:
            overlay = QColor(custom.get("overlay_recent", "#6a5a40"))
        elif diff < 86400:
            overlay = QColor(custom.get("overlay_day", "#5a5a30"))
        elif diff < 4233600:
            overlay = QColor(custom.get("overlay_old", "#40506a"))
        else:
            overlay = None
        if overlay:
            base = QColor(bg_color)
            return self.blend_colors(base, overlay, 0.25)
        return bg_color

    @staticmethod
    def blend_colors(c1, c2, ratio):
        return f"#{int(c1.red() * (1 - ratio) + c2.red() * ratio):02x}{int(c1.green() * (1 - ratio) + c2.green() * ratio):02x}{int(c1.blue() * (1 - ratio) + c2.blue() * ratio):02x}"

    def _insert_silo_at(self, pos, text=""):
        """Insert a silo at `pos`, shifting everything below it down.

        Goes through _remap_silo_indices so colours, pins, ticks, children,
        folders, project paths and saved cursors all move with their silos
        instead of being left on the slot numbers they used to occupy.

        Honours the single 100-slot capacity boundary: if the space is already
        full of content the insert is refused (returns None) before anything is
        mutated, so no silo is silently evicted and nothing is lost. A blank
        slot, if one exists, is reused in place rather than growing the list
        past the persistence contract.
        """
        from PyQt6.QtGui import QTextDocument

        presets = self.data["temp_presets"]
        self.capture_silo_state()

        blank = next((i for i, p in enumerate(presets) if not (p or "").strip() and self._slot_is_pristine(i, False)), None)
        if len(presets) >= self.MAX_SILOS_PER_CATEGORY and blank is None:
            # full of content or no pristine blank: refuse BEFORE mutating anything; lose nothing
            return None
        if blank is not None and len(presets) >= self.MAX_SILOS_PER_CATEGORY:
            # reuse the pristine blank instead of exceeding the 100-slot contract
            self.add_data_undo_state("Insert silo")
            presets[blank] = text
            doc = QTextDocument()
            doc.setDefaultFont(self.text_area.font())
            self._set_plain_text_clean(doc, text)
            while len(self.silo_docs) <= blank:
                spare = QTextDocument()
                spare.setDefaultFont(self.text_area.font())
                self.silo_docs.append(spare)
            if self.silo_docs[blank] is None:
                self.silo_docs[blank] = doc
            else:
                self._set_plain_text_clean(self.silo_docs[blank], text)
            self.mark_dirty()
            return blank

        pos = max(0, min(pos, len(presets)))

        self.add_data_undo_state("Insert silo")

        # shift every index at or after pos BEFORE the new slot exists
        self._remap_silo_indices(lambda i: i + 1 if i >= pos else i)

        presets.insert(pos, text)
        doc = QTextDocument()
        doc.setDefaultFont(self.text_area.font())
        self._set_plain_text_clean(doc, text)
        while len(self.silo_docs) < pos:
            spare = QTextDocument()
            spare.setDefaultFont(self.text_area.font())
            self.silo_docs.append(spare)
        self.silo_docs.insert(pos, doc)

        if getattr(self, "active_temp_slot", 0) >= pos:
            self.active_temp_slot += 1
        self.mark_dirty()
        return pos

    def duplicate_silo(self, idx, is_archive=False):
        """Copy a silo, its text and its files, into the next slot."""
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        if not (0 <= idx < len(presets)):
            return
        if is_archive:      # archive has no insert path; keep it simple
            return

        src_dir = self._silo_folder_dir(idx)
        text = presets[idx]
        # W2-005: capture the IMMUTABLE originating ownership at dispatch —
        # the category this duplicate belongs to. The async copy validates its
        # destination against THIS captured owner, never the mutable current
        # category, so navigating to another category during the copy cannot
        # invalidate a still-valid duplicate (which would otherwise leave the
        # duplicated silo permanently missing its File Container assets).
        dup_cat = self.get_current_category() or ""
        new_idx = self._insert_silo_at(idx + 1, text)
        if new_idx is None:
            return  # capacity refused: lose nothing

        # carry the visual identity across, but NOT the pin/tick state —
        # a copy shouldn't silently inherit "pinned" or "done"
        colours = self.data.get("silo_colors", {})
        if isinstance(colours, dict) and str(idx) in colours:
            colours[str(new_idx)] = colours[str(idx)]
        paths = self.data.get("silo_project_paths", {})
        if isinstance(paths, dict) and isinstance(paths.get(str(idx)), dict):
            paths[str(new_idx)] = dict(paths[str(idx)])

        # copy the files folder too, into the copy's OWN uniquely named dir
        # via the container's atomic no-clobber primitive (never copytree
        # with dirs_exist_ok: a fresh silo folder must be unique, and a large
        # tree must not copy on the GUI thread).
        try:
            if os.path.isdir(src_dir) and os.listdir(src_dir):
                dst_dir = self._silo_folder_dir(new_idx)
                if os.path.abspath(dst_dir) != os.path.abspath(src_dir):
                    def _publish_guard():
                        # W2-005: validate against the IMMUTABLE originating
                        # category/root captured at dispatch, not the current
                        # category. A delete (or structural move) of the
                        # duplicate while the copy runs makes this false and
                        # aborts publication, removing the temp instead of
                        # resurrecting an orphan asset directory — but mere
                        # navigation to another category must NOT cancel a
                        # valid duplicate.
                        try:
                            presets_all = self.data.get("temp_presets_all", {})
                            cat_presets = presets_all.get(dup_cat)
                            if not isinstance(cat_presets, list):
                                return False
                            if not (0 <= new_idx < len(cat_presets)):
                                return False
                            fmap = self.data.get(
                                "silo_folders_all", {}).get(dup_cat, {})
                            expected = fmap.get(str(new_idx))
                            if expected:
                                cat_comp = self._category_files_dir(dup_cat)
                                if cat_comp is None:
                                    return False
                                resolved = os.path.join(
                                    self._files_root(), cat_comp, expected)
                                return os.path.abspath(resolved) == \
                                    os.path.abspath(dst_dir)
                            # folder not yet committed: the slot still exists in
                            # the originating category, so the deterministic name
                            # would recompute to dst_dir — the copy target is
                            # still valid.
                            return True
                        except Exception:
                            return False
                    self._copy_folder_into_container(
                        src_dir, dst_dir, publish_guard=_publish_guard)
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning("duplicate_silo: copying files failed: %s", e)

        self.refresh_temp_presets()
        self._switch_to_slot(new_idx)

    def _copy_folder_into_container(self, src_dir, dst_dir, publish_guard=None):
        """Copy a silo folder into the container via the SAME primitives the
        file panel uses: atomic no-clobber copy, worker-dispatched when the
        tree is large so the GUI thread never walks/copies it.

        ``publish_guard`` (W2-012): revalidated immediately before the final
        rename so an async copy whose destination silo was deleted/moved
        while the worker ran aborts instead of resurrecting an orphan
        directory.
        """
        import uuid

        from fastprompter.ui.file_container import (
            _async_eligible,
            _copy_atomic,
            capture_resolved_root,
            dispatch_container_command,
        )
        cat_dir = os.path.dirname(dst_dir)
        identity = capture_resolved_root(cat_dir)
        items = [("copy", src_dir, dst_dir, True)]
        if _async_eligible(items):
            request = {
                "request_id": uuid.uuid4().hex,
                "owner_id": uuid.uuid4().hex,
                "kind": "dup-copy",
                "publish_guard": publish_guard,
                "origin": os.path.realpath(os.path.abspath(cat_dir)),
                "refresh_identity": os.path.normcase(os.path.abspath(cat_dir)),
                "items": tuple(items),
                "root": cat_dir,
                "root_identity": identity,
                "policy": "IMPORT_TO_CONTAINER",
            }
            worker = dispatch_container_command(request, request["request_id"])
            # P1-15: any directory copy is worker-dispatched, so its
            # completion must be observed or the duplicate lands with a
            # stale "0 files" badge until the next unrelated refresh.
            # One window-level listener, filtered by request kind.
            if getattr(self, "_dup_copy_worker", None) is not worker:
                worker.done.connect(self._on_duplicate_copy_done)
                self._dup_copy_worker = worker
        else:
            _copy_atomic(src_dir, dst_dir, True, cat_dir, identity,
                         publish_guard=publish_guard)

    def _on_duplicate_copy_done(self, request_id, request, done, errors):
        """The async duplicate copy landed on the worker: report any error
        and refresh the silo file badge so the copy never shows 0 files."""
        if request.get("kind") != "dup-copy":
            return
        if errors:
            from fastprompter.core.logging import logger
            logger.warning("duplicate_silo: async copy reported %d error(s): %s",
                           len(errors), errors)
        if (hasattr(self, "btn_files") and not sip.isdeleted(self.btn_files)
                and hasattr(self, "_update_files_button")):
            self._update_files_button()


    def new_child_silo(self, idx, is_archive=False):
        """Create an empty silo directly under `idx` and nest it there."""
        presets = self.data.get("archive_temp_presets" if is_archive else "temp_presets", [])
        if is_archive or not (0 <= idx < len(presets)):
            return
        if self.silo_depth(idx) >= MAX_SILO_DEPTH:
            # a third level would be created but never rendered — refuse
            # instead of silently making a silo that cannot be seen
            return
        new_idx = self._insert_silo_at(idx + 1, "")
        if new_idx is None:
            return  # capacity refused: lose nothing

        cmap = self.data.setdefault("silo_children", {})
        if isinstance(cmap, dict):
            # the map is keyed inconsistently (int vs str) across the app,
            # so find whichever form this parent already uses
            key = next((k for k in cmap if str(k) == str(idx)), idx)
            kids = cmap.setdefault(key, [])
            if isinstance(kids, list) and new_idx not in kids:
                kids.append(new_idx)

        self.mark_dirty()
        self.refresh_temp_presets()
        self._switch_to_slot(new_idx)

    # -- T-589: multi-select silos + batch ops --------------------------------
    def _silo_sel(self):
        """The set of currently multi-selected silo global indices (lazy)."""
        if not isinstance(getattr(self, "_silo_selection", None), set):
            self._silo_selection = set()
        return self._silo_selection

    def toggle_silo_selection(self, idx):
        """Ctrl+click: add/remove one silo from the selection."""
        sel = self._silo_sel()
        sel.discard(idx) if idx in sel else sel.add(idx)
        self._silo_sel_anchor = idx
        self.refresh_temp_presets()

    def range_select_silos(self, idx):
        """Shift+click: select the contiguous range anchor..idx (inclusive)."""
        sel = self._silo_sel()
        anchor = getattr(self, "_silo_sel_anchor", idx)
        lo, hi = sorted((anchor, idx))
        n = len(self.data.get("temp_presets", []))
        sel.update(i for i in range(lo, hi + 1) if 0 <= i < n)
        self.refresh_temp_presets()

    def clear_silo_selection(self):
        """Plain click elsewhere drops the multi-selection."""
        if getattr(self, "_silo_selection", None):
            self._silo_selection = set()
            self.refresh_temp_presets()

    def batch_save_selected_silos(self):
        """Export each selected silo to its files folder (batch 'save')."""
        from fastprompter.core.logging import logger
        for i in sorted(self._silo_sel()):
            try:
                self.backup_silo_to_files(i, is_archive=False)
            except Exception:
                logger.debug("batch save failed for silo %s", i)

    def batch_delete_selected_silos(self):
        """Trash every selected silo (recoverable). Deletes high index first
        so the earlier indices stay valid as the list shrinks.

        A per-item failure (a silo whose files cannot be retired) no longer
        silently leaves the batch half-applied: each result is checked, failed
        silos are kept selected/owned, and a PARTIAL outcome is reported
        instead of pretending completion. One pre-batch undo snapshot keeps
        the successful subset recoverable (P1-6)."""
        from fastprompter.core.logging import logger
        sel = sorted(self._silo_sel(), reverse=True)
        if not sel:
            return
        le = getattr(self, "_current_lang", "EN")
        resp = QMessageBox.question(
            self, tr("Delete selected silos", le),
            tr("Move the selected silos to Trash?", le) + f" ({len(sel)})",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            return
        # single snapshot: the successful subset must stay recoverable
        self.add_data_undo_state("Batch delete silos")
        failures = []
        for i in sel:
            try:
                ok = self.trash_silo(i, is_archive=False, skip_undo=True)
            except Exception:
                ok = False
                logger.debug("batch delete raised for silo %s", i)
            if not ok:
                failures.append(i)
        # W2-007: successful deletions at lower indices shift every surviving
        # higher silo down by one. Remap recorded failures (and the anchor) so
        # the selection still points at the same surviving silos.
        for removed in sel:
            if removed not in failures:
                for f in failures:
                    if f > removed:
                        failures[failures.index(f)] = f - 1
                if hasattr(self, "_silo_sel_anchor") and self._silo_sel_anchor is not None:
                    if self._silo_sel_anchor > removed:
                        self._silo_sel_anchor -= 1
        # preserve the failed/unprocessed silos in the selection so they stay
        # owned and can be retried; only the successfully deleted ones leave.
        self._silo_selection = set(failures)
        if failures:
            from fastprompter.core.logging import logger as _lg
            _lg.warning(
                "batch delete PARTIAL: %d of %d silo(s) not deleted "
                "(assets could not be retired); selection preserved for %s",
                len(failures), len(sel), failures)
        self.refresh_temp_presets()

    @staticmethod
    def _is_descendant_of(node, root, child_of):
        """True if ``node`` sits anywhere under ``root``. Cycle-safe."""
        seen = set()
        cur = child_of.get(node)
        while cur is not None and cur not in seen:
            if cur == root:
                return True
            seen.add(cur)
            cur = child_of.get(cur)
        return False

    def _subtree_end(self, disp_pos, display_order, child_of):
        """Last display position of the subtree rooted at ``disp_pos``.

        A gap anchored to a parent must clear the parent's whole expanded
        group; anchoring it to the parent row alone dropped the divider
        BETWEEN the parent and its own children and cut the group in half.
        Collapsed children are not in display_order, so this naturally
        returns the parent itself and the gap sits right under it."""
        root = display_order[disp_pos]
        end = disp_pos
        j = disp_pos + 1
        while j < len(display_order):
            if not self._is_descendant_of(display_order[j], root, child_of):
                break
            end = j
            j += 1
        return end

    def _apply_conceal_mode(self):
        """Push the Hide-Markup setting into the highlighter.

        Only meaningful while a highlighter is attached, i.e. in a preview
        mode; in Source View there is nothing to conceal. Returns True when
        this call itself rehighlighted (conceal ON), so a caller like the
        live-preview sync can avoid a second full rehighlight.
        """
        hl = getattr(self, "highlighter", None)
        if hl is None or sip.isdeleted(hl):
            return False
        on = self.data.get("live_preview_conceal", "False") == "True"
        hl.set_conceal(on)
        if on and hasattr(self, "text_area"):
            hl.reveal_block = self.text_area.textCursor().blockNumber()
            hl.rehighlight()
            return True
        return False

    def _normalise_int_keys(self, all_key):
        """Coerce every category map under ``data[all_key]`` to int keys.

        JSON has no int keys, so a save/load round-trip returns {"1": ...}
        while every reader indexes with an int. Boot normalises these once,
        but a PROFILE SWITCH swaps in a freshly loaded dict and skipped it —
        so switching profiles flattened the silo hierarchy and killed the
        recency colours until the app was restarted. Mutates in place: these
        maps are aliased, rebinding them would orphan the alias."""
        store = self.data.get(all_key)
        if not isinstance(store, dict):
            return
        if all_key == "silo_children_all":
            # W2-003: canonical two-level normalizer for hierarchy
            for cat, cmap in list(store.items()):
                if not isinstance(cmap, dict):
                    continue
                fixed = {}
                for k, v in cmap.items():
                    try:
                        ik = int(k)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(v, (list, tuple)):
                        continue
                    childs = []
                    for x in v:
                        try:
                            childs.append(int(x))
                        except (TypeError, ValueError):
                            continue
                    if childs:
                        fixed[ik] = childs
                cmap.clear()
                cmap.update(fixed)
            return
        for cmap in store.values():
            if not isinstance(cmap, dict) or all(isinstance(k, int) for k in cmap):
                continue
            fixed = {}
            for k, v in cmap.items():
                try:
                    fixed[int(k)] = v
                except (TypeError, ValueError):
                    continue
            cmap.clear()
            cmap.update(fixed)

    def _slot_list(self, key):
        """The active category's slot-index list for ``key``, always aliased.

        Several callers used to do `lst = data.get(k, [])` and, when the value
        was missing or corrupt, rebind `data[k] = []`. That silently ORPHANS
        the alias into `<key>_all[category]`, so the value stopped being
        per-project and never reached the DB. Creating it here keeps both
        sides pointing at the same list."""
        lst = self.data.get(key)
        if not isinstance(lst, list):
            lst = []
            self.data[key] = lst
            self.data.setdefault(f"{key}_all", {})[self.get_current_category() or ""] = lst
        return lst

    def _silo_gaps_list(self):
        """The active category's gap list, created and aliased if missing."""
        return self._slot_list("silo_gaps")

    def toggle_silo_gap(self, idx):
        """T-590: add/remove a user gap rendered below the silo at ``idx``."""
        # T-716: without this, moving gaps around had NO undo entry, so the
        # next Ctrl+Z reached past them into an unrelated older action.
        self.add_data_undo_state("Toggle silo gap")
        gaps = self._silo_gaps_list()
        if idx in gaps:
            gaps.remove(idx)
            names = self.data.setdefault("silo_gap_names_all", {}).setdefault(self.get_current_category(), {})
            if str(idx) in names:
                del names[str(idx)]
            self.data["silo_gap_names"] = names
        else:
            gaps.append(idx)
        self.mark_dirty()
        self.refresh_temp_presets()

    def move_silo_gap(self, from_idx, to_idx):
        """T-593: drag a gap to sit below a different row.

        This rewrites the anchor slot. A drop onto a row that already has a
        gap, or outside the list, is a no-op instead of silently stacking two.
        (Since T-704 the anchor also rides with its silo through
        `_SILO_INDEX_STATE` — a gap belongs to the silo it was placed under.)"""
        gaps = self._silo_gaps_list()
        n = len(self.data.get("temp_presets", []))
        if from_idx not in gaps or not (0 <= to_idx < n) or to_idx in gaps:
            return False
        # Validated first: a rejected drag must not leave an undo entry behind.
        self.add_data_undo_state("Move silo gap")
        gaps[gaps.index(from_idx)] = to_idx
        # The gap name is keyed by its anchor slot, so it must travel WITH the
        # gap — otherwise the renamed divider keeps its old (now empty) row and
        # the label silently vanishes at the drop row (Ctrl+Drag gap bug).
        # Silo REORDER remaps this key automatically via _SILO_INDEX_STATE; only
        # this direct anchor rewrite must move the name by hand.
        names = self.data.setdefault("silo_gap_names_all", {}).setdefault(
            self.get_current_category(), {})
        old_key = str(from_idx)
        if old_key in names:
            names[str(to_idx)] = names.pop(old_key)
        self.data["silo_gap_names"] = names
        self.mark_dirty()
        self.refresh_temp_presets()
        return True

    def prune_silo_gaps(self):
        """Drop gap anchors that fell off the end (silos deleted).

        A shrinking list can leave an anchor pointing past the last row; it
        would simply never render and would silently resurrect if the list
        grew again."""
        gaps = self.data.get("silo_gaps")
        if not isinstance(gaps, list):
            return
        n = len(self.data.get("temp_presets", []))
        alive = [i for i in gaps if isinstance(i, int) and 0 <= i < n]
        if len(alive) != len(gaps):
            dead = set(gaps) - set(alive)
            gaps[:] = alive
            names = self.data.setdefault("silo_gap_names_all", {}).setdefault(self.get_current_category(), {})
            for d in dead:
                if str(d) in names:
                    del names[str(d)]
            self.data["silo_gap_names"] = names
            self.mark_dirty()

    def show_temp_menu(self, idx, pos, is_archive=False):
        cur = self.text_area.toPlainText().strip()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())

        # -- batch actions (only when a multi-selection is active) -----------
        sel = getattr(self, "_silo_selection", None)
        if not is_archive and sel:
            n = len(sel)
            le = getattr(self, "_current_lang", "EN")
            menu.addAction(tr("💾 Save selected", le) + f" ({n})",
                           lambda: self.batch_save_selected_silos())
            menu.addAction(tr("🗑 Delete selected", le) + f" ({n})",
                           lambda: self.batch_delete_selected_silos())
            menu.addAction(tr("✖ Clear selection", le),
                           lambda: self.clear_silo_selection())
            menu.addSeparator()

        # -- everyday actions ------------------------------------------------
        if not is_archive:
            pinned_list = self.data.get("pinned_silos", [])
            if isinstance(pinned_list, str):
                import ast
                try:
                    pinned_list = ast.literal_eval(pinned_list)
                except Exception:
                    pinned_list = []
            if idx in pinned_list:
                menu.addAction(tr("📌 Unpin", getattr(self, "_current_lang", "EN")), lambda i=idx: self._toggle_pin_silo(i))
            else:
                menu.addAction(tr("📌 Pin to Top", getattr(self, "_current_lang", "EN")), lambda i=idx: self._toggle_pin_silo(i))
            menu.addAction(tr("📥 Archive", getattr(self, "_current_lang", "EN")), lambda i=idx: self.archive_single_silo(i))
            kids = self._children_map().get(idx, [])
            if kids:
                collapsed_now = idx in self.data.get("silo_collapsed", [])
                menu.addAction(
                    "▾ Expand Children" if collapsed_now else f"▸ Collapse Children ({len(kids)})",
                    lambda i=idx: self.toggle_silo_collapse(i))
                # In tab mode a child has nowhere to render — the bar shows
                # top-level silos only — so this menu IS the way to reach it.
                # Harmless in sidebar mode: it is a second route, not the only.
                presets = self.data.get("temp_presets", [])
                kid_menu = menu.addMenu(
                    tr("↳ Children", getattr(self, "_current_lang", "EN"))
                    + f" ({len(kids)})")
                for kid in kids:
                    if not (0 <= kid < len(presets)):
                        continue
                    raw = (presets[kid] or "").replace("\n", " ").strip()
                    label = f"{kid + 1}: {raw[:40]}" if raw else f"{kid + 1}"
                    kid_menu.addAction(label, lambda k=kid: self._switch_to_slot(k))
            if self.silo_parent_of(idx) is not None:
                menu.addAction(tr("⬆ Un-nest from Parent", getattr(self, "_current_lang", "EN")),
                               lambda i=idx: (self.unnest_silo(i), self.refresh_temp_presets()))
        if not is_archive:
            menu.addAction(
                tr("⧉ Duplicate Silo (with files)", getattr(self, "_current_lang", "EN")),
                lambda i=idx: self.duplicate_silo(i))
            menu.addAction(
                tr("↳ New Child Silo", getattr(self, "_current_lang", "EN")),
                lambda i=idx: self.new_child_silo(i))
            preset_menu = menu.addMenu(
                tr("▤ Fill from preset", getattr(self, "_current_lang", "EN")))
            if not self._add_silo_preset_actions(
                    preset_menu, lambda t, i=idx: self.fill_silo_from_preset(i, t)):
                preset_menu.setEnabled(False)
            gaps_now = self.data.get("silo_gaps") or []
            menu.addAction(
                tr("␣ Remove gap below", getattr(self, "_current_lang", "EN"))
                if idx in gaps_now else
                tr("␣ Insert gap below", getattr(self, "_current_lang", "EN")),
                lambda i=idx: self.toggle_silo_gap(i))
            menu.addSeparator()
        menu.addAction(tr("📁 Files…", getattr(self, "_current_lang", "EN")), lambda i=idx, a=is_archive: self.open_file_container(i, a))
        menu.addAction(tr("⚙ Configure Project Paths...", getattr(self, "_current_lang", "EN")), lambda i=idx, a=is_archive: self.open_silo_settings(i, a))

        # Sync/Link this silo with a single file — both sides, live,
        # revertable (Unlink keeps the silo text).
        if not is_archive:
            linked = self._link_file_for_slot(idx)
            if linked:
                act = menu.addAction(
                    tr("🔗 Linked to: ", getattr(self, "_current_lang", "EN"))
                    + os.path.basename(linked))
                act.setEnabled(False)
                menu.addAction(
                    tr("🔓 Unlink this silo (stop syncing)",
                       getattr(self, "_current_lang", "EN")),
                    lambda i=idx: self._unlink_silo_file(i))
            else:
                menu.addAction(
                    tr("🔗 Sync/Link this silo with a file…",
                       getattr(self, "_current_lang", "EN")),
                    lambda i=idx: self._link_silo_to_file(i))

        # -- save ---------------------------------------------------------------
        if cur:
            menu.addSeparator()
            menu.addAction(tr("💾 Save text as Snippet", getattr(self, "_current_lang", "EN")), self.save_snippet)
            menu.addAction(tr("💾 Save as Snippet #…", getattr(self, "_current_lang", "EN")), self.save_snippet_as_number)

        # -- destructive (middle-click already trashes a silo directly) -------
        # Deleting used to appear ONLY on a silo that already had text in it,
        # so an empty one had no delete anywhere in the UI and the whole
        # feature read as missing. It is always offered now; the confirmation
        # is what protects the silo that actually holds something.
        menu.addSeparator()
        menu.addAction(tr("🗑 Delete to Trash", getattr(self, "_current_lang", "EN")),
                       lambda i=idx, a=is_archive: self.prompt_delete_silo(i, a))
        menu.addAction(tr("♻ Manage Trash", getattr(self, "_current_lang", "EN")), self.open_trash_folder)

        menu.addSeparator()
        # Transfer to Snippet
        presets_list = (
            self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        )
        if idx < len(presets_list) and presets_list[idx] and presets_list[idx].strip():
            menu.addAction(
                tr("➡ Transfer to Snippet", getattr(self, "_current_lang", "EN")),
                lambda i=idx, a=is_archive: self._transfer_to_snippet(i, a),
            )
            transfer_menu = menu.addMenu("➡ Transfer to Project")
            _here = self.get_current_category() or ""
            for cat_name in self.data.get("cats_order", list(self.data["categories"].keys())):
                if cat_name not in self.data["categories"]:
                    continue
                if cat_name == _here and not is_archive:
                    continue          # transferring into the current project is a no-op
                transfer_menu.addAction(
                    cat_name,
                    lambda i=idx, a=is_archive, c=cat_name: self.transfer_silo_to_project(i, c, a),
                )
            transfer_menu.setEnabled(not transfer_menu.isEmpty())
            menu.addAction(
                tr("⬆ Move to Top", getattr(self, "_current_lang", "EN")),
                lambda i=idx, a=is_archive: self._move_silo_to_top(i, a),
            )
            menu.addAction(
                tr("⬇ Move to Bottom", getattr(self, "_current_lang", "EN")),
                lambda i=idx, a=is_archive: self._move_silo_to_bottom(i, a),
            )

        # Replace Silo submenu — shows all non-empty silos to copy text from
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        replace_menu = menu.addMenu("🔁 Replace from…")
        has_source = False
        for src_i, src_text in enumerate(presets):
            if src_i == idx or not src_text or not src_text.strip():
                continue
            has_source = True
            label = src_text.strip().replace("\n", " ")[:30] + (
                "…" if len(src_text.strip()) > 30 else ""
            )
            act_label = f"Silo {src_i + 1}: {label}"

            def make_replace(target_idx=idx, src_idx=src_i, archive=is_archive):
                def do_replace():
                    src_presets = (
                        self.data["archive_temp_presets"] if archive else self.data["temp_presets"]
                    )
                    src_presets[target_idx] = src_presets[src_idx]
                    self.mark_dirty()
                    self.refresh_temp_presets()
                    if target_idx == self.active_temp_slot:
                        self._set_plain_text_clean(self.text_area, src_presets[target_idx])

                return do_replace

            replace_menu.addAction(act_label, make_replace())
        if not has_source:
            replace_menu.setEnabled(False)

        # Transform to...
        # CORE-010: silo TYPE is normal-silo state only. The runtime treats
        # archives as text-only (`_apply_silo_type` returns early for them), so
        # offering a Transform on an archive slot would write through the
        # SAME numeric `silo_type_all[category]` namespace used by normal
        # silos — mutating the type of the normal silo at that slot while
        # nothing is rendered for the archive. Do NOT expose the transform for
        # archive slots.
        if not is_archive:
            transform_menu = menu.addMenu(tr("✨ Transform to…", getattr(self, "_current_lang", "EN")))
            current_type = self.data.get("silo_types", {}).get(str(idx), "text")

            def make_transform(tgt_type):
                def _t():
                    self.play_sound("transform")
                    presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
                    text = presets[idx] if idx < len(presets) else ""

                    # An EMPTY silo is the main way into this: make a new silo,
                    # right-click, turn it into a board. The old prompt asked
                    # "Format as one first?" and then formatted nothing whatever
                    # you answered, so Yes and No did the same thing and the user
                    # landed in an empty widget either way. Seed a real starter
                    # instead, and only ask when there is text that would be left
                    # sitting beside the new structure.
                    seeded = self._seed_silo_structure(idx, tgt_type, text, is_archive)
                    if seeded is None:
                        return

                    cat = self.get_current_category() or ""
                    types = self.data.setdefault("silo_type_all", {}).setdefault(cat, {})
                    # write through the SAME dict the alias points at: rebinding
                    # data["silo_types"] is what orphans a per-category store
                    if self.data.get("silo_types") is not types:
                        self.data["silo_types"] = types
                    self.data["silo_types"][str(idx)] = tgt_type
                    if self.active_temp_slot == idx and not is_archive:
                        self._apply_silo_type(idx, is_archive)
                    self.mark_dirty()
                return _t

            a_text = transform_menu.addAction(tr("📄 Text", getattr(self, "_current_lang", "EN")))
            if current_type == "text": a_text.setEnabled(False)
            else: a_text.triggered.connect(make_transform("text"))

            a_kanban = transform_menu.addAction(tr("📋 Kanban Board", getattr(self, "_current_lang", "EN")))
            if current_type == "kanban": a_kanban.setEnabled(False)
            else: a_kanban.triggered.connect(make_transform("kanban"))

            a_table = transform_menu.addAction(tr("📊 Table", getattr(self, "_current_lang", "EN")))
            if current_type == "table": a_table.setEnabled(False)
            else: a_table.triggered.connect(make_transform("table"))


        self.ignore_focus_loss = True
        try:
            menu.exec(pos)
        finally:
            self.ignore_focus_loss = False
        self.activateWindow()



    def _move_silo_identity(self, src_cat, src_idx, dst_cat, dst_idx, is_archive_src, folder_plan=None):
        """Move every identity-owned, slot-keyed store for ONE silo from
        (src_cat, src_idx[/archive namespace]) to (dst_cat, dst_idx).

        Identity-owned means the data describes THIS silo wherever it lives:
        its files folder, project link, watcher queue, type, last-edited
        recency and saved cursor/view state (plus colour and done-tick).
        Positional layout (parent/children, collapse, pin-gap) is intentionally
        NOT moved — it is source-local and only an explicit re-parent would
        transfer it. Archive->normal translation rewrites the ``aN`` queue and
        view keys to the normal ``N`` / ``sN`` form.

        All moves are in-memory ``pop``/``set`` pairs; on failure the caller
        restores via the undo snapshot it already took, so this need not roll
        back per-key. Returned True if at least the text moved.

        CORE-007: ``folder_plan`` is the (src_dir, dst_dir, src_name,
        dst_name) tuple resolved and physically published by the caller
        BEFORE this method runs; the folder mapping follows the physical
        move and records the reserved destination name. The caller must
        never hand a plan whose physical move did not succeed.

        W2-003: uses canonical per-category stores from _PER_CATEGORY_ALIASES,
        never hand-written aliases like ``silo_types_all`` (which does not exist
        in production schema).
        """
        from fastprompter.core.state import _PER_CATEGORY_ALIASES
        skey = str(src_idx)
        dkey = str(dst_idx)
        dst_folder_name = folder_plan[3] if folder_plan else None

        # files folder + project path: per-category *_all stores
        if is_archive_src:
            src_folders = self.data.setdefault("archive_silo_folders_all", {})
            src_paths = self.data.setdefault("archive_project_paths_all", {})
        else:
            src_folders = self.data.setdefault("silo_folders_all", {})
            src_paths = self.data.setdefault("silo_project_paths_all", {})
        dst_folders = self.data.setdefault("silo_folders_all", {})
        dst_paths = self.data.setdefault("silo_project_paths_all", {})
        sfold = src_folders.get(src_cat)
        dfold = dst_folders.setdefault(dst_cat, {})
        if isinstance(sfold, dict) and isinstance(dfold, dict) and skey in sfold:
            src_name = sfold.pop(skey)
            dfold[dkey] = dst_folder_name if dst_folder_name and src_name == folder_plan[2] else src_name
        spath = src_paths.get(src_cat)
        dpath = dst_paths.setdefault(dst_cat, {})
        if isinstance(spath, dict) and isinstance(dpath, dict) and skey in spath:
            dpath[dkey] = spath.pop(skey)

        # colour + type + per-silo file link: canonical per-category *_all
        # stores (W2-003). Per-silo links are ABSOLUTE paths and are
        # self-contained identities, safe to move across projects. Sync-Project
        # map entries are handled SEPARATELY below because their identity is
        # (project root, relative path), not the relative path alone.
        for flat, all_key in _PER_CATEGORY_ALIASES:
            if flat not in ("silo_colors", "silo_types", "silo_links"):
                continue
            sm = self.data.setdefault(all_key, {})
            ssm = sm.get(src_cat)
            ddm = sm.setdefault(dst_cat, {})
            if isinstance(ssm, dict) and isinstance(ddm, dict) and skey in ssm:
                ddm[dkey] = ssm.pop(skey)

        # W2-003: Sync-Project map identity is (project root, relative path),
        # NOT the relative path alone. A map entry moved across projects whose
        # roots differ would be reinterpreted under the destination root and
        # silently bind to a DIFFERENT physical file (and later two-way sync
        # could overwrite it). Resolve the source entry to its exact absolute
        # path and preserve it as a per-silo absolute link when the roots
        # differ; keep the relative map move only when both categories share
        # the same project root.
        smap = self.data.get("project_sync_map_all")
        if isinstance(smap, dict):
            ssm = smap.get(src_cat)
            if isinstance(ssm, dict) and skey in ssm:
                rel = ssm[skey]
                def _cfg_root(cat):
                    cfg = (self.data.get("project_sync_all") or {}).get(cat)
                    if isinstance(cfg, dict) and cfg.get("root"):
                        return os.path.normcase(os.path.abspath(cfg["root"]))
                    return None
                src_root = _cfg_root(src_cat)
                dst_root = _cfg_root(dst_cat)
                if src_root and dst_root and src_root == dst_root:
                    dsm = smap.setdefault(dst_cat, {})
                    if isinstance(dsm, dict):
                        dsm[dkey] = ssm.pop(skey)
                else:
                    ssm.pop(skey)
                    if isinstance(rel, str) and rel and src_root:
                        abs_path = os.path.join(
                            src_root, rel.replace("/", os.sep))
                        links = self.data.setdefault(
                            "silo_links_all", {}).setdefault(dst_cat, {})
                        if isinstance(links, dict):
                            links[dkey] = abs_path

        # last-edited recency: per-category int-keyed store
        le = self.data.get("silo_last_edited_all")
        if isinstance(le, dict):
            sle = le.get(src_cat)
            dle = le.setdefault(dst_cat, {})
            if isinstance(sle, dict) and isinstance(dle, dict) and src_idx in sle:
                dle[dst_idx] = sle.pop(src_idx)

        # watcher queue: canonical watcher_queues_all store (W2-003)
        queues_all = self.data.get("watcher_queues_all")
        if isinstance(queues_all, dict):
            qsrc_store = queues_all.get(src_cat)
            qdst_store = queues_all.setdefault(dst_cat, {})
            qsrc = ("a" + skey) if is_archive_src else skey
            if isinstance(qsrc_store, dict) and isinstance(qdst_store, dict) and qsrc in qsrc_store:
                qdst_store[dkey] = qsrc_store.pop(qsrc)
            # also update the active alias if it still points here
            active_q = self.data.get("watcher_queues")
            if isinstance(active_q, dict) and qsrc in active_q:
                active_q[dkey] = active_q.pop(qsrc)

        # saved silo view/cursor state: per-category "sN"/"aN" keys
        vstore = self.data.get("silo_view_state_all")
        if isinstance(vstore, dict):
            sv = vstore.get(src_cat)
            dv = vstore.setdefault(dst_cat, {})
            if isinstance(sv, dict) and isinstance(dv, dict):
                vsrc = ("a" + skey) if is_archive_src else ("s" + skey)
                vdst = "s" + dkey
                if vsrc in sv:
                    dv[vdst] = sv.pop(vsrc)

        # done-tick: per-category membership list (identity, not layout)
        tstore = self.data.get("silo_ticked_all")
        if isinstance(tstore, dict):
            st = tstore.get(src_cat)
            dt = tstore.setdefault(dst_cat, [])
            if isinstance(st, list) and src_idx in st:
                st.remove(src_idx)
                if isinstance(dt, list) and dst_idx not in dt:
                    dt.append(dst_idx)

    _TRANSFER_STORE_KEYS = (
        "temp_presets_all", "archive_temp_presets_all",
        "pinned_silos_all", "silo_ticked_all", "silo_children_all",
        "silo_collapsed_all", "silo_colors_all", "silo_gaps_all",
        "silo_gap_names_all", "silo_folders_all", "archive_silo_folders_all",
        "silo_project_paths_all", "archive_project_paths_all",
        "watcher_queues_all", "silo_type_all", "silo_last_edited_all",
        "silo_view_state_all",
        "silo_links_all", "project_sync_map_all", "project_sync_all",
    )

    def _capture_category_stores(self, cat):
        """Deep-copied per-category stores of ONE category, for composite
        cross-project undo entries (CORE-008). Missing stores are recorded as
        None so apply can remove what the transfer created."""
        out = {}
        for key in self._TRANSFER_STORE_KEYS:
            store = self.data.get(key)
            if isinstance(store, dict) and cat in store:
                value = store[cat]
                if isinstance(value, dict):
                    out[key] = {k: copy.deepcopy(v) for k, v in value.items()}
                elif isinstance(value, list):
                    out[key] = list(value)
                else:
                    out[key] = None
            else:
                out[key] = None
        return out

    def transfer_silo_to_project(self, idx, target_cat, is_archive=False):
        """Move a silo into another project's SILO list (T-595).

        The old 'Transfer to Project' menu entry called _transfer_to_snippet,
        so the silo landed in the target project's SNIPPETS instead: it
        vanished from the silo list and looked deleted. This moves silo to
        silo, and carries the silo's COMPLETE identity (files folder, project
        link, watcher queue, type, recency, saved cursor/view state, colour
        and done-tick) across the per-category stores, so the destination
        owns everything the source did and the emptied source owns nothing.

        The destination slot is reserved FIRST and the capacity boundary is
        checked BEFORE any source mutation, so a full destination refuses with
        nothing lost and no partial transfer.
        """
        src_presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if not (0 <= idx < len(src_presets)) or not str(src_presets[idx]).strip():
            return False
        if target_cat not in self.data.get("categories", {}):
            return False
        cur_cat = self.get_current_category() or ""
        if target_cat == cur_cat and not is_archive:
            return False                      # already there

        dest = self.data.setdefault("temp_presets_all", {}).setdefault(target_cat, [])
        if not isinstance(dest, list):
            return False

        # W2-005: destination capacity uses TARGET state only, with consistent
        # blank semantics and identity-awareness. Source capacity is irrelevant.
        # A slot is reusable only when semantically blank AND free of identity.
        def _slot_free(slot_idx):
            """True when the destination slot holds NO identity-owned metadata
            of any namespace (CORE-006).

            The free-slot predicate and ``_move_silo_identity`` must agree on
            which stores describe a silo. The canonical set below mirrors
            exactly what ``_move_silo_identity`` moves (colour, type, last
            edited, watcher queue, view/cursor state, done-tick, folder,
            project path), so a destination slot that still carries another
            silo's metadata is REJECTED rather than allowed to contaminate the
            transferred silo.
            """
            text = (dest[slot_idx] or "").strip() if 0 <= slot_idx < len(dest) else ""
            if text:
                return False
            folders = self.data.get("silo_folders_all", {}).get(target_cat, {})
            if isinstance(folders, dict) and str(slot_idx) in folders:
                return False
            afolders = self.data.get("archive_silo_folders_all", {}).get(target_cat, {})
            if isinstance(afolders, dict) and str(slot_idx) in afolders:
                return False
            ppath = self.data.get("silo_project_paths_all", {}).get(target_cat, {})
            if isinstance(ppath, dict) and str(slot_idx) in ppath:
                return False
            colors = self.data.get("silo_colors_all", {}).get(target_cat, {})
            if isinstance(colors, dict) and str(slot_idx) in colors:
                return False
            types = self.data.get("silo_type_all", {}).get(target_cat, {})
            if isinstance(types, dict) and str(slot_idx) in types:
                return False
            last_edited = self.data.get("silo_last_edited_all", {}).get(target_cat, {})
            if isinstance(last_edited, dict) and slot_idx in last_edited:
                return False
            queues = self.data.get("watcher_queues_all", {}).get(target_cat, {})
            if isinstance(queues, dict) and str(slot_idx) in queues:
                return False
            view = self.data.get("silo_view_state_all", {}).get(target_cat, {})
            if isinstance(view, dict) and ("s" + str(slot_idx)) in view:
                return False
            ticked = self.data.get("silo_ticked_all", {}).get(target_cat, [])
            if isinstance(ticked, list) and slot_idx in ticked:
                return False
            links = self.data.get("silo_links_all", {}).get(target_cat, {})
            if isinstance(links, dict) and str(slot_idx) in links:
                return False
            sync_map = self.data.get("project_sync_map_all", {}).get(target_cat, {})
            if isinstance(sync_map, dict) and str(slot_idx) in sync_map:
                return False
            return True

        max_slots = self.MAX_SILOS_PER_CATEGORY
        # Find first reusable blank slot; if none, grow bounded by max.
        dslot = None
        for i in range(len(dest)):
            if _slot_free(i):
                dslot = i
                break
        appending = False
        if dslot is None and len(dest) < max_slots:
            # Target has room but every existing slot holds identity — reserve a
            # NEW slot index WITHOUT mutating `dest` yet (CORE-005). The list is
            # only grown in the atomic commit phase, AFTER every preflight and
            # the physical folder move have succeeded, so a refused transfer can
            # never leave a phantom blank slot eating the capacity.
            dslot = len(dest)
            appending = True
        elif dslot is None:
            return False                          # truly full: lose nothing

        text = src_presets[idx]

        # CORE-007: resolve the physical folder relocation BEFORE any
        # mutation. The source category root and the destination root are
        # resolved now; a down/unreachable custom root refuses the transfer
        # (fail closed: a folder mapping must never detach from the physical
        # folder it identifies). The destination name is reserved against
        # both the destination mapping and the destination directory, so a
        # name collision renames the incoming folder instead of clobbering.
        folder_plan = None
        fsrc = self.data.setdefault(
            "archive_silo_folders_all" if is_archive else "silo_folders_all", {})
        fmap_src = fsrc.get(cur_cat)
        if isinstance(fmap_src, dict) and str(idx) in fmap_src and fmap_src[str(idx)]:
            src_name = fmap_src[str(idx)]
            comp_src = self._category_files_dir(cur_cat)
            comp_dst = self._category_files_dir(target_cat)
            if comp_src is None or comp_dst is None:
                return False
            root = self._files_root()
            src_dir = os.path.join(root, comp_src, src_name)
            dfold = self.data.setdefault("silo_folders_all", {}).setdefault(target_cat, {})
            taken = set(dfold.values())
            dst_comp_dir = os.path.join(root, comp_dst)
            dst_name, n = src_name, 2
            while dst_name in taken or os.path.isdir(os.path.join(dst_comp_dir, dst_name)):
                dst_name = f"{src_name}-{n}"
                n += 1
            folder_plan = (src_dir, os.path.join(dst_comp_dir, dst_name), src_name, dst_name)

        # W2-004/CORE-008: ONE composite before-state covering both owners —
        # the source (standard snapshot keys) and the destination (captured
        # per-category stores). Exactly one undo entry per transfer; the old
        # duplicate generic snapshot and the unused _transfer_* fields are
        # gone.
        snap = self._snapshot_current()
        snap["_transfer"] = True
        snap["_transfer_dst_cat"] = target_cat
        snap["_transfer_dst_before"] = self._capture_category_stores(target_cat)
        # CORE-004: record the physical folder transaction so undo/redo can
        # reverse it symmetrically with the store transaction. Stored in the
        # REVERSED orientation (dst -> src): the snapshot is applied by UNDO,
        # which reverses the transfer; the REDO entry inverts it back to
        # forward (src -> dst).
        snap["_transfer_folder"] = (
            (folder_plan[1], folder_plan[0], folder_plan[3], folder_plan[2])
            if folder_plan else None)

        # The only fallible step runs FIRST, before any in-memory mutation:
        # a failed physical move must leave text, mapping and files exactly
        # as they were (no partial transfer, no orphaned folder).
        if folder_plan is not None:
            # CORE-004: a mapped source folder must actually exist on disk. If
            # the mapping names a directory that is missing, refuse the whole
            # transfer (fail closed) instead of committing a detached mapping
            # while leaving the bytes behind.
            if not os.path.isdir(folder_plan[0]):
                from fastprompter.core.logging import logger
                logger.warning("silo folder transfer refused: mapped source "
                               "%s does not exist; nothing changed",
                               folder_plan[0])
                return False
            try:
                # CORE-004: the destination category's physical directory may
                # not exist yet (a fresh category with no files); create it
                # before the rename or the move fails with WinError 3.
                os.makedirs(os.path.dirname(folder_plan[1]), exist_ok=True)
                os.rename(folder_plan[0], folder_plan[1])
            except OSError as e:
                from fastprompter.core.logging import logger
                logger.warning("silo folder transfer %s -> %s failed: %s; "
                               "transfer refused, nothing changed",
                               folder_plan[0], folder_plan[1], e)
                return False
            # W2-002: a drawer bound to the source location just lost its
            # storage owner — the folder now lives under the destination.
            if hasattr(self, "_detach_file_container_for"):
                self._detach_file_container_for(folder_plan[0])

        # CORE-005: reserve the destination slot ONLY now — after every
        # preflight and the physical folder move have succeeded. A refused
        # transfer (missing source dir, rename failure) returns above without
        # ever touching `dest`, so capacity is preserved exactly.
        if appending:
            dest.append(text)
        else:
            dest[dslot] = text

        # move the silo's full identity across the per-category stores
        self._move_silo_identity(cur_cat, idx, target_cat, dslot, is_archive, folder_plan)

        # empty the source row and drop its source-local positional membership
        src_presets[idx] = ""
        for key in ("pinned_silos", "silo_collapsed"):
            lst = self.data.get(key)
            if isinstance(lst, list) and idx in lst:
                lst.remove(idx)
        if not is_archive:
            self.unnest_silo(idx) if hasattr(self, "unnest_silo") else None

        if idx == self.active_temp_slot and not getattr(self, "editing_snippet", None):
            self.clear_text(internal=True)

        # stamp the AFTER half into the same composite entry and push it as
        # ONE logical undo record
        snap["_transfer_dst_after"] = self._capture_category_stores(target_cat)
        self._stamp_snapshot(snap)
        self.data_undo_stack.append(snap)
        self._push_undo_state(snap, "Transfer silo to project")

        self.mark_dirty()
        self.refresh_temp_presets()
        self.play_sound("snippet")
        return True

    def _transfer_to_snippet(self, idx, is_archive, target_cat=None):
        """Transfer silo content to a new snippet in the current (or given) category."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if idx >= len(presets) or not presets[idx] or not presets[idx].strip():
            return
        text = presets[idx]
        cat = target_cat if target_cat in self.data["categories"] else self.get_current_category()
        if not cat:
            return
        slots = self.data["categories"][cat]
        if None not in slots:
            return
        self.add_data_undo_state("Transfer to snippet")
        empty_idx = slots.index(None)
        name = text.replace("\n", " ")[:22]
        if len(text) > 22:
            name += "..."
        slots[empty_idx] = {"name": name, "text": text, "last_edited": int(time.time())}
        presets[idx] = ""
        if idx == self.active_temp_slot and not getattr(self, "editing_snippet", None):
            self.clear_text(internal=True)
        self.mark_dirty()
        self.refresh_snippets_panel()
        self.refresh_temp_presets()
        self.play_sound("snippet")

    def _children_map(self):
        cmap = self.data.get("silo_children")
        if not isinstance(cmap, dict):
            return {}
        # Skip normalization if this exact dict was already cleaned.
        cmap_id = id(cmap)
        if getattr(self, "_cmap_norm_id", None) == cmap_id:
            return cmap
        # Drop parents whose last child went away. An empty list means
        # nothing, but it lingers in the saved data and makes equality
        # checks (and eyeballing the map) needlessly confusing.
        empty = [k for k, v in cmap.items() if not v]
        for k in empty:
            cmap.pop(k, None)
        # Every caller looks these up with an INT slot index. A str key makes
        # the lookup miss, which does not merely drop the indent: the child is
        # still counted as somebody's kid, so it is excluded from the top
        # level and then never emitted under its parent — the silo disappears
        # from the sidebar. Normalise in place, at the single read point.
        # W2-003: always normalize both levels, not only when parent keys are strings
        need = any(not isinstance(k, int) for k in cmap) or any(
            not isinstance(x, int) for v in cmap.values() if isinstance(v, (list, tuple)) for x in v)
        if need:
            fixed = {}
            for k, v in cmap.items():
                try:
                    ik = int(k)
                except (TypeError, ValueError):
                    continue
                if not isinstance(v, (list, tuple)):
                    continue
                childs = []
                for x in v:
                    try:
                        childs.append(int(x))
                    except (TypeError, ValueError):
                        continue
                if childs:
                    fixed[ik] = childs
            cmap.clear()
            cmap.update(fixed)
        self._cmap_norm_id = cmap_id
        return cmap

    def silo_depth(self, idx, _seen=None):
        """0 for a top-level silo, 1 for a child, 2 for a grandchild."""
        depth = 0
        seen = set()
        cur = idx
        while True:
            parent = self.silo_parent_of(cur)
            if parent is None or parent in seen:
                return depth
            seen.add(parent)
            depth += 1
            cur = parent
            if depth > MAX_SILO_DEPTH + 1:
                return depth        # cycle guard

    def _is_descendant(self, candidate, ancestor):
        """Is `candidate` somewhere below `ancestor`?"""
        seen = set()
        cur = candidate
        while True:
            parent = self.silo_parent_of(cur)
            if parent is None or parent in seen:
                return False
            if parent == ancestor:
                return True
            seen.add(parent)
            cur = parent

    def silo_parent_of(self, idx):
        for p, kids in self._children_map().items():
            if idx in kids:
                return p
        return None

    def make_silo_child(self, child_idx, parent_idx):
        """Nest child under parent (1 level). The child's own children are
        promoted; its files merge into the parent's container on confirm."""
        if child_idx == parent_idx:
            return
        cmap = self.data.setdefault("silo_children", {})
        if self.silo_depth(parent_idx) >= MAX_SILO_DEPTH:
            return  # would exceed 1 -> 1.1 -> 1.1.1
        if self._is_descendant(parent_idx, child_idx):
            return  # refuse to nest a silo under its own descendant
        if child_idx in cmap.get(parent_idx, []):
            return
        self.add_data_undo_state("Nest silo")
        # keep the moved silo's own children ONLY if they still fit within
        # the depth limit at the new position; otherwise promote them
        if self.silo_depth(parent_idx) + 1 >= MAX_SILO_DEPTH:
            cmap.pop(child_idx, None)
        for kids in cmap.values():
            if child_idx in kids:
                kids.remove(child_idx)
        cmap.setdefault(parent_idx, []).append(child_idx)
        pinned = self.data.get("pinned_silos", [])
        if isinstance(pinned, list) and child_idx in pinned:
            pinned.remove(child_idx)  # children live under their parent, not in the pin bar
        # W2-004: the optional physical merge belongs to the SAME undoable
        # transaction as the hierarchy change. The exact move ledger rides on
        # the snapshot just pushed, so Ctrl+Z reverses files and nesting
        # together (and a restart cannot forget which owner each moved file
        # has) — the ledger persists inside the undo JSON.
        ledger = self._merge_child_files(child_idx, parent_idx)
        if ledger:
            stack = getattr(self, "data_undo_stack", None)
            if stack:
                rec = stack[-1]
                if isinstance(rec, dict):
                    rec["_merge_ledger"] = [
                        [pair[0], pair[1]] for pair in ledger]
                    self._save_undo_state()
        self.mark_dirty()
        self.refresh_temp_presets()

    def reorder_sibling(self, idx, before_idx=None):
        """Move a child to another position among its OWN siblings.

        Children are rendered in the order of the parent's child list, not
        in slot order, so reordering them means editing that list. Dropping
        a child in a gap used to call unnest_silo() unconditionally, which
        threw it out of the parent every time someone merely reordered it.
        """
        parent = self.silo_parent_of(idx)
        if parent is None:
            return False
        kids = self._children_map().get(parent) or []
        if idx not in kids:
            return False
        rest = [k for k in kids if k != idx]
        if before_idx is not None and before_idx in rest:
            rest.insert(rest.index(before_idx), idx)
        else:
            rest.append(idx)                    # dropped past the last sibling
        if rest == kids:
            return False
        kids[:] = rest
        self.mark_dirty()
        self.refresh_temp_presets()
        return True

    def unnest_silo(self, idx):
        """Promote a child back to top level (dragging it out does this)."""
        changed = False
        cmap = self._children_map()
        if not isinstance(cmap, dict):
            return False
        for parent, kids in list(cmap.items()):
            if idx in kids:
                kids.remove(idx)
                if not kids:
                    # a parent whose last child left must not linger as an
                    # empty key: the index remap then carries the corpse to
                    # the wrong slot and exact-equality readers see ghosts
                    del cmap[parent]
                changed = True
        if changed:
            self.mark_dirty()
        return changed

    def toggle_silo_collapse(self, idx):
        collapsed = self.data.setdefault("silo_collapsed", [])
        if idx in collapsed:
            collapsed.remove(idx)
        else:
            collapsed.append(idx)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _merge_child_files(self, child_idx, parent_idx):
        """A nested silo's files can merge into the parent's folder —
        asked once, moved with collision-safe names, never overwritten."""

        from fastprompter.ui.file_container import _unique_dest
        presets = self.data.get("temp_presets", [])
        if not (0 <= child_idx < len(presets) and 0 <= parent_idx < len(presets)):
            return
        src = self._silo_folder_dir(child_idx)
        dst = self._silo_folder_dir(parent_idx)
        try:
            names = os.listdir(src)
        except OSError:
            return
        if not names or os.path.abspath(src) == os.path.abspath(dst):
            return
        box = QMessageBox(self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle(tr("Merge files", self._current_lang))
        box.setText(
            tr("The nested silo owns {} file(s).\nMerge them into the parent silo's Files?\n(collisions get ' (2)' names — nothing is overwritten)", self._current_lang).format(len(names)))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        prev = getattr(self, "ignore_focus_loss", False)
        self.ignore_focus_loss = True
        try:
            ans = box.exec()
        finally:
            self.ignore_focus_loss = prev
        if ans != QMessageBox.StandardButton.Yes:
            return
        os.makedirs(dst, exist_ok=True)
        from fastprompter.ui.file_container import _move_into_container, capture_resolved_root
        identity = capture_resolved_root(dst)
        moved = 0
        # W2-004: the merge is part of the SAME undoable transaction as the
        # nesting itself, so every successful move is recorded as an exact
        # (original_child_path, published_parent_path) pair — including
        # collision-renamed destinations — and attached to the nesting undo
        # record by the caller.
        ledger = []
        for n in names:
            try:
                # the same safe move primitive the file panel uses: no-clobber
                # by construction, containment-checked at mutation time — a
                # hand-rolled _unique_dest + shutil.move had a TOCTOU where a
                # file appearing at the destination was silently overwritten
                dest = _unique_dest(dst, n)
                src_file = os.path.join(src, n)
                _move_into_container(src_file, dest, dst, identity)
                moved += 1
                ledger.append((os.path.abspath(src_file), os.path.abspath(dest)))
            except OSError as e:
                from fastprompter.core.logging import logger
                logger.warning(f"Child file merge failed for {n}: {e}")
        try:
            if moved:
                os.rmdir(src)
        except OSError:
            pass
        return ledger

    def _toggle_tick_silo(self, idx):
        """Toggle the ✅ done-mark on a silo (persists per project)."""
        # PERF-002: one bool flip gets a compact record, not a project copy.
        ticked = self._slot_list("silo_ticked")
        rec = self.add_compact_meta_undo("tick", idx, idx in ticked)
        if idx in ticked:
            ticked.remove(idx)
        else:
            ticked.append(idx)
        self._finish_compact_meta_undo(rec, idx in ticked)
        self.play_tick_sound(idx in ticked)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _toggle_pin_silo(self, idx):
        """Toggle pin/unpin status for a silo."""
        # PERF-002: compact record — see add_compact_meta_undo.
        pinned = self._slot_list("pinned_silos")
        rec = self.add_compact_meta_undo("pin", idx, idx in pinned)
        if idx in pinned:
            pinned.remove(idx)
        else:
            pinned.insert(0, idx)
        self._finish_compact_meta_undo(rec, idx in pinned)
        self.mark_dirty()
        self.refresh_temp_presets()

    def _move_silo_to_bottom(self, idx, is_archive=False):
        """Move a silo to the bottom — via move_temp_to_index so pins,
        ticks and children indices are remapped with it."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if 0 <= idx < len(presets) - 1:
            self.move_temp_to_index(idx, len(presets) - 1, is_archive=is_archive)

    def _move_silo_to_top(self, idx, is_archive=False):
        """Move a silo to the top of the order (same remap guarantees)."""
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if 0 < idx < len(presets):
            self.move_temp_to_index(idx, 0, is_archive=is_archive)

    def clear_temp(self, idx, is_archive=False):
        # Clicking clear on an already-empty silo removes the slot entirely.
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if (
            0 <= idx < len(presets)
            and not presets[idx].strip()
            and len(presets) > 1
            and getattr(self, "active_is_archive", False) == is_archive
        ):
            self.del_silo(idx)
            return
        pushed_undo = self.add_data_undo_state("Clear silo")
        self.play_sound("clear")

        if 0 <= idx < len(presets):
            # CORE-001: stage the durable recovery copy FIRST. A write failure
            # must refuse the clear entirely — the slot text is NOT wiped.
            folder = self._silo_folder_dir(idx, is_archive=is_archive)
            # CORE-003: pass the EXACT original folder path for a unique link.
            folder_path = os.path.abspath(folder) if folder else None
            staged = self._trash_silo_content(
                presets[idx], folder_name=folder_path)
            if staged is False:
                from fastprompter.core.logging import logger as _lg
                _lg.warning("silo clear ABORTED (slot %d, archive=%s): "
                            "trash write failed; the slot was NOT wiped",
                            idx, is_archive)
                if self.data_undo_stack and \
                        self.data_undo_stack[-1] is pushed_undo:
                    self.data_undo_stack.pop()
                self._save_undo_state()
                return
            if hasattr(self, "_delete_file_container"):
                if folder is None:
                    retire = "ROOT_UNAVAILABLE"
                else:
                    retire = self._delete_file_container(
                        self.get_current_category(), folder)
                if retire in ("FAILED", "ROOT_UNAVAILABLE"):
                    # P0-7: ABORT — the slot is NOT wiped. Drop the redundant
                    # staged recovery copy so trash does not claim a clear that
                    # never happened.
                    if isinstance(staged, str):
                        try:
                            os.remove(staged)
                            self.data.get("trash_text_folder", {}).pop(
                                os.path.basename(staged), None)
                        except OSError:
                            pass
                    from fastprompter.core.logging import logger as _lg
                    _lg.warning("silo clear ABORTED (slot %d, archive=%s): "
                                "folder retirement %s; the slot was NOT "
                                "wiped", idx, is_archive, retire)
                    if self.data_undo_stack and \
                            self.data_undo_stack[-1] is pushed_undo:
                        self.data_undo_stack.pop()
                    self._save_undo_state()
                    return
                # P1-9: drop the ownership mapping ONLY for a confirmed
                # retirement; FAILED / ROOT_UNAVAILABLE keep it so the assets
                # stay recoverable and the map never lies. By the time we are
                # here the retirement is confirmed, so the maps are dropped.
                if not is_archive:
                    self.data.get("silo_folders", {}).pop(str(idx), None)
                    self.data.get("silo_project_paths", {}).pop(str(idx), None)
                else:
                    self.data.get("archive_silo_folders", {}).pop(str(idx), None)
                    self.data.get("archive_project_paths", {}).pop(str(idx), None)

        if is_archive:
            self.data["archive_temp_presets"][idx] = ""
            if idx == self.active_temp_slot and getattr(self, "active_is_archive", False):
                self.clear_text(internal=True)
            self._trim_archive()
            self.refresh_archive_panel()
        else:
            # archiving is NOT an edit of the silo's text, so a synced silo
            # must not push its now-empty text into its file: drop the
            # bindings first (the file on disk survives untouched)
            self._drop_slot_bindings(idx)
            self.data["temp_presets"][idx] = ""
            if idx == self.active_temp_slot and not getattr(self, "active_is_archive", False):
                self.clear_text(internal=True)
            self.refresh_temp_presets()
        self.mark_dirty()

    def archive_single_silo(self, idx):
        """Archive a specific silo by index (called from hover button).

        Routes through the ONE canonical silo->archive transaction (T-754)
        shared with archive_active_silo, so the text, folder, project path
        and queue always move as a unit regardless of which entry point
        fired."""
        self._archive_silo(idx)

    def safe_set_clipboard(self, text):
        if text:
            from PyQt6.QtGui import QGuiApplication

            clip = QGuiApplication.clipboard()
            clip.setText(text)

    def insert_divider_line(self):
        """Ctrl+W: alias for the toolbar's Insert Line command — single
        implementation lives in FormattingMixin.insert_add_line so the two
        entry points can never silently diverge again."""
        self.insert_add_line()

    def auto_paste(self, text):
        if not text.strip():
            return
        self.safe_set_clipboard(text)
        self.hide_and_save()
        QTimer.singleShot(150, lambda: not sip.isdeleted(self) and self.simulate_ctrl_v())

    @staticmethod
    def simulate_ctrl_v():
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            )

        class INPUT_union(ctypes.Union):
            _fields_ = (("ki", KEYBDINPUT), ("mi", ctypes.c_ulong * 6), ("hi", ctypes.c_ulong * 6))

        class INPUT(ctypes.Structure):
            _fields_ = (("type", ctypes.c_ulong), ("union", INPUT_union))

        def send_key(vk, up=False):
            i = INPUT(type=1)
            i.union.ki.wVk = vk
            i.union.ki.dwFlags = 2 if up else 0
            ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))

        VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x12, 0x5B, 0x5C
        VK_CTRL, VK_V = 0x11, 0x56

        for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                send_key(vk, True)

        send_key(VK_CTRL)
        send_key(VK_V)
        send_key(VK_V, True)
        send_key(VK_CTRL, True)

    def setup_global_shortcuts(self):
        for shortcut in getattr(self, "_app_shortcuts", []):
            shortcut.deleteLater()
        self._app_shortcuts = []

        # Physical-key fallback so every shortcut below keeps working on a
        # non-Latin keyboard layout (Qt matches the character, not the key).
        from fastprompter.ui.layout_shortcuts import LayoutIndependentShortcuts

        flt = getattr(self, "_layout_shortcuts", None)
        if flt is None:
            flt = LayoutIndependentShortcuts(self)
            self._layout_shortcuts = flt
            QApplication.instance().installEventFilter(flt)
        flt.clear()

        def add_shortcut(key_name, default_seq, slot, context=Qt.ShortcutContext.WindowShortcut):
            seq_str = self.data.get(key_name, default_seq)
            if not seq_str: return
            seq = QKeySequence(seq_str)
            slot = self._with_hotkey_sound(key_name, slot)
            shortcut = QShortcut(seq, self, context=context)
            shortcut.activated.connect(slot)
            self._app_shortcuts.append(shortcut)
            flt.register(seq, slot)

        add_shortcut("hk_focus", "Ctrl+D", self.cycle_focus_mode)
        add_shortcut("hk_find", "Ctrl+F", self.toggle_find)
        add_shortcut("hk_replace", "Ctrl+H", self.show_replace)
        add_shortcut("hk_export_silo", "Ctrl+Shift+S", self.save_silo_to_file)

        # Previously global hotkeys, now local to app window.
        # Canonical map (per profile, T-814): Alt+E = lock, Alt+S = always on
        # top. The _alt slots are the user's second combo from the settings
        # dialog and are bound exactly like the primary ones (a configured
        # _alt that went nowhere was the migration bug this wires up).
        add_shortcut("lock_window_hotkey", "Alt+E", self.toggle_lock)
        add_shortcut("always_on_top_hotkey", "Alt+S", self.toggle_always_on_top)
        add_shortcut("toggle_sidebar_hotkey", "Alt+D", lambda: self.toggle_visibility(force_sidebar=True))
        add_shortcut("hide_on_clickout_hotkey", "Alt+A", self.toggle_hide_on_clickout)
        add_shortcut("lock_window_hotkey_alt", "", self.toggle_lock)
        add_shortcut("always_on_top_hotkey_alt", "", self.toggle_always_on_top)
        add_shortcut("toggle_sidebar_hotkey_alt", "",
                     lambda: self.toggle_visibility(force_sidebar=True))
        add_shortcut("hide_on_clickout_hotkey_alt", "", self.toggle_hide_on_clickout)

        shortcut = QShortcut(QKeySequence("Esc"), self)
        shortcut.activated.connect(self._on_escape)
        self._app_shortcuts.append(shortcut)

        add_shortcut("hk_save_snippet", "Ctrl+S", self.save_snippet)
        add_shortcut("hk_new_snippet", "Ctrl+N", lambda: self.select_empty_silo(insertion="top"), Qt.ShortcutContext.ApplicationShortcut)
        add_shortcut("hk_divider", "Ctrl+W", self.insert_divider_line, Qt.ShortcutContext.ApplicationShortcut)
        add_shortcut("hk_snap", "Ctrl+Q", self.cycle_snap_corner)
        add_shortcut("hk_quit", "Ctrl+Alt+Shift+Q", self.quit_app)
        add_shortcut("hk_header", "Ctrl+E", self.apply_header_timestamp)
        add_shortcut("hk_quote", "Ctrl+Shift+Q", self.toggle_quote_conversion)
        add_shortcut("hk_line_nums", "Alt+Z",
                     lambda: self.set_line_numbers(
                         self.data.get("show_line_numbers", "False") != "True"))
        add_shortcut("hk_settings", "Alt+`", self.toggle_mini_settings)
        add_shortcut("hk_bold", "Ctrl+B", self.apply_bold_smart)
        add_shortcut("hk_undo", "Ctrl+Z", self._smart_undo)
        # Timer and Hashtag dialogs were only reachable by clicking their
        # labels, while the cheatsheet and User-Guide have always advertised
        # Ctrl+Shift+T / Alt+Shift+T. Bind them so the docs tell the truth.
        add_shortcut("hk_timers", "Ctrl+Shift+T", self.open_timer_dialog)
        add_shortcut("hk_hashtags", "Alt+Shift+T", self.open_hashtag_dialog)
        # Alt+C queues the current line; Alt+Shift+C opens the this-silo queue.
        add_shortcut("hk_queue_master", "Alt+Shift+C", self.open_queue_master,
                     Qt.ShortcutContext.ApplicationShortcut)

        def add_fixed(seq_str, slot, context=Qt.ShortcutContext.WindowShortcut):
            slot = self._with_hotkey_sound(seq_str, slot)
            shortcut = QShortcut(QKeySequence(seq_str), self, context=context)
            shortcut.activated.connect(slot)
            self._app_shortcuts.append(shortcut)

        add_fixed("Ctrl+Shift+Z", self._smart_redo)
        # Ctrl+Y was text-only (handled inside the editor), so a data undo had
        # exactly one redo key and you had to know which one.
        add_fixed("Ctrl+Y", self._smart_redo)
        add_fixed("Ctrl+Shift+C", self.clear_text)
        # Alt+W is Ctrl+W turned around: the new point goes ABOVE and the
        # existing text moves down. It used to insert the plain toolbar
        # divider, which had no settings of its own at all.
        add_fixed("Alt+W", self.insert_add_line_up, Qt.ShortcutContext.ApplicationShortcut)
        add_fixed("Alt+Up", lambda: self.navigate_silo(-1), Qt.ShortcutContext.WindowShortcut)
        add_fixed("Alt+Down", lambda: self.navigate_silo(1), Qt.ShortcutContext.WindowShortcut)
        add_shortcut("hk_italic", "Ctrl+I", lambda: self.apply_format("italic"))
        add_shortcut("hk_underline", "Ctrl+U", lambda: self.apply_format("underline"))
        # Ctrl+T (strike) is handled inside the editor's keyPressEvent
        # (editor.py:2825) — a shortcut here would fire a SECOND time on top
        # of the editor path and toggle the strike twice for one keypress.
        # The editor path plays its own "strike" sound.

        for i in range(1, 13):
            key_num = i % 10
            # F-keys navigate PROJECTS (tabs) by default; set
            # data["fkey_action"]="snippets" to restore snippet execution.
            # Ctrl+Shift+N still runs snippets either way.
            add_fixed(f"F{i}", lambda i=i: self._fkey_navigate(i))
            if i <= 10:
                add_fixed(f"Ctrl+{key_num}", lambda i=i: self._switch_to_slot(i - 1))
                add_fixed(f"Ctrl+Shift+{key_num}", lambda i=i: self.fire_shortcut(i))

        # Previously global snippet/silo hotkeys, now local to app window
        for i in range(5):
            seq_str = self.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i + 1}")
            if seq_str:
                add_fixed(seq_str, lambda i=i: self.fire_global_snippet(i))
            seq_str = self.data.get(f"silo_{i}_hotkey", f"Alt+Shift+Numpad{i + 1}")
            if seq_str:
                add_fixed(seq_str, lambda i=i: self.fire_global_silo(i))
            # the dialog's second combo for each row must be bound too, or a
            # user who sets it gets a setting that silently does nothing
            add_shortcut(f"snippet_{i}_hotkey_alt", "",
                         lambda i=i: self.fire_global_snippet(i))
            add_shortcut(f"silo_{i}_hotkey_alt", "",
                         lambda i=i: self.fire_global_silo(i))

    def _fkey_navigate(self, idx):
        """F1-F10: switch to Project N. Configurable via
        ``data["fkey_action"]``: ``"projects"`` (default) navigates tabs,
        ``"snippets"`` restores the legacy snippet execution."""
        if str(self.data.get("fkey_action", "projects")) == "snippets":
            self.fire_shortcut(idx)
            return
        combo = getattr(self, "cat_combo", None)
        if combo is None or combo.count() == 0:
            return
        target = min(idx - 1, combo.count() - 1)
        if target >= 0:
            combo.setCurrentIndex(target)

    def fire_shortcut(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat:
            return
        query = self._snippet_query()
        active_items = []
        for i, s in enumerate(self.data["categories"][cat]):
            if s is not None:
                if self._match_snippet_query(query, s):
                    active_items.append((i, s))

        page = self.current_pages.get(cat, 0)
        start_idx = page * 10
        page_items = active_items[start_idx : start_idx + 10]

        i = idx - 1
        if i < len(page_items):
            global_idx, item = page_items[i]
            self.auto_paste(item["text"])

    def show_quick_list(self):
        self.play_sound("tick")
        w = QuickListWidget(self)
        w.show()

    def fire_global_snippet(self, idx):
        self.play_sound("snippet")
        cat = self.get_current_category()
        if not cat:
            return
        active = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active):
            self.auto_paste(active[idx]["text"])

    def fire_global_silo(self, idx):
        self.play_sound("silo")
        if 0 <= idx < len(self.data.get("temp_presets", [])):
            text = self.data["temp_presets"][idx]
            if text.strip():
                self.auto_paste(text)

    def fire_global_snippet_from_cat(self, cat, idx):
        self.play_sound("snippet")
        if not cat:
            return
        active_snippets = [s for s in self.data["categories"].get(cat, []) if s is not None]
        if 0 <= idx < len(active_snippets):
            self.auto_paste(active_snippets[idx]["text"])

    def cycle_snap_corner(self):
        """Ctrl+Q: open the FancyZones picker on the monitor under the cursor.

        (Kept under the old name so the existing hk_snap binding, tooltips
        and any saved user hotkey keep working.)

        In Fast mode the picker never appears: each press steps to the next
        zone of the page chosen in Settings.
        """
        if self.data.get("fancyzones_fast", "False") == "True":
            if self._fancy_zones.apply_fast(self, 1):
                self.mark_dirty()
                return
        self._fancy_zones.open_for(self)

    _TS_RE = None  # compiled lazily below

    def _update_line_count_label(self):
        lbl = getattr(self, "lbl_line_count", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        doc = self.text_area.document()
        lines = doc.blockCount() if doc.characterCount() > 1 else 0

        # P0/P2 Fix: cache line-label QFontMetrics width
        needed_width = getattr(self, "_line_count_width", None)
        if needed_width is None:
            from PyQt6.QtGui import QFontMetrics
            fm = QFontMetrics(lbl.font())
            needed_width = fm.horizontalAdvance("0 L") + 4
            self._line_count_width = needed_width

        if lbl.minimumWidth() != needed_width:
            lbl.setMinimumWidth(needed_width)
            from PyQt6.QtCore import Qt
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl.setText(f"{lines} L" if lines else "")
        self._update_token_count_label()

    # Two ways to guess a token count without shipping a tokenizer. Chars are
    # the better proxy for prose in any language; words are the better proxy
    # for English-ish text with a lot of punctuation. Both are estimates and
    # the label says so with a leading ~.
    TOKEN_MODES = ("chars", "words")

    def token_estimate(self, text):
        """Rough token count for this text under the user's chosen weighting."""
        if not text:
            return 0
        mode = self.data.get("token_mode", "chars")
        try:
            weight = float(self.data.get("token_weight", 4.0))
        except (TypeError, ValueError):
            weight = 4.0
        if mode == "words":
            return int(round(len(text.split()) * max(0.1, min(10.0, weight))))
        weight = max(1.0, min(20.0, weight))
        return int(round(len(text) / weight))

    @staticmethod
    def _short_count(n):
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1000:
            return f"{n / 1000:.1f}k"
        return str(n)

    def _update_token_count_label(self):
        lbl = getattr(self, "lbl_token_count", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        if self.data.get("show_token_count", "False") != "True":
            lbl.setVisible(False)
            return

        doc = self.text_area.document()
        raw_chars = max(0, doc.characterCount() - 1)
        mode = self.data.get("token_mode", "chars")
        try:
            weight = float(self.data.get("token_weight", 4.0))
        except (TypeError, ValueError):
            weight = 4.0

        if mode == "words":
            word_count = self.text_area.document_word_count()

            weight = max(0.1, min(10.0, weight))
            tokens = int(round(word_count * weight))
            lbl.setToolTip(tr(
                "Estimated input tokens for the open silo\n"
                "~{} characters, {} words\n"
                "Weighting is configurable in Settings > Editor > Lines",
                getattr(self, "_current_lang", "EN")
            ).format(raw_chars, word_count))
        else:
            weight = max(1.0, min(20.0, weight))
            tokens = int(round(raw_chars / weight))
            lbl.setToolTip(tr(
                "Estimated input tokens for the open silo\n"
                "{} characters, ~ words\n"
                "Weighting is configurable in Settings > Editor > Lines",
                getattr(self, "_current_lang", "EN")
            ).format(raw_chars))

        lbl.setText(f"~{self._short_count(tokens)} T" if tokens else "")
        lbl.setVisible(True)

    def refresh_timestamp_in_block(self, block):
        """Replace a line's (DD.MM - hh:mm) stamp with right now — used by
        the inline refresh glyph painted after stamped lines."""

        from fastprompter.ui.editor import TS_STAMP_LINE_RE
        m = TS_STAMP_LINE_RE.search(block.text())
        if not m:
            return

        now = datetime.datetime.now()
        h = now.hour
        if 5 <= h < 12: daypart = "Morning"
        elif 12 <= h < 17: daypart = "Day"
        elif 17 <= h < 22: daypart = "Evening"
        else: daypart = "Night"
        text_month = self.data.get("date_text_month", "False") == "True"
        m_fmt = "%d %b" if text_month else "%d.%m"
        ts = now.strftime(f"{m_fmt} - {self._clock_time_fmt()}")

        now_str = f"{daypart} {ts}" if self.data.get("date_daypart", "True") == "True" else ts
        doc = self.text_area.document()
        cur = self.text_area.textCursor()
        keep = cur.position()
        cur.setPosition(block.position() + m.start())
        cur.setPosition(block.position() + m.end(), QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(now_str)
        cur.setPosition(min(keep, doc.characterCount() - 1))
        self.text_area.setTextCursor(cur)
        self.play_tick_sound()
        self.mark_dirty()

    def _live_folder_sync(self):
        """No-op. The per-slot silo_folders map (see _silo_folder_name) owns
        folder identity and follows retitles on its own; a live title-rename
        would fight the map. Kept because ``_on_text_changed`` still calls it
        on every keystroke; the body is deliberately empty."""
        return

    def _schedule_visual_rebuild(self):
        """PERF-001: coalesce text->visual rebuilds during a typing burst.

        Single-shot 300 ms timer matching the visual->text coalescing
        direction; only the newest pending document revision is rebuilt.
        """
        from PyQt6.QtCore import QTimer
        t = getattr(self, "_visual_rebuild_timer", None)
        if t is None or sip.isdeleted(t):
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(300)
            t.timeout.connect(self._flush_visual_rebuild)
            self._visual_rebuild_timer = t
        t.start()

    def _flush_visual_rebuild(self):
        """Rebuild the active visual widget from the CURRENT document text
        only when it differs from what is already rendered (PERF-001).
        Loop prevention via _syncing_from_visual stays intact."""
        if getattr(self, "_syncing_from_visual", False):
            return
        try:
            idx = self.silo_view.currentIndex()
        except Exception:
            return
        if idx not in (1, 2):
            self._rendered_visual_text = None
            return
        try:
            text = self.text_area.toPlainText()
        except Exception:
            return
        if text == getattr(self, "_rendered_visual_text", None):
            return
        if idx == 1:
            self.kanban_widget.load_markdown(text)
        else:
            self.table_widget.load_markdown(text)
        self._rendered_visual_text = text

    def _on_text_changed(self):
        # A save must never persist pre-edit text: _last_cached_text holds the
        # editor snapshot from the LAST cache tick, and a save between a text
        # change and the next tick would otherwise read STALE content (a
        # keystroke's data-loss window). Every edit invalidates the cache so a
        # save falls through to the live editor text; the cache still serves
        # the common no-edit case.
        self._last_cached_text = None
        self._last_text_edit_time = self._bump_action_seq()
        self._update_line_count_label()
        # PERF-005: an edit can change heat/fold ownership -- invalidate the
        # cached view metadata so the next capture rebuilds it once.
        try:
            self.text_area._invalidate_view_metadata()
        except Exception:
            pass
        if not getattr(self, "_syncing_from_visual", False):
            # PERF-001: text->visual rebuilds are DEBOUNCED -- a typing
            # burst parses/rebuilds the board/table once when the timer
            # fires, not on every keystroke. The explicit entry into a
            # visual view flushes synchronously in _apply_silo_type.
            self._schedule_visual_rebuild()

        doc = self.text_area.document()
        count = doc.characterCount()
        if count > 50000:
            interval = 2500
        elif count > 20000:
            interval = 1500
        else:
            interval = 800
        if interval != self._cache_timer_interval:
            self._cache_timer_interval = interval
            self._cache_timer.setInterval(interval)
        self._cache_timer.start()
        # typecheck + app->file sync ride the same debounce pattern: a burst
        # of keystrokes runs each exactly once, after the typing settles.
        # Guarded: these timers are created late in __init__, while text
        # changes can already fire during UI construction.
        if hasattr(self, "_typo_timer"):
            self._typo_timer.start()
        if hasattr(self, "_sync_push_timer"):
            self._sync_push_timer.start()

    def _on_cache_timer(self):
        self.cache_current_text()

    def cache_current_text(self):
        if hasattr(self, "_last_deleted_preset"):
            self._last_deleted_preset = None
        if hasattr(self, "_last_deleted_silo_data"):
            self._last_deleted_silo_data = None
        if getattr(self, "_suspend_cache", False):
            return
        if getattr(self, "_initializing_ui", False):
            return
        if getattr(self, "_cache_in_progress", False):
            return
        self._cache_in_progress = True
        try:
            current_text = self.text_area.toPlainText()
            self._last_cached_text = current_text
            if not self.editing_snippet:
                is_arc = getattr(self, "active_is_archive", False)
                target = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
                if 0 <= self.active_temp_slot < len(target):
                    old_text = target[self.active_temp_slot]
                    target[self.active_temp_slot] = current_text
                    if current_text != old_text:
                        self.mark_dirty("arc" if is_arc else "temp")
                        self.silo_last_edited[self.active_temp_slot] = int(time.time())
                        # PERF-001: reuse the snapshot already materialized
                        # above — never a second whole-document extraction.
                        self._update_active_silo_ui(raw=current_text)
            else:
                cat, idx = self.editing_snippet
                if cat in self.data["categories"] and self.data["categories"][cat][idx]:
                    if self.data["categories"][cat][idx]["text"] != current_text:
                        self.data["categories"][cat][idx]["text"] = current_text
                        self.mark_dirty("snippets")
                    if cat == self.get_current_category():
                        if len(current_text) > 100:
                            t = current_text[:100].replace(chr(10), " ").strip()
                        else:
                            t = current_text.replace(chr(10), " ").strip()
                        display_idx = idx + 1
                        label = (
                            f"{display_idx}: {t[:22]}…"
                            if len(t) > 22
                            else (f"{display_idx}: {t}" if t else str(display_idx))
                        )
                        main_btn = self._snippet_widget_cache.get((cat, idx))
                        if main_btn is None:
                            layout = getattr(self, "snippets_widget", None)
                            if layout and hasattr(layout, "layout"):
                                for i in range(layout.layout.count()):
                                    item = layout.layout.itemAt(i)
                                    if item and item.widget():
                                        widget = item.widget()
                                        main_btn = getattr(widget, "main_btn", None)
                                        if (
                                            main_btn
                                            and getattr(main_btn, "cat", None) == cat
                                            and getattr(main_btn, "global_idx", None) == idx
                                        ):
                                            self._snippet_widget_cache[(cat, idx)] = main_btn
                                            break
                        if main_btn:
                            main_btn.setText(label)
        finally:
            self._cache_in_progress = False

    @staticmethod
    def _set_plain_text_clean(target, text):
        doc = target.document() if hasattr(target, "document") else target
        large = doc.blockCount() > 500 or len(text) > 10000
        if not large:
            doc.setUndoRedoEnabled(False)
        doc.setPlainText(text)
        if not large:
            doc.setUndoRedoEnabled(True)

    def hide_and_save(self):
        # every route out of the window restores the desktop, not just Ctrl+D
        self.exit_zen_solo()
        ok = self.save_data_to_db(force=True)
        if not ok:
            # P1: a known failed autosave must NOT hide the window and silently
            # drop the user's data. Keep it visible/active and report the
            # failure so the dirty state stays retryable.
            from fastprompter.core.logging import logger as _log
            _log.error("hide_and_save: autosave failed; window kept visible so "
                       "the change stays retryable")
            self.show()
            self.raise_()
            self.activateWindow()
            return
        if getattr(self, "is_locked", False):
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.hide()

    def quit_app(self):
        """Request process quit — the SINGLE canonical quit entry point.

        P0-12/P0-6: everything that must land in the FINAL save is settled
        HERE, while the event loop is still alive (watcher quiesce + final
        DB save), and only a clean result calls QApplication.quit(). A
        failed final save refuses the quit: the window stays open instead of
        closing with unsaved state and releasing the ownership lock.
        ``_shutdown_application`` still owns worker retirement, SQLite close
        and the mutex release; closeEvent skips the final save when this
        method already performed it.

        T-810: the tray icon is withdrawn only AFTER the finalize succeeds. On a
        refused quit it stays (or is restored to) visible and the window is
        raised, so a hidden tray-resident window plus a failed save can never
        leave the process alive with both the window and the tray hidden.
        """
        if not self._pre_quit_logical_finalize():
            from fastprompter.core.logging import logger as _log
            _log.error("Quit refused: the final state save failed; the "
                       "window stays open so the data can still be saved")
            try:
                if hasattr(self, "tray_icon"):
                    self.tray_icon.show()
            except Exception:
                pass
            try:
                self.show()
                self.raise_()
                self.activateWindow()
            except Exception:
                pass
            return
        try:
            if hasattr(self, "tray_icon"):
                self.tray_icon.hide()
        except Exception:
            pass
        QApplication.quit()

    def _pre_quit_logical_finalize(self):
        """Settle watcher + DB BEFORE the event loop dies (P0-6).

        The old close path saved after QApplication.quit(): closeEvent runs
        when the event loop is gone, so a watcher send still in the air
        could complete on the worker thread but never apply its queued GUI
        result, and the final save raced it. Here the watcher is quiesced
        first (its queue state is persisted), then the DB save runs exactly
        once. Returns True only when the final state is safely on disk.

        T-809: quiescence is a MANDATORY terminal barrier. A False return or an
        exception from the quiesce aborts the quit BEFORE the final save/quit, so
        an in-flight watcher send can never be lost or applied against a dead
        loop, and the window stays open for a retry.
        """
        if getattr(self, "_logical_finalized", False):
            return True
        try:
            self._cancel_timer_test_jobs()
        except Exception:
            pass
        try:
            if hasattr(self, "_watcher_begin_quiesce"):
                quiesced = self._watcher_begin_quiesce()
            else:
                quiesced = True
        except Exception:
            from fastprompter.core.logging import logger as _log
            _log.exception("watcher quiesce failed during quit; refusing to finalize")
            return False
        if not quiesced:
            from fastprompter.core.logging import logger as _log
            _log.error("Quit refused: the watcher did not quiesce within the "
                       "timeout; the final state save is skipped so no in-flight "
                       "send is lost")
            return False
        ok = bool(self.save_data_to_db(force=True))
        if ok:
            # W2-001: the final save committed — resolve the paused watcher by
            # performing the irreversible disarm now.
            self._watcher_commit_quiesce()
            self._logical_finalized = True
        else:
            # W2-001: the final save failed and the quit is refused; resume the
            # paused watcher (it is still armed) so the window stays fully
            # active rather than silently stranded paused/disarmed.
            self._watcher_rollback_quiesce()
        return ok


_QT_MESSAGE_HANDLER = None


def setup_exception_hook():
    """Make every crash leave a trace.

    sys.excepthook only covers uncaught exceptions on the MAIN thread. A
    failure in a worker thread, or a fatal message from Qt itself, produced
    no crash.log entry and no dialog — the app simply vanished, which is
    exactly the "crashes without any messages" report. All three routes now
    end up in the same log.
    """
    import threading
    import traceback

    old_hook = sys.excepthook
    crash_log = os.path.join(get_data_dir(), "crash.log")

    def _record(text, show_dialog=True):
        try:
            with open(crash_log, "a", encoding="utf-8", errors="replace") as f:
                import datetime as _dt
                stamp = _dt.datetime.now().isoformat(timespec="seconds")
                f.write("--- " + stamp + " ---" + chr(10))
                f.write(text + chr(10))
        except Exception:
            pass
        if show_dialog:
            try:
                ctypes.windll.user32.MessageBoxW(
                    0, "FastPrompter Error:" + chr(10) * 2 + text,
                    "FastPrompter Error", 0x10)
            except Exception:
                pass

    def hook(typ, val, tb):
        _record("".join(traceback.format_exception(typ, val, tb)))
        if old_hook:
            old_hook(typ, val, tb)

    sys.excepthook = hook

    def thread_hook(args):
        # Worker-thread failures were completely silent before this.
        detail = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        name = getattr(args.thread, "name", "?")
        _record("Exception in thread " + str(name) + chr(10) + detail,
                show_dialog=False)

    try:
        threading.excepthook = thread_hook
    except Exception:
        pass

    # Qt's own fatal messages never reach Python's hooks; without this a Qt
    # abort (deleted object, failed assertion) takes the process down mute.
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

        def qt_handler(mode, context, message):
            if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
                where = ""
                if context is not None and context.file:
                    where = f" ({context.file}:{context.line})"
                _record(f"Qt {mode.name}{where}: {message}",
                        show_dialog=(mode == QtMsgType.QtFatalMsg))
            elif mode == QtMsgType.QtWarningMsg:
                try:
                    from fastprompter.core.logging import logger
                    logger.debug("Qt warning: %s", message)
                except Exception:
                    pass

        # keep a module-level reference: qInstallMessageHandler stores the
        # callable on the C++ side, and if Python garbage-collects it the
        # next Qt message dereferences freed memory (access violation).
        global _QT_MESSAGE_HANDLER
        _QT_MESSAGE_HANDLER = qt_handler
        return qInstallMessageHandler(qt_handler)
    except Exception:
        pass
    return None


def main_entry():
    from fastprompter.core.instance_lock import (
        HANDED_OFF,
        PRIMARY,
        InstanceLock,
        bootstrap_ownership,
    )
    from fastprompter.core.ipc_server import request_show

    # Writer ownership is the process's, not the socket's. If a live instance
    # already owns the database mutex we must NOT open a second writer no
    # matter how quiet its event loop is — the best we may do is ask it to
    # show itself, and exit when it answers or when it stays silent.
    lock = InstanceLock()
    role, reason = bootstrap_ownership(lock, request_show)
    if role != PRIMARY:
        lock.release()
        if role == HANDED_OFF:
            return
        # UNRESPONSIVE / FAILED: a live owner exists (or ownership could not
        # be established). Refuse to become a second writer; say why.
        from fastprompter.core.logging import logger as _log
        _log.warning("FastPrompter startup refused: %s", reason)
        _show_startup_diagnostic(reason)
        return

    # Abandoned ownership means the previous owner died mid-run: its database
    # write may have been interrupted. Run a lightweight read-only consistency
    # check before opening the DB for normal use — fail closed, never repair
    # speculatively.
    if lock.abandoned:
        import os

        from fastprompter.core.state import RestoreError, validate_database
        from fastprompter.utils.paths import get_db_path

        # P1-6 Fix: Abandoned lock means the whole app died, so ANY profile's DB
        # could be torn. We must validate all of them before opening any.
        for pid in range(1, 5):
            db_p = get_db_path(pid)
            if not os.path.exists(db_p):
                continue
            try:
                validate_database(db_p)
            except RestoreError as exc:
                lock.release()
                from fastprompter.core.logging import logger as _log
                _log.error(f"previous FastPrompter died mid-run and profile {pid} database "
                           f"does not pass a consistency check: {exc}")
                _show_startup_diagnostic(
                    "A previous FastPrompter instance ended unexpectedly, and "
                    f"a database (Profile {pid}) does not pass a consistency check.\n\n{exc}\n\n"
                    "Your database was not modified. Restore it from the .bak or "
                    "the Documents\\\\.fastprompter snapshot, or run a SQLite "
                    "repair, then start FastPrompter again.")
                return

    setup_exception_hook()

    # portable Markdown snapshots run on a worker thread, off the save path
    try:
        _install_portable_backup_sink()
    except Exception:
        pass

    app = QApplication(sys.argv)
    from fastprompter.utils.fonts import no_aa, resolve_family
    global_font = no_aa(QFont(resolve_family("Verdana"), 10))
    app.setFont(global_font)
    app.setQuitOnLastWindowClosed(False)

    # Create and show window
    window = FastPrompter()
    window.show()
    window.raise_()
    window.activateWindow()

    # Install hotkey filter for global hotkeys
    filter_obj = HotkeyFilter(window)
    app.installNativeEventFilter(filter_obj)

    try:
        sys.exit(app.exec())
    finally:
        _shutdown_application(window, app, lock)


def _shutdown_application(window, app, lock):
    """Retire every app-owned writer before releasing process ownership.

    A timeout is fail-closed: the mutex remains owned until process death, when
    Windows marks it abandoned. That is safer than allowing a new primary to
    start while an old worker can still publish files.
    """
    from fastprompter.core.logging import logger as _log

    clean = True

    # W2-011: every graceful event-loop exit must run the SAME canonical
    # quiesce -> final-save finalization as quit_app(). The old code relied
    # on window.close() as a post-loop "final state capture", but closeEvent
    # only saves when _logical_finalized is False and silently swallows a
    # refused/ignored close -- so a non-quit_app event-loop exit could bypass
    # logical finalization and still retire writers/DB/locks as if clean.
    try:
        finalize = getattr(window, "_pre_quit_logical_finalize", None)
        if finalize is not None:
            finalized = finalize()
        else:
            # no canonical hook: attempt a direct save as a last resort
            try:
                finalized = bool(window.save_data_to_db(force=True))
            except Exception:
                finalized = False
    except Exception:
        _log.exception("application final state capture failed")
        finalized = False
    if not finalized:
        # Refused: dirty state or an in-flight watcher result must NOT be
        # torn down as a clean shutdown. Do not retire workers, do not close
        # the DB, do not release the ownership lock -- the process ends via
        # OS reaping, keeping the mutex fail-closed.
        _log.error(
            "application shutdown refused: logical finalization did not "
            "complete; skipping writer/DB/lock retirement")
        clean = False
        return clean
    # finalize succeeded: perform the window UI close (hide etc.) WITHOUT
    # re-saving (closeEvent sees _logical_finalized True and skips the save).
    try:
        window.close()
    except Exception:
        _log.exception("application window close failed")

    # Retire the window's own workers here and ONLY here, after the final
    # save: the Sync flush captures the newest committed snapshot, and the
    # watcher worker is stopped exactly once per process.
    try:
        watcher_shutdown = getattr(window, "_watcher_shutdown", None)
        if watcher_shutdown is not None and watcher_shutdown() is False:
            clean = False
        try:
            arm_shutdown = getattr(window, "_watcher_arm_shutdown", None)
            if arm_shutdown is not None and arm_shutdown() is False:
                clean = False
        except Exception:
            _log.exception("watcher arm worker shutdown FAILED")
            clean = False
        try:
            typo_shutdown = getattr(window, "typo_worker_shutdown", None)
            if typo_shutdown is not None and typo_shutdown() is False:
                clean = False
        except Exception:
            _log.exception("typo scan worker shutdown FAILED")
            clean = False
    except Exception:
        _log.exception("watcher shutdown FAILED")
        clean = False
    try:
        sync_shutdown = getattr(window, "_sync_shutdown", None)
        if sync_shutdown is not None:
            if sync_shutdown() is False:
                clean = False
    except Exception:
        _log.exception("Sync final flush FAILED")
        clean = False
    try:
        push_shutdown = getattr(window, "_push_shutdown", None)
        if push_shutdown is not None:
            if push_shutdown() is False:
                clean = False
    except Exception:
        _log.exception("Sync push worker shutdown FAILED")
        clean = False
    if getattr(window, "_close_workers_clean", True) is False:
        clean = False

    # Retire IPC and live SQLite on every event-loop exit, not only Quit-menu.
    try:
        ipc = getattr(window, "ipc", None)
        if ipc is not None:
            ipc.close()
    except Exception:
        _log.exception("IPC shutdown failed")
        clean = False
    try:
        conn = getattr(window, "conn", None)
        state = getattr(window, "state", None)
        if conn is None and state is not None:
            conn = getattr(state, "conn", None)
        if conn is not None:
            conn.close()
        window.conn = None
        if state is not None:
            state.conn = None
    except Exception:
        _log.exception("database retirement failed")
        clean = False

    try:
        if getattr(window, "_wait_for_undo_saves", lambda: True)() is False:
            # P1-8: a failed drain is either a writer still alive after the
            # deadline OR a tracked writer that reported a publication
            # failure — the two have different meanings, so they get
            # different messages.
            if getattr(window, "_undo_save_failed", False):
                _log.error("undo PERSISTENCE FAILED: a tracked undo writer "
                           "reported a publication failure")
            else:
                _log.error("undo writer shutdown TIMED_OUT")
            clean = False
    except Exception:
        _log.exception("undo writer shutdown FAILED")
        clean = False

    shutdowns = [
        ("Sync", sync_shutdown_global),
        ("portable backup", backup_worker_shutdown_global),
    ]
    try:
        from fastprompter.ui.file_container import (
            container_worker_shutdown_global,
            export_worker_shutdown_global,
        )
        shutdowns.append(("File Container", container_worker_shutdown_global))
        shutdowns.append(("File Container Export", export_worker_shutdown_global))
    except Exception:
        _log.exception("File Container shutdown import FAILED")
        clean = False

    for name, shutdown in shutdowns:
        try:
            if shutdown() is False:
                _log.error("%s worker shutdown TIMED_OUT", name)
                clean = False
        except Exception:
            _log.exception("%s worker shutdown FAILED", name)
            clean = False

    if clean:
        # C++ destruction is non-mutating and happens while QApplication lives.
        try:
            window.deleteLater()
            app.processEvents()
        except Exception:
            _log.exception("window destruction FAILED")
            clean = False

    if clean:
        lock.release()
    else:
        _log.critical("writer mutex retained: mutating teardown did not stop cleanly")
    return clean


def _show_startup_diagnostic(reason):
    """A frozen instance is a diagnostic, never a license for a second writer."""
    import ctypes
    message = (
        "FastPrompter is already running, but it is not responding.\n\n"
        f"{reason}\n\n"
        "Your data is not at risk: another writer was not started. "
        "If the existing instance is stuck, close it in Task Manager "
        "and start FastPrompter again.")
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "FastPrompter", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    main_entry()
