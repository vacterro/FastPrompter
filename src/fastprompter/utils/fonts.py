"""One place for the no-antialiasing rule.

The Win95 look (UI.md) wants crisp, software-rendered, non-antialiased text
everywhere. A QFont built fresh from a family name — `QFont("Verdana")` —
does NOT inherit the application font's style strategy, so it renders with
the platform default, which on Windows means antialiased. Copying a widget's
existing font keeps the strategy; building a new one loses it.

Measured: with this strategy a glyph is exactly two colours (fg/bg), 0 edge
pixels; without it, ~195 grey edge pixels per line. So any QFont(family)
that skips this is a visible AA leak.
"""

from __future__ import annotations

from PyQt6.QtGui import QFont, QFontDatabase

_NO_AA = QFont.StyleStrategy.NoAntialias | QFont.StyleStrategy.NoSubpixelAntialias


def no_aa(font: QFont) -> QFont:
    """Stamp the non-antialiased strategy onto `font`, in place, and return it."""
    font.setStyleStrategy(_NO_AA)
    return font


def resolve_family(name: str, families=None) -> str:
    """Prefer a user's "<name>_m1" build when one is installed.

    The _m1 fonts are hand-made bitmap/unhinted builds that render genuinely
    crisp with no antialiasing. The user wants to pick plain "Verdana" and
    get their "Verdana_m1" — so the name shown in the UI stays "Verdana"
    while the family actually rendered is the m1 one when it exists. Any
    family gets the same treatment (Ubuntu -> Ubuntu_m1, ...), so it is one
    rule, not a per-font list.

    Already asking for the _m1 family, or one that is not installed, is
    returned unchanged.
    """
    if not name or name.endswith("_m1"):
        return name
    fams = families if families is not None else set(QFontDatabase.families())
    m1 = f"{name}_m1"
    return m1 if m1 in fams else name


def display_family(name: str) -> str:
    """The other direction, for the UI: show "Verdana", not "Verdana_m1"."""
    if name and name.endswith("_m1"):
        return name[:-3]
    return name
