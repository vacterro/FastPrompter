"""Image opening: the user's chosen viewer, verified pixels first.

Where an image opens is a preference (``image_viewer_mode``):

* ``system``   -- the program Windows associates with the image type
* ``custom``   -- an .exe the user picked (``image_viewer_path``)
* ``internal`` -- the small built-in Qt preview below

Whatever the mode, the file is header-checked as a real raster of an
admitted format BEFORE anything is launched: a script renamed to ``.png``
never reaches a shell association or an external program.
"""
import os
import subprocess
import sys
import weakref

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from fastprompter.core.i18n import tr
from fastprompter.core.logging import logger

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_FORMATS = {b"png", b"jpg", b"jpeg", b"webp", b"gif", b"bmp"}
_OPEN_VIEWERS = set()
_MAX_PIXELS = 16_000_000
VIEWER_MODES = ("system", "custom", "internal")

# The settings dict is owned by the main window; the router only reads it.
# Unbound (tests, headless tools) means "internal": nothing is ever handed
# to the OS unless an application instance has opted in.
_PREFS_REF = None


def bind_preferences(owner):
    """Let the router read ``owner.data`` without keeping ``owner`` alive."""
    global _PREFS_REF
    _PREFS_REF = weakref.ref(owner) if owner is not None else None


def viewer_preference():
    """(mode, exe_path) currently in force."""
    owner = _PREFS_REF() if _PREFS_REF is not None else None
    data = getattr(owner, "data", None) if owner is not None else None
    if not isinstance(data, dict):
        return "internal", ""
    mode = str(data.get("image_viewer_mode", "system") or "system")
    if mode not in VIEWER_MODES:
        mode = "system"
    return mode, str(data.get("image_viewer_path", "") or "")


class ImageViewer(QDialog):
    def __init__(self, path, image, parent=None, lang="EN"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(os.path.basename(path))
        self._path = os.path.normpath(str(path))
        font = QFont("Verdana")
        font.setPixelSize(12)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.setFont(font)
        self.setMinimumSize(280, 220)
        self.resize(640, 480)
        self._pixmap = QPixmap.fromImage(image)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._label)
        caption = QLabel(os.path.basename(path))
        caption.setToolTip(path)
        # Ctrl+C in the viewer must put the PICTURE on the clipboard, not the
        # path: the whole point of opening a picture is to be able to send it
        # somewhere, and re-finding it in the silo for the same gesture is
        # busywork. The button states the same shortcut it also honours.
        self._copy_button = QPushButton(tr("Copy", lang))
        self._copy_button.setToolTip(
            tr("Copy this image to the clipboard\tCtrl+C", lang))
        self._copy_button.clicked.connect(self.copy_to_clipboard)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(caption)
        row.addStretch(1)
        row.addWidget(self._copy_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._scroll)
        layout.addLayout(row)

    def copy_to_clipboard(self):
        """Put this image (pixels + file URL) on the clipboard."""
        return copy_image_to_clipboard(self._path)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_C
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.copy_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = self._scroll.viewport().size()
        self._label.setPixmap(self._pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))


def _verified_reader(path):
    """A QImageReader for a genuine, bounded raster -- or None."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    # Bound allocation before decoding; SVG and other plugin formats are not
    # admitted by a misleading .png suffix. GIF previews its first frame.
    if (bytes(reader.format()).lower() not in _FORMATS or not reader.canRead()
            or not size.isValid()
            or size.width() * size.height() > _MAX_PIXELS):
        return None
    return reader


def launch_external(path, exe=""):
    """Hand a verified image to ``exe`` or the OS association. True on launch."""
    try:
        if exe:
            if not os.path.isfile(exe):
                logger.warning(f"Image viewer not found: {exe}")
                return False
            subprocess.Popen([exe, os.path.normpath(path)], close_fds=True)  # noqa: S603
            return True
        if sys.platform == "win32":
            os.startfile(os.path.normpath(path))  # noqa: S606 - verified raster
            return True
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
    except OSError as e:
        logger.error(f"External image viewer failed: {e}")
        return False


def open_image_viewer(path, parent=None, lang="EN"):
    """Open ``path`` in the preferred viewer; False + message if not an image.

    External modes still refuse anything that is not a verified raster (and
    anything whose real, link-resolved name is not an image suffix, since the
    OS association is picked by suffix), and fall back to the built-in
    preview when the program cannot be launched.
    """
    reader = _verified_reader(path)
    if reader is None:
        QMessageBox.information(
            parent, tr("Image preview", lang),
            tr("Image could not be previewed\n{}", lang).format(path))
        return False
    mode, exe = viewer_preference()
    real = os.path.realpath(os.path.abspath(str(path)))
    if (mode != "internal"
            and os.path.splitext(real)[1].lower() in IMAGE_SUFFIXES
            and launch_external(real, exe if mode == "custom" else "")):
        return True
    image = reader.read()
    if image.isNull():
        QMessageBox.information(
            parent, tr("Image preview", lang),
            tr("Image could not be previewed\n{}", lang).format(path))
        return False
    viewer = ImageViewer(path, image, parent, lang)
    viewer.show()
    _OPEN_VIEWERS.add(viewer)
    def _on_destroyed(obj):  # noqa: no-weak-refs
        _OPEN_VIEWERS.discard(viewer)
    viewer.destroyed.connect(_on_destroyed)
    return True


def copy_image_path(path):
    """Put the file's full path on the clipboard as plain text."""
    QApplication.clipboard().setText(os.path.normpath(str(path)))
    return True


def copy_image_to_clipboard(path):
    """Put the decoded image (plus the file itself) on the clipboard.

    Pixels paste into chat apps / editors; the file URL makes Explorer paste
    a copy of the file. No plain text is set, so a text field does not
    receive the path by surprise.
    """
    path = os.path.realpath(os.path.abspath(str(path)))
    reader = _verified_reader(path)
    if reader is None:
        return False
    image = reader.read()
    if image.isNull():
        return False
    mime = QMimeData()
    mime.setImageData(image)
    mime.setUrls([QUrl.fromLocalFile(path)])
    QApplication.clipboard().setMimeData(mime)
    return True


def copy_files_to_clipboard(paths):
    """Explorer-style Ctrl+C: file URLs, plus the paths as text."""
    paths = [os.path.normpath(p) for p in paths if p]
    if not paths:
        return False
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    mime.setText("\n".join(paths))
    QApplication.clipboard().setMimeData(mime)
    return True
