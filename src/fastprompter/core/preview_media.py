"""External-media policy and loader for the rich preview (T-1484).

Three separate concerns, deliberately kept apart:

* ``validate_remote_url`` -- the policy: HTTPS only, no loopback/private hosts,
  bounded length.  Pure, no Qt, testable on its own.
* ``MediaCache``           -- bounded LRU of decoded payloads.  Pure.
* ``RemoteImageLoader``    -- asynchronous transport with a hard timeout, a
  download cap and a concurrency limit, so a slow image host can never freeze
  the preview.

Nothing here writes to disk, executes downloaded content or follows a redirect
to a scheme/ host the policy would have refused in the first place.
"""

from __future__ import annotations

import ipaddress
import re
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_REMOTE_BYTES = 8 * 1024 * 1024
MAX_URL_LENGTH = 2048
DEFAULT_TIMEOUT_MS = 8000
DEFAULT_MAX_CONCURRENT = 3
# T-1488/D: how much of a live reply is moved out per drain step. The point is
# not throughput but EARLY refusal: the buffer is measured while the body is
# still arriving, so a hostile or misconfigured host can never make us hold
# the whole payload before we notice it is too large.
_READ_CHUNK = 256 * 1024
# A document may reference more images than the transport may run at once.
# Those wait in a bounded FIFO instead of being dropped: the old code returned
# silently at the concurrency cap, so every image past it stayed a bare link
# forever, with no cause and no retry.
MAX_QUEUED_REQUESTS = 64
CACHE_MAX_ITEMS = 24
CACHE_MAX_BYTES = 48 * 1024 * 1024

_REMOTE_RE = re.compile(r"^https?://", re.IGNORECASE)
_PRIVATE_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")


def validate_remote_url(url: str) -> bool:
    """True when ``url`` is a remote image we are willing to fetch.

    Refuses anything that is not plain HTTPS, anything with credentials, any
    loopback / private / link-local / multicast literal address and any host
    that is only reachable inside the machine or the LAN.
    """
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        return False
    if not url.lower().startswith("https://"):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() != "https":
        return False
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host or parts.username or parts.password:
        return False
    if host in ("localhost",) or host.endswith(_PRIVATE_SUFFIXES):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            return False
        return True
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


@dataclass(frozen=True)
class MediaPayload:
    url: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


class MediaCache:
    """Bounded LRU keyed by URL.

    Both dimensions are hard caps: a document with fifty large images keeps the
    twenty-four most recent within the byte budget instead of growing without
    limit for the life of the session.
    """

    def __init__(self, max_items: int = CACHE_MAX_ITEMS,
                 max_bytes: int = CACHE_MAX_BYTES):
        self.max_items = max(1, int(max_items))
        self.max_bytes = max(1, int(max_bytes))
        self._items: OrderedDict[str, MediaPayload] = OrderedDict()

    @property
    def bytes_used(self) -> int:
        return sum(item.size for item in self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def get(self, url: str) -> MediaPayload | None:
        item = self._items.get(url)
        if item is None:
            return None
        self._items.move_to_end(url)
        return item

    def put(self, payload: MediaPayload) -> None:
        if payload.size > self.max_bytes:
            return
        self._items[payload.url] = payload
        self._items.move_to_end(payload.url)
        while self._items and (len(self._items) > self.max_items
                               or self.bytes_used > self.max_bytes):
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


def looks_animated(url: str, data: bytes) -> bool:
    """True for a GIF payload (header), regardless of the URL suffix."""
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return (url or "").lower().split("?")[0].endswith(".gif")


class RemoteImageLoader:
    """Asynchronous HTTPS image loader built on QNetworkAccessManager.

    Imported lazily so the pure helpers above stay usable without Qt.
    """

    def __init__(self, parent=None, max_concurrent: int = DEFAULT_MAX_CONCURRENT,
                 timeout_ms: int = DEFAULT_TIMEOUT_MS, on_ready=None,
                 on_failed=None, cache: MediaCache | None = None):
        from PyQt6.QtCore import QObject
        from PyQt6.QtNetwork import QNetworkAccessManager

        self._qobject = QObject(parent)
        self._nam = QNetworkAccessManager(self._qobject)
        self._timeout_ms = int(timeout_ms)
        self._max_concurrent = max(1, int(max_concurrent))
        # ``cache or MediaCache()`` looked harmless but MediaCache defines
        # ``__len__``: an EMPTY injected cache is falsy, so the caller's cache
        # was silently replaced by a fresh one exactly while it had nothing in
        # it. Keep the object the caller handed us.
        self.cache = cache if cache is not None else MediaCache()
        self.on_ready = on_ready
        self.on_failed = on_failed
        self._pending: dict[str, object] = {}
        self._buffers: dict[str, bytearray] = {}
        self._oversize: set[str] = set()
        self._queue: list[str] = []
        self._pumping = False
        self._generation = 0

    # -- public -----------------------------------------------------------
    def cancel_all(self) -> None:
        """Abandon every in-flight request; late replies are ignored."""
        self._generation += 1
        for reply in list(self._pending.values()):
            try:
                reply.abort()
            except Exception:
                pass
        self._pending.clear()
        self._buffers.clear()
        self._oversize.clear()
        self._queue.clear()

    @property
    def pending_count(self) -> int:
        """How many requests are still in flight (T-1486 lifecycle probe)."""
        return len(self._pending)

    def request(self, url: str) -> None:
        """Queue ``url``; cached payloads answer immediately.

        A request beyond ``max_concurrent`` waits in a bounded FIFO and is
        started as soon as a slot frees, so no image is silently abandoned.
        """
        cached = self.cache.get(url)
        if cached is not None:
            if self.on_ready:
                self.on_ready(url, cached.data)
            return
        if url in self._pending or url in self._queue:
            return
        if not validate_remote_url(url):
            if self.on_failed:
                self.on_failed(url, "url rejected by policy")
            return
        if len(self._pending) >= self._max_concurrent:
            if len(self._queue) >= MAX_QUEUED_REQUESTS:
                if self.on_failed:
                    self.on_failed(url, "too many images are waiting")
                return
            self._queue.append(url)
            return
        self._start(url)

    def _start(self, url: str) -> None:
        """Open ONE transport request for an already policy-checked url."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtNetwork import QNetworkRequest

        request = QNetworkRequest(QUrl(url))
        try:
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        except Exception:
            pass
        request.setMaximumRedirectsAllowed(3)
        request.setTransferTimeout(self._timeout_ms)
        reply = self._nam.get(request)
        self._pending[url] = reply
        generation = self._generation
        # T-1488/D: drain WHILE the body arrives. The old code buffered the
        # whole payload and only then compared it to the cap.
        reply.readyRead.connect(
            lambda: self._on_ready_read(url, reply, generation))
        reply.finished.connect(lambda: self._finish(url, reply, generation))
        declared = self._declared_length(reply)
        if declared is not None and declared > MAX_REMOTE_BYTES:
            self._refuse_oversized(url, reply)

    # -- private ----------------------------------------------------------
    def _pump(self) -> None:
        """Start queued requests while the transport has free slots.

        Called when a slot frees (finish, refusal, abort). Re-entrant calls
        are ignored: ``_start`` can synchronously refuse a declared-too-large
        body, which pumps again from inside this loop.
        """
        if self._pumping:
            return
        self._pumping = True
        try:
            while self._queue and len(self._pending) < self._max_concurrent:
                url = self._queue.pop(0)
                if url in self._pending:
                    continue
                cached = self.cache.get(url)
                if cached is not None:
                    if self.on_ready:
                        self.on_ready(url, cached.data)
                    continue
                self._start(url)
        finally:
            self._pumping = False

    @staticmethod
    def _declared_length(reply) -> int | None:
        """``Content-Length`` when the host declared one, else None."""
        try:
            from PyQt6.QtNetwork import QNetworkRequest

            value = reply.header(
                QNetworkRequest.KnownHeaders.ContentLengthHeader)
        except Exception:
            return None
        try:
            length = int(value)
        except (TypeError, ValueError):
            return None
        return length if length >= 0 else None

    def _on_ready_read(self, url: str, reply, generation: int) -> None:
        if generation != self._generation:
            return
        self._drain(url, reply, generation)

    def _drain(self, url: str, reply, generation: int) -> bool:
        """Move the available bytes into the buffer; False once over the cap.

        Returns False immediately after refusing, so neither the transport nor
        the caller may keep growing the payload.
        """
        buffer = self._buffers.setdefault(url, bytearray())
        while True:
            available = reply.bytesAvailable()
            if available <= 0:
                return True
            chunk = bytes(reply.read(min(available, _READ_CHUNK)))
            if not chunk:
                return True
            buffer.extend(chunk)
            if len(buffer) > MAX_REMOTE_BYTES:
                self._refuse_oversized(url, reply)
                return False

    def _refuse_oversized(self, url: str, reply) -> None:
        """Abort a payload the moment it exceeds the cap, then report once."""
        self._pending.pop(url, None)
        self._buffers.pop(url, None)
        self._oversize.add(url)
        try:
            reply.abort()
        except Exception:
            pass
        if self.on_failed:
            self.on_failed(url, "image exceeds the size cap")
        self._pump()

    def _finish(self, url: str, reply, generation: int) -> None:
        try:
            self._pending.pop(url, None)
            if url in self._oversize:
                # Already refused mid-transfer; the abort's own finished signal
                # must not report a second, different failure.
                self._oversize.discard(url)
                reply.deleteLater()
                return
            if generation != self._generation:
                self._buffers.pop(url, None)
                reply.deleteLater()
                return
            try:
                if reply.error():
                    if self.on_failed:
                        self.on_failed(url, str(reply.errorString()))
                    return
                # Revalidate AFTER redirects: a public URL may not land
                # somewhere the policy would have refused.
                final = reply.url().toString()
                if not validate_remote_url(final):
                    if self.on_failed:
                        self.on_failed(url, "redirect target refused by policy")
                    return
                # Drain whatever is still queued after the last readyRead,
                # then judge the exact buffered size (never a post-hoc
                # readAll).
                if not self._drain(url, reply, generation):
                    return
                data = bytes(self._buffers.pop(url, b""))
                if not data:
                    if self.on_failed:
                        self.on_failed(url, "empty response")
                    return
                if len(data) > MAX_REMOTE_BYTES:
                    if self.on_failed:
                        self.on_failed(url, "image exceeds the size cap")
                    return
                if not self._looks_like_image(data):
                    if self.on_failed:
                        self.on_failed(url, "response is not an image")
                    return
                self.cache.put(MediaPayload(url=url, data=data))
                if self.on_ready:
                    self.on_ready(url, data)
            finally:
                self._buffers.pop(url, None)
                reply.deleteLater()
        finally:
            # A finished request frees a transport slot for the FIFO. This
            # runs on every exit path, including an abort we refused.
            self._pump()

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        head = data[:12]
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return True
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return True
        if head[:3] == b"\xff\xd8\xff":
            return True
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
