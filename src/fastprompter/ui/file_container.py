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


def folder_summary(root, category, silo_text):
    """Tooltip text: item count + total size + per-extension breakdown."""
    d = silo_files_dir(root, category, silo_text)
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    if not names:
        return "No files yet"
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
    return "\n".join(lines)


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
        self.btn_clip = QPushButton("Clip→File")
        self.btn_clip.setToolTip("Save the clipboard text into this folder as a .txt file")
        self.btn_clip.clicked.connect(self.save_clipboard_as_file)
        self.btn_view = QPushButton("")
        self.btn_view.setToolTip("Cycle view: Icons → List → Details (like Explorer)")
        self.btn_view.clicked.connect(self._cycle_view)

        bar.addWidget(self.btn_import)
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

        self.lbl_hint = QLabel(
            "Drop files here — copied into a plain folder you own. "
            "Hold Alt while dropping to add links instead of copies.")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self.refresh())
        self._apply_view_mode()


    # ---- view modes (Explorer-like) ---------------------------------------

    _VIEW_MODES = ("Icons", "List", "Details")

    def _view_mode(self):
        mode = self.main_win.data.get("file_panel_view", "Icons")
        return mode if mode in self._VIEW_MODES else "Icons"

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
        self.btn_view.setText(f"View: {mode}")
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
        details = self._view_mode() == "Details"
        for name in names:
            path = os.path.join(self.folder, name)
            label = name
            if details:
                try:
                    size = _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
                    import datetime
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                    label = f"{name}  —  {_fmt_size(size)}  —  {mtime.strftime('%d.%m.%y %H:%M')}"
                except OSError:
                    pass
            item = QListWidgetItem(self._icon_for(path), label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.file_list.addItem(item)
        self.lbl_count.setText(f"{len(names)} file(s)")
        self._update_preview()
        if hasattr(self.main_win, "_update_files_button"):
            self.main_win._update_files_button()
        if hasattr(self.main_win, "refresh_temp_presets"):
            self.main_win.refresh_temp_presets()  # keep silo 📁N badges live

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
            from PyQt6.QtWidgets import QApplication
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
                self.import_links(paths)
            else:
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

    def import_links(self, paths):
        """Add .url shortcuts pointing at the originals (no copy).

        Plain-text InternetShortcut files: double-click opens the target,
        readable and portable without FastPrompter."""
        if not self.folder:
            return
        made = 0
        for src in paths:
            if not os.path.exists(src):
                continue
            name = os.path.basename(src.rstrip("\\/")) + ".url"
            dest = _unique_dest(self.folder, name)
            url = QUrl.fromLocalFile(os.path.abspath(src)).toString()
            try:
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(f"[InternetShortcut]\nURL={url}\n")
                made += 1
            except OSError as e:
                logger.error(f"File container link failed for {src}: {e}")
        if made and hasattr(self.main_win, "sound_manager"):
            self.main_win.sound_manager.play_tick()
        self.refresh()

    def _pick_link(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Link to files (no copy)", "", "All files (*.*)")
        if paths:
            self.import_links(paths)

    def save_clipboard_as_file(self):
        """Save clipboard text into the folder as clip-<stamp>.txt."""
        if not self.folder:
            return
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text()
        if not text.strip():
            self.lbl_count.setText("clipboard has no text")
            return
        import datetime
        stamp = datetime.datetime.now().strftime("%d.%m.%y-%H%M%S")
        dest = _unique_dest(self.folder, f"clip-{stamp}.txt")
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
            if hasattr(self.main_win, "sound_manager"):
                self.main_win.sound_manager.play_tick()
        except OSError as e:
            logger.error(f"File container clipboard save failed: {e}")
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
        restore = self._modal_guard()
        try:
            new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        finally:
            restore()
        new = (new or "").strip()
        if not ok or not new or new == old:
            return
        try:
            os.rename(path, _unique_dest(self.folder, new))
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
        box.setWindowTitle("Delete files")
        box.setText(f"Delete from this silo's folder?\n\n{names}{more}")
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
            self.lbl_count.setText("path copied")

    def new_folder(self):
        """Create a subfolder in the container (Ctrl+N)."""
        if not self.folder:
            return
        from PyQt6.QtWidgets import QInputDialog
        restore = self._modal_guard()
        try:
            name, ok = QInputDialog.getText(self, "New Folder", "Folder name:",
                                            text="New Folder")
        finally:
            restore()
        name = (name or "").strip().strip(".")
        if not ok or not name:
            return
        safe = re.sub(r'[<>:"/\\|?*]', "_", name)
        try:
            os.makedirs(_unique_dest(self.folder, safe), exist_ok=False)
        except OSError as e:
            logger.error(f"File container new folder failed: {e}")
        self.refresh()

    def _show_menu(self, pos):
        item = self.file_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            menu.addAction("Open\tEnter", lambda: self._open_item(item))
            menu.addAction("Show in Explorer", lambda: self._reveal(path))
            menu.addAction("Copy Path\tCtrl+Shift+C", lambda: self._copy_path(path))
            menu.addAction("Rename…\tF2", lambda: self._rename(path))
            menu.addAction("Export to…", self._export_all)
            menu.addSeparator()
            menu.addAction("Delete…\tDel", lambda: self._delete(self.selected_paths() or [path]))
        else:
            menu.addAction("Import…", self._pick_import)
            menu.addAction("New Folder\tCtrl+N", self.new_folder)
            menu.addAction("Add Link to Files…", self._pick_link)
            menu.addAction("Clipboard → File\tCtrl+V", self.save_clipboard_as_file)
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
