"""Ready-made silo templates, loaded from `.md` files rather than code.

The shipped set lives in `src/fastprompter/presets/` and is included in the
packaged build the same way `sound/` is. Files, not a Python list, so a user
can drop their own `.md` in beside them and it appears in the menu without a
code change — which is the whole point of the feature.

A file name orders and names the entry: a leading `NN_` sorts it and is
stripped from the label, and underscores read as spaces. `10_Table.md`
therefore shows as "Table" and sits after "Kanban".
"""

from __future__ import annotations

import os
import re

from fastprompter.utils.paths import get_resource_path

_ORDER_PREFIX = re.compile(r"^\d+[_\-. ]+")

# Read once per process: this is a handful of small files behind a menu that
# opens on a right-click, and re-reading the directory on every paint of the
# context menu is a filesystem hit the GUI thread does not need.
_CACHE: list[tuple[str, str]] | None = None


def presets_dir() -> str:
    """Where the templates live, in both the source and packaged layouts."""
    return get_resource_path("presets")


def label_for(filename: str) -> str:
    """`03_Bullet list.md` -> `Bullet list`."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = _ORDER_PREFIX.sub("", stem)
    return stem.replace("_", " ").strip() or os.path.basename(filename)


def load_presets(force: bool = False) -> list[tuple[str, str]]:
    """[(label, text)] for every `.md` in the presets directory, in order.

    A directory that is missing or unreadable yields an empty list rather
    than raising: a broken template folder must not take the context menu
    with it.
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    out: list[tuple[str, str]] = []
    folder = presets_dir()
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".md"))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        out.append((label_for(name), text))
    _CACHE = out
    return out
