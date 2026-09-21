"""Local raster preview: decode pixels in Qt, never invoke a shell association."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QImageReader, QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QScrollArea, QVBoxLayout

from fastprompter.core.i18n import tr

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_FORMATS = {b"png", b"jpg", b"jpeg", b"webp", b"gif", b"bmp"}
_OPEN_VIEWERS = set()


class ImageViewer(QDialog):
    def __init__(self, path, image, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(os.path.basename(path))
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._scroll)
        layout.addWidget(caption)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = self._scroll.viewport().size()
        self._label.setPixmap(self._pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))


def open_image_viewer(path, parent=None, lang="EN"):
    """Return False with an ordinary error on invalid/oversized raster data."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    # Bound allocation before decoding; SVG and other plugin formats are not
    # admitted by a misleading .png suffix. GIF previews its first frame.
    if (bytes(reader.format()).lower() not in _FORMATS or not reader.canRead()
            or not size.isValid() or size.width() * size.height() > 16_000_000):
        QMessageBox.information(
            parent, tr("Image preview", lang),
            tr("Image could not be previewed\n{}", lang).format(path))
        return False
    image = reader.read()
    if image.isNull():
        QMessageBox.information(
            parent, tr("Image preview", lang),
            tr("Image could not be previewed\n{}", lang).format(path))
        return False
    viewer = ImageViewer(path, image, parent)
    _OPEN_VIEWERS.add(viewer)
    viewer.destroyed.connect(lambda: _OPEN_VIEWERS.discard(viewer))
    viewer.show()
    return True
