"""Rich document rendering for Reading mode: Markdown and BBCode -> safe HTML.

One authority, four separable stages (T-1484):

1. ``detect_syntax()``      -- decide which language the source is written in
2. ``parse_bbcode()``       -- structural BBCode parse into a node tree
3. ``sanitize()``           -- allowlist rewrite of generated HTML into a
                               trusted subset, collecting media references
4. ``render()``             -- the composed pipeline returning a
                               ``RenderedDocument`` (html + media + warnings)

Nothing here imports Qt: the parser and the renderer are testable on their own,
and the presentation surface (``fastprompter.ui.rich_preview_view``) only ever
sees the finished HTML plus the media list.

The renderer is strictly read-only with respect to the source: it never
normalises line endings, never rewrites the document and never touches the
clipboard or the editor's undo stack.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import markdown

# --------------------------------------------------------------------------
# public vocabulary
# --------------------------------------------------------------------------

SYNTAX_AUTO = "Auto"
SYNTAX_MARKDOWN = "Markdown"
SYNTAX_BBCODE = "BBCode"
SYNTAX_PLAIN = "Plain"

SYNTAXES = (SYNTAX_AUTO, SYNTAX_MARKDOWN, SYNTAX_BBCODE)

#: The marker the sanitizer emits for every image it accepted.  It is generated
#: by US for a real ``<img>`` tag, never copied from user markup: the sanitizer
#: rewrites every element from the token stream and drops unknown attributes,
#: so a document cannot forge one.
MEDIA_CLASS = "fp-media"


@dataclass(frozen=True)
class MediaRef:
    """One image the document asked for."""

    url: str
    alt: str = ""
    remote: bool = False
    animated_hint: bool = False


@dataclass
class RenderedDocument:
    """The finished presentation form of one source document."""

    html: str
    syntax: str
    media: tuple[MediaRef, ...] = ()
    warnings: tuple[str, ...] = ()
    source: str = ""
    #: Set by the view when it has to fall back to a flat HTML block.
    plain_body: str = ""
    blocks: list = field(default_factory=list, repr=False)

    def media_urls(self) -> tuple[str, ...]:
        return tuple(m.url for m in self.media)


# --------------------------------------------------------------------------
# theme tokens
# --------------------------------------------------------------------------

DEFAULT_TOKENS: dict[str, str] = {
    "text": "#c4ba9f",
    "bg": "#0f0f0f",
    "heading": "#f0cc6a",
    "subheading": "#e0b856",
    "link": "#61afef",
    "code_bg": "#1a1a1a",
    "code_text": "#e06c75",
    "border": "#5a4a2a",
    "quote": "#7f848e",
    "table_head_bg": "#1a1810",
    "accent": "#c9a84c",
}

_FONT_STACK = "Verdana,DejaVu Sans,sans-serif"


def _stylesheet(t: dict[str, str]) -> str:
    """Qt rich-text CSS.  Class selectors keep colours out of the HTML body."""
    return (
        f"body {{ color: {t['text']}; background: {t['bg']};"
        f" font-family: {_FONT_STACK}; font-size: 11px; }}"
        f" h1 {{ color: {t['heading']}; margin: 8px 0 4px 0; }}"
        f" h2 {{ color: {t['subheading']}; margin: 7px 0 4px 0; }}"
        f" h3 {{ color: {t['subheading']}; margin: 6px 0 3px 0; }}"
        f" h4 {{ color: {t['subheading']}; margin: 5px 0 3px 0; }}"
        f" h5, h6 {{ color: {t['subheading']}; margin: 4px 0 3px 0; }}"
        f" a {{ color: {t['link']}; text-decoration: underline; }}"
        f" pre {{ background: {t['code_bg']}; color: {t['code_text']};"
        f" padding: 5px; border: 1px solid {t['border']};"
        f" white-space: pre-wrap; }}"
        f" code {{ background: {t['code_bg']}; color: {t['code_text']}; }}"
        f" blockquote {{ color: {t['quote']}; border-left: 3px solid {t['border']};"
        f" margin: 4px 0; padding-left: 8px; }}"
        f" hr {{ border: 1px solid {t['border']}; }}"
        f" table {{ border-collapse: collapse; border: 1px solid {t['border']}; }}"
        f" .c {{ border: 1px solid {t['border']}; padding: 4px;"
        f" vertical-align: top; }}"
        f" .h {{ border: 1px solid {t['border']}; padding: 4px;"
        f" background: {t['table_head_bg']}; font-weight: bold;"
        f" vertical-align: top; }}"
        f" .q {{ color: {t['quote']}; }}"
        f" .plain {{ white-space: pre-wrap; }}"
    )


def _wrap(body: str, tokens: dict[str, str] | None = None) -> str:
    t = dict(DEFAULT_TOKENS)
    if tokens:
        for key, value in tokens.items():
            if isinstance(value, str) and value:
                t[key] = value
    bg = t["bg"].replace('"', "")
    return (
        "<html><head><style>"
        + _stylesheet(t)
        + "</style></head>"
        + f'<body style="background:{bg}; margin:0;">'
        + body
        + "</body></html>"
    )


# --------------------------------------------------------------------------
# 1. syntax detection
# --------------------------------------------------------------------------

#: Tags whose presence is evidence of real BBCode rather than bracketed prose.
_BBCODE_KNOWN = (
    "b", "i", "u", "s", "url", "img", "table", "tr", "td", "th", "list",
    "quote", "code", "color", "size", "center", "hr", "h1", "h2", "h3", "h4",
    "*",
)
_BBCODE_TAG_RE = re.compile(
    r"\[(/?)(?:" + "|".join(re.escape(t) for t in _BBCODE_KNOWN) + r")"
    r"(?:=[^\]\n]*)?\]",
    re.IGNORECASE,
)
_BBCODE_BLOCK_RE = re.compile(r"\[/?(?:table|list|quote|code|center|h[1-4])\b[^\]]*\]",
                              re.IGNORECASE)


def detect_syntax(text: str) -> str:
    """Return ``BBCode``, ``Markdown`` or ``Plain`` for a source document.

    A single pair of brackets is prose (``[1]``, ``[note]``); BBCode has to show
    structure.  Two recognised tags, or one recognised block tag, are enough.
    """
    if not text or not text.strip():
        return SYNTAX_PLAIN
    tags = _BBCODE_TAG_RE.findall(text)
    if len(tags) >= 2:
        return SYNTAX_BBCODE
    if tags and _BBCODE_BLOCK_RE.search(text):
        return SYNTAX_BBCODE
    return SYNTAX_MARKDOWN


# --------------------------------------------------------------------------
# 2. BBCode parse
# --------------------------------------------------------------------------


class _Node:
    """A parsed BBCode element (or a text run when ``tag`` is ``None``)."""

    __slots__ = ("tag", "attr", "children", "literal")

    def __init__(self, tag: str | None, attr: str = "", literal: bool = False):
        self.tag = tag
        self.attr = attr
        self.children: list = []
        self.literal = literal

    def text(self) -> str:
        if self.tag is None:
            return self.children[0] if self.children else ""
        return "".join(c.text() for c in self.children)


_TOKEN_RE = re.compile(r"\[(/?)([a-zA-Z*][a-zA-Z0-9]*)(?:=([^\]\n]*))?\]")

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "table", "tr", "td", "th", "list",
               "quote", "code", "center", "hr"}
_INLINE_TAGS = {"b", "i", "u", "s", "url", "img", "color", "size"}


def parse_bbcode(source: str) -> _Node:
    """Structural BBCode parse.

    Unknown and unbalanced tags are preserved as literal text, never deleted,
    and nesting is tracked with a real stack so overlapping markup degrades to
    readable text instead of scrambled output.
    """
    root = _Node("root")
    stack: list[_Node] = [root]
    pos = 0
    for match in _TOKEN_RE.finditer(source):
        if match.start() < pos:
            continue          # already consumed as part of a [code] block
        if match.start() > pos:
            text_node = _Node(None)
            text_node.children.append(source[pos:match.start()])
            stack[-1].children.append(text_node)
        pos = match.end()
        closing, name, attr = match.group(1), match.group(2).lower(), match.group(3) or ""
        if name == "*":
            # List item boundary.  A new [*] closes the item above it, so the
            # list's children stay flat items instead of nesting into each
            # other.
            while len(stack) > 1 and stack[-1].tag == "*":
                node = stack.pop()
                stack[-1].children.append(node)
            if stack[-1].tag == "list":
                stack.append(_Node("*"))
            else:
                _append_text(stack[-1], match.group(0))
            continue
        known = name in _BLOCK_TAGS or name in _INLINE_TAGS
        if closing:
            # an open [*] item ends where its list ends
            while (len(stack) > 1 and stack[-1].tag == "*"
                   and stack[-1].tag != name):
                node = stack.pop()
                stack[-1].children.append(node)
            if len(stack) > 1 and stack[-1].tag == name and not stack[-1].literal:
                node = stack.pop()
                stack[-1].children.append(node)
            else:
                _append_text(stack[-1], match.group(0))
            continue
        if not known:
            # literal bracket text survives verbatim
            _append_text(stack[-1], match.group(0))
            continue
        if name == "code":
            # [code] content is literal until the matching [/code]
            end = source.lower().find("[/code]", pos)
            if end < 0:
                _append_text(stack[-1], source[match.start():])
                pos = len(source)
                break
            node = _Node("code")
            raw = _Node(None)
            raw.children.append(source[pos:end])
            node.children.append(raw)
            stack[-1].children.append(node)
            pos = end + len("[/code]")
            continue
        stack.append(_Node(name, attr))
    if pos < len(source):
        _append_text(stack[-1], source[pos:])
    while len(stack) > 1:                      # unbalanced opens stay visible
        node = stack.pop()
        stack[-1].children.append(node)
    return root


def _append_text(parent: _Node, text: str) -> None:
    node = _Node(None)
    node.children.append(text)
    parent.children.append(node)


# --- inline markdown inside BBCode text (mixed documents) -------------------

_RE_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_RE_MD_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_RE_MD_CODE = re.compile(r"`([^`\n]+)`")
_RE_AUTOLINK = re.compile(r"(?<![\w(\"'=>])(https?://[^\s<>\"]+[^\s<>\".,;:!?)\]}])")


def _escape_and_linkify(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _RE_AUTOLINK.sub(
        lambda m: f'<a href="{html.escape(m.group(1), quote=True)}">{m.group(1)}</a>',
        out,
    )
    return out


def _inline_markdown(text: str) -> str:
    """Light Markdown pass over a BBCode text run.

    Only inline emphasis and code spans: block Markdown inside a BBCode document
    would fight the BBCode block structure, and a fenced block is already
    ``[code]``.  The pass runs on ESCAPED text, so it can only ever emit the
    four inline tags it knows.
    """
    escaped = _escape_and_linkify(text)
    escaped = _RE_MD_CODE.sub(
        lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = _RE_MD_BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _RE_MD_STRIKE.sub(r"<s>\1</s>", escaped)
    escaped = _RE_MD_ITALIC.sub(r"<i>\1</i>", escaped)
    # an autolink produced above must not be re-emphasised
    return escaped


_SAFE_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$")


def _bbcode_url(attr: str, body: str) -> str:
    target = attr.strip() or body.strip()
    if not target:
        return _inline_markdown(body)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        # an explicit scheme is left EXACTLY as written: it is the sanitizer's
        # job to refuse javascript:/data:/vbscript:, not this prefixer's
        pass
    elif target.startswith("//"):
        target = "https:" + target
    else:
        target = "https://" + target
    href = html.escape(target, quote=True)
    return f'<a href="{href}">{_inline_markdown(body)}</a>'


def _emit_children(node: _Node) -> str:
    return "".join(_emit(c) for c in node.children)


def _emit(node: _Node) -> str:
    tag = node.tag
    if tag is None:
        return _inline_markdown(node.text())
    if tag == "root":
        return _blocks(node)
    if tag in ("b", "i", "u", "s"):
        return f"<{tag}>{_emit_children(node)}</{tag}>"
    if tag == "url":
        return _bbcode_url(node.attr, node.text())
    if tag == "img":
        url = (node.attr or node.text()).strip()
        return _img_marker(url, "")
    if tag == "color":
        color = node.attr.strip()
        if _SAFE_COLOR.match(color):
            return f'<span style="color:{color}">{_emit_children(node)}</span>'
        return _emit_children(node)
    if tag == "size":
        try:
            px = max(8, min(48, int(float(node.attr.strip() or "11"))))
        except (TypeError, ValueError):
            px = 11
        return f'<span style="font-size:{px}px">{_emit_children(node)}</span>'
    if tag == "code":
        raw = html.escape(node.text(), quote=False)
        return f"<pre><code>{raw}</code></pre>"
    if tag == "quote":
        return f"<blockquote>{_emit_children(node)}</blockquote>"
    if tag == "center":
        return f'<div align="center">{_emit_children(node)}</div>'
    if tag == "hr":
        return "<hr/>"
    if tag in ("h1", "h2", "h3", "h4"):
        return f"<{tag}>{_emit_children(node)}</{tag}>"
    if tag == "table":
        return "<table>" + _emit_children(node) + "</table>"
    if tag == "tr":
        return "<tr>" + _emit_children(node) + "</tr>"
    if tag == "td":
        return f'<td class="c">{_emit_children(node)}</td>'
    if tag == "th":
        return f'<th class="h">{_emit_children(node)}</th>'
    if tag == "list":
        ordered = node.attr.strip().lower() in ("1", "a", "i")
        kind = "ol" if ordered else "ul"
        items = [c for c in node.children if c.tag == "*"]
        if not items:
            return f"<{kind}><li>{_emit_children(node)}</li></{kind}>"
        return f"<{kind}>" + "".join(f"<li>{_emit_children(c)}</li>" for c in items) + f"</{kind}>"
    if tag == "*":
        return f"<li>{_emit_children(node)}</li>"
    return _emit_children(node)


def _blocks(root: _Node) -> str:
    """Top level: contiguous inline runs become paragraphs, blocks stand alone."""
    out: list[str] = []
    run: list[str] = []

    def flush():
        if run:
            text = "".join(run)
            if text.strip():
                out.append(f"<p>{text}</p>")
            run.clear()

    for child in root.children:
        if child.tag is None:
            run.append(_inline_markdown(child.text()))
            continue
        if child.tag in _BLOCK_TAGS or child.tag == "*" or child.tag == "img":
            flush()
            out.append(_emit(child))
            continue
        run.append(_emit(child))
    flush()
    return "\n".join(out)


def _img_marker(url: str, alt: str) -> str:
    safe_url = html.escape(url.strip(), quote=True)
    safe_alt = html.escape(alt.strip(), quote=True)
    return (f'<img class="{MEDIA_CLASS}" src="{safe_url}" alt="{safe_alt}"/>')


# --------------------------------------------------------------------------
# 3. markdown
# --------------------------------------------------------------------------


def _markdown_html(source: str) -> str:
    return markdown.markdown(
        source,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )


def _plain_html(source: str) -> str:
    return '<pre class="plain">' + html.escape(source, quote=False) + "</pre>"


# --------------------------------------------------------------------------
# 4. sanitizer
# --------------------------------------------------------------------------

_ALLOWED_TAGS = {
    "p", "br", "hr", "b", "strong", "i", "em", "u", "s", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "a", "span", "div", "h1", "h2", "h3", "h4", "h5", "h6", "small", "big",
    "sub", "sup",
}
_VOID_TAGS = {"br", "hr"}
# One output vocabulary for both languages: python-markdown emits strong/em,
# BBCode emits b/i, and the preview should not care which produced the run.
_TAG_ALIASES = {"strong": "b", "em": "i", "del": "s", "ins": "u",
                "thead": "thead", "tbody": "tbody"}
_SAFE_SCHEMES = ("http", "https", "mailto", "file")

_STYLE_PROP_RE = re.compile(
    r"^(color|font-size|text-align|font-weight|font-style|text-decoration|"
    r"background-color)\s*:\s*([#\w(),.%\s-]+)$",
    re.IGNORECASE,
)
_LOCAL_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_REMOTE_RE = re.compile(r"^https?://", re.IGNORECASE)


def _safe_href(raw: str) -> str | None:
    value = html.unescape((raw or "").strip())
    if not value:
        return None
    lowered = value.lower()
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", lowered)
    if match:
        scheme = match.group(1)
        if scheme not in _SAFE_SCHEMES:
            return None
        if scheme == "file":
            path = value.split(":", 1)[1]
            if not (_LOCAL_PATH_RE.match(path) or path.startswith("/")):
                return None
            return "file:" + path
        return value
    if lowered.startswith("//"):
        return "https:" + value
    return None           # relative targets have nothing to resolve against


def _safe_style(raw: str) -> str:
    kept = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if _STYLE_PROP_RE.match(part):
            kept.append(part)
    return ";".join(kept)


class _Sanitizer:
    """Allowlist rewriter built on the stdlib tokenizer.

    It emits only the tags/attributes in the allowlist, linkifies bare URLs in
    TEXT nodes (so a URL inside ``<code>``/``<pre>``/``<a>`` is never touched),
    rewrites every image into a ``MEDIA_CLASS`` marker and records it, and
    escapes every text node exactly once (``convert_charrefs`` decodes input,
    ``html.escape`` re-encodes — so entities are never double-escaped).
    """

    def __init__(self, allow_remote: bool = False):
        self.allow_remote = allow_remote
        self.media: list[MediaRef] = []
        self.warnings: list[str] = []
        self.out: list[str] = []
        self._open: list[str] = []
        self._walk = None

    # -- text ------------------------------------------------------------
    def handle_data(self, data: str) -> None:
        if not data:
            return
        if "code" in self._open or "pre" in self._open or "a" in self._open:
            self.out.append(html.escape(data, quote=False))
            return
        self.out.append(_escape_and_linkify(data))

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&#{name};"))

    # -- tags ------------------------------------------------------------
    def _emit(self, text: str) -> None:
        self.out.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = _TAG_ALIASES.get(tag.lower(), tag.lower())
        if tag == "img":
            self._emit_image(attrs)
            return
        if tag not in _ALLOWED_TAGS:
            # Not in the allowlist: show the markup as the text it is.  That
            # keeps script/style/iframe inert AND keeps what the author wrote
            # visible, instead of silently dropping a run of the document.
            self._emit(html.escape(self._tag_text(tag), quote=False))
            return
        if tag == "a" and not any(
                (n or "").lower() == "href" and _safe_href(v or "")
                for n, v in attrs):
            # nothing safe to open: keep the words, drop the anchor entirely
            return
        pieces = [f"<{tag}"]
        if tag == "td":
            pieces.append(' class="c"')
        elif tag == "th":
            pieces.append(' class="h"')
        for name, value in attrs:
            name = (name or "").lower()
            if tag == "a" and name == "href":
                href = _safe_href(value or "")
                if href:
                    pieces.append(f' href="{html.escape(href, quote=True)}"')
            elif tag in ("td", "th") and name in ("colspan", "rowspan"):
                if value and value.strip().isdigit():
                    pieces.append(f' {name}="{int(value.strip())}"')
            elif tag == "td" and name == "align":
                if (value or "").lower() in ("left", "center", "right"):
                    pieces.append(f' align="{(value or "").lower()}"')
            elif name == "style":
                safe = _safe_style(value or "")
                if safe:
                    pieces.append(f' style="{html.escape(safe, quote=True)}"')
        pieces.append("/>" if tag in _VOID_TAGS else ">")
        self._emit("".join(pieces))
        if tag not in _VOID_TAGS:
            self._open.append(tag)

    def _tag_text(self, tag: str) -> str:
        """The start tag exactly as the document wrote it, or a rebuild of it."""
        try:
            raw = self._walk.get_starttag_text() if self._walk else None
        except Exception:
            raw = None
        if raw:
            return raw
        return f"<{tag}>"

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = _TAG_ALIASES.get(tag.lower(), tag.lower())
        if tag not in _ALLOWED_TAGS:
            self._emit(html.escape(f"</{tag}>", quote=False))
            return
        if tag in _VOID_TAGS:
            return
        if tag not in self._open:
            # a stray close tag carries no content and is dropped
            return
        if self._open[-1] != tag:
            self.warnings.append(f"unbalanced </{tag}>")
            # close the tags opened above it, innermost first, so the fragment
            # stays well formed instead of nesting across the mismatch
            while self._open and self._open[-1] != tag:
                self._emit(f"</{self._open.pop()}>")
        self._open.pop()
        self._emit(f"</{tag}>")

    def _emit_image(self, attrs) -> None:
        raw_src = ""
        alt = ""
        for name, value in attrs:
            name = (name or "").lower()
            if name == "src":
                raw_src = value or ""
            elif name == "alt":
                alt = value or ""
        src = html.unescape(raw_src.strip())
        if src.startswith("//"):
            src = "https:" + src
        if not src:
            return
        remote = bool(_REMOTE_RE.match(src))
        animated = src.lower().split("?")[0].endswith(".gif")
        if remote:
            if not src.lower().startswith("https://"):
                self.warnings.append("insecure image url dropped")
                return
            if not self.allow_remote:
                self.media.append(MediaRef(url=src, alt=alt, remote=True,
                                           animated_hint=animated))
                reopened = False
                if self._open and self._open[-1] == "p":
                    self._emit("</p>")
                    reopened = True
                self._emit(
                    f'<div class="{MEDIA_CLASS}" data-src="{html.escape(src, quote=True)}"'
                    f' data-remote="1" data-blocked="1"{self._alt_attr(alt)}/>'
                )
                if reopened:
                    self._emit("<p>")
                return
        elif not (src.lower().startswith("file:") or _LOCAL_PATH_RE.match(src)
                  or src.startswith("/")):
            self.warnings.append("unsupported image src dropped")
            return
        self.media.append(MediaRef(url=src, alt=alt, remote=remote,
                                   animated_hint=animated))
        reopened = False
        if self._open and self._open[-1] == "p":
            self._emit("</p>")
            reopened = True
        self._emit(
            f'<div class="{MEDIA_CLASS}" data-src="{html.escape(src, quote=True)}"'
            f' data-remote="{1 if remote else 0}"{self._alt_attr(alt)}/>'
        )
        if reopened:
            self._emit("<p>")

    @staticmethod
    def _alt_attr(alt: str) -> str:
        return f' data-alt="{html.escape(alt, quote=True)}"' if alt else ""


def sanitize(raw_html: str, allow_remote: bool = False) -> tuple[str, list[MediaRef],
                                                                list[str]]:
    """Rewrite ``raw_html`` into the trusted preview subset."""
    from html.parser import HTMLParser

    class _Walker(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.s = _Sanitizer(allow_remote=allow_remote)
            self.s._walk = self

        def handle_starttag(self, tag, attrs):
            self.s.handle_starttag(tag, attrs)

        def handle_startendtag(self, tag, attrs):
            self.s.handle_startendtag(tag, attrs)

        def handle_endtag(self, tag):
            self.s.handle_endtag(tag)

        def handle_data(self, data):
            self.s.handle_data(data)

    walker = _Walker()
    walker.feed(raw_html or "")
    walker.close()
    # close anything still open so the fragment is well formed
    while walker.s._open:
        walker.s.out.append(f"</{walker.s._open.pop()}>")
    return "".join(walker.s.out), walker.s.media, walker.s.warnings


# --------------------------------------------------------------------------
# 5. the pipeline
# --------------------------------------------------------------------------


def render(source: str, syntax: str = SYNTAX_AUTO, allow_remote: bool = False,
           tokens: dict[str, str] | None = None) -> RenderedDocument:
    """Render ``source`` into a ``RenderedDocument``.

    ``syntax`` is one of ``SYNTAXES``; anything else falls back to Auto.  The
    source is never modified.
    """
    text = source or ""
    requested = syntax if syntax in SYNTAXES else SYNTAX_AUTO
    resolved = detect_syntax(text) if requested == SYNTAX_AUTO else requested
    if resolved == SYNTAX_BBCODE:
        raw = _blocks(parse_bbcode(text))
    elif resolved == SYNTAX_MARKDOWN:
        try:
            raw = _markdown_html(text)
        except Exception:                          # never break the preview
            raw = _plain_html(text)
            resolved = SYNTAX_MARKDOWN
    else:
        raw = _plain_html(text)

    body, media, warnings = sanitize(raw, allow_remote=allow_remote)
    doc = RenderedDocument(
        html=_wrap(body, tokens),
        syntax=resolved,
        media=tuple(media),
        warnings=tuple(warnings),
        source=text,
        plain_body=body,
    )
    return doc


MEDIA_MARKER_PREFIX = f'<div class="{MEDIA_CLASS}" data-src="'


def split_blocks(body: str) -> list[tuple[str, str]]:
    """Split sanitized body HTML into ``("html"|"media", payload)`` blocks.

    The media marker carries two values that the old single regex could not
    survive: the alt text (``alt="A/B"`` contains a slash) and the URL, which
    the sanitizer stores HTML-escaped (``?x=1&amp;y=2``). A character class
    built to stop at ``/`` therefore dropped the whole marker into an html
    block, and even a matching marker handed back a payload that never equalled
    ``MediaRef.url``.

    This scan walks the tag by QUOTE state instead: ``html.escape(...,
    quote=True)`` guarantees no raw ``"`` inside the value, so the first ``"``
    after the prefix really is the terminator, whatever the alt contains. The
    value is then unescaped with the inverse codec, so the block payload is
    byte-equal to the MediaRef the document already carries.
    """
    prefix = MEDIA_MARKER_PREFIX
    blocks: list[tuple[str, str]] = []
    pos = 0
    while True:
        start = body.find(prefix, pos)
        if start < 0:
            break
        value_start = start + len(prefix)
        value_end = body.find('"', value_start)
        if value_end < 0:
            break
        close = body.find("/>", value_end)
        next_tag = body.find("<", value_end)
        if close < 0 or (0 <= next_tag < close):
            # not a self-closed media marker: leave it as html and move on
            if start > pos:
                blocks.append(("html", body[pos:start]))
            pos = start + len(prefix)
            continue
        if start > pos:
            blocks.append(("html", body[pos:start]))
        blocks.append(("media", html.unescape(body[value_start:value_end])))
        pos = close + 2
    if pos < len(body):
        blocks.append(("html", body[pos:]))
    return blocks
