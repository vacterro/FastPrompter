"""Write a silo out as a real `.md` file, for dragging into a file manager.

A drag that leaves the app has to hand the receiver an actual file, so the
text is written to a scratch folder first and offered as `text/uri-list`
alongside the internal `silo:<idx>` text the app's own drop targets read.

The name comes from the content, because `silo_7.md` in a Downloads folder a
week later tells the user nothing: the silo's header if it has one, else its
first three words, always with a timestamp so two drags of the same silo do
not collide.
"""

from __future__ import annotations

import datetime
import os
import re
import tempfile

# Windows forbids these outright; the rest of the world merely regrets them.
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# One repeated group, not an alternation: `- [ ] buy milk` needs BOTH
# strips, and two `^`-anchored alternatives only ever fire once each at
# position 0 — the checkbox survived the bullet.
_MARKERS = re.compile(r"^(?:[\s>#*\-•]+|\[[ xX]\]\s*)+")
_MAX_STEM = 60
_SCRATCH = "fastprompter_drag"
_KEEP_SECONDS = 24 * 3600


def _title_from(text: str) -> str:
    """The silo's header, or its first three words."""
    for line in (text or "").splitlines():
        stripped = _MARKERS.sub("", line).strip()
        if stripped:
            # A header line is the whole title; a prose line gives three words.
            if line.lstrip().startswith("#"):
                return stripped
            return " ".join(stripped.split()[:3])
    return ""


def drag_filename(text: str, when: datetime.datetime | None = None) -> str:
    """`# Fix the parser` -> `Fix the parser_20260805_1730.md`."""
    when = when or datetime.datetime.now()
    stem = _ILLEGAL.sub("_", _title_from(text))
    stem = " ".join(stem.split()).strip(" ._")[:_MAX_STEM]
    if not stem:
        stem = "silo"
    return f"{stem}_{when:%Y%m%d_%H%M}.md"


def scratch_dir() -> str:
    return os.path.join(tempfile.gettempdir(), _SCRATCH)


def _prune(folder: str) -> None:
    """Drop yesterday's drags. A cancelled drag leaves its file behind — the
    receiving app is the only one who knows whether it was taken, and it does
    not tell us — so the scratch folder is swept instead of tracked."""
    cutoff = datetime.datetime.now().timestamp() - _KEEP_SECONDS
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def write_drag_file(text: str, when: datetime.datetime | None = None) -> str | None:
    """Write `text` to the scratch folder; return the path, or None."""
    folder = scratch_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return None
    _prune(folder)
    path = os.path.join(folder, drag_filename(text, when))
    # Two drags inside the same minute would otherwise overwrite each other,
    # and the second drop would carry the first one's text.
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = f"{base}_{n}{ext}"
        n += 1
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text or "")
    except OSError:
        return None
    return path
