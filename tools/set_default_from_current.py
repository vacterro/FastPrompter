"""SetDefaultFromCurrent: the ONE canonical bake of live preferences.

Contract (SRC-029 corrective, 0.8.68 RC):

    LIVE PREFERENCE SNAPSHOT
    -> SANITIZE TRANSIENT / PERSONAL / MACHINE STATE
    -> PREVIEW (counts, named highlights, asset check)
    -> EXPLICIT CONFIRM
    -> ATOMIC WRITE of `src/fastprompter/core/default_profile.py`
    -> INDEPENDENT RELOAD + EQUALITY CHECK of the written module

A "clean bake" preserves every intentional user preference (theme, layout,
fonts, sounds with gains/modes, quick bar, interval rules, timers, presets,
hotkeys) and neutralizes only what must not ship (personal content, machine
paths, account discovery, runtime timestamps). Reconstructing preferences
from base/HEAD values is NOT a bake -- that semantic mistake replaced the
operator's sound map (T-1295).

Policy: every persisted setting key is classified explicitly as COPY
(shippable live value), NEUTRAL (fixed shipped value) or EXCLUDED (personal /
machine state, keep the shipped base value). An unclassified key fails the
bake loudly instead of being silently dropped, so a newly introduced setting
can never ship as an accident of what an old DEFAULT_PROFILE happened to
contain.

Usage:
    uv run python tools/set_default_from_current.py [--dry-run] [--profile <id>] [--json]
"""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import os
import pprint
import re
import sys
import tempfile
import tokenize
import types
from contextlib import contextmanager
from dataclasses import dataclass, field

# Ensure repo root and src/ are in sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

_TARGET_FILE = os.path.join(_SRC_DIR, "fastprompter", "core", "default_profile.py")


class BakePolicyError(RuntimeError):
    """A persisted setting appeared with no bake classification."""


class BakeRefusalError(RuntimeError):
    """A baked sound reference cannot ship (managed-only / missing / bad)."""


class BakeFrozenError(RuntimeError):
    """A frozen build must never pretend it can mutate repository defaults."""


class BakeBusyError(RuntimeError):
    """Another bake writer holds the target lock beyond the timeout."""


class BakeConcurrentModificationError(RuntimeError):
    """The target file changed under a non-cooperative external writer."""


# Lock defaults: a holder that has not finished (or died) blocks contenders
# for at most this long before they are told to try again later.
_DEFAULT_LOCK_TIMEOUT = 5.0


def canonical_target_path(path) -> str:
    """The lock identity for a target file: absolute, normalized, case-folded.

    Relative/absolute aliases of one file must serialize against the SAME
    lock; on Windows the filesystem is case-insensitive, so the case folds
    too. A target that does not exist yet still resolves deterministically.
    """
    abs_p = os.path.abspath(os.path.expanduser(str(path)))
    norm = os.path.normpath(abs_p)
    if sys.platform == "win32":
        norm = norm.lower()
    return norm


def bake_lock_path(target) -> str:
    """The cross-process lock file guarding one target's bake transaction."""
    return canonical_target_path(target) + ".bake.lock"


@contextmanager
def bake_transaction_lock(target, timeout: float = _DEFAULT_LOCK_TIMEOUT):
    """Hold the exclusive bake lock for ``target`` for the duration.

    Cross-process and cross-thread serialization: two bakes on the SAME
    target (by any path alias) never interleave; different targets never
    block each other. On timeout raises ``BakeBusyError``.
    """
    from tools.write_guard import exclusive_file_lock
    with exclusive_file_lock(
            bake_lock_path(target), timeout=timeout,
            busy_error=BakeBusyError,
            busy_message="a bake of this target is already in progress"):
        yield


# ---------------------------------------------------------------------------
# Shippable-key policy (SRC-029 §9/§14)
# ---------------------------------------------------------------------------

#: Keys whose live value is an intentional, shippable user preference.
COPY_KEYS: frozenset[str] = frozenset((
    "altw_blanks_after", "altw_blanks_before", "altw_bullet_char",
    "altw_s1_after", "altw_s1_before", "altw_s1_bullet", "altw_s1_divider",
    "altw_s2_after", "altw_s2_before", "altw_s2_bullet", "altw_s2_divider",
    "altw_s3_after", "altw_s3_before", "altw_s3_bullet", "altw_s3_divider",
    "altw_s4_after", "altw_s4_before", "altw_s4_bullet", "altw_s4_divider",
    "altw_s5_after", "altw_s5_before", "altw_s5_bullet", "altw_s5_divider",
    "altw_s6_action",
    "always_on_top", "always_on_top_hotkey", "always_on_top_hotkey_alt",
    "analog_clock", "archive_visible",
    "audio_device_render", "audio_edge_pad", "audio_global_muted",
    "audio_render_policy_migrated_v2",
    "auto_bullet", "bold_hash_titles", "bullet_double_line", "button_scale",
    "close_on_focus_loss", "code_auto_gutter",
    "code_monospace",
    "codex_gauges", "codex_gauges_refresh_sec", "cs_style",
    "ctrl_c_closes",
    "ctrl_e_align", "ctrl_e_align_bullet", "ctrl_e_align_rule",
    "ctrl_e_bullet", "ctrl_e_bullet_char", "ctrl_e_center",
    "ctrl_e_follow_edit", "ctrl_e_format",
    "ctrl_e_gap_after", "ctrl_e_gap_below", "ctrl_e_gap_bottom",
    "ctrl_e_rule", "ctrl_e_rule_below", "ctrl_e_stamp_every",
    "ctrlw_blanks_after", "ctrlw_blanks_before", "ctrlw_bullet_char",
    "ctrlw_s1_after", "ctrlw_s1_before", "ctrlw_s1_bullet", "ctrlw_s1_divider",
    "ctrlw_s2_after", "ctrlw_s2_before", "ctrlw_s2_bullet", "ctrlw_s2_divider",
    "ctrlw_s3_after", "ctrlw_s3_before", "ctrlw_s3_bullet", "ctrlw_s3_divider",
    "ctrlw_s4_after", "ctrlw_s4_before", "ctrlw_s4_bullet", "ctrlw_s4_divider",
    "ctrlw_s5_after", "ctrlw_s5_before", "ctrlw_s5_bullet", "ctrlw_s5_divider",
    "ctrlw_s6_action", "ctrlw_split_behavior",
    "cursor_blink_ms", "custom_colors", "custom_cursors", "customize_toolbar",
    "date_ampm", "date_daypart", "date_emoji", "date_seconds",
    "date_text_month", "divider_lines_after",
    "drop_bot_left", "drop_bot_right", "drop_top_left", "drop_top_right",
    "fancyzones_fast", "fancyzones_fast_idx", "fancyzones_layout",
    "file_panel_docked", "file_panel_view", "files_dock_open",
    "files_dock_width", "fkey_action", "font_family", "font_size",
    "global_hotkey", "global_hotkey_alt", "header_position",
    "hide_on_clickout_hotkey", "hide_on_clickout_hotkey_alt", "hide_shortkeys",
    "hk_audio_mute", "hk_bold", "hk_divider", "hk_export_silo", "hk_find",
    "hk_focus", "hk_hashtags", "hk_header", "hk_italic", "hk_line_nums",
    "hk_new_snippet", "hk_pack_selection", "hk_pack_silo", "hk_quote", "hk_quit",
    "hk_replace",
    "hk_save_snippet", "hk_settings", "hk_snap", "hk_timers", "hk_underline",
    "hk_undo",
    "hover_line", "hover_line_color", "hover_line_opacity", "hr_visual_line",
    "language", "last_save_format",
    "limit_colors", "limit_gauges", "limit_gauges_fill",
    "limit_gauges_hide_unusable_5h", "limit_gauges_hide_zero_usage",
    "limit_gauges_refresh_sec", "limit_gauges_show_labels",
    "limit_gauges_style", "limit_gauges_vendor_tint",
    "limit_notif_color", "limit_notif_duration_sec", "limit_notif_symbol",
    "line_heat", "line_heat_palette", "line_heat_strength", "line_marks",
    "live_preview_conceal", "lock_to_cursor",
    "lock_window_hotkey", "lock_window_hotkey_alt",
    "new_silo_paste_clipboard", "numbox_btn_size", "numbox_per_row",
    "numbox_tabs", "pack_coverage_fade", "passed_alert_enabled", "passed_event_color",
    "paste_mode",
    "pie_menu_hotkey", "pie_menu_hotkey_alt",
    "portable_backup_enabled", "preview_mode", "productivity_timer",
    "quote_italic", "saved_sidebar_size", "saved_sound_mappings",
    "settings_width", "show_date_rect", "show_line_numbers", "show_pack_coverage", "show_titlebar",
    "show_token_count", "sidebar_right",
    "silo_0_hotkey", "silo_0_hotkey_alt", "silo_1_hotkey", "silo_1_hotkey_alt",
    "silo_2_hotkey", "silo_2_hotkey_alt", "silo_3_hotkey", "silo_3_hotkey_alt",
    "silo_4_hotkey", "silo_4_hotkey_alt",
    "silo_bundle_keep_versions",
    "silo_chest_slots", "silo_color_box", "silo_gap_height", "silo_pinned_gap",
    "silo_random_color_on_new", "silo_remember_scroll",
    "silo_remember_scroll_migrated",
    "silo_tabs_mode", "silo_ticks_enabled",
    "snippet_0_hotkey", "snippet_0_hotkey_alt",
    "snippet_1_hotkey", "snippet_1_hotkey_alt",
    "snippet_2_hotkey", "snippet_2_hotkey_alt",
    "snippet_3_hotkey", "snippet_3_hotkey_alt",
    "snippet_4_hotkey", "snippet_4_hotkey_alt",
    "snippet_5_hotkey", "snippet_6_hotkey", "snippet_7_hotkey",
    "snippet_8_hotkey", "snippet_9_hotkey",
    "snippet_arrows", "snippets_hidden", "snippets_visible",
    "sound_events", "sound_gain_schema",
    "sound_hotkey_on_by_default", "sound_quick_bar", "sound_typewriter",
    "sound_ui", "sound_volume",
    "splitter_sizes", "splitter_sizes_left", "splitter_sizes_right",
    "splitter_width", "static_cursor",
    "sync_exclude", "sync_include", "sync_live_watch", "sync_max_kb",
    "sync_mode", "sync_recursive",
    "tab_overflow_mode", "temp_timer_settings", "text_align", "theme",
    "timer_show_minutes", "toggle_files_hotkey",
    "toggle_sidebar_hotkey", "toggle_sidebar_hotkey_alt",
    "token_mode", "token_weight", "toolbar_hidden", "toolbar_order",
    "toolbar_position", "topbar_visibility", "trash_vision",
    "tray_click_activates", "tray_visible", "two_sided_buttons",
    "typo_check_enabled", "typo_color", "ui_scale", "window_locked",
    "window_presets", "window_presets_enabled", "word_wrap",
    "zebra_lines", "zebra_stripes",
    # T-1466: user-defined default table layout template
    "table_default_layout",
))

#: Keys that ARE shipped settings but may not carry live/machine state.
NEUTRAL_KEYS: dict[str, object] = {
    "hide_extra": "True",
    "search_visible": "False",
    # A custom executable is machine-local. Ship system association mode with
    # an empty path so the baked pair can never describe a broken custom mode.
    "image_viewer_mode": "system",
    "image_viewer_path": "",
    "limit_antigravity_dir": "",
    "limit_codex_homes": "",
    # Extra Claude accounts are machine-local CLAUDE_CONFIG_DIR paths.
    "limit_claude_homes": "",
    # zcode / freebuff are opt-in providers aimed at machine-local paths.
    "limit_zcode_config": "",
    "limit_zcode_enabled": "False",
    "limit_freebuff_state": "",
    "limit_freebuff_enabled": "False",
    # Discovered account identities / delivery state are machine-local.
    "limit_gauges_hidden_accounts": [],
    "limit_gauges_account_labels": {},
    "limit_gauges_account_names": {},
    "limit_gauges_account_order": [],
    "limit_notifications": {},
    "limit_notification_state": {},
    "project_sync": {},
    "project_sync_all": {},
    "project_sync_map": {},
    "project_sync_map_all": {},
    "typo_user_words": [],
}

#: Keys that are personal content / machine state; keep the shipped base value
#: (or omit the key entirely when the base has none).
EXCLUDED_KEYS: frozenset[str] = frozenset((
    "active_silo_folder", "active_temp_slot", "agent_timers",
    "arc_page", "arc_silo_page",
    "archive_project_paths", "archive_project_paths_all",
    "archive_silo_folders", "archive_silo_folders_all",
    "archive_temp_presets", "archive_temp_presets_all",
    "category_file_dirs", "cats_order", "categories",
    "custom_font_ids", "custom_font_paths", "folder_trash_log", "hidden_categories",
    "last_geometry", "last_tab_idx", "last_text",
    "limit_settings_geometry", "line_marks_data", "missed_timer_ids",
    "normal_window", "pinned_silos", "pinned_silos_all",
    "recent_files", "recent_replace_terms", "recent_search_terms",
    "silo_bundle_defaults", "silo_bundle_history", "silo_bundle_meta_retry",
    "silo_category", "silo_children", "silo_children_all", "silo_collapsed",
    "silo_collapsed_all", "silo_colors", "silo_colors_all", "silo_done_marks",
    "silo_folders", "silo_folders_all", "silo_folders_order",
    "silo_gap_names", "silo_gap_names_all", "silo_gaps", "silo_gaps_all",
    "silo_home_states", "silo_last_edited", "silo_last_edited_all",
    "silo_links", "silo_links_all", "silo_media_first_seen", "silo_project_paths",
    "silo_project_paths_all", "silo_row_presence", "silo_selected",
    "silo_selected_all", "silo_session_all", "silo_text", "silo_ticked",
    "silo_ticked_all", "silo_type_all", "silo_types", "silo_view_state_all",
    "silos", "silo_pack_coverage", "snippets", "sync_path", "temp_presets", "temp_presets_all",
    "text", "timers", "trash_consumed", "trash_text_folder", "watcher_queues",
    "watcher_queues_all", "watcher_skill",
    "window_geometry", "window_presets_capture_state", "window_x", "window_y",
    "archive_folders", "archive_folders_all", "archive_silos", "content",
    "file_tags", "history", "redo_history", "undo_history",
))

#: Keys that must NEVER appear in the shipped profile, not even as a neutral
#: empty structure: they are pure session artifacts or personal-content maps
#: (test_state.TestDefaultProfile.test_no_user_content_baked_in pins this).
DROP_KEYS: frozenset[str] = frozenset((
    "aligned_blocks", "centered_blocks", "files_root", "files_root_folder",
    # obsolete alias: replaced by silo_remember_scroll (T-1459); a profile
    # still carrying it must fail open at bake time instead of shipping it
    "silo_home",
    # obsolete alias: the canonical shipped key is sound_ui
    # (tests/test_resync_keys.py::test_sound_enabled_alias_removed_from_defaults)
    "sound_enabled",
))

#: Release-level overrides (SRC-029 §11). Exactly one explicit override:
#: the shipped base language stays EN while every other preference bakes.
RELEASE_OVERRIDES: dict[str, object] = {"language": "EN"}

#: Source-owned keys: the canonical value comes from the source module, not
#: from the live profile. An id-matched live customization still passes the
#: sanitizer and ships (that is what "make the current state the default"
#: means), but it is written as a literal -- the symbolic form is reserved
#: for values that still equal the canonical preset (T-1443, T-1457-B).
SOURCE_OWNED_KEYS: frozenset[str] = frozenset((
    "interval_notifs",
))

#: Returned by :func:`_symbol_value_in_source` when the source being rewritten
#: cannot be executed, so the formatter uses the literal form (T-1457-B).
_SYMBOL_UNREADABLE = object()

#: Backwards-compatible aliases (existing importers/tests).
DENYLIST = EXCLUDED_KEYS
RESET_KEYS = NEUTRAL_KEYS

#: Runtime fields stripped from structured preference payloads before shipping.
_RUNTIME_TIMER_FIELDS = frozenset((
    "last_fired", "last_fired_minute", "remaining", "running", "active",
    "started_at", "target_epoch", "next_fire", "fired_at",
))


def policy_conflicts() -> list[str]:
    """Keys claimed by more than one policy set (must always be empty).

    A key present in both COPY_KEYS and EXCLUDED_KEYS is the dangerous case:
    whichever branch runs first silently decides, and personal text can ship
    while the exclusion looks authoritative. Overlap is a policy bug.
    """
    sets = {
        "copy": set(COPY_KEYS),
        "neutral": set(NEUTRAL_KEYS),
        "excluded": set(EXCLUDED_KEYS),
        "drop": set(DROP_KEYS),
        "source_owned": set(SOURCE_OWNED_KEYS),
    }
    conflicts = set()
    names = sorted(sets)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            conflicts |= sets[left] & sets[right]
    return sorted(conflicts)


def classify_key(key: str) -> str:
    """Return ``"copy" | "neutral" | "excluded" | "drop" | "source_owned"`` for a key."""
    hits = []
    if key in COPY_KEYS:
        hits.append("copy")
    if key in NEUTRAL_KEYS:
        hits.append("neutral")
    if key in EXCLUDED_KEYS:
        hits.append("excluded")
    if key in DROP_KEYS:
        hits.append("drop")
    if key in SOURCE_OWNED_KEYS:
        hits.append("source_owned")
    if len(hits) > 1:
        raise BakePolicyError(
            f"ambiguous bake policy for {key!r}: {hits} -- a key may belong "
            f"to exactly one of COPY_KEYS / NEUTRAL_KEYS / EXCLUDED_KEYS / "
            f"DROP_KEYS / SOURCE_OWNED_KEYS")
    if hits:
        return hits[0]
    raise BakePolicyError(
        f"unclassified setting {key!r}: classify it in COPY_KEYS, "
        f"NEUTRAL_KEYS or EXCLUDED_KEYS (SRC-029 §14)")


def assert_policy_covers(keys) -> list[str]:
    """Return the unclassified subset of ``keys`` (empty == full coverage)."""
    missing = []
    for key in keys:
        try:
            classify_key(key)
        except BakePolicyError:
            missing.append(key)
    return missing


# ---------------------------------------------------------------------------
# Frozen build guard (SRC-029 §15)
# ---------------------------------------------------------------------------

def is_frozen_build() -> bool:
    """True inside a packaged onefile build (Nuitka/PyInstaller)."""
    if getattr(sys, "frozen", False):
        return True
    if "__compiled__" in globals():
        return True
    try:
        main_mod = sys.modules.get("__main__")
        if main_mod is not None and hasattr(main_mod, "__compiled__"):
            return True
    except Exception:
        pass
    return hasattr(sys, "nuitka_version")


# ---------------------------------------------------------------------------
# Sound-asset validation (SRC-029 §8)
# ---------------------------------------------------------------------------

PACKAGED = "PACKAGED"
MANAGED_ONLY = "MANAGED-ONLY"
MISSING = "MISSING"
UNSUPPORTED = "UNSUPPORTED"


@dataclass
class AssetCheck:
    ref: str
    status: str
    location: str = ""

    @property
    def shippable(self) -> bool:
        return self.status == PACKAGED


def check_sound_asset(ref, *, builtin_root=None, user_root=None) -> AssetCheck:
    """Classify one baked sound reference for release shipment."""
    text = str(ref or "").strip()
    if not text:
        return AssetCheck(text, UNSUPPORTED, "")
    bare = text[5:] if text.startswith("file:") else text
    if not bare.lower().endswith(".wav"):
        return AssetCheck(text, UNSUPPORTED, "")

    from fastprompter.core.sound_library import (
        VAULT_DIR_NAME,
        contained_path,
        split_ref,
    )

    namespace, rel = split_ref(bare)
    if namespace in ("user", "addon"):
        # Both are machine-local: an imported copy or a file the user dropped
        # into <user-data>/addon/sounds. Neither can ship as a default, so the
        # bake refuses with the precise reason instead of calling it missing.
        found = contained_path(user_root, rel) if user_root else None
        if found and os.path.isfile(found):
            return AssetCheck(text, MANAGED_ONLY, found)
        if namespace == "addon":
            from fastprompter.core.sound_library import addon_root
            found = contained_path(addon_root(), rel)
            if found and os.path.isfile(found):
                return AssetCheck(text, MANAGED_ONLY, found)
        return AssetCheck(text, MISSING, "")

    roots = [builtin_root] if builtin_root else []
    if builtin_root:
        roots.append(os.path.join(builtin_root, VAULT_DIR_NAME))
    for root in roots:
        found = contained_path(root, rel)
        if found and os.path.isfile(found):
            return AssetCheck(text, PACKAGED, found)
    if user_root:
        found = contained_path(user_root, rel)
        if found and os.path.isfile(found):
            return AssetCheck(text, MANAGED_ONLY, found)
    return AssetCheck(text, MISSING, "")


def _looks_like_sound_file(ref) -> bool:
    """True only for actual file references, not logical sound-event tokens.

    Timer configuration legitimately carries logical tokens (``tick``,
    ``notify``) that the runtime resolves through the event registry; those
    are not asset references and must not be asset-checked.
    """
    text = str(ref or "").strip()
    if not text:
        return False
    return text.startswith("file:") or text.lower().endswith(".wav")


def _iter_sound_refs(profile: dict):
    """Yield ``(label, ref)`` for every sound FILE reference in a profile."""
    def _emit(label, ref):
        if _looks_like_sound_file(ref):
            return (label, ref)
        return None

    events = profile.get("sound_events")
    if isinstance(events, dict):
        for event, cfg in events.items():
            if isinstance(cfg, dict) and cfg.get("file"):
                item = _emit(f"sound_events.{event}", cfg["file"])
                if item:
                    yield item
    mappings = profile.get("saved_sound_mappings")
    if isinstance(mappings, dict):
        for name, ref in mappings.items():
            item = _emit(f"saved_sound_mappings.{name}", ref)
            if item:
                yield item
    quick = profile.get("sound_quick_bar")
    if isinstance(quick, list):
        for index, ref in enumerate(quick):
            item = _emit(f"sound_quick_bar[{index}]", ref)
            if item:
                yield item
    intervals = profile.get("interval_notifs")
    if isinstance(intervals, list):
        for rule in intervals:
            if isinstance(rule, dict):
                item = _emit(f"interval_notifs.{rule.get('id', '?')}",
                             rule.get("sound"))
                if item:
                    yield item
    temp = profile.get("temp_timer_settings")
    if isinstance(temp, dict):
        item = _emit("temp_timer_settings.sound", temp.get("sound"))
        if item:
            yield item
        for i, rule in enumerate(temp.get("sound_rules") or []):
            if isinstance(rule, dict):
                item = _emit(f"temp_timer_settings.sound_rules[{i}]",
                             rule.get("sound"))
                if item:
                    yield item
    prod = profile.get("productivity_timer")
    if isinstance(prod, dict):
        for field_name in ("work_sound", "break_sound"):
            item = _emit(f"productivity_timer.{field_name}",
                         prod.get(field_name))
            if item:
                yield item


# ---------------------------------------------------------------------------
# Nested sanitizers (SRC-029 §10)
# ---------------------------------------------------------------------------

def _scrub_custom_colors(value, base_value):
    """custom_colors is an unconditional OVERLAY on the active theme.

    Stamping a key a theme already owns pins the current palette onto every
    theme, so only the extras no theme defines may ship.
    """
    if not isinstance(value, dict):
        return base_value
    from fastprompter.theme.themes import THEMES
    theme_keys = set()
    for spec in THEMES.values():
        theme_keys |= set((spec.get("raw_colors") or {}).keys())
    return {k: v for k, v in sorted(value.items()) if k not in theme_keys}


def _sanitize_sound_events(value, base_value):
    """Preserve the complete modern per-event contract, never downgrade it."""
    if not isinstance(value, dict):
        return copy.deepcopy(base_value)
    healed = {}
    for event, cfg in value.items():
        if isinstance(cfg, dict):
            healed[str(event)] = copy.deepcopy(cfg)
        else:
            healed[str(event)] = cfg
    return healed


def _sanitize_interval_notifs(value, base_value):
    """Keep intentional rule configuration; neutralize runtime history.

    Source-owned daypart rules are matched by id against the canonical
    template: rules whose id exists in the base profile pass through
    sanitized; a live-only rule set that cannot be matched at all (e.g. a
    foreign or hacked list) is rejected wholesale and the canonical rules
    ship instead -- a conflicting live value can never replace them.
    """
    if not isinstance(value, list) or not isinstance(base_value, list):
        return copy.deepcopy(base_value)
    canonical_ids = {
        (rule.get("id") if isinstance(rule, dict) else None)
        for rule in base_value
    }
    rules = []
    for rule in value:
        if not isinstance(rule, dict):
            continue
        clean = copy.deepcopy(rule)
        clean["last_fired"] = 0.0
        clean["last_fired_minute"] = ""
        rules.append(clean)
    if not rules:
        return copy.deepcopy(base_value)
    if not canonical_ids or any(rule.get("id") in canonical_ids for rule in rules):
        return rules
    return copy.deepcopy(base_value)


def _strip_runtime_fields(payload: dict) -> dict:
    out = copy.deepcopy(payload)
    for field_name in _RUNTIME_TIMER_FIELDS:
        out.pop(field_name, None)
    return out


def _sanitize_temp_timer(value, base_value):
    if not isinstance(value, dict):
        return copy.deepcopy(base_value)
    return _strip_runtime_fields(value)


def _sanitize_productivity_timer(value, base_value):
    if not isinstance(value, dict):
        return copy.deepcopy(base_value)
    out = _strip_runtime_fields(value)
    if "completed_cycles" in out:
        out["completed_cycles"] = 0
    return out


def _sanitize_silo_chest_slots(value, base_value):
    """Preserve only supported chest capacities; junk uses the canonical default."""
    allowed = {"dynamic", "64", "128"}
    if isinstance(value, bool):
        normalized = None
    elif isinstance(value, int):
        normalized = str(value) if str(value) in allowed else None
    elif isinstance(value, str) and value.strip().lower() in allowed:
        normalized = value.strip().lower()
    else:
        normalized = None

    if normalized is not None:
        return normalized
    if isinstance(base_value, str) and base_value.strip().lower() in allowed:
        return base_value.strip().lower()
    if isinstance(base_value, int) and not isinstance(base_value, bool) \
            and str(base_value) in allowed:
        return str(base_value)
    return "dynamic"


# key -> sanitizer(live_value, base_value). Applied to a value taken from the
# live profile, so a session value can never ship in a shape the shipped
# defaults are not allowed to carry.
SANITIZERS = {
    "custom_colors": _scrub_custom_colors,
    "sound_events": _sanitize_sound_events,
    "interval_notifs": _sanitize_interval_notifs,
    "temp_timer_settings": _sanitize_temp_timer,
    "productivity_timer": _sanitize_productivity_timer,
    "silo_chest_slots": _sanitize_silo_chest_slots,
}


#: Named preference surfaces the preview must call out (SRC-029 §12).
HIGHLIGHT_KEYS = (
    "theme", "language", "sidebar_right", "sound_volume", "sound_typewriter",
    "font_family", "ui_scale", "toolbar_position", "saved_sidebar_size",
    "splitter_sizes_right", "splitter_sizes_left", "sound_quick_bar",
    "window_presets", "interval_notifs",
)


def _coerce_to_base_type(value, base_value):
    """Keep the shipped default's TYPE.

    Settings round-trip through SQLite as text, so the live dict holds
    ``font_size='10'`` where the shipped default is the int ``10`` that every
    consumer expects. Stamping the string back silently changes the type of a
    shipped default.
    """
    if isinstance(base_value, bool) or not isinstance(base_value, (int, float)):
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return value
    try:
        return type(base_value)(float(value)) if isinstance(base_value, int) \
            else type(base_value)(value)
    except (TypeError, ValueError):
        return base_value


@dataclass
class BakePlan:
    """One reviewable bake: sanitized profile + evidence for the operator."""

    profile: dict
    base: dict
    copied: int = 0
    neutralized: int = 0
    excluded: int = 0
    changed: list = field(default_factory=list)
    highlights: dict = field(default_factory=dict)
    assets: list = field(default_factory=list)
    refused: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refused

    def summary(self) -> dict:
        return {
            "keys_total": len(self.profile),
            "safe_values_copied": self.copied,
            "reset_neutralized": self.neutralized,
            "excluded_personal": self.excluded,
            "asset_references_verified": sum(
                1 for a in self.assets if a.shippable),
            "asset_refusals": len(self.refused),
            "warnings": len(self.warnings),
            "changed_count": len(self.changed),
            "highlights": self.highlights,
            "refused": [
                {"ref": a.ref, "status": a.status, "location": a.location}
                for a in self.refused
            ],
            "warnings_detail": list(self.warnings),
        }


def _highlight_profile_diff(old: dict, new: dict) -> dict:
    highlights = {}
    for key in HIGHLIGHT_KEYS:
        before, after = old.get(key), new.get(key)
        if before != after:
            highlights[key] = {"from": before, "to": after}
    old_events = old.get("sound_events") or {}
    new_events = new.get("sound_events") or {}
    if isinstance(old_events, dict) and isinstance(new_events, dict):
        changed_events = []
        for event in sorted(set(old_events) | set(new_events)):
            old_file = (old_events.get(event) or {}).get("file") \
                if isinstance(old_events.get(event), dict) else None
            new_file = (new_events.get(event) or {}).get("file") \
                if isinstance(new_events.get(event), dict) else None
            if old_file != new_file:
                changed_events.append(
                    {"event": event, "from": old_file, "to": new_file})
        if changed_events:
            highlights["sound_event_mappings_changed"] = changed_events
        highlights["sound_event_mapping_count"] = {
            "from": len(old_events), "to": len(new_events)}
    return highlights


def build_bake_plan(source_data: dict, base_defaults: dict | None = None,
                    *, builtin_root: str | None = None,
                    user_root: str | None = None,
                    release_overrides: dict | None = None,
                    check_assets: bool = True) -> BakePlan:
    """Build the sanitized shippable profile + preview evidence.

    Raises :class:`BakePolicyError` when a persisted key is unclassified.
    Sound references that cannot ship land in ``plan.refused`` (the caller
    must not write a refused plan -- never a silent substitution).
    """
    if base_defaults is None:
        from fastprompter.core.default_profile import DEFAULT_PROFILE as _BASE
        base_defaults = _BASE

    universe = sorted(set(base_defaults) | set(source_data))
    overrides = RELEASE_OVERRIDES if release_overrides is None else release_overrides

    # Fail closed BEFORE producing any partial profile (SRC-029 §14).
    missing = assert_policy_covers(universe)
    if missing:
        raise BakePolicyError(
            "unclassified settings present: " + ", ".join(missing) +
            " -- classify them in tools/set_default_from_current.py")

    if builtin_root is None:
        from fastprompter.core.sound_library import packaged_root
        builtin_root = packaged_root()
    if user_root is None:
        from fastprompter.core.sound_library import managed_root
        user_root = managed_root()

    plan = BakePlan(profile={}, base=dict(base_defaults))
    plan.copied = plan.neutralized = plan.excluded = 0

    for key in universe:
        policy = classify_key(key)
        if policy == "drop":
            plan.excluded += 1
            continue
        if policy == "excluded":
            plan.excluded += 1
            if key in base_defaults:
                plan.profile[key] = copy.deepcopy(base_defaults[key])
            continue

        if policy == "neutral":
            plan.neutralized += 1
            plan.profile[key] = copy.deepcopy(NEUTRAL_KEYS[key])
            continue

        if policy == "source_owned":
            # Shippable, but the live value only passes through the canonical
            # sanitizer (id-matched daypart rules); anything foreign is
            # rejected and the canonical source-owned value ships instead.
            plan.copied += 1
            sanitize = SANITIZERS.get(key)
            if sanitize is not None:
                plan.profile[key] = copy.deepcopy(
                    sanitize(source_data.get(key), base_defaults.get(key)))
            elif key in base_defaults:
                plan.profile[key] = copy.deepcopy(base_defaults[key])
            continue

        # copy
        plan.copied += 1
        if key in source_data:
            value = source_data[key]
            sanitize = SANITIZERS.get(key)
            if sanitize is not None:
                value = sanitize(value, base_defaults.get(key))
            plan.profile[key] = _coerce_to_base_type(
                value, base_defaults.get(key))
        elif key in base_defaults:
            # The shipped base fallback passes the SAME sanitizer: a stale
            # base value (e.g. interval last_fired from an old hand bake) must
            # not survive just because the source profile omitted the key.
            value = base_defaults[key]
            sanitize = SANITIZERS.get(key)
            if sanitize is not None:
                value = sanitize(value, base_defaults.get(key))
            plan.profile[key] = copy.deepcopy(value)
        else:
            plan.profile[key] = None
            plan.warnings.append(f"{key}: no live value and no shipped base")

    # Release overrides are applied last, named, and must be shippable keys;
    # they ship even when the source profile predates the key (SRC-029 §11).
    for key, value in (overrides or {}).items():
        if classify_key(key) != "copy":
            raise BakePolicyError(f"release override {key!r} is not shippable")
        plan.profile[key] = copy.deepcopy(value)
        plan.warnings.append(f"release override: {key} = {value!r}")

    if check_assets:
        for label, ref in _iter_sound_refs(plan.profile):
            check = check_sound_asset(ref, builtin_root=builtin_root,
                                      user_root=user_root)
            plan.assets.append(check)
            if not check.shippable:
                plan.refused.append(check)
                plan.warnings.append(
                    f"{label}: {ref!r} is {check.status} -- bake refused "
                    f"(use the canonical asset mechanism or remove the "
                    f"mapping; never substitute a default)")

    plan.changed = [
        (key, base_defaults.get(key), plan.profile[key])
        for key in sorted(plan.profile)
        if base_defaults.get(key) != plan.profile[key]
    ]
    plan.highlights = _highlight_profile_diff(dict(base_defaults),
                                              plan.profile)
    return plan


def extract_defaults_from_data(source_data: dict, base_defaults: dict = None) -> dict:
    """Sanitized profile dict (back-compatible pure transformation).

    Performs NO filesystem/asset access: callers that are about to WRITE the
    shipped file must go through :func:`build_bake_plan` +
    :func:`apply_bake_plan`, which classify and refuse non-packaged sound
    references before any write.
    """
    plan = build_bake_plan(source_data, base_defaults, check_assets=False)
    return plan.profile


# ---------------------------------------------------------------------------
# Live snapshot (SRC-029 §5/§6)
# ---------------------------------------------------------------------------

def snapshot_defaults_from_window(window, data=None) -> dict:
    """Collect the live preference truth WITHOUT mutating personal state.

    The snapshot starts from the window's live data dict (the same authority
    normal persistence uses) and then refreshes values owned by live widgets
    -- splitter geometry, sidebar side and saved width -- taken from the
    widget at this instant, not from a stale list written at an earlier save
    boundary.
    """
    source = data if data is not None else getattr(window, "data", None)
    snapshot = copy.deepcopy(source) if isinstance(source, dict) else {}

    try:
        splitter = getattr(window, "splitter", None)
        sizes = list(splitter.sizes()) if splitter is not None else []
    except (RuntimeError, TypeError, AttributeError):
        sizes = []

    if sizes:
        is_right = bool(getattr(window, "_sidebar_right", False))
        snapshot["splitter_sizes"] = sizes[:2]
        snapshot["splitter_sizes_right" if is_right
                 else "splitter_sizes_left"] = sizes
        snapshot["sidebar_right"] = "True" if is_right else "False"
        if is_right and len(sizes) >= 3:
            snapshot["saved_sidebar_size"] = str(sizes[-1])

    try:
        saved = getattr(window, "_saved_sidebar_size", None)
        if saved:
            snapshot["saved_sidebar_size"] = str(int(saved))
    except (TypeError, ValueError):
        pass

    return snapshot


# ---------------------------------------------------------------------------
# Formatting / writing / roundtrip verification
# ---------------------------------------------------------------------------

def _symbol_value_in_source(source: str, symbol: str):
    """Value ``symbol`` denotes when the source being rewritten executes.

    The symbolic write is lossless only while the baked value still equals
    what the symbol evaluates to. Returns :data:`_SYMBOL_UNREADABLE` when the
    source cannot be executed at all, so the caller falls back to the literal
    form rather than guessing (T-1457-B).
    """
    module = types.ModuleType("fastprompter_bake_symbol_probe")
    module.__file__ = _TARGET_FILE
    try:
        exec(compile(source, _TARGET_FILE, "exec"), module.__dict__)
    except BaseException:
        return _SYMBOL_UNREADABLE
    return getattr(module, symbol, _SYMBOL_UNREADABLE)


def format_default_profile_py(new_profile: dict, original_source: str) -> str:
    """Rebuild only the DEFAULT_PROFILE dict body; everything else is
    preserved byte-identically (T-1443 prefix/suffix contract).

    Source-owned keys (interval_notifs) keep their symbolic form while the
    baked value is still the canonical preset:
    `from fastprompter.core.interval_presets import DAYPART_CHIME_RULES`
    `_INTERVAL_NOTIFS_DEFAULT = copy.deepcopy(DAYPART_CHIME_RULES)`
    `"interval_notifs": _INTERVAL_NOTIFS_DEFAULT,`

    A source-owned key whose baked value DIVERGED from that preset (the
    sanitizer deliberately passes an id-matched live customization through)
    is written as a literal instead: the symbol would silently ship the
    canonical preset and the round-trip check would reject the file, so the
    literal is the only lossless encoding of a baked customization
    (T-1457-B).
    """
    source_owned_symbols = {}
    for key in SOURCE_OWNED_KEYS:
        match = re.search(
            rf'["\']{re.escape(key)}["\']\s*:\s*([A-Za-z_][A-Za-z0-9_]*)',
            original_source)
        if match:
            source_owned_symbols[key] = match.group(1)

    prefix, interior, suffix = _split_profile_assignment(original_source)
    body_lines = []
    for key in sorted(new_profile.keys()):
        symbol = source_owned_symbols.get(key)
        if symbol is not None:
            denoted = _symbol_value_in_source(original_source, symbol)
            if denoted is not _SYMBOL_UNREADABLE \
                    and denoted == new_profile[key]:
                body_lines.append(f'    "{key}": {symbol},')
                continue
        val = new_profile[key]
        formatted_val = pprint.pformat(val, indent=4, width=100)
        if "\n" in formatted_val:
            indented_lines = formatted_val.splitlines()
            formatted_val = "\n".join(
                [indented_lines[0]] + ["    " + line
                                       for line in indented_lines[1:]])
        body_lines.append(f'    "{key}": {formatted_val},')

    new_content = (prefix + "\n" + "\n".join(body_lines) + "\n" + suffix)
    try:
        ast.parse(new_content)
    except SyntaxError as exc:
        raise BakePolicyError(
            f"candidate default_profile is not valid Python: {exc}") from exc
    return new_content


def _split_profile_assignment(source: str):
    """Split ``source`` at the ``DEFAULT_PROFILE = {...}`` dict literal.

    Returns ``(prefix, interior, suffix)`` where ``prefix`` ends with the
    opening ``{``, ``suffix`` starts with the closing ``}`` and ``interior``
    is everything between them. Brace matching is token-based so braces
    inside string values never confuse it.
    """
    lines = source.splitlines(keepends=True)
    line_start = [0]
    for line in lines:
        line_start.append(line_start[-1] + len(line))

    def _abs(pos):
        # tokenize columns are zero-based (PEP 626); rows are 1-based.
        return line_start[pos[0] - 1] + pos[1]

    open_end = close_start = None
    depth = 0
    seen_name = False
    try:
        tokens = list(tokenize.generate_tokens(
            io.StringIO(source).readline))
    except (AttributeError, tokenize.TokenError) as exc:
        raise BakePolicyError(
            f"candidate default_profile is not tokenizable: {exc}") from exc
    for tok in tokens:
        if not seen_name:
            if tok.type == tokenize.NAME and tok.string == "DEFAULT_PROFILE":
                seen_name = True
            continue
        if open_end is None:
            if tok.type == tokenize.OP and tok.string == "{":
                open_end = _abs(tok.end)
                depth = 1
            continue
        if tok.type == tokenize.OP:
            if tok.string == "{":
                depth += 1
            elif tok.string == "}":
                depth -= 1
                if depth == 0:
                    close_start = _abs(tok.start)
                    break
    if open_end is None or close_start is None:
        raise BakePolicyError(
            "candidate default_profile has no DEFAULT_PROFILE = {...} dict")
    return source[:open_end], source[open_end:close_start], source[close_start:]


def _reload_written_module(path: str) -> dict:
    """Independently compile the written file and return its DEFAULT_PROFILE.

    A loader with bytecode caching must never be used here: two bakes whose
    profile renders to the same byte size and filesystem timestamp granularity
    collide, and the stale ``__pycache__`` wins (measured: a round-trip that
    returned the PREVIOUS profile). Compiling the source directly makes every
    read genuinely independent of import machinery and pyc caches.
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SyntaxError(f"written profile is not UTF-8: {path}")
    module = types.ModuleType("fastprompter_bake_roundtrip_check")
    module.__file__ = path
    exec(compile(source, path, "exec"), module.__dict__)
    return module.DEFAULT_PROFILE


def _target_sha256(path: str) -> str:
    """SHA256 of the target's current bytes (the external-edit sentinel)."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _restore_original(target: str, original_raw: bytes) -> None:
    """Put the pre-bake bytes back after a failed round-trip check.

    The candidate already replaced the target by the time the independent
    reload runs, so a semantic mismatch must roll the exact original bytes
    back -- leaving the verified-wrong target on disk would silently change
    the shipped profile of every future build. The raw bytes are restored
    verbatim: re-encoding the read text would normalize line endings and
    fail the byte-identical contract.
    """
    directory = os.path.dirname(target) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=".default_profile_restore_", suffix=".py", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(original_raw)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def apply_bake_plan(plan: BakePlan, *, target_file: str | None = None,
                    dry_run: bool = False, timeout: float = _DEFAULT_LOCK_TIMEOUT) -> dict:
    """Atomically write a vetted plan and prove the written module round-trips.

    The write is a transaction: the target lock serializes every writer (any
    path alias) for the duration, the candidate temp file is removed on any
    failure, and an external non-cooperative edit of the target during the
    bake is detected by SHA and reported instead of being silently clobbered.
    """
    target = target_file or _TARGET_FILE
    if plan.refused:
        detail = ", ".join(f"{a.ref} [{a.status}]" for a in plan.refused)
        raise BakeRefusalError(f"sound assets cannot ship: {detail}")
    if not dry_run and is_frozen_build():
        raise BakeFrozenError(
            "Set Defaults from Current edits repository source; a packaged "
            "build has no durable semantics for it. Source development builds "
            "only.")

    if dry_run:
        return {
            "keys_count": len(plan.profile),
            "target_file": target,
            "dry_run": True,
            "profile": plan.profile,
            "summary": plan.summary(),
            "written_sha256": None,
            "roundtrip_equal": None,
        }

    with bake_transaction_lock(target, timeout=timeout):
        with open(target, "rb") as f:
            original_raw = f.read()
        try:
            original_source = original_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BakePolicyError(
                f"candidate default_profile is not valid UTF-8: {exc}") from exc
        sha_before = _target_sha256(target)
        new_source = format_default_profile_py(plan.profile, original_source)
        sha_after_format = _target_sha256(target)
        if sha_after_format != sha_before:
            raise BakeConcurrentModificationError(
                "target was modified concurrently during bake; refusing to "
                "clobber an external edit")

        written_sha = hashlib.sha256(new_source.encode("utf-8")).hexdigest()
        roundtrip_ok = None
        directory = os.path.dirname(target) or "."
        fd, tmp_path = tempfile.mkstemp(
            prefix=".default_profile_candidate_", suffix=".py", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_source)
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        # SRC-029 §13: never trust AST parsing alone -- build a fresh module
        # from ONLY the written file and compare every shippable key. The
        # bytes-on-disk check runs FIRST: an external edit swapped in while
        # we held the lock is reported, never evaluated as a round-trip
        # failure (and never clobbered).
        sha_after_replace = _target_sha256(target)
        if sha_after_replace != written_sha:
            raise BakeConcurrentModificationError(
                "target was modified concurrently during bake; the bytes on "
                "disk do not match the candidate that was written")
        try:
            reloaded = _reload_written_module(target)
        except BaseException:
            # A concurrent external edit may have landed while the reload
            # was in flight (inside the loader itself). Verify the bytes
            # still match the candidate before attributing the failure to
            # the round-trip check, and never clobber an external writer.
            if _target_sha256(target) != sha_after_replace:
                raise BakeConcurrentModificationError(
                    "target was modified concurrently during bake; the "
                    "bytes on disk do not match the candidate that was "
                    "written") from None
            raise
        if _target_sha256(target) != sha_after_replace:
            raise BakeConcurrentModificationError(
                "target was modified concurrently during bake; the bytes on "
                "disk do not match the candidate that was written")
        if reloaded != plan.profile:
            _restore_original(target, original_raw)
            raise RuntimeError(
                "written DEFAULT_PROFILE does not round-trip equal to the "
                "sanitized snapshot")
        roundtrip_ok = True

    return {
        "keys_count": len(plan.profile),
        "target_file": target,
        "dry_run": dry_run,
        "profile": plan.profile,
        "summary": plan.summary(),
        "written_sha256": written_sha,
        "roundtrip_equal": roundtrip_ok,
    }


def format_bake_preview(plan: BakePlan) -> str:
    """Human-readable dry-run summary for the dev button (SRC-029 §12)."""
    summary = plan.summary()
    lines = [
        f"SAFE VALUES COPIED:    {summary['safe_values_copied']}",
        f"RESET/NEUTRALIZED:     {summary['reset_neutralized']}",
        f"EXCLUDED PERSONAL:     {summary['excluded_personal']}",
        f"ASSET REFERENCES OK:   {summary['asset_references_verified']}",
        f"ASSET REFUSALS:        {summary['asset_refusals']}",
        f"WARNINGS:              {summary['warnings']}",
        "",
        "Changed preferences:",
    ]
    for key, before, after in plan.changed[:60]:
        lines.append(f"  {key}: {before!r} -> {after!r}")
    if len(plan.changed) > 60:
        lines.append(f"  ... and {len(plan.changed) - 60} more")
    if plan.refused:
        lines.append("")
        lines.append("REFUSED sound references (bake will not write):")
        for check in plan.refused:
            lines.append(f"  {check.ref} [{check.status}]")
    if plan.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in plan.warnings[:20]:
            lines.append(f"  {warning}")
    return "\n".join(lines)


def update_default_profile_from_state(state_or_data=None, profile_id: int = 1,
                                      dry_run: bool = False) -> dict:
    """Update `src/fastprompter/core/default_profile.py` from live state."""
    if state_or_data is None:
        from fastprompter.core.state import FastPrompterState
        state = FastPrompterState(profile_id=profile_id)
        data = state.data
    elif hasattr(state_or_data, "data"):
        data = state_or_data.data
    elif isinstance(state_or_data, dict):
        data = state_or_data
    else:
        raise TypeError(f"Unsupported state_or_data type: {type(state_or_data)}")

    plan = build_bake_plan(data)
    return apply_bake_plan(plan, dry_run=dry_run)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Bake live settings into repo DEFAULT_PROFILE.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the bake without writing")
    parser.add_argument("--json", action="store_true",
                        help="Structured summary instead of prose")
    parser.add_argument("--profile", type=int, default=1,
                        help="Profile ID to read settings from (default: 1)")
    args = parser.parse_args()

    from fastprompter.core.state import FastPrompterState
    state = FastPrompterState(profile_id=args.profile)
    plan = build_bake_plan(state.data)

    if args.json:
        payload = {"dry_run": args.dry_run, "ok": plan.ok,
                   "summary": plan.summary(),
                   "changed": [{"key": k, "from": b, "to": a}
                               for k, b, a in plan.changed]}
        try:
            result = apply_bake_plan(plan, dry_run=args.dry_run)
            payload["written_sha256"] = result["written_sha256"]
            payload["roundtrip_equal"] = result["roundtrip_equal"]
            payload["target_file"] = result["target_file"]
        except (BakeRefusalError, BakeFrozenError) as exc:
            payload["ok"] = False
            payload["error"] = str(exc)
        print(json.dumps(payload, indent=2, default=str))
        return 0 if payload.get("ok") else 1

    summary = plan.summary()
    print(f"Keys in bake:            {summary['keys_total']}")
    print(f"SAFE VALUES COPIED:      {summary['safe_values_copied']}")
    print(f"RESET/NEUTRALIZED:       {summary['reset_neutralized']}")
    print(f"EXCLUDED PERSONAL:       {summary['excluded_personal']}")
    print(f"ASSET REFERENCES OK:     {summary['asset_references_verified']}")
    print(f"ASSET REFUSALS:          {summary['asset_refusals']}")
    print(f"WARNINGS:                {summary['warnings']}")
    print("\nChanged preferences:")
    for key, before, after in plan.changed:
        print(f"  {key}: {before!r} -> {after!r}")
    if plan.refused:
        print("\nREFUSED sound references:")
        for check in plan.refused:
            print(f"  {check.ref} [{check.status}] {check.location}")
        print("Bake refused: no file written.")
        return 1

    try:
        result = apply_bake_plan(plan, dry_run=args.dry_run)
    except (BakeRefusalError, BakeFrozenError) as exc:
        print(f"Bake refused: {exc}")
        return 1
    mode = "[DRY-RUN] previewed" if args.dry_run else "wrote"
    print(f"\n{mode} {result['target_file']}")
    print(f"roundtrip_equal={result['roundtrip_equal']} "
          f"sha256={result['written_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
