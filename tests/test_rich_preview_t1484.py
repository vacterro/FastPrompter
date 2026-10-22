"""T-1484: rich document preview (Markdown + BBCode) acceptance suite.

The pure renderer is exercised without Qt; the presentation surface is
exercised offscreen.  Every test asserts rendered STRUCTURE (nodes, attributes,
widgets, document frames) rather than the mere presence of a source substring.
"""

from __future__ import annotations

import pathlib
import re
import time

import pytest
from PyQt6.QtCore import QByteArray, QUrl
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QTextBrowser

from fastprompter.core import rich_preview
from fastprompter.core.preview_media import (
    MediaCache,
    MediaPayload,
    looks_animated,
    validate_remote_url,
)
from fastprompter.ui.rich_preview_view import RichPreviewView

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
VRV = (FIXTURES / "vrv_announcement.bbcode").read_text(encoding="utf-8")

#: A real two-frame 1x1 GIF: header, palette, two graphic-control-extension
#: frames and a trailer.  Qt only reports frameCount == 2 for a genuinely
#: animated GIF, so this is what makes "animated" testable rather than assumed.
ANIMATED_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    + b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00"
    + b"\x3b"
)


def body(doc: rich_preview.RenderedDocument) -> str:
    return doc.plain_body


# ---------------------------------------------------------------------------
# 1-2. headings, bold and italic nesting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_headings_render_at_their_level(level):
    doc = rich_preview.render(f"[h{level}]Title {level}[/h{level}]")
    assert doc.syntax == rich_preview.SYNTAX_BBCODE
    assert f"<h{level}>Title {level}</h{level}>" in body(doc)


def test_bold_and_italic_nest_into_real_elements():
    doc = rich_preview.render("[b]bold [i]and italic[/i][/b] [u]under[/u] [s]gone[/s]")
    html = body(doc)
    assert "<b>bold <i>and italic</i></b>" in html
    assert "<u>under</u>" in html
    assert "<s>gone</s>" in html


# ---------------------------------------------------------------------------
# 3. url tags -> safe anchors
# ---------------------------------------------------------------------------


def test_url_tag_produces_anchor_with_href():
    doc = rich_preview.render("[url=https://example.com/a?b=1&c=2]Link[/url]")
    html = body(doc)
    assert 'href="https://example.com/a?b=1&amp;c=2"' in html
    assert ">Link</a>" in html


def test_bare_url_tag_uses_its_body_as_target():
    doc = rich_preview.render("[url]https://example.com/x[/url]")
    assert 'href="https://example.com/x"' in body(doc)


def test_dangerous_url_tag_is_not_a_link():
    doc = rich_preview.render("[url=javascript:alert(1)]boom[/url]")
    html = body(doc)
    assert "javascript" not in html.lower()
    assert "boom" in html


# ---------------------------------------------------------------------------
# 4-5, 9. images
# ---------------------------------------------------------------------------


def test_png_image_becomes_a_media_reference():
    doc = rich_preview.render("[img]https://example.com/pic.png[/img]")
    assert doc.media == (rich_preview.MediaRef(
        url="https://example.com/pic.png", alt="", remote=True,
        animated_hint=False),)
    assert 'class="fp-media"' in body(doc)


def test_gif_image_is_marked_animated():
    doc = rich_preview.render("[img]https://example.com/anim.gif[/img]")
    ref = doc.media[0]
    assert ref.animated_hint is True
    assert ref.remote is True


def test_multiple_images_are_independent_media_entries():
    doc = rich_preview.render(
        "[img]https://a.example/1.png[/img]\n[img]https://b.example/2.png[/img]")
    assert [m.url for m in doc.media] == [
        "https://a.example/1.png", "https://b.example/2.png"]
    assert body(doc).count('class="fp-media"') == 2


# ---------------------------------------------------------------------------
# 6-8. tables and lists
# ---------------------------------------------------------------------------


def test_table_preserves_every_cell_and_real_rows():
    doc = rich_preview.render(
        "[table]\n"
        "[tr][th]A[/th][th]B[/th][/tr]\n"
        "[tr][td]1[/td][td]2[/td][/tr]\n"
        "[tr][td]3[/td][td]4[/td][/tr]\n"
        "[/table]")
    html = body(doc)
    assert html.count("<tr>") == 3
    assert html.count('class="h"') == 2
    assert html.count('class="c"') == 4
    for cell in ("A", "B", "1", "2", "3", "4"):
        assert cell in html
    assert "table" in html.split("<table>", 1)[0] + html   # a real table element
    assert "<table>" in html and "</table>" in html


def test_nested_bold_inside_a_table_cell_renders():
    doc = rich_preview.render("[table][tr][td][b]7[/b][/td][/tr][/table]")
    html = body(doc)
    assert '<td class="c"><b>7</b></td>' in html


def test_list_items_keep_their_order():
    doc = rich_preview.render("[list][*]first[*]second[*]third[/list]")
    html = body(doc)
    assert html.count("<li>") == 3
    assert html.index("first") < html.index("second") < html.index("third")


def test_ordered_list_attribute_is_honoured():
    doc = rich_preview.render("[list=1][*]one[*]two[/list]")
    assert "<ol>" in body(doc)


# ---------------------------------------------------------------------------
# 10-13. mixed, code fences, unknown and malformed markup
# ---------------------------------------------------------------------------


def test_mixed_document_renders_bbcode_blocks_and_markdown_inline():
    doc = rich_preview.render(
        "[h2]Section[/h2]\n"
        "A paragraph with **markdown bold** and [b]bbcode bold[/b].\n")
    html = body(doc)
    assert "<h2>Section</h2>" in html
    assert "<b>markdown bold</b>" in html
    assert "<b>bbcode bold</b>" in html


def test_code_block_keeps_tag_text_literal():
    doc = rich_preview.render("[code][b]not bold[/b] [table][/table][/code]")
    html = body(doc)
    assert "<pre><code>" in html
    inside = html.split("<pre>", 1)[1].split("</pre>", 1)[0]
    assert "[b]not bold[/b]" in inside
    assert "[table]" in inside
    assert "<b>" not in inside and "<table>" not in inside, (
        "code content must stay literal, never become live markup")
    assert "<table>" not in html.replace(inside, "")


def test_markdown_fence_keeps_bbcode_literal():
    doc = rich_preview.render("```\n[b]literal[/b]\n```", syntax="Markdown")
    html = body(doc)
    assert "[b]literal[/b]" in html
    assert "<b>literal</b>" not in html


def test_unknown_tags_are_preserved_not_deleted():
    doc = rich_preview.render("[unknown]keep me[/unknown]")
    html = body(doc)
    assert "[unknown]" in html and "[/unknown]" in html and "keep me" in html


def test_malformed_markup_cannot_crash_the_renderer():
    for source in ("[b]unclosed", "[/b]stray close",
                   "[table][tr][td]no close", "[url=http://x", "[list][*]"):
        doc = rich_preview.render(source)
        assert doc.html.startswith("<html>")


# ---------------------------------------------------------------------------
# 14-15. unsafe HTML and unsafe links
# ---------------------------------------------------------------------------


def test_scripts_and_event_handlers_are_inert():
    doc = rich_preview.render(
        '<script>alert(1)</script><img src="x.png" onerror="alert(2)">'
        '<iframe src="https://evil.example"></iframe>'
        '<a href="javascript:alert(3)">click</a>')
    html = body(doc)
    assert "<script" not in html.lower()
    assert "onerror" not in html.lower()
    assert "<iframe" not in html.lower()
    assert "javascript:" not in html.lower()
    # the words the document contained are still readable, just inert
    assert "alert(1)" in html
    assert "click" in html


def test_unsafe_html_entities_are_not_double_escaped():
    doc = rich_preview.render("a &amp; b &lt; c", syntax="Markdown")
    html = body(doc)
    assert "a &amp; b &lt; c" in html
    assert "&amp;amp;" not in html


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "data:text/html,<script>", "vbscript:msgbox",
])
def test_dangerous_markdown_links_lose_their_href(href):
    doc = rich_preview.render(f"[text]({href})", syntax="Markdown")
    assert "href=" not in body(doc)


# ---------------------------------------------------------------------------
# 16-19. media policy and loading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://example.com/a.png",          # not https
    "https://localhost/a.png",
    "https://127.0.0.1/a.png",
    "https://10.0.0.5/a.png",
    "https://169.254.1.1/a.png",
    "https://user:pw@example.com/a.png",
    "https://intranet.local/a.png",
    "ftp://example.com/a.png",
    "",
])
def test_remote_policy_refuses_unsafe_targets(url):
    assert validate_remote_url(url) is False


def test_remote_policy_allows_a_plain_https_image_host():
    assert validate_remote_url("https://i.ibb.co/2YPvk7cQ/otd546d2.png") is True


def test_remote_images_are_not_fetched_without_permission(qapp):
    view = RichPreviewView()
    view.set_external_media_enabled(False)
    doc = rich_preview.render("[img]https://example.com/pic.png[/img]",
                             allow_remote=False)
    view.set_rendered_document(doc)
    assert view._loader is None, "no network object may exist while the opt-in is off"
    labels = [w for w in view._blocks if w.__class__.__name__ == "_MediaBlock"]
    assert labels and "https://example.com/pic.png" in labels[0].text()
    view.deleteLater()
    QApplication.processEvents()


def test_failed_local_image_shows_a_placeholder(qapp, tmp_path):
    view = RichPreviewView()
    missing = tmp_path / "gone.png"
    doc = rich_preview.render(f"[img]{missing.as_posix()}[/img]")
    view.set_rendered_document(doc)
    labels = [w for w in view._blocks if w.__class__.__name__ == "_MediaBlock"]
    assert labels and labels[0].pixmap().isNull()
    view.deleteLater()
    QApplication.processEvents()


PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
          b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82")


class _Signal:
    """The only part of a Qt signal the loader uses."""

    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self):
        for slot in list(self.slots):
            slot()


class _FakeReply:
    """QNetworkReply as the loader actually uses it.

    T-1488/D: the loader now DRAINS a reply while the body arrives, so the fake
    has to be able to hand out bytes in pieces and report how many were taken
    — otherwise the size cap could only ever be tested after full buffering,
    which is precisely the behaviour the defect was.
    """

    def __init__(self, data=b"", failed=False, final_url="https://e.example/x.png",
                 declared_length=None):
        self._data = bytes(data)
        self._pos = 0
        self._failed = failed
        self._url = final_url
        self._declared = declared_length
        self.aborted = False
        self.deleted = False
        self.readyRead = _Signal()
        self.finished = _Signal()

    def error(self):
        return 1 if self._failed else 0

    def errorString(self):
        return "boom"

    def bytesAvailable(self):
        return 0 if self.aborted else max(0, len(self._data) - self._pos)

    def read(self, n):
        if self.aborted:
            return QByteArray()
        chunk = self._data[self._pos:self._pos + max(0, int(n))]
        self._pos += len(chunk)
        return QByteArray(chunk)

    def readAll(self):
        return self.read(self.bytesAvailable())

    @property
    def consumed(self):
        return self._pos

    def header(self, name):
        return self._declared

    def url(self):
        return QUrl(self._url)

    def abort(self):
        self.aborted = True

    def deleteLater(self):
        self.deleted = True


class _FakeNAM:
    def __init__(self, reply):
        self.reply = reply

    def get(self, request):
        return self.reply


def _loader(qapp, cache=None):
    from fastprompter.core.preview_media import RemoteImageLoader

    return RemoteImageLoader(cache=cache or MediaCache())


def test_cached_payload_is_answered_without_touching_the_network(qapp):
    cache = MediaCache()
    cache.put(MediaPayload("https://e.example/x.png", PNG_1PX))
    loader = _loader(qapp, cache)
    ready, failed = [], []
    loader.on_ready = lambda url, data: ready.append((url, data))
    loader.on_failed = lambda url, why: failed.append((url, why))
    loader.request("https://e.example/x.png")
    assert ready == [("https://e.example/x.png", PNG_1PX)]
    assert failed == []
    assert loader._pending == {}, "a cache hit must not open a transport"


class _MultiReplyNAM:
    """A QNetworkAccessManager that answers each url with its own reply."""

    def __init__(self):
        self.urls = []
        self.replies = {}

    def get(self, request):
        url = request.url().toString()
        self.urls.append(url)
        reply = _FakeReply(data=PNG_1PX, final_url=url)
        self.replies[url] = reply
        return reply


def test_requests_beyond_the_concurrency_cap_wait_instead_of_vanishing(qapp):
    # Review finding: ``request`` returned silently at the concurrency cap, so
    # every image past the third in one document stayed a bare link forever --
    # no cause, no retry, nothing to notice. They must wait their turn.
    from fastprompter.core.preview_media import RemoteImageLoader

    loader = RemoteImageLoader(max_concurrent=1)
    nam = _MultiReplyNAM()
    loader._nam = nam
    ready = []
    loader.on_ready = lambda url, data: ready.append(url)

    for i in range(1, 4):
        loader.request(f"https://e.example/{i}.png")
    assert nam.urls == ["https://e.example/1.png"], (
        "one slot: the later images must be queued, not dropped")
    assert loader._queue == ["https://e.example/2.png",
                             "https://e.example/3.png"]

    loader._finish("https://e.example/1.png",
                   nam.replies["https://e.example/1.png"],
                   loader._generation)
    assert nam.urls == ["https://e.example/1.png", "https://e.example/2.png"], (
        "a finished request must free its slot for the next queued image")
    assert ready == ["https://e.example/1.png"]


def test_the_waiting_queue_is_bounded(qapp, monkeypatch):
    from fastprompter.core import preview_media as pm

    monkeypatch.setattr(pm, "MAX_QUEUED_REQUESTS", 2)
    loader = pm.RemoteImageLoader(max_concurrent=1)
    loader._nam = _MultiReplyNAM()
    failed = []
    loader.on_failed = lambda url, why: failed.append(why)

    for i in range(5):
        loader.request(f"https://e.example/q{i}.png")
    assert len(loader._queue) == 2, "the FIFO must not grow without bound"
    assert failed == ["too many images are waiting"] * 2, (
        "an image that cannot even be queued must report, never vanish")


def test_a_failed_transfer_never_enters_the_cache(qapp):
    cache = MediaCache()
    loader = _loader(qapp, cache)
    failed = []
    loader.on_failed = lambda url, why: failed.append((url, why))
    url = "https://e.example/x.png"
    loader._finish(url, _FakeReply(failed=True), loader._generation)
    assert failed and failed[0][0] == url
    assert cache.get(url) is None


def test_an_oversized_payload_is_refused(qapp):
    from fastprompter.core.preview_media import MAX_REMOTE_BYTES

    cache = MediaCache()
    loader = _loader(qapp, cache)
    failed = []
    loader.on_failed = lambda url, why: failed.append((url, why))
    url = "https://e.example/huge.png"
    loader._finish(url, _FakeReply(data=PNG_1PX + b"x" * MAX_REMOTE_BYTES),
                   loader._generation)
    assert failed and "size" in failed[0][1]
    assert cache.get(url) is None


def test_a_non_image_response_is_refused(qapp):
    cache = MediaCache()
    loader = _loader(qapp, cache)
    failed = []
    loader.on_failed = lambda url, why: failed.append((url, why))
    url = "https://e.example/page.html"
    loader._finish(url, _FakeReply(data=b"<html>not an image</html>"),
                   loader._generation)
    assert failed and "image" in failed[0][1]
    assert cache.get(url) is None


def test_a_redirect_to_a_refused_host_is_not_followed(qapp):
    cache = MediaCache()
    loader = _loader(qapp, cache)
    failed = []
    loader.on_failed = lambda url, why: failed.append((url, why))
    url = "https://e.example/x.png"
    loader._finish(url, _FakeReply(data=PNG_1PX,
                                   final_url="https://127.0.0.1/secret.png"),
                   loader._generation)
    assert failed and "redirect" in failed[0][1]
    assert cache.get(url) is None


def test_a_cancelled_generation_is_ignored(qapp):
    loader = _loader(qapp)
    ready, failed = [], []
    loader.on_ready = lambda url, data: ready.append(url)
    loader.on_failed = lambda url, why: failed.append(url)
    generation = loader._generation
    loader.cancel_all()
    loader._finish("https://e.example/x.png", _FakeReply(data=PNG_1PX), generation)
    assert ready == [] and failed == [], (
        "a reply for an abandoned document must not touch the current one")


def test_cache_refuses_payloads_over_its_byte_budget():
    cache = MediaCache(max_items=4, max_bytes=1024)
    cache.put(MediaPayload("https://a/1.png", b"x" * 900))
    cache.put(MediaPayload("https://a/2.png", b"x" * 900))
    assert len(cache) == 1, "the byte cap must evict, not accumulate"
    cache.put(MediaPayload("https://a/big.png", b"x" * 2048))
    assert cache.get("https://a/big.png") is None


def test_local_image_is_scaled_and_keeps_its_aspect_ratio(qapp, tmp_path):
    path = tmp_path / "wide.png"
    image = QImage(200, 50, QImage.Format.Format_RGB32)
    image.fill(QColor("#808080"))
    assert image.save(str(path))
    view = RichPreviewView()
    view.resize(120, 400)
    view.show()
    QApplication.processEvents()
    view.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    QApplication.processEvents()
    label = [w for w in view._blocks if w.__class__.__name__ == "_MediaBlock"][0]
    assert not label.pixmap().isNull()
    pixmap = label.pixmap()
    assert pixmap.width() <= view.viewport().width()
    assert abs(pixmap.height() / pixmap.width() - 0.25) < 0.02
    view.deleteLater()
    QApplication.processEvents()


def test_animated_gif_really_animates(qapp, tmp_path):
    path = tmp_path / "anim.gif"
    path.write_bytes(ANIMATED_GIF)
    assert looks_animated(path.as_posix(), ANIMATED_GIF)
    view = RichPreviewView()
    view.resize(200, 400)
    view.show()
    view.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    QApplication.processEvents()
    label = [w for w in view._blocks if w.__class__.__name__ == "_MediaBlock"][0]
    movie = label._movie
    assert movie is not None, "a GIF must be presented by a QMovie, not a still frame"
    assert movie.isValid()
    assert movie.frameCount() >= 2
    view.deleteLater()
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# 20-23. structure, source integrity, stale media, read-only
# ---------------------------------------------------------------------------


def test_wide_table_is_rendered_as_a_document_table(qapp):
    columns = "".join(f"[th]Header {i}[/th]" for i in range(8))
    cells = "".join(f"[td]value {i}[/td]" for i in range(8))
    doc = rich_preview.render(f"[table][tr]{columns}[/tr][tr]{cells}[/tr][/table]")
    view = RichPreviewView()
    view.set_rendered_document(doc)
    browser = [w for w in view._blocks if isinstance(w, QTextBrowser)]
    assert browser, "a table must land on a real rich-text block"
    root = browser[0].document().rootFrame()
    assert len(list(root.childFrames())) >= 1, "Qt must have built a real QTextTable"
    assert browser[0].horizontalScrollBarPolicy().name != "ScrollBarAlwaysOff"
    view.deleteLater()
    QApplication.processEvents()


def test_changing_syntax_never_changes_the_source():
    source = "[h1]Title[/h1]\n\n**text** with [b]tags[/b]\r\n"
    auto = rich_preview.render(source)
    markdown = rich_preview.render(source, syntax="Markdown")
    bbcode = rich_preview.render(source, syntax="BBCode")
    for doc in (auto, markdown, bbcode):
        assert doc.source == source
    # Auto recognises the BBCode structure, so it must agree with an explicit
    # BBCode choice; an explicit Markdown choice must differ (it shows the raw
    # region markers instead), and the source stays byte-identical throughout.
    assert auto.html == bbcode.html
    assert markdown.html != bbcode.html
    assert "[h1]Title[/h1]" in body(markdown)
    assert "<h1>Title</h1>" in body(bbcode)


def test_switching_documents_drops_the_previous_media(qapp, tmp_path):
    path = tmp_path / "one.png"
    QImage(20, 20, QImage.Format.Format_RGB32).save(str(path))
    view = RichPreviewView()
    view.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    assert view._media_blocks, "the first document had media"
    view.set_rendered_document(rich_preview.render("[h1]no media[/h1]"))
    assert view._media_blocks == {}
    assert not [w for w in view._blocks
                if w.__class__.__name__ == "_MediaBlock"]
    view.deleteLater()
    QApplication.processEvents()


def test_reading_surface_is_read_only(qapp):
    view = RichPreviewView()
    view.set_rendered_document(rich_preview.render("[h1]x[/h1]"))
    # the window drives this state, so the test drives it the same way
    view.setReadOnly(True)
    assert view.isReadOnly() is True
    for block in view._blocks:
        if isinstance(block, QTextBrowser):
            assert block.isReadOnly() is True
    view.setReadOnly(False)
    assert view.isReadOnly() is False
    view.setReadOnly(True)
    assert view.isReadOnly() is True, (
        "the Reading surface must return to read-only, not latch editable")
    view.deleteLater()
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# 24-28. no mutation, no duplicate navigation, theme
# ---------------------------------------------------------------------------


def test_rendering_never_touches_the_editor_document():
    from unittest.mock import MagicMock

    from fastprompter.ui.formatting_mixin import FormattingMixin

    window = FormattingMixin.__new__(FormattingMixin)
    window.text_area = MagicMock()
    window.data = {}
    FormattingMixin.simple_markdown_to_html(window, "[b]x[/b]")
    assert not window.text_area.mock_calls, (
        "the renderer is presentation only: it may not touch the editor")


def test_one_anchor_click_emits_one_navigation(qapp):
    view = RichPreviewView()
    seen = []
    view.linkActivated.connect(seen.append)
    view._on_anchor_clicked(QUrl("https://example.com/x"))
    assert seen == ["https://example.com/x"]
    view.deleteLater()
    QApplication.processEvents()


def test_rendering_follows_the_active_theme_tokens():
    doc = rich_preview.render("[h1]x[/h1]", tokens={"heading": "#123456",
                                                    "bg": "#0a0a0a"})
    assert "#123456" in doc.html
    assert "#0a0a0a" in doc.html


def test_large_document_renders_within_a_bounded_time():
    paragraph = ("The recycler consumes the queued scrap and reports back. "
                 "[b]bold[/b] and `code` and [url=https://e.example/x]link[/url].\n\n")
    source = "[h1]Big[/h1]\n\n" + paragraph * 900
    assert len(source) > 100_000
    started = time.perf_counter()
    doc = rich_preview.render(source)
    elapsed = time.perf_counter() - started
    assert len(doc.html) > 100_000
    assert elapsed < 5.0, f"100KB+ document took {elapsed:.2f}s"


def test_autolink_skips_code_and_existing_links():
    doc = rich_preview.render(
        "see https://plain.example/x and `https://code.example/y` "
        "and [https://linked.example/z](https://linked.example/z)",
        syntax="Markdown")
    html = body(doc)
    assert 'href="https://plain.example/x"' in html
    assert "https://code.example/y" in html
    assert html.count("code.example/y</a>") == 0
    assert html.count('href="https://linked.example/z"') == 1


# ---------------------------------------------------------------------------
# golden VRV acceptance
# ---------------------------------------------------------------------------


def test_vrv_fixture_has_substantial_content():
    assert len(VRV.splitlines()) > 150
    assert len(VRV) > 6000


def test_vrv_fixture_renders_as_a_real_document():
    doc = rich_preview.render(VRV)
    html = body(doc)
    assert doc.syntax == rich_preview.SYNTAX_BBCODE
    # heading hierarchy
    for tag in ("<h1>", "<h2>", "<h3>"):
        assert tag in html
    # no visible markup for supported tags.  The [code] block is excluded on
    # purpose: its content is REQUIRED to stay literal, so a tag there is the
    # correct rendering, not a leak.
    visible = re.sub(r"<pre>.*?</pre>", "", html, flags=re.S)
    for token in ("[b]", "[/b]", "[h1]", "[table]", "[tr]", "[td]", "[list]",
                  "[*]", "[url", "[img]"):
        assert token not in visible, f"{token} leaked into the rendered document"
    # genuine bold text
    assert "<b>Overhauled mission DLLs for VSR</b>" in html
    # real tables, not flattened paragraphs
    assert html.count("<table>") >= 2
    # 3 + 4 + 4 header cells across the fixture's three tables
    assert html.count('class="h"') == 11
    assert html.count('class="c"') >= 40
    # lists keep their items
    assert html.count("<li>") >= 20
    # literal bracketed prose survives untouched
    for literal in ("(&lt;25%, default)", "(&lt;8%)", "(2+ units)"):
        assert literal in html
    # code block stays literal
    assert "[table]" in html.split("<pre>")[1]
    # links are real anchors
    assert 'href="https://steamcommunity.com/sharedfiles/filedetails/?id=1325933293"' in html


def test_vrv_fixture_images_are_discovered_but_not_fetched(qapp):
    doc = rich_preview.render(VRV)
    assert [m.url for m in doc.media] == [
        "https://i.ibb.co/2YPvk7cQ/otd546d2.png",
        "https://i.ibb.co/PZWPsqnQ/ql50flhx.png",
        "https://i.ibb.co/spC8pKWd/0ypbm015.gif",
    ]
    assert doc.media[2].animated_hint is True
    view = RichPreviewView()
    view.set_rendered_document(doc)
    assert view._loader is None
    media = [w for w in view._blocks if w.__class__.__name__ == "_MediaBlock"]
    assert len(media) == 3
    assert all("i.ibb.co" in w.text() for w in media)
    view.deleteLater()
    QApplication.processEvents()


def test_vrv_fixture_source_is_byte_identical_after_rendering():
    before = VRV
    doc = rich_preview.render(VRV)
    assert doc.source == before
    assert VRV == before


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def test_bracketed_prose_is_not_mistaken_for_bbcode():
    assert rich_preview.detect_syntax("See [1] and [note] for details.") == \
        rich_preview.SYNTAX_MARKDOWN


def test_bbcode_structure_is_detected():
    assert rich_preview.detect_syntax("[b]x[/b] [i]y[/i]") == \
        rich_preview.SYNTAX_BBCODE
    assert rich_preview.detect_syntax("[h1]x[/h1]") == rich_preview.SYNTAX_BBCODE
    assert rich_preview.detect_syntax("# plain markdown") == \
        rich_preview.SYNTAX_MARKDOWN
    assert rich_preview.detect_syntax("   ") == rich_preview.SYNTAX_PLAIN


def test_media_marker_is_not_forgeable_from_document_text():
    doc = rich_preview.render(
        '<div class="fp-media" data-src="https://evil.example/x.png"></div>'
        '<img src="https://ok.example/real.png" alt="real">')
    assert doc.media == (rich_preview.MediaRef(
        url="https://ok.example/real.png", alt="real", remote=True),)
    assert body(doc).count('class="fp-media"') == 1

# ---------------------------------------------------------------------------
# T-1488 post-closure: split_blocks structure, identity, escaping, bounded I/O
# ---------------------------------------------------------------------------


def test_image_alt_containing_a_slash_still_splits_as_media():
    # Finding A: the marker regex stopped its attribute class at "/", so an
    # alt of "A/B" pushed the WHOLE marker into an html block and the image
    # disappeared into escaped text.
    doc = rich_preview.render(
        "![A/B](https://e.example/x.png)", allow_remote=True)
    assert doc.media and doc.media[0].alt == "A/B"
    blocks = rich_preview.split_blocks(doc.plain_body)
    media = [payload for kind, payload in blocks if kind == "media"]
    assert media == ["https://e.example/x.png"]
    for kind, payload in blocks:
        if kind == "html":
            assert rich_preview.MEDIA_CLASS not in payload


def test_multi_parameter_url_round_trips_byte_exactly():
    # Finding B: data-src is stored HTML-escaped; the block payload used to
    # come back as "x=1&amp;y=2", which never equalled MediaRef.url.
    url = "https://e.example/i.png?x=1&y=2&z=3"
    doc = rich_preview.render(f"![pic]({url})", allow_remote=True)
    assert doc.media[0].url == url
    payloads = [p for k, p in rich_preview.split_blocks(doc.plain_body)
                if k == "media"]
    assert payloads == [url]


def test_media_block_identity_survives_the_split(qapp):
    url = "https://e.example/i.png?a=1&b=2"
    doc = rich_preview.render(f"![pic]({url})", allow_remote=True)
    view = RichPreviewView()
    view.configure(external_media=False)
    view.set_rendered_document(doc)
    block = [w for w in view._blocks
             if w.__class__.__name__ == "_MediaBlock"][0]
    ref = doc.media[0]
    assert block._ref.url == ref.url
    assert block._ref is view._ref_for(url), (
        "the block must reuse the document's MediaRef, not a lookalike")
    view.deleteLater()
    QApplication.processEvents()


def test_hostile_alt_text_stays_literal_in_the_placeholder(qapp):
    # Finding C: the alt was interpolated into rich HTML unescaped, so an
    # encoded tag in the alt text became live markup inside the placeholder.
    hostile = '<img src=x onerror="alert(1)">'
    doc = rich_preview.render(
        f"![{hostile}](https://e.example/x.png)", allow_remote=True)
    view = RichPreviewView()
    view.configure(external_media=False)
    view.set_rendered_document(doc)
    block = [w for w in view._blocks
             if w.__class__.__name__ == "_MediaBlock"][0]
    shown = block.text()
    assert "<img" not in shown, "the alt must never become live markup"
    assert "&lt;img" in shown, "the alt must still be visible, as text"
    view.deleteLater()
    QApplication.processEvents()


def test_oversized_transfer_is_aborted_before_the_whole_body_arrives(qapp):
    # Finding D: the loader read the WHOLE reply and then compared it to the
    # cap. It must stop the transfer once the cap is crossed.
    from fastprompter.core.preview_media import MAX_REMOTE_BYTES

    loader = _loader(qapp)
    failed = []
    loader.on_failed = lambda url, why: failed.append(why)
    url = "https://e.example/huge.png"
    reply = _FakeReply(data=b"\x00" * (MAX_REMOTE_BYTES * 3))
    loader._pending[url] = reply

    assert loader._drain(url, reply, loader._generation) is False
    assert reply.aborted, "the transfer must be aborted, not merely refused"
    assert reply.consumed < len(reply._data), (
        "the loader must not consume the whole oversized payload")
    assert reply.consumed <= MAX_REMOTE_BYTES + 2 * 256 * 1024
    assert len(failed) == 1 and "size" in failed[0]
    assert loader.cache.get(url) is None

    # The abort's own finished signal carries the same URL; it must not
    # report a second, different failure for the same payload.
    loader._finish(url, reply, loader._generation)
    assert len(failed) == 1


def test_declared_content_length_is_refused_before_any_body(qapp):
    from fastprompter.core.preview_media import MAX_REMOTE_BYTES

    reply = _FakeReply(data=b"", declared_length=MAX_REMOTE_BYTES + 1)
    loader = _loader(qapp)
    loader._nam = _FakeNAM(reply)
    failed = []
    loader.on_failed = lambda url, why: failed.append(why)

    loader.request("https://e.example/declared-too-big.png")
    assert reply.aborted is True
    assert reply.consumed == 0, "no body may be read once the size is declared"
    assert len(failed) == 1 and "size" in failed[0]


# ---------------------------------------------------------------------------
# T-1486: the surface owns its animations and requests
# ---------------------------------------------------------------------------


def _animated_view(tmp_path, size=(200, 400)):
    path = tmp_path / "tick.gif"
    path.write_bytes(ANIMATED_GIF)
    view = RichPreviewView()
    view.resize(*size)
    view.show()
    view.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    QApplication.processEvents()
    return view


def test_suspending_the_surface_stops_every_animation(qapp, tmp_path):
    view = _animated_view(tmp_path)
    assert view.running_movie_count() == 1, "the GIF must be ticking first"
    view.suspend_media()
    assert view.running_movie_count() == 0, (
        "leaving Reading must stop every QMovie, not just hide the widget")
    view.deleteLater()
    QApplication.processEvents()


def test_returning_restores_the_animation_without_duplicating_it(qapp, tmp_path):
    view = _animated_view(tmp_path)
    blocks_before = len(view._blocks)
    media_before = sum(len(v) for v in view._media_blocks.values())
    for _ in range(3):
        view.suspend_media()
        assert view.running_movie_count() == 0
        view.resume_media()
        assert view.running_movie_count() == 1
    assert len(view._blocks) == blocks_before
    assert sum(len(v) for v in view._media_blocks.values()) == media_before, (
        "repeated switching must not accumulate blocks or movies")
    view.deleteLater()
    QApplication.processEvents()


def test_a_document_arriving_while_suspended_does_not_animate(qapp, tmp_path):
    path = tmp_path / "late.gif"
    path.write_bytes(ANIMATED_GIF)
    view = RichPreviewView()
    view.resize(200, 400)
    view.show()
    view.suspend_media()
    view.set_rendered_document(
        rich_preview.render(f"[img]{path.as_posix()}[/img]"))
    QApplication.processEvents()
    assert view.running_movie_count() == 0, (
        "a document that arrives while Reading is closed must not animate")
    view.resume_media()
    QApplication.processEvents()
    assert view.running_movie_count() == 1, (
        "the retained payload must replay on return, without re-reading disk")
    view.deleteLater()
    QApplication.processEvents()


def test_returning_to_reading_restores_the_scroll_position(qapp):
    source = "\n\n".join(f"Paragraph {i} " + "text " * 40 for i in range(60))
    view = RichPreviewView()
    view.resize(320, 200)
    view.show()
    QApplication.processEvents()
    view.set_rendered_document(rich_preview.render(source))
    QApplication.processEvents()
    QApplication.processEvents()

    bar = view.verticalScrollBar()
    assert bar.maximum() > 0, "the document must be long enough to scroll"
    bar.setValue(min(400, bar.maximum()))
    QApplication.processEvents()
    saved = bar.value()
    assert saved > 0

    # Leaving Reading and returning re-renders the same document: the reader
    # must not be thrown back to the top.
    view.suspend_media()
    view.set_rendered_document(rich_preview.render(source))
    view.resume_media()
    QApplication.processEvents()
    QApplication.processEvents()
    assert view.verticalScrollBar().value() == saved

    # An EDITED document must not inherit the old offset.
    view.suspend_media()
    view.set_rendered_document(rich_preview.render("short, new document"))
    view.resume_media()
    QApplication.processEvents()
    QApplication.processEvents()
    assert view.verticalScrollBar().value() == 0
    view.deleteLater()
    QApplication.processEvents()


def test_suspending_abandons_in_flight_requests(qapp):
    class _FakeLoader:
        def __init__(self):
            self.cancelled = 0
            self.pending = 2

        def cancel_all(self):
            self.cancelled += 1
            self.pending = 0

        @property
        def pending_count(self):
            return self.pending

    view = RichPreviewView()
    loader = _FakeLoader()
    view._loader = loader
    assert view.pending_remote_requests == 2
    view.suspend_media()
    assert loader.cancelled == 1, "every in-flight request must be abandoned"
    assert view.pending_remote_requests == 0
    # The transport OBJECT is retained (one QNetworkAccessManager per surface,
    # not one per mode switch); only its traffic is abandoned.
    assert view._loader is loader
    view.deleteLater()
    QApplication.processEvents()


def test_control_the_reuse_gate_detects_the_pre_fix_suspend(qapp, monkeypatch):
    """Instrument control (VERIFY-ORACLE-01): the known-bad subject.

    With the PRE-FIX ``_stop_network`` restored (drop the loader), the reuse
    gate above must go RED -- otherwise that gate proves nothing.
    """
    from fastprompter.core.preview_media import RemoteImageLoader as _Real
    from fastprompter.ui import rich_preview_view as view_module

    created = []

    class _Offline(_Real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._nam = _FakeNAM(_FakeReply(data=PNG_1PX))
            created.append(self)

    monkeypatch.setattr(view_module, "RemoteImageLoader", _Offline)

    def pre_fix_stop_network(self):
        if self._loader is not None:
            self._loader.cancel_all()
            self._loader = None

    monkeypatch.setattr(RichPreviewView, "_stop_network", pre_fix_stop_network)
    view = RichPreviewView()
    view.configure(external_media=True)
    view.set_rendered_document(
        rich_preview.render("![a](https://e.example/x.png)", allow_remote=True))
    for _ in range(4):
        view.suspend_media()
        view.resume_media()
    assert len(created) > 1, "the pre-fix subject really does leak a transport"
    with pytest.raises(AssertionError):
        assert len(created) == 1      # the reuse gate goes red on those bytes
    view.deleteLater()
    QApplication.processEvents()


def test_repeated_switching_reuses_one_transport_and_its_cache(qapp, monkeypatch):
    from fastprompter.core.preview_media import RemoteImageLoader as _Real
    from fastprompter.ui import rich_preview_view as view_module

    created = []

    class _Offline(_Real):
        """The real loader, wired to a fake transport (no test traffic)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._nam = _FakeNAM(_FakeReply(data=PNG_1PX))
            created.append(self)

    monkeypatch.setattr(view_module, "RemoteImageLoader", _Offline)
    view = RichPreviewView()
    view.configure(external_media=True)
    view.set_rendered_document(
        rich_preview.render("![a](https://e.example/x.png)", allow_remote=True))
    assert len(created) == 1
    cache = view._media_cache
    for _ in range(4):
        view.suspend_media()
        assert view.pending_remote_requests == 0
        view.resume_media()
        assert view.pending_remote_requests == 1, (
            "one visible image, one request -- never a duplicate")
    assert len(created) == 1, (
        "each switch must not build another QNetworkAccessManager child")
    assert view._loader is created[0]
    assert view._loader.cache is cache, (
        "the decoded-payload cache must survive leaving Reading")
    view.deleteLater()
    QApplication.processEvents()


def test_a_suspended_surface_starts_no_remote_request(qapp):
    view = RichPreviewView()
    view.configure(external_media=True)
    view.suspend_media()
    view.set_rendered_document(
        rich_preview.render("![x](https://e.example/x.png)", allow_remote=True))
    assert view.pending_remote_requests == 0
    assert view._loader is None, (
        "a document nobody is looking at must not open a transport")
    view.resume_media()
    view.suspend_media()
    view.deleteLater()
    QApplication.processEvents()


def test_failure_causes_are_distinguishable(qapp, tmp_path):
    from fastprompter.ui import rich_preview_view as view_module

    view = RichPreviewView()
    view.configure(external_media=False)

    off = view_module._MediaBlock(
        view, rich_preview.MediaRef(url="https://e.example/a.png", remote=True))
    refused = view_module._MediaBlock(
        view, rich_preview.MediaRef(url="https://127.0.0.1/b.png", remote=True))
    refused.set_failed(view_module.MEDIA_CAUSE_REFUSED)
    missing = view_module._MediaBlock(
        view, rich_preview.MediaRef(url=str(tmp_path / "gone.png")))
    texts = {b.text() for b in (off, refused, missing)}
    assert len(texts) == 3, (
        "external-media-off, a policy refusal and an unavailable file must "
        "not render the same anonymous box")
    # …and each box must carry ITS OWN cause, not just its own URL.
    assert view_module._MEDIA_NOTES[view_module.MEDIA_CAUSE_OFF] in off.text()
    assert view_module._MEDIA_NOTES[view_module.MEDIA_CAUSE_REFUSED] \
        in refused.text()
    assert view_module._MEDIA_NOTES[view_module.MEDIA_CAUSE_LOCAL] \
        in missing.text()

    for cause in (view_module.MEDIA_CAUSE_OFF, view_module.MEDIA_CAUSE_REFUSED,
                  view_module.MEDIA_CAUSE_TRANSFER,
                  view_module.MEDIA_CAUSE_OVERSIZED,
                  view_module.MEDIA_CAUSE_DECODE, view_module.MEDIA_CAUSE_LOCAL):
        assert view_module._MEDIA_NOTES[cause]


def test_query_tokens_never_reach_the_log(qapp, caplog):
    from fastprompter.ui import rich_preview_view as view_module

    view = RichPreviewView()
    block = view_module._MediaBlock(
        view, rich_preview.MediaRef(
            url="https://cdn.example/a.png?Signature=SECRET123", remote=True))
    with caplog.at_level("WARNING"):
        block.set_failed(view_module.MEDIA_CAUSE_TRANSFER, "timeout")
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRET123" not in joined, (
        "a signed CDN query must never be copied into the log")
    assert "cdn.example/a.png" in joined
    assert "transfer-failed" in joined
