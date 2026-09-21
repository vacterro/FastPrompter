"""Versioned, deterministic responsive policy for the main top bar.

Toolbar order and responsive visibility are deliberately separate settings.
This module contains no Qt code, so validation, migration and range selection
can be tested without constructing the application window.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

VERSION = 1
RANGE_IDS = ("wide", "medium", "narrow", "ultra")
RULES = frozenset({"show", "auto", "hide"})
DETAILS = frozenset({"full", "compact"})


@dataclass(frozen=True)
class TopbarItem:
    token: str
    label: str
    group: str
    priority: int = 50
    configurable: bool = True
    action: bool = True
    compact: bool = False


def _item(token, label, group, priority=50, *, configurable=True,
          action=True, compact=False):
    return TopbarItem(token, label, group, priority, configurable, action, compact)


# Stable English labels are translated only at presentation time. Persistent
# identity is always ``token``.
TOPBAR_ITEMS = (
    _item("btn_sidebar_toggle", "Sidebar", "Access", 1000,
          configurable=False),
    _item("btn_settings_toggle", "Settings", "Access", 1000,
          configurable=False),
    _item("btn_pin_top", "Always on top", "Window", 55),
    _item("btn_line_nums", "Line numbers", "Editor", 45),
    _item("cat_combo", "Project list", "Projects", 100, action=False),
    _item("cat_numbox", "Project number tabs", "Projects", 100, action=False),
    _item("btn_new", "New", "Projects", 120),
    _item("btn_save", "Save", "Projects", 115),
    _item("btn_home", "Go to start", "Navigation", 35),
    _item("btn_end", "Go to end", "Navigation", 35),
    _item("btn_trash", "Trash", "Projects", 42),
    _item("btn_toggle_search", "Search", "Navigation", 48),
    _item("btn_toggle_snippets", "Snippets", "Projects", 46),
    _item("btn_arc_snip", "Archive current", "Projects", 38),
    _item("btn_toggle_archive", "Archive", "Projects", 38),
    _item("btn_project_folder", "Project folder", "Projects", 52),
    _item("btn_project_run", "Run project", "Projects", 52),
    _item("btn_files", "Files", "Projects", 50),
    _item("btn_vision", "View mode", "Editor", 40),
    _item("btn_bold", "Bold", "Formatting", 30),
    _item("btn_italic", "Italic", "Formatting", 30),
    _item("btn_under", "Underline", "Formatting", 24),
    _item("btn_strike", "Strikethrough", "Formatting", 22),
    _item("btn_header", "Header", "Formatting", 34),
    _item("btn_quote", "Quote", "Formatting", 28),
    _item("btn_align_left", "Align left", "Formatting", 18),
    _item("btn_align_center", "Align center", "Formatting", 18),
    _item("btn_align_right", "Align right", "Formatting", 18),
    _item("btn_clear_fmt", "Clear formatting", "Formatting", 16),
    _item("btn_add_line", "Insert divider", "Editor", 26),
    _item("btn_bullet_toggle", "Bullets", "Formatting", 28),
    _item("btn_copy", "Copy all", "Editor", 32),
    _item("btn_clear", "Clear text", "Editor", 25),
    _item("analog_clock", "Analog clock", "Status", 96, action=False),
    _item("lbl_date", "Digital date and time", "Status", 98,
          action=False, compact=True),
    _item("lbl_timer", "Timer countdown", "Status", 90, action=False),
    _item("limit_gauges", "AI limit gauges", "Status", 94, action=False),
    _item("lbl_limit_timer", "AI reset countdown", "Status", 95, action=False),
    _item("_counter_sep", "Counter separator", "Status", 10,
          configurable=False, action=False),
    _item("lbl_line_count", "Line counter", "Status", 97, action=False),
    _item("lbl_token_count", "Token estimate", "Status", 72, action=False),
    _item("btn_settings_toggle_right", "Settings (right)", "Access", 60),
    _item("btn_help", "Help", "Access", 44),
    _item("btn_toolbar_reset", "Reset toolbar order", "Access", 1000,
          configurable=False),
    _item("btn_overflow", "More", "Access", 999,
          configurable=False),
)

ITEM_BY_TOKEN = {item.token: item for item in TOPBAR_ITEMS}


def _default_rule(item: TopbarItem, range_id: str) -> str:
    if not item.configurable:
        return "show"
    if range_id == "wide":
        return "show"
    if range_id == "medium":
        # Important information and project creation stay requested; compact
        # editor affordances yield deterministically if metrics demand it.
        return "show" if item.priority >= 90 else "auto"
    # At genuinely small widths physics decides among AUTO items by priority.
    # They remain recoverable in overflow when they are actions.
    return "show" if item.token in {"btn_new", "btn_save"} else "auto"


def default_topbar_visibility() -> dict:
    items = {}
    for item in TOPBAR_ITEMS:
        row = {rid: _default_rule(item, rid) for rid in RANGE_IDS}
        row["priority"] = item.priority
        if item.compact:
            row["detail"] = {
                "wide": "full", "medium": "full",
                "narrow": "full", "ultra": "compact",
            }
        items[item.token] = row
    return {
        "version": VERSION,
        "breakpoints": [
            {"id": "ultra", "min": 0, "max": 599},
            {"id": "narrow", "min": 600, "max": 899},
            {"id": "medium", "min": 900, "max": 1279},
            {"id": "wide", "min": 1280, "max": None},
        ],
        "items": items,
    }


def _valid_breakpoints(raw) -> list[dict]:
    defaults = default_topbar_visibility()["breakpoints"]
    if not isinstance(raw, list):
        return defaults
    by_id = {entry.get("id"): entry for entry in raw if isinstance(entry, dict)}
    try:
        narrow = int(by_id["narrow"]["min"])
        medium = int(by_id["medium"]["min"])
        wide = int(by_id["wide"]["min"])
    except (KeyError, TypeError, ValueError):
        return defaults
    if not (200 <= narrow < medium < wide <= 10000):
        return defaults
    return [
        {"id": "ultra", "min": 0, "max": narrow - 1},
        {"id": "narrow", "min": narrow, "max": medium - 1},
        {"id": "medium", "min": medium, "max": wide - 1},
        {"id": "wide", "min": wide, "max": None},
    ]


def normalize_topbar_visibility(raw) -> dict:
    """Merge valid user values over defaults; malformed data heals closed."""
    result = default_topbar_visibility()
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return result
    result["breakpoints"] = _valid_breakpoints(raw.get("breakpoints"))
    rows = raw.get("items")
    if not isinstance(rows, dict):
        return result
    for token, default_row in result["items"].items():
        incoming = rows.get(token)
        if not isinstance(incoming, dict):
            continue
        item = ITEM_BY_TOKEN[token]
        if item.configurable:
            for rid in RANGE_IDS:
                rule = incoming.get(rid)
                if rule in RULES:
                    default_row[rid] = rule
            try:
                default_row["priority"] = max(0, min(1000, int(
                    incoming.get("priority", default_row["priority"]))))
            except (TypeError, ValueError):
                pass
        if item.compact and isinstance(incoming.get("detail"), dict):
            for rid in RANGE_IDS:
                detail = incoming["detail"].get(rid)
                if detail in DETAILS:
                    default_row["detail"][rid] = detail
    return result


def range_for_width(config: dict, effective_width: float) -> str:
    cfg = normalize_topbar_visibility(config)
    try:
        width = max(0.0, float(effective_width))
    except (TypeError, ValueError):
        width = 0.0
    for entry in cfg["breakpoints"]:
        upper = entry["max"]
        if width >= entry["min"] and (upper is None or width <= upper):
            return entry["id"]
    return "ultra"


def requested_tokens(config: dict, effective_width: float,
                     semantic: dict[str, bool]) -> tuple[str, dict[str, str]]:
    """Return active range and semantic+policy requested rules from scratch."""
    cfg = normalize_topbar_visibility(config)
    rid = range_for_width(cfg, effective_width)
    requested = {}
    for item in TOPBAR_ITEMS:
        if item.token == "btn_overflow":
            continue
        if semantic.get(item.token, True):
            rule = cfg["items"][item.token][rid]
            if rule != "hide":
                requested[item.token] = rule
    return rid, requested


def clone_config(config: dict) -> dict:
    return copy.deepcopy(normalize_topbar_visibility(config))
