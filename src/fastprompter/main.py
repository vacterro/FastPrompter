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
    QEventLoop,
    QFileSystemWatcher,
    QObject,
    QSignalBlocker,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
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
    QLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
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
from fastprompter.core.profile_flags import profile_default, profile_flag
from fastprompter.core.sound_manager import SoundManager, _parse_volume_value
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
from fastprompter.ui.qt_lifetime import drain_qt_threadpool, weak_qt_callback
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


#: The canonical settings-tab identity.  Nothing may hardcode an index:
#: ``settings_tab_index("Problip")`` is how the tray and every other caller
#: finds a page (T-1238-C4.2).
SETTINGS_TAB_TITLES = ("Window", "Editor", "Clock", "Data", "Problip")


def settings_tab_index(english_title: str) -> int:
    """Index of a settings tab by its stable English title, or -1."""
    try:
        return SETTINGS_TAB_TITLES.index(english_title)
    except ValueError:
        return -1


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


class _SettingsPage(QWidget):
    """Tab page that never inflates the tab widget's minimum.

    QTabWidget's minimumSizeHint is the tab bar plus the TALLEST page, so a
    page that reports the height its flow needs at the flow's minimum width
    (all groups stacked) forces the whole panel tall enough to show that
    worst case on every tab. The visible page is sized on demand by
    ``_fit_settings_tabs`` instead, so the page's job is only to not stand
    in the way: report no minimum and let the fitter decide the height.
    """
    def minimumSizeHint(self):
        return QSize(0, 0)

    def sizeHint(self):
        return QSize(0, 0)


class _SettingsGearButton(QPushButton):
    """Settings ⚙ button."""

    def __init__(self, parent=None):
        super().__init__("⚙", parent)



def _snapshot_text_size(st):
    """Chars of silo text a data snapshot holds, for the undo/redo size cap."""
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


def _snapshot_cached_text_size(st):
    """Return a finalized snapshot's cached text size, measuring legacy data once."""
    size = st.get("_text_size")
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    return _snapshot_text_size(st)


def _trim_snapshot_stack(stack, max_entries=50, max_chars=20_000_000):
    """Enforce undo/redo caps with one size total and constant-time eviction."""
    max_entries = max(1, max_entries)
    while len(stack) > max_entries:
        stack.pop(0)

    if len(stack) <= 1:
        return

    total_chars = sum(_snapshot_cached_text_size(snapshot) for snapshot in stack)
    while len(stack) > 1 and total_chars > max_chars:
        oldest = stack.pop(0)
        total_chars -= _snapshot_cached_text_size(oldest)


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


# FREEZE-2026-08-30: deadlock watchdog.  A background thread watches the
# heartbeat that a GUI-thread QTimer keeps ticking.  If the heartbeat goes
# silent for >1500 ms, the GUI thread is presumed wedged ("Not Responding").
# The watchdog logs the freeze length; once the GUI thread gets its next
# turn it dumps its own Python stack so the exact blocking call is on record
# for the next session.  Without this, a hard freeze leaves no trace.
_GUI_LAST_ANSWER = [0.0]
_GUI_WATCHDOG_STARTED = [False]


def _start_gui_watchdog(window):
    """Install a heartbeat + watchdog that detects a frozen GUI thread."""
    if _GUI_WATCHDOG_STARTED[0]:
        return
    _GUI_WATCHDOG_STARTED[0] = True
    _GUI_LAST_ANSWER[0] = time.monotonic()
    import threading
    gui_thread_ident = threading.get_ident()
    try:
        from fastprompter.core.logging import logger as _log
    except Exception:
        _log = None

    from PyQt6.QtCore import QTimer

    blocked_since = [0.0]
    stall_captured = [False]

    def _heartbeat():
        now = time.monotonic()
        prev = _GUI_LAST_ANSWER[0]
        _GUI_LAST_ANSWER[0] = now
        if blocked_since[0]:
            stalled = now - blocked_since[0]
            if _log is not None:
                _log.warning("GUI recovered after %.2fs stall", stalled)
            blocked_since[0] = 0.0
            stall_captured[0] = False
        elif _log is not None and (now - prev) > 1.5:
            _log.warning(
                "GUI heartbeat gap %.2fs (event loop stalled?)",
                now - prev)

    _heartbeat_timer = QTimer(window)
    _heartbeat_timer.setInterval(500)
    _heartbeat_timer.timeout.connect(_heartbeat)
    _heartbeat_timer.start()
    window._watchdog_heartbeat_timer = _heartbeat_timer

    def _watcher():
        while True:
            time.sleep(0.5)
            try:
                gap = time.monotonic() - _GUI_LAST_ANSWER[0]
                if gap > 1.5 and not stall_captured[0]:
                    blocked_since[0] = _GUI_LAST_ANSWER[0]
                    stall_captured[0] = True
                    try:
                        import sys
                        import traceback
                        frame = sys._current_frames().get(gui_thread_ident)
                        tb = "".join(traceback.format_stack(frame, limit=30)) if frame is not None else "<no frame>"
                        if _log is not None:
                            _log.error("GUI STALL %.2fs\n%s", gap, tb)
                    except Exception:
                        pass
            except Exception:
                break

    t = threading.Thread(target=_watcher, daemon=True,
                          name="fastprompter-gui-watchdog")
    t.start()


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
_SYNC_EPOCH = 0
_SYNC_LATEST_REQUESTED = {}
# PERF-006: folder-result caches must stay bounded over long tray-resident
# sessions. These caps apply to the per-process dicts.
_FILE_COUNT_CACHE_CAP = 4096
_TOOLTIP_CACHE_CAP = 2048


def _sync_register_snapshot(snapshot):
    """Give a snapshot physical publication ownership for its destinations."""
    global _SYNC_WRITE_SEQ
    with _SYNC_REQUEST_LOCK:
        issued_epoch = snapshot.get("_write_epoch")
        if snapshot.get("_write_seq") is None:
            snapshot["_write_epoch"] = _SYNC_EPOCH
            _SYNC_WRITE_SEQ += 1
            snapshot["_write_seq"] = _SYNC_WRITE_SEQ
        elif issued_epoch != _SYNC_EPOCH:
            # Revocation is permanent for this captured intent. Re-registering
            # it after restore must not mint fresh ownership from stale RAM.
            return None
        seq = snapshot["_write_seq"]
        for dest in snapshot.get("files", ()):
            key = os.path.normcase(os.path.abspath(dest))
            _SYNC_LATEST_REQUESTED[key] = max(
                seq, _SYNC_LATEST_REQUESTED.get(key, 0)
            )
    return snapshot


def _sync_revoke_all():
    """CORE-004: permanently revoke every pre-restore one-way-mirror snapshot.

    Called the instant a DB restore commits. Clears the destination->seq
    registry and bumps the global sequence, so ``_sync_snapshot_is_latest``
    and the final-replace recheck both fail for any already-running pre-restore
    writer — it can no longer publish stale RAM over the restored DB."""
    global _SYNC_WRITE_SEQ, _SYNC_EPOCH
    with _SYNC_REQUEST_LOCK:
        _SYNC_EPOCH += 1
        _SYNC_WRITE_SEQ += 1
        _SYNC_LATEST_REQUESTED.clear()


def _sync_snapshot_is_latest(snapshot, dest):
    seq = snapshot.get("_write_seq")
    key = os.path.normcase(os.path.abspath(dest))
    with _SYNC_REQUEST_LOCK:
        return (snapshot.get("_write_epoch") == _SYNC_EPOCH
                and seq is not None
                and _SYNC_LATEST_REQUESTED.get(key) == seq)


def _sync_mechanical_write(snapshot, lock_timeout_s=None):
    """Mechanically writes a sync snapshot, protected by a process-level lock.
    Returns (written: list, errors: list)."""
    if _sync_register_snapshot(snapshot) is None:
        return [], []
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
                from fastprompter.utils.path_safety import unique_temp_path
                tmp = unique_temp_path(dest, "sync")
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


def _sync_stat_identity(path):
    """W2-001: cheap observation identity for one filesystem read.

    ``(size, mtime_ns)`` travels with every worker-captured file fact so the
    GUI commit can re-stat (one syscall, never a read) and reject an
    observation the filesystem has already superseded. ``None`` means the
    path was verified absent at capture time.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _collect_sync_pull(request):
    """Read one watcher reconciliation snapshot without touching Qt state.

    W2-001: the result is an OBSERVATION, not authorization. Every row
    carries the observation identity captured *before* its read, so text
    taken from generation A can never be committed once the disk holds
    generation B (see ``_apply_external_sync_collected``). Rows:

        mapped: (slot_key, rel, path, status, read, identity)
        new:    (rel, path, read, identity)
        links:  (slot_key, path, status, read, identity)
    """
    from fastprompter.core import project_sync as ps

    changed = set(request["changed"])
    dir_changed = bool(request["dir_changed"])
    file_only = bool(changed) and not dir_changed
    max_bytes = request["max_bytes"]
    result = {"mapped": [], "new": [], "links": []}

    root = request["root"]
    mapping = dict(request["mapping"])
    if root and os.path.isdir(root):
        for slot_key, rel in mapping.items():
            path = ps.resolve_relative_path(root, rel)
            if path is None:
                result["mapped"].append(
                    (slot_key, rel, None, "invalid", None, None))
                continue
            if file_only and os.path.normcase(path) not in changed:
                continue
            # Identity BEFORE the read: if the file moves on mid-read the
            # captured identity is the older generation, so the commit-side
            # re-stat mismatches and the observation is rejected.
            ident = _sync_stat_identity(path)
            if ident is None:
                result["mapped"].append(
                    (slot_key, rel, path, "missing", None, None))
                continue
            result["mapped"].append(
                (slot_key, rel, path, "read",
                 ps.read_text_file(path, max_bytes), ident))

        if dir_changed or not changed:
            files = ps.scan_folder(
                root, request["include"], request["exclude"],
                recursive=request["recursive"], max_bytes=max_bytes,
                limit=100)
            mapped = set(mapping.values())
            for rel in files:
                if rel in mapped:
                    continue
                path = ps.resolve_relative_path(root, rel)
                if path is not None:
                    ident = _sync_stat_identity(path)
                    result["new"].append(
                        (rel, path, ps.read_text_file(path, max_bytes), ident))

    for slot_key, path in request["links"]:
        if not isinstance(path, str) or not path:
            continue
        if file_only and os.path.normcase(path) not in changed:
            continue
        ident = _sync_stat_identity(path)
        if ident is None:
            result["links"].append((slot_key, path, "missing", None, None))
            continue
        result["links"].append(
            (slot_key, path, "read", ps.read_text_file(path, max_bytes), ident))
    return result


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
                        # CORE-004: the restore-revocation barrier is rechecked
                        # AT the mutation gate, not only at batch start — a
                        # restore that commits while this job was reading must
                        # stop the write that follows.
                        if getattr(self, "_suppress", False):
                            results.append(
                                (key, path, text, "stale", None))
                            continue
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
                    # CORE-004: restore-revocation rechecked at the final
                    # mutation gate (see recreate branch above).
                    if getattr(self, "_suppress", False):
                        results.append((key, path, text, "stale", None))
                        continue
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
        # a dropped in-flight job must not leave the portable layer's
        # coalescing markers behind: they are retired only by a worker
        # completion that will now never arrive, and a surviving marker
        # silently refuses every future backup for that profile
        try:
            from fastprompter.utils import portable_backup as _pb
            for pid in set(_BACKUP_INFLIGHT) | set(_BACKUP_NEWEST_GEN):
                _pb.abandon_inflight(pid)
        except Exception:
            from fastprompter.core.logging import logger as _log
            _log.exception("portable backup intent cleanup failed")
        _BACKUP_WORKER = None
        _BACKUP_THREAD = None
        _BACKUP_COMPLETION_RELAY = None
        _BACKUP_PENDING = {}
        _BACKUP_INFLIGHT = {}
        _BACKUP_NEWEST_GEN = {}
        if worker is not None or thread is not None:
            _RETIRED_WORKERS.append((worker, thread))
    return success


# T-1269C append — keys the EDITOR owns, and who (if anyone) may really have
# them. ``VaultTextEdit.keyPressEvent`` implements Ctrl+A/C/V/X itself, and
# Ctrl+Z/Ctrl+Y are dispatched from the editor to the window's smart
# undo/redo. QShortcut is consulted BEFORE the focused widget sees a key, so a
# profile that maps a configurable command onto one of these silently replaces
# editing with that command: on a machine where the operator had remapped, say,
# Ctrl+V, the editor would never run its paste branch, its paste cue would
# never play, and the ``clipboard.text()`` route through NEW would keep working
# — exactly the intermittent "Ctrl+V does nothing" shape. It must not be
# reachable by accident.
#
# Value is (editor action, the one configurable hotkey allowed to own the
# sequence). ``None`` means nobody may: the editor is the only implementation of
# that binding, so a collision is refused and the editor keeps the key.
# Ctrl+Z names ``hk_undo`` because that IS the shipped owner — the editor calls
# the same window handler, so the two are not ambiguous. Any OTHER command
# claiming Ctrl+Z takes undo away from the whole application and is refused.
EDITOR_RESERVED_SEQUENCES = {
    "Ctrl+A": ("select all", None),
    "Ctrl+C": ("copy", None),
    "Ctrl+V": ("paste", None),
    "Ctrl+X": ("cut", None),
    "Ctrl+Z": ("undo", "hk_undo"),
    "Ctrl+Y": ("redo", None),
}


def _portable_sequence(seq):
    """One canonical spelling for a key sequence, for conflict comparison."""
    try:
        return QKeySequence(seq).toString(
            QKeySequence.SequenceFormat.PortableText)
    except Exception:
        return ""


def editor_shortcut_conflict(key_name, seq):
    """The editor action this hotkey would steal, or None if the key is free.

    Pure decision, so it can be pinned without a window or a QShortcut (see
    ``tests/test_editor_paste_live_t1269.py``).
    """
    reserved = EDITOR_RESERVED_SEQUENCES.get(_portable_sequence(seq))
    if reserved is None:
        return None
    action, allowed_owner = reserved
    if allowed_owner == key_name:
        return None
    return action


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
        import time
        self._t_startup_start = time.perf_counter()
        self._startup_timings = {}
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
        _t_state_0 = time.perf_counter()
        self.state = FastPrompterState()
        self._startup_timings["1_FastPrompterState_load"] = (time.perf_counter() - _t_state_0) * 1000.0
        # PERF-001: the GUI build dispatches the throttled .bak refresh to the
        # background worker — a full-database copy+validation must never run
        # on the save critical path (it held State._lock and hitched the UI).
        self.state.background_backups = True
        self.data = self.state.data
        self._t_pre_0 = time.perf_counter()
        # W2-006: reconcile any crash-consistent retirement journal left
        # by a process death between a folder rename and its in-memory log
        # append. Idempotent; DEFERRED until after the per-category
        # migration below so _retirement_owner_is_live sees canonicalized
        # silo_folders_all rather than stale flat data (W2-001).
        from fastprompter.ui.snippet_ops_mixin import _reconcile_retirement_journal
        self._reconciliation_pending = True
        self._journal_reconcile_fn = _reconcile_retirement_journal
        from fastprompter.core.timers import load_timers
        self.timers = load_timers(self.data.get("timers"))
        self.prompt_queues = {}
        # on_tab_changed rebinds this to the active category as soon as the
        # UI is up; this is only the pre-UI starting point
        from fastprompter.core.pomodoro import ProductivityTimer
        self.productivity_timer = ProductivityTimer.from_dict(
            self.data.get("productivity_timer"))
        self._pomo_last_tick = None
        # cadence anchor for the repeated-alarm replay (CORE-001)
        self._pomo_alarm_replay_at = None
        self._POMO_ALARM_REPEAT_SECONDS = 60
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
        # T-1330: the image-viewer router reads image_viewer_mode off this
        # window's data. Nothing ever bound it, so viewer_preference() always
        # answered ("internal", "") and the Settings toggle was decoration —
        # images opened in the built-in preview whatever the profile said.
        # The weakref keeps no ownership cycle; None (tests) still means
        # internal, so nothing hands a file to the OS without an owner.
        try:
            from fastprompter.ui import image_viewer as _image_viewer

            _image_viewer.bind_preferences(self)
        except Exception:
            from fastprompter.core.logging import logger as _logger

            _logger.debug("image viewer preference bind failed", exc_info=True)
        # T-1238-C1: ONE Problip runtime for the whole application lifetime.
        # It is created here, right after the audio authority exists, and it
        # is never recreated by a profile switch, a Settings open or a preset.
        self.problip_controller = None
        try:
            from fastprompter.ui.problip_controller import ProblipController

            self.problip_controller = ProblipController(self, self.sound_manager)
            self.problip_controller.start_if_remembered()
        except Exception:
            from fastprompter.core.logging import logger as _logger

            _logger.debug("Problip controller unavailable", exc_info=True)
        # T-1238-C3.7/C3.12: the voice countdown and the ambience engine each
        # get ONE application-owned runtime adapter.  Neither polls anything:
        # voice observes deadlines this window already knows, ambience runs
        # one evaluation timer, one fade driver and one weather refresh.
        self.voice_controller = None
        self.ambience_controller = None
        try:
            from fastprompter.ui.voice_controller import VoiceController

            self.voice_controller = VoiceController(self, self.sound_manager)
        except Exception:
            from fastprompter.core.logging import logger as _logger

            _logger.debug("Voice controller unavailable", exc_info=True)
        try:
            from fastprompter.ui.ambience_controller import AmbienceController

            self.ambience_controller = AmbienceController(
                self, self.sound_manager)
            # T-1265 C2: ambience used to die at every restart -- the
            # controller stopped the engine in its constructor and nothing
            # ever restored it, so "on" meant "on until you close the app".
            # The DESIRED state lives in audio.db (application-global, not
            # per-profile) and is restored exactly once, here, now that the
            # SoundManager and the hub are both real.
            self.ambience_controller.start_if_remembered()
        except Exception:
            from fastprompter.core.logging import logger as _logger

            _logger.debug("Ambience controller unavailable", exc_info=True)
        # One owner for the sound-event mapping. This was written out here as
        # well, which is how the two copies drift: the module function also
        # heals overrides that point at a file the library no longer has.
        from fastprompter.core.sound_manager import migrate_sound_settings
        migrate_sound_settings(self.data, self.sound_manager._sounds_dir)

        # Subtle wheel feedback in long panels. Filter is a no-op while UI
        # sounds are off (the sound manager respects sound_ui on its own).
        # Filters are installed at the end of __init__ so startup widget creation
        # and theming are not slowed down by Python event processing.
        from fastprompter.ui.scroll_sound import ScrollSoundFilter
        self._scroll_sound_filter = ScrollSoundFilter(self.sound_manager, main_win=self)

        # An unfocused combo/spin under the pointer must not consume the wheel:
        # scrolling the Interval Notifications tab used to step its sound combo
        # (firing the live preview — the "random sounds" report), its interval
        # and its volume, all without a click. Installed at the end of __init__
        # AFTER the scroll-sound filter so it receives events first (Qt notifies
        # filters newest-first).
        from fastprompter.ui.wheel_guard import WheelGuard
        self._wheel_guard = WheelGuard()

        # A default click on every button press that produced no sound of its
        # own (T-1225). Deferred to the release's tail: if the clicked handler
        # already played an action sound it is dropped, otherwise the button
        # clicks. Installed with the other app-level filters at the end of
        # __init__ so startup widget creation never crosses this hook.
        from fastprompter.ui.button_sound import ButtonClickSoundFilter
        self._button_sound_filter = ButtonClickSoundFilter(self.sound_manager)

        # T-1245: generic dialog/panel appearance cues. App-level Show-event
        # reporting, so every QDialog presentation reaches the semantic
        # dialog_show event without per-dialog wiring; the Audio Hub carries
        # its own audio_hub_show tag and is excluded (no double-fire).
        from fastprompter.ui.appearance_sounds import AppearanceShowFilter
        self._appearance_sound_filter = AppearanceShowFilter(
            self.sound_manager, main_win=self)

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
        # temp_presets_all); migrate the old flat keys into the persisted
        # ACTIVE tab. W2-001: the boot category must use the SAME
        # visible-category/last_tab_idx semantics FastPrompterState.init_db
        # uses — a hardcoded cats_order[0] guess migrates legacy flat
        # metadata (folders/pins/children/project paths) onto the wrong
        # project and it then vanishes when the real project is bound.
        hidden = set(self.data.get("hidden_categories", []))
        _visible = [c for c in (self.data.get("cats_order") or []) if c not in hidden]
        if not _visible:
            _visible = self.data.get("cats_order") or ["Code"]
        first_cat = _visible[min(int(self.data.get("last_tab_idx", 0)),
                                 len(_visible) - 1)] if _visible else "Code"
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
        # Ctrl+click multi-selection, same shape and same aliasing rule as the
        # ticks above. Without this bind the flat key is a FREE list at startup,
        # so every latch written before the first project switch lands nowhere
        # and the next bind_active_category replaces it with an empty one.
        sall = self.data.get("silo_selected_all")
        if not isinstance(sall, dict):
            sall = {}
        if (not sall and isinstance(self.data.get("silo_selected"), list)
                and self.data["silo_selected"]):
            sall[first_cat] = list(self.data["silo_selected"])
        self.data["silo_selected_all"] = sall
        self.data["silo_selected"] = sall.setdefault(first_cat, [])
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
        # The gap NAMES ride the same aliasing rule: the loader decodes the
        # flat row and the _all row as two separate dicts, so without this
        # bind the flat alias and silo_gap_names_all[cat] SPLIT at startup —
        # a post-restart deletion then remapped the alias while the _all
        # store kept the stale anchors (T-1222 companion, red regression in
        # test_explicit_silo_deletion_still_shrinks_and_prunes_across_restart).
        gnames_all = self.data.get("silo_gap_names_all")
        if not isinstance(gnames_all, dict):
            gnames_all = {}
        self.data["silo_gap_names_all"] = gnames_all
        self.data["silo_gap_names"] = gnames_all.setdefault(first_cat, {})
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

        # W2-001: the per-category migration has now canonicalized every
        # legacy flat owner into the _all stores, so retirement recovery can
        # classify durable owners correctly.
        if getattr(self, "_reconciliation_pending", False):
            try:
                fn = getattr(self, "_journal_reconcile_fn", None)
                if fn is not None:
                    fn(self._files_root(), self.data,
                       owner_is_live=self._retirement_owner_is_live)
            except Exception:
                from fastprompter.core.logging import logger
                logger.warning("retirement journal reconciliation skipped",
                               exc_info=True)
            self._reconciliation_pending = False
        # W2-002: reconcile any interrupted nested-silo file merge left by a
        # process death between physical moves and the persisted undo record.
        try:
            from fastprompter.ui.snippet_ops_mixin import _reconcile_merge_journal
            _reconcile_merge_journal(self._files_root(), self.data)
        except Exception:
            from fastprompter.core.logging import logger
            logger.warning("merge journal reconciliation skipped",
                           exc_info=True)
        # CORE-004b: reconcile any interrupted cross-project folder transfer the
        # same way — the journal is the durable truth about how far it got.
        try:
            self._reconcile_transfer_journal()
        except Exception:
            from fastprompter.core.logging import logger
            logger.warning("transfer journal reconciliation skipped",
                           exc_info=True)

        import time
        self._startup_timings["2_pre_init_migrations"] = (time.perf_counter() - self._t_pre_0) * 1000.0

        self._current_lang = get_language(self.data)
        _t_ui_0 = time.perf_counter()
        self.init_ui()
        self._startup_timings["3_init_ui_total"] = (time.perf_counter() - _t_ui_0) * 1000.0
        self.init_tray()
        self.setup_global_shortcuts()
        self._apply_tooltips()
        # Delay global hotkey binding until after UI initialization to prevent race conditions causing silent crashes (Debater Constraint)
        QTimer.singleShot(100, weak_qt_callback(
            self, lambda window: window.register_all_hotkeys()))

        self._switch_to_slot(self.active_temp_slot, initial=True)
        # PERF: apply theme early so the window is visually ready before
        # place_window/show.  The heavy _apply_profile_runtime_state (widget
        # sync, hotkeys, watcher) is deferred to the next event-loop tick so
        # the user sees the window ~1.4 s sooner.  The initializing flags
        # stay True until the deferred apply finishes so that handlers
        # triggered during profile state application do not fire premature
        # side-effects (save, sync, etc.).
        _t_thm_0 = time.perf_counter()
        self.apply_theme()
        self._startup_timings["8_apply_theme"] = (time.perf_counter() - _t_thm_0) * 1000.0
        self.place_window()
        if getattr(self, 'is_locked', False):
            self._locked_geometry = self.geometry()
        # A static singleShot owns its Python callback until the event fires.
        # Capturing ``self`` here kept a close()+deleteLater() window alive;
        # some later, unrelated processEvents() then ran theme work against a
        # half-torn-down widget tree and could corrupt Qt's native heap.
        def _deferred_profile_apply(window):
            try:
                _t_def_0 = time.perf_counter()
                window._apply_profile_runtime_state(initial=True)
                window._startup_timings["10_deferred_profile_runtime"] = (
                    time.perf_counter() - _t_def_0) * 1000.0
                window._startup_timings["9_first_visible_frame"] = (
                    time.perf_counter() - window._t_startup_start) * 1000.0
                window._initializing_ui = False
                window._suspend_temp_sync = False
            except Exception:
                from fastprompter.core.logging import logger
                logger.exception("deferred profile apply failed")
        QTimer.singleShot(0, weak_qt_callback(self, _deferred_profile_apply))
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
        self._sync_apply_timer.timeout.connect(self._request_external_sync)
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
        # Watcher-triggered disk scans/reads run through one-inflight plus one
        # latest-pending QRunnable. Only immutable results return to the GUI.
        self._sync_pull_inflight = False
        self._sync_pull_pending = None
        self._sync_pull_request_gen = 0
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
        self._load_missed_ids()

        # Install global event filters at the end of __init__ so that the
        # ~45,000 internal Qt child/layout/polish events during init_ui and
        # apply_theme do not cross into Python eventFilter hooks.
        # Installed in order: _scroll_sound_filter then _wheel_guard, so
        # _wheel_guard is newest and gets notified first.
        # T-1296: the filters are OWNED by this window -- parenting them ties
        # their C++ lifetime to the window's, so a destroyed window (app
        # shutdown, or a test retiring it) destroys its filters and Qt
        # removes them from the application's filter chain by itself. A
        # window must never leave an app-level filter behind that still
        # consults its dead SoundManager on every later Show/Click: that
        # stale wrapper raised on each event and, under pytest's log
        # capture, the retained exc_info frames leaked every later shown
        # widget (test_timer_dialog_wave residue, test_timer_fire
        # starvation).
        app_inst = QApplication.instance()
        if app_inst is not None:
            for flt in (self._scroll_sound_filter, self._wheel_guard,
                        self._button_sound_filter,
                        self._appearance_sound_filter):
                flt.setParent(self)
                app_inst.installEventFilter(flt)

    def _clock_time_fmt(self, show_secs=False):
        """strftime format for hh:mm[:ss], honoring the 12h/AM-PM setting."""
        ampm = self.data.get("date_ampm", "False") == "True"
        if ampm:
            return "%I:%M:%S %p" if show_secs else "%I:%M %p"
        return "%H:%M:%S" if show_secs else "%H:%M"

    def _update_date_label(self):
        # PERF-004: the date/top-bar label is pure VISUAL work. A tray-hidden
        # process must not repaint main-window widgets once a second while
        # invisible — the scheduler (_check_timers) stays alive on its own
        # timer, and showEvent performs one immediate catch-up so the first
        # visible frame is current. User-initiated settings toggles call this
        # while the window is visible, so the gate never starves them.
        if not self.isVisible():
            return
        if hasattr(self, "analog_clock"):
            self.analog_clock.sync()
        if hasattr(self, "limit_gauges"):
            self.limit_gauges.sync()
        if hasattr(self, "_update_limit_timer_label"):
            self._update_limit_timer_label()
        if hasattr(self, "_update_limit_status"):
            self._update_limit_status()
        show_date = self.data.get("show_date_rect", "True") == "True"
        if not show_date:
            self._set_topbar_semantic("lbl_date", False)
            return

        self._set_topbar_semantic("lbl_date", True, refresh=False)
        now = datetime.datetime.now()
        # The full clock (seconds + day word) must fit even at the Ctrl+Q
        # quarter-FullHD snap — dense mode wins the pixels from buttons and
        # paddings, never by silently dropping what the user enabled.
        show_secs = self.data.get("date_seconds", "True") == "True"
        show_word = profile_flag(self.data, "date_daypart")
        text_month = self.data.get("date_text_month", "False") == "True"
        ampm = self.data.get("date_ampm", "False") == "True"
        if self._topbar_detail_mode("lbl_date") == "compact":
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
            use_emoji = profile_flag(self.data, "date_emoji")
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
        self._apply_topbar_visibility()

    def _apply_limit_hint_style(self, label, padding="0 4px"):
        """Small caption colour for AI-limit text — one settable role.

        Every grey explanatory line in the limit UI (header status, dialog
        captions) reads its colour from ``limit_colors["hint"]``, so retinting
        them is one setting instead of four hardcoded hex values.
        """
        if label is None:
            return
        from fastprompter.ui.limit_colors import resolve_hex
        pad = f"padding: {padding}; " if padding else ""
        label.setStyleSheet(
            f"{pad}color: {resolve_hex(self, 'hint')}; font-size: 10px;")

    def _update_limit_status(self):
        """Status text shown in Clock settings — account count or error.

        Update source: service callback (any sweep completes) and the per-
        second date timer (one line of text, near-free).
        """
        lbl = getattr(self, "lbl_limit_status", None)
        if lbl is None:
            return
        svc = getattr(self, "limit_service", None)
        if svc is None:
            lbl.setVisible(False)
            return
        snap = svc.state_copy
        from fastprompter.ui.limit_account_selector import hidden_account_keys
        hidden = hidden_account_keys(self.data)
        accounts = [a for a in snap.accounts if a.key not in hidden]
        n = len(accounts)
        visible_keys = {a.key for a in accounts}
        snapshots = {key: value for key, value in snap.snapshots.items()
                     if key in visible_keys}
        ok = sum(1 for s in snapshots.values()
                 if getattr(s, "status", None) == "OK")
        stale = sum(1 for s in snapshots.values()
                    if getattr(s, "status", None) == "STALE")
        err = sum(1 for s in snapshots.values()
                  if getattr(s, "status", None) in ("ERROR", "AUTH_REQUIRED"))
        # A provider designed to stay silent until it has a fact (Antigravity
        # only learns quota from a refusal) is idle, not broken — counting it
        # as "unavailable" would advertise a defect with nothing to fix.
        from fastprompter.core.usage_limits.model import EXPECTED_QUIET_CODES
        quiet = sum(1 for s in snapshots.values()
                    if getattr(s, "status", None) == "UNAVAILABLE"
                    and getattr(s, "error_code", "") in EXPECTED_QUIET_CODES)
        unavailable = sum(1 for s in snapshots.values()
                          if getattr(s, "status", None) == "UNAVAILABLE") - quiet
        if snap.status == "DISCOVERING":
            lbl.setText("scanning accounts…")
        elif snap.accounts and n == 0:
            lbl.setText(f"0/{len(snap.accounts)} shown — choose accounts below")
        elif n == 0:
            lbl.setText("no accounts found (~/.codex, ~/.codex-*, ~/.claude, "
                        "~/.gemini/antigravity)")
        elif not snapshots:
            lbl.setText(f"discovered {n} account(s) — probing…")
        elif err or unavailable:
            details = []
            if err:
                details.append(f"{err} error(s)")
            if unavailable:
                details.append(f"{unavailable} unavailable")
            if stale:
                details.append(f"{stale} stale")
            lbl.setText(f"{ok + stale}/{n} readable · {' · '.join(details)} · "
                        "hover gauges for details")
        elif stale:
            lbl.setText(f"{ok + stale}/{n} readable · {stale} stale")
        elif quiet:
            lbl.setText(f"{ok}/{n} accounts OK · {quiet} idle "
                        "(reports only when the provider refuses work)")
        else:
            lbl.setText(f"{ok}/{n} accounts OK")
        # This label lives in the LAZY settings panel ("Passed events" group in
        # settings_builder), so until that panel is built nothing owns it — and
        # setVisible(True) on a parentless widget does not mean "show this
        # caption", it means "open a window". That is what it did: a thin strip
        # reading "4/4 accounts OK" floating beside the app, re-shown every
        # second by the date timer. Showing it only means anything once
        # something has adopted it.
        lbl.setVisible(lbl.parentWidget() is not None)
        selector = getattr(self, "limit_accounts_selector", None)
        if selector is not None:
            selector.sync()

    def _update_limit_timer_label(self):
        """Update content and publish semantic availability of AI reset."""
        lbl = getattr(self, "lbl_limit_timer", None)
        if lbl is None or sip.isdeleted(lbl):
            return
        svc = getattr(self, "limit_service", None)
        gauges = getattr(self, "limit_gauges", None)
        if (svc is None or gauges is None
                or self.data.get("limit_gauges", "False") != "True"):
            lbl.setToolTip("")
            self._set_topbar_semantic("lbl_limit_timer", False)
            return
        snap = svc.state_copy
        from fastprompter.core.usage_limits.model import reset_candidates
        from fastprompter.ui.limit_account_selector import hidden_account_keys
        from fastprompter.ui.limit_colors import reset_color
        hidden = set(hidden_account_keys(self.data))
        # Availability filters only affect quota bars. Exhausted accounts
        # still own the reset the user is waiting for.
        candidates = reset_candidates(snap.snapshots, hidden)
        provider, soonest = (
            (candidates[0].provider_id, candidates[0].resets_at_epoch)
            if candidates else (None, None))
        if soonest is None:
            lbl.setToolTip(tr("No upcoming AI limit resets", self._current_lang))
            self._reset_queue_html = ""
            self._refresh_reset_hover_card()
            self._set_topbar_semantic("lbl_limit_timer", False)
            return
        import datetime
        now = datetime.datetime.now().timestamp()
        remaining = soonest - now
        if remaining <= 0:
            text = "now"
        else:
            from fastprompter.core.duration import format_remaining
            text = format_remaining(
                remaining, short=bool(getattr(self, "_header_dense", False)),
                minutes=True)
        lbl.setText(f"↻ {text}")
        color = reset_color(self, provider)
        if color:
            lbl.setStyleSheet(
                f"padding: 0 4px; font-weight: bold; color: {color};")
        else:
            lbl.setStyleSheet("padding: 0 4px; font-weight: bold;")

        # Hover opens the COMPLETE chronological reset queue as structured
        # columns in the existing LimitHoverCard (T-1279) — same candidates
        # the ↻ countdown winner came from, never a second selection
        # algorithm. Column widths are content-measured, so the Left column
        # is right-aligned and stable and a long Pool truncates before it.
        from fastprompter.ui.limit_account_selector import (
            account_display_name as _acct_name,
        )
        from fastprompter.ui.reset_queue_card import render_table, reset_rows
        rows = reset_rows(
            candidates, now,
            name_for=lambda acct: _acct_name(acct, self.data),
            pool_colors={c.provider_id: (reset_color(self, c.provider_id) or "")
                         for c in candidates})
        # Canonical column labels go through tr(); the renderer stays a pure
        # content builder (no UI language state import), and "#" is
        # language-independent.
        column_labels = {
            name: tr(name, self._current_lang)
            for name in ("Account", "Pool", "Window", "Left")
        }
        # T-1298: decide the composition from the REAL width the card may
        # occupy (font metrics for the text + the screen it will open on),
        # never from character counts alone. When the wide table cannot fit,
        # the renderer stacks Account / Pool instead of letting the popup clip
        # them.
        available_width = None
        try:
            from fastprompter.ui.limit_hover_card import MAX_WIDTH as _CARD_MAX
            metrics = lbl.fontMetrics()
            available_width = _CARD_MAX
            screen = lbl.screen()
            if screen is not None:
                available_width = min(
                    _CARD_MAX, screen.availableGeometry().width() - 24)
        except Exception:
            available_width = None
        self._reset_queue_html = render_table(
            rows, header=tr("Next resets", self._current_lang),
            labels=column_labels,
            available_width=available_width,
            measure=(lambda text: metrics.horizontalAdvance(text))
            if available_width is not None else None)
        # The native tooltip stays a short summary: the full queue lives in
        # the card, and a native tooltip cannot be entered by the pointer.
        lbl.setToolTip(tr(self.lbl_limit_timer._en_tooltip, self._current_lang))
        self._set_topbar_semantic("lbl_limit_timer", True)
        self._refresh_reset_hover_card()

    def _show_reset_hover_card(self):
        """Open the reset-queue card (existing LimitHoverCard, no new system)."""
        lbl = getattr(self, "lbl_limit_timer", None)
        if lbl is None or not self._widget_alive(lbl) or not lbl.isVisible():
            return
        if not self._reset_queue_html:
            return
        card = getattr(self, "_reset_hover_card", None)
        if card is None or not self._widget_alive(card):
            from fastprompter.ui.limit_hover_card import LimitHoverCard
            card = LimitHoverCard(lbl)
            self._reset_hover_card = card
        try:
            card.show_card(self._reset_queue_html)
        except Exception:
            pass

    def _refresh_reset_hover_card(self):
        """Re-render an OPEN card; a closed one is left alone."""
        card = getattr(self, "_reset_hover_card", None)
        if card is None or not self._widget_alive(card) or not card.isVisible():
            return
        try:
            card.set_html(self._reset_queue_html)
        except Exception:
            pass

    def _hide_reset_hover_card(self):
        card = getattr(self, "_reset_hover_card", None)
        if card is None or not self._widget_alive(card):
            return
        card.schedule_hide()

    @staticmethod
    def _widget_alive(widget) -> bool:
        """True unless this is a Qt object sip has already destroyed.

        ``sip.isdeleted`` raises on a non-Qt double, and the hover helpers are
        exercised by tests (and by future refactors) with lightweight stand-ins,
        so the liveness question is asked only where it is answerable.
        """
        try:
            return not sip.isdeleted(widget)
        except TypeError:
            return True

    def _update_claude_bridge_controls(self, directory=None):
        label = getattr(self, "lbl_claude_bridge", None)
        button = getattr(self, "btn_claude_bridge", None)
        if label is None or button is None:
            return
        try:
            from fastprompter.core.usage_limits.claude_statusline import bridge_status
            status = bridge_status(directory)
        except Exception as exc:
            label.setText(f"Claude Code: configuration error — {exc}")
            button.setText("Connect Claude Code")
            return
        if status["connected"] and status["has_cache"]:
            label.setText("Claude Code: connected · structured limits received")
            button.setText("Disconnect Claude Code")
        elif status["connected"]:
            label.setText("Claude Code: connected · waiting for first API response")
            button.setText("Disconnect Claude Code")
        else:
            label.setText("Claude Code: not connected")
            button.setText("Connect Claude Code")

    def _toggle_claude_limit_bridge(self, directory=None):
        """Explicitly connect/disconnect the passive Claude status-line feed.

        ``directory`` names the EXACT Claude home to act on (T-1267) so an
        explicit account row never mutates a sibling home; omitted, the
        bridge layer resolves the default ~/.claude home -- the historical
        single-account behaviour.
        """
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
            install_bridge,
            uninstall_bridge,
        )
        try:
            if bridge_status(directory)["connected"]:
                uninstall_bridge(directory)
            else:
                install_bridge(directory)
        except Exception as exc:
            QMessageBox.warning(
                self, "Claude Code limits",
                "Could not update Claude Code statusLine safely:\n\n"
                f"{exc}")
            self._update_claude_bridge_controls(directory)
            return
        self._update_claude_bridge_controls(directory)
        svc = getattr(self, "limit_service", None)
        if svc is not None:
            svc.reconfigure_async(self.data)

    def open_limit_settings_dialog(self):
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

        dialog = LimitSettingsDialog(self)
        dialog.exec()
        self.limit_gauges.refresh_view()
        self._update_limit_status()

    def _show_in_app_toast(self, title, message, *, header=None, status=None,
                           duration_ms=None, accent_color=None, symbol=None):
        """The app's own silent visual notification (T-1228).

        The ONLY visual presentation for app-owned alerts. It never calls the
        OS notification API, so presenting a notification cannot inject a
        Windows/system sound; all audible sound is owned by SoundManager.
        Returns the toast, or None when no UI can be shown.
        """
        try:
            from fastprompter.ui.timer_toast import show_simple_toast
            return show_simple_toast(self, title, message, header=header,
                                     status=status, duration_ms=duration_ms,
                                     accent_color=accent_color, symbol=symbol)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("in-app toast failed")
            return None

    def _show_limit_popup(self, title, message, duration_sec=None, color=None, symbol=None):
        """Silent in-app notification for real quota alerts and previews."""
        from types import SimpleNamespace
        try:
            from fastprompter.ui.timer_toast import show_toast
            if duration_sec is None:
                duration_sec = self.data.get("limit_notif_duration_sec", 10)
            try:
                sec_val = float(duration_sec)
                duration_ms = int(sec_val * 1000) if sec_val > 0 else 0
            except (TypeError, ValueError):
                duration_ms = 10000

            if color is None:
                color = self.data.get("limit_notif_color", "")
            if color:
                try:
                    from fastprompter.ui.limit_colors import resolve_hex
                    color = resolve_hex(self, color) if not str(color).startswith("#") else color
                except Exception:
                    pass

            if symbol is None:
                symbol = self.data.get("limit_notif_symbol", "⚡")

            _toast_obj = SimpleNamespace(
                name=str(title),
                description=str(message),
                display_color=lambda: color if color else None,
            )
            toast = show_toast(self, _toast_obj,
                               header="FastPrompter", status="AI limit alert",
                               duration_ms=duration_ms,
                               accent_color=color if color else None,
                               symbol=symbol if symbol else None)
            if toast is not None:
                return
        except Exception:
            pass
        # T-1228: NO OS notification fallback -- its sound cannot be silenced
        # and would race the SoundManager-owned alert. A silent status-bar
        # message is the guaranteed-silent fallback.
        try:
            self.statusBar().showMessage(f"{title}: {message}", 8000)
        except Exception:
            pass

    def _check_limit_notifications(self):
        """Evaluate fresh authoritative snapshots and fire each rule once."""
        from fastprompter.core.usage_limits.notifications import (
            evaluate_limit_notifications,
        )
        from fastprompter.ui.limit_account_selector import account_display_name
        from fastprompter.ui.limit_settings_dialog import _request_limit_sound

        svc = getattr(self, "limit_service", None)
        if svc is None:
            return
        is_initial = not getattr(self, "_limit_notifications_initialized", False)
        self._limit_notifications_initialized = True
        snap = svc.state_copy
        alerts, new_state = evaluate_limit_notifications(
            snap.accounts, snap.snapshots,
            self.data.get("limit_notifications", {}),
            self.data.get("limit_notification_state", {}),
            is_initial_poll=is_initial,
        )
        if new_state != self.data.get("limit_notification_state", {}):
            self.data["limit_notification_state"] = new_state
            self.mark_dirty("settings")
        played_sounds = set()
        sound_played = False
        to_notify = []
        for alert in alerts:
            rule = alert.rule
            prefix = "reset_" if alert.kind == "reset" else ""
            if not sound_played and rule.get(f"{prefix}sound_enabled") == "True":
                sound_ref = rule.get(f"{prefix}sound", "notify")
                volume = rule.get(f"{prefix}volume", 0.5)
                sound_key = (sound_ref, volume)
                if sound_key not in played_sounds:
                    played_sounds.add(sound_key)
                    try:
                        _request_limit_sound(
                            self.sound_manager, alert.kind, alert.key,
                            sound_ref, volume,
                        )
                        sound_played = True
                    except Exception:
                        pass
            if rule.get(f"{prefix}show_notification") == "True":
                to_notify.append(alert)

        if not to_notify:
            return

        from fastprompter.ui.limit_settings_dialog import _window_name
        if len(to_notify) == 1:
            alert = to_notify[0]
            rule = alert.rule
            name = account_display_name(alert.account, self.data)
            remaining = float(alert.window.remaining_percent)
            if alert.kind == "reset":
                self._show_limit_popup(
                    f"AI limit reset: {name} — {_window_name(alert.window)}",
                    f"{remaining:.1f}% available again · time to work")
            else:
                threshold = float(rule.get("threshold", 20.0))
                self._show_limit_popup(
                    f"AI limit: {name} — {_window_name(alert.window)}",
                    f"{remaining:.1f}% remaining · "
                    f"alert threshold {threshold:.1f}%")
        else:
            # Coalesce multiple alerts in a single sweep: show combined toast to prevent screen flood
            lines = []
            for alert in to_notify:
                name = account_display_name(alert.account, self.data)
                remaining = float(alert.window.remaining_percent)
                w_name = _window_name(alert.window)
                if alert.kind == "reset":
                    lines.append(f"• {name} ({w_name}): reset ({remaining:.1f}% available)")
                else:
                    lines.append(f"• {name} ({w_name}): {remaining:.1f}% remaining")
            summary_msg = "\n".join(lines)
            self._show_limit_popup(
                f"AI limits: {len(to_notify)} quota alerts",
                summary_msg,
            )

    def _load_missed_ids(self):
        """Load the persisted missed-event IDs from the active profile data."""
        raw = self.data.get("missed_timer_ids")
        ids = set()
        if isinstance(raw, (list, tuple, set)):
            for i in raw:
                if isinstance(i, str) and i:
                    ids.add(i)
        # drop IDs that no longer correspond to an enabled one-shot in this
        # profile (e.g. a deleted/disabled timer carried over from a crash)
        from fastprompter.core.timers import REPEAT_NONE
        timers = getattr(self, "timers", [])
        valid = {getattr(t, "id", None) for t in timers
                 if getattr(t, "repeat", None) == REPEAT_NONE
                 and getattr(t, "enabled", False)}
        ids &= valid
        self._missed_timer_ids = ids

    def _persist_missed_ids(self):
        """Write the current missed-event ID set back into profile data."""
        missed = getattr(self, "_missed_timer_ids", None)
        if missed is None:
            return
        self.data["missed_timer_ids"] = sorted(missed)
        self.mark_dirty("settings")

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
        self._persist_missed_ids()
        self._apply_date_alert_style()

    def _ack_missed(self, timer):
        """The toast's Dismiss button: acknowledge THIS passed event."""
        if timer is not None:
            self._missed_timer_ids.discard(timer.id)
            self._persist_missed_ids()
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
                and temp.show_in_top_bar):
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
            self._set_topbar_semantic("lbl_timer", True)
            return

        # a running work/break phase outranks a distant alarm: it is the one
        # counting down right now, and it is the one being watched
        pomo = getattr(self, "productivity_timer", None)
        if pomo is not None and pomo.state != "idle":
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
            self._set_topbar_semantic("lbl_timer", True)
            return

        # an enabled interval rule that opted into the top bar is a real
        # upcoming reminder: render its countdown until the same boundary the
        # scheduler will fire on (W2-005), below Temp/Productivity precedence.
        import datetime as _idt
        cand = self._interval_top_bar_candidate(_idt.datetime.now())
        if cand is not None:
            rule, irem = cand
            short = getattr(self, "_header_dense", False)
            text = format_remaining(
                irem, short=short,
                minutes=self.data.get("timer_show_minutes", "False") == "True")
            name = rule.get("name") or tr("Reminder",
                                          getattr(self, "_current_lang", "EN"))
            if not short and len(name) > 14:
                name = name[:13] + "…"
            if not short:
                text = f"{name} {text}"
            lbl.setText(text)
            lbl.setToolTip(
                f"{name} — {tr('interval reminder', getattr(self, '_current_lang', 'EN'))}\n"
                + tr("Click to manage timers", getattr(self, "_current_lang", "EN")))
            lbl.setStyleSheet(
                "padding: 0 4px; font-weight: bold; color: #7fae7f;")
            self._set_topbar_semantic("lbl_timer", True)
            return

        nxt = next_due(getattr(self, "timers", []), topbar_only=True)
        if nxt is None:
            self._set_topbar_semantic("lbl_timer", False)
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
        self._set_topbar_semantic("lbl_timer", True)

    def _interval_top_bar_remaining(self, rule, now_dt):
        """Seconds until the next eligible occurrence of an interval rule, or
        None when the rule must not appear in the top bar (W2-005).

        Uses the same clock/elapsed boundary contract as the scheduler
        (`_check_interval_notifs`), so the countdown and the firing can never
        disagree about the next boundary. Clock rules with minutes > 1440 fire
        only at midnight (minute_of_day == 0), exactly as the scheduler does.
        """
        import datetime as _dt
        import time as _time

        if not rule.get("enabled"):
            return None
        if not rule.get("show_in_top_bar"):
            return None
        try:
            minutes = max(1, int(rule.get("minutes") or 60))
        except (TypeError, ValueError):
            return None
        align_mode = str(rule.get("align_mode", "clock"))

        if align_mode != "clock":
            last = float(rule.get("last_fired") or 0.0)
            if last <= 0.0:
                return minutes * 60.0
            return max(0.0, last + minutes * 60.0 - _time.time())

        mod = now_dt.hour * 60 + now_dt.minute
        minute_key = now_dt.strftime("%Y-%m-%d %H:%M")
        if minutes <= 1440:
            boundary_now = mod % minutes == 0
        else:
            boundary_now = mod == 0
        if boundary_now and rule.get("last_fired_minute") != minute_key:
            return 0.0
        if minutes <= 1440:
            nxt_mod = ((mod // minutes) + 1) * minutes
            if nxt_mod >= 1440:
                day = now_dt.date() + _dt.timedelta(days=1)
                nxt_mod %= 1440
            else:
                day = now_dt.date()
        else:
            day = now_dt.date() + _dt.timedelta(days=1)
            nxt_mod = 0
        nxt = _dt.datetime.combine(day, _dt.time(nxt_mod // 60, nxt_mod % 60))
        # active-hour gate: an occurrence outside the window is impossible, so
        # it must not be advertised as a countdown.
        if not rule.get("all_day", True):
            try:
                start_m = int(rule.get("start_minute", 0))
                end_m = int(rule.get("end_minute", 1439))
            except (TypeError, ValueError):
                start_m, end_m = 0, 1439
            if start_m <= end_m:
                if not (start_m <= nxt_mod <= end_m):
                    return None
            else:
                if not (nxt_mod >= start_m or nxt_mod <= end_m):
                    return None
        return max(0.0, (nxt - now_dt).total_seconds())

    def _interval_top_bar_candidate(self, now_dt):
        """First enabled show_in_top_bar interval rule with a valid next
        occurrence (topmost in list order wins), or None."""
        from fastprompter.core.logging import logger
        try:
            rules = self._interval_notifs()
        except Exception:
            logger.debug("interval top-bar rule read failed", exc_info=True)
            return None
        for rule in rules:
            try:
                remaining = self._interval_top_bar_remaining(rule, now_dt)
            except Exception:
                # HUNT: a broken rule must be skippable WITHOUT silently
                # swallowing the failure — one debug line keeps the error
                # visible in logs while the healthy rules still render.
                logger.debug("interval top-bar rule skipped: %s",
                             rule.get("id", "<no-id>"), exc_info=True)
                continue
            if remaining is not None:
                return rule, remaining
        return None

    def _temp_timer(self):
        """Return the one persisted express/focus timer, if any."""
        return next((t for t in getattr(self, "timers", [])
                     if getattr(t, "temporary", False)), None)

    def temp_timer_template(self):
        """Settings used when Shift+Click creates a fresh temp timer."""
        from fastprompter.core.timers import _heal_volume

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
        # canonical 0.0-1.0 float; legacy 0-10 accepted on read; never int()-truncate
        vol = _heal_volume(raw.get("volume", 5))
        volume = vol if vol is not None else 0.5
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
        from fastprompter.core.timers import _heal_volume

        current = self.temp_timer_template()
        current.update(settings or {})
        try:
            current["increment_minutes"] = max(
                1, int(current.get("increment_minutes", 15)))
        except (TypeError, ValueError):
            current["increment_minutes"] = 15
        # volume stored canonically as 0.0-1.0 (legacy 0-10 healed on the way in)
        if "volume" in current:
            hv = _heal_volume(current.get("volume"))
            current["volume"] = hv if hv is not None else 0.5
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
        import datetime as _datetime

        from fastprompter.core.timers import Timer

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
        """Apply compact sizing, then the centralized responsive policy."""
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
        from fastprompter.core.topbar_visibility import range_for_width
        active_range = range_for_width(self._topbar_visibility_config(), effective)
        dense = active_range != "wide"
        flipped = getattr(self, "_header_dense", None) != dense
        if flipped:
            self._header_dense = dense
            # Zero: the bar is tinted lighter than the widgets on it, so any
            # spacing showed as a 1px line of tint in EVERY gap - 31 of them,
            # measured. Buttons carry their own borders, so flush is the
            # classic toolbar look rather than a crowded one.
            self.header_layout.setSpacing(0)

        # Coarse flags remain sizing hints only. Visibility is owned by the
        # policy coordinator below and never by these flags.
        ultra = active_range == "ultra"
        ultra_flipped = getattr(self, "_header_ultra", None) != ultra
        self._header_ultra = ultra

        update_projects = getattr(self, "_update_project_buttons", None)
        if callable(update_projects):
            update_projects(refresh=False)
        if ultra_flipped:
            self._update_date_label()
            update_limit_timer = getattr(self, "_update_limit_timer_label", None)
            if callable(update_limit_timer):
                update_limit_timer()

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

        # Project number buttons: restore the configured baseline on every
        # pass. The coordinator shrinks them first; only then may its one
        # deterministic fallback displace lower-priority toolbar items.
        box = getattr(self, "cat_numbox", None)
        buttons = getattr(self, "_cat_num_buttons", ())
        if (box is not None and not sip.isdeleted(box)
                and not box.isHidden() and buttons):
            cfg = self.numbox_button_size()
            per_row = self.numbox_per_row()
            cols = min(len(buttons), per_row)
            rows = (len(buttons) + per_row - 1) // per_row
            spacing = self._cat_numbox_layout.spacing()
            for b in buttons:
                b.setFixedSize(cfg, cfg)
            box.setFixedSize(cols * cfg + max(0, cols - 1) * spacing,
                             rows * cfg + max(0, rows - 1) * spacing)

        self._apply_topbar_visibility()
        # The density tiers re-set widths and fonts, so the label-fit
        # guarantee has to be re-checked AFTER them — this runs on a 0ms
        # singleShot from apply_theme, i.e. after the theme's own fit pass,
        # and would otherwise silently undo it.
        if hasattr(self, "enforce_button_fit"):
            self.enforce_button_fit()

    # Compatibility names retained for third-party extensions. They are empty:
    # responsive policy lives in core.topbar_visibility.
    _DENSE_HIDDEN = ()
    _ULTRA_HIDDEN = ()

    def _topbar_visibility_config(self):
        """Validated responsive config; malformed/old profiles self-heal."""
        raw = self.data.get("topbar_visibility")
        cached_raw = getattr(self, "_cached_topbar_raw", None)
        cached_config = getattr(self, "_cached_topbar_config", None)
        if cached_config is not None and raw is cached_raw:
            return cached_config
        from fastprompter.core.topbar_visibility import normalize_topbar_visibility

        config = normalize_topbar_visibility(raw)
        if raw != config:
            self.data["topbar_visibility"] = config
            raw = config
        self._cached_topbar_raw = raw
        self._cached_topbar_config = config
        return config

    def _topbar_effective_width(self):
        """Width used by responsive rules after upward-only UI scaling."""
        width = max(0, self.width())
        try:
            scale = self._effective_scale()
        except Exception:
            scale = 1.0
        return width / scale if scale > 1.0 else float(width)

    def _header_available_width(self, header=None):
        """Pixels the top bar may actually occupy.

        ``header.width()`` is only meaningful once the window has been laid
        out. Before the first show it still carries the widget default (640,
        minus the layout margins), which is far narrower than the window and
        made the fit pass evict widgets that had plenty of room — the label a
        never-shown window reported as hidden. The window's own width is the
        honest bound in that state, so the smaller of the two is used only
        when the header has really been laid out.
        """
        if header is None:
            header = getattr(self, "header_widget", None)
        room = max(0, self.width() - 4)
        if header is None or sip.isdeleted(header) or not header.isVisible():
            return room
        width = header.width()
        return room if width <= 0 or width > room else width

    def _topbar_detail_mode(self, token):
        from fastprompter.core.topbar_visibility import range_for_width

        config = self._topbar_visibility_config()
        rid = range_for_width(config, self._topbar_effective_width())
        row = config["items"].get(token, {})
        detail = row.get("detail", {})
        return detail.get(rid, "full") if isinstance(detail, dict) else "full"

    def _set_topbar_semantic(self, token, available, *, refresh=True):
        """Publish feature availability without bypassing responsive policy."""
        states = getattr(self, "_topbar_semantic", None)
        if states is None:
            states = self._topbar_semantic = {}
        old_val = states.get(token)
        new_val = bool(available)
        states[token] = new_val
        if old_val == new_val:
            return
        if (refresh and not getattr(self, "_topbar_applying", False)
                and not getattr(self, "_initializing_ui", False)
                and hasattr(self, "header_widget")):
            self._apply_topbar_visibility()

    def _topbar_semantic_state(self):
        """Current non-responsive availability for every registered item."""
        from fastprompter.core.topbar_visibility import TOPBAR_ITEMS

        state = {item.token: True for item in TOPBAR_ITEMS}
        state.update(getattr(self, "_topbar_semantic", {}))
        dynamic = getattr(self, "_topbar_semantic", {})
        for token in ("btn_project_folder", "btn_project_run",
                      "lbl_timer", "lbl_limit_timer"):
            state[token] = bool(dynamic.get(token, False))
        numbox = self.data.get("numbox_tabs", "False") == "True"
        state["cat_combo"] = not numbox
        state["cat_numbox"] = numbox
        state["analog_clock"] = self.data.get("analog_clock", "False") == "True"
        state["lbl_date"] = self.data.get("show_date_rect", "True") == "True"
        gauges = self.data.get("limit_gauges", "False") == "True"
        state["limit_gauges"] = gauges
        state["lbl_limit_timer"] = gauges and state.get("lbl_limit_timer", False)
        line_label = getattr(self, "lbl_line_count", None)
        token_label = getattr(self, "lbl_token_count", None)
        state["lbl_line_count"] = bool(line_label is not None and line_label.text())
        state["lbl_token_count"] = (
            self.data.get("show_token_count", "False") == "True"
            and bool(token_label is not None and token_label.text()))
        state["btn_toolbar_reset"] = (
            self.data.get("customize_toolbar", "False") == "True")
        state["_counter_sep"] = bool(
            state.get("lbl_line_count") or state.get("lbl_token_count"))
        state["btn_overflow"] = False
        return state

    def _restore_cat_numbox_size(self):
        box = getattr(self, "cat_numbox", None)
        buttons = getattr(self, "_cat_num_buttons", ())
        if (box is None or sip.isdeleted(box) or box.isHidden() or not buttons):
            return
        configured = self.numbox_button_size()
        per_row = self.numbox_per_row()
        cols = min(len(buttons), per_row)
        rows = (len(buttons) + per_row - 1) // per_row
        spacing = self._cat_numbox_layout.spacing()
        for button in buttons:
            button.setFixedSize(configured, configured)
        box.setFixedSize(
            cols * configured + max(0, cols - 1) * spacing,
            rows * configured + max(0, rows - 1) * spacing,
        )

    def _apply_topbar_visibility(self):
        """Resolve semantic, user and fit state from the current width.

        No previous hidden set participates in this calculation. The same
        config, semantic state and width therefore always produce the same
        result, regardless of the resize path used to reach it.
        """
        header = getattr(self, "header_widget", None)
        layout = getattr(self, "header_layout", None)
        if (header is None or layout is None or sip.isdeleted(header)
                or getattr(self, "_topbar_applying", False)):
            return
        from fastprompter.core.topbar_visibility import (
            ITEM_BY_TOKEN,
            TOPBAR_ITEMS,
            requested_tokens,
        )

        self._topbar_applying = True
        try:
            config = self._topbar_visibility_config()
            semantic = self._topbar_semantic_state()
            rid, requested = requested_tokens(
                config, self._topbar_effective_width(), semantic)
            if not ({"lbl_line_count", "lbl_token_count"} & requested.keys()):
                requested.pop("_counter_sep", None)
            self._topbar_active_range = rid
            widgets = {}
            for item in TOPBAR_ITEMS:
                widget = getattr(self, item.token, None)
                if widget is None or sip.isdeleted(widget):
                    continue
                widgets[item.token] = widget
                widget.setVisible(item.token in requested)
            if "cat_numbox" in requested:
                for button in getattr(self, "_cat_num_buttons", ()):
                    if not sip.isdeleted(button):
                        button.setVisible(True)

            overflow = widgets.get("btn_overflow")
            if overflow is not None:
                overflow.setVisible(False)
            self._topbar_overflow_tokens = ()
            self._restore_cat_numbox_size()
            layout.activate()
            self._fit_cat_numbox_to_header()
            layout.activate()

            available = self._header_available_width(header)

            order = {item.token: index for index, item in enumerate(TOPBAR_ITEMS)}
            auto = [token for token, rule in requested.items() if rule == "auto"]
            emergency = [token for token, rule in requested.items()
                         if rule == "show" and ITEM_BY_TOKEN[token].configurable]
            def priority_key(token):
                return (
                    int(config["items"][token].get(
                        "priority", ITEM_BY_TOKEN[token].priority)),
                    order[token],
                )
            displaced = []
            for token in sorted(auto, key=priority_key) + sorted(
                    emergency, key=priority_key):
                if available <= 0 or header.sizeHint().width() <= available:
                    break
                widget = widgets.get(token)
                if widget is None or widget.isHidden():
                    continue
                widget.setVisible(False)
                if ITEM_BY_TOKEN[token].action:
                    displaced.append(token)
                    if overflow is not None:
                        overflow.setVisible(True)
                layout.activate()

            self._topbar_overflow_tokens = tuple(displaced)
            separator = widgets.get("_counter_sep")
            if (separator is not None
                    and all(widgets.get(token) is None
                            or widgets[token].isHidden()
                            for token in ("lbl_line_count", "lbl_token_count"))):
                separator.setVisible(False)
            # Reclaim any space released by fallback for number tabs, up to
            # their configured width. The 14 px floor remains clickable.
            self._restore_cat_numbox_size()
            layout.activate()
            self._fit_cat_numbox_to_header()
            layout.activate()
            self._topbar_visible_tokens = frozenset(
                token for token, widget in widgets.items() if not widget.isHidden())
        finally:
            self._topbar_applying = False

    def open_topbar_visibility_dialog(self):
        from fastprompter.ui.topbar_visibility_dialog import TopbarVisibilityDialog

        TopbarVisibilityDialog(self).exec()

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

    def capture_silo_state(self, slot=None, is_archive=None, text=None):
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
        # PERF-003: the caller may pass the already-materialized authoritative
        # snapshot (from save_data_to_db), so a fresh-edit save does not
        # re-extract the whole document here.
        try:
            doc = ta.document()
            entry["text_len"], entry["text_crc"] = \
                self._document_fingerprint(doc, text)
        except Exception as exc:
            from fastprompter.core.logging import logger as _log
            _log.warning("silo state fingerprint update failed: %s", exc)
        m = self._silo_state_map()
        cat_map = m.setdefault(cat, {})
        if cat_map.get(key) != entry:
            cat_map[key] = entry
            self.mark_dirty("settings")

    def _restore_folded_blocks_incrementally(self, doc, folded):
        """Restore a huge document's folds in small event-loop chunks."""
        ta = self.text_area
        cursor = [doc.begin()]

        def step():
            if (sip.isdeleted(self) or sip.isdeleted(ta) or sip.isdeleted(doc)
                    or ta.document() is not doc):
                return
            block = cursor[0]
            for _ in range(200):
                if not block.isValid():
                    return
                if (block.text().strip() in folded
                        and not (max(0, block.userState()) & ta.FOLD_BIT)):
                    ta.toggle_fold(block)
                block = block.next()
            cursor[0] = block
            QTimer.singleShot(0, step)

        QTimer.singleShot(0, step)

    def restore_silo_state(self, slot=None, is_archive=None):
        """Put the cursor, selection, scroll and margin marks back."""
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return False
        cat, key = self._silo_state_key(slot, is_archive)
        entry = (self._silo_state_map().get(cat) or {}).get(key)
        if not isinstance(entry, dict):
            return False

        doc = ta.document()
        # Reject stale view state before applying marks, folds or cursor data.
        # The fingerprint is seeded during document load/live snapshot, so the
        # warm and freshly-created paths do not need another toPlainText copy.
        if "text_len" in entry and "text_crc" in entry:
            try:
                fp = self._document_fingerprint(doc)
                if fp != (entry["text_len"], entry["text_crc"]):
                    return False
            except Exception:
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
                folded = set(folded)
                if doc and not sip.isdeleted(doc):
                    char_threshold = int(getattr(
                        self, "_LARGE_DOC_THRESHOLD", 500000))
                    block_threshold = int(getattr(
                        self, "_LARGE_DOC_BLOCK_THRESHOLD", 2000))
                    if (doc.characterCount() >= char_threshold
                            or doc.blockCount() >= block_threshold):
                        self._restore_folded_blocks_incrementally(doc, folded)
                    else:
                        b = doc.begin()
                        while b.isValid():
                            if (b.text().strip() in folded
                                    and not (max(0, b.userState()) & ta.FOLD_BIT)):
                                ta.toggle_fold(b)
                            b = b.next()
        except Exception:
            pass

        doc_len = doc.characterCount() - 1
        # T-720: the saved offsets belong to the text they were captured
        # against. If that text changed (an edit between sessions, a reload,
        # an undo that rewrote the doc), clamping the OLD offset into the NEW
        # document lands the caret mid-word. Fall back to the caller's own
        # Start/End rule instead. Entries written before this fingerprint
        # existed carry neither field and keep the old clamp behaviour.
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
        new = save_timers(self.timers)
        # prune missed-event IDs whose timer was deleted/disabled (W2-003)
        missed = getattr(self, "_missed_timer_ids", None)
        if missed:
            from fastprompter.core.timers import REPEAT_NONE
            valid = {t.id for t in self.timers
                      if getattr(t, "repeat", None) == REPEAT_NONE
                      and getattr(t, "enabled", False)}
            dropped = missed - valid
            if dropped:
                missed -= dropped
                self._persist_missed_ids()
        # PERF-001: change-aware — a no-op (countdown-only) update must not
        # mark settings dirty every tick
        if self.data.get("timers") == new:
            return
        self.data["timers"] = new
        self.mark_dirty("settings")

    def save_productivity_timer(self):
        new = self.productivity_timer.to_dict()
        # PERF-001: change-aware — only persist + mark dirty when something
        # actually changed (durations/sounds/volume), not on every countdown tick
        if self.data.get("productivity_timer") == new:
            return
        self.data["productivity_timer"] = new
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

        A repeating alarm (``repeat_alarm``) keeps replaying its sound on a
        cadence after a phase ends, until it is acknowledged (CORE-001).
        """
        timer = getattr(self, "productivity_timer", None)
        if timer is None:
            return
        import time as _t
        now = _t.monotonic()
        last, self._pomo_last_tick = self._pomo_last_tick, now
        if not timer.running:
            # stopped/paused: a pending alarm no longer replays. Clear the
            # cadence anchor but leave alarm_pending for the UI to surface.
            if not (timer.alarm_pending and timer.repeat_alarm
                    and timer.sound_enabled):
                self._pomo_alarm_replay_at = None
            return
        if last is None:
            return                        # first tick after starting
        ended = timer.tick(now - last)
        for phase in ended:
            self._notify_productivity(phase)
        if ended:
            # arm the replay cadence from the moment the phase ended
            self._pomo_alarm_replay_at = now
            self.save_productivity_timer()
        if (timer.alarm_pending and timer.repeat_alarm
                and timer.sound_enabled):
            if self._pomo_alarm_replay_at is None:
                self._pomo_alarm_replay_at = now
            elif now - self._pomo_alarm_replay_at >= self._POMO_ALARM_REPEAT_SECONDS:
                self._pomo_alarm_replay_at = now
                self._replay_productivity_alarm()
        else:
            self._pomo_alarm_replay_at = None

    def _replay_productivity_alarm(self):
        """Replay only the sound for a still-pending productivity alarm."""
        timer = getattr(self, "productivity_timer", None)
        if timer is None or not timer.alarm_pending:
            return
        if not getattr(timer, "sound_enabled", True):
            return
        from fastprompter.core.pomodoro import PHASE_WORK
        phase = getattr(timer, "alarm_phase", None) or timer.phase
        sound_ref = (timer.work_sound if phase == PHASE_WORK
                     else timer.break_sound)
        vol = getattr(timer, "volume", 0.05)
        try:
            if hasattr(self, "sound_manager") and self.sound_manager:
                self.sound_manager.play_sound_ref(sound_ref, vol)
            else:
                self.play_sound(sound_ref)
        except Exception:
            from fastprompter.core.logging import logger
            logger.debug("productivity alarm replay failed")

    def _notify_productivity(self, phase):
        """Sound + popup when a work or break phase ends."""
        from fastprompter.core.pomodoro import PHASE_WORK
        lang = getattr(self, "_current_lang", "EN")
        title = (tr("Work phase over", lang) if phase == PHASE_WORK
                 else tr("Break over", lang))
        timer = getattr(self, "productivity_timer", None)
        if timer and getattr(timer, "sound_enabled", True):
            sound_ref = getattr(timer, "work_sound", "file:QUEST.wav") if phase == PHASE_WORK else getattr(timer, "break_sound", "file:NEWDAY.wav")
            vol = getattr(timer, "volume", 0.05)
            try:
                if hasattr(self, "sound_manager") and self.sound_manager:
                    self.sound_manager.play_sound_ref(sound_ref, vol)
                else:
                    self.play_sound(sound_ref)
            except Exception:
                from fastprompter.core.logging import logger
                logger.debug("productivity sound failed")
        # T-1228: the visual half is an in-app toast, never an OS tray
        # notification -- the latter can add its own Windows sound that
        # SoundManager does not own or know about.
        try:
            message = self.productivity_timer.describe()
        except Exception:
            message = ""
        try:
            self._show_in_app_toast(
                title, message,
                header="FastPrompter", status=title, duration_ms=10000)
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
        pass

    def _queue_slot_key(self):
        slot = getattr(self, "active_temp_slot", 0)
        prefix = "a" if getattr(self, "active_is_archive", False) else ""
        return f"{prefix}{slot}"

    def _sync_active_queue_lines(self):
        pass

    def queue_current_line(self):
        return None

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
        raw = ""
        if 0 <= index < len(presets):
            raw = presets[index] or ""
        # PERF-001: never materialize the full splitlines() of an unchanged
        # inactive silo on every 900ms Watcher tick. Cache per (slot, raw-id)
        # the exact requested line numbers, extracted by a sequential scan
        # that stops after the highest requested line.
        # PERF-004: the cache key must describe what it actually holds — the
        # requested-line COVERAGE, not just the raw object identity. When the
        # requested set changes while the raw text is unchanged, missing lines
        # are extracted now (fill coverage) instead of being misread as
        # detached source lines.
        if not hasattr(self, "_queue_live_line_cache"):
            self._queue_live_line_cache = {}
        wanted = sorted({item.line for item in items if item.line})
        if not wanted:
            lines_map = {}
        else:
            cache = self._queue_live_line_cache
            entry = cache.get(str(slot))
            if entry is None or entry[0] != id(raw):
                lines_map = self._extract_requested_lines(raw, set(wanted))
                cache[str(slot)] = (id(raw), lines_map, set(wanted))
            else:
                _, cached_lines, covered = entry
                missing = set(wanted) - covered
                if missing:
                    # coverage-aware: fill only the uncached lines from the
                    # SAME unchanged raw text
                    new_map = self._extract_requested_lines(raw, missing)
                    new_map.update(cached_lines)
                    lines_map = new_map
                    cache[str(slot)] = (id(raw), new_map, covered | missing)
                else:
                    lines_map = cached_lines

        for item in items:
            if item.line and item.line in lines_map:
                text = lines_map[item.line].strip()
                if text:
                    result[item] = (text, False)
                    continue
            # Nothing to read it from. A source-referenced item (line > 0) that
            # cannot be resolved is DETACHED — a stale snapshot is not live and
            # must not be sent as if it were (T-756). A snapshot item (line 0,
            # usually moved in from elsewhere) has no source, so it survives.
            result[item] = (item.text, bool(item.line))
            
        return result

    @staticmethod
    def _extract_requested_lines(raw, wanted):
        """Extract only ``wanted`` 1-based line numbers without building the
        full splitlines() list. Stops after the highest requested line."""
        if not wanted:
            return {}
        max_line = max(wanted)
        wanted = set(wanted)
        out = {}
        line_no = 1
        i = 0
        n = len(raw)
        while i < n and line_no <= max_line:
            j = raw.find("\n", i)
            if j < 0:
                j = n
            if line_no in wanted:
                out[line_no] = raw[i:j]
            i = j + 1
            line_no += 1
        return out

    def queue_item_live_text(self, slot, item):
        """The text this item would send right now."""
        return self.queue_items_live_text(slot, [item])[item]

    def open_queue_dialog(self, master=False):
        pass

    def open_queue_master(self):
        pass

    # ---- hashtags -----------------------------------------------------
    def open_hashtag_dialog(self, tag=None):
        from fastprompter.ui.hashtag_dialog import HashtagDialog
        self._increment_focus_lock()
        try:
            HashtagDialog(self, tag).exec()
        finally:
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))

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
        self._clear_missed_alert()
        self._increment_focus_lock()
        try:
            TimerDialog(self, initial_tab=initial_tab).exec()
        finally:
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
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
        "volume": 1.0,
        "show_notification": False,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
        "last_fired": 0.0,
        "last_fired_minute": "",
    }

    def _heal_interval_rule(self, rule):
        """Canonicalize one interval-notif rule; drop non-dicts (W2-004).

        Heals minutes, booleans, alignment, active-hour bounds, volume
        (canonical 0.0-1.0, legacy 0-10 healed) and string fields, and yields
        a unique non-empty id. Returns None for entries that are not dicts.
        """
        import uuid as _uuid

        if not isinstance(rule, dict):
            return None
        r = dict(rule)
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            rid = "interval_" + _uuid.uuid4().hex[:8]
        r["id"] = rid
        try:
            minutes = int(r.get("minutes", 60))
        except (TypeError, ValueError):
            minutes = 60
        r["minutes"] = max(1, minutes)
        for bk, dflt in (("enabled", True), ("show_notification", False),
                          ("show_in_top_bar", False), ("all_day", True)):
            v = r.get(bk, dflt)
            if isinstance(v, str):
                r[bk] = v.strip().lower() not in ("", "0", "false", "no", "off")
            else:
                r[bk] = bool(v)
        am = str(r.get("align_mode", "clock"))
        r["align_mode"] = am if am in ("clock", "elapsed") else "clock"
        try:
            sm = int(r.get("start_minute", 0))
        except (TypeError, ValueError):
            sm = 0
        try:
            em = int(r.get("end_minute", 1439))
        except (TypeError, ValueError):
            em = 1439
        r["start_minute"] = max(0, min(1439, sm))
        r["end_minute"] = max(0, min(1439, em))
        from fastprompter.core.timers import _heal_volume
        vol = _heal_volume(r.get("volume", 0.5))
        r["volume"] = vol if vol is not None else 0.5
        snd = r.get("sound")
        r["sound"] = snd if isinstance(snd, str) and snd else None
        nm = r.get("name")
        r["name"] = nm if isinstance(nm, str) and nm else "Interval"
        try:
            lf = float(r.get("last_fired", 0.0))
        except (TypeError, ValueError):
            lf = 0.0
        r["last_fired"] = lf
        lfm = r.get("last_fired_minute")
        r["last_fired_minute"] = lfm if isinstance(lfm, str) else ""
        return r

    def _interval_notifs(self):
        """Return the healed interval-notif rules.

        Non-dict entries are dropped, malformed fields are healed, duplicate
        ids are collapsed (first wins), and the result is written back so a
        malformed stored list round-trips to canonical JSON (W2-004).
        """
        rules = self.data.get("interval_notifs")
        if not isinstance(rules, list):
            rules = [dict(self._INTERVAL_NOTIF_DEFAULT)]
            self.data["interval_notifs"] = rules
            self.mark_dirty()
            return rules
        healed = []
        seen_ids = set()
        changed = False
        for raw in rules:
            h = self._heal_interval_rule(raw)
            if h is None:
                changed = True
                continue
            if h["id"] in seen_ids:
                changed = True
                continue
            seen_ids.add(h["id"])
            healed.append(h)
            if h != raw:
                changed = True
        if changed:
            self.data["interval_notifs"] = healed
            self.mark_dirty()
        return healed

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
                    # Fire on the clock crossing: the current minute-of-day is a
                    # multiple of the interval. NOT gated on second==0, so a late
                    # or missed 1Hz sample still catches the boundary on its next
                    # tick (once) — last_fired_minute dedups by minute, so there
                    # are no replay storms and no same-boundary duplicates. This
                    # also makes arbitrary clock intervals (45m, 90m, ...) valid
                    # instead of silently never firing.
                    if minute_of_day % minutes == 0:
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
            # W2-004 follow-up: _heal_interval_rule returns dict(rule) copies,
            # so last_fired/last_fired_minute updates on the copies never reach
            # the originals in self.data["interval_notifs"].  Write them back
            # so the next tick sees the updated timestamps.
            raw = self.data.get("interval_notifs")
            if isinstance(raw, list):
                for rule in rules:
                    rid = rule.get("id")
                    if not rid:
                        continue
                    for orig in raw:
                        if isinstance(orig, dict) and orig.get("id") == rid:
                            if "last_fired" in rule:
                                orig["last_fired"] = rule["last_fired"]
                            if "last_fired_minute" in rule:
                                orig["last_fired_minute"] = rule["last_fired_minute"]
                            break
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
            # T-1228: the interval visual is an in-app toast, NOT
            # QSystemTrayIcon.showMessage(). The OS notification can add its
            # own Windows sound that races ahead of the SoundManager-owned
            # WAV -- the reported stray "pop" before the hourly sound.
            try:
                self._show_in_app_toast(
                    str(rule.get("name") or "Hourly Reminder"), "",
                    header="FastPrompter",
                    status=tr("Interval reached", self._current_lang),
                    symbol="\U0001F514", duration_ms=4000)
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
                self._persist_missed_ids()
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
        # W2-006: a toast may only advertise actions the runtime will accept.
        # The snooze/missed-attention contract is defined for PERSISTENT OWNED
        # one-shot timers only. A Test probe is never in self.timers and a
        # delete_after_fire Temp timer is retired the moment it fires, so
        # neither may accumulate missed attention nor offer a Snooze button
        # whose callback the ownership guard would reject.
        owned = timer in getattr(self, "timers", [])
        will_remain = owned and not (
            getattr(timer, "temporary", False)
            and getattr(timer, "delete_after_fire", False))
        # The red date alert is a state indicator, not a duplicate of the
        # popup. A calendar event still needs attention when the user chose
        # silent notifications, so register it before the popup early-return.
        if timer.repeat == REPEAT_NONE and will_remain:
            missed = getattr(self, "_missed_timer_ids", None)
            if missed is not None:
                missed.add(timer.id)
                self._persist_missed_ids()
        if not timer.show_notification:
            # visual notification intentionally off — no popup, no tray
            return
        from fastprompter.ui.timer_toast import show_toast
        # A fired ONE-SHOT timer whose moment passed enters the "missed" set:
        # the date label turns red (user-chosen colour) until the event is
        # snoozed, deleted, disabled or explicitly acknowledged (Dismiss).
        # Repeating timers are never "missed" — they roll to their next
        # occurrence and the top bar shows that instead.
        toast = show_toast(self, timer,
                           on_snooze=self._snooze_timer if will_remain else None,
                           on_dismiss=getattr(self, "_ack_missed", None))
        if toast is None:
            # popup unavailable (no screen / teardown) -- NEVER fall back to a
            # notification API whose silence cannot be guaranteed (T-1228).
            # The timer's SoundManager-owned WAV already represented the
            # audible event; a missing visual beats injecting a second sound.
            try:
                lang = getattr(self, "_current_lang", "EN")
                status = getattr(self, "statusBar", None)
                if callable(status):
                    status().showMessage(
                        f"{tr('Timer', lang)}: {timer.summary()}", 10000)
            except Exception:
                from fastprompter.core.logging import logger
                logger.debug("timer silent fallback failed")

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
                self._persist_missed_ids()
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

    def _fit_settings_tabs(self, index=None, _deferred=False):
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
            # Once the page is on screen with a real width, THAT is the width
            # its layout will be given; an estimate a few pixels wider can
            # pick a lower arrangement and cut the page's last cards off
            # (T-1246: Problip at 960px measured 195px for 215px of cards).
            if page.isVisible() and page.width() > 200:
                avail = page.width()
            measurer = (getattr(page, "totalHeightForWidth", None)
                        or getattr(inner, "totalHeightForWidth", None))
            if measurer is not None:
                try:
                    needed = measurer(avail)
                except Exception:
                    needed = page.sizeHint().height()
            else:
                needed = page.sizeHint().height()
            bar = tabs.tabBar().sizeHint().height() if tabs.tabBar() else 24
            fitted = max(60, needed + bar + 14)
            tabs.setFixedHeight(fitted)
            # The panel must never be compressed below its content, or the
            # last row (Typos on the Editor tab) is cut off.  The frame's
            # vertical policy is Maximum, so the main layout can shrink it
            # below content — pin the frame's own minimumHeight to the full
            # height its layout needs.  Only once the frame has a real
            # width: during the initial build it is ~100px and a measured
            # minimum there is a single tall column.
            if frame is not None and not sip.isdeleted(frame) and frame.width() > 200:
                flay = frame.layout()
                if flay is not None:
                    app_h = 0
                    app_item = flay.itemAt(0)
                    app_w = app_item.widget() if app_item is not None else None
                    if app_w is not None and hasattr(app_w, "totalHeightForWidth"):
                        try:
                            avail_w = app_w.width() if app_w.width() > 100 else avail
                            app_h = app_w.totalHeightForWidth(avail_w)
                        except Exception:
                            app_h = app_w.height()
                    if app_w is not None and app_h > 0:
                        app_w.setFixedHeight(app_h)
                    hline_h = 0
                    hl_item = flay.itemAt(1)
                    hl_w = hl_item.widget() if hl_item is not None else None
                    if hl_w is not None:
                        hline_h = max(2, hl_w.sizeHint().height())
                    m = flay.contentsMargins()
                    pad = m.top() + m.bottom() + flay.spacing() * 2
                    # SETTINGS LAYOUT OVERRIDE (T-1205): the frame is the
                    # complete content height of the current tab. It is a
                    # function of (current tab, current width) only — never
                    # of the window's resize/open/close history — so the
                    # editor below always receives the remaining space and
                    # nothing inside Settings is ever clipped.
                    needed_frame = int(app_h + hline_h + fitted + pad)
                    frame.setMinimumHeight(needed_frame)
                    frame.setMaximumHeight(needed_frame)
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

        # The first fit can run while the main layout still reports its
        # construction geometry (often only the toolbar row).  Re-measure
        # once after Qt has applied the geometry.  The guard and
        # ``_deferred`` flag make this one extra pass, not a timer loop.
        if (not _deferred and frame.isVisible()
                and not getattr(self, "_settings_refit_pending", False)):
            self._settings_refit_pending = True

            def _deferred_refit(window):
                window._settings_refit_pending = False
                window._fit_settings_tabs(index, _deferred=True)

            QTimer.singleShot(0, weak_qt_callback(self, _deferred_refit))

    def pick_hover_colour(self):
        from PyQt6.QtWidgets import QColorDialog

        current = self.data.get("hover_line_color", "auto")
        start = QColor(current) if QColor(current).isValid() else QColor("#6aa9ff")
        self._increment_focus_lock()
        try:
            chosen = QColorDialog.getColor(start, self, tr(
                "Hover line colour", getattr(self, "_current_lang", "EN")))
        finally:
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
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
        """Action buttons displaced by the authoritative fit result."""
        out = []
        for name in getattr(self, "_topbar_overflow_tokens", ()):
            btn = getattr(self, name, None)
            if btn is None or sip.isdeleted(btn):
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
        """Compatibility entry point for callers predating the coordinator."""
        self._apply_topbar_visibility()

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
        if getattr(self, "cb_focus", None) is not None:
            self.cb_focus.setChecked(not self.cb_focus.isChecked())
            self.play_tick_sound(self.cb_focus.isChecked())
        else:
            cur = self.data.get("close_on_focus_loss", "True") == "True"
            new_val = not cur
            self.data["close_on_focus_loss"] = "True" if new_val else "False"
            self.mark_dirty()
            self.play_tick_sound(new_val)

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
        cb_top = getattr(self, "cb_top", None)
        if cb_top is not None and cb_top.isChecked() != checked:
            cb_top.setChecked(checked)  # cb_top's handler does the work
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
            self._set_topbar_semantic("btn_toolbar_reset", on)

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
            # Composite undo/redo restores a captured (text, mapping) PAIR.
            # The retitle follower below would read that pair as "the user
            # retitled assets -> new" and physically rename the restored
            # folder, leaving the undo's own physical half pointing at a
            # path that no longer exists (the next redo then refuses with
            # "orientation impossible"). A restore is not a retitle.
            if getattr(self, "_composite_applying", False):
                return fmap[key]
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
        for record in log:
            # W2-005: defensively skip malformed members — a corrupt row must
            # never abort the whole recovery batch.
            if not (isinstance(record, (tuple, list)) and len(record) >= 2
                    and isinstance(record[0], str) and isinstance(record[1], str)
                    and record[0] and record[1]):
                continue
            original, trashed = record[0], record[1]
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

    @staticmethod
    def _bounded_cache_put(cache: dict, key, value, cap: int) -> None:
        """Insert ``key -> value`` into ``cache``, evicting the oldest entries
        (insertion order) when the map exceeds ``cap``. PERF-006: folder-result
        caches must stay bounded across long tray-resident sessions, not grow
        monotonically with every folder the user visits."""
        cache[key] = value
        while len(cache) > cap:
            try:
                cache.pop(next(iter(cache)), None)
            except StopIteration:
                break

    def _on_file_count_result(self, path, count, slot_idx, is_archive, category,
                              profile_id):
        if hasattr(self, "_pending_file_counts"):
            self._pending_file_counts.discard(path)
        if not hasattr(self, "_file_count_cache"):
            self._file_count_cache = {}
        self._bounded_cache_put(self._file_count_cache, path, count,
                                _FILE_COUNT_CACHE_CAP)

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
        """Open the comprehensive sound settings dialog.

        T-1242 spec A2: one predictable lifecycle.  The dialog object is
        kept alive by the class-level hook it already registers for the
        theme repaint (``_LAST_INSTANCE``); ``open_canonical`` reuses a live
        instance, clears a stale one, and returns the single dialog.  A
        construction failure is recorded as a bounded
        AUDIO_HUB_OPEN_FAILED provenance entry -- never silently swallowed.
        """
        from fastprompter.ui.sound_settings_dialog import SoundSettingsDialog

        t0 = time.perf_counter()
        # The modal takes the foreground, which is a deactivation as far as
        # the main window is concerned — without the lock, Hide on Click-Out
        # hid everything behind the dialog and closing it left the user
        # staring at a desktop where nothing reacted any more.
        self._increment_focus_lock()
        try:
            try:
                dialog = SoundSettingsDialog.open_canonical(
                    self, self.data, self.sound_manager)
            except Exception as exc:  # noqa: BLE001 - spec A5: never silent
                try:
                    self.sound_manager._provenance.append({
                        "op": "AUDIO_HUB_OPEN_FAILED",
                        "detail": f"{type(exc).__name__}: {exc}"[:200],
                        "outcome": "FAILED",
                    })
                except Exception:
                    pass
                raise
            # T-1245: the hub owns the SPECIFIC audio_hub_show event for
            # every visible presentation of the dialog (fresh construction
            # or reuse-raise), so the generic dialog_show must never also
            # fire for the same appearance.
            from fastprompter.ui.appearance_sounds import (
                SPECIFIC_APPEARANCE_ATTR,
                emit_audio_hub_show,
            )
            setattr(dialog, SPECIFIC_APPEARANCE_ATTR, "audio_hub_show")
            emit_audio_hub_show(self)
            try:
                self.last_audio_hub_open_timings = dict(
                    getattr(dialog, "_timings", {}))
            except RuntimeError:
                pass
            self.last_audio_hub_open_timings["click_to_exec"] = (
                (time.perf_counter() - t0) * 1000.0)
            dialog.exec()
        finally:
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
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

    def _update_project_buttons(self, is_archive=None, *, refresh=True):
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
            self._set_topbar_semantic(
                "btn_project_folder", has_folder, refresh=False)
        if hasattr(self, "btn_project_run"):
            self._set_topbar_semantic(
                "btn_project_run", has_exe, refresh=False)
        if refresh and hasattr(self, "header_widget"):
            self._apply_topbar_visibility()

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
            # TTL check; PERF-006: an EXPIRED entry is removed, not merely
            # ignored, so the map does not retain dead path keys forever.
            import time
            hit_time, hit_text = self._tooltip_cache[folder]
            if time.time() - hit_time < 30.0:
                self.btn_files.setToolTip(base_tt + hit_text)
                return
            del self._tooltip_cache[folder]

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
                def __init__(self, p, s, lang, cat, is_arc, prof, app_ref):
                    super().__init__()
                    self.p = p
                    self.s = s
                    self.lang = lang
                    self.cat = cat
                    self.is_arc = is_arc
                    self.prof = prof
                    self.app_ref = app_ref
                def run(self):
                    from fastprompter.ui.file_container import folder_summary
                    try:
                        res = folder_summary(self.p, lang=self.lang)
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
        # PERF-006: cap the tooltip map; the full summary text is retained for
        # every distinct folder visited over a long session otherwise.
        self._bounded_cache_put(self._tooltip_cache, folder, (time.time(), res),
                                _TOOLTIP_CACHE_CAP)
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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
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
        color_val = silo_colors.get(str(idx), "")
        color_hex = color_val if (has_hash or (color_val and self.data.get("silo_color_box", "True") == "True")) else ""

        btn.update_data(label, idx, bg_color, font_family, scale, line_str, True, title_bold, is_child, fcount, has_children, is_collapsed, has_hash, color_hex, is_pinned)

    def mark_dirty(self, domain=None):
        self.state.mark_dirty(domain)

    def _auto_save_tick(self):
        if not getattr(self.state, "has_pending_changes", getattr(self.state, "_db_dirty", False)):
            return
        import time as _t
        _start = _t.monotonic()
        st = self.state
        dirty_before = []
        if getattr(st, "_db_dirty", False):
            dirty_before.append("db")
        if getattr(st, "_dirty_settings", 0) > getattr(st, "_saved_settings_gen", 0):
            dirty_before.append("settings")
        if getattr(st, "_dirty_snippets", 0) > getattr(st, "_saved_snippets_gen", 0):
            dirty_before.append("snippets")
        if getattr(st, "_dirty_temp", 0) > getattr(st, "_saved_temp_gen", 0):
            dirty_before.append("temp")
        if getattr(st, "_dirty_arc", 0) > getattr(st, "_saved_arc_gen", 0):
            dirty_before.append("archive")
        try:
            saved = bool(self.save_data_to_db())
        finally:
            _elapsed_ms = (_t.monotonic() - _start) * 1000
            # T06: log only slow autosaves (>= 30 ms) with the dirty domains
            # and the coordinator snapshot, so a persistence stall is
            # diagnosable without a logging firehose on the healthy path.
            if _elapsed_ms >= 30:
                from fastprompter.core.logging import logger as _log
                try:
                    from fastprompter.core.state import backup_debug_state
                    coord = backup_debug_state(st.db_path)
                except Exception:
                    coord = {"available": False, "reason": "error"}
                result = getattr(st, "_last_save_outcome", "FAILED")
                if "saved" in locals() and saved:
                    result = "committed"
                _log.warning(
                    "autosave.total=%.1fms dirty=%s result=%s coord=%s",
                    _elapsed_ms, ",".join(dirty_before) or "none", result, coord)

    def play_sound(self, name):
        self.sound_manager.play(name)

    def play_click_sound(self):
        self.sound_manager.play_click()

    def play_project_sound(self):
        self.sound_manager.play_project()

    def _play_settings_tab_sound(self, index=-1):
        """Click for the Window/Editor/Clock/Data tabs.

        Silent while the UI is still being assembled: adding the four pages
        fires `currentChanged` before the window is on screen, and a startup
        that goes "click" on its own is a bug report, not a feature.
        """
        if index < 0 or getattr(self, "_initializing_ui", False):
            return
        self.play_sound("settings_tab")

    def play_tick_sound(self, on=True):
        self.sound_manager.play_tick(bool(on))

    # Which shortcuts get a sound of their own. Everything else falls back to
    # the generic `hotkey` event, which ships DISABLED — a sound on literally
    # every shortcut, on by default, is a reason to switch sound off entirely.
    # T-1244: the mute hotkey plays its own cue from INSIDE the toggle (the
    # wrapper's generic "hotkey" event would be muted by the very state the
    # keypress sets, and would double the cue that survives the mute).
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
        "toggle_files_hotkey": "chest_open",
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
        # toggle_sidebar_visibility plays "sidebar" inside; the wrapper's
        # own event would double it on Alt+D.
        "toggle_sidebar_hotkey",
        # toggle_mini_settings plays "settings" inside — it has to, because the
        # two ⚙ header buttons call it directly and a sound wired only here
        # left them mute. The wrapper's event would double it on Alt+`.
        "hk_settings",
        # file_container.open_for / close plays "chest_open" / "chest_close"
        # internally; the wrapper's event would double it on Alt+F.
        "toggle_files_hotkey",
        # quit_app owns the one canonical exit sound and waits for it.  A
        # wrapper sound would start the same event twice on the shortcut path.
        "hk_quit", "hk_snap",
        # T-1244: toggle_audio_mute plays its own mute cue from inside — the
        # wrapper's generic "hotkey" event would be silenced by the very mute
        # state the keypress sets, and would double the surviving cue.
        "hk_audio_mute",
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
            QTimer.singleShot(50, weak_qt_callback(
                self,
                lambda window: window._deferred_silo_refresh(attempts - 1)))
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
            self._visible_silos = getattr(self, "_visible_silos", 10)

    def _ensure_silo_buttons(self, count):
        count = max(1, min(50, count))
        while len(self.silo_buttons) < count:
            btn = DraggableSiloButton(self)
            btn.setMinimumHeight(14)
            btn.hide()
            self.silos_widget.layout.addWidget(btn)
            self.silo_buttons.append(btn)

    def _ensure_archive_buttons(self, count):
        count = max(1, min(50, count))
        while len(self.archive_buttons) < count:
            btn = DraggableSiloButton(self, is_archive=True)
            btn.setMinimumHeight(14)
            btn.hide()
            self.archive_widget.layout.addWidget(btn)
            self.archive_buttons.append(btn)

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

    def save_data_to_db(self, force=False, durable=False):
        # PERF-003: acquire ONE authoritative whole-document snapshot and
        # thread the SAME string through silo-state fingerprinting and the
        # authoritative persistence — a fresh-edit save must not materialize
        # the Qt document twice.
        if hasattr(self, "text_area"):
            # T-1227: read the LIVE document through the revision-keyed
            # snapshot, never the debounce cache. `_last_cached_text` can
            # still hold the previous document's text across a silo switch
            # (cache tick not yet run), which would land it in the newly
            # active slot. The snapshot is keyed by (doc id, revision), so
            # this is still a single materialization, not a second one.
            current_text = self._editor_text_snapshot()
            if current_text is None:
                # T-1250: an unreadable editor is NOT an empty document and
                # the stored text of the last successful save is NOT live
                # editor content. The live flush and the view-state capture
                # are refused below; the already-stored silo text stays
                # authoritative while this save still persists the
                # non-editor state truthfully.
                self._live_editor_unreadable = True
                self._last_cached_text = None
                current_text = self.data.get("last_text", "")
                self._log_snapshot_unavailable("save_data_to_db",
                                               bool(getattr(
                                                   self,
                                                   "active_is_archive",
                                                   False)))
            else:
                self._live_editor_unreadable = False
                self._last_cached_text = None
        else:
            self._live_editor_unreadable = False
            current_text = self.data.get("last_text", "")
        self._last_saved_text = current_text

        # Capture the current silo's view state so the saved position,
        # cursor, and scroll survive restart.
        if (
            not getattr(self, "_suspend_cache", False)
            and hasattr(self, "text_area")
            and not getattr(self, "_live_editor_unreadable", False)
        ):
            self.capture_silo_state(self.active_temp_slot,
                                    getattr(self, "active_is_archive", False),
                                    text=current_text)
            # and WHICH silo that was, for this project — the outer half of
            # "put me back where I left off"
            self.capture_silo_session()

        # CORE-001: the live editor owner must be flushed synchronously before
        # EVERY authoritative save. Snippet mode copies the exact editor text
        # into the referenced snippet (updating last-edited metadata and the
        # snippets domain dirty flag); silo mode keeps the established
        # per-slot behaviour under its suspension guards.
        if (
            not getattr(self, "_suspend_cache", False)
            and not getattr(self, "_initializing_ui", False)
            and not getattr(self, "_suspend_temp_sync", False)
            and not getattr(self, "_live_editor_unreadable", False)
        ):
            self._flush_live_editor(current_text)

        # T-1227 §11/§28: queue a committed-text transition for every silo
        # whose content changed since the last authoritative commit. The
        # state layer drains the queue INSIDE the save transaction, so a
        # content overwrite can never land without its recovery predecessor.
        self._queue_silo_text_history()

        self.data["window_locked"] = "True" if getattr(self, "is_locked", False) else "False"

        ui_settings = {
            "last_tab_idx": str(self.data["last_tab_idx"]),
            "active_temp_slot": str(self.active_temp_slot),
            "last_geometry": self.data.get("last_geometry", ""),
            "font_size": str(self.data.get("font_size", 11))
            if hasattr(self, "font_spin")
            else str(self.data.get("font_size", 11)),
            "font_family": str(self.data.get("font_family", "Verdana")),
            "preview_mode": (self.preview_combo.currentData() or self.preview_combo.currentText())
            if hasattr(self, "preview_combo")
            else self.data.get("preview_mode", "None"),
            "paste_mode": self.data.get("paste_mode", "Plain"),
            "tray_visible": str(self.cb_tray.isChecked())
            if getattr(self, "cb_tray", None) is not None
            else self.data.get("tray_visible", "True"),
            "close_on_focus_loss": str(self.cb_focus.isChecked())
            if getattr(self, "cb_focus", None) is not None
            else self.data.get("close_on_focus_loss", "True"),
            "ctrl_c_closes": str(self.cb_ctrl_c.isChecked())
            if getattr(self, "cb_ctrl_c", None) is not None
            else self.data.get("ctrl_c_closes", "True"),
            "silo_last_edited": getattr(self, "silo_last_edited", {}),
        }

        ok = bool(self.state.save_data_to_db(current_text, ui_settings,
                                              force=force, durable=durable))
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
            # settings changes (root/mode/topology maps) still do. PERF-002:
            # the mirror publishes NORMAL temp silos, so a snippet-only or
            # archive-only save must not trigger a capture either.
            if (force
                    or getattr(self.state, "last_save_had_temp_text", False)
                    or self._mirror_settings_dirty()):
                self.sync_to_disk()
            # PERF-004: Sync-Project / per-silo links publish silo text to disk
            # only when THIS save actually touched the NORMAL temp-silo domain,
            # or a forced save demands it. A settings-only persistence (font
            # size, geometry, a checkbox) must not traverse every bound file,
            # and a snippet-only or archive-only save must not re-digest
            # unrelated normal bindings (PERF-002). App-side text edits are
            # covered independently by the 1.5s typing debounce.
            if force:
                self._push_sync_files()
            elif getattr(self.state, "last_save_had_temp_text", False):
                cat = self.get_current_category() or ""
                slots = getattr(self.state, "last_save_temp_slots", {}).get(cat)
                self._push_sync_files(slots=slots)
        return ok

    def _queue_silo_text_history(self):
        """Diff every silo store against the last-committed snapshot and
        queue OLD->NEW transitions into the state layer (T-1227 §11).

        CORE-001: ownership is IDENTITY-based, never coordinate-based. The
        previous side pairs the COMMITTED slot rows with the COMMITTED
        identity mapping; the current side pairs the live rows with the live
        mapping; only a per-silo_id text difference becomes a transition. A
        structural reorder/insert/delete/swap/transfer that leaves a silo's
        text unchanged therefore queues ZERO transitions, instead of
        manufacturing cross-SILO before/after rows from the previous occupant
        of a new coordinate."""
        st = getattr(self, "state", None)
        if st is None or getattr(st, "conn", None) is None:
            return
        committed_ids = st.committed_silo_identities()
        if not committed_ids:
            return
        suppress = getattr(self, "_persistent_history_suppress_sid", None)
        cursors = getattr(self, "_persistent_history_cursor", None)
        for is_arc, all_key, saved in (
                (False, "temp_presets_all",
                 getattr(st, "_last_saved_temp", set()) or set()),
                (True, "archive_temp_presets_all",
                 getattr(st, "_last_saved_arc", set()) or set())):
            # previous committed text OWNED BY IDENTITY: the committed row's
            # text paired with the identity that owned that coordinate when
            # the row was committed.
            previous = {}
            for cat, i, content in saved:
                sid_prev = committed_ids.get((cat, 1 if is_arc else 0, int(i)))
                if sid_prev:
                    previous.setdefault(sid_prev, content or "")
            if not previous:
                continue
            for cat, slots in (self.data.get(all_key) or {}).items():
                for i, content in enumerate(slots[:100]):
                    content = content or ""
                    sid = st.silo_id_for(cat, is_arc, i)
                    if not sid:
                        continue
                    old = previous.get(sid)
                    if old is None or old == content:
                        # No committed predecessor for this identity (a newly
                        # created silo), or the identity's own text is
                        # unchanged: nothing to record. A deleted identity
                        # simply has no current row and never reaches here, so
                        # its history is retained without touching anybody
                        # else's timeline.
                        continue
                    if suppress is not None and sid == suppress:
                        # T-1227 §14: a persistent recovery replay — the
                        # transition is already in the timeline; do not
                        # append a reverse one.
                        continue
                    if cursors is not None and sid in cursors:
                        # T-1227 §15: a real commit after a persistent undo
                        # abandons the old redo branch — drop every transition
                        # AFTER the cursor's position in the same txn.
                        pos = cursors.pop(sid)
                        try:
                            timeline = st.silo_text_history_for(sid)
                            threshold = (timeline[pos - 1][0]
                                         if 0 < pos <= len(timeline) else 0)
                            st.truncate_silo_text_history_after(
                                sid, threshold)
                        except Exception:
                            pass
                    st.record_silo_text_history(
                        sid, old, content,
                        "committed-autosave" if not is_arc
                        else "committed-archive")

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
            text = self._editor_text_snapshot()
            if text is None:
                # T-1250: no snapshot, no scan. Skip this refresh and keep
                # the currently rendered underlines; an unreadable document
                # is not an empty one.
                return
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
        """Paint spans onto the live editor (GUI thread).

        T-1269 SPAN CONTRACT -- this is the single Python/Qt boundary for
        typo spans. The worker scans an immutable PYTHON snapshot and emits
        Unicode code-point spans; ``QTextDocument`` counts UTF-16 units, and
        the two diverge at the first non-BMP character, so a raw worker span
        used as a document position underlines, hit-tests and replaces the
        wrong range. The complete list is converted exactly ONCE, here,
        against the text the scan was accepted for (``_on_typo_scanned``
        proves the document revision has not moved). ``editor._typo_spans``
        holds QT offsets thereafter and every consumer is Qt-native.
        """
        editor = getattr(self, "text_area", None)
        if editor is not None and not sip.isdeleted(editor):
            if spans:
                from fastprompter.ui.qt_text_coords import (
                    convert_spans_py_to_qt,
                )
                spans = convert_spans_py_to_qt(editor.toPlainText(), spans)
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
        # T-1269: ``hit`` is a QT UTF-16 range, so the word is read through a
        # cursor. ``toPlainText()[start:end]`` would index a PYTHON string
        # with a document position and return a shifted word after any
        # non-BMP character earlier in the silo.
        word_cursor = self.text_area.textCursor()
        word_cursor.setPosition(start)
        word_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        word = word_cursor.selectedText()
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

    def _establish_sync_writer_barrier(self):
        """Quiesce and revoke every captured Sync-Project push intent.

        The worker and barrier share the final mutation gate. Returning from
        this method therefore means an already-entered physical write has
        finished, while every queued or in-flight old lease is stale.
        """
        gate = self._sync_commit_gate
        with gate:
            worker = getattr(self, "_push_worker", None)
            if worker is not None:
                worker._suppress = True
            pending = getattr(self, "_push_jobs_pending", {})
            leases = getattr(self, "_sync_leases", {})
            keys = set(leases) | set(pending)
            for key in keys:
                leases[key] = leases.get(key, 0) + 1
            pending.clear()
            timer = getattr(self, "_sync_push_timer", None)
            if timer is not None:
                timer.stop()

    def _resume_sync_push_after_restore_refusal(self):
        """Resume future captures after a refused restore; old leases stay stale."""
        with self._sync_commit_gate:
            worker = getattr(self, "_push_worker", None)
            if worker is not None:
                worker._suppress = False

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
                    text = self._editor_text_snapshot()
                    if text is None:
                        # T-1250/T-1030: the editor cannot currently be
                        # observed, so there is NO truthful text for the
                        # active binding -- neither "" nor the stale preset
                        # copy. Skip THIS binding for THIS round: no digest,
                        # no worker job, no baseline mutation, no file write.
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

    def _request_external_sync(self):
        """Capture watcher state and dispatch all filesystem reads off-thread."""
        self._sync_pending_apply = False
        changed = set(self._sync_changed_files)
        self._sync_changed_files = set()
        dir_changed = bool(self._sync_dir_changed)
        self._sync_dir_changed = False
        if not self._sync_config() and not (self.data.get("silo_links") or {}):
            return

        self._sync_pull_request_gen += 1
        request = {
            "gen": self._sync_pull_request_gen,
            "profile_id": getattr(getattr(self, "state", None),
                                  "profile_id", None),
            "category": self.get_current_category() or "",
            "root": self._sync_root(),
            "mapping": tuple((self.data.get("project_sync_map") or {}).items()),
            "links": tuple((self.data.get("silo_links") or {}).items()),
            "changed": changed,
            "dir_changed": dir_changed,
            "include": tuple(self._sync_include()),
            "exclude": tuple(self._sync_exclude()),
            "recursive": self._sync_recursive(),
            "max_bytes": self._sync_max_bytes(),
        }
        if self._sync_pull_inflight:
            prior = self._sync_pull_pending
            if (prior is not None
                    and prior["profile_id"] == request["profile_id"]
                    and prior["category"] == request["category"]
                    and prior["root"] == request["root"]):
                request["changed"].update(prior["changed"])
                request["dir_changed"] |= prior["dir_changed"]
            self._sync_pull_pending = request
            return
        self._dispatch_external_sync(request)

    def _dispatch_external_sync(self, request):
        import weakref

        from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

        if not hasattr(self, "_sync_pull_signals"):
            class Signals(QObject):
                loaded = pyqtSignal(object, object)

            self._sync_pull_signals = Signals()
            self._sync_pull_signals.loaded.connect(
                self._on_external_sync_collected)

        class Worker(QRunnable):
            def __init__(self, req, window_ref):
                super().__init__()
                self.request = req
                self.window_ref = window_ref

            def run(self):
                try:
                    result = _collect_sync_pull(self.request)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                window = self.window_ref()
                if window is None:
                    return
                from PyQt6 import sip
                if sip.isdeleted(window):
                    return
                try:
                    window._sync_pull_signals.loaded.emit(self.request, result)
                except RuntimeError:
                    pass

        self._sync_pull_inflight = True
        QThreadPool.globalInstance().start(Worker(request, weakref.ref(self)))

    def _on_external_sync_collected(self, request, result):
        """Apply a worker snapshot only while its logical owner is current."""
        self._sync_pull_inflight = False
        try:
            if "error" in result:
                from fastprompter.core.logging import logger
                logger.debug("external sync collection failed: %s",
                             result["error"])
            elif (request["gen"] == self._sync_pull_request_gen
                  and request["profile_id"]
                  == getattr(getattr(self, "state", None), "profile_id", None)
                  and request["category"] == (self.get_current_category() or "")
                  and request["root"] == self._sync_root()):
                self._apply_external_sync_collected(request, result)
        finally:
            pending = self._sync_pull_pending
            self._sync_pull_pending = None
            if pending is not None:
                self._dispatch_external_sync(pending)

    def _requeue_stale_sync(self, paths, dir_level=False):
        """W2-001: bounded async retry for rejected stale observations.

        Rejected rows go back through the EXISTING 350 ms apply debounce
        (``_sync_apply_timer``) instead of being applied, so:

        * no blocking read ever moves onto the GUI thread — the retry is a
          normal asynchronous pull that re-observes the current generation;
        * repeated stale completions coalesce into ONE follow-up pull, so a
          continuously-rewritten file cannot create a redispatch storm;
        * at most the newest pending request follows an in-flight one
          (``_sync_pull_pending``), so coalescing is preserved.
        """
        if getattr(self, "_sync_shutting_down", False):
            return
        changed = getattr(self, "_sync_changed_files", None)
        if changed is None:
            return
        if dir_level:
            # A superseded discovery needs the O(project) enumeration pass;
            # a superseded mapped/link read only needs its own path re-read.
            self._sync_dir_changed = True
        for path in paths:
            if isinstance(path, str) and path:
                changed.add(os.path.normcase(path))
        if getattr(self, "_sync_pending_apply", False):
            return  # a pull is already queued and will carry these paths
        self._sync_pending_apply = True
        timer = getattr(self, "_sync_apply_timer", None)
        if timer is not None:
            timer.start()

    def _apply_external_sync_collected(self, request, result):
        """Commit a disk-free watcher result to current in-memory UI state.

        W2-001: the worker result is an OBSERVATION, never authorization for
        an irreversible binding mutation. Each filesystem-derived row is
        re-validated here with ONE cheap ``stat`` (never a read):

        * a mapped ``missing`` whose path is back keeps its binding (W2-003)
          and re-reads the CURRENT generation instead of detaching identity;
        * a mapped/link ``read`` whose generation moved on is dropped — stale
          text is never applied to a silo;
        * a discovered file whose generation moved on (or vanished) is never
          bound, so no free slot is allocated from a stale snapshot.

        Everything rejected is requeued through ``_requeue_stale_sync`` and
        converges on the next asynchronous pull.
        """
        from fastprompter.core import project_sync as ps

        presets = self._ensure_temp_presets()
        active = getattr(self, "active_temp_slot", -1)
        editing_snippet = getattr(self, "editing_snippet", None)
        applied: dict[int, str] = {}
        mapping_changed = False
        mapping = self.data.setdefault("project_sync_map", {})
        stale_paths: list[str] = []
        stale_discovery = False

        for slot_key, rel, path, status, read, ident in result["mapped"]:
            if mapping.get(slot_key) != rel:
                continue
            try:
                slot = int(slot_key)
            except (TypeError, ValueError):
                continue
            if status == "invalid":
                # A corrupt/escaping mapping is not a filesystem fact: drop
                # it exactly as before (the silo text stays).
                mapping.pop(slot_key, None)
                mapping_changed = True
                continue
            if status == "missing":
                if path and os.path.exists(path):
                    # W2-001: transient delete/recreate. The absence is
                    # already stale, so retain the stable binding and let a
                    # fresh pull read the current text.
                    stale_paths.append(path)
                    continue
                mapping.pop(slot_key, None)
                mapping_changed = True
                if path:
                    self._sync_invalidate_binding(slot, path)
                continue
            if read is None:
                continue
            text, eol, had_bom = read
            if path and _sync_stat_identity(path) != ident:
                stale_paths.append(path)
                continue
            key = self._sync_baseline_key(slot, path)
            self._sync_bom_cache[key] = had_bom
            self._apply_external_change(
                slot, path, text, eol, presets, active,
                editing_snippet, applied)

        mapped_paths = set(mapping.values())
        # Validate discovery BEFORE allocating slots: a superseded observation
        # must not consume a free slot or claim an identity.
        new_rows = []
        for rel, path, read, ident in result["new"]:
            if read is None or rel in mapped_paths:
                continue
            if _sync_stat_identity(path) != ident:
                stale_discovery = True
                continue
            new_rows.append((rel, path, read))
        if new_rows:
            slots = ps.free_slots(mapping, len(presets), len(new_rows))
            for (rel, path, read), slot in zip(new_rows, slots):
                if rel in mapped_paths:
                    continue
                text, eol, had_bom = read
                while len(presets) <= slot:
                    presets.append("")
                presets[slot] = text
                mapping[str(slot)] = rel
                mapped_paths.add(rel)
                key = self._sync_baseline_key(slot, path)
                self._sync_eol_cache[key] = eol
                self._sync_bom_cache[key] = had_bom
                self._sync_last_applied[key] = self._sync_side_digest(text)
                applied[slot] = text

        links = self.data.get("silo_links") or {}
        for slot_key, path, status, read, ident in result["links"]:
            if status != "read" or read is None or links.get(slot_key) != path:
                continue
            try:
                slot = int(slot_key)
            except (TypeError, ValueError):
                continue
            if _sync_stat_identity(path) != ident:
                stale_paths.append(path)
                continue
            text, eol, had_bom = read
            key = self._sync_baseline_key(slot, path)
            self._sync_bom_cache[key] = had_bom
            self._apply_external_change(
                slot, path, text, eol, presets, active,
                editing_snippet, applied)

        if stale_paths or stale_discovery:
            self._requeue_stale_sync(stale_paths, dir_level=stale_discovery)

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
        # Keep the whole logical binding available for rollback until the
        # authoritative SQLite save accepts the new root and mappings.
        old_binding = {
            "project_sync": copy.deepcopy(self.data.get("project_sync")),
            "project_sync_all": copy.deepcopy(
                self.data.get("project_sync_all", {})),
            "project_sync_map": copy.deepcopy(
                self.data.get("project_sync_map", {})),
            "project_sync_map_all": copy.deepcopy(
                self.data.get("project_sync_map_all", {})),
            "presets": list(self._ensure_temp_presets()),
            "eol": dict(self._sync_eol_cache),
            "bom": dict(self._sync_bom_cache),
            "applied": dict(self._sync_last_applied),
            "unsafe": set(self._sync_unsafe_bindings),
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
        try:
            committed = self.save_data_to_db(force=True)
        except Exception:
            committed = False
        if not committed:
            if old_binding["project_sync"] is None:
                self.data.pop("project_sync", None)
            else:
                self.data["project_sync"] = old_binding["project_sync"]
            restored_configs = old_binding["project_sync_all"]
            if old_binding["project_sync"] is not None:
                restored_configs[cat] = old_binding["project_sync"]
            self.data["project_sync_all"] = restored_configs
            restored_maps = old_binding["project_sync_map_all"]
            restored_maps[cat] = old_binding["project_sync_map"]
            self.data["project_sync_map_all"] = restored_maps
            self.data["project_sync_map"] = old_binding["project_sync_map"]
            presets[:] = old_binding["presets"]
            for cache_name, old_values in (
                    ("_sync_eol_cache", old_binding["eol"]),
                    ("_sync_bom_cache", old_binding["bom"]),
                    ("_sync_last_applied", old_binding["applied"])):
                cache = getattr(self, cache_name)
                cache.clear()
                cache.update(old_values)
            self._sync_unsafe_bindings.clear()
            self._sync_unsafe_bindings.update(old_binding["unsafe"])
            self._push_jobs_pending.clear()
            from fastprompter.core.logging import logger as _log
            _log.error("Sync-Project folder rebind was not committed; "
                       "restored the previous in-memory binding")
            QMessageBox.critical(
                self, tr("Sync-Project", lang),
                tr("Sync-Project folder change was NOT saved — the previous "
                   "folder binding stays in force. Nothing was changed.",
                   lang))
            try:
                self._push_sync_files()
            except Exception:
                _log.exception("could not recapture pushes for the restored "
                               "Sync-Project binding")
            return
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
            mapping = self.data.setdefault("project_sync_map", {})
            # PERF-001: discovery is bounded to the ACTUAL slot demand. Only
            # K free slots can become new bindings, so scanning/sorting the
            # whole tree is O(N) waste; a bounded scan keeps the
            # lexicographically smallest K eligible paths (O(N log K), O(K)
            # memory).
            presets = self._ensure_temp_presets()
            free_count = max(0, 100 - len(mapping))
            files = ps.scan_folder(
                root, self._sync_include(), self._sync_exclude(),
                recursive=self._sync_recursive(),
                max_bytes=self._sync_max_bytes(),
                limit=free_count if free_count > 0 else 100)
            # W2-003: existing bindings are classified separately from new-file
            # discovery. `files` only contains CURRENTLY syncable entries — a
            # file that is temporarily over max_bytes, caught mid-write as
            # binary, or hitting a transient stat/read failure is omitted, but
            # it is NOT physically deleted. Removing the mapping for it would
            # detach the silo and reassign it a new identity when it becomes
            # valid again. An existing mapping is dropped only when the
            # physical file is genuinely absent.
            for key in list(mapping.keys()):
                rel = mapping[key]
                path = ps.resolve_relative_path(root, rel)
                if os.path.isfile(path) if path is not None else False:
                    # still physically present — retain the binding (it may be
                    # temporarily unsyncable; that is handled elsewhere by
                    # holding/suspending, never by unlink)
                    continue
                mapping.pop(key, None)
                if path is not None:
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

    def _ensure_settings_built(self):
        if getattr(self, "_settings_built", False):
            return
        self._settings_built = True
        from fastprompter.ui.settings_builder import build_settings_tabs
        build_settings_tabs(self)

    def init_ui(self):
        import time
        _t_hdr_0 = time.perf_counter()
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
        self.header_widget.setMinimumSize(0, 0)
        self.header_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.header_layout = QHBoxLayout(self.header_widget)
        # The toolbar resolver, not QLayout's aggregate child minimum, owns
        # horizontal fitting.  Without this, a Wide set can impose a 1500+ px
        # window floor and Qt never delivers the narrow resize from which the
        # responsive policy would hide/overflow AUTO controls.
        self.header_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetNoConstraint)
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
        # QComboBox owns a separate popup viewport.  Its default right-click
        # handling may move the popup's current row before our context menu is
        # shown, which makes merely asking for the menu open another project.
        # Intercept that viewport just like the number buttons below.
        self._cat_combo_popup_view = self.cat_combo.view().viewport()
        self._cat_combo_popup_view.installEventFilter(self)

        self.cat_numbox = QWidget()
        # A grid, not a row: the project cap is 100, and 100 boxes in one
        # QHBoxLayout is ~2200px of header that simply runs off the window.
        # Wraps every `numbox_per_row` buttons instead (user-configurable).
        from PyQt6.QtWidgets import QGridLayout
        self._cat_numbox_layout = QGridLayout(self.cat_numbox)
        self._cat_numbox_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_numbox_layout.setSpacing(1)
        self._cat_num_buttons: list[QPushButton] = []
        from fastprompter.ui.project_numbox_reorder import (
            install_project_numbox_reorder,
        )
        install_project_numbox_reorder(self)
        numbox_on = self.data.get("numbox_tabs", "False") == "True"
        if numbox_on:
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

        self.cat_combo.setVisible(not numbox_on)
        self.cat_numbox.setVisible(numbox_on)

        self.btn_new = QPushButton(tr("NEW", getattr(self, "_current_lang", "EN")))
        self.btn_new.setToolTip(
            tr("NEW ({})", self._current_lang).format(self.data.get('hk_new_snippet', 'Ctrl+N'))
            + "\n" + tr("Right-click: new silo at the bottom", self._current_lang)
            + "\n" + tr("Ctrl+Alt+click: new child silo", self._current_lang))
        self.apply_button_size(self.btn_new, 24)
        def _on_btn_new_clicked():
            mods = QApplication.keyboardModifiers()
            child_mods = (Qt.KeyboardModifier.ControlModifier
                          | Qt.KeyboardModifier.AltModifier)
            if (mods & child_mods) == child_mods and not getattr(self, "active_is_archive", False):
                self._create_child_silo_for_current()
                return
            self.select_empty_silo(insertion=None)

        self.btn_new.clicked.connect(_on_btn_new_clicked)
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



        self.btn_settings_toggle = _SettingsGearButton()
        self.apply_button_size(self.btn_settings_toggle, 24, 24)
        self.btn_settings_toggle.setToolTip(tr(
            "Settings\nConfigure hotkeys, theme, fonts, and UI scaling.", getattr(self, "_current_lang", "EN")))
        self.btn_settings_toggle.clicked.connect(self.toggle_mini_settings)

        self.btn_settings_toggle_right = _SettingsGearButton()
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

        # AI usage gauges: one bar per quota window (5h, weekly, or whatever
        # the plan reports) per provider account, filled bottom-up by
        # remaining percent. Provider-neutral; driven by UsageLimitService.
        # Hidden unless master enabled.
        from fastprompter.core.usage_limits.service import UsageLimitService
        from fastprompter.ui.limit_gauges import LimitGauges
        self.limit_service = UsageLimitService(self.data, discover=False)
        # Test/preview windows and short-lived secondary instances may be
        # destroyed without the process-wide _shutdown_application path.
        # Retire their Python workers with the QObject; the closure retains
        # only the service, never the window.
        self.destroyed.connect(
            lambda _obj=None, service=self.limit_service: service.shutdown())
        # ``destroyed`` alone is not enough: a window that is merely closed, or
        # held by a module-scoped test fixture, never emits it, and the probe
        # children then outlive the interpreter. Tie the service to the
        # application lifetime as well — shutdown is idempotent, so both hooks
        # plus _shutdown_application may all fire.
        _qapp = QApplication.instance()
        if _qapp is not None:
            _qapp.aboutToQuit.connect(
                lambda service=self.limit_service: service.shutdown())
        self.limit_gauges = LimitGauges(self, self.limit_service)
        self.limit_gauges.setToolTip(tr(
            "AI usage limits (remaining quota per window)\nClick to refresh",
            getattr(self, "_current_lang", "EN")))
        self.header_layout.addWidget(self.limit_gauges)

        # Minutes until the soonest quota reset, right beside the gauges.
        # Hidden until gauges are enabled and a reset time is known.
        self.lbl_limit_timer = QLabel("")
        self.lbl_limit_timer.setStyleSheet("padding: 0 4px; font-weight: bold;")
        self.lbl_limit_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_limit_timer.mousePressEvent = lambda _e: (
            hasattr(self, "open_limit_settings_dialog") and self.open_limit_settings_dialog())
        self.lbl_limit_timer._en_tooltip = "Soonest AI limit reset"
        self.lbl_limit_timer.setToolTip(tr(
            self.lbl_limit_timer._en_tooltip, self._current_lang))
        # T-1279: the queue opens in the EXISTING LimitHoverCard, not a
        # native tooltip and not a second hover system. The card is created
        # lazily on first hover so the header build stays cheap.
        self._reset_hover_card = None
        self._reset_queue_html = ""
        self.lbl_limit_timer.enterEvent = (
            lambda _e: self._show_reset_hover_card())
        self.lbl_limit_timer.leaveEvent = (
            lambda _e: self._hide_reset_hover_card())
        self.lbl_limit_timer.setVisible(False)
        self.header_layout.addWidget(self.lbl_limit_timer)

        # Status label for the Clock settings group — shows account count or
        # error so the user knows whether the gauges found anything.
        self.lbl_limit_status = QLabel("")
        self._apply_limit_hint_style(self.lbl_limit_status)
        self.lbl_limit_status.setVisible(False)
        self.limit_gauges._result_ready.connect(self._update_limit_status)
        self.limit_gauges._result_ready.connect(
            self._check_limit_notifications)
        self.limit_gauges._result_ready.connect(
            self._update_limit_timer_label)

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
        self._counter_sep.setFixedSize(8, 16)
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
        # Rendering has an 8pt readability floor; exposing 6/7 here made the
        # control claim one value while the editor correctly rendered another.
        self.font_spin.setRange(8, 48)
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

        def make_action_checkbox(text, callback, fixed_w=None, sound=True):
            btn = QPushButton(text)

            def run():
                if sound:
                    self.play_tick_sound()
                callback()

            btn.clicked.connect(run)
            btn._en_text = text
            if fixed_w is not None:
                btn.is_squishable = True
                btn.setFixedWidth(fixed_w)
            return btn

        self.btn_hotkeys = make_action_checkbox("Keys", self.open_hotkey_settings, fixed_w=32)
        self.btn_hotkeys.setToolTip(tr("Configure Global Hotkeys (Settings Cog)", getattr(self, "_current_lang", "EN")))
        self.btn_colors = make_action_checkbox("RGB", self.open_color_settings, fixed_w=30)
        self.btn_colors.setToolTip(tr("Custom Theme Colors (Color Palette)", getattr(self, "_current_lang", "EN")))
        self.btn_backup = make_action_checkbox("BkUp", self.backup_db, fixed_w=32)
        self.btn_backup.setToolTip(tr("Backup the database", getattr(self, "_current_lang", "EN")))
        self.btn_restore = make_action_checkbox("Rstr", self.restore_db, fixed_w=32)
        self.btn_restore.setToolTip(tr("Restore the database from a backup", getattr(self, "_current_lang", "EN")))
        self.btn_exit = make_action_checkbox(
            "Exit", self.quit_app, fixed_w=32, sound=False)
        self.btn_exit.setToolTip(tr("Exit FastPrompter (Ctrl+Alt+Shift+Q)\nSave all data and quit application.", getattr(self, "_current_lang", "EN")))

        try:
            current_scale_pct = int(float(self.data.get("ui_scale", "0.5")) * 100)
        except Exception:
            current_scale_pct = 100
        self.btn_button_scale = make_action_checkbox(
            f"{current_scale_pct}%", self.cycle_button_scale, fixed_w=44
        )
        self.btn_button_scale.setToolTip(tr(
            "Scale the whole program: 50 / 75 / 100 / 125 / 150%\n"
            "(fine-tune with Ctrl+Plus / Ctrl+Minus)", getattr(self, "_current_lang", "EN"))
        )

        # Load custom font button
        self.btn_load_font = QPushButton("+")
        self.btn_load_font.is_squishable = True
        self.btn_load_font.setFixedWidth(20)
        self.btn_load_font.setToolTip(tr("Load a custom .ttf/.otf font file", getattr(self, "_current_lang", "EN")))
        self.btn_load_font.clicked.connect(self.load_custom_font)

        self.btn_clear_fonts = QPushButton("↺")
        self.btn_clear_fonts.is_squishable = True
        self.btn_clear_fonts.setFixedWidth(20)
        self.btn_clear_fonts.setToolTip(tr("Clear all custom fonts from combo (reset to defaults)", getattr(self, "_current_lang", "EN")))
        self.btn_clear_fonts.clicked.connect(self.clear_custom_fonts)

        self.font_combo.setMaximumWidth(105)
        self.font_spin.setFixedWidth(42)
        self.cb_theme.setMaximumWidth(125)
        self.preview_combo.setMaximumWidth(100)

        # Volume slider
        self.spin_volume = QSlider(Qt.Orientation.Horizontal)
        self.spin_volume.setRange(0, 100)
        try:
            vol = _parse_volume_value(self.data.get("sound_volume", "0.15"))
            if vol is None:
                vol = 0.15
            self.spin_volume.setValue(max(0, min(100, int(round(vol * 100)))))
        except Exception:
            self.spin_volume.setValue(15)
        self.spin_volume.setFixedWidth(100)
        self.spin_volume.setToolTip(tr("Global volume (0-100)", getattr(self, "_current_lang", "EN")))
        self.spin_volume.valueChanged.connect(
            lambda v: (self.data.update({"sound_volume": f"{v/100:.2f}"}), self.mark_dirty())
        )

        # --- Settings panel: hidden by default, toggled by the gear button. ---
        # Top bar: appearance & global actions organized in 4 compact clusters.
        # Fits on a single row on wide screens, wraps into balanced spacious rows on compact screens.
        self.btn_drop_zones = make_action_checkbox("Zones", self.open_drop_zones_settings, fixed_w=48)
        self.btn_drop_zones.setToolTip(tr("Customize Drop Zones", getattr(self, "_current_lang", "EN")))

        self.cb_language = QComboBox()
        self.cb_language.setMaximumWidth(105)
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

        for btn, min_w in ((self.btn_colors, 38), (self.btn_drop_zones, 48), (self.btn_hotkeys, 42),
                           (self.btn_backup, 44), (self.btn_restore, 42), (self.btn_exit, 40)):
            btn.setMinimumWidth(min_w)
            btn.setStyleSheet("padding: 2px 5px;")

        class _ClusterWidget(QWidget):
            def sizeHint(self):
                w = 0
                lay = self.layout()
                if lay is not None:
                    for i in range(lay.count()):
                        item = lay.itemAt(i)
                        wid = item.widget() if item is not None else None
                        if wid is not None:
                            if isinstance(wid, QLabel):
                                cw = wid.fontMetrics().horizontalAdvance(wid.text()) + 4
                            else:
                                cw = min(wid.sizeHint().width(), wid.maximumWidth())
                            w += cw
                    if lay.count() > 1:
                        w += (lay.count() - 1) * lay.spacing()
                    margins = lay.contentsMargins()
                    w += margins.left() + margins.right()
                return QSize(w, super().sizeHint().height())

        def _make_cluster(items):
            box = _ClusterWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            for it in items:
                lay.addWidget(it)
            return box

        _lbl_font = QLabel(tr("Font:", getattr(self, "_current_lang", "EN")))
        _lbl_font._en_text = "Font:"
        _lbl_font.setFixedWidth(_lbl_font.fontMetrics().horizontalAdvance(_lbl_font.text()) + 4)
        cluster_font = _make_cluster([
            _lbl_font, self.font_combo, self.font_spin,
            self.btn_load_font, self.btn_clear_fonts
        ])

        _lbl_theme = QLabel(tr("Theme:", getattr(self, "_current_lang", "EN")))
        _lbl_theme._en_text = "Theme:"
        _lbl_theme.setFixedWidth(_lbl_theme.fontMetrics().horizontalAdvance(_lbl_theme.text()) + 4)
        cluster_theme = _make_cluster([
            _lbl_theme, self.cb_theme, self.btn_colors, self.btn_drop_zones
        ])

        _lbl_view = QLabel(tr("View:", getattr(self, "_current_lang", "EN")))
        _lbl_view._en_text = "View:"
        _lbl_view.setFixedWidth(_lbl_view.fontMetrics().horizontalAdvance(_lbl_view.text()) + 4)
        cluster_view = _make_cluster([
            _lbl_view, self.preview_combo, self.btn_button_scale
        ])

        cluster_system = _make_cluster([
            self.cb_language, self.btn_hotkeys, self.btn_backup,
            self.btn_restore, self.btn_exit
        ])

        self._appearance_items = [cluster_font, cluster_theme, cluster_view, cluster_system]

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setDocumentMode(True)
        self.settings_tabs.setSizePolicy(QSizePolicy.Policy.Preferred,
                                         QSizePolicy.Policy.Maximum)
        self._settings_tab_titles = SETTINGS_TAB_TITLES
        self._tab_placeholders = []
        for _t in self._settings_tab_titles:
            _p = _SettingsPage()
            self._tab_placeholders.append(_p)
            self.settings_tabs.addTab(_p, tr(_t, self._current_lang))
        self.settings_tabs.currentChanged.connect(self._fit_settings_tabs)
        self.settings_tabs.currentChanged.connect(self._play_settings_tab_sound)

        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFrameShadow(QFrame.Shadow.Sunken)

        v_layout = QVBoxLayout(self.mini_settings_frame)
        v_layout.setContentsMargins(4, 2, 4, 3)
        v_layout.setSpacing(3)
        from fastprompter.ui.flow_layout import flow_widget
        v_layout.addWidget(flow_widget(self._appearance_items, h_spacing=3, v_spacing=2))
        v_layout.addWidget(hline)
        v_layout.addWidget(self.settings_tabs)

        self._settings_built = False
        orig_set_visible = self.mini_settings_frame.setVisible
        def _settings_frame_set_visible(visible):
            if visible and not getattr(self, "_settings_built", False):
                self._ensure_settings_built()
            was_visible = self.mini_settings_frame.isVisible()
            orig_set_visible(visible)
            # T-1245: the settings surface transitions hidden -> visible --
            # exactly once per real opening. Internal refresh of a hidden
            # frame, relayout and retranslation never pass through here
            # with visible=False -> True.
            if visible and not was_visible:
                from fastprompter.ui.appearance_sounds import emit_settings_show
                emit_settings_show(self)
        self.mini_settings_frame.setVisible = _settings_frame_set_visible

        # Hidden by default — the gear button reveals it. If already opened,
        # make frame visible immediately but defer building 270+ child widgets
        # to the next event-loop tick so startup time and theming are not blocked.
        if self.data.get("hide_extra", "True") != "True":
            orig_set_visible(True)
            QTimer.singleShot(50, weak_qt_callback(self, lambda w: w._ensure_settings_built()))
        else:
            self.mini_settings_frame.setVisible(False)

        # Hug the content: spare vertical space belongs to the editor below,
        # not to a settings panel showing one row of checkboxes.
        self.mini_settings_frame.setSizePolicy(QSizePolicy.Policy.Preferred,
                                               QSizePolicy.Policy.Maximum)
        self.main_layout.addWidget(self.mini_settings_frame)
        self._startup_timings["4_header_settings"] = (time.perf_counter() - _t_hdr_0) * 1000.0
        _t_sb_0 = time.perf_counter()
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
        self.btn_page_up.setVisible(False)
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
        self.btn_page_down.setVisible(False)
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
        self.btn_arc_page_up.setVisible(False)
        self.btn_arc_page_up.clicked.connect(lambda: self.change_arc_page(-1))
        self.archive_section_layout.addWidget(self.btn_arc_page_up)

        self.archive_widget = SiloDropWidget(self, is_archive=True)
        self.archive_buttons = []
        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        if saved_arc_visible:
            initial_arc = max(1, min(50, getattr(self, "_visible_silos", 10)))
            for _ in range(initial_arc):
                btn = DraggableSiloButton(self, is_archive=True)
                btn.setMinimumHeight(14)
                btn.hide()
                self.archive_widget.layout.addWidget(btn)
                self.archive_buttons.append(btn)
        self.archive_section_layout.addWidget(self.archive_widget)

        self.btn_arc_page_down = QPushButton("▼")
        self.apply_button_size(self.btn_arc_page_down, 16)
        self.btn_arc_page_down.setVisible(False)
        self.btn_arc_page_down.clicked.connect(lambda: self.change_arc_page(1))
        self.archive_section_layout.addWidget(self.btn_arc_page_down)

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
        initial_silos = max(1, min(50, getattr(self, "_visible_silos", 10)))
        for _ in range(initial_silos):
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

        self._startup_timings["5_sidebar"] = (time.perf_counter() - _t_sb_0) * 1000.0
        _t_ed_0 = time.perf_counter()
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
        # Category-scoped document cache.  A project switch must not throw
        # away every QTextDocument and make the next A -> B -> A navigation a
        # cold load again.  Keep a small bounded set so this cannot become a
        # RAM graveyard when a user has many projects.
        self._category_document_cache = {}
        self._document_fingerprint_cache = {}
        self._document_cache_limit = 4
        self._document_cache_char_limit = 4_000_000
        self._line_count_cache = {}
        self._LARGE_DOC_BLOCK_THRESHOLD = 2_000

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

        self._startup_timings["6_editor_highlighter_construction"] = (time.perf_counter() - _t_ed_0) * 1000.0
        _t_kt_0 = time.perf_counter()
        self.kanban_widget = None
        self.table_widget = None
        self._kanban_placeholder = QWidget()
        self._table_placeholder = QWidget()
        self.silo_view.addWidget(self._kanban_placeholder) # page 1
        self.silo_view.addWidget(self._table_placeholder)  # page 2
        self._startup_timings["7_kanban_table_construction"] = (time.perf_counter() - _t_kt_0) * 1000.0

        # the page has to be re-picked when the TEXT stops matching the type,
        # not only when the silo is switched
        self.text_area.textChanged.connect(self._schedule_silo_type_recheck)

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
        QTimer.singleShot(0, weak_qt_callback(
            self, lambda window: window._deferred_silo_refresh()))
        # a files sidebar left open is part of the layout the user left
        if (self.files_docked()
                and self.data.get("files_dock_open", "False") == "True"):
            QTimer.singleShot(0, weak_qt_callback(
                self, lambda window: window.open_file_container()))
        self.change_preview_mode(self.preview_combo.currentIndex())
        self.on_tray_toggled(self.data.get("tray_visible", "True") == "True")
        self.set_lock_state(self.data.get("window_locked", "False") == "True")
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
            switched = self.state.switch_profile(idx + 1, save_current=False)
            if not switched:
                # W6 (P0-003): State refused the switch (e.g. a pre-switch
                # save failed). Roll back the watcher quiesce and keep A
                # fully active — no irreversible detach/rebind occurs.
                from fastprompter.core.logging import logger as _plog
                _plog.warning(
                    "profile switch refused by State; old profile kept active")
                if getattr(self, "_watcher_quiesced_for_switch", False):
                    try:
                        self._watcher_rollback_quiesce()
                    except Exception:
                        pass
                    self._watcher_quiesced_for_switch = False
                return
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

        # Runtime documents and all metadata derived from them belong to the
        # old profile. Category/slot names are not a profile identity.
        self._reset_profile_document_caches()
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

    def _apply_profile_runtime_state(self, initial: bool = False):
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
        self.timers = load_timers(data.get("timers"))
        self.prompt_queues = {}
        self.productivity_timer = ProductivityTimer.from_dict(
            data.get("productivity_timer"))
        self._pomo_last_tick = None
        self._pomo_alarm_replay_at = None

        # -- persisted undo for THIS profile --------------------------------
        self._undo_kinds().clear()
        self._load_undo_state()

        # -- sound ownership -------------------------------------------------
        self.sound_manager._data = data
        self.sound_manager.invalidate_cache()
        from fastprompter.core.sound_manager import migrate_sound_settings
        migrate_sound_settings(data, self.sound_manager._sounds_dir)
        # The global Overlay/Stack/Replace setting is profile state, so the
        # new profile's value must reach the hub here.  Problip itself is
        # APPLICATION-global and is deliberately NOT rebound: switching
        # profiles must never restart it or reset its statistics (C1.4).
        self.sound_manager.reload_playback_mode()
        # T-1244: the master mute is profile state too.  reload_playback_mode
        # re-reads audio_global_muted into the hub, so a switch to a muted
        # profile mutes immediately and a switch away releases the stale
        # mute — no Settings dialog interaction required.
        self._sync_audio_mute_state()
        # T-1242 spec B11: the two render-policy switches are ALSO profile
        # state.  Without this, module globals kept the old profile's policy
        # alive after a switch and an explicit pad=True in the new profile
        # never reached the runtime.  apply_device_render_setting() clamps
        # pad to render (spec B5) and invalidates the transport pool (spec B7)
        # when the policy actually changes.
        self.sound_manager.apply_device_render_setting()

        # -- language --------------------------------------------------------
        self._current_lang = get_language(data)
        self._apply_tooltips()
        self._retranslate_preview_combo(self._current_lang)
        self._apply_settings_language()
        # T-1244 A3: _sync_audio_mute_state() ran BEFORE the new profile's
        # language was assigned above, so the dynamic MUTED / SOUND ON label
        # was rendered in the OLD language.  Re-sync now that both the mute
        # state and the language are the destination profile's.
        self._sync_audio_mute_state()

        # -- persisted widget values -> widgets ------------------------------
        self._resync_profile_widgets()

        # -- font / theme ----------------------------------------------------
        self.apply_font()
        if not initial:
            self.apply_theme()

        # -- hotkeys: the old profile's native registrations must die --------
        self.unregister_all_hotkeys()
        self.register_all_hotkeys()

        # -- watcher: fail closed; do NOT auto-arm ----------------------------
        # Observe mode is a separate loop from arming: disarming only stops the
        # SEND engine, it does NOT stop an in-progress Observe. Switching
        # profiles must stop BOTH so a Profile-A adapter/probes/timer cannot
        # survive into Profile B (W-09/P1). No auto-restart in the new profile.
        if hasattr(self, "watcher_disarm"):
            self.watcher_disarm("profile switch")

        # -- profile-scoped runtime state -------------------------------------
        # The missed-event alert, the typecheck dictionary cache and the
        # sync "last applied" baselines all belong to ONE profile's data;
        # the sync watcher paths are re-derived from the new profile's
        # active category below. Guarded: at startup this runs BEFORE the
        # attributes are created (they are made at the end of __init__).
        if hasattr(self, "_missed_timer_ids"):
            self._load_missed_ids()
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
            ("cb_static_cursor", "static_cursor", "False"),
            ("cb_focus", "close_on_focus_loss", "True"),
            ("cb_tray_activate", "tray_click_activates", "True"),
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
            ("cb_date_daypart", "date_daypart", profile_default("date_daypart")),
            ("cb_date_emoji", "date_emoji", profile_default("date_emoji")),
            ("cb_date_text_month", "date_text_month", "False"),
            ("cb_date_ampm", "date_ampm", "False"),
            ("cb_limit_gauges", "limit_gauges", "False"),
            ("cb_sound", "sound_ui", "True"),
            ("cb_typewriter", "sound_typewriter", "False"),
            ("cb_audio_mute", "audio_global_muted", "False"),
            ("cb_trash_vision", "trash_vision", "False"),
            ("cb_silo_color_box", "silo_color_box", "False"),
            ("cb_new_silo_paste_clipboard", "new_silo_paste_clipboard", "False"),
            ("cb_silo_random_color_on_new", "silo_random_color_on_new", "False"),
            ("cb_cs_style", "cs_style", "False"),
            ("cb_typo_check", "typo_check_enabled", "False"),
            ("cb_passed_alert", "passed_alert_enabled", "True"),
            ("cb_sync_recursive", "sync_recursive", "True"),
            ("cb_sync_live", "sync_live_watch", "True"),
        )
        if getattr(self, "_settings_built", False):
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
        self.on_tray_toggled(data.get("tray_visible", "True") == "True")
        self.toggle_aot(data.get("always_on_top", "True") == "True")
        self.set_lock_state(data.get("window_locked", "False") == "True")
        self.apply_window_flags()
        self.toggle_sidebar_position(data.get("sidebar_right", "False") == "True")
        self.on_wrap_toggled(data.get("word_wrap", "True") == "True")
        self.set_line_numbers(data.get("show_line_numbers", "False") == "True")
        self._toggle_numbox_mode(data.get("numbox_tabs", "False") == "True")
        self.apply_toolbar_position(data.get("toolbar_position", "top") == "bottom")
        self._on_files_dock_toggled(data.get("file_panel_docked", "False") == "True")
        self.on_lock_cursor_toggled(data.get("lock_to_cursor", "False") == "True")
        self.on_silo_home_toggled(data.get("silo_home", "False") == "True")
        self.on_customize_toolbar_toggled(
            data.get("customize_toolbar", "False") == "True")
        # Custom cursors: apply SILENTLY (the toggle handler can pop a modal
        # capture dialog — not allowed during a programmatic switch).
        if hasattr(self, "apply_custom_cursors"):
            self.apply_custom_cursors()   # re-applies the static override too
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
            time_str = f"{daypart} {ts}" if profile_flag(self.data, "date_daypart") else ts

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

    def _widgets_with_english_source(self, widget_type, prefix):
        """Every widget of `widget_type` this window owns that can be retranslated.

        Deliberately a superset of the two ways such a widget can be
        reachable: parented anywhere under the window, or held only as a
        `self.<prefix>*` attribute. Whichever route a future widget arrives
        by, it gets retranslated without anybody having to remember to add
        its name to a list — which is what the two hand-typed tuples this
        replaced could not do. Carrying `_en_text` is the real contract, so
        that is what gets asked for.
        """
        seen = {}
        for widget in self.findChildren(widget_type):
            if not sip.isdeleted(widget):
                seen[id(widget)] = widget
        for source in (dir(type(self)), vars(self)):
            for name in list(source):
                if not name.startswith(prefix):
                    continue
                widget = getattr(self, name, None)
                if isinstance(widget, widget_type) and not sip.isdeleted(widget):
                    seen.setdefault(id(widget), widget)
        return list(seen.values())

    def _translatable_checkboxes(self):
        return self._widgets_with_english_source(QCheckBox, "cb_")

    def _translatable_buttons(self):
        return self._widgets_with_english_source(QPushButton, "btn_")

    def _apply_settings_language(self):
        """Re-apply translations to all settings widgets."""
        lang = self._current_lang
        # Translate every settings QLabel that carries its English source in
        # `_en_text` (group headers + the `_tr_label` static labels). The base
        # is ALWAYS the stamped English, never the current display text: reading
        # the base off the widget is a one-way trip, because no reverse map can
        # turn Arabic or Japanese back into the English key, so the label would
        # stay stuck in the previous language forever. Unstamped labels carry
        # dynamic text (counts, paths) and are left alone.
        for child in self.mini_settings_frame.findChildren(QLabel):
            en = getattr(child, "_en_text", None)
            if en:
                child.setText(tr(en, lang))

        # The Window/Editor/Clock/Data tab titles are translated once, when the
        # tabs are built, and were never touched again — the same one-way trip
        # the labels above used to take, one level up. `_settings_tab_titles`
        # already holds the English source, so drive the retranslation off that.
        tabs = getattr(self, "settings_tabs", None)
        if tabs is not None and not sip.isdeleted(tabs):
            titles = getattr(self, "_settings_tab_titles", ())
            for i, en_title in enumerate(titles):
                if i < tabs.count():
                    tabs.setTabText(i, tr(en_title, lang))

        # The Problip page owns combo items and composed status strings that
        # no generic sweep can see; it retranslates those itself.
        page = getattr(self, "problip_page", None)
        if page is not None:
            try:
                page.retranslate(lang)
            except Exception:
                from fastprompter.core.logging import logger as _logger

                _logger.debug("Problip retranslation failed", exc_info=True)

        # Every checkbox that remembers its English source.
        #
        # This used to be a hand-typed tuple of 38 attribute names. A list like
        # that only records which checkboxes existed on the day someone last
        # remembered to edit it: add a thirty-ninth and it is silently
        # untranslatable in all 32 languages, with nothing anywhere going red.
        # `_en_text` is the actual contract, so find the widgets that carry it.
        for cb in self._translatable_checkboxes():
            en_text = getattr(cb, "_en_text", None)
            if en_text:
                cb.setText(tr(en_text, lang))
            en_tip = getattr(cb, "_en_tooltip", None)
            if en_tip:
                cb.setToolTip(tr(en_tip, lang))

        # Translate action buttons
        # Same story as the checkboxes: this was eight hand-typed names, and
        # `btn_exit_app` and `btn_sound_settings` both carry `_en_text` and
        # were both absent from it — so the Data tab kept two English buttons
        # in every other language, forever, with nothing to notice it.
        for ac in self._translatable_buttons():
            en_text = getattr(ac, "_en_text", None)
            if en_text:
                ac.setText(tr(en_text, lang))
            en_tip = getattr(ac, "_en_tooltip", None)
            if en_tip:
                ac.setToolTip(tr(en_tip, lang))

        # Translate button_scale text (compact percentage)
        if hasattr(self, "btn_button_scale") and not sip.isdeleted(self.btn_button_scale):
            try:
                pct = int(float(self.data.get("ui_scale", "0.5")) * 100)
            except Exception:
                pct = 100
            self.btn_button_scale.setText(f"{pct}%")

        # (The static-label pass that used to live here reverse-mapped the
        # visible text through the Russian dictionary. It could not recover any
        # other script, and it duplicated the `_en_text` pass above, which now
        # covers Font:/Theme:/View: and every `_tr_label` in the settings tabs.)

        # T-1244 A3: the master-mute MUTED / SOUND ON label is dynamic state,
        # not a static `_en_text` widget — the generic checkbox/label sweeps
        # above never touch it.  It re-derives its text from the live mute
        # state in the ACTIVE language, so a language or profile switch can
        # never leave it stale.
        self._sync_audio_mute_state()

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
            self.spin_volume.setToolTip(tr("Global volume (0-100)", lang))

        # Translate files_row buttons
        if hasattr(self, "btn_files_root") and not sip.isdeleted(self.btn_files_root):
            # the same key the builder used ("…", not "...")
            self.btn_files_root.setText(tr("Files Folder…", lang))
            self.btn_files_root.setToolTip(
                tr("Choose where silo file containers are stored.\nDefault: data/files next to the app.", lang))

        # Translate preview combo items from their English base (itemData),
        # never from the current — possibly already-translated — display text.
        if hasattr(self, "preview_combo") and not sip.isdeleted(self.preview_combo):
            self._retranslate_preview_combo(lang)
            self.preview_combo.setToolTip(
                tr("Source View: Plain text editor\nLive Preview: Editor with live markdown highlights (default)\nReading: Read-only rendered markdown view", lang))

        # The image-viewer caption is composed ("🖼 " + mode word), so it has
        # no static `_en_text`; the builder leaves its composer behind.
        viewer_caption = getattr(self, "_image_viewer_caption", None)
        btn_viewer = getattr(self, "btn_image_viewer", None)
        if (viewer_caption and btn_viewer is not None
                and not sip.isdeleted(btn_viewer)):
            btn_viewer.setText(f"🖼 {viewer_caption()}")

        # Translate _day_part used in _update_date_label
        self._update_date_label()
        lbl_timer = getattr(self, "lbl_limit_timer", None)
        if lbl_timer is not None and not sip.isdeleted(lbl_timer):
            desc = getattr(lbl_timer, "_en_tooltip", "") or "Soonest AI limit reset"
            lbl_timer.setToolTip(tr(desc, lang))

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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))

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
        if not self._durable_undo_or_refuse("Swap temp slots"):
            return
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
        # T-1227: re-stamp after the swap (see move_temp_to_index).
        self._rebind_silo_document_owners()
        self._stamp_active_document_owner()
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
        ("silo_last_edited", "int_dict"),
        ("pinned_silos", "int_list"),
        ("silo_ticked", "int_list"),
        # Ctrl+click multi-selection: a latched FOCUS set that persists, so it
        # must follow its silos through reorder/insert/delete exactly like the
        # pins and ticks beside it.
        ("silo_selected", "int_list"),
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
    _ARCHIVE_INDEX_STATE = (
        ("archive_silo_folders", "str_dict", "numeric"),
        ("archive_project_paths", "str_dict", "numeric"),
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
        return self._category_slot_has_state(self.get_current_category(), idx, is_archive)

    def _category_slot_has_state(self, category, idx, is_archive=False):
        """Registry-owned slot state, without switching the active category."""
        from fastprompter.core.state import _PER_CATEGORY_ALIASES
        aliases = dict(_PER_CATEGORY_ALIASES)
        aliases["silo_last_edited"] = "silo_last_edited_all"
        table = self._ARCHIVE_INDEX_STATE if is_archive else self._SILO_INDEX_STATE
        for entry in table:
            key, kind = entry[0], entry[1]
            ns = entry[2] if len(entry) > 2 else "numeric"
            if category == self.get_current_category():
                container = getattr(self, key, None) if key == "silo_last_edited" else self.data.get(key)
            else:
                container = self.data.get(aliases[key], {}).get(category)
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
                if idx in container or str(idx) in container:
                    return True
                for kids in container.values():
                    if isinstance(kids, (list, tuple)) and (idx in kids or str(idx) in kids):
                        return True
        view = self.data.get("silo_view_state_all")
        if isinstance(view, dict):
            cat = category
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
        return self._acquire_silo_slot_for_category(
            self.get_current_category(), is_archive, allow_reuse_empty)

    def _acquire_silo_slot_for_category(self, category, is_archive=False, allow_reuse_empty=True):
        """Read-only reservation shared by active and cross-project insertions."""
        key = "archive_temp_presets" if is_archive else "temp_presets"
        presets = (self.data.get(key) if category == self.get_current_category()
                   else self.data.get(key + "_all", {}).get(category, []))
        if not isinstance(presets, list):
            return None
        if allow_reuse_empty:
            for i, p in enumerate(presets):
                if i >= self.MAX_SILOS_PER_CATEGORY:
                    break
                if not (p or "").strip() and not self._category_slot_has_state(category, i, is_archive):
                    return i
        for i in range(len(presets), self.MAX_SILOS_PER_CATEGORY):
            if not self._category_slot_has_state(category, i, is_archive):
                return i
        return None

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
        # T-1227: the deleted slot's identity anchor leaves with it, BEFORE
        # the down-shift remap runs (no collision with its successor).
        try:
            self.state.remap_silo_identities(
                self.get_current_category(), is_archive, lambda i: i,
                drop=(idx,))
        except Exception:
            pass

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
            selected = self.data.get("silo_selected", [])
            if isinstance(selected, list) and idx in selected:
                selected.remove(idx)
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
            # The live selection SET is what the UI reads; the remapped list is
            # what persists. Reload the set from it so a reorder moves the
            # highlight with its silos instead of leaving it on a stranger.
            self._silo_selection_source = None

        self._remap_silo_view_state(remap, is_archive=is_archive)
        # T-1227: identity anchors travel WITH their silos across reorder,
        # swap and insert. Only the active (category, space) namespace moves.
        try:
            self.state.remap_silo_identities(
                self.get_current_category(), is_archive, remap)
        except Exception:
            pass

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

        Since T-1270 the pinned list is not just metadata: it IS the leading
        raw block. Every commit therefore re-applies that block, so the drag
        reorder survives a reload and the drop-outside case (which pulls a
        silo back out of the pinned zone) leaves the raw order consistent too.
        """
        pinned = self._slot_list("pinned_silos")

        def commit(changed):
            if changed:
                self._apply_pinned_block(pinned)
                return True
            return False

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
                return commit(True)
            return False

        if source_idx in pinned:
            pinned.remove(source_idx)
            return commit(True)
        return False

    def move_temp_to_index(self, from_idx, to_idx, is_archive=False):
        """Move a silo to a new position, shifting the others (drop 'between' silos)."""
        temps = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if not (0 <= from_idx < len(temps)):
            return
        to_idx = max(0, min(len(temps) - 1, to_idx))
        if from_idx == to_idx:
            return
        if not self._durable_undo_or_refuse("Move silo"):
            return
        self._relocate_silo_slot(from_idx, to_idx, is_archive=is_archive)

    def _relocate_silo_slot(self, from_idx, to_idx, is_archive=False):
        """Apply the raw-order permutation for one silo move — NO undo record.

        Callers that own an undoable transaction (``move_temp_to_index``, the
        pin/unpin contract) call this after publishing their own before-state,
        so one user gesture stays ONE Ctrl+Z. It carries the full remap +
        document-owner rebound, because the slot index is the identity key of
        every per-silo store.
        """
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
        # T-1227: index order changed — every materialized document gets a
        # fresh owner stamp; the visible document must never keep the old one.
        self._rebind_silo_document_owners()
        self._stamp_active_document_owner()
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
        if getattr(self, "cb_top", None) is not None:
            self.data["always_on_top"] = "True" if self.cb_top.isChecked() else "False"
        if getattr(self, "cb_normal_window", None) is not None:
            self.data["normal_window"] = "True" if self.cb_normal_window.isChecked() else "False"
        flags = Qt.WindowType.Window
        normal = (
            self.cb_normal_window.isChecked()
            if getattr(self, "cb_normal_window", None) is not None
            else (self.data.get("normal_window", "False") == "True")
        )
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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
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
        """Move a preset after destination admission; rollback both owners on failure."""
        source_silo = from_cat in ("silo", "arcsilo")
        target_silo = to_cat in ("silo", "arcsilo")
        source_arc, target_arc = from_cat == "arcsilo", to_cat == "arcsilo"
        cats = self.data.get("categories", {})
        if source_silo:
            self._flush_transfer_source_if_live(from_idx, source_arc)
            source = self.data["archive_temp_presets" if source_arc else "temp_presets"]
        else:
            if from_cat not in cats:
                return
            if self.editing_snippet == (from_cat, from_idx):
                self.commit_current_text()
                self._cache_timer.stop()
            source = cats[from_cat]
        if not 0 <= from_idx < len(source):
            return
        item = source[from_idx]
        text = item if source_silo else (item or {}).get("text", "")
        if not str(text or "").strip():
            return
        if target_silo:
            dest = self.data["archive_temp_presets" if target_arc else "temp_presets"]
            slot = self._acquire_silo_slot(target_arc)
            if slot is None:
                return
        else:
            if to_cat not in cats or None not in cats[to_cat]:
                return
            dest = cats[to_cat]
            slot = to_idx if 0 <= to_idx < len(dest) and dest[to_idx] is None else dest.index(None)
        if not 0 <= to_idx <= len(dest):
            return
        if from_cat == to_cat:
            if source_silo:
                return self.move_temp_to_index(from_idx, to_idx, source_arc)
            return
        # Snippets cannot own attachment directories. Refuse conversion with
        # real assets before deleting any source identity or publishing a slot.
        if source_silo and not target_silo:
            folders = self.data.get("archive_silo_folders" if source_arc else "silo_folders", {})
            if str(from_idx) in folders:
                path = self._silo_folder_dir(from_idx, is_archive=source_arc)
                if path is not None and os.path.isdir(path):
                    return
        live_source = ((source_silo and not self.editing_snippet
                        and self.active_temp_slot == from_idx and self.active_is_archive == source_arc)
                       or self.editing_snippet == (from_cat, from_idx))
        before = copy.deepcopy(self.data)
        stacks = (list(self.data_undo_stack), list(self.data_redo_stack), list(self._undo_kinds()))
        docs_before = (list(self.silo_docs), list(self.archive_docs), dict(self.snippet_docs))
        owner = (self.active_temp_slot, self.active_is_archive, self.editing_snippet)
        identity = {}
        view = self.data.get("silo_view_state_all", {}).get(self.get_current_category(), {})
        view_key = f"{'a' if source_arc else 's'}{from_idx}"
        saved_view = copy.deepcopy(view.get(view_key))
        if source_silo:
            for normal, archive in (("silo_folders", "archive_silo_folders"),
                                    ("silo_project_paths", "archive_project_paths")):
                identity[normal] = self.data.get(archive if source_arc else normal, {}).get(str(from_idx))
        try:
            self.add_data_undo_state("Move preset cross category")
            if target_silo:
                # Preserve requested insertion placement while below capacity;
                # a full target can only reuse the canonical pristine slot.
                reuse = len(dest) >= self.MAX_SILOS_PER_CATEGORY
                if not reuse:
                    slot = to_idx
                    self.open_silo_slot(slot, is_archive=target_arc)
                    dest.insert(slot, text)
                else:
                    dest[slot] = text
                target_docs = self.archive_docs if target_arc else self.silo_docs
                doc = QTextDocument()
                doc.setDefaultFont(self.text_area.font())
                doc.setPlainText(text)
                if reuse:
                    target_docs.extend([None] * max(0, slot + 1 - len(target_docs)))
                    target_docs[slot] = doc
                else:
                    target_docs.insert(slot, doc)
                for normal, archive in (("silo_folders", "archive_silo_folders"),
                                        ("silo_project_paths", "archive_project_paths")):
                    if identity.get(normal) is not None:
                        self.data[archive if target_arc else normal][str(slot)] = identity[normal]
                if saved_view is not None:
                    view[f"{'a' if target_arc else 's'}{slot}"] = saved_view
            else:
                dest[slot] = ({"name": text[:22], "text": text, "last_edited": int(time.time())}
                              if source_silo else copy.deepcopy(item))
            if source_silo:
                source.pop(from_idx)
                source_docs = self.archive_docs if source_arc else self.silo_docs
                if from_idx < len(source_docs):
                    source_docs.pop(from_idx)
                self.drop_silo_state(from_idx, is_archive=source_arc)
                if not live_source and not self.editing_snippet and self.active_is_archive == source_arc:
                    if self.active_temp_slot > from_idx:
                        self.active_temp_slot -= 1
            else:
                source.pop(from_idx)
                source.append(None)
                self._remap_snippet_owner(from_cat, lambda i: None if i == from_idx else i - 1 if i > from_idx else i)
            if live_source:
                if target_silo:
                    self.editing_snippet = None
                    self.active_temp_slot, self.active_is_archive = slot, target_arc
                    self.text_area.setDocument(target_docs[slot])
                else:
                    self.editing_snippet = (to_cat, slot)
                    self.snippet_docs[f"{to_cat}_{slot}"] = self.text_area.document()
            self._trim_archive()
            self.mark_dirty()
            self.refresh_snippets_panel()
            self.refresh_temp_presets()
            self.refresh_archive_panel()
            # Slot refresh may synthesize a folder name from text.  Restore
            # transferred identity after UI synchronization so it remains
            # attached to the logical silo.
            if target_silo:
                target_folders = self.data[
                    "archive_silo_folders" if target_arc else "silo_folders"
                ]
                target_projects = self.data[
                    "archive_project_paths" if target_arc else "silo_project_paths"
                ]
                for normal, target_map in (
                    ("silo_folders", target_folders),
                    ("silo_project_paths", target_projects),
                ):
                    if identity.get(normal) is not None:
                        target_map[str(slot)] = identity[normal]
            return True
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("Preset transfer failed; restoring both owners")
            self._restore_transfer_data(self.data, before)
            self.data_undo_stack[:], self.data_redo_stack[:], self._undo_kinds()[:] = stacks
            self.silo_docs[:], self.archive_docs[:] = docs_before[:2]
            self.snippet_docs.clear()
            self.snippet_docs.update(docs_before[2])
            self.active_temp_slot, self.active_is_archive, self.editing_snippet = owner
            return False

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
        if not self._durable_undo_or_refuse("Swap cross temp slots"):
            return
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

        def _swap_between(source_map, source_key, target_map, target_key):
            if not isinstance(source_map, dict) or not isinstance(target_map, dict):
                return
            if source_map is target_map:
                if source_key in source_map or target_key in target_map:
                    s_val = source_map.pop(source_key, None)
                    t_val = source_map.pop(target_key, None)
                    if t_val is not None:
                        source_map[source_key] = t_val
                    if s_val is not None:
                        target_map[target_key] = s_val
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

        # T-1227: cross-space swap moved documents BETWEEN lists — re-stamp
        # both spaces so no document keeps a pre-swap owner identity.
        try:
            self.state.swap_silo_identities(
                self.get_current_category(),
                (source_is_archive, source_idx),
                (target_is_archive, target_idx))
        except Exception:
            pass
        self._rebind_silo_document_owners()
        self._stamp_active_document_owner()
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
        try:
            threshold = int(getattr(self, "_LARGE_DOC_THRESHOLD", 500000))
        except (AttributeError, TypeError, ValueError):
            threshold = 500000
        if doc.characterCount() >= threshold:
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
        try:
            threshold = int(getattr(self, "_LARGE_DOC_THRESHOLD", 500000))
        except (AttributeError, TypeError, ValueError):
            threshold = 500000
        if doc.characterCount() >= threshold:
            return
        centered = set(centered)
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
        QTimer.singleShot(300, weak_qt_callback(
            self, lambda w: w._decrement_focus_lock()))

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
            # The latched Ctrl+click selection is persisted slot-index state
            # like the ticks, so a delete/undo must restore the same silos as
            # selected instead of leaving the highlight one slot off.
            "silo_selected": list(self.data.get("silo_selected", [])),
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
        if state.get("_compact") is not None:
            return self._compact_snapshot_is_valid(state)
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
        # W2-003: composite physical records optionally bind to a canonical
        # files-root identity. If present it must be a non-empty string;
        # a malformed owner identity is quarantined.
        if (state.get("_transfer") or state.get("_merge_ledger")):
            fr = state.get("_fs_root")
            if fr is not None and not (isinstance(fr, str) and fr):
                return False
        return True

    def _compact_snapshot_is_valid(self, state):
        # Compact records intentionally omit the full data snapshot fields.
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
            elif self._persistent_text_step(forward=False):
                # T-1227 §14: native Qt history is gone (typically after a
                # restart) — recover the committed predecessor from the
                # persistent silo history, keyed by the immutable silo_id.
                kinds.append("ptext")
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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
            # The lock only stops the HIDE; it does not stop Windows from
            # dropping the window to the back of the z-order. Re-assert the
            # foreground right away (the rebuild is synchronous, so any
            # deactivation it caused has already landed) and again after the
            # lock releases, to cover any straggler event still in the queue.
            self._bring_to_front()
            QTimer.singleShot(320, weak_qt_callback(
                self, type(self)._bring_to_front))

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
            if kind == "ptext":
                # T-1227 §14: replay the persistent-history recovery step.
                if self._persistent_text_step(forward=True):
                    self.play_sound("redo")
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
            if self._persistent_text_step(forward=True):
                self.play_sound("redo")
                return
            self.statusBar().showMessage(tr("Nothing to redo", getattr(self, "_current_lang", "EN")), 2000)
        finally:
            self._in_smart_redo = False
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))
            # Same z-order fix as _smart_undo: a data redo rebuilds the lists
            # and can drop the window behind others. Keep it on top.
            self._bring_to_front()
            QTimer.singleShot(320, weak_qt_callback(
                self, type(self)._bring_to_front))

    def _active_silo_id(self):
        """The immutable silo_id of the active silo, or None (snippet mode,
        no state, or a not-yet-loaded identity anchor). T-1227 §14: recovery
        is keyed by identity, never by content or raw slot number."""
        st = getattr(self, "state", None)
        if st is None or getattr(self, "editing_snippet", None):
            return None
        try:
            cat = self.get_current_category()
            is_arc = bool(getattr(self, "active_is_archive", False))
            slot = int(self.active_temp_slot)
        except Exception:
            return None
        sid = st.silo_id_for(cat, is_arc, slot)
        if not sid or str(sid).startswith("pending::"):
            return None
        return sid

    @staticmethod
    def _persistent_history_state_at(hist, pos):
        """The committed text at timeline position ``pos``: 0 = the very
        first BEFORE, k = the AFTER of transition k-1."""
        if pos <= 0:
            return hist[0][1]
        return hist[pos - 1][2]

    def _persistent_history_locate(self, hist, text):
        """The newest timeline position whose text equals ``text`` (or None
        when the live text is not on the recorded timeline at all)."""
        for pos in range(len(hist), -1, -1):
            if self._persistent_history_state_at(hist, pos) == text:
                return pos
        return None

    def _silo_lineage_is_trustworthy(self, sid):
        """Refuse persistent recovery when identity and text disagree.

        Persistent Ctrl+Z looks up a timeline BY IDENTITY and writes the
        result into whatever slot that identity currently points at. If a
        structural route ever moved a silo without moving its identity, that
        makes the recovery feature write one silo's history into another --
        the single worst outcome available here, because it is the mechanism
        the user reaches for precisely when they have already lost something.

        So the cheap cross-check runs first, and on any disagreement the step
        is refused rather than guessed at. Native in-session undo is
        unaffected; only the persistent fallback is gated.
        """
        st = getattr(self, "state", None)
        if st is None or not hasattr(st, "validate_silo_lineage"):
            return True
        # The active silo is legitimately dirty whenever the user has typed
        # since the last commit, so it is exempt from the comparison.
        dirty = ()
        try:
            slot = int(getattr(self, "active_temp_slot", -1))
            if slot >= 0:
                dirty = ((self.get_current_category(),
                          bool(getattr(self, "active_is_archive", False)),
                          slot),)
        except (TypeError, ValueError, AttributeError):
            dirty = ()
        try:
            problems = st.validate_silo_lineage(dirty_slots=dirty)
        except Exception:
            from fastprompter.core.logging import logger as _lg
            _lg.exception("silo lineage validation raised; refusing "
                          "persistent recovery for safety")
            return False
        mine = [p for p in problems if p["silo_id"] == sid]
        if not mine:
            return True
        from fastprompter.core.logging import logger as _lg
        _lg.critical(
            "T-1236 SILO_LINEAGE_MISMATCH: silo_id=%s maps to "
            "category=%r space=%s slot=%s whose text hashes %s, but its "
            "newest committed transition ended at %s. Persistent undo/redo "
            "REFUSED for this silo; a structural route very likely moved the "
            "text without moving the identity anchor.",
            sid, mine[0]["category"],
            "archive" if mine[0]["is_archive"] else "normal",
            mine[0]["slot"], mine[0]["actual_hash"][:12],
            mine[0]["expected_after_hash"][:12])
        return False

    def _persistent_text_step(self, forward):
        """T-1227 §14/§15: one coarse committed-text undo/redo step from the
        persistent silo history. Returns True when the live text moved.

        The persistent timeline is treated as a forensic, append-only record;
        a recovery step does NOT append a reverse transition (the caller's
        forced save suppresses it), so repeated Ctrl+Z walks the timeline
        backwards instead of ping-ponging. A real committed edit clears the
        cursor for that silo, which discards the redo branch (§15)."""
        sid = self._active_silo_id()
        if not sid:
            return False
        st = getattr(self, "state", None)
        if not self._silo_lineage_is_trustworthy(sid):
            return False
        hist = st.silo_text_history_for(sid) if st is not None else []
        if not hist:
            return False
        cur = self._editor_text_snapshot()
        if cur is None:
            return False
        cursors = getattr(self, "_persistent_history_cursor", None)
        if cursors is None:
            cursors = self._persistent_history_cursor = {}
        pos = cursors.get(sid)
        if pos is None:
            pos = self._persistent_history_locate(hist, cur)
            if pos is None:
                return False
        new_pos = pos + 1 if forward else pos - 1
        if new_pos < 0 or new_pos > len(hist):
            return False
        target = self._persistent_history_state_at(hist, new_pos)
        if target == cur:
            return False
        if not self._apply_persistent_text(sid, target):
            return False
        cursors[sid] = new_pos
        return True

    def _apply_persistent_text(self, sid, text):
        """Publish one persistent-recovery text step to the active silo.

        The change is a recovery replay of an already-recorded transition, so
        the history queue is suppressed for THIS silo during the forced save;
        the authoritative content still commits atomically."""
        ta = getattr(self, "text_area", None)
        if ta is None:
            return False
        is_arc = bool(getattr(self, "active_is_archive", False))
        key = "archive_temp_presets" if is_arc else "temp_presets"
        slots = self.data.get(key) or []
        slot = int(self.active_temp_slot)
        if not 0 <= slot < len(slots):
            return False
        old_text = ta.toPlainText()
        old_slot_text = slots[slot]
        self._persistent_history_suppress_sid = sid
        try:
            was_suspend = getattr(self, "_suspend_temp_sync", False)
            self._suspend_temp_sync = True
            try:
                ta.setPlainText(text)
            finally:
                self._suspend_temp_sync = was_suspend
            slots[slot] = text
            self.mark_dirty("arc" if is_arc else "temp")
            if not self.save_data_to_db(force=True):
                raise RuntimeError("persistent text publication was refused")
            return True
        except Exception:
            slots[slot] = old_slot_text
            was_suspend = getattr(self, "_suspend_temp_sync", False)
            self._suspend_temp_sync = True
            try:
                ta.setPlainText(old_text)
            finally:
                self._suspend_temp_sync = was_suspend
            from fastprompter.core.logging import logger
            logger.warning("persistent text recovery was not committed; "
                           "the prior live value remains authoritative",
                           exc_info=True)
            return False
        finally:
            self._persistent_history_suppress_sid = None

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
            finally:
                self._composite_applying = False
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
                    "category": now["category"],
                    "active_temp_slot": now["active_temp_slot"],
                    "active_is_archive": now.get("active_is_archive", False),
                })
            else:
                redo_state = self._stamp_snapshot(now)
                if state.get("_transfer"):
                    redo_state = self._inverse_transfer_snapshot(state, now)
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

            _trim_snapshot_stack(self.data_redo_stack)
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
            finally:
                self._composite_applying = False
            if state.get("_transfer"):
                undo_state = self._inverse_transfer_snapshot(state, undo_state)
            self.data_undo_stack.append(undo_state)
            self.play_sound("redo")
            self._last_data_action_time = undo_state["_seq"]
            self._save_undo_state()
            return True
        # Text redo is handled natively by QTextEdit via VaultTextEdit.keyPressEvent
        return False

    def _inverse_transfer_snapshot(self, state, fallback):
        """Invert both category halves, independent of the currently viewed tab."""
        inverse = copy.deepcopy(state.get("_transfer_src_after") or fallback)
        inverse["_transfer"] = True
        inverse["_transfer_dst_cat"] = state["_transfer_dst_cat"]
        inverse["_transfer_dst_before"] = copy.deepcopy(state.get("_transfer_dst_after") or {})
        inverse["_transfer_dst_after"] = copy.deepcopy(state["_transfer_dst_before"])
        inverse["_transfer_src_after"] = self._snapshot_current()
        inverse["_fs_root"] = state.get("_fs_root")
        folder = state.get("_transfer_folder")
        inverse["_transfer_folder"] = ((folder[1], folder[0], folder[3], folder[2]) if folder else None)
        return self._stamp_snapshot(inverse)

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
        # W2-003: the physical half is bound to the files-root identity it was
        # captured against. If the Files Folder was re-rooted since, these
        # coordinates are stale and MUST NOT mutate the abandoned old root.
        recorded_root = state.get("_fs_root")
        if recorded_root:
            try:
                cur_root = os.path.abspath(self._files_root())
            except Exception:
                cur_root = None
            if cur_root is not None and os.path.normcase(recorded_root) != os.path.normcase(cur_root):
                raise _TransactionRefused(
                    "composite filesystem history belongs to a different "
                    "Files Folder; refusing to mutate the old root")
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
            # W2-002: VALIDATE the entire inverse plan before mutating
            # anything. A collision on any later pair must refuse the WHOLE
            # reversal with every file untouched, never a partial split.
            pending = []
            for pair in reversed(ledger):
                if not (isinstance(pair, (tuple, list)) and len(pair) == 2):
                    continue
                orig, pub = pair[0], pair[1]
                if not os.path.lexists(pub):
                    continue          # nothing landed / already reverted
                if os.path.lexists(orig):
                    raise _TransactionRefused(
                        f"merge undo collision: {orig} already exists")
                pending.append((orig, pub))
            applied = []
            try:
                for orig, pub in pending:
                    os.makedirs(os.path.dirname(orig), exist_ok=True)
                    os.rename(pub, orig)
                    applied.append((orig, pub))
            except OSError as e:
                # compensate already-applied renames back to their pre-call
                # orientation so the reversal is all-or-nothing
                for orig, pub in reversed(applied):
                    try:
                        os.rename(orig, pub)
                    except OSError:
                        # compensation itself failed: leave a durable trace —
                        # the ledger stays in the persisted undo record, so a
                        # retry can reconcile the remaining split
                        pass
                raise _TransactionRefused(
                    f"merge undo {pub} -> {orig} failed and was "
                    f"compensated: {e}")
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
        self._composite_applying = True
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
            # `is not None`: a snapshot written before this store existed has
            # no such key, and clearing on a missing key would silently drop
            # the user's current selection during an unrelated undo.
            saved_selected = state.get("silo_selected")
            if saved_selected is not None:
                slist = self.data.setdefault(
                    "silo_selected_all", {}).setdefault(snap_cat, [])
                slist[:] = [i for i in saved_selected
                            if isinstance(i, int) and i >= 0]
                self.data["silo_selected"] = slist
                self._silo_selection_source = None
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
        # T-1227: a snapshot restore can reorder/shrink BOTH document lists —
        # re-stamp every owner before anything flushes again.
        self._rebind_silo_document_owners()
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
        # Identity BEFORE the order mutation: rebuild_cat_combo re-selects the
        # project by name, so a settings toggle never throws the user back to
        # row 0 the way build_categories() (profile boot) does.
        keep = self.get_current_category()
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
        self.rebuild_cat_combo(keep=keep)

    def on_sound_toggled(self, checked):
        """Handle UI sound toggle."""
        self.data["sound_ui"] = "True" if checked else "False"
        self.mark_dirty()

    def on_typewriter_toggled(self, checked):
        """Handle typewriter sound toggle."""
        self.data["sound_typewriter"] = "True" if checked else "False"
        self.mark_dirty()

    def on_audio_mute_toggled(self, checked):
        """T-1244 master mute toggle (settings checkbox and hotkey path).

        Both entry points land here so the persisted state, the settings
        checkbox and the hotkey-visible state can never disagree about what
        ON means.  Required order: persist -> physically stop existing audio
        (set_master_muted flips the hub state AND silences the legacy
        transport) -> resync UI -> emit exactly ONE confirmation cue through
        the play_mute_cue escape hatch, the sole route audible while muted.
        """
        self.data["audio_global_muted"] = "True" if checked else "False"
        self.mark_dirty()
        self.sound_manager.set_master_muted(checked)
        self._sync_audio_mute_state()
        self.sound_manager.play_mute_cue(
            "audio_mute_on" if checked else "audio_mute_off")

    def toggle_audio_mute(self):
        """Ctrl+M-style hotkey: flip the master mute and show the result."""
        self.on_audio_mute_toggled(
            self.data.get("audio_global_muted", "False") != "True")

    def _sync_audio_mute_state(self):
        """Push the persisted mute state into the settings checkbox + the
        footer label, so pressing the hotkey is visible without opening
        settings (T-1244 "state visible in UI")."""
        muted = self.data.get("audio_global_muted", "False") == "True"
        cb = getattr(self, "cb_audio_mute", None)
        if cb is not None and cb.isChecked() != muted:
            # Signal-block: we ARE the source of truth here, echoing back
            # through the checkbox signal would call the toggle twice.
            with QSignalBlocker(cb):
                cb.setChecked(muted)
        lbl = getattr(self, "audio_mute_state_label", None)
        if lbl is not None:
            lbl.setText(tr("MUTED" if muted else "SOUND ON",
                           self._current_lang))

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

    def _save_undo_state(self, merge_journal_root=None):
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
            # CORE-007: a merge journal may only be cleared once the undo
            # snapshot that durably represents its ledger has been published.
            # The root rides on the pending job and is actioned by the writer
            # after a successful os.replace.
            "merge_journal_root": merge_journal_root,
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
            from fastprompter.utils.path_safety import unique_temp_path
            tmp_path = unique_temp_path(undo_path, "undo")

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
            else:
                # CORE-007: the snapshot that carries the merge ledger has now
                # been durably published (its os.replace landed). ONLY now may
                # the write-ahead merge journal be cleared — a crash earlier
                # left it intact so startup reconciliation could reverse any
                # half-applied moves.
                mj_root = (job or {}).get("merge_journal_root")
                if mj_root:
                    try:
                        from fastprompter.ui.snippet_ops_mixin import _merge_journal_clear
                        _merge_journal_clear(mj_root)
                    except Exception:
                        from fastprompter.core.logging import logger
                        logger.exception(
                            "merge journal clear after durable undo failed")
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
        # T-1227 §16: never restart the process-local action sequence below
        # persisted sequences, or Ctrl+Z would route to an old structural
        # snapshot over a newer committed text revision. Narrow unification
        # for SILO operations: the sequence is seeded from the newest of
        # (structural undo/redo snapshots, persistent text history).
        try:
            persisted = 0
            for snap in (list(self.data_undo_stack) + list(self.data_redo_stack)):
                if isinstance(snap, dict):
                    try:
                        persisted = max(persisted, int(snap.get("_seq", 0) or 0))
                    except (TypeError, ValueError):
                        pass
            st = getattr(self, "state", None)
            if st is not None:
                persisted = max(persisted,
                                int(st.latest_silo_history_seq()))
            self._action_seq = max(getattr(self, "_action_seq", 0), persisted)
        except Exception:
            pass

    def add_data_undo_state(self, _action_name="", durable=False):
        """Push a before-state snapshot of the current data.

        Returns the pushed snapshot, or None when the new state equals the
        top of the stack and nothing was pushed (dedup). `_switch_to_slot`
        uses the return value to re-stamp its "Switch silo" entry against
        the document it lands on; callers that do not care may ignore it.

        T-1227 §17: ``durable=True`` publishes the BEFORE snapshot
        SYNCHRONOUSLY before the caller mutates anything, so a destructive
        silo action (delete/move/swap/insert/archive) can never become
        irreversible by a crash — a publish failure returns None and the
        caller must abort."""
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
            if durable:
                # §17: the identical top IS the before-state — make sure it
                # is on disk before the destructive mutation runs.
                self._dispatch_undo_save()
                if not self._wait_for_undo_saves(timeout_s=2.0):
                    from fastprompter.core.logging import logger
                    logger.error(
                        "durable undo-before publication FAILED for %r "
                        "(dedup); refusing the destructive silo operation",
                        _action_name)
                    return None
                return self.data_undo_stack[-1]
            return None
        self._stamp_snapshot(state)
        self.data_undo_stack.append(state)
        self._push_undo_state(state, _action_name)
        if durable:
            # §17: the before-state must be ON DISK before the destructive
            # mutation is allowed to run. Synchronous drain + bounded wait;
            # failure => None so the caller refuses the operation.
            self._dispatch_undo_save()
            if not self._wait_for_undo_saves(timeout_s=2.0):
                from fastprompter.core.logging import logger
                logger.error(
                    "durable undo-before publication FAILED for %r; "
                    "refusing the destructive silo operation",
                    _action_name)
                try:
                    self.data_undo_stack.remove(state)
                except ValueError:
                    pass
                return None
        return state

    def _durable_undo_or_refuse(self, action_name):
        """T-1227 §17: publish the BEFORE-state durably, then return True.

        Returns False (the destructive operation MUST be refused) when the
        snapshot could not be written to disk, so no irreversible mutation
        ever runs without a persisted way back."""
        if self.add_data_undo_state(action_name, durable=True) is None:
            from fastprompter.core.logging import logger
            logger.error(
                "%s REFUSED: durable undo-before publication failed",
                action_name)
            return False
        return True

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
        _trim_snapshot_stack(self.data_undo_stack)
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
            btn.is_squishable = True
            btn.setProperty("fp_numbox", "true")
            idx = i
            btn.clicked.connect(lambda _c, n=idx: self._cat_numbox_clicked(n))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, n=idx: self._cat_numbox_context(n, pos))
            # Drag-to-reorder in box mode: the filter is installed on the
            # container once, but the buttons are recreated every rebuild so
            # each one has to re-register as a drag source here.
            flt = getattr(self, "_project_numbox_reorder_filter", None)
            if flt is not None:
                btn.installEventFilter(flt)
            layout.addWidget(btn, i // per_row, i % per_row)
            self._cat_num_buttons.append(btn)
        # The row can be rebuilt while its own visibility is unreliable: the
        # first build runs before the box is even added to the header layout
        # (a hidden top-level), and later builds replace buttons inside a
        # shown window via a queued slot. In both cases Qt can leave the new
        # buttons in the explicitly-hidden state, so the whole 1-N row sits
        # invisible until an unrelated resize un-hides it — the reported
        # "project buttons disappear" bug. Derive visibility from the box
        # itself: box visible -> every button shown; box hidden (combo mode)
        # -> every button hidden with it.
        for btn in self._cat_num_buttons:
            btn.setVisible(self.data.get("numbox_tabs", "False") == "True")
        cols = min(len(cats), per_row) if cats else 1
        spacing = layout.spacing()
        total_w = cols * size + max(0, cols - 1) * spacing
        rows = (len(cats) + per_row - 1) // per_row if cats else 1
        total_h = rows * size + max(0, rows - 1) * spacing
        self.cat_numbox.setFixedSize(total_w, total_h)
        self._update_cat_numbox_active()
        # A rebuild at a narrow width must not pop the row back to its full
        # configured footprint: the overflow would push it past the right
        # edge (buttons painted off the header) until the next resize event
        # re-ran the density pass. Adding or deleting a project in a narrow
        # window is exactly that rebuild, so re-fit immediately.
        self._fit_cat_numbox_to_header()

    def _fit_cat_numbox_to_header(self):
        """Shrink number tabs into cards when available header width is tight."""
        box = getattr(self, "cat_numbox", None)
        header = getattr(self, "header_widget", None)
        buttons = getattr(self, "_cat_num_buttons", ())
        if (box is None or header is None or sip.isdeleted(box)
                or sip.isdeleted(header) or box.isHidden() or not buttons):
            return
        available = self._header_available_width(header)
        if available <= 0:
            return

        per_row = self.numbox_per_row()
        cols = min(len(buttons), per_row)
        rows = (len(buttons) + per_row - 1) // per_row
        spacing = self._cat_numbox_layout.spacing()
        configured = self.numbox_button_size()
        gap = max(0, cols - 1) * spacing
        desired_w = cols * configured + gap

        try:
            scale = self._effective_scale()
        except Exception:
            scale = 1.0
        # reachability floor: a card narrower than this is not clickable, so
        # when even the floor does not fit the overflow spills right instead
        # of deleting a project button.
        min_btn_w = max(14, int(round(14 * scale)))

        # Budget 1 — layout demand: the space left once every OTHER visible
        # header item got its sizeHint. The box's CURRENT footprint is what
        # the sizeHint contains, so a previously squeezed box does not fake
        # extra demand from its own configured size.
        other_w = max(0, header.sizeHint().width() - box.width())
        budget = max(0, available - other_w)
        fitted_w = configured
        if desired_w > budget:
            fitted_w = min(configured, max(min_btn_w, (budget - gap) // cols))
        # Budget 2 — raw geometry. sizeHint under-reports when the layout is
        # mid-pass or the box sits right of a stretch (custom toolbar order):
        # whatever lies between box.x() and the right edge is all it gets.
        geo_budget = available - box.x()
        if geo_budget > 0 and desired_w > geo_budget:
            fitted_w = min(fitted_w, max(min_btn_w, (geo_budget - gap) // cols))

        # Cards, not smaller squares: the row keeps its configured HEIGHT and
        # only gives up width, so a squeezed number tab stays as tall (and as
        # clickable) as the rest of the toolbar instead of shrinking away.
        for button in buttons:
            button.setFixedSize(fitted_w, configured)
        total_w = cols * fitted_w + gap
        total_h = rows * configured + max(0, rows - 1) * spacing
        box.setFixedSize(total_w, total_h)
        if hasattr(self, "header_layout") and self.header_layout is not None:
            self.header_layout.activate()

    def _schedule_numbox_rebuild(self, *_args):
        """Rebuild the number row once, after the combo has settled.

        Clearing and refilling the combo fires a signal per row, and each
        rebuild throws away and recreates every button — so this coalesces to
        one pass on the next tick instead of N passes mid-edit.
        """
        if sip.isdeleted(self) or getattr(self, "_numbox_rebuild_pending", False):
            return
        if self.data.get("numbox_tabs", "False") != "True":
            self._cat_numbox_dirty = True
            return
        self._numbox_rebuild_pending = True

        def run():
            if sip.isdeleted(self):
                return
            self._numbox_rebuild_pending = False
            self._rebuild_cat_numbox()

        QTimer.singleShot(0, weak_qt_callback(
            self, lambda _window: run()))

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
            if self.cat_combo.currentIndex() == idx:
                self.play_project_sound()
            else:
                self.cat_combo.setCurrentIndex(idx)
        # A checkable QPushButton toggles ITSELF on click. Re-clicking the
        # already-active project changes no combo index, so on_tab_changed
        # never fires and the button would be left visually released; sync the
        # whole row here so exactly one box is ever pressed.
        self._update_cat_numbox_active()

    def _cat_numbox_context(self, idx, pos):
        if 0 <= idx < self.cat_combo.count():
            if 0 <= idx < len(self._cat_num_buttons):
                # Right-click is inspection, not navigation.  Pass the target
                # row to the menu without changing the active project.
                self.show_cat_context_menu(
                    pos, anchor=self._cat_num_buttons[idx], project_idx=idx)

    def _cat_combo_popup_context(self, pos, global_pos=None):
        """Open a popup-row menu without letting right-click select the row."""
        view = self.cat_combo.view()
        model_idx = view.indexAt(pos)
        if not model_idx.isValid():
            return
        if global_pos is None:
            global_pos = view.viewport().mapToGlobal(pos)
        self.cat_combo.hidePopup()
        self.show_cat_context_menu(
            pos, anchor=view.viewport(), project_idx=model_idx.row(),
            global_pos=global_pos)

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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))

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
        if self.data.get("numbox_tabs", "False") == "True":
            self._rebuild_cat_numbox()
        else:
            self._cat_numbox_dirty = True
        self.mark_dirty()

    def _toggle_numbox_mode(self, checked):
        self.data["numbox_tabs"] = "True" if checked else "False"
        if checked:
            self._cat_numbox_dirty = False
            self._rebuild_cat_numbox()
        self._apply_topbar_visibility()
        self.mark_dirty()

    def _sync_silo_folder(self, cat, old_text, new_text):
        """No-op. Folder identity is owned by the per-slot silo_folders map
        (see _silo_folder_name), which follows retitles itself; a title-based
        rename here would fight the map (and re-allocate category folders).
        Kept only because callers still invoke it on the retitle path."""
        return

    # ------------------------------------------------------------------
    # T-1227 P0 — live document ownership contract
    #
    # A silo is identified purely by its position, and every flush used to
    # trust `active_temp_slot` blindly. A stale binding (or a structural op
    # that shifted lists under the visible document) then turned an innocent
    # scroll/autosave into a wrong-slot text write — the "SILO 6 and 8 became
    # identical twins" corruption class. Every silo QTextDocument now carries
    # an owner stamp and every flush verifies it; a mismatch fails CLOSED
    # with an emergency recovery artifact instead of writing.
    # ------------------------------------------------------------------

    def _document_owner_stamp(self, slot, is_archive):
        """The owner identity a live silo QTextDocument must carry."""
        return (self.get_current_category(), bool(is_archive), int(slot))

    def _rebind_silo_document_owners(self):
        """Re-stamp every materialized silo QTextDocument with its current
        owner identity. O(materialized documents) — never a text scan."""
        cat = self.get_current_category()
        for is_arc, docs in ((False, getattr(self, "silo_docs", [])),
                             (True, getattr(self, "archive_docs", []))):
            for i, d in enumerate(docs):
                if d is None:
                    continue
                try:
                    if sip.isdeleted(d):
                        continue
                    d._fastprompter_owner = (cat, is_arc, i)
                except (RuntimeError, AttributeError):
                    continue

    def _stamp_active_document_owner(self):
        """Stamp the attached editor document as the owner of the ACTIVE slot
        and record that its loaded text equals the authoritative slot text."""
        ta = getattr(self, "text_area", None)
        if ta is None:
            return
        try:
            doc = ta.document()
        except RuntimeError:
            return
        if doc is None or sip.isdeleted(doc):
            return
        try:
            doc._fastprompter_owner = self._document_owner_stamp(
                getattr(self, "active_temp_slot", -1),
                getattr(self, "active_is_archive", False))
            doc._fastprompter_flushed_rev = doc.revision()
        except (RuntimeError, AttributeError):
            pass

    def _document_owner_matches(self, slot, is_archive, doc=None):
        """Verify the live editor's document actually belongs to the
        (category, space, slot) a flush is about to target.

        Checks, in the T-1227 contract order:
        A. the current category is valid;
        B. the active slot is in range of the space it claims;
        C. the active QTextDocument is EXACTLY the document owned by the
           current silo (the alias contract `temp_presets is
           temp_presets_all[cat]` must also hold);
        D. the document's owner stamp agrees — an absent stamp is adopted
           lazily (upgraded) when C already proved physical ownership; a
           DISAGREEING stamp refuses.
        """
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return False
        if doc is None:
            try:
                doc = ta.document()
            except RuntimeError:
                return False
        if doc is None or sip.isdeleted(doc):
            return False
        cat = self.get_current_category()
        if not cat:                                   # A
            return False
        if not isinstance(slot, int) or slot < 0:     # B
            return False
        if is_archive:
            key = "archive_temp_presets"
            alias = (self.data.get("archive_temp_presets_all") or {}).get(cat)
            docs = getattr(self, "archive_docs", [])
        else:
            key = "temp_presets"
            alias = (self.data.get("temp_presets_all") or {}).get(cat)
            docs = getattr(self, "silo_docs", [])
        backing = self.data.get(key)
        if not isinstance(backing, list):
            return False
        if alias is not None and alias is not backing:   # E (alias contract)
            return False
        if not (0 <= slot < len(backing)):            # B
            return False
        owner_doc = docs[slot] if 0 <= slot < len(docs) else None
        if doc is not owner_doc:                      # C
            return False
        try:
            stamp = getattr(doc, "_fastprompter_owner", None)
        except (RuntimeError, AttributeError):
            return False
        expected = self._document_owner_stamp(slot, is_archive)
        if stamp is None:
            try:
                doc._fastprompter_owner = expected    # lazy adoption
            except (RuntimeError, AttributeError):
                return False
        elif stamp != expected:                       # D
            return False
        return True

    # The owner-mismatch guard fires from the save path, and the save path
    # runs on a 10s timer. A mismatch the user cannot see and cannot clear
    # therefore writes a full copy of the editor text six times a minute,
    # forever. At a 200 KB silo that is ~70 MB an hour of duplicated user
    # text on the same disk the database lives on — a fail-closed guard that
    # ends in a full volume is not fail-closed.
    _OWNER_MISMATCH_ARTIFACT_CAP = 20

    def _publish_owner_mismatch_artifact(self, base, digest, payload, text):
        """Write one recovery artifact, atomically, bounded, deduplicated.

        Two bounds, both deliberate:

        * identical text is written ONCE. The name carries the SHA256 prefix,
          so a repeating mismatch over the same buffer resolves to the file
          that already exists.
        * past the cap, nothing more is written. The files kept are the
          EARLIEST ones, because those are the ones nearest the root cause;
          a rotating window would throw away the original evidence and keep
          N copies of the aftermath.
        """
        import json as _json
        import uuid as _uuid

        stem = "silo_owner_mismatch_"
        try:
            existing = [n for n in os.listdir(base)
                        if n.startswith(stem) and n.endswith(".json")]
        except OSError:
            existing = []

        suffix = "_" + digest[:12] + ".json"
        for name in existing:
            if name.endswith(suffix):
                return os.path.join(base, name)   # same text, already captured

        if len(existing) >= self._OWNER_MISMATCH_ARTIFACT_CAP:
            from fastprompter.core.logging import logger as _lg
            _lg.critical(
                "T-1227 owner-mismatch artifact cap reached (%d in %s); "
                "keeping the earliest evidence and NOT writing more. The "
                "flush is still refused, so no silo is being overwritten.",
                len(existing), base)
            return None

        artifact = os.path.join(
            base, stem + time.strftime("%Y%m%d_%H%M%S") + suffix)
        # Atomic publish: a half-written recovery artifact is worse than none,
        # because it looks like the text was saved.
        tmp = artifact + ".tmp-" + _uuid.uuid4().hex
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump({**payload, "text": text}, fh,
                       ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, artifact)
        return artifact

    def _refuse_unowned_flush(self, slot, is_arc, doc, current_text):
        """T-1227 fail-closed: publish the live text into an emergency
        recovery artifact, then REFUSE the flush. The text never reaches a
        silo slot and never enters ordinary logs."""
        import hashlib
        digest = hashlib.sha256(
            current_text.encode("utf-8", "surrogatepass")).hexdigest()
        stamp = None
        try:
            stamp = getattr(doc, "_fastprompter_owner", None)
        except (RuntimeError, AttributeError):
            stamp = None
        payload = {
            "reason": "SILO_OWNER_MISMATCH",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "db_path": getattr(getattr(self, "state", None), "db_path", None),
            "profile_id": getattr(getattr(self, "state", None),
                                  "profile_id", None),
            "category": self.get_current_category(),
            "claimed_slot": slot,
            "claimed_space": "archive" if is_arc else "normal",
            "document_owner_stamp": (list(stamp) if isinstance(stamp, tuple)
                                     else repr(stamp)),
            "text_length": len(current_text),
            "text_sha256": digest,
        }
        artifact = None
        try:
            db_path = getattr(getattr(self, "state", None), "db_path", None)
            if db_path:
                base = os.path.join(os.path.dirname(db_path), "recovery")
                os.makedirs(base, exist_ok=True)
                artifact = self._publish_owner_mismatch_artifact(
                    base, digest, payload, current_text)
                if artifact:
                    payload["artifact"] = artifact
        except Exception:
            from fastprompter.core.logging import logger as _lg
            _lg.exception("T-1227 owner-mismatch recovery artifact FAILED")
        from fastprompter.core.logging import logger as _lg
        _lg.critical(
            "T-1227 SILO_OWNER_MISMATCH: refused to flush live editor into "
            "category=%r slot=%s space=%s stamp=%s len=%s sha=%s "
            "artifact=%s; text NOT written, state left dirty",
            payload["category"], slot, payload["claimed_space"],
            payload["document_owner_stamp"], payload["text_length"],
            digest[:12], payload.get("artifact", "UNAVAILABLE"))

    def _flush_live_editor(self, current_text):
        """Copy the live editor text into its owning store.

        Snippet mode writes the exact editor text into the referenced
        snippet, refreshes its last-edited metadata and marks the snippets
        domain dirty when the value changed. Silo mode keeps the established
        per-slot alias behaviour. This is the single synchronous owner flush
        used by every authoritative save and owner transition.

        T-1227: silo mode verifies the document's owner FIRST. On mismatch
        the text goes to a recovery artifact and no slot is touched. On a
        clean match, an UNEDITED document (revision unchanged since its last
        flush) is skipped entirely: scroll/cursor/settings-only saves must
        never rewrite silo text from the editor buffer."""
        if self.editing_snippet:
            cat_snip, idx = self.editing_snippet
            if cat_snip in self.data["categories"] and self.data["categories"][cat_snip][idx]:
                item = self.data["categories"][cat_snip][idx]
                old_text = item.get("text")
                if old_text != current_text:
                    item["text"] = current_text
                    item["last_edited"] = int(time.time())
                    self.mark_dirty("snippets")
            return
        is_arc = getattr(self, "active_is_archive", False)
        slot = self.active_temp_slot
        doc = self._active_doc()
        if not self._document_owner_matches(slot, is_arc, doc=doc):
            self._refuse_unowned_flush(slot, is_arc, doc, current_text)
            return
        target = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
        if not (0 <= slot < len(target)):
            return
        try:
            rev = doc.revision()
        except (RuntimeError, AttributeError):
            return
        if getattr(doc, "_fastprompter_flushed_rev", None) == rev:
            # The document has not been edited since its last flush, so the
            # slot already holds the authoritative text. Scroll-only and
            # settings-only saves stop here.
            return
        old_text = target[slot]
        target[slot] = current_text
        self._remember_active_document_text(current_text)
        try:
            doc._fastprompter_flushed_rev = rev
        except (RuntimeError, AttributeError):
            pass
        if current_text != old_text:
            self.mark_dirty("arc" if is_arc else "temp")
            if not is_arc:
                self.silo_last_edited[slot] = int(time.time())
            self._update_active_silo_ui()

    def commit_current_text(self):
        """Commit the current text to the active slot."""
        if getattr(self, "_initializing_ui", False):
            return
        current_text = self._editor_text_snapshot()
        if current_text is None:
            # T-1250: the snapshot normally reports unavailability as None
            # instead of raising, so the old try/except fallback could never
            # run. ONE guarded direct read is still allowed before refusing.
            try:
                ta = getattr(self, "text_area", None)
                if ta is None or sip.isdeleted(ta):
                    current_text = None
                else:
                    current_text = ta.toPlainText()
            except Exception:
                current_text = None
        if current_text is None:
            # Both reads failed. Refuse the commit: no flush, no store
            # mutation -- an unreadable document is not an empty one.
            self._log_snapshot_unavailable("commit_current_text",
                                           bool(getattr(
                                               self, "active_is_archive",
                                               False)))
            return
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
            QTimer.singleShot(300, weak_qt_callback(
                self, lambda w: w._decrement_focus_lock()))

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
                # CORE-003 / T02: the backup worker must be drained BEFORE the
                # live DB incarnation changes. A timed-out drain means a stale
                # worker can still publish a pre-restore snapshot into the
                # restored DB's .bak after the swap. The drain helper enforces
                # a real wall-clock deadline; on False the restore is aborted
                # with the live DB and connection untouched.
                from fastprompter.core.logging import logger as _log
                from fastprompter.core.state import (
                    FatalRestoreError,
                    RestoreError,
                    _drain_db_backup,
                    restore_database,
                )
                if not _drain_db_backup(db_path, timeout=5.0):
                    _log.error("Restore aborted: backup worker did not drain "
                               "within the bound; the live database is unchanged")
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang),
                        tr("Restore aborted — the backup worker was still busy; "
                           "try again once it settles.", self._current_lang))
                    # T02: the watcher was paused by _watcher_begin_quiesce;
                    # a refused restore must roll that pause back, never
                    # commit the disarm (the runtime stays fully active).
                    self._resume_watcher_runtime()
                    return
                # Establish a two-way writer boundary before the live DB is
                # closed. A final worker mutation completes before this
                # returns; every captured lease becomes stale.
                self._establish_sync_writer_barrier()
                # drain proven: now close the live connection (SQLite keeps
                # the file locked while a connection is open).
                if self.state.conn:
                    self.state.conn.close()
                    self.state.conn = None
                self.conn = None
                time.sleep(0.1)
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
                    if getattr(e, "repaired", True):
                        msg = tr("Restore failed and the live database could not be "
                                 "left consistent. It has been repaired from the "
                                 "automatic safety snapshot on disk — restart "
                                 "FastPrompter to reload it.", self._current_lang)
                    else:
                        msg = tr("Restore failed and the live database could not be "
                                 "repaired. Your data is not guaranteed intact — "
                                 "restart FastPrompter.", self._current_lang)
                    QMessageBox.critical(
                        self, tr("Error", self._current_lang), msg)
                    self._restore_stale_memory = True
                    self._logical_finalized = True
                    if hasattr(self, "_watcher_commit_quiesce"):
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
                        if hasattr(self, "_watcher_commit_quiesce"):
                            self._watcher_commit_quiesce()
                        self.quit_app()
                        return
                    self._resume_sync_push_after_restore_refusal()
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
                # CORE-004: the restored DB is authoritative — revoke every
                # pre-restore external writer NOW (one-way mirror + Sync-Project
                # push) so no already-running worker can publish stale RAM over
                # the restored state before quit_app's own drain.
                try:
                    from fastprompter.main import _sync_revoke_all
                    _sync_revoke_all()
                except Exception:
                    pass
                try:
                    if self._push_worker is not None:
                        self._push_worker._suppress = True
                except Exception:
                    pass
                if hasattr(self, "_watcher_commit_quiesce"):
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
            self._resume_sync_push_after_restore_refusal()
            self._resume_watcher_runtime()
        finally:
            self.ignore_focus_loss = False

    def _reopen_live_connection(self):
        """Reopen the live SQLite connection to the SAME db_path without
        reloading disk (CORE-002). Use after a refused/failed restore where
        the original file is untouched and the in-memory state is still
        authoritative — reloading via init_db would discard the RAM edits.

        T04: the reopened connection inherits the same bounded GUI busy
        budget as the original init_db path. Without it, a reconnected
        runtime could again sit inside sqlite3's multi-second default
        busy wait on the next writer contention.

        Returns True only when a usable connection was established; callers
        must NOT resume an editable runtime (CORE-009) on False.
        """
        try:
            # One canonical connect site (T-1232): this used to carry its own
            # copy of the pragma block, so a durability change made in
            # state.py would have silently missed the post-restore runtime.
            from fastprompter.core.state import connect_app_db
            conn = connect_app_db(self.state.db_path)
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
            if getattr(self, "_watcher_quiescing", False) and hasattr(self, "_watcher_rollback_quiesce"):
                self._watcher_rollback_quiesce()
                return
            engine = getattr(self, "_watcher_engine", None)
            if engine is not None and getattr(engine, "armed", False) and hasattr(self, "_watcher_start_timer"):
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
        """Template NEW: create ONE genuinely fresh silo, then fill THAT
        identity. Never overwrites an existing blank slot. The template text
        is explicit content, so the clipboard-into-new-silo automation is
        suppressed for this creation; the random-color-on-NEW automation is
        content-independent and still applies."""
        self._suppress_new_silo_clipboard = True
        try:
            self.select_empty_silo(insertion="top")
            self.fill_silo_from_preset(self.active_temp_slot, text)
        finally:
            self._suppress_new_silo_clipboard = False

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
            self.refresh_archive_panel()
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
        # W2-002: during post-loop physical teardown, skip logical save fallback.
        if getattr(self, "_in_physical_teardown", False):
            super().closeEvent(event)
            return
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
        QApplication.quit()

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

        super().resizeEvent(event)
        self._apply_header_density()
        # a wrapping settings panel changes height when the window changes width
        if getattr(self, "mini_settings_frame", None) is not None and \
                not sip.isdeleted(self.mini_settings_frame) and \
                self.mini_settings_frame.isVisible():
            self._fit_settings_tabs()

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
        was_visible = self.isVisible()
        super().showEvent(event)
        # T-1245: the app becomes visibly shown for a new visible cycle --
        # a tray restore or an un-hide, never the initial construction
        # show (isVisible() was still False when the event arrived) and
        # never a repaint or retranslation of an already-visible window.
        if was_visible is False and self.isVisible():
            from fastprompter.ui.appearance_sounds import emit_app_show
            emit_app_show(self)
        # PERF-004: after being hidden (tray-resident), the date/top-bar label
        # must catch up immediately so the first visible frame is current.
        self._update_date_label()
        # The panel is measured against a WIDTH, and during construction the
        # tabs are still a few pixels wide — a wrapping row measured there
        # reports the height it would need in a sliver, which is how a fresh
        # launch came up with a screenful of dead panel under two rows of
        # checkboxes. The first real geometry only exists now, so re-fit once
        # the event loop has laid the window out.
        if getattr(self, "mini_settings_frame", None) is not None:
            QTimer.singleShot(0, weak_qt_callback(
                self, type(self)._fit_settings_tabs))
        if hasattr(self, "_apply_header_density"):
            self._apply_header_density()
            QTimer.singleShot(0, weak_qt_callback(
                self, type(self)._apply_header_density))

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
                # Settings are lazy: before the panel is first built the
                # checkbox does not exist, and the runtime gate must read the
                # persisted value then — a widget that was never created is
                # not a disabled setting.
                _cb_focus = getattr(self, "cb_focus", None)
                focus_loss_on = (
                    _cb_focus.isChecked() if _cb_focus is not None
                    else self.data.get("close_on_focus_loss", "True") == "True")
                if focus_loss_on:
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

        if obj is getattr(self, "_cat_combo_popup_view", None):
            is_right = (
                event.type() in (QEvent.Type.MouseButtonPress,
                                 QEvent.Type.MouseButtonRelease)
                and event.button() == Qt.MouseButton.RightButton
            )
            if is_right:
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self._cat_combo_popup_context(
                        event.position().toPoint(),
                        event.globalPosition().toPoint())
                return True

        if obj is getattr(self, "btn_new", None):
            if event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.MiddleButton:
                    self.show_new_silo_presets(event.globalPosition().toPoint())
                    return True
                child_mods = (Qt.KeyboardModifier.ControlModifier
                              | Qt.KeyboardModifier.AltModifier)
                mods = event.modifiers() | QApplication.keyboardModifiers()
                if (event.button() == Qt.MouseButton.LeftButton
                        and mods & child_mods == child_mods
                        and not getattr(self, "active_is_archive", False)):
                    self.btn_new.setDown(False)
                    self._create_child_silo_for_current()
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

    def _run_project_context_action(self, idx, callback):
        """Activate a context target only after its menu action was chosen."""
        if not 0 <= idx < self.cat_combo.count():
            return
        if self.cat_combo.currentIndex() != idx:
            self.cat_combo.setCurrentIndex(idx)
        callback()

    def _move_project(self, idx, step):
        """Reorder the project at combo row ``idx`` by ``step`` visible slots.

        The combo row is a VISIBLE position; cats_order also holds hidden
        projects. Swapping the two visible neighbours by their absolute index
        in cats_order moves the pair without disturbing any hidden project
        sitting between them (T-599 divergence)."""
        visible = self.visible_categories()
        new = idx + step
        if not (0 <= idx < len(visible) and 0 <= new < len(visible)):
            return
        cat, neighbor = visible[idx], visible[new]
        order = self.data.get("cats_order")
        if not isinstance(order, list) or cat not in order or neighbor not in order:
            return
        self.add_data_undo_state("Reorder projects")
        i, j = order.index(cat), order.index(neighbor)
        order[i], order[j] = order[j], order[i]
        self.mark_dirty()
        # keep=cat: the moved project stays selected under the pointer
        self.rebuild_cat_combo(keep=cat)
        self._update_cat_numbox_active()

    def show_cat_context_menu(self, pos, anchor=None, project_idx=None,
                              global_pos=None):
        """`anchor` is the widget `pos` is relative to. It defaults to the
        combo, but in number-box mode the combo is HIDDEN — mapToGlobal on a
        hidden widget lands the menu somewhere off in the corner, so the
        number button that was right-clicked passes itself in."""
        if not hasattr(self, "cat_combo"): return
        idx = (self.cat_combo.currentIndex()
               if project_idx is None else project_idx)
        cat = self._cat_at(idx) if 0 <= idx < self.cat_combo.count() else None
        if cat is None:
            return

        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setFont(QApplication.font())
        lang = getattr(self, "_current_lang", "EN")

        def on_target(callback):
            return lambda _checked=False: self._run_project_context_action(
                idx, callback)

        menu.addAction(tr("➕ Add New Project Tab", lang), self.add_category)
        menu.addAction(tr("✏️ Rename Project Tab", lang),
                       on_target(self.rename_category))
        menu.addAction(tr("❌ Delete Project Tab", lang),
                       on_target(self.del_category))
        # Reorder — moves the project among the VISIBLE tabs. idx is the
        # right-clicked row (combo currentIndex or the number button that
        # opened the menu), so the move works the same in dropdown and
        # number-box mode; grey the ends so there is no no-op action.
        visible_count = len(self.visible_categories())
        menu.addSeparator()
        act_left = menu.addAction(
            tr("◀ Move Project Left", lang),
            lambda _c=False, n=idx: self._move_project(n, -1))
        act_left.setEnabled(idx > 0)
        act_right = menu.addAction(
            tr("▶ Move Project Right", lang),
            lambda _c=False, n=idx: self._move_project(n, 1))
        act_right.setEnabled(0 <= idx < visible_count - 1)
        menu.addSeparator()
        # Sync-Project: bind this project tab to a folder and read it as
        # silos, two-way, in real time (revertable via Unlink).
        target_sync = (self._sync_config()
                       if idx == self.cat_combo.currentIndex()
                       else self.data.get("project_sync_all", {}).get(cat))
        if target_sync:
            menu.addAction(tr("🔄 Re-scan folder", lang),
                           on_target(self._rescan_project_sync))
            menu.addAction(tr("📂 Change folder…", lang),
                           on_target(self._change_project_sync_folder))
            menu.addAction(tr("🔌 Unlink Sync-Project (keep silos)", lang),
                           on_target(self._unlink_project_sync))
        else:
            menu.addAction(tr("📁 Convert to Sync-Project…", lang),
                           on_target(self._convert_project_to_sync))
        # whole-project typecheck report (same dictionary as the live
        # underlines — see Settings > Editor > Typos)
        menu.addAction(tr("🔍 Check Typos in this project…", lang),
                       on_target(self.check_project_typos))
        menu_pos = (global_pos if global_pos is not None
                    else (anchor or self.cat_combo).mapToGlobal(pos))
        menu.exec(menu_pos)

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
        for record in log:
            # W2-005: defensively skip malformed members — a corrupt row must
            # never abort the whole rollback batch.
            if not (isinstance(record, (tuple, list)) and len(record) >= 2
                    and isinstance(record[0], str) and isinstance(record[1], str)
                    and record[0] and record[1]):
                continue
            original, trashed = record[0], record[1]
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

    def _remember_category_documents(self, category):
        """Save the current category's document lists in a bounded LRU."""
        if not category:
            return
        cache = getattr(self, "_category_document_cache", None)
        if cache is None:
            cache = self._category_document_cache = {}
        cache.pop(category, None)
        cache[category] = (self.silo_docs, self.archive_docs)
        self._prune_category_document_cache()

    @staticmethod
    def _document_lists_char_count(document_lists):
        total = 0
        for docs in document_lists:
            for doc in docs:
                if doc is None:
                    continue
                try:
                    total += max(0, int(doc.characterCount()) - 1)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue
        return total

    def _prune_category_document_cache(self):
        """Bound warm documents by category count and approximate characters."""
        cache = getattr(self, "_category_document_cache", {})
        count_limit = max(1, int(getattr(self, "_document_cache_limit", 4)))
        char_limit = max(1, int(getattr(
            self, "_document_cache_char_limit", 4_000_000)))
        while len(cache) > 1:
            total_chars = sum(
                self._document_lists_char_count(document_lists)
                for document_lists in cache.values()
            )
            if len(cache) <= count_limit and total_chars <= char_limit:
                break
            evicted_category = next(iter(cache))
            evicted_docs = cache.pop(evicted_category)
            evicted_ids = {
                id(doc) for docs in evicted_docs for doc in docs if doc is not None
            }
            fp_cache = getattr(self, "_document_fingerprint_cache", {})
            for key in list(fp_cache):
                if key[0] in evicted_ids:
                    fp_cache.pop(key, None)
            line_cache = getattr(self, "_line_count_cache", {})
            for key in list(line_cache):
                if key[0] == evicted_category:
                    line_cache.pop(key, None)
            # QTextDocument destruction can itself be expensive. Queue C++
            # retirement after navigation returns to Qt's event loop instead
            # of freeing a multi-megabyte document on this call stack.
            active_doc = getattr(getattr(self, "text_area", None),
                                 "document", lambda: None)()
            for docs in evicted_docs:
                for doc in docs:
                    if doc is None or doc is active_doc:
                        continue
                    try:
                        doc.deleteLater()
                    except (AttributeError, RuntimeError):
                        pass

    def _reset_profile_document_caches(self):
        """Drop every document-derived cache at a profile ownership boundary."""
        active_doc = getattr(getattr(self, "text_area", None),
                             "document", lambda: None)()
        seen = set()
        cache = getattr(self, "_category_document_cache", {})
        groups = list(cache.values())
        groups.append((getattr(self, "silo_docs", []),
                       getattr(self, "archive_docs", [])))
        for document_lists in groups:
            for docs in document_lists:
                for doc in docs:
                    if doc is None or doc is active_doc or id(doc) in seen:
                        continue
                    seen.add(id(doc))
                    try:
                        doc.deleteLater()
                    except (AttributeError, RuntimeError):
                        pass
        self._category_document_cache = {}
        self._document_fingerprint_cache = {}
        self._line_count_cache = {}
        self._editor_text_snaps = None
        self._last_cached_text = None
        self.silo_docs = [None] * len(self.data.get("temp_presets", []))
        self.archive_docs = [None] * len(
            self.data.get("archive_temp_presets", []))

    def _restore_category_documents(self, category):
        """Restore cached lists and align them with the live slot counts."""
        cache = getattr(self, "_category_document_cache", {})
        cached = cache.pop(category, None)
        if cached is None:
            silo_docs, archive_docs = [], []
        else:
            silo_docs, archive_docs = cached
        silo_count = len(self.data.get("temp_presets", []))
        archive_count = len(self.data.get("archive_temp_presets", []))
        del silo_docs[silo_count:]
        del archive_docs[archive_count:]
        silo_docs.extend([None] * (silo_count - len(silo_docs)))
        archive_docs.extend([None] * (archive_count - len(archive_docs)))
        self.silo_docs = silo_docs
        self.archive_docs = archive_docs
        cache[category] = (silo_docs, archive_docs)
        self._prune_category_document_cache()

    @staticmethod
    def _silo_cache_key(category, is_archive, slot):
        return (category or "", bool(is_archive), int(slot))

    def _remember_active_document_text(self, text):
        category = self.get_current_category()
        slot = getattr(self, "active_temp_slot", -1)
        if category and slot >= 0:
            doc = self.text_area.document()
            try:
                doc._fastprompter_loaded_text_token = text
            except (AttributeError, RuntimeError):
                pass
            self._document_fingerprint(doc, text)
            key = self._silo_cache_key(
                category, getattr(self, "active_is_archive", False), slot)
            self._line_count_cache[key] = (
                text, text.count("\n") + 1 if text.strip() else 0)

    def _cached_silo_line_count(self, raw, slot, is_archive=False):
        """Return a line count cached by category, slot and text generation."""
        cache = getattr(self, "_line_count_cache", None)
        if cache is None:
            cache = self._line_count_cache = {}
        key = self._silo_cache_key(
            self.get_current_category(), is_archive, slot)
        cached = cache.pop(key, None)
        if cached is not None and cached[0] is raw:
            cache[key] = cached
            return cached[1]
        count = raw.count("\n") + 1 if raw.strip() else 0
        cache[key] = (raw, count)
        while len(cache) > 1024:
            cache.pop(next(iter(cache)))
        return count

    def _ensure_document_text(self, doc, text):
        """Populate one document unless that exact document owns this token."""
        loaded_token = getattr(
            doc, "_fastprompter_loaded_text_token", None)
        if loaded_token is text:
            return True
        # A snapshot can carry equal text in a different string object. Do
        # not erase the document's native undo/redo history just to reload it.
        if doc.toPlainText() == text:
            doc._fastprompter_loaded_text_token = text
            self._document_fingerprint(doc, text)
            return True
        self._set_plain_text_clean(doc, text)
        try:
            doc._fastprompter_loaded_text_token = text
        except (AttributeError, RuntimeError):
            pass
        # Seed from the string already in hand. Restore must never copy the
        # freshly-loaded QTextDocument merely to calculate the same bytes.
        self._document_fingerprint(doc, text)
        return False

    def _document_fingerprint(self, doc, text=None):
        """Canonical fingerprint cache keyed by document identity and revision.

        ``id(doc)`` alone is NOT identity: CPython recycles the address of a
        freed QTextDocument, and a fresh document that lands on the same
        address at the same revision then reads a DEAD document's cached
        fingerprint. The cache entry therefore holds a weak reference to the
        document it was computed from and is only trusted while that exact
        object is alive under the key.
        """
        import weakref

        cache = getattr(self, "_document_fingerprint_cache", None)
        if cache is None:
            cache = self._document_fingerprint_cache = {}
        key = (id(doc), doc.revision())
        entry = cache.get(key)
        if entry is not None:
            try:
                if entry[0]() is doc:
                    return entry[1]
            except TypeError:
                pass
        if text is None:
            text = doc.toPlainText()
        fingerprint = (
            len(text), zlib.crc32(text.encode("utf-8", "replace")))
        try:
            cache[key] = (weakref.ref(doc), fingerprint)
        except TypeError:
            return fingerprint
        while len(cache) > 256:
            cache.pop(next(iter(cache)))
        return fingerprint

    def on_tab_changed(self, index, prev_identity=None):
        if index < 0:
            return
        if not getattr(self, "_initializing_ui", False):
            self.play_project_sound()
        _tab_started = time.perf_counter()
        def _tab_phase(label, started, category=None, doc=None, warm=None):
            elapsed = time.perf_counter() - started
            if elapsed < 0.03:
                return
            try:
                from fastprompter.core.logging import logger as _log
                _log.info(
                    "tab phase=%s elapsed=%.3fs category=%s slot=%s "
                    "chars=%s blocks=%s warm=%s",
                    label, elapsed, category or self.get_current_category(),
                    getattr(self, "active_temp_slot", -1),
                    doc.characterCount() if doc is not None else 0,
                    doc.blockCount() if doc is not None else 0,
                    warm if warm is not None else "unknown")
            except Exception:
                pass
        _tab_commit_started = time.perf_counter()
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
            cache_store_started = time.perf_counter()
            self._remember_category_documents(prev_cat)
            _tab_phase("cache_store_evict", cache_store_started, prev_cat)
        self.data["last_tab_idx"] = index
        self.commit_current_text()
        _tab_phase("commit", _tab_commit_started)
        self.cancel_editing(silent=True)

        # Switch Silos to the new Tab's hierarchy
        cat = self._cat_at(index)
        if cat is None:
            _tab_phase("total", _tab_started)
            return
        _switch_started = time.perf_counter()
        if "temp_presets_all" in self.data:
            # ONE authoritative alias binder: every per-category flat alias
            # (silos, pins, ticks, children, colours, gaps, folders, project
            # paths, watcher queues, types, ...) is re-bound to `cat` here.
            from fastprompter.core.state import bind_active_category
            bind_started = time.perf_counter()
            bind_active_category(self.data, cat)
            _tab_phase("category_bind", bind_started, cat)
            self.prompt_queues = {}
            self.silo_last_edited = self.data.setdefault("silo_last_edited_all", {}).setdefault(
                cat, {}
            )

            # Restore this category's bounded document cache instead of
            # destroying all warm documents on every project switch.
            cache_warm = cat in self._category_document_cache
            cache_restore_started = time.perf_counter()
            self._restore_category_documents(cat)
            _tab_phase(
                "cache_restore_evict", cache_restore_started, cat,
                warm=cache_warm)

            # Land where this project was left, not where the last one was.
            slot = self.restore_silo_session(cat)
            self._switch_to_slot(
                slot, initial=True,
                is_archive=getattr(self, "active_is_archive", False),
                sync_outgoing=False)
            _tab_phase("switch", _switch_started)

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
        # The latched selection is per-category and persisted, so it is not
        # cleared here — it is RE-READ from the alias the category bind just
        # rebound. Dropping the cached set is what makes each project show its
        # own latched silos instead of the previous project's indices.
        self._silo_selection_source = None
        self._silo_sel()
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
        for i, s in enumerate(self.data.get("categories", {}).get(cat, [])):
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
        # Rendering must stay read-only.  Archive retirement is performed by
        # explicit mutation paths; a silo switch must not touch the filesystem.
        total = len(self.data.get("archive_temp_presets", []))
        if total == 0:
            self.archive_section.setVisible(False)
            return

        saved_arc_visible = self.data.get("archive_visible", "False") == "True"
        self.archive_section.setVisible(saved_arc_visible)
        if not saved_arc_visible:
            return

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
        self._ensure_archive_buttons(visible_count)

        for i, btn in enumerate(self.archive_buttons):
            slot_idx = start_idx + i
            if i >= visible_count or slot_idx >= total:
                btn.hide()
                continue
            raw = self.data["archive_temp_presets"][slot_idx]
            text = (raw[:100] if len(raw) > 100 else raw).replace("\n", " ").strip()
            display_idx = slot_idx + 1
            line_count = self._cached_silo_line_count(
                raw, slot_idx, is_archive=True)
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

    def _switch_to_slot(self, idx, initial=False, is_archive=False,
                        sync_outgoing=True):
        if is_archive:
            self.arc_silo_page = idx // 10
        else:
            self.silo_page = idx // max(1, self._visible_silos)

        was_editing_snippet = bool(getattr(self, "editing_snippet", None))
        was_archive = getattr(self, "active_is_archive", False)
        # PERF-002: the owner we are leaving (valid before any reassignment)
        outgoing_slot = getattr(self, "active_temp_slot", -1)
        navigation_started = time.perf_counter()

        def profile_phase(label, started, doc=None, warm=None):
            elapsed = time.perf_counter() - started
            if elapsed < 0.03:
                return
            try:
                from fastprompter.core.logging import logger as _log
                _log.info(
                    "navigation phase=%s elapsed=%.3fs category=%s slot=%s "
                    "chars=%s blocks=%s warm=%s",
                    label, elapsed, self.get_current_category(), idx,
                    doc.characterCount() if doc is not None else 0,
                    doc.blockCount() if doc is not None else 0,
                    warm if warm is not None else "unknown",
                )
            except Exception:
                pass

        # T-1250: observe the outgoing document BEFORE anything else. If it
        # cannot be read, the navigation cannot truthfully publish its newest
        # state -- aborting the ownership transition keeps the user on this
        # silo instead of silently leaving potentially newer text behind.
        outgoing_txt = None
        if not initial and not was_editing_snippet:
            outgoing_txt = self._editor_text_snapshot()
            if outgoing_txt is None:
                self._log_snapshot_unavailable("switch_silo", was_archive)
                return

        # remember where we were before the document underneath us changes
        if not initial and not was_editing_snippet:
            self.capture_silo_state(self.active_temp_slot, was_archive)

        if not initial:
            self.play_click_sound()
            self._cache_timer.stop()
            if was_editing_snippet:
                self.save_snippet(silent=True)
            elif was_archive:
                new_txt = outgoing_txt
                if (new_txt.strip()
                        and 0 <= self.active_temp_slot < len(
                            self.data.get("archive_temp_presets", [])
                        )):
                    old_arc_txt = self.data["archive_temp_presets"][self.active_temp_slot]
                    # T-1227: the outgoing archive flush only proceeds when the
                    # document really owns this slot; otherwise refuse (recovery
                    # artifact) exactly like _flush_live_editor.
                    outgoing_doc = self._active_doc()
                    if self._document_owner_matches(
                            self.active_temp_slot, was_archive,
                            doc=outgoing_doc):
                        self._sync_silo_folder(
                            self.get_current_category(),
                            old_arc_txt,
                            new_txt,
                        )
                        self.data["archive_temp_presets"][self.active_temp_slot] = new_txt
                        self._remember_active_document_text(new_txt)
                        try:
                            outgoing_doc._fastprompter_flushed_rev = \
                                outgoing_doc.revision()
                        except (RuntimeError, AttributeError):
                            pass
                        # PERF-002: mark the archive domain when text changed
                        if new_txt != old_arc_txt:
                            self.mark_dirty("arc")
                    else:
                        self._refuse_unowned_flush(
                            self.active_temp_slot, was_archive,
                            outgoing_doc, new_txt)
            else:
                old_slot = self.active_temp_slot
                new_text = outgoing_txt
                if 0 <= old_slot < len(self.data["temp_presets"]):
                    outgoing_doc = self._active_doc()
                    if self._document_owner_matches(old_slot, False,
                                                    doc=outgoing_doc):
                        old_text = self.data["temp_presets"][old_slot]
                        self._sync_silo_folder(self.get_current_category(), old_text, new_text)
                        self.data["temp_presets"][old_slot] = new_text
                        self._remember_active_document_text(new_text)
                        try:
                            outgoing_doc._fastprompter_flushed_rev = \
                                outgoing_doc.revision()
                        except (RuntimeError, AttributeError):
                            pass
                        if new_text != old_text:
                            self.silo_last_edited[old_slot] = int(time.time())
                            # PERF-002: the text changed, mark the silo domain
                            self.mark_dirty("temp")
                    else:
                        self._refuse_unowned_flush(
                            old_slot, False, outgoing_doc, new_text)

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
                document_started = time.perf_counter()

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

                # Loaded identity belongs to THIS QTextDocument. A new doc
                # created after LRU eviction cannot inherit a stale slot token
                # and open blank (then overwrite authoritative text on leave).
                warm_document = self._ensure_document_text(doc, new_text)
                profile_phase(
                    "document_load", document_started, doc,
                    warm=warm_document)

                attach_started = time.perf_counter()
                self.text_area.set_active_document(doc)
                profile_phase("attach", attach_started, doc)
                # T-1227: the document that now fronts the editor must carry
                # the owner stamp of the slot it was loaded FOR, so the next
                # flush verifies identity instead of trusting the slot number.
                try:
                    doc._fastprompter_owner = self._document_owner_stamp(
                        idx, is_archive)
                    doc._fastprompter_flushed_rev = doc.revision()
                except (RuntimeError, AttributeError):
                    pass
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
                    restore_started = time.perf_counter()
                    self.restore_silo_state(idx, is_archive)
                    profile_phase("restore_state", restore_started, doc,
                                  warm=warm_document)
                    self.text_area.moveCursor(QTextCursor.MoveOperation.Start)
                else:
                    restore_started = time.perf_counter()
                    restored = self.restore_silo_state(idx, is_archive)
                    profile_phase("restore_state", restore_started, doc,
                                  warm=warm_document)
                    if not restored:
                        self.text_area.moveCursor(QTextCursor.MoveOperation.End)
            finally:
                self.text_area.blockSignals(False)
                self._suspend_cache = False

            phase_started = time.perf_counter()
            self.refresh_temp_presets()
            profile_phase("sidebar", phase_started, doc)
            phase_started = time.perf_counter()
            self.refresh_archive_panel()
            profile_phase("archive", phase_started, doc)
            phase_started = time.perf_counter()
            self.update_preview(new_text)
            profile_phase("preview", phase_started, doc)
            phase_started = time.perf_counter()
            self._update_line_count_label()
            profile_phase("line_token_label", phase_started, doc)
            phase_started = time.perf_counter()
            self._update_files_button()
            self._sync_files_dock_to_active_silo()
            profile_phase("file_dock", phase_started, doc)
            self._update_project_buttons(is_archive)
            cur_text = new_text
            phase_started = time.perf_counter()
            self._apply_silo_type(idx, is_archive, cur_text)
            profile_phase("silo_type", phase_started, doc)
            # seed the live folder-sync baseline for the new silo
            from fastprompter.ui.file_container import silo_slug as _sl2
            self._active_silo_slug = _sl2(
                cur_text[:cur_text.index("\n")] if "\n" in cur_text else cur_text)
            if sync_outgoing:
                self._push_sync_files(
                    slots=None if outgoing_slot < 0 else {outgoing_slot})
            if hasattr(self, "_typo_timer"):
                self._typo_timer.start()
            self.text_area.setFocus()
            self.text_area.ensureCursorVisible()
            profile_phase("total", navigation_started, doc)
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

    def _get_or_create_kanban_widget(self):
        if getattr(self, "kanban_widget", None) is None:
            from fastprompter.ui.kanban_widget import KanbanBoardWidget
            kw = KanbanBoardWidget(self)
            kw.changed.connect(lambda markdown: self._on_visual_widget_changed(markdown))
            kw.undoRequested.connect(self.text_area.undo)
            self.kanban_widget = kw
            if hasattr(self, "_apply_kanban_theme"):
                self._apply_kanban_theme(None)
            idx = self.silo_view.indexOf(getattr(self, "_kanban_placeholder", None))
            if idx >= 0:
                self.silo_view.removeWidget(self._kanban_placeholder)
                self.silo_view.insertWidget(idx, self.kanban_widget)
            elif self.silo_view.indexOf(self.kanban_widget) < 0:
                self.silo_view.insertWidget(1, self.kanban_widget)
        return self.kanban_widget

    def _get_or_create_table_widget(self):
        if getattr(self, "table_widget", None) is None:
            from fastprompter.ui.table_widget import TableGridWidget
            tw = TableGridWidget(self)
            tw.changed.connect(lambda markdown: self._on_visual_widget_changed(markdown))
            tw.undoRequested.connect(self.text_area.undo)
            self.table_widget = tw
            if hasattr(self, "_apply_table_theme"):
                self._apply_table_theme(None)
            idx = self.silo_view.indexOf(getattr(self, "_table_placeholder", None))
            if idx >= 0:
                self.silo_view.removeWidget(self._table_placeholder)
                self.silo_view.insertWidget(idx, self.table_widget)
            elif self.silo_view.indexOf(self.table_widget) < 0:
                self.silo_view.insertWidget(2, self.table_widget)
        return self.table_widget

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
            kw = self._get_or_create_kanban_widget()
            self.silo_view.setCurrentIndex(1)
            kw.load_markdown(text)
            self._rendered_visual_text = text
        elif stype == "table":
            tw = self._get_or_create_table_widget()
            self.silo_view.setCurrentIndex(2)
            tw.load_markdown(text)
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
        self._ensure_silo_buttons(self._visible_silos)

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

            line_count = self._cached_silo_line_count(raw, slot_idx)
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
            color_val = silo_colors.get(str(slot_idx), "")
            color_hex = color_val if (has_hash or (color_val and self.data.get("silo_color_box", "True") == "True")) else ""
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
        # T-1222: refresh is a RENDER pass and must not mutate user state —
        # pruning here destroyed recoverable gap evidence whenever the list
        # reconstruction was shorter than the real structure. Gap anchors now
        # leave ONLY through canonical deletion (drop_silo_state removes the
        # gap owned by the deleted silo and remaps the rest).
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
            if not self._durable_undo_or_refuse("Insert silo"):
                return
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

        if not self._durable_undo_or_refuse("Insert silo"):
            return

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
        # T-1227: insertion shifted slot indices — re-stamp owners.
        self._rebind_silo_document_owners()
        self._stamp_active_document_owner()
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


    def _create_child_silo_for_current(self):
        """Ctrl+Alt+Click NEW: create a child silo under the current active silo."""
        presets = self.data.get("temp_presets", [])
        if not presets:
            self.select_empty_silo(insertion=None)
            return
        slot = getattr(self, "active_temp_slot", 0)
        if not (0 <= slot < len(presets)):
            slot = 0
        if self.silo_depth(slot) >= MAX_SILO_DEPTH:
            parent = self.silo_parent_of(slot)
            if parent is not None and (0 <= parent < len(presets)):
                slot = parent
        self.new_child_silo(slot)

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
        # Explicit blank creation of a normal silo: the same post-creation
        # defaults apply (clipboard seed + optional color) as plain NEW.
        self._apply_new_silo_defaults(new_idx, is_archive=False)

    # -- T-589: multi-select silos + batch ops --------------------------------
    def _silo_sel(self):
        """The set of currently latched silo global indices.

        Backed by ``data["silo_selected"]`` — a per-category list that is
        persisted like pins and ticks, so a latched selection survives a
        project switch, a profile reload and a restart. The set here is a live
        view; ``_persist_silo_selection`` writes it back.
        """
        raw = self.data.get("silo_selected")
        if not isinstance(raw, list):
            raw = []
            self.data["silo_selected"] = raw
        current = getattr(self, "_silo_selection", None)
        loaded = getattr(self, "_silo_selection_source", None)
        if not isinstance(current, set) or loaded is not raw:
            self._silo_selection = {i for i in raw
                                    if isinstance(i, int) and i >= 0}
            self._silo_selection_source = raw
        return self._silo_selection

    def _persist_silo_selection(self):
        """Write the latched set back into the per-category store.

        The list object is an alias into ``silo_selected_all[category]``, so it
        is mutated in place — rebinding it would orphan the category's data
        exactly like the temp_presets aliasing trap.
        """
        raw = self.data.get("silo_selected")
        if not isinstance(raw, list):
            raw = []
            self.data["silo_selected"] = raw
        raw[:] = sorted(self._silo_sel())
        self._silo_selection_source = raw
        self.mark_dirty("settings")

    def toggle_silo_selection(self, idx):
        """Ctrl+click: latch/unlatch one silo in the selection.

        The selection is a FOCUS set, not a transient hover: it survives
        switching silos, projects and restarts, and is released only by the
        same Ctrl+click, Ctrl+triple-click, the context menu, or a batch op.
        """
        sel = self._silo_sel()
        sel.discard(idx) if idx in sel else sel.add(idx)
        self._silo_sel_anchor = idx
        self._persist_silo_selection()
        self.refresh_temp_presets()

    def unselect_silo(self, idx):
        """Context menu: release exactly this silo, keep the rest latched."""
        sel = self._silo_sel()
        if idx not in sel:
            return
        sel.discard(idx)
        self._persist_silo_selection()
        self.refresh_temp_presets()

    def range_select_silos(self, idx):
        """Shift+click: select the contiguous range anchor..idx (inclusive)."""
        sel = self._silo_sel()
        anchor = getattr(self, "_silo_sel_anchor", idx)
        lo, hi = sorted((anchor, idx))
        n = len(self.data.get("temp_presets", []))
        sel.update(i for i in range(lo, hi + 1) if 0 <= i < n)
        self._persist_silo_selection()
        self.refresh_temp_presets()

    def clear_silo_selection(self):
        """Release every latched silo (Ctrl+triple-click / menu / batch op)."""
        if getattr(self, "_silo_selection", None):
            self._silo_selection = set()
            self._persist_silo_selection()
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
        if not self._durable_undo_or_refuse("Batch delete silos"):
            return
        # One sound and one UI rebuild for the whole operation.  The old loop
        # rebuilt/switch-rendered the editor after EVERY silo; deleting seven
        # selected rows held the GUI thread long enough for Windows to report
        # "Not Responding" (the 16:02 trace wrote seven trash records before
        # the event loop got a breath).
        started = time.monotonic()
        failures = []
        for i in sel:
            try:
                ok = self.trash_silo(
                    i, is_archive=False, skip_undo=True, defer_ui=True)
            except Exception:
                ok = False
                logger.debug("batch delete raised for silo %s", i)
            if not ok:
                failures.append(i)
            # Filesystem retirement is deliberately synchronous and durable,
            # but Windows messages need servicing between complete items.  User
            # input stays excluded, so nobody can mutate the half-finished
            # selection while paint/window-system events keep the app alive.
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
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
        self._persist_silo_selection()
        if len(failures) != len(sel):
            # T-1261: ONE success cue for the whole batch, and only when at
            # least one silo was actually deleted. The cue used to fire
            # before the loop, so a batch where every retirement failed
            # still sounded exactly like a completed delete.
            self.sound_manager.play("delete")
            presets = self.data.get("temp_presets", [])
            if presets:
                self.active_temp_slot = max(
                    0, min(self.active_temp_slot, len(presets) - 1))
                self.silo_page = self.active_temp_slot // max(
                    1, self._visible_silos)
                self._switch_to_slot(
                    self.active_temp_slot, initial=True, is_archive=False)
            self.cancel_editing()
        if failures:
            from fastprompter.core.logging import logger as _lg
            _lg.warning(
                "batch delete PARTIAL: %d of %d silo(s) not deleted "
                "(assets could not be retired); selection preserved for %s",
                len(failures), len(sel), failures)
        self.refresh_temp_presets()
        logger.info(
            "batch delete complete: %d/%d deleted in %.3fs (%d failed)",
            len(sel) - len(failures), len(sel), time.monotonic() - started,
            len(failures))

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
        self._flush_transfer_source_if_live(idx, is_archive)
        cur = self.text_area.toPlainText().strip()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setFont(QApplication.font())

        # -- batch actions (only when a multi-selection is active) -----------
        sel = self._silo_sel() if not is_archive else None
        if not is_archive and sel:
            n = len(sel)
            le = getattr(self, "_current_lang", "EN")
            menu.addAction(tr("💾 Save selected", le) + f" ({n})",
                           lambda: self.batch_save_selected_silos())
            menu.addAction(tr("🗑 Delete selected", le) + f" ({n})",
                           lambda: self.batch_delete_selected_silos())
            # Unselect acts on the silo the menu was opened ON; Unselect All
            # releases the whole latched set. Two separate controls, because
            # one control that means two things depending on the set size is
            # exactly the surprise the UI contract forbids.
            if idx in sel:
                menu.addAction(tr("✖ Unselect", le),
                               lambda i=idx: self.unselect_silo(i))
            menu.addAction(tr("✖ Unselect All", le) + f" ({n})",
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
        Gaps and gap names follow the silo (T-704). Parent/children, collapse
        and pins are source-local: detach both directions and clear them.
        Archive->normal translation rewrites the
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
            if is_archive_src or flat not in ("silo_colors", "silo_types", "silo_links", "silo_gap_names"):
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
        if not is_archive_src and isinstance(smap, dict):
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
        if not is_archive_src and isinstance(le, dict):
            sle = le.get(src_cat)
            dle = le.setdefault(dst_cat, {})
            if isinstance(sle, dict) and isinstance(dle, dict) and src_idx in sle:
                dle[dst_idx] = sle.pop(src_idx)

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
        if not is_archive_src and isinstance(tstore, dict):
            st = tstore.get(src_cat)
            dt = tstore.setdefault(dst_cat, [])
            if isinstance(st, list) and src_idx in st:
                st.remove(src_idx)
                if isinstance(dt, list) and dst_idx not in dt:
                    dt.append(dst_idx)

        # latched selection: same membership shape as the tick above, so a
        # transferred silo arrives selected in its new project instead of
        # leaving the highlight behind on whatever slot took its index.
        sstore = self.data.get("silo_selected_all")
        if not is_archive_src and isinstance(sstore, dict):
            ss = sstore.get(src_cat)
            ds = sstore.setdefault(dst_cat, [])
            if isinstance(ss, list) and src_idx in ss:
                ss.remove(src_idx)
                if isinstance(ds, list) and dst_idx not in ds:
                    ds.append(dst_idx)
                self._silo_selection_source = None

        if not is_archive_src:
            gaps = self.data.get("silo_gaps_all", {})
            source = gaps.get(src_cat, [])
            if src_idx in source:
                source.remove(src_idx)
                gaps.setdefault(dst_cat, []).append(dst_idx)

        # T-1227: the stable identity anchor travels WITH the silo. Text
        # history is keyed by silo_id, so the recovery chain follows too.
        try:
            self.state.move_silo_identity(
                src_cat, is_archive_src, src_idx, dst_cat, False, dst_idx)
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("silo identity transfer failed")

    _TRANSFER_STORE_KEYS = _PER_CATEGORY_STATE_KEYS

    def _flush_transfer_source_if_live(self, idx, is_archive=False):
        """Flush only the requested editor owner; never a same-index stranger."""
        if (not self.editing_snippet and idx == self.active_temp_slot
                and bool(is_archive) == bool(self.active_is_archive)):
            self.commit_current_text()
            self._cache_timer.stop()
            return True
        return False

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

    # --- durable transfer filesystem journal (T-1217 / CORE-004b) -----------
    _TRANSFER_JOURNAL = ".transfer_journal.json"

    def _transfer_journal_path(self):
        return os.path.join(self._files_root(), "_trash", self._TRANSFER_JOURNAL)

    def _write_transfer_journal(self, record):
        """Durably stage the physical-transfer record BEFORE the rename.

        Returns False on OSError: the caller MUST refuse the physical move
        without a journal, because the journal is the only recovery record that
        can reconstruct source<->destination ownership after a crash."""
        jp = self._transfer_journal_path()
        try:
            os.makedirs(os.path.dirname(jp), exist_ok=True)
            tmp = f"{jp}.tmp{int(time.time() * 1000)}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(record, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, jp)
            return True
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning("transfer journal write failed: %s", e)
            return False

    def _read_transfer_journal(self):
        jp = self._transfer_journal_path()
        try:
            with open(jp, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return None
        if isinstance(payload, dict) and payload.get("phase"):
            return payload
        return None

    def _clear_transfer_journal(self):
        try:
            os.remove(self._transfer_journal_path())
            return True
        except OSError as e:
            from fastprompter.core.logging import logger
            logger.warning("transfer journal clear failed: %s", e)
            return False

    def _reconcile_transfer_journal(self):
        """Reconcile a physical transfer from durable DB ownership + FS reality.

        The phase is only a receipt.  It is never authority: SQLite says who
        owns the folder, and the filesystem says where the bytes actually are.
        Ambiguous pairs stay journaled for an operator; recovery never guesses
        by deleting or moving an uncertain user folder.
        """
        record = self._read_transfer_journal()
        if not record:
            return
        src = record.get("src_dir")
        dst = record.get("dst_dir")
        src_cat = record.get("src_cat")
        dst_cat = record.get("dst_cat")
        src_idx = str(record.get("src_idx"))
        dst_idx = str(record.get("dst_idx"))
        source_key = ("archive_silo_folders_all"
                      if record.get("is_archive_src")
                      else "silo_folders_all")
        source_map = (self.data.get(source_key, {}).get(src_cat, {})
                      if isinstance(self.data.get(source_key), dict) else {})
        dest_map = (self.data.get("silo_folders_all", {}).get(dst_cat, {})
                    if isinstance(self.data.get("silo_folders_all"), dict) else {})
        source_owner = (isinstance(source_map, dict)
                        and source_map.get(src_idx) == record.get("src_name"))
        dest_owner = (isinstance(dest_map, dict)
                      and dest_map.get(dst_idx) == record.get("dst_name"))
        src_exists = bool(src and os.path.isdir(src))
        dst_exists = bool(dst and os.path.isdir(dst))
        from fastprompter.core.logging import logger

        try:
            if source_owner and not dest_owner:
                if src_exists and not dst_exists:
                    self._clear_transfer_journal()
                    return
                if not src_exists and dst_exists:
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    os.rename(dst, src)
                    self._clear_transfer_journal()
                    return
            elif dest_owner and not source_owner:
                if dst_exists and not src_exists:
                    self._clear_transfer_journal()
                    return
            elif (not source_owner and not dest_owner
                  and src_exists and not dst_exists):
                # PREPARED with no physical side effect: safe to retire.
                self._clear_transfer_journal()
                return

            logger.error(
                "transfer recovery required: ownership/filesystem ambiguous; "
                "source=%s (exists=%s owner=%s), destination=%s "
                "(exists=%s owner=%s); journal retained",
                src, src_exists, source_owner, dst, dst_exists, dest_owner)
        except Exception:
            logger.warning("transfer journal reconciliation failed; journal retained",
                           exc_info=True)

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
        live_source = self._flush_transfer_source_if_live(idx, is_archive)
        src_presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if not (0 <= idx < len(src_presets)) or not str(src_presets[idx]).strip():
            return False
        if target_cat not in self.data.get("categories", {}):
            return False
        cur_cat = self.get_current_category() or ""
        if target_cat == cur_cat and not is_archive:
            return False                      # already there

        dslot = self._acquire_silo_slot_for_category(target_cat)
        if dslot is None:
            return False

        text = src_presets[idx]

        # CORE-007: resolve the physical folder relocation BEFORE any
        # mutation. The source category root and the destination root are
        # resolved now; a down/unreachable custom root refuses the transfer
        # (fail closed: a folder mapping must never detach from the physical
        # folder it identifies). The destination name is reserved against
        # both the destination mapping and the destination directory, so a
        # name collision renames the incoming folder instead of clobbering.
        folder_plan = None
        stale_folder = False
        fsrc = self.data.get(
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
            # CORE-004: a mapped source folder that no longer exists on disk
            # has NO bytes to protect. Refusing the whole transfer over a dead
            # mapping would block a legitimate text+identity move (the user
            # deleted or moved the folder externally, or a stale mapping
            # survived a re-root). Drop the stale mapping and transfer WITHOUT
            # a physical folder move instead of leaving the silo stuck.
            if not os.path.isdir(src_dir):
                from fastprompter.core.logging import logger
                logger.warning("silo folder transfer: mapped source %s is "
                               "missing; dropping the stale mapping", src_dir)
                stale_folder = True
            else:
                dfold = self.data.get("silo_folders_all", {}).get(target_cat, {})
                taken = set(dfold.values())
                dst_comp_dir = os.path.join(root, comp_dst)
                dst_name, n = src_name, 2
                while dst_name in taken or os.path.exists(os.path.join(dst_comp_dir, dst_name)):
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
        # W2-003: bind the physical half to the canonical files-root identity
        # captured at action time. After a Files Folder re-root this record is
        # non-executable (preflight refuses it) instead of mutating the old root.
        snap["_fs_root"] = os.path.abspath(self._files_root())

        # Capture rollback state before publishing either half. Restore containers
        # in place so active aliases and existing widget references stay valid.
        before = copy.deepcopy(self.data)
        stacks = (list(self.data_undo_stack), list(self.data_redo_stack),
                  list(self._undo_kinds()))
        editor_text = self._editor_text_snapshot()
        moved = False
        record = None
        try:
            if folder_plan is not None:
                self._reconcile_transfer_journal()
                if self._read_transfer_journal() is not None:
                    return False
                record = {
                    "txn": f"{int(time.time() * 1000)}",
                    "phase": "PREPARED",
                    "src_cat": cur_cat, "src_idx": idx,
                    "dst_cat": target_cat, "dst_idx": dslot,
                    "src_dir": folder_plan[0], "dst_dir": folder_plan[1],
                    "src_name": folder_plan[2], "dst_name": folder_plan[3],
                    "is_archive_src": is_archive, "ts": time.time(),
                }
                if not self._write_transfer_journal(record):
                    return False
                os.makedirs(os.path.dirname(folder_plan[1]), exist_ok=True)
                os.rename(folder_plan[0], folder_plan[1])
                moved = True
                record["phase"] = "FILES_MOVED"
                if not self._write_transfer_journal(record):
                    raise RuntimeError("transfer journal FILES_MOVED update failed")
                self._detach_file_container_for(folder_plan[0])
            if stale_folder:
                fmap_src.pop(str(idx), None)
            dest = self.data.setdefault("temp_presets_all", {}).setdefault(target_cat, [])
            dest.extend([""] * max(0, dslot + 1 - len(dest)))
            dest[dslot] = text
            self._move_silo_identity(cur_cat, idx, target_cat, dslot, is_archive, folder_plan)
            src_presets[idx] = ""
            if not is_archive:
                for key in ("pinned_silos", "silo_collapsed"):
                    self.data[key][:] = [i for i in self.data[key] if i != idx]
                self.unnest_silo(idx)
                self.data["silo_children"].pop(idx, None)
                self.data["silo_children"].pop(str(idx), None)
            if live_source:
                self.clear_text(internal=True)
            snap["_transfer_dst_after"] = self._capture_category_stores(target_cat)
            snap["_transfer_src_after"] = self._snapshot_current()
            self._stamp_snapshot(snap)
            self.data_undo_stack.append(snap)
            self._push_undo_state(snap, "Transfer silo to project")
            self.mark_dirty()
            self.refresh_temp_presets()
            self.refresh_archive_panel()
            if record is not None:
                suspended = getattr(self, "_suspend_temp_sync", False)
                self._suspend_temp_sync = True
                try:
                    if not self.save_data_to_db(durable=True):
                        raise RuntimeError("durable transfer commit failed")
                finally:
                    self._suspend_temp_sync = suspended
                record["phase"] = "STATE_COMMITTED"
                if not self._write_transfer_journal(record):
                    from fastprompter.core.logging import logger
                    logger.error(
                        "transfer committed but journal acknowledgement update "
                        "failed; recovery journal retained")
                elif not self._clear_transfer_journal():
                    from fastprompter.core.logging import logger
                    logger.warning("transfer committed but journal clear failed")
        except Exception:
            from fastprompter.core.logging import logger
            logger.exception("Silo transfer failed; restoring both owners")
            if moved:
                try:
                    os.rename(folder_plan[1], folder_plan[0])
                    rollback_ok = True
                except OSError:
                    rollback_ok = False
                    logger.exception("Folder rollback failed: retained data at %s", folder_plan[1])
                if rollback_ok:
                    self._restore_transfer_data(self.data, before)
                    self.data_undo_stack[:] = stacks[0]
                    self.data_redo_stack[:] = stacks[1]
                    self._undo_kinds()[:] = stacks[2]
                    if (live_source and editor_text is not None
                            and self.text_area.toPlainText() != editor_text):
                        self.text_area.setPlainText(editor_text)
                    self._cache_timer.stop()
                    self.text_area.viewport().update()
                    if record is not None:
                        self._clear_transfer_journal()
                    return False
                logger.error(
                    "transfer recovery required: reverse rename failed; "
                    "bytes retained at %s; journal retained", folder_plan[1])
                self._restore_transfer_data(self.data, before)
                self.data_undo_stack[:] = stacks[0]
                self.data_redo_stack[:] = stacks[1]
                self._undo_kinds()[:] = stacks[2]
                return False
            self._restore_transfer_data(self.data, before)
            self.data_undo_stack[:] = stacks[0]
            self.data_redo_stack[:] = stacks[1]
            self._undo_kinds()[:] = stacks[2]
            if (live_source and editor_text is not None
                    and self.text_area.toPlainText() != editor_text):
                self.text_area.setPlainText(editor_text)
            self._cache_timer.stop()
            self.text_area.viewport().update()
            if record is not None:
                self._clear_transfer_journal()
            return False
        self.play_sound("snippet")
        return True

    @staticmethod
    def _restore_transfer_data(target, snapshot):
        """Restore JSON-shaped transaction data without orphaning live aliases."""
        for key in list(target):
            if key not in snapshot:
                del target[key]
        for key, value in snapshot.items():
            current = target.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                FastPrompter._restore_transfer_data(current, value)
            elif isinstance(current, list) and isinstance(value, list):
                current[:] = copy.deepcopy(value)
            else:
                target[key] = copy.deepcopy(value)

    def _transfer_to_snippet(self, idx, is_archive, target_cat=None):
        """Transfer silo content to a new snippet in the current (or given) category."""
        self._flush_transfer_source_if_live(idx, is_archive)
        presets = self.data["archive_temp_presets"] if is_archive else self.data["temp_presets"]
        if not 0 <= idx < len(presets) or not presets[idx] or not presets[idx].strip():
            return
        cat = target_cat if target_cat is not None else self.get_current_category()
        if cat not in self.data["categories"]:
            return
        if not cat:
            return
        slots = self.data["categories"][cat]
        if None not in slots:
            return
        return self.move_preset_cross_category(
            "arcsilo" if is_archive else "silo", idx, cat, slots.index(None))

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
        if not self._durable_undo_or_refuse("Nest silo"):
            return
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
                    # W2-003: bind to the canonical files root so a later
                    # Files Folder re-root makes this record non-executable.
                    rec["_fs_root"] = os.path.abspath(self._files_root())
                    # CORE-007: do NOT clear the merge journal here. The undo
                    # snapshot is only QUEUED at this point (a 1s debounce
                    # timer + a background writer later perform the actual
                    # durable os.replace). Clearing the write-ahead journal at
                    # queue time would erase the only physical transaction
                    # record if the process dies inside the debounce or the
                    # writer fails — startup would then see child files already
                    # moved under the parent while the DB still describes
                    # pre-nest ownership, with no way to reverse the moves.
                    # The journal is retained and the CLEAR is deferred into
                    # the undo writer, which removes it only AFTER the exact
                    # snapshot that carries this ledger has been durably
                    # published (see _write_undo_file).
                    self._save_undo_state(merge_journal_root=os.path.abspath(
                        self._files_root()))
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
        from fastprompter.ui.snippet_ops_mixin import (
            _merge_journal_write,
        )
        # W2-004/W2-002: the merge is part of the SAME undoable transaction as
        # the nesting itself. W2-002: the COMPLETE source -> collision-resolved
        # destination plan is computed BEFORE the first rename and written to a
        # durable write-ahead journal, so a crash after move 1 of N can be
        # deterministically reversed on restart instead of stranding child files
        # under the parent with no durable record.
        plan = []
        for n in names:
            try:
                dest = _unique_dest(dst, n)
                src_file = os.path.join(src, n)
                plan.append({
                    "original": os.path.abspath(src_file),
                    "trashed": os.path.abspath(dest),
                    "done": False,
                })
            except OSError:
                continue
        if not plan:
            return []
        if not _merge_journal_write(self._files_root(), plan):
            # fail closed: never start moving files without a durable recovery
            # record, mirroring the retirement journal precondition
            from fastprompter.core.logging import logger
            logger.warning("child file merge aborted: merge journal write failed")
            return []
        ledger = []
        moved = 0
        try:
            for rec in plan:
                src_file, dest = rec["original"], rec["trashed"]
                try:
                    # the same safe move primitive the file panel uses: no-clobber
                    # by construction, containment-checked at mutation time — a
                    # hand-rolled _unique_dest + shutil.move had a TOCTOU where a
                    # file appearing at the destination was silently overwritten
                    _move_into_container(src_file, dest, dst, identity)
                    moved += 1
                    rec["done"] = True
                    ledger.append((os.path.abspath(src_file), os.path.abspath(dest)))
                    _merge_journal_write(self._files_root(), plan)
                except OSError as e:
                    from fastprompter.core.logging import logger
                    logger.warning(f"Child file merge failed for {src_file}: {e}")
            try:
                if moved:
                    os.rmdir(src)
            except OSError:
                pass
        except Exception:
            # keep the journal: startup reconciliation reverses done moves
            raise
        # Journal is cleared by make_silo_child once the undo record carrying
        # the ledger has been persisted; leaving it in place until then keeps
        # the crash window closed (W2-002).
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
        """Pin/unpin with a DETERMINISTIC position contract (T-1270).

        The old shape only mutated ``pinned_silos``: raw order was never
        touched, so pinning showed the silo at the top of the pinned zone and
        unpinning dropped it back to its ORIGINAL raw slot — which can be
        several pages away. That teleport IS the operator's complaint ("I pin
        it, unpin it, and it jumped away").

        Contract, both directions explicit, one gesture = one undo record:

        * PIN   -> the silo MOVES into the pinned visual zone (head of it).
        * UNPIN -> it stays at the TOP of the unpinned zone, never back to a
          stale slot.

        Enforced by compacting the whole pinned set into the LEADING raw block
        in pinned-list order, so raw order, display order and the pin list
        agree — and a reload rebuilds exactly the same list. A pre-existing
        arbitrary pin set (a profile saved before this contract) is normalized
        by the same pass instead of being half-honoured.
        """
        if not (0 <= idx < len(self.data.get("temp_presets", []))):
            return
        pinned = self._slot_list("pinned_silos")
        if not self._durable_undo_or_refuse("Pin silo" if idx not in pinned
                                            else "Unpin silo"):
            return
        if idx in pinned:
            pinned.remove(idx)
        else:
            # A nested child cannot live in the top-level pinned zone: pinning
            # a child PROMOTES it. That is the one explicit child/pin contract —
            # the old shape left ``is_pinned`` true while rendering excluded the
            # child from the pinned order, i.e. pinned metadata with no effect.
            if self.silo_parent_of(idx) is not None:
                self.unnest_silo(idx)
            pinned.insert(0, idx)
        self._apply_pinned_block(pinned)

    def _apply_pinned_block(self, pinned):
        """Compact pinned silos into the leading raw block, in pinned order.

        ``pinned`` holds the desired pinned sequence (head first). The rest of
        the silos keep their existing relative order after the block, so a
        pin/unpin moves exactly the involved rows and nothing else shuffles.

        A nested child is dropped from the pin list here: the child/pin
        contract is "pin promotes", so a stale child pin (a silo nested after
        it was pinned, or data saved before the contract) is cleared instead of
        leaving ``is_pinned`` true with no effect on the rendered order.
        """
        temps = self.data.get("temp_presets", [])
        n = len(temps)
        children = {k for kids in self._children_map().values()
                    for k in kids if isinstance(k, int)}
        pins = [p for p in dict.fromkeys(pinned)
                if isinstance(p, int) and 0 <= p < n and p not in children]
        pinned[:] = pins
        rest = [i for i in range(n) if i not in set(pins)]
        order = pins + rest
        if order == list(range(n)):
            # Already a leading, ordered pinned block: the pin list is the only
            # thing that changed, so no slot permutation is needed.
            self.mark_dirty()
            self.refresh_temp_presets()
            return
        self._permute_silo_order(order)

    def _permute_silo_order(self, order):
        """Rebuild raw silo order from ``order`` (list of OLD indices, new first).

        A pin/unpin is a permutation of the whole list, not one swap: the
        pinned set has to become a contiguous leading block whatever the
        starting arrangement was. Every slot-index-keyed store is remapped in
        one pass, so identity travel and the document-owner stamps stay exact.
        """
        temps = self.data.get("temp_presets", [])
        n = len(temps)
        if sorted(order) != list(range(n)):
            return False
        docs = self.silo_docs
        from PyQt6.QtGui import QTextDocument
        while len(docs) < n:
            d = QTextDocument()
            d.setDefaultFont(self.text_area.font())
            d.setPlainText(temps[len(docs)])
            docs.append(d)
        new_pos = {old: new for new, old in enumerate(order)}
        self._suspend_cache = True
        temps[:] = [temps[i] for i in order]
        docs[:] = [docs[i] for i in order]
        if getattr(self, "active_is_archive", False) is False:
            self.active_temp_slot = new_pos.get(
                getattr(self, "active_temp_slot", 0),
                getattr(self, "active_temp_slot", 0))
        self._remap_silo_indices(lambda i: new_pos.get(i, i))
        self._rebind_silo_document_owners()
        self._stamp_active_document_owner()
        self._suspend_cache = False
        self.mark_dirty()
        self.refresh_temp_presets()
        return True

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
        pushed_undo = self.add_data_undo_state("Clear silo", durable=True)
        if pushed_undo is None:
            # T-1227 §17: the before-state could not be published durably —
            # the destructive clear is REFUSED (retryable).
            from fastprompter.core.logging import logger as _lg
            _lg.error("silo clear REFUSED (slot %d): durable undo-before "
                      "unavailable", idx)
            return
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
        if self.isVisible():
            self._insert_into_editor(text)
            return
        self.safe_set_clipboard(text)
        self.hide_and_save()
        QTimer.singleShot(150, weak_qt_callback(
            self, lambda window: window.simulate_ctrl_v()))

    def _insert_into_editor(self, text):
        cursor = self.text_area.textCursor()
        cursor.insertText(text)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.text_area.setFocus()
        self.mark_dirty()

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

    def hotkey_conflicts(self):
        """Configured hotkeys refused because the editor owns the sequence.

        T-1269C append. Empty for every profile that leaves the editing keys
        alone -- which is every shipped default. A non-empty list means the
        user's own settings mapped a command onto Ctrl+A/C/V/X/Z/Y and that
        command did NOT take the key: the editor did, deterministically, so
        Ctrl+V cannot be swallowed by a shortcut nobody knew was there. Each
        entry names the losing command, the sequence, and the editor action
        that kept it.
        """
        return [dict(row) for row in getattr(self, "_hotkey_conflicts", ())]

    def setup_global_shortcuts(self):
        for shortcut in getattr(self, "_app_shortcuts", []):
            shortcut.deleteLater()
        self._app_shortcuts = []

        # Physical-key fallback so every shortcut below keeps working on a
        # non-Latin keyboard layout (Qt matches the character, not the key).
        from fastprompter.ui.layout_shortcuts import LayoutIndependentShortcuts

        # Conflicts detected while registering (T-1269C append). Rebuilt on every
        # refresh so a settings change cannot leave a stale report behind.
        self._hotkey_conflicts = []
        flt = getattr(self, "_layout_shortcuts", None)
        if flt is None:
            flt = LayoutIndependentShortcuts(self)
            self._layout_shortcuts = flt
            QApplication.instance().installEventFilter(flt)
        flt.clear()

        def reserve_conflict(key_name, seq_str, seq):
            """Refuse a configurable hotkey that would steal an editor binding.

            Returns the reserved action's name, or None when the sequence is
            free or this hotkey is its legitimate owner. The report names the
            owner, the loser and the sequence, so the collision is resolved
            deterministically (the editor keeps the key) and visibly, instead
            of one command silently eating the other's keystroke.
            """
            action = editor_shortcut_conflict(key_name, seq)
            if action is None:
                return None
            self._hotkey_conflicts.append({
                "hotkey": key_name,
                "sequence": _portable_sequence(seq),
                "editor_action": action,
            })
            from fastprompter.core.logging import logger
            logger.warning(
                "Hotkey %r is configured as %s, which the editor owns for "
                "%r; leaving %s with the editor so editing keeps working "
                "instead of two commands sharing one keypress.",
                key_name, _portable_sequence(seq), action, _portable_sequence(seq),
            )
            return action

        def add_shortcut(key_name, default_seq, slot, context=Qt.ShortcutContext.WindowShortcut):
            seq_str = self.data.get(key_name, default_seq)
            if not seq_str: return
            seq = QKeySequence(seq_str)
            if reserve_conflict(key_name, seq_str, seq) is not None:
                return
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
        add_shortcut("toggle_files_hotkey", "Alt+F", self.toggle_file_container)
        add_shortcut("lock_window_hotkey_alt", "", self.toggle_lock)
        add_shortcut("always_on_top_hotkey_alt", "", self.toggle_always_on_top)
        add_shortcut("toggle_sidebar_hotkey_alt", "",
                     lambda: self.toggle_visibility(force_sidebar=True))
        add_shortcut("hide_on_clickout_hotkey_alt", "", self.toggle_hide_on_clickout)
        add_shortcut("toggle_files_hotkey_alt", "", self.toggle_file_container)

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
        # T-1244 global master mute. Registered through add_shortcut like the
        # others so it is remappable in settings, but its sound is SELF (see
        # HOTKEY_SOUND_SELF_EXTRA) — the toggle fires its own cue.
        add_shortcut("hk_audio_mute", "Ctrl+M", self.toggle_audio_mute)

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
        for i, s in enumerate(self.data.get("categories", {}).get(cat, [])):
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
        # Pie menu passes the ORIGINAL index into the raw category list
        # (index into the unfiltered categories[cat]), never a re-filtered
        # position. Using the raw list directly keeps the index stable even
        # when earlier entries are None (deleted snippet placeholders).
        raw = self.data["categories"].get(cat, [])
        if 0 <= idx < len(raw):
            snip = raw[idx]
            if snip is not None:
                self.auto_paste(snip["text"])

    def cycle_snap_corner(self):
        """Ctrl+Q: open the FancyZones picker on the monitor under the cursor.

        (Kept under the old name so the existing hk_snap binding, tooltips
        and any saved user hotkey keep working.)

        In Fast mode the picker never appears: each press steps to the next
        zone of the page chosen in Settings.
        """
        self.play_sound("snap")
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

        new_text = f"{lines} L" if lines else ""
        if lbl.text() != new_text:
            lbl.setText(new_text)
        self._set_topbar_semantic("lbl_line_count", bool(new_text))
        if self.data.get("show_token_count", "False") == "True":
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
            self._set_topbar_semantic("lbl_token_count", False)
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
            new_tip = tr(
                "Estimated input tokens for the open silo\n"
                "~{} characters, {} words\n"
                "Weighting is configurable in Settings > Editor > Lines",
                getattr(self, "_current_lang", "EN")
            ).format(raw_chars, word_count)
        else:
            weight = max(1.0, min(20.0, weight))
            tokens = int(round(raw_chars / weight))
            new_tip = tr(
                "Estimated input tokens for the open silo\n"
                "{} characters, ~ words\n"
                "Weighting is configurable in Settings > Editor > Lines",
                getattr(self, "_current_lang", "EN")
            ).format(raw_chars)

        new_text = f"~{self._short_count(tokens)} T" if tokens else ""
        if lbl.text() != new_text:
            lbl.setText(new_text)
        if lbl.toolTip() != new_tip:
            lbl.setToolTip(new_tip)
        self._set_topbar_semantic("lbl_token_count", bool(new_text))

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

        now_str = f"{daypart} {ts}" if profile_flag(self.data, "date_daypart") else ts
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
            text = self._editor_text_snapshot()
        except Exception:
            return
        if text is None:
            # T-1250: keep the currently rendered pane; an unavailable
            # snapshot must never rebuild it as an empty document.
            return
        if text == getattr(self, "_rendered_visual_text", None):
            return
        if idx == 1:
            kw = self._get_or_create_kanban_widget()
            kw.load_markdown(text)
        else:
            tw = self._get_or_create_table_widget()
            tw.load_markdown(text)
        self._rendered_visual_text = text

    def _editor_text_snapshot(self):
        """PERF-004: one canonical immutable whole-document snapshot.

        Keyed by (document identity, revision): every settled-edit consumer
        (visual rebuild, typo scan, Sync push, cache tick) that reads the
        SAME revision shares ONE O(document) toPlainText() instead of each
        materializing a fresh full string on the GUI thread. A document
        switch changes the identity key; any revision change re-extracts.
        """
        ta = getattr(self, "text_area", None)
        if ta is None or sip.isdeleted(ta):
            return None
        try:
            doc = ta.document()
            if doc is None or sip.isdeleted(doc):
                return None
            ident = id(doc)
            rev = doc.revision()
        except Exception:
            return None
        cache = getattr(self, "_editor_text_snaps", None)
        if cache is None:
            cache = self._editor_text_snaps = {}
        entry = cache.get(ident)
        if entry is not None and entry[1] == rev:
            try:
                # id(doc) is recycled, so the entry is only valid while the
                # exact document it was computed from is still alive
                if entry[0]() is doc:
                    return entry[2]
            except TypeError:
                pass
        try:
            text = ta.toPlainText()
        except Exception:
            return None
        import weakref
        try:
            cache[ident] = (weakref.ref(doc), rev, text)
        except TypeError:
            return text
        if len(cache) > 4:
            for stale in [k for k in cache if k != ident]:
                cache.pop(stale, None)
        return text

    _snapshot_refusal_last_log = 0.0

    def _log_snapshot_unavailable(self, operation, is_archive=False):
        """T-1250: bounded diagnostic for a MUTATING snapshot refusal.

        Time-throttled (one line per minute at most) so a persistently
        unreadable editor cannot spam the log; the non-mutating visual/
        typecheck skips stay silent. Identifies the operation, category,
        silo slot and archive flag -- never document contents."""
        now = time.monotonic()
        if now - getattr(self, "_snapshot_refusal_last_log", 0.0) < 60.0:
            return
        self._snapshot_refusal_last_log = now
        try:
            from fastprompter.core.logging import logger as _lg
            _lg.warning(
                "T-1250 editor snapshot unavailable: %s refused; no text "
                "published (category=%r slot=%s space=%s snippet=%s)",
                operation,
                self.get_current_category(),
                getattr(self, "active_temp_slot", -1),
                "archive" if is_archive else "normal",
                bool(getattr(self, "editing_snippet", None)))
        except Exception:
            pass

    def _on_text_changed(self):
        # A save must never persist pre-edit text: _last_cached_text holds the
        # editor snapshot from the LAST cache tick, and a save between a text
        # change and the next tick would otherwise read STALE content (a
        # keystroke's data-loss window). Every edit invalidates the cache so a
        # save falls through to the live editor text; the cache still serves
        # the common no-edit case.
        self._last_cached_text = None
        # PERF-004: revision-aware snapshots are keyed by document revision;
        # an edit bumps the revision so every later consumer re-extracts.
        try:
            self._editor_text_snaps = None
        except Exception:
            pass
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
            current_text = self._editor_text_snapshot()
            if current_text is None:
                # T-1250: an unreadable editor is NOT an empty document. A
                # failed observation must never publish "" as authoritative
                # user content: no silo/snippet/archive mutation, no dirty
                # flag, no last-edited stamp, and the cached text stays
                # explicitly non-authoritative.
                self._last_cached_text = None
                self._log_snapshot_unavailable("cache_current_text",
                                               bool(getattr(
                                                   self, "active_is_archive",
                                                   False)))
                return
            self._last_cached_text = current_text
            if not self.editing_snippet:
                is_arc = getattr(self, "active_is_archive", False)
                slot = self.active_temp_slot
                doc = self._active_doc()
                # T-1227: the debounce flush obeys the same ownership
                # contract as every authoritative save. A mismatch refuses
                # the write (recovery artifact) instead of landing the text
                # in whatever slot the (possibly stale) index points to.
                if not self._document_owner_matches(slot, is_arc, doc=doc):
                    self._refuse_unowned_flush(slot, is_arc, doc,
                                               current_text)
                else:
                    self._last_cached_text = current_text
                    target = self.data["archive_temp_presets"] if is_arc else self.data["temp_presets"]
                    if 0 <= slot < len(target):
                        old_text = target[slot]
                        target[slot] = current_text
                        self._remember_active_document_text(current_text)
                        try:
                            doc._fastprompter_flushed_rev = doc.revision()
                        except (RuntimeError, AttributeError):
                            pass
                        if current_text != old_text:
                            self.mark_dirty("arc" if is_arc else "temp")
                            self.silo_last_edited[slot] = int(time.time())
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
        # PERF-002: an ordinary hide needs durability of the KNOWN dirty state,
        # not a full re-scan of every clean domain. durable=True commits the
        # dirty generations synchronously without the exhaustive force scan.
        ok = self.save_data_to_db(durable=True)
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
        if getattr(self, "_quit_in_progress", False):
            return
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
        self._quit_in_progress = True
        try:
            try:
                self.sound_manager.play_to_completion("quit")
            except Exception:
                # Audio must never turn a successful durable quit into a refusal.
                from fastprompter.core.logging import logger as _log
                _log.exception("Quit sound playback failed")
            QApplication.quit()
        finally:
            # QApplication.quit() is asynchronous.  This reset mainly keeps
            # patched tests and a refused outer platform quit retryable; a
            # second click during playback is blocked by the flag above.
            self._quit_in_progress = False

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
            if hasattr(self, "_watcher_commit_quiesce"):
                self._watcher_commit_quiesce()
            self._logical_finalized = True
        else:
            if hasattr(self, "_watcher_rollback_quiesce"):
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


def _release_probe_marker(argv):
    """Release-probe-only seam: a strict marker token from ``--release-probe-write``.

    Used by tools/probe_release.py to prove a frozen EXE can write through the
    app's own settings persistence and survive a graceful restart. Not a user
    feature: the value is charset-restricted and merely stored.
    """
    prefix = "--release-probe-write="
    for arg in argv:
        if arg.startswith(prefix):
            value = arg[len(prefix):].strip()
            if value and len(value) <= 120 and all(
                    ch.isalnum() or ch in "-_" for ch in value):
                return value
    return ""


def main_entry():
    from fastprompter.core.instance_lock import (
        HANDED_OFF,
        PRIMARY,
        InstanceLock,
        bootstrap_ownership,
    )
    from fastprompter.core.ipc_server import request_show
    from fastprompter.core.logging import logger as _log

    # Writer ownership is the process's, not the socket's. If a live instance
    # already owns the database mutex we must NOT open a second writer no
    # matter how quiet its event loop is — the best we may do is ask it to
    # show itself, and exit when it answers or when it stays silent.
    # W2-001: only PRIMARY may proceed. A no-ACK owner is never killed and
    # the mutex is never force-reclaimed; the ownership verdict is final.
    lock = InstanceLock()
    role, reason = bootstrap_ownership(lock, request_show)
    if role != PRIMARY:
        lock.release()
        if role == HANDED_OFF:
            return
        _log.warning("FastPrompter startup refused: %s", reason)
        from fastprompter.core.ipc_server import _LAST_SAW_SERVER
        if _LAST_SAW_SERVER:
            return  # owner alive but busy — exit silently; window comes to front
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
    from PyQt6.QtWidgets import QToolTip
    QToolTip.setFont(no_aa(QFont(resolve_family("Verdana"), 10)))
    app.setQuitOnLastWindowClosed(False)

    # Create and show window
    window = FastPrompter()
    window.show()
    window.raise_()
    window.activateWindow()

    probe_marker = _release_probe_marker(sys.argv)
    if probe_marker:
        def _write_release_probe_marker():
            try:
                window.data["release_probe_marker"] = probe_marker
                ok = window.save_data_to_db(force=True, durable=True)
                _log.info("release probe marker committed: %s", bool(ok))
            except Exception:
                _log.exception("release probe marker write failed")
        QTimer.singleShot(2000, _write_release_probe_marker)

    # FREEZE-2026-08-30: heartbeat watchdog — log any GUI-thread stall so a
    # "Not Responding" freeze leaves a stack trace instead of silence.
    try:
        _start_gui_watchdog(window)
    except Exception:
        pass

    # Install hotkey filter for global hotkeys
    filter_obj = HotkeyFilter(window)
    app.installNativeEventFilter(filter_obj)

    # W2-002: Session management / commitDataRequest hook before event loop
    def _on_commit_data_request(session_manager):
        if getattr(window, "_logical_finalized", False):
            return
        if not window._pre_quit_logical_finalize():
            from fastprompter.core.logging import logger as _log
            _log.error("OS session commitDataRequest: logical finalization refused")
            try:
                session_manager.cancel()
            except Exception:
                pass
            try:
                if hasattr(window, "tray_icon"):
                    window.tray_icon.show()
                window.show()
                window.raise_()
                window.activateWindow()
            except Exception:
                pass

    def _on_about_to_quit():
        if not getattr(window, "_logical_finalized", False):
            from fastprompter.core.logging import logger as _log
            _log.warning(
                "aboutToQuit fired without prior logical finalization; "
                "performing best-effort durable save before process termination")
            try:
                window.save_data_to_db(force=True)
            except Exception:
                _log.exception("aboutToQuit best-effort save failed")

    try:
        app.commitDataRequest.connect(_on_commit_data_request)
    except Exception:
        pass
    try:
        app.aboutToQuit.connect(_on_about_to_quit)
    except Exception:
        pass

    exit_code = 0
    clean = True
    try:
        exit_code = app.exec()
    finally:
        clean = _shutdown_application(window, app, lock)

    sys.exit(exit_code if clean else (exit_code or 1))


def _shutdown_application(window, app, lock):
    """Retire every app-owned writer before releasing process ownership.

    A timeout is fail-closed: the mutex remains owned until process death, when
    Windows marks it abandoned. That is safer than allowing a new primary to
    start while an old worker can still publish files.
    """
    from fastprompter.core.logging import logger as _log

    clean = True
    # T-1238-C4.4: audio timers and the Problip scheduler are retired BEFORE
    # the transports go away, so no QTimer callback can arrive after its
    # QObject is gone and no cue can sound after the window is closing.
    for attribute in ("problip_controller", "voice_controller",
                      "ambience_controller"):
        controller = getattr(window, attribute, None)
        if controller is None:
            continue
        try:
            # CORE-002: a controller whose owned worker survives its bounded
            # retirement returns False. That worker can still emit against a
            # logically closed controller, so it is reported into the same
            # fail-closed accounting as a timed-out limit worker rather than
            # being silently discarded.
            if controller.shutdown() is False:
                _log.error("%s shutdown did not retire its worker", attribute)
                clean = False
        except Exception:
            _log.debug("%s shutdown failed", attribute, exc_info=True)
    sound = getattr(window, "sound_manager", None)
    if sound is not None:
        try:
            sound.stop_all_sound()
        except Exception:
            _log.debug("stop_all_sound failed during shutdown", exc_info=True)
        try:
            sound.shutdown()
        except Exception:
            _log.debug("sound shutdown failed", exc_info=True)

    # Quota probing owns a thread pool AND real ``codex`` child processes, so
    # it is retired first: before the final save, before the DB handle closes,
    # before the ownership mutex is released, and before the refused-
    # finalization return below. A probe still running past this point could
    # publish into a torn-down window or hold a child alive past interpreter
    # finalization, which ends the process with an access violation instead of
    # an exit code.
    try:
        limit_service = getattr(window, "limit_service", None)
        if limit_service is not None and limit_service.shutdown() is False:
            _log.error("AI usage-limit worker shutdown TIMED_OUT")
            clean = False
    except Exception:
        _log.exception("AI usage-limit worker shutdown FAILED")
        clean = False

    # Global-pool runnables (external sync collection, silo/folder scans) run
    # Python and are joined by nobody. Drain them before any writer, DB handle
    # or lock is retired -- and before the refused-finalization return below --
    # so a late result can never touch torn-down state.
    if drain_qt_threadpool() is False:
        # Fail-closed: an app-owned global-pool runnable may still be
        # executing Python. Releasing the writer mutex now would let another
        # FastPrompter process take ownership while this one still mutates
        # files/DB state, so clean retirement is impossible. The bounded
        # wait stays bounded; remaining physical teardown below still runs
        # so the process converges toward termination.
        _log.error(
            "background file workers still running at shutdown; "
            "global Qt thread pool did not drain within the bounded wait -- "
            "writer mutex remains owned until process death")
        clean = False

    # W2-002: Logical finalization (watcher quiescence + final durable save)
    # is strictly pre-exit and occurs before the Qt event loop dies.
    # _shutdown_application owns PHYSICAL retirement only.
    setattr(window, "_in_physical_teardown", True)
    try:
        if hasattr(window, "close"):
            window.close()
    except Exception:
        _log.exception("application window close failed")

    # Limit probes finish on a Python worker pool.  Retired at the very top of
    # this function, before finalization could refuse and return.

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
        # CORE-003: drain core-state SQLite backup workers BEFORE the live
        # connection is closed / process ownership is released. A backup
        # writer still running after this point could publish stale or
        # partial recovery artifacts once SQLite is gone.
        from fastprompter.core.state import _drain_all_db_backups
        if not _drain_all_db_backups():
            _log.error("core-state backup worker shutdown TIMED_OUT")
            clean = False
    except Exception:
        _log.exception("core-state backup drain FAILED")
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
