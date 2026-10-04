"""T-1413 — Pure, stdlib-only Markdown reference and target codec authority.

Zero Qt dependencies.
Provides canonical destination parsing, URL-safe destination encoding,
decoding, and CommonMark reference discovery for silo bundles and indices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

# Characters preserved without encoding in archive member Markdown destinations:
# unreserved ASCII per RFC 3986 (ALPHA / DIGIT / "-" / "." / "_" / "~") plus "/"
_URL_SAFE = "/._-~"


def encode_destination(member: str) -> str:
    """Encode an archive member into a syntactically safe Markdown URL destination."""
    return quote(member, safe=_URL_SAFE)


def decode_destination(raw: str) -> str:
    """Decode a Markdown URL destination back to its archive member or target path."""
    s = raw.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    # Strip optional query strings or fragment identifiers if present in archive paths
    # Note: literal '#' or '?' encoded via %23 or %3F will not match literal '?' or '#'
    s = s.split("?")[0].split("#")[0].strip()
    return unquote(s)


@dataclass(frozen=True)
class MarkdownRef:
    """One discovered Markdown link or image reference with exact character spans."""

    raw_target: str          # verbatim target substring inside the parentheses
    clean_target: str        # unquoted, decoded target (no angle brackets, no %20)
    is_image: bool           # True for ![alt](target), False for [text](target)
    link_span: tuple[int, int]    # (start, end) of whole ![alt](target) or [text](target)
    target_span: tuple[int, int]  # (start, end) of raw_target in source text
    doc_index: int           # 0-based document occurrence index


_LINK_PREFIX_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(")


def find_markdown_refs(text: str) -> list[MarkdownRef]:
    """Find all Markdown image and link references in ``text``.

    Supports:
      - Plain destinations with or without percent-encoding
      - Angle-bracket destinations: ``<destination with spaces>``
      - Destinations with balanced parentheses
      - Optional trailing title: ``"title"``, ``'title'``, or ``(title)``
    """
    if not text:
        return []

    refs: list[MarkdownRef] = []
    doc_index = 0
    pos = 0
    text_len = len(text)

    while pos < text_len:
        m = _LINK_PREFIX_RE.search(text, pos)
        if not m:
            break

        is_image = (m.group(1) == "!")
        dest_start = m.end()

        # Parse destination inside parentheses starting at dest_start
        # Skip leading whitespace
        curr = dest_start
        while curr < text_len and text[curr] in " \t\r\n":
            curr += 1

        if curr >= text_len:
            pos = dest_start
            continue

        raw_target_start = curr
        raw_target_end = curr

        if text[curr] == "<":
            # Angle-bracket destination: scan until matching '>'
            curr += 1
            while curr < text_len and text[curr] != ">" and text[curr] != "\n":
                if text[curr] == "\\" and curr + 1 < text_len:
                    curr += 2
                else:
                    curr += 1
            if curr < text_len and text[curr] == ">":
                curr += 1
                raw_target_end = curr
            else:
                pos = dest_start
                continue
        else:
            # Standard destination: tolerate balanced parentheses
            # Destination ends at closing ')' or whitespace before an optional title
            paren_depth = 1
            in_quotes = None  # None, '"', "'"

            while curr < text_len:
                ch = text[curr]
                if ch == "\\":
                    curr += 2
                    continue
                if in_quotes:
                    if ch == in_quotes:
                        in_quotes = None
                    curr += 1
                    continue

                if ch in ('"', "'"):
                    # Started a title?
                    # Title must be preceded by whitespace
                    if curr > raw_target_start and text[curr - 1] in " \t":
                        raw_target_end = curr - 1
                        in_quotes = ch
                        curr += 1
                        continue

                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        if not raw_target_end or raw_target_end <= raw_target_start:
                            raw_target_end = curr
                        break

                curr += 1

            if paren_depth != 0:
                pos = dest_start
                continue

        # Skip any trailing title and whitespace up to closing ')'
        while curr < text_len and text[curr] != ")":
            curr += 1

        if curr >= text_len or text[curr] != ")":
            pos = dest_start
            continue

        link_end = curr + 1

        raw_target = text[raw_target_start:raw_target_end].strip()
        clean_target = decode_destination(raw_target)

        refs.append(MarkdownRef(
            raw_target=raw_target,
            clean_target=clean_target,
            is_image=is_image,
            link_span=(m.start(), link_end),
            target_span=(raw_target_start, raw_target_end),
            doc_index=doc_index,
        ))
        doc_index += 1
        pos = link_end

    return refs
