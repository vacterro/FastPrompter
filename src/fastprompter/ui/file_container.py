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

from PyQt6.QtCore import QFileSystemWatcher, QMimeData, QSize, Qt, QUrl
from PyQt6.QtGui import QDrag, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.logging import logger

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}
_SLUG_STRIP = re.compile(r"[#*_`•\[\]]+")
# ascii + lowercase cyrillic (U+0430-044F, U+0451) survive in slugs
_SLUG_BAD = re.compile(
    "[^a-z0-9" + chr(0x0430) + "-" + chr(0x044F) + chr(0x0451) + "\\- ]+"
)


def silo_slug(text):
    """Folder-safe slug from a silo's first line. Keyed by title, not slot
    index, so the folder follows the silo through reorders."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
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
        drag.exec(Qt.DropAction.CopyAction)


class FileContainerPanel(QWidget):
    """Non-modal drawer window over one silo's file folder."""

    def __init__(self, main_win):
        super().__init__(main_win, Qt.WindowType.Tool)
        self.main_win = main_win
        self.folder = ""
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
        self.btn_import = QPushButton("Import…")
        self.btn_import.setToolTip("Copy files into this silo's folder\n(or just drop files anywhere on this window)")
        self.btn_import.clicked.connect(self._pick_import)
        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.setToolTip("Open this silo's folder in Explorer")
        self.btn_open_folder.clicked.connect(self._open_folder)
        self.btn_export = QPushButton("Export All…")
        self.btn_export.setToolTip("Copy every file here to a folder you pick")
        self.btn_export.clicked.connect(self._export_all)
        bar.addWidget(self.btn_import)
        bar.addWidget(self.btn_open_folder)
        bar.addWidget(self.btn_export)
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

        self.lbl_hint = QLabel("Drop files here — they are copied into a plain folder you own.")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self.refresh())

    # ---- lifecycle -------------------------------------------------------

    def open_for(self, root, category, silo_text):
        """Point the panel at one silo's folder, creating it, and show."""
        title = silo_slug(silo_text)
        folder = silo_files_dir(root, category, silo_text)
        os.makedirs(folder, exist_ok=True)
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self._watcher.addPath(folder)
        self.folder = folder
        self.setWindowTitle(f"Files — {title}")
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self):
        self.file_list.clear()
        try:
            names = sorted(os.listdir(self.folder), key=str.lower)
        except OSError:
            names = []
        for name in names:
            path = os.path.join(self.folder, name)
            item = QListWidgetItem(self._icon_for(path), name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.file_list.addItem(item)
        self.lbl_count.setText(f"{len(names)} file(s)")
        self._update_preview()

    def selected_paths(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.file_list.selectedItems()]

    def _icon_for(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in _IMAGE_EXTS:
            try:
                mtime = os.path.getmtime(path)
                cached = self._thumb_cache.get(path)
                if cached and cached[0] == mtime:
                    return cached[1]
                pix = QPixmap(path)
                if not pix.isNull():
                    icon = QIcon(pix.scaled(
                        48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    self._thumb_cache[path] = (mtime, icon)
                    return icon
            except OSError:
                pass
        from PyQt6.QtCore import QFileInfo
        return self._icon_provider.icon(QFileInfo(path))

    # ---- drop in ---------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths)
            event.acceptProposedAction()

    def import_paths(self, paths):
        """Copy files (or whole folders) into the silo folder."""
        if not self.folder:
            return
        copied = 0
        for src in paths:
            if not os.path.exists(src):
                continue
            # Never swallow our own folder into itself
            if os.path.abspath(src) == os.path.abspath(self.folder):
                continue
            dest = _unique_dest(self.folder, os.path.basename(src.rstrip("\\/")))
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                copied += 1
            except OSError as e:
                logger.error(f"File container import failed for {src}: {e}")
        if copied and hasattr(self.main_win, "sound_manager"):
            self.main_win.sound_manager.play_tick()
        self.refresh()

    def _pick_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import files", "", "All files (*.*)")
        if paths:
            self.import_paths(paths)

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
        target = QFileDialog.getExistingDirectory(self, "Export all files to…")
        if not target:
            return
        try:
            names = self.selected_paths() or [
                os.path.join(self.folder, n) for n in os.listdir(self.folder)
            ]
        except OSError:
            return
        for src in names:
            try:
                dest = _unique_dest(target, os.path.basename(src))
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
            except OSError as e:
                logger.error(f"File container export failed for {src}: {e}")

    def _rename(self, path):
        from PyQt6.QtWidgets import QInputDialog
        old = os.path.basename(path)
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        new = (new or "").strip()
        if not ok or not new or new == old:
            return
        try:
            os.rename(path, _unique_dest(self.folder, new))
        except OSError as e:
            logger.error(f"File container rename failed: {e}")
        self.refresh()

    def _delete(self, paths):
        if not paths:
            return
        names = "\n".join(os.path.basename(p) for p in paths[:8])
        more = f"\n… and {len(paths) - 8} more" if len(paths) > 8 else ""
        ans = QMessageBox.question(
            self, "Delete files",
            f"Delete from this silo's folder?\n\n{names}{more}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
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

    def _show_menu(self, pos):
        item = self.file_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            menu.addAction("Open", lambda: self._open_item(item))
            menu.addAction("Show in Explorer", lambda: self._reveal(path))
            menu.addAction("Copy Path", lambda: self._copy_path(path))
            menu.addAction("Rename…", lambda: self._rename(path))
            menu.addAction("Export to…", self._export_all)
            menu.addSeparator()
            menu.addAction("Delete…", lambda: self._delete(self.selected_paths() or [path]))
        else:
            menu.addAction("Import…", self._pick_import)
            menu.addAction("Open Folder", self._open_folder)
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
