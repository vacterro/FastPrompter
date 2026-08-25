"""Hashtags — tags that live inside the text, not beside it.

Deliberately small. There is no tag store, no rename, no tag manager: a tag
exists exactly because it is written somewhere, so nothing can fall out of
sync and nothing has to be cleaned up. Silos already give hierarchy; this
covers the other axis — marking a line and finding it again across silos.

Qt-free so the matching rules can be tested directly.
"""

from __future__ import annotations

import re

# `#` followed immediately by a letter or digit. The space is what keeps
# this off markdown headers: "# Title" is a header, "#title" is a tag.
# Unicode letters are in, so Russian tags work; `-` and `_` may appear
# inside a tag but never start or end it.
TAG_RE = re.compile(r"(?<![\w#])#(\w[\w-]*)", re.UNICODE)

# A run of hashes IS a header (or a "###" divider), never a tag.
_HEADER_RE = re.compile(r"^\s*#{1,6}\s")


def _is_header(line):
    return bool(_HEADER_RE.match(line))


def extract_tags(text):
    """Every distinct tag in `text`, lowercased, in first-seen order.

    Case-insensitive because #Todo and #todo are obviously the same thing to
    the person typing them, and being strict here would just create
    duplicates nobody asked for.
    """
    seen = {}
    for line in (text or "").splitlines():
        if _is_header(line):
            continue
        for match in TAG_RE.finditer(line):
            tag = match.group(1).lower()
            seen.setdefault(tag, True)
    return list(seen)


def tags_in_line(line):
    """The tags on one line, with their positions: [(tag, start, end)]."""
    if _is_header(line or ""):
        return []
    return [(m.group(1).lower(), m.start(), m.end())
            for m in TAG_RE.finditer(line or "")]


def tag_at(line, column):
    """The tag under a cursor column, or None.

    Used for Ctrl+click, so it must accept a click anywhere on the tag
    including on the leading '#'.
    """
    for tag, start, end in tags_in_line(line):
        if start <= column <= end:
            return tag
    return None


def find_occurrences(tag, silos, names=None):
    """Every line carrying `tag`, as dicts across all silos.

    `silos` is the list of silo texts; `names` an optional matching list of
    labels. Returns [{silo, name, line, text}], line numbers 1-based so they
    match what the gutter shows.
    """
    tag = (tag or "").lstrip("#").lower()
    if not tag:
        return []
    hits = []
    for idx, body in enumerate(silos or []):
        if not isinstance(body, str) or not body:
            continue
        name = ""
        if names and idx < len(names):
            name = (names[idx] or "").strip()
        for n, line in enumerate(body.splitlines(), start=1):
            if tag in (t for t, _s, _e in tags_in_line(line)):
                hits.append({
                    "silo": idx,
                    "name": name or f"Silo {idx + 1}",
                    "line": n,
                    "text": line.strip(),
                })
    return hits


def collect_all(silos):
    """{tag: number of lines carrying it} across every silo."""
    counts = {}
    for body in silos or []:
        if not isinstance(body, str):
            continue
        for line in body.splitlines():
            for tag in {t for t, _s, _e in tags_in_line(line)}:
                counts[tag] = counts.get(tag, 0) + 1
    return counts
