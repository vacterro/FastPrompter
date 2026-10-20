"""Rich preview surface for Reading mode (T-1484).

The old Reading view was one ``QTextEdit`` fed a single HTML string.  Qt's rich
text engine renders headings, tables and links well, but a ``QTextDocument``
image resource is a still frame: an animated GIF could only ever show its first
frame, and there was nowhere to put a load state, a policy refusal or a bounded
network request.

So the surface is a vertical list of blocks:

* ``_HtmlBlock``  -- one ``QTextBrowser`` per contiguous run of formatted
  content (headings, paragraphs, tables, lists, links);
* ``_MediaBlock`` -- one image: a ``QMovie`` when the payload animates, a
  scaled ``QPixmap`` otherwise, or a placeholder that keeps the URL reachable
  when the media policy forbids fetching.

Blocks are rebuilt only when a new document arrives, so scrolling a long
document never re-parses it.
"""

from __future__ import annotations

import html as _html
import os
import re

from PyQt6.QtCore import QBuffer, QByteArray, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QMovie, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core import rich_preview
from fastprompter.core.logging import logger
from fastprompter.core.preview_media import (
    MAX_REMOTE_BYTES,
    MediaCache,
    RemoteImageLoader,
    looks_animated,
)

# T-1485: each failure CAUSE has its own readable placeholder. The surface used
# to render one identical box for "external images are off", "the URL was
# refused", "the transfer failed" and "the file is broken", so a user staring
# at a blank image could not tell whether to flip a setting or suspect the host.
MEDIA_CAUSE_OFF = "policy-off"
MEDIA_CAUSE_REFUSED = "policy-refused"
MEDIA_CAUSE_TRANSFER = "transfer-failed"
MEDIA_CAUSE_OVERSIZED = "oversized"
MEDIA_CAUSE_DECODE = "decode-failed"
MEDIA_CAUSE_LOCAL = "local-missing"

_MEDIA_NOTES = {
    MEDIA_CAUSE_OFF: "External images are off",
    MEDIA_CAUSE_REFUSED: "Image link refused by policy",
    MEDIA_CAUSE_TRANSFER: "Image could not be fetched",
    MEDIA_CAUSE_OVERSIZED: "Image is larger than the preview limit",
    MEDIA_CAUSE_DECODE: "Image data could not be decoded",
    MEDIA_CAUSE_LOCAL: "Local image file is unavailable",
}


def _safe_url(url: str) -> str:
    """``url`` without its query/fragment, for a durable log line.

    Signed CDN links routinely carry credentials in the query string; a
    preview diagnostic must never copy those into the log file.
    """
    head = (url or "").partition("?")[0]
    return head.partition("#")[0]


def _local_path(url: str) -> str:
    """Absolute filesystem path for a ``file:`` URL or a raw path, or ''."""
    if not url:
        return ""
    raw = url
    if raw.lower().startswith("file:"):
        raw = QUrl(raw).toLocalFile() or ""
    raw = raw.strip()
    if not raw:
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("\\\\"):
        return raw if os.path.isfile(raw) else ""
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    return ""


class _HtmlBlock(QTextBrowser):
    """One contiguous run of formatted content, sized to its own height."""

    def __init__(self, view: RichPreviewView):
        super().__init__(view)
        self._view = view
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.anchorClicked.connect(view._on_anchor_clicked)

    def fit_height(self) -> None:
        width = max(80, self.viewport().width())
        doc = self.document()
        doc.setTextWidth(width)
        height = int(doc.size().height()) + 8
        self.setFixedHeight(max(14, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_height()


class _MediaBlock(QLabel):
    """One image, with real animation, real scaling and an honest placeholder."""

    def __init__(self, view: RichPreviewView, ref: rich_preview.MediaRef):
        super().__init__(view)
        self._view = view
        self._ref = ref
        self._movie: QMovie | None = None
        self._buffer: QBuffer | None = None
        self._pixmap: QPixmap | None = None
        self._image: QImage | None = None
        #: the last decoded payload, kept so a resume can replay the animation
        #: without touching the network or the disk again.
        self._data: bytes | None = None
        self._cause: str = ""
        self._resume_animation = False
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.linkActivated.connect(view._on_anchor_clicked)
        self.set_placeholder()
        self.load()

    # -- states ----------------------------------------------------------
    def _placeholder_html(self, note: str = "") -> str:
        """The placeholder, with EVERY interpolated value escaped.

        The alt text comes from the document, so it is attacker-controlled: an
        alt of ``<img src=x onerror=...>`` used to become live markup inside
        the placeholder. Only the anchor below is constructed markup; the label
        and the note are escaped text.
        """
        href = _html.escape(self._ref.url or "", quote=True)
        label = _html.escape(self._ref.alt or self._ref.url or "", quote=False)
        prefix = (f'<span style="color:#7f848e">{_html.escape(note)}</span><br/>'
                  if note else "")
        return f'{prefix}<a href="{href}">{label}</a>'

    def set_placeholder(self, note: str = "", cause: str = "") -> None:
        """The ONE placeholder path (the two old branches were identical)."""
        self._stop_movie()
        self._cause = cause
        self.setText(self._placeholder_html(note))
        self.setFixedHeight(28)

    def set_failed(self, cause: str = "", detail: str = "") -> None:
        """Show WHY this image is not here, and record it durably (T-1485)."""
        note = _MEDIA_NOTES.get(cause, "")
        if detail:
            logger.warning("rich preview media %s for %s: %s",
                           cause or "failed", _safe_url(self._ref.url), detail)
        else:
            logger.warning("rich preview media %s for %s",
                           cause or "failed", _safe_url(self._ref.url))
        self.set_placeholder(note, cause)

    # -- probes (T-1486) -------------------------------------------------
    def has_payload(self) -> bool:
        return self._data is not None

    def is_animating(self) -> bool:
        if self._movie is None:
            return False
        try:
            return self._movie.state() == QMovie.MovieState.Running
        except Exception:
            return False

    # -- lifecycle (T-1486) ----------------------------------------------
    def suspend(self) -> None:
        """Stop animating; nothing may tick or download unseen.

        The decoded payload is KEPT so a resume can replay it without touching
        the network or the disk a second time.
        """
        state = None
        if self._movie is not None:
            try:
                state = self._movie.state()
            except Exception:
                state = None
        self._resume_animation = state == QMovie.MovieState.Running
        self._stop_movie()

    def resume(self) -> None:
        """Restore exactly what the visible document needs, once."""
        if self._data is not None:
            if self._resume_animation:
                self._play_movie(self._data)
            elif self._image is not None:
                self._show_image()
            self._resume_animation = False
            return
        if (self._ref.remote and self._view.external_media_enabled
                and not self._cause):
            # A cause means this image already failed once: retrying it on
            # every mode switch would re-run a doomed transfer each time.
            self._view.request_remote(self)

    # -- loading ---------------------------------------------------------
    def load(self) -> None:
        if self._ref.remote:
            if not self._view.external_media_enabled:
                self.set_failed(MEDIA_CAUSE_OFF)
                return
            self._view.request_remote(self)
            return
        path = _local_path(self._ref.url)
        if not path:
            self.set_failed(MEDIA_CAUSE_LOCAL, "not a readable local path")
            return
        try:
            size = os.path.getsize(path)
            if size > MAX_REMOTE_BYTES:
                self.set_failed(MEDIA_CAUSE_OVERSIZED, f"{size} bytes")
                return
            with open(path, "rb") as handle:
                data = handle.read(MAX_REMOTE_BYTES)
        except OSError as exc:
            # T-1485: the reason used to be swallowed into an anonymous box.
            self.set_failed(MEDIA_CAUSE_LOCAL, str(exc))
            return
        self.apply_bytes(data)

    def apply_bytes(self, data: bytes) -> None:
        if not data:
            self.set_failed(MEDIA_CAUSE_DECODE, "empty payload")
            return
        # T-1487: the module-level wrapper around looks_animated() is gone.
        if looks_animated(self._ref.url, data):
            self._data = data
            self._play_movie(data)
            return
        image = QImage.fromData(QByteArray(data))
        if image.isNull():
            self.set_failed(MEDIA_CAUSE_DECODE, "not a decodable image")
            return
        self._data = data
        self._image = image
        self._show_image()

    def _play_movie(self, data: bytes) -> None:
        self._stop_movie()
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(data))
        self._buffer.open(QBuffer.OpenModeFlag.ReadOnly)
        movie = QMovie(self._buffer, QByteArray(b"gif"), self)
        if not movie.isValid():
            self.set_failed(MEDIA_CAUSE_DECODE, "QMovie rejected the payload")
            return
        self._movie = movie
        width = max(64, self._view.viewport().width() - 8)
        size = movie.currentPixmap().size()
        if size.isValid() and size.width() > width:
            ratio = width / float(size.width())
            movie.setScaledSize(QSize(width, max(1, int(size.height() * ratio))))
        self.setMovie(movie)
        height = movie.scaledSize().height() if movie.scaledSize().isValid() \
            else size.height()
        self.setFixedHeight(max(24, height + 4))
        movie.start()

    def _show_image(self) -> None:
        if self._image is None:
            return
        width = max(64, self._view.viewport().width() - 8)
        pixmap = QPixmap.fromImage(self._image)
        if pixmap.width() > width:
            pixmap = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self._pixmap = pixmap
        self.setPixmap(pixmap)
        self.setFixedHeight(pixmap.height() + 4)

    def _stop_movie(self) -> None:
        if self._movie is not None:
            try:
                self._movie.stop()
                self.setMovie(None)
            except Exception:
                pass
            self._movie = None
        if self._buffer is not None:
            try:
                self._buffer.close()
                self._buffer.deleteLater()
            except Exception:
                pass
            self._buffer = None
        self._pixmap = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._movie is None and self._pixmap is None and self._image is not None:
            QTimer.singleShot(0, self._show_image)

    def shutdown(self) -> None:
        self._stop_movie()
        self._data = None


class RichPreviewView(QScrollArea):
    """Read-only rendered document surface for Reading mode."""

    linkActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document: rich_preview.RenderedDocument | None = None
        self._blocks: list[QWidget] = []
        self._media_blocks: dict[str, list[_MediaBlock]] = {}
        self._read_only = True
        self._base_font = None
        self.external_media_enabled = False
        self._tokens: dict[str, str] = dict(rich_preview.DEFAULT_TOKENS)
        self._loader: RemoteImageLoader | None = None
        #: ONE cache for the life of the surface. Leaving Reading abandons the
        #: transport, not the payloads it already decoded, so returning does
        #: not re-download the same images (T-1486).
        self._media_cache = MediaCache()
        #: ONE lifecycle authority (T-1486): while the surface is not the
        #: presented mode, no movie runs and no request is in flight.
        self._media_active = True
        #: The scroll offset to put back when Reading is presented again, and
        #: the source it belongs to. Blocks are rebuilt on every re-entry, so
        #: without this the reader lands at the top of the document; an EDITED
        #: source must not inherit the old position, hence the source guard.
        self._saved_scroll = 0
        self._saved_source = ""

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)
        self.setWidget(self._container)

    # -- compatibility with the old QTextEdit surface --------------------
    def setReadOnly(self, value: bool) -> None:      # noqa: N802 (Qt spelling)
        self._read_only = bool(value)

    def isReadOnly(self) -> bool:                     # noqa: N802
        return self._read_only

    def setFont(self, font) -> None:                  # noqa: N802
        self._base_font = font
        super().setFont(font)
        for block in self._blocks:
            block.setFont(font)

    def anchorAt(self, pos) -> str:                   # noqa: N802
        return ""

    def setHtml(self, html_text: str) -> None:        # noqa: N802
        """Flat fallback: one rendered block, no media resolution."""
        doc = rich_preview.RenderedDocument(
            html=html_text, syntax=rich_preview.SYNTAX_MARKDOWN,
            source="", plain_body=self._strip_wrapper(html_text),
        )
        self.set_rendered_document(doc)

    def setPlainText(self, text: str) -> None:        # noqa: N802
        self.set_rendered_document(rich_preview.render(text))

    def set_rendered_document(self, doc: rich_preview.RenderedDocument) -> None:
        """Replace the whole document.  Stale media loads are abandoned."""
        self._document = doc
        self._clear_blocks()
        if doc is None:
            return
        if self._loader is not None:
            self._loader.cancel_all()
        for kind, payload in rich_preview.split_blocks(doc.plain_body):
            if kind == "html":
                if not payload.strip():
                    continue
                block = _HtmlBlock(self)
                block.setHtml(self._wrap_fragment(payload))
                if self._base_font is not None:
                    block.setFont(self._base_font)
                self._add_block(block)
            else:
                ref = self._ref_for(payload)
                block = _MediaBlock(self, ref)
                self._media_blocks.setdefault(ref.url, []).append(block)
                self._add_block(block)
                if not self._media_active:
                    # A document can arrive while Reading is not presented
                    # (a queued update_preview): it must not start animating
                    # or downloading either. Resume replays from the payload.
                    block.suspend()

    # -- media -----------------------------------------------------------
    def set_external_media_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.external_media_enabled:
            return
        self.configure(external_media=enabled)
        if self._document is not None:
            self.set_rendered_document(self._document)

    def request_remote(self, block: _MediaBlock) -> None:
        if not self._media_active:
            # T-1486: a document that is not on screen must not start a fetch.
            return
        if self._loader is None:
            self._loader = RemoteImageLoader(
                parent=self, cache=self._media_cache,
                on_ready=self._on_remote_ready, on_failed=self._on_remote_failed)
        self._loader.request(block._ref.url)

    @property
    def pending_remote_requests(self) -> int:
        """In-flight image requests (0 when the surface is suspended)."""
        if not self._media_active or self._loader is None:
            return 0
        return self._loader.pending_count

    def running_movie_count(self) -> int:
        """How many animations are ticking right now (T-1486 probe)."""
        running = 0
        for blocks in self._media_blocks.values():
            for block in blocks:
                if block.is_animating():
                    running += 1
        return running

    def suspend_media(self) -> None:
        """The surface stopped being presented: stop ALL background work.

        ``closeEvent`` never fires for a hidden child, and ``shutdown()`` had
        no caller, so a document left Reading mode with its GIF still ticking
        and its request still running. This is the single authority every
        exit path uses.
        """
        try:
            self._saved_scroll = int(self.verticalScrollBar().value())
            self._saved_source = self._document.source if self._document else ""
        except Exception:
            self._saved_scroll = 0
            self._saved_source = ""
        self._media_active = False
        self._stop_network()
        for blocks in self._media_blocks.values():
            for block in blocks:
                block.suspend()

    def resume_media(self) -> None:
        """The surface is presented again: restore only what is visible."""
        self._media_active = True
        for blocks in list(self._media_blocks.values()):
            for block in blocks:
                block.resume()
        self._restore_scroll()

    def _restore_scroll(self) -> None:
        """Put the reader back where they were, if the document is unchanged.

        The re-entry render rebuilds every block, so the position has to be
        re-applied after the layout settles: the synchronous attempt covers a
        view that is already laid out, and the queued one covers the rebuild
        that is still waiting for its LayoutRequest.
        """
        if self._saved_scroll <= 0 or self._document is None:
            return
        if self._document.source != self._saved_source:
            return
        value = self._saved_scroll
        self.verticalScrollBar().setValue(value)
        # The queued pass must survive nothing: if the surface is deleted
        # before the event loop runs, touching its C++ object is a hard crash.
        QTimer.singleShot(0, lambda: self._alive() and self._apply_scroll(value))

    def _apply_scroll(self, value: int) -> None:
        if (self._media_active and self._document is not None
                and self._document.source == self._saved_source):
            self.verticalScrollBar().setValue(value)

    def _alive(self) -> bool:
        """False once Qt has already destroyed this widget.

        A network reply can land after the surface is gone; touching a deleted
        C++ object from that callback is a hard crash, not a Python exception,
        so every async entry point checks first.
        """
        try:
            from PyQt6 import sip
            return not sip.isdeleted(self)
        except Exception:
            return True

    def _on_remote_ready(self, url: str, data: bytes) -> None:
        if not self._alive() or not self._media_active:
            # A stale reply must never touch content nobody is looking at.
            return
        for block in self._media_blocks.get(url, ()):
            if block is not None:
                block.apply_bytes(data)

    def _on_remote_failed(self, url: str, reason: str) -> None:
        if not self._alive() or not self._media_active:
            return
        cause = MEDIA_CAUSE_REFUSED if "policy" in (reason or "").lower() \
            else MEDIA_CAUSE_TRANSFER
        if "size cap" in (reason or ""):
            cause = MEDIA_CAUSE_OVERSIZED
        for block in self._media_blocks.get(url, ()):
            if block is not None:
                block.set_failed(cause, reason)

    # -- theme / policy --------------------------------------------------
    def configure(self, tokens: dict[str, str] | None = None,
                  external_media: bool | None = None) -> None:
        """Store presentation settings WITHOUT rebuilding the blocks.

        Callers that are about to hand over a fresh document use this so the
        blocks are built exactly once.
        """
        if tokens:
            merged = dict(rich_preview.DEFAULT_TOKENS)
            for key, value in tokens.items():
                if isinstance(value, str) and value:
                    merged[key] = value
            self._tokens = merged
        if external_media is not None:
            self.external_media_enabled = bool(external_media)

    def set_theme_tokens(self, tokens: dict[str, str]) -> None:
        self.configure(tokens=tokens)
        if self._document is not None:
            self.set_rendered_document(self._document)

    # -- internals -------------------------------------------------------
    def _add_block(self, block: QWidget) -> None:
        self._layout.insertWidget(self._layout.count() - 1, block)
        self._blocks.append(block)

    def _clear_blocks(self) -> None:
        for block in self._blocks:
            try:
                if isinstance(block, _MediaBlock):
                    block.shutdown()
                self._layout.removeWidget(block)
                block.setParent(None)
                block.deleteLater()
            except Exception:
                pass
        self._blocks.clear()
        self._media_blocks.clear()

    def _ref_for(self, url: str) -> rich_preview.MediaRef:
        if self._document is not None:
            for ref in self._document.media:
                if ref.url == url:
                    return ref
        return rich_preview.MediaRef(url=url, remote=url.lower().startswith("http"))

    def _wrap_fragment(self, fragment: str) -> str:
        return rich_preview._wrap(fragment, self._tokens)

    @staticmethod
    def _strip_wrapper(html_text: str) -> str:
        match = re.search(r"<body[^>]*>(.*)</body>", html_text or "", re.S | re.I)
        return match.group(1) if match else (html_text or "")

    def _on_anchor_clicked(self, url: QUrl) -> None:
        href = url.toString() if isinstance(url, QUrl) else str(url)
        if href:
            self.linkActivated.emit(href)

    def _stop_network(self) -> None:
        """Abandon in-flight requests, but KEEP the loader and its cache.

        Dropping the transport used to lose every decoded payload with it, so
        each return to Reading re-fetched the same images and built a second
        ``QNetworkAccessManager`` whose Qt parent is this widget -- a child
        that outlives the Python reference and accumulates per switch.
        ``cancel_all`` already bumps the generation, so a late reply can never
        touch the new document; one retained loader means one transport, one
        cache and no duplicated fetches across mode changes.
        """
        if self._loader is not None:
            try:
                self._loader.cancel_all()
            except Exception:
                pass

    def closeEvent(self, event):
        # A reply that outlives its surface is a crash waiting for the next
        # event-loop turn: abandon the transport as soon as the page is gone.
        self.suspend_media()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Release movies and abandon in-flight requests before deletion."""
        self.suspend_media()
        self._clear_blocks()
