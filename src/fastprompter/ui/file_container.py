"""Per-silo file container — Eagle/PureRef-lite asset drawer.

Each silo owns a real folder on disk: <data>/files/<category-slug>/<silo-title-slug>/.
The panel is a thin window over that folder: drop files in (they are copied),
drag them out (real file URLs any app accepts), double-click to open,
right-click for the usual file verbs (Open, Show in Explorer, Copy path,
Rename, Export to..., Delete).

No database, no sidecar metadata — the folder IS the container. The structure
stays fully readable and portable outside FastPrompter: it is keyed by the
silo's first-line title (stable across silo reorders), not by slot index.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from PyQt6.QtCore import (
    QFileSystemWatcher,
    QMimeData,
    QObject,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDrag, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.logging import logger
from fastprompter.core.translations import tr
from fastprompter.utils.path_safety import (
    capture_resolved_root,
    is_within_captured_root,
    safe_join,
    validate_component,
)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}
_SLUG_STRIP = re.compile(r"[#*_`•\[\]]+")


# Threshold above which a File Container import/export is handed to the
# shared worker instead of running synchronously on the GUI thread. Small
# operations (a few KB text files) stay synchronous — an industrial scheduler
# for a 20-byte file is noise.
_ASYNC_THRESHOLD_BYTES = 512 * 1024
_ASYNC_THRESHOLD_FILES = 20

# Process-wide shared container-operation worker (same pattern as the sync
# worker: one thread, never torn down per-window, explicit global shutdown).
_CONTAINER_WORKER = None
_CONTAINER_THREAD = None
_CONTAINER_SHUTDOWN_TIMEOUT_S = 5.0
_CONTAINER_PENDING = 0
_CONTAINER_PENDING_CONDITION = threading.Condition()


class _ContainerOpWorker(QObject):
    """Runs File Container copy/move requests on its own thread.

    The request is IMMUTABLE: every containment/no-clobber decision was made
    by the caller (the same _copy_atomic / _move_into_container primitives
    used synchronously for small ops). The worker reports which destinations
    landed and which failed, with exact source paths.

    The dispatch->run connection is made by the factory AFTER moveToThread:
    PyQt captures the receiver's thread affinity at CONNECT time, and a
    self-connection made before moveToThread runs ``_run`` on the GUI thread.
    """

    dispatch = pyqtSignal(object, object)              # request, request_id
    done = pyqtSignal(object, object, object, object)  # id, request, done, errors

    def __init__(self):
        super().__init__()

    def _run(self, request, request_id):
        global _CONTAINER_PENDING
        done = []
        errors = []
        root = request.get("root")
        root_identity = request.get("root_identity")
        try:
            for item in request.get("items", ()):
                try:
                    op, src, dest, is_dir = item
                    mutation_root = root
                    mutation_identity = root_identity
                    if request.get("policy") == "EXTERNAL_EXPORT":
                        mutation_root = os.path.dirname(dest)
                        key = os.path.normcase(os.path.abspath(mutation_root))
                        mutation_identity = request["destination_identities"].get(key)
                    if op == "move":
                        _move_into_container(
                            src, dest, mutation_root, mutation_identity
                        )
                    else:
                        _copy_atomic(
                            src, dest, is_dir, mutation_root, mutation_identity
                        )
                    done.append(dest)
                except Exception as exc:
                    src = item[1] if len(item) > 1 else repr(item)
                    errors.append((src, str(exc)))
                    logger.error(
                        "File Container command %s (%s) failed for %s: %s",
                        request_id, request.get("kind", "unknown"), src, exc,
                    )
            logger.info(
                "File Container command %s completed: %d succeeded, %d failed",
                request_id, len(done), len(errors),
            )
            self.done.emit(request_id, request, done, errors)
        finally:
            with _CONTAINER_PENDING_CONDITION:
                _CONTAINER_PENDING -= 1
                _CONTAINER_PENDING_CONDITION.notify_all()


def container_worker():
    """The shared container-op worker, created once per process."""
    global _CONTAINER_WORKER, _CONTAINER_THREAD
    if _CONTAINER_WORKER is None:
        thread = QThread()
        thread.setObjectName("fastprompter-container")
        worker = _ContainerOpWorker()
        worker.moveToThread(thread)
        worker.dispatch.connect(worker._run)   # AFTER moveToThread: queued
        thread.start()
        _CONTAINER_WORKER = worker
        _CONTAINER_THREAD = thread
    return _CONTAINER_WORKER


def dispatch_container_command(request, request_id):
    """Queue one FIFO command and track its complete physical lifetime."""
    global _CONTAINER_PENDING
    worker = container_worker()
    with _CONTAINER_PENDING_CONDITION:
        _CONTAINER_PENDING += 1
    try:
        worker.dispatch.emit(request, request_id)
    except Exception:
        with _CONTAINER_PENDING_CONDITION:
            _CONTAINER_PENDING -= 1
            _CONTAINER_PENDING_CONDITION.notify_all()
        raise
    return worker


def container_worker_shutdown_global():
    """Stop the shared container worker at application exit (bounded).

    The globals are nulled (mid-session teardown can spawn a fresh worker)
    and the retired wrappers are kept for the process lifetime: Python
    teardown destroying a worker whose thread was stopped mid-reference is an
    access-violation class.
    """
    global _CONTAINER_WORKER, _CONTAINER_THREAD
    thread = _CONTAINER_THREAD
    worker = _CONTAINER_WORKER
    success = True
    deadline = time.monotonic() + _CONTAINER_SHUTDOWN_TIMEOUT_S
    with _CONTAINER_PENDING_CONDITION:
        while _CONTAINER_PENDING and time.monotonic() < deadline:
            _CONTAINER_PENDING_CONDITION.wait(
                max(0.0, deadline - time.monotonic())
            )
        if _CONTAINER_PENDING:
            logger.error(
                "File Container worker shutdown TIMED_OUT with %d command(s) pending",
                _CONTAINER_PENDING,
            )
            return False
    if thread is not None and thread.isRunning():
        thread.quit()
        from fastprompter.main import wait_thread_seconds
        success = wait_thread_seconds(
            thread, max(0.0, deadline - time.monotonic()), "File Container worker"
        )
    if success:
        _CONTAINER_WORKER = None
        _CONTAINER_THREAD = None
        if worker is not None or thread is not None:
            _RETIRED_CONTAINER_WORKERS.append((worker, thread))
    return success


_RETIRED_CONTAINER_WORKERS = []# ascii + lowercase cyrillic (U+0430-044F, U+0451) survive in slugs
_SLUG_BAD = re.compile(
    "[^a-z0-9" + chr(0x0430) + "-" + chr(0x044F) + chr(0x0451) + "\\- ]+"
)


# Ctrl+E timestamps — "(17.07 - 04:19)", "(17 Jul - 04:19:33)" etc. They
# change on every re-stamp, so they must NEVER leak into the folder slug
# or each refresh would detach the silo from its files.
_SLUG_TIMESTAMP = re.compile(r"\([^()]*\d{1,2}[:.]\d{2}[^()]*\)")


def silo_slug(text):
    """Folder-safe slug from a silo's first line. Keyed by title, not slot
    index, so the folder follows the silo through reorders. Timestamps in
    the title are ignored (they change on every Ctrl+E refresh)."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    first = _SLUG_TIMESTAMP.sub("", first)
    first = _SLUG_STRIP.sub("", first).strip().lower()
    first = _SLUG_BAD.sub("", first)
    first = re.sub(r"\s+", "-", first).strip("-")[:40].strip("-")
    return first or "untitled"


def silo_files_dir(root, category, silo_text):
    """Absolute folder for a silo's files (not created here)."""
    return os.path.join(root, silo_slug(category), silo_slug(silo_text))


def silo_file_count(root, category, silo_text):
    """How many entries a silo's folder holds (0 if the folder doesn't exist)."""
    try:
        return len(os.listdir(silo_files_dir(root, category, silo_text)))
    except OSError:
        return 0


def _fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024 / 1024 / 1024:.2f} GB"


def _dir_size(path, _cap=2000):
    """Recursive size, capped at _cap files so a giant dropped folder
    can't stall silo switching (tooltip precision isn't worth a freeze)."""
    total, seen = 0, 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
            seen += 1
            if seen >= _cap:
                return total
    return total


# P2-24: the header tooltip used to re-walk the folder tree on the GUI
# thread on every refresh, so an HDD/NAS silo with subfolders froze the
# window on each switch. The summary is now cached per
# (folder, direct-listing signature, lang): a change IN this folder
# (drop/remove) invalidates immediately via the signature; a change inside
# a SUBfolder is bounded by the short TTL (stale tooltip at most
# _SUMMARY_TTL seconds — the live 📁 count badge never caches).
_SUMMARY_TTL = 2.0
_folder_summary_cache = {}


def _summary_now():
    return time.monotonic()


def folder_summary(d, lang="EN"):
    """Tooltip text for a resolved folder: item count + total size + per-ext.

    Cached (P2-24): the expensive recursive walk only runs when the folder's
    own listing changed or the short TTL expired — never on every refresh.
    """
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    key = (os.path.normcase(os.path.abspath(d)),
           tuple(sorted(names)), lang)
    now = _summary_now()
    hit = _folder_summary_cache.get(key)
    if hit is not None and now - hit[0] < _SUMMARY_TTL:
        return hit[1]
    if not names:
        text = tr("No files yet", lang)
        _folder_summary_cache[key] = (now, text)
        return text
    counts, sizes, total = {}, {}, 0
    for n in names:
        p = os.path.join(d, n)
        if os.path.isdir(p):
            ext, s = "folder", _dir_size(p)
        else:
            ext = os.path.splitext(n)[1].lower() or "no ext"
            try:
                s = os.path.getsize(p)
            except OSError:
                s = 0
        counts[ext] = counts.get(ext, 0) + 1
        sizes[ext] = sizes.get(ext, 0) + s
        total += s
    lines = [f"{len(names)} item(s) · {_fmt_size(total)}"]
    for ext in sorted(counts, key=lambda e: -sizes[e]):
        lines.append(f"  {ext} ×{counts[ext]} · {_fmt_size(sizes[ext])}")
    if len(lines) > 13:
        lines = lines[:13] + [f"  … and {len(counts) - 12} more types"]
    text = "\n".join(lines)
    _folder_summary_cache[key] = (now, text)
    # bounded cache: drop expired entries when it outgrows its working set
    if len(_folder_summary_cache) > 64:
        for stale in [k for k, (t, _v) in _folder_summary_cache.items()
                      if now - t >= _SUMMARY_TTL]:
            _folder_summary_cache.pop(stale, None)
    return text


def _unique_dest(folder, name):
    """foo.txt -> foo (2).txt until the name is free in folder."""
    dest = os.path.join(folder, name)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(folder, f"{stem} ({n}){ext}")):
        n += 1
    return os.path.join(folder, f"{stem} ({n}){ext}")


def _require_container_destination(root, root_identity, candidate):
    if root is None:
        return
    identity = (
        capture_resolved_root(root) if root_identity is None else root_identity
    )
    if not is_within_captured_root(root, identity, candidate):
        raise OSError(
            "destination no longer resolves inside the captured container root"
        )


def _publish_new_file(tmp, dest, root=None, root_identity=None):
    """Publish a temp file as a NEW file WITHOUT clobbering anything.

    ``os.replace`` is correct when replacing a file FastPrompter already
    owns, but dangerous for a create-new operation: a file that appeared at
    ``dest`` after ``_unique_dest()`` selected it must never be silently
    overwritten. ``os.rename`` fails atomically on Windows when the
    destination exists; the pre-check covers platforms where it replaces. A
    refused publish removes its own temp.
    """
    _require_container_destination(root, root_identity, dest)
    if os.path.lexists(dest):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise OSError(
            f"destination {dest!r} appeared; refusing to overwrite it")
    os.rename(tmp, dest)


def _move_into_container(src, dest, root=None, root_identity=None):
    """Move src to dest without ever clobbering a destination that appeared.

    Same-volume: os.rename is atomic AND fails on Windows when dest exists
    (source preserved). Cross-volume: copy to a unique temp sibling, publish
    no-clobber, and only then remove the source.
    """
    if root is not None and root_identity is None:
        root_identity = capture_resolved_root(root)
    _require_container_destination(root, root_identity, dest)

    if os.path.lexists(dest):
        raise OSError(f"destination {dest!r} appeared; refusing to overwrite it")
    try:
        _require_container_destination(root, root_identity, dest)
        os.rename(src, dest)      # same-volume: atomic, no-clobber
        return
    except OSError:
        # a destination appeared between the check and the rename, or the
        # rename crossed volumes
        if os.path.lexists(dest):
            raise OSError(f"destination {dest!r} appeared; refusing to overwrite it")

        tmp = f"{dest}.fptmp-{uuid.uuid4().hex[:8]}"

        _require_container_destination(root, root_identity, tmp)

        try:
            if os.path.isdir(src):
                shutil.copytree(src, tmp)
            else:
                shutil.copy2(src, tmp)

            _publish_new_file(tmp, dest, root, root_identity)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                if os.path.lexists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise

    # publication succeeded: remove the source
    try:
        _require_container_destination(root, root_identity, dest)
        if os.path.isdir(src):
            shutil.rmtree(src)
        else:
            os.remove(src)
    except OSError:
        logger.warning("move published %s but could not remove the source %s",
                       dest, src)


def _copy_atomic(src, dest, is_dir, root=None, root_identity=None):
    """Copy src to dest so a partial copy is never presented as the result.

    A direct ``copytree``/``copy2`` interrupted mid-way (disk full, IO error)
    leaves a half file or half folder inside the container that looks real.
    The copy therefore lands in a UNIQUE sibling temp.
    """
    if root is not None and root_identity is None:
        root_identity = capture_resolved_root(root)
    _require_container_destination(root, root_identity, dest)

    tmp = f"{dest}.fptmp-{uuid.uuid4().hex[:8]}"

    _require_container_destination(root, root_identity, tmp)

    try:
        if is_dir:
            shutil.copytree(src, tmp)
        else:
            shutil.copy2(src, tmp)

        _require_container_destination(root, root_identity, dest)
        # os.rename refuses to clobber an existing destination atomically on
        # Windows; the pre-check catches it early on platforms where it does
        if os.path.lexists(dest):
            raise OSError(
                f"destination {dest!r} appeared during the copy; "
                f"refusing to overwrite it")
        os.rename(tmp, dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            if os.path.lexists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _async_eligible(items):
    """Should these container ops go to the worker instead of the GUI thread?

    Heuristic: many entries, any DIRECTORY, or a total file payload above the
    size threshold. Small text-file copies stay synchronous — no scheduler
    for a 20-byte file.

    This decision must NEVER walk a directory tree: ``os.walk`` here would
    hand the GUI thread the exact recursive scan (and its cost — a slow or
    network folder) that the worker exists to absorb. Any directory item is
    therefore dispatched immediately; only plain files get a cheap
    ``getsize``.
    """
    if len(items) > _ASYNC_THRESHOLD_FILES:
        return True
    total = 0
    for _op, src, _dest, is_dir in items:
        if is_dir:
            return True       # recursive work: the worker walks it, never us
        try:
            total += os.path.getsize(src) or 0
        except OSError:
            continue
        if total > _ASYNC_THRESHOLD_BYTES:
            return True
    return False


def _write_text_atomic(path, content, root=None, root_identity=None):
    """Write a small NEW text file atomically and no-clobber.

    A .url link or similar NEW item must never overwrite a file that appeared
    at `path` while the write was in progress — os.replace would clobber it,
    so publication goes through _publish_new_file (os.rename, which fails on
    Windows when the destination exists).
    """
    tmp = f"{path}.fptmp-{uuid.uuid4().hex[:8]}"
    try:
        _require_container_destination(root, root_identity, tmp)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        _publish_new_file(tmp, path, root, root_identity)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


class _FileList(QListWidget):
    """Icon grid whose items drag out as real file URLs."""

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(48, 48))
        self.setGridSize(QSize(84, 76))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setWordWrap(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)  # drops land on the panel, not the list

    def keyPressEvent(self, event):
        p = self._panel
        key, mods = event.key(), event.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier
        shift = mods & Qt.KeyboardModifier.ShiftModifier
        if key == Qt.Key.Key_Delete:
            p._delete(p.selected_paths())
        elif key == Qt.Key.Key_F2:
            paths = p.selected_paths()
            if paths:
                p._rename(paths[0])
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.currentItem():
                p._open_item(self.currentItem())
        elif ctrl and shift and key == Qt.Key.Key_C:
            p.copy_selected_paths()
        elif ctrl and key == Qt.Key.Key_N:
            p.new_folder()
        elif ctrl and key == Qt.Key.Key_V:
            p.save_clipboard_as_file()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def startDrag(self, actions):
        paths = self._panel.selected_paths()
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = self.currentItem().icon() if self.currentItem() else QIcon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(48, 48))
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)



class FileContainerPanel(QWidget):
    """One silo's file folder: a floating drawer, or a docked sidebar.

    Same widget either way — `set_docked()` flips the window flags and
    `open_for()` stops trying to raise/activate a window that is really a
    child panel inside the splitter.
    """

    def __init__(self, main_win):
        import uuid

        super().__init__(main_win, Qt.WindowType.Tool)
        self.main_win = main_win
        self._container_owner_id = uuid.uuid4().hex
        self.docked = False
        self.lang = getattr(main_win, "_current_lang", "EN")
        self.folder = ""
        self._folder_root_identity = ""
        self._icon_provider = QFileIconProvider()
        self._thumb_cache = {}  # path -> (mtime, QIcon)
        self.setAcceptDrops(True)
        self.setMinimumSize(300, 220)
        self.resize(420, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.btn_import = QPushButton("📄+")
        self.btn_import.setToolTip(tr("Import Files...\nCopy files into this silo's folder\n(or just drop files anywhere on this window)", self.lang))
        self.btn_import.clicked.connect(self._pick_import)
        self.btn_import_folder = QPushButton("📁+")
        self.btn_import_folder.setToolTip(tr("Import Folder...\nCopy an entire folder into this silo's folder", self.lang))
        self.btn_import_folder.clicked.connect(self._pick_import_folder)
        self.btn_open_folder = QPushButton("📂")
        self.btn_open_folder.setToolTip(tr("Open Folder\nOpen this silo's folder in Explorer", self.lang))
        self.btn_open_folder.clicked.connect(self._open_folder)
        self.btn_export = QPushButton("📤")
        self.btn_export.setToolTip(tr("Export All...\nCopy every file here to a folder you pick", self.lang))
        self.btn_export.clicked.connect(self._export_all)
        self.btn_clip = QPushButton("📋→📄")
        self.btn_clip.setToolTip(tr("Clip→File\nSave the clipboard text into this folder as a .txt file", self.lang))
        self.btn_clip.clicked.connect(self.save_clipboard_as_file)
        self.btn_view = QPushButton("👁️")
        self.btn_view.setToolTip(tr("View\nCycle view: Icons → List → Details (like Explorer)", self.lang))
        self.btn_view.clicked.connect(self._cycle_view)

        bar.addWidget(self.btn_import)
        bar.addWidget(self.btn_import_folder)
        bar.addWidget(self.btn_clip)
        bar.addWidget(self.btn_open_folder)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_view)
        bar.addStretch(1)
        self.lbl_count = QLabel("")
        bar.addWidget(self.lbl_count)
        layout.addLayout(bar)

        self.file_list = _FileList(self)
        self.file_list.itemDoubleClicked.connect(self._open_item)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._show_menu)
        self.file_list.itemSelectionChanged.connect(self._update_preview)
        layout.addWidget(self.file_list, 1)

        self.lbl_preview = QLabel("")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setMaximumHeight(130)
        self.lbl_preview.hide()
        layout.addWidget(self.lbl_preview)

        tpl_layout = QHBoxLayout()
        tpl_layout.setContentsMargins(0, 0, 0, 0)
        self.le_tpl = QLineEdit(self.main_win.data.get("folder_template", "ae, c4d, _output, _input"))
        self.le_tpl.setPlaceholderText(tr("Folder template (e.g. src, docs, assets)", self.lang))
        self.le_tpl.textChanged.connect(self._on_tpl_changed)
        self.btn_build_tpl = QPushButton(tr("Build Template", self.lang))
        self.btn_build_tpl.setToolTip(tr("Create these folders in the current silo", self.lang))
        self.btn_build_tpl.clicked.connect(self.build_template_folders)
        tpl_layout.addWidget(QLabel(tr("Folder Tpl:", self.lang)))
        tpl_layout.addWidget(self.le_tpl)
        tpl_layout.addWidget(self.btn_build_tpl)
        layout.addLayout(tpl_layout)

        self.lbl_hint = QLabel(
            tr("Drop files here — copied into a plain folder you own. "
               "Hold Alt while dropping to add links instead of copies.", self.lang))
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self.refresh)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self._refresh_timer.start())
        self._apply_view_mode()

    def set_language(self, lang):
        self.lang = lang
        self.retranslate_ui()

    def retranslate_ui(self):
        self.btn_import.setToolTip(tr("Import Files...\nCopy files into this silo's folder\n(or just drop files anywhere on this window)", self.lang))
        self.btn_import_folder.setToolTip(tr("Import Folder...\nCopy an entire folder into this silo's folder", self.lang))
        self.btn_open_folder.setToolTip(tr("Open Folder\nOpen this silo's folder in Explorer", self.lang))
        self.btn_export.setToolTip(tr("Export All...\nCopy every file here to a folder you pick", self.lang))
        self.btn_clip.setToolTip(tr("Clip→File\nSave the clipboard text into this folder as a .txt file", self.lang))
        self.btn_view.setToolTip(tr("View\nCycle view: Icons → List → Details (like Explorer)", self.lang))
        self.le_tpl.setPlaceholderText(tr("Folder template (e.g. src, docs, assets)", self.lang))
        self.btn_build_tpl.setText(tr("Build Template", self.lang))
        self.btn_build_tpl.setToolTip(tr("Create these folders in the current silo", self.lang))
        self.lbl_hint.setText(
            tr("Drop files here — copied into a plain folder you own. "
               "Hold Alt while dropping to add links instead of copies.", self.lang))

    # ---- view modes (Explorer-like) ---------------------------------------

    _VIEW_MODES = ("Icons", "List", "Details")

    def _view_mode(self):
        mode = self.main_win.data.get("file_panel_view", "Details")
        return mode if mode in self._VIEW_MODES else "Details"

    def _cycle_view(self):
        modes = self._VIEW_MODES
        nxt = modes[(modes.index(self._view_mode()) + 1) % len(modes)]
        self.main_win.data["file_panel_view"] = nxt
        if hasattr(self.main_win, "mark_dirty"):
            self.main_win.mark_dirty()
        self._apply_view_mode()
        self.refresh()

    def _apply_view_mode(self):
        mode = self._view_mode()
        self.btn_view.setText("👁️")
        self.btn_view.setToolTip(tr("View ({})\nCycle view: Icons → List → Details (like Explorer)", self.lang).format(mode))
        lw = self.file_list
        if mode == "Icons":
            lw.setViewMode(QListWidget.ViewMode.IconMode)
            lw.setIconSize(QSize(48, 48))
            lw.setGridSize(QSize(84, 76))
            lw.setWordWrap(True)
        else:
            lw.setViewMode(QListWidget.ViewMode.ListMode)
            lw.setIconSize(QSize(16, 16))
            lw.setGridSize(QSize())
            lw.setWordWrap(False)

    # ---- lifecycle -------------------------------------------------------

    def set_docked(self, docked, parent=None):
        """Move between floating Tool window and in-layout child panel.

        A Qt.Tool widget cannot simply be added to a layout — the flags have
        to go back to Qt.Widget first, and a reparent resets visibility, so
        callers show it again themselves.
        """
        docked = bool(docked)
        self.docked = docked
        self.hide()
        if docked:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setParent(parent or self.main_win)
            self.setMinimumSize(180, 120)
        else:
            self.setParent(self.main_win, Qt.WindowType.Tool)
            self.setMinimumSize(300, 220)
            self.resize(420, 320)

    def open_for(self, folder, title=""):
        """Point the panel at a resolved (unique) folder without creating it, and show."""
        self._discard_if_empty()

        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())

        if os.path.isdir(folder):
            self._watcher.addPath(folder)

        self.folder = folder
        self._folder_root_identity = capture_resolved_root(folder)

        import uuid
        self._container_owner_id = str(uuid.uuid4())

        self.setWindowTitle(tr("Files — {}", self.lang).format(title))
        self.refresh()
        self.show()
        # Play chest_open sound (T-710)
        if hasattr(self.main_win, 'sound_manager'):
            self.main_win.sound_manager.play("chest_open")
        if not self.docked:
            # a docked panel is a child of the splitter: raising it does
            # nothing useful and activating it steals focus from the editor
            self.raise_()
            self.activateWindow()
        elif hasattr(self.main_win, "_show_files_dock"):
            self.main_win._show_files_dock(True, title=title)

    def _ensure_folder(self):
        """Create the folder if it doesn't exist and ensure it is watched."""
        if self.folder and not os.path.isdir(self.folder):
            try:
                os.makedirs(self.folder, exist_ok=True)
                self._watcher.addPath(self.folder)
            except OSError as e:
                logger.error(f"File container folder creation failed: {e}")
                return False
        return True

    def detach_session(self):
        """Detach from the current filesystem location and ownership session."""
        self.hide()
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self.folder = None
        self._container_owner_id = None
    def _discard_if_empty(self):
        """Remove the current folder if it is still completely empty."""
        folder = getattr(self, "folder", None)
        if not folder or not os.path.isdir(folder):
            return False
        try:
            if os.listdir(folder):
                return False          # never touch a folder with content
        except OSError:
            return False
        # On Windows the file-system watcher holds an open handle to the
        # directory, so it cannot be removed until Qt has actually released
        # it — drop the paths, let the event loop run, then retry once.
        try:
            if self._watcher.directories():
                self._watcher.removePaths(self._watcher.directories())
        except Exception:
            pass
        for attempt in range(2):
            try:
                os.rmdir(folder)
                return True
            except OSError:
                if attempt == 0:
                    from PyQt6.QtWidgets import QApplication
                    QApplication.processEvents()
                    continue
                return False          # still held: leaving it is harmless
        return False

    def closeEvent(self, event):
        """Don't leave an empty folder behind just for looking.

        open_for() creates the directory so the panel has somewhere to watch
        and drop into. If the user added nothing, that directory is litter
        that accumulates one-per-silo forever, so remove it again — but only
        when it is genuinely empty, never when it holds anything.
        """
        # Play chest_close sound (T-710)
        if hasattr(self.main_win, 'sound_manager'):
            self.main_win.sound_manager.play("chest_close")
        self._discard_if_empty()
        super().closeEvent(event)

    def refresh(self):
        """Reload the list, without letting the main window hide itself.

        An UNDOCKED panel is a `Qt.Tool` window (see the class docstring), and
        touching one can hand the foreground away for an instant — at which
        point `changeEvent` in the main window sees a deactivation and, with
        "Hide on Click-Out" on, hides everything. That is how "Ctrl+Z right
        after pasting an image made the window vanish" happened: the paste
        writes a PNG into the watched folder, `directoryChanged` fires a
        moment LATER, and the refresh lands under the user's next keystroke,
        so the hide looks like it belongs to whatever they just pressed.
        The lock is the same counted one dialogs already take.
        """
        mw = getattr(self, "main_win", None)
        lock = (not self.docked) and mw is not None and hasattr(mw, "_increment_focus_lock")
        if lock:
            mw._increment_focus_lock()
        try:
            if mw and hasattr(mw, "invalidate_file_count_cache"):
                mw.invalidate_file_count_cache(self.folder)
                if hasattr(self, "slot_idx"):
                    mw._silo_file_count(self.slot_idx, is_archive=getattr(self, "is_archive", False))
            self._refresh_list()
        finally:
            if lock:
                QTimer.singleShot(300, mw._decrement_focus_lock)

    def _refresh_list(self):
        if not hasattr(self, "folder") or not self.folder:
            return

        import weakref
        from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal
        if not hasattr(self, "refresh_loaded"):
            from PyQt6.QtCore import QObject
            class Signals(QObject):
                refresh_loaded = pyqtSignal(list, int)
            self._refresh_signals = Signals()
            self.refresh_loaded = self._refresh_signals.refresh_loaded
            self.refresh_loaded.connect(self._on_refresh_list_result)

        class Worker(QRunnable):
            def __init__(self, p, s, panel_ref):
                super().__init__()
                self.p = p
                self.s = s
                self.panel_ref = panel_ref

            def run(self):
                import datetime
                import os
                from fastprompter.ui.file_container import _IMAGE_EXTS, _dir_size, _fmt_size

                try:
                    names = sorted(os.listdir(self.p), key=str.lower)
                except OSError:
                    names = []

                items = []
                for name in names:
                    if name.endswith(".lnk"): continue
                    path = os.path.join(self.p, name)
                    label = name
                    if self.s:
                        try:
                            s = _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
                            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                            label = f"{name}  —  {_fmt_size(s)}  —  {mtime.strftime('%d.%m.%y %H:%M')}"
                        except OSError:
                            pass

                    img = None
                    mtime_val = 0
                    ext = os.path.splitext(path)[1].lower()
                    needs_thumb = ext in _IMAGE_EXTS
                    if needs_thumb:
                        try:
                            mtime_val = os.path.getmtime(path)
                        except OSError:
                            pass
                    items.append((path, label, img, mtime_val, needs_thumb))

                panel = self.panel_ref()
                if panel:
                    from PyQt6 import sip
                    if not sip.isdeleted(panel):
                        try:
                            panel.refresh_loaded.emit(items, len(names))
                        except RuntimeError:
                            pass

        worker = Worker(self.folder, self._view_mode() == "Details", weakref.ref(self))
        QThreadPool.globalInstance().start(worker)

    def _on_refresh_list_result(self, items, count):
        from PyQt6 import sip
        from PyQt6.QtCore import Qt
        if sip.isdeleted(self): return

        if not hasattr(self, "_thumb_lru"):
            from collections import OrderedDict
            class LRUCache:
                def __init__(self, capacity=200):
                    self.cache = OrderedDict()
                    self.capacity = capacity
                def get(self, key):
                    if key not in self.cache: return None
                    self.cache.move_to_end(key)
                    return self.cache[key]
                def put(self, key, value):
                    self.cache[key] = value
                    self.cache.move_to_end(key)
                    if len(self.cache) > self.capacity:
                        self.cache.popitem(last=False)
            self._thumb_lru = LRUCache(200)

        existing = {}
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            existing[item.data(Qt.ItemDataRole.UserRole)] = item

        new_paths = set()

        for idx, (path, label, img, mtime_val, needs_thumb) in enumerate(items):
            new_paths.add(path)
            icon = None
            if needs_thumb:
                cached = self._thumb_lru.get(path)
                if cached and cached[0] == mtime_val:
                    icon = cached[1]
                else:
                    from PyQt6.QtCore import QFileInfo
                    icon = self._icon_provider.icon(QFileInfo(path))
            else:
                from PyQt6.QtCore import QFileInfo
                icon = self._icon_provider.icon(QFileInfo(path))

            if path in existing:
                item = existing[path]
                if item.text() != label:
                    item.setText(label)
                item.setIcon(icon)
                if self.file_list.row(item) != idx:
                    taken = self.file_list.takeItem(self.file_list.row(item))
                    self.file_list.insertItem(idx, taken)
            else:
                item = QListWidgetItem(icon, label)
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setToolTip(path)
                self.file_list.insertItem(idx, item)

        for i in range(self.file_list.count() - 1, -1, -1):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) not in new_paths:
                self.file_list.takeItem(i)

        self.lbl_count.setText(tr("{} file(s)", getattr(self, "lang", "EN")).format(count))
        self._update_preview()
        mw = getattr(self, "main_win", None)
        if hasattr(mw, "_update_files_button"):
            mw._update_files_button()
        if hasattr(mw, "refresh_temp_presets"):
            mw.refresh_temp_presets()

        self._queue_thumbnail_fetch()

    def selected_paths(self):
        from PyQt6.QtCore import Qt
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.file_list.selectedItems()]

    def _queue_thumbnail_fetch(self):
        if not hasattr(self, "_thumb_timer"):
            from PyQt6.QtCore import QTimer
            self._thumb_timer = QTimer(self)
            self._thumb_timer.setSingleShot(True)
            self._thumb_timer.timeout.connect(self._fetch_visible_thumbnails)
            self.file_list.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._thumb_timer.start(250)

    def _on_scroll(self):
        self._fetch_visible_thumbnails(immediate_only=True)
        if hasattr(self, "_thumb_timer"):
            self._thumb_timer.start(250)

    def _fetch_visible_thumbnails(self, immediate_only=False):
        import os

        from PyQt6.QtCore import Qt

        from fastprompter.ui.file_container import _IMAGE_EXTS
        viewport = self.file_list.viewport().rect()

        to_fetch = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if not path: continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in _IMAGE_EXTS: continue

            try:
                mtime_val = os.path.getmtime(path)
            except OSError:
                continue

            cached = self._thumb_lru.get(path)
            if cached and cached[0] == mtime_val:
                continue

            rect = self.file_list.visualItemRect(item)
            if rect.intersects(viewport):
                to_fetch.insert(0, (path, mtime_val)) # visible first
            elif not immediate_only:
                to_fetch.append((path, mtime_val))

        if not to_fetch:
            return

        if not hasattr(self, "_fetching_thumbs"):
            self._fetching_thumbs = set()

        filtered = []
        for path, mtime in to_fetch:
            if path not in self._fetching_thumbs:
                self._fetching_thumbs.add(path)
                filtered.append((path, mtime))

        if not filtered:
            return

        import weakref
        from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal
        if not hasattr(self, "thumb_loaded"):
            from PyQt6.QtCore import QObject
            class Signals(QObject):
                thumb_loaded = pyqtSignal(str, int, object)
            self._thumb_signals = Signals()
            self.thumb_loaded = self._thumb_signals.thumb_loaded
            self.thumb_loaded.connect(self._on_thumb_loaded)

        class ThumbWorker(QRunnable):
            def __init__(self, to_fetch, panel_ref):
                super().__init__()
                self.to_fetch = to_fetch
                self.panel_ref = panel_ref

            def run(self):
                from PyQt6.QtGui import QImageReader
                from PyQt6.QtCore import Qt
                for path, mtime in self.to_fetch:
                    img = None
                    try:
                        reader = QImageReader(path)
                        reader.setAutoTransform(True)
                        sz = reader.size()
                        if not sz.isNull():
                            sz.scale(48, 48, Qt.AspectRatioMode.KeepAspectRatio)
                            reader.setScaledSize(sz)
                            read_img = reader.read()
                            if not read_img.isNull():
                                img = read_img
                    except Exception:
                        pass

                    panel = self.panel_ref()
                    if panel:
                        from PyQt6 import sip
                        if not sip.isdeleted(panel):
                            try:
                                panel.thumb_loaded.emit(path, mtime, img)
                            except RuntimeError:
                                pass

        worker = ThumbWorker(filtered, weakref.ref(self))
        QThreadPool.globalInstance().start(worker)

    def _on_thumb_loaded(self, path, mtime, img):
        from PyQt6 import sip
        if sip.isdeleted(self): return
        if hasattr(self, "_fetching_thumbs") and path in self._fetching_thumbs:
            self._fetching_thumbs.discard(path)

        if not img:
            return

        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QIcon, QPixmap
        icon = QIcon(QPixmap.fromImage(img))
        self._thumb_lru.put(path, (mtime, icon))

        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setIcon(icon)
                break

    # ---- drop in ---------------------------------------------------------

    def _set_drop_hot(self, hot):
        """Outline the panel while a drag is over it.

        As a floating window the title bar told you where the drop would
        land. Docked, the panel is just another strip of the window, so it
        has to say so itself.
        """
        if bool(getattr(self, "_drop_hot", False)) == bool(hot):
            return
        self._drop_hot = bool(hot)
        accent = "#C0A060"
        try:
            cache = getattr(self.main_win, "_theme_cache", None)
            if cache and cache.get("raw_colors"):
                accent = cache["raw_colors"].get("accent", accent)
        except Exception:
            pass
        self.file_list.setStyleSheet(
            f"border: 2px solid {accent};" if hot else "")
        old = self.lbl_hint.text()
        if hot:
            self._hint_text = old
            self.lbl_hint.setText(tr("Drop to file into this silo", self.lang))
        elif getattr(self, "_hint_text", None):
            self.lbl_hint.setText(self._hint_text)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._set_drop_hot(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_drop_hot(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_hot(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            from PyQt6.QtWidgets import QApplication
            is_internal = event.source() is not None
            is_ctrl = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
            is_alt = QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier

            if is_alt:
                self.import_links(paths)
                event.acceptProposedAction()
            else:
                do_move = is_internal and not is_ctrl
                self.import_paths(paths, do_move=do_move)
                if do_move:
                    event.setDropAction(Qt.DropAction.MoveAction)
                else:
                    event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()

    def import_paths(self, paths, do_move=False):
        """Copy or move files (or whole folders) into the silo folder.

        Small operations run synchronously (no scheduler for a 20-byte text
        file); large ones are handed to the shared container worker so the
        GUI never freezes on a big drop or export."""
        if not self.folder:
            return
        if not self._ensure_folder():
            return
        items = []
        for src in paths:
            if not os.path.exists(src):
                continue
            # Never swallow our own folder into itself
            if os.path.abspath(src) == os.path.abspath(self.folder):
                continue

            # If the file is already in this exact folder
            if os.path.dirname(os.path.abspath(src)) == os.path.abspath(self.folder):
                if do_move:
                    continue  # Moving to same folder is a no-op

            dest = _unique_dest(self.folder, os.path.basename(src.rstrip("\\/")))
            items.append(("move" if do_move else "copy", src, dest,
                          os.path.isdir(src)))
        if not items:
            return
        self._run_container_ops(items)

    def _run_container_ops(self, items):
        """Synchronous for small ops, worker-dispatched for large ones."""
        if _async_eligible(items):
            self._dispatch_container_ops(items)
            return
        done = []
        errors = []
        for op, src, dest, is_dir in items:
            try:
                if op == "move":
                    _move_into_container(
                        src, dest, self.folder, self._folder_root_identity
                    )
                else:
                    _copy_atomic(
                        src, dest, is_dir, self.folder,
                        self._folder_root_identity,
                    )
                done.append(dest)
            except Exception as e:
                logger.error(f"File container import failed for {src}: {e}")
                errors.append((src, str(e)))
        self._finish_container_ops(done, errors)

    def _dispatch_container_ops(self, items, is_export=False):
        """Queue one explicit FIFO command with immutable origin context."""
        import uuid
        request_id = uuid.uuid4().hex
        origin = os.path.realpath(os.path.abspath(self.folder)) if self.folder else ""
        request = {
            "request_id": request_id,
            "owner_id": self._container_owner_id,
            "kind": "export" if is_export else "import",
            "origin": origin,
            "refresh_identity": os.path.normcase(os.path.abspath(self.folder)),
            "items": tuple(items),
            "root": None if is_export else origin,
            "root_identity": None if is_export else self._folder_root_identity,
            "policy": "EXTERNAL_EXPORT" if is_export else "IMPORT_TO_CONTAINER",
        }
        if is_export:
            request["destination_identities"] = {
                os.path.normcase(os.path.abspath(os.path.dirname(dest))):
                    capture_resolved_root(os.path.dirname(dest))
                for _op, _src, dest, _is_dir in items
            }
        worker = container_worker()
        if getattr(self, "_container_done_worker", None) is not worker:
            worker.done.connect(self._on_container_done)
            self._container_done_worker = worker
        dispatch_container_command(request, request_id)
        return request_id

    def _on_container_done(self, request_id, request, done, errors):
        """The worker's result, applied on the GUI thread (refresh once).

        The command RESULT is processed first and unconditionally: an explicit
        user command that failed is a fact, and it must survive a profile or
        panel switch that happened while the worker was running. The old
        ordering returned on the owner check BEFORE errors were logged, so an
        old-owner failure vanished without a trace. Only the UI side effects
        — sound and refresh — belong to the CURRENT owner.
        """
        from fastprompter.main import is_gui_thread
        if not is_gui_thread():
            logger.critical("File Container completion rejected outside GUI thread")
            return
        # 1. Command result, always: the outcome of an explicit command is not
        #    a superseding snapshot — a stale completion must never refresh
        #    the panel, but its failure must still be observable.
        if errors:
            for entry in errors:
                if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    src, err = entry[0], entry[1]
                else:
                    src, err = "?", entry
                logger.error("File Container command %s failed for %s: %s",
                             request_id, src, err)
        elif done:
            logger.info("File Container command %s completed (%d item(s))",
                        request_id, len(done))
        # 2. UI side effects only for the CURRENT owner and origin folder.
        if request.get("owner_id") != self._container_owner_id:
            return
        if done and hasattr(self.main_win, "sound_manager"):
            self.main_win.sound_manager.play_tick()
        current = os.path.normcase(os.path.abspath(self.folder))
        if request.get("refresh_identity") == current:
            self.refresh()

    def _finish_container_ops(self, done, errors):
        if done and hasattr(self.main_win, "sound_manager"):
            self.main_win.sound_manager.play_tick()
        self.refresh()

    def _pick_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Import files", self.lang), "", tr("All files (*.*)", self.lang))
        if paths:
            self.import_paths(paths)

    def _pick_import_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("Import folder", self.lang))
        if path:
            self.import_paths([path])

    def import_links(self, paths):
        """Add .url shortcuts pointing at the originals (no copy).

        Plain-text InternetShortcut files: double-click opens the target,
        readable and portable without FastPrompter."""
        if not self.folder:
            return
        if not self._ensure_folder():
            return
        made = 0
        for src in paths:
            if not os.path.exists(src):
                continue
            name = os.path.basename(src.rstrip("\\/")) + ".url"
            dest = _unique_dest(self.folder, name)
            url = QUrl.fromLocalFile(os.path.abspath(src)).toString()
            try:
                _write_text_atomic(
                    dest, f"[InternetShortcut]\nURL={url}\n", self.folder,
                    self._folder_root_identity,
                )
                made += 1
            except OSError as e:
                logger.error(f"File container link failed for {src}: {e}")
        if made and hasattr(self.main_win, "sound_manager"):
            self.main_win.sound_manager.play_tick()
        self.refresh()

    def _pick_link(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Link to files (no copy)", self.lang), "", tr("All files (*.*)", self.lang))
        if paths:
            self.import_links(paths)

    def save_clipboard_as_file(self, filename=None):
        """Save clipboard text into the folder, prompting the user for a filename.

        `filename` is testable as an optional override; production prompts.
        The name is validated by the canonical container-safety helper, so a
        traversal or drive-qualified name can never escape the container."""
        if not self.folder:
            return
        if not self._ensure_folder():
            return
        import datetime

        from PyQt6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        if not text.strip():
            self.lbl_count.setText(tr("clipboard has no text", self.lang))
            return

        if filename is None:
            stamp = datetime.datetime.now().strftime("%d.%m.%y-%H%M%S")
            first_word = ""

            try:
                if hasattr(self.main_win, "silo_docs"):
                    idx = getattr(self.main_win, "active_temp_slot", 0)
                    if 0 <= idx < len(self.main_win.silo_docs):
                        doc = self.main_win.silo_docs[idx]
                        first_line = doc.toPlainText().split('\n')[0].strip()
                        import re as _re
                        clean_line = _re.sub(r'[*_#]+', '', first_line).strip()
                        if clean_line:
                            first_word = clean_line.split()[0]
                            first_word = _re.sub(r'[^a-zA-Z0-9]', '', first_word)
            except Exception:
                pass

            default_name = f"clip-{first_word}" if first_word else f"clip-{stamp}"
            name, ok = self._prompt_text(
                tr("Save Clipboard", self.lang), tr("Enter filename (without .txt):", self.lang), default_name
            )
            if not ok or not name.strip():
                return
            filename = name

        clean, reason = validate_component(filename)
        if clean is None:
            logger.warning("File container clipboard save rejected: %s", reason)
            self.lbl_count.setText(tr("invalid filename", self.lang))
            return

        dest = _unique_dest(self.folder, f"{clean}.txt")
        tmp = f"{dest}.fptmp-{uuid.uuid4().hex[:8]}"
        root_identity = self._folder_root_identity
        try:
            _require_container_destination(self.folder, root_identity, tmp)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            # no-clobber: a file that appeared at `dest` since _unique_dest
            # is never silently overwritten
            _publish_new_file(tmp, dest, self.folder, root_identity)
            if hasattr(self.main_win, "sound_manager"):
                self.main_win.sound_manager.play_tick()
        except OSError as e:
            logger.error(f"File container clipboard save failed: {e}")
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        self.refresh()

    # ---- file verbs ------------------------------------------------------

    def _open_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            try:
                os.startfile(path)  # noqa: S606 — user-initiated open
            except OSError as e:
                logger.error(f"File container open failed: {e}")

    def _open_folder(self):
        if self.folder and os.path.isdir(self.folder):
            try:
                os.startfile(self.folder)
            except OSError as e:
                logger.error(f"File container open-folder failed: {e}")

    def _reveal(self, path):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            self._open_folder()

    def _export_all(self):
        target, _ = QFileDialog.getSaveFileName(
            self, tr("Export all files to ZIP…", self.lang),
            os.path.join(os.path.expanduser("~"), "Desktop", "export.zip"),
            "ZIP Archives (*.zip)"
        )
        if not target:
            return
        try:
            names = self.selected_paths() or [
                os.path.join(self.folder, n) for n in os.listdir(self.folder)
            ]
        except OSError:
            return

        if not names:
            return

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog(tr("Zipping files...", self.lang), tr("Cancel", self.lang), 0, len(names), self)
        progress.setWindowTitle(tr("Exporting", self.lang))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(500)

        # Run zipping in a background thread
        import threading
        import zipfile

        def do_zip():
            try:
                with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for i, src in enumerate(names):
                        if progress.wasCanceled():
                            break
                        if os.path.isdir(src):
                            for root, _, files in os.walk(src):
                                for file in files:
                                    fpath = os.path.join(root, file)
                                    arcname = os.path.relpath(fpath, self.folder)
                                    zipf.write(fpath, arcname)
                        else:
                            zipf.write(src, os.path.basename(src))

                        # Use QMetaObject.invokeMethod to safely update progress from background thread
                        from PyQt6.QtCore import Q_ARG, QMetaObject
                        QMetaObject.invokeMethod(progress, "setValue", Qt.ConnectionType.QueuedConnection, Q_ARG(int, i + 1))
            except Exception as e:
                logger.error(f"ZIP export failed: {e}")
            finally:
                from PyQt6.QtCore import QMetaObject
                QMetaObject.invokeMethod(progress, "cancel", Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=do_zip, daemon=True).start()

    def _prompt_text(self, title, label, default_text=""):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QInputDialog
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(default_text)
        # Force the dialog to stay on top, fixing issues when opened in the collapsible sidebar
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        restore = self._modal_guard()
        try:
            ok = dialog.exec()
        finally:
            restore()

        return dialog.textValue(), bool(ok)

    def _rename(self, path, new_name=None):
        old = os.path.basename(path)
        if new_name is None:
            new, ok = self._prompt_text(tr("Rename", self.lang), tr("New name:", self.lang), old)
            new_name = new
            if not ok:
                return
        new_name = (new_name or "").strip()
        if not new_name or new_name == old:
            return
        clean, reason = validate_component(new_name)
        if clean is None or not safe_join(self.folder, clean)[0]:
            logger.warning("File container rename rejected: %s", reason)
            self.lbl_count.setText(tr("invalid filename", self.lang))
            return
        dest = _unique_dest(self.folder, clean)
        try:
            os.rename(path, dest)
        except OSError as e:
            logger.error(f"File container rename failed: {e}")
        self.refresh()

    def _modal_guard(self):
        """The main window is frameless + always-on-top and hides on focus
        loss — an unguarded dialog opens BEHIND it and looks like a dead
        button. Returns (restore_fn) after suppressing that behavior."""
        prev = getattr(self.main_win, "ignore_focus_loss", False)
        self.main_win.ignore_focus_loss = True

        def restore():
            self.main_win.ignore_focus_loss = prev
        return restore

    def _delete(self, paths):
        if not paths:
            return
        names = "\n".join(os.path.basename(p) for p in paths[:8])
        more = f"\n… and {len(paths) - 8} more" if len(paths) > 8 else ""
        box = QMessageBox(self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle(tr("Delete files", self.lang))
        box.setText(tr("Delete from this silo's folder?\n\n{}\n", self.lang).format(names + more))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        restore = self._modal_guard()
        try:
            ans = box.exec()
        finally:
            restore()
        if ans != QMessageBox.StandardButton.Yes:
            return
        for p in paths:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except OSError as e:
                logger.error(f"File container delete failed for {p}: {e}")
        self.refresh()

    def copy_selected_paths(self):
        """Ctrl+Shift+C: full paths of the selection to the clipboard."""
        from PyQt6.QtWidgets import QApplication
        paths = self.selected_paths()
        if paths:
            QApplication.clipboard().setText("\n".join(paths))
            self.lbl_count.setText(tr("path copied", self.lang))

    def new_folder(self, name=None):
        """Create a subfolder in the container (Ctrl+N).

        `name` is testable as an optional override; production prompts. The
        name goes through the canonical container-safety helper, so a
        traversal or drive-qualified name can never leave the container."""
        if not self.folder:
            return
        if not self._ensure_folder():
            return
        if name is None:
            name, ok = self._prompt_text(tr("New Folder", self.lang), tr("Folder name:", self.lang), tr("New Folder", self.lang))
            if not ok:
                return
        clean, reason = validate_component(name)
        if clean is None or not safe_join(self.folder, clean)[0]:
            logger.warning("File container new-folder rejected: %s", reason)
            self.lbl_count.setText(tr("invalid filename", self.lang))
            return
        try:
            dest = _unique_dest(self.folder, clean)
            _require_container_destination(
                self.folder, self._folder_root_identity, dest
            )
            os.makedirs(dest, exist_ok=False)
        except OSError as e:
            logger.error(f"File container new folder failed: {e}")
        self.refresh()

    def _on_tpl_changed(self, text):
        self.main_win.data["folder_template"] = text
        self.main_win.mark_dirty()

    def build_template_folders(self, template=None):
        """Create the comma-separated template folders inside the container.

        `template` is testable as an optional override; production reads the
        saved setting. Each element is treated as ONE folder name (nested
        paths are not a supported template feature) and must pass the
        canonical container-safety helper — a malicious element is skipped
        and reported, never allowed to leave the container root."""
        if not self.folder:
            return
        if not self._ensure_folder():
            return
        if template is None:
            template = self.main_win.data.get("folder_template", "ae, c4d, _output, _input")
        folders = [f.strip() for f in str(template or "").split(",") if f.strip()]
        rejected = []
        made = 0
        for f in folders:
            clean, reason = validate_component(f)
            if clean is None or not safe_join(self.folder, clean)[0]:
                rejected.append(f)
                continue
            try:
                dest = os.path.join(self.folder, clean)
                _require_container_destination(
                    self.folder, self._folder_root_identity, dest
                )
                os.makedirs(dest, exist_ok=True)
                made += 1
            except OSError as e:
                logger.error(f"File container template build failed for {f}: {e}")
        if rejected:
            logger.warning("File container template skipped %d invalid name(s): %r",
                           len(rejected), rejected)
        if made:
            self.refresh()

    def _show_menu(self, pos):
        item = self.file_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            menu.addAction(tr("Open\tEnter", self.lang), lambda: self._open_item(item))
            menu.addAction(tr("Show in Explorer", self.lang), lambda: self._reveal(path))
            menu.addAction(tr("Copy Path\tCtrl+Shift+C", self.lang), lambda: self._copy_path(path))
            menu.addAction(tr("Rename…\tF2", self.lang), lambda: self._rename(path))
            menu.addAction(tr("Export to…", self.lang), self._export_all)
            menu.addSeparator()
            menu.addAction(tr("Delete…\tDel", self.lang), lambda: self._delete(self.selected_paths() or [path]))
        else:
            menu.addAction(tr("Import Files…", self.lang), self._pick_import)
            menu.addAction(tr("Import Folder…", self.lang), self._pick_import_folder)
            menu.addAction(tr("New Folder\tCtrl+N", self.lang), self.new_folder)
            menu.addAction(tr("Build Template Folders", self.lang), self.build_template_folders)
            menu.addAction(tr("Add Link to Files…", self.lang), self._pick_link)
            menu.addAction(tr("Clipboard → File\tCtrl+V", self.lang), self.save_clipboard_as_file)
            menu.addAction(tr("Open Folder", self.lang), self._open_folder)
        menu.exec(self.file_list.mapToGlobal(pos))

    def _copy_path(self, path):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(path)

    # ---- preview ---------------------------------------------------------

    def _update_preview(self):
        paths = self.selected_paths()
        if len(paths) != 1:
            self.lbl_preview.hide()
            return
        path = paths[0]
        ext = os.path.splitext(path)[1].lower()
        if ext in _IMAGE_EXTS:
            pix = QPixmap(path)
            if not pix.isNull():
                self.lbl_preview.setPixmap(pix.scaled(
                    self.width() - 24, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                self.lbl_preview.show()
                return
        try:
            size = os.path.getsize(path)
            kb = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
            self.lbl_preview.setText(f"{os.path.basename(path)} — {kb}")
            self.lbl_preview.show()
        except OSError:
            self.lbl_preview.hide()
