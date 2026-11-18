"""T-1494 — the ONE shared, Qt-independent link tokenization authority.

Zero Qt. Every surface that has to recognise a link (Source editor, Live
Preview, Reading mode, the context menu, the hover Copy control) asks this
module, so the same text always yields the same tokens.

Two rules shape everything here:

* A destination is kept **verbatim**.  The Markdown archive codec
  (:func:`fastprompter.core.markdown_refs.decode_destination`) deliberately
  strips query strings and fragments because it resolves archive MEMBERS;
  for a clickable web URL that would throw away exactly the data the user
  asked to keep.  This module therefore never decodes a destination at all:
  no percent-decoding (so nothing is ever decoded twice), no scheme
  rewriting of the stored text, no HTML escaping.
* A token is a fact about the SOURCE TEXT: exact character spans, the exact
  visible label, the exact destination, plus a normalised navigation target
  and a safe-action classification.

Recognised forms: bare ``http``/``https``/``ftp`` URLs, ``www.`` hosts,
``mailto:`` addresses, ``file:`` URLs, Markdown links and images, and the
existing BBCode ``[url]`` syntax.  Code fences and inline code are never
linkified.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass

from fastprompter.core.markdown_refs import find_markdown_refs

#: Sort sentinels for the interval query below (outside any real offset).
_NEG = float("-inf")

__all__ = [
    "LinkToken",
    "SAFE_SCHEMES",
    "classify_destination",
    "tokenize_block",
    "is_fence_line",
    "is_fence_closer",
]

#: Schemes the application is willing to hand to the operating system.
#: Mirrors ``VaultTextEdit._SAFE_LINK_SCHEMES``; kept here so the pure
#: tokenizer can classify a destination without importing any UI module.
SAFE_SCHEMES = ("http", "https", "ftp", "mailto", "file")

#: Action classes a destination can be sorted into.
ACTIONS = ("web", "email", "local_file", "unsupported")

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")

# A bare URL candidate.  The scheme alternatives come first so that
# "http://www.example.com" is ONE token, not a URL plus a "www." fragment.
_BARE_URL_RE = re.compile(
    r"(?:(?:https?|ftp)://|file://|mailto:|www\.)[^\s<>\"'`]+",
    re.IGNORECASE,
)

# Inline code spans: a backtick run, its content, the same run again.
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")

# BBCode URL syntax (the form the BBCode renderer already supports).
_BBCODE_URL_RE = re.compile(
    r"\[url=([^\]\n]+)\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_BBCODE_URL_BARE_RE = re.compile(
    r"\[url\]([^\[\n]+)\[/url\]", re.IGNORECASE)

# Characters that end a sentence rather than a URL.
_TRAILING_PUNCT = ".,;:!?'\""


@dataclass(frozen=True)
class LinkToken:
    """One recognised link in a block of source text.

    ``span`` covers the whole token as written (for a Markdown link that is
    the complete ``[label](destination)`` markup); ``target_span`` covers the
    destination characters alone.  Both are offsets into the text that was
    tokenized, so a caller can map a token straight onto a document.
    """

    kind: str                 # "markdown" | "autolink" | "bbcode" | "image"
    label: str                # visible text of the link
    destination: str          # exact destination, verbatim
    span: tuple[int, int]     # (start, end) of the whole token
    target_span: tuple[int, int]   # (start, end) of the destination text
    action: str               # "web" | "email" | "local_file" | "unsupported"
    normalized: str           # navigation target (may add a scheme)

    @property
    def is_supported(self) -> bool:
        """True when the destination may be handed to the OS router."""
        return self.action != "unsupported"

    @property
    def is_image(self) -> bool:
        return self.kind == "image"


def classify_destination(destination: str) -> tuple[str, str]:
    """``(action, normalized_target)`` for one destination string.

    The classification never opens, resolves or fetches anything: it only
    decides what KIND of thing the destination is.  Unsupported schemes
    (``javascript:``, ``data:``, ``vbscript:``, anything unknown) are
    reported as ``"unsupported"`` so the caller can refuse them.
    """
    dest = (destination or "").strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1].strip()
    if not dest:
        return ("unsupported", "")
    match = _SCHEME_RE.match(dest)
    if match:
        scheme = match.group(1).lower()
        if scheme in ("http", "https", "ftp"):
            return ("web", dest)
        if scheme == "mailto":
            return ("email", dest)
        if scheme == "file":
            return ("local_file", dest)
        return ("unsupported", dest)
    lowered = dest.lower()
    if lowered.startswith("www."):
        return ("web", "https://" + dest)
    if dest.startswith("//"):
        return ("web", "https:" + dest)
    # Arbitrary prose is NOT a local filesystem link.
    return ("unsupported", dest)


def is_fence_line(text: str) -> bool:
    """True when the line opens or closes a fenced code block."""
    return text.strip().startswith("```")


def is_fence_closer(text: str) -> bool:
    """True when the line is a bare closing fence (``` and nothing else)."""
    stripped = text.strip()
    return stripped.startswith("```") and stripped.rstrip("`") == ""


def _inline_code_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _INLINE_CODE_RE.finditer(text)]


def _overlaps(spans, start: int, end: int) -> bool:
    """True when ``[start, end)`` intersects any span in ``spans``.

    PERF-004: the caller keeps each collection sorted AND disjoint, so its
    starts and ends both increase. A span ``(a, b)`` overlaps ``[start, end)``
    exactly when ``a < end and start < b``, so only spans beginning before
    ``end`` can qualify, and among them the one with the largest end is the
    last such span. One ``bisect_left`` locates it, replacing a scan of every
    preceding span for every candidate.
    """
    index = bisect_left(spans, (end, _NEG))
    return index > 0 and spans[index - 1][1] > start


def _claim(spans: list[tuple[int, int]], start: int, end: int) -> None:
    """Record a claimed span, keeping ``spans`` sorted, disjoint and merged."""
    index = bisect_left(spans, (start, start))
    if index > 0 and spans[index - 1][1] >= start:
        prev_start, prev_end = spans[index - 1]
        start = min(start, prev_start)
        end = max(end, prev_end)
        index -= 1
        del spans[index]
    while index < len(spans) and spans[index][0] <= end:
        end = max(end, spans[index][1])
        del spans[index]
    spans.insert(index, (start, end))


def _trim_url(raw: str) -> str:
    """Drop the punctuation that ends a sentence instead of the URL.

    Balanced parentheses stay (Wikipedia style titles need them); an
    unbalanced trailing ``)`` is prose.
    """
    value = raw
    while value and value[-1] in _TRAILING_PUNCT:
        value = value[:-1]
    while value.endswith(")") and value.count(")") > value.count("("):
        value = value[:-1]
    while value.endswith("]") and value.count("]") > value.count("["):
        value = value[:-1]
    return value


def _markdown_label(text: str, start: int, end: int) -> str:
    """Visible label of a ``[label](...)`` token."""
    close = text.find("]", start)
    if close == -1 or close > end:
        return ""
    return text[start + 1:close]


def tokenize_block(text: str, *, in_code: bool = False) -> list[LinkToken]:
    """Every link token in one block of source text.

    ``in_code`` says the block sits inside a fenced code region; such a
    block yields nothing at all.  Tokens never overlap: a destination that
    belongs to a Markdown link is never also reported as a bare URL.
    """
    if in_code or not text:
        return []

    tokens: list[LinkToken] = []
    claimed: list[tuple[int, int]] = []
    code_spans = _inline_code_spans(text)

    # 1. Markdown links and images.
    for ref in find_markdown_refs(text):
        start, end = ref.link_span
        if _overlaps(code_spans, start, end):
            continue
        destination = ref.raw_target.strip()
        if destination.startswith("<") and destination.endswith(">"):
            destination = destination[1:-1].strip()
        action, normalized = classify_destination(destination)
        label = _markdown_label(text, start, end)
        tokens.append(LinkToken(
            kind="image" if ref.is_image else "markdown",
            label=label,
            destination=destination,
            span=(start, end),
            target_span=ref.target_span,
            action=action,
            normalized=normalized,
        ))
        _claim(claimed, start, end)

    # 2. BBCode [url=...]label[/url] and [url]destination[/url].
    for match in _BBCODE_URL_RE.finditer(text):
        start, end = match.span()
        if _overlaps(code_spans, start, end):
            continue
        destination = match.group(1).strip()
        action, normalized = classify_destination(destination)
        tokens.append(LinkToken(
            kind="bbcode",
            label=match.group(2),
            destination=destination,
            span=(start, end),
            target_span=(start + 5, start + 5 + len(match.group(1))),
            action=action,
            normalized=normalized,
        ))
        _claim(claimed, start, end)
    for match in _BBCODE_URL_BARE_RE.finditer(text):
        start, end = match.span()
        if _overlaps(code_spans, start, end):
            continue
        destination = match.group(1).strip()
        action, normalized = classify_destination(destination)
        tokens.append(LinkToken(
            kind="bbcode",
            label=destination,
            destination=destination,
            span=(start, end),
            target_span=(start + 5, start + 5 + len(match.group(1))),
            action=action,
            normalized=normalized,
        ))
        _claim(claimed, start, end)

    # 3. Bare URLs anywhere else in the block.
    for match in _BARE_URL_RE.finditer(text):
        start = match.start()
        raw = _trim_url(match.group(0))
        if not raw:
            continue
        end = start + len(raw)
        if _overlaps(code_spans, start, end):
            continue
        if _overlaps(claimed, start, end):
            continue
        action, normalized = classify_destination(raw)
        tokens.append(LinkToken(
            kind="autolink",
            label=raw,
            destination=raw,
            span=(start, end),
            target_span=(start, end),
            action=action,
            normalized=normalized,
        ))

    tokens.sort(key=lambda token: token.span[0])
    return tokens
