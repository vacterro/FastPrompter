"""One user-settable palette for every AI-limit surface.

The gauge, the overview bars, the reset countdown and the settings captions all
used to hardcode their own hex values in three different files, so "make the
warning colour less orange" meant editing source in three places and the four
vendor colours could not be changed at all.

Everything those surfaces paint now resolves through :func:`limit_palette`:

* a user override in ``data["limit_colors"][key]`` wins;
* otherwise the ACTIVE theme supplies it, when the role has a theme counterpart
  (a bar outline should follow the theme's border, not fight it);
* otherwise the built-in default below.

Overrides live in ONE profile dict rather than a dozen top-level keys, so a
profile written by an older build simply has no entry and every role falls back
exactly as before.
"""

from __future__ import annotations

import dataclasses

from PyQt6.QtGui import QColor

from fastprompter.core.usage_limits.model import PROVIDER_RESET_COLORS
from fastprompter.theme.themes import theme_raw_colors

SETTING_KEY = "limit_colors"


@dataclasses.dataclass(frozen=True)
class LimitColor:
    """One paintable role in the AI-limit UI."""

    key: str
    label: str
    tooltip: str
    default: str
    # raw_colors name in the active theme; used when the user has no override.
    theme_key: str = ""


# Ordered as they are presented in the settings tab: quota levels first (the
# ones a user actually wants to retune), then states, then structure, then the
# per-vendor countdown colours.
ROLES: tuple[LimitColor, ...] = (
    LimitColor("good", "Healthy quota",
               "Bars and marks while more than 50% remains",
               "#D9B340", theme_key="accent"),
    LimitColor("warn", "Low quota",
               "Below 50% remaining", "#A3822A"),
    LimitColor("bad", "Critical quota",
               "Below 20% remaining", "#C05A3A"),
    LimitColor("stale", "Stale reading",
               "The last good numbers, when a probe could not refresh them",
               "#9C9371"),
    LimitColor("dim", "Unavailable / not probed",
               "Placeholder marks and windows a provider cannot report",
               "#6E674E"),
    LimitColor("edge", "Mark outline",
               "Outline of a live bar or dot", "#5a4a2a",
               theme_key="border_light"),
    LimitColor("bg", "Gauge background",
               "Behind the header gauge; follows the theme by default so the "
               "gauge blends into the header bar",
               "#1a1a1a", theme_key="bg_main"),
    LimitColor("track", "Bar track",
               "Empty part of a full-size bar in this window",
               "#2c2c2c", theme_key="bg_text"),
    LimitColor("text", "Label text",
               "Window names and values beside the full-size bars",
               "#c0c0c0", theme_key="text_main"),
    LimitColor("light", "Bevel highlight",
               "Lit edge of the Win95 bevel around a full-size bar",
               "#4d4d4d", theme_key="border_light"),
    LimitColor("dark", "Bevel shadow",
               "Shadowed edge of the Win95 bevel around a full-size bar",
               "#0a0a0a", theme_key="border_dark"),
    LimitColor("pool", "Quota pool heading",
               "Name of an independent quota pool (Antigravity groups its "
               "Gemini and Claude/GPT limits separately)",
               "#9C9371"),
    LimitColor("hint", "Caption text",
               "Small explanatory lines in this window and the header status",
               "#9C9371"),
    LimitColor("reset_claude", "Claude reset timer",
               "Header countdown colour when Claude refills next",
               PROVIDER_RESET_COLORS["claude"]),
    LimitColor("reset_codex", "Codex reset timer",
               "Header countdown colour when Codex refills next",
               PROVIDER_RESET_COLORS["codex"]),
    LimitColor("reset_antigravity", "Antigravity reset timer",
               "Header countdown colour when Antigravity refills next",
               PROVIDER_RESET_COLORS["antigravity"]),
    LimitColor("reset_zcode", "ZCode reset timer",
               "Header countdown colour when ZCode refills next",
               PROVIDER_RESET_COLORS["zcode"]),
)

ROLES_BY_KEY = {role.key: role for role in ROLES}


def overrides(data: dict | None) -> dict[str, str]:
    """The user's colour overrides, tolerating a pre-codec/garbage profile."""
    raw = (data or {}).get(SETTING_KEY)
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        key = str(key)
        if key not in ROLES_BY_KEY:
            continue
        color = QColor(str(value))
        if color.isValid():
            out[key] = color.name()
    return out


def resolve_hex(main_win, key: str) -> str:
    """The hex colour for one role: override, then theme, then default."""
    role = ROLES_BY_KEY.get(key)
    if role is None:
        return "#808080"
    data = getattr(main_win, "data", None)
    override = overrides(data).get(key)
    if override:
        return override
    if role.theme_key:
        # Each role carries its OWN default into the lookup. A shared fallback
        # dict keyed by theme_key silently merged the roles that follow the same
        # theme colour (edge and light both read border_light), so whichever was
        # declared last decided what the other fell back to before the theme
        # cache existed.
        raw = theme_raw_colors(main_win, {role.theme_key: role.default})
        value = raw.get(role.theme_key)
        if value:
            candidate = QColor(str(value))
            if candidate.isValid():
                return candidate.name()
    return role.default


def limit_palette(main_win) -> dict[str, QColor]:
    """Every role as a QColor, ready to paint with."""
    return {role.key: QColor(resolve_hex(main_win, role.key))
            for role in ROLES}


def reset_color(main_win, provider_id: str) -> str | None:
    """Header countdown colour for one vendor, or None to inherit the theme.

    Mirrors ``model.provider_reset_color`` but honours the user's override; the
    model keeps the Qt-free defaults so the core never imports a widget toolkit.
    """
    key = f"reset_{provider_id}"
    if key not in ROLES_BY_KEY:
        return None
    return resolve_hex(main_win, key)
