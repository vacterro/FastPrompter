"""SetDefaultFromCurrent: Developer utility to stamp live settings as repo defaults.

Extracts all current UI settings, themes, sounds, interval notifications,
window presets, timer configurations, typography, and states from the active
live database/state and writes them directly to `DEFAULT_PROFILE` in
`src/fastprompter/core/default_profile.py`.

Explicitly excludes all personal user content:
- User text, notes, and silos text
- Personal timers and queues
- Machine-specific filesystem paths
- Window absolute screen positions
- Search and undo history

Usage:
    uv run python tools/set_default_from_current.py [--dry-run] [--profile <id>]
"""

import ast
import json
import os
import pprint
import re
import sys

# Ensure repo root and src/ are in sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

_TARGET_FILE = os.path.join(_SRC_DIR, "fastprompter", "core", "default_profile.py")

# Absolute DENYLIST: keys that hold personal content, text, or machine-specific data.
# These MUST NEVER be copied into the shipped DEFAULT_PROFILE.
DENYLIST = {
    # Personal text and silo content
    "temp_presets",
    "temp_presets_all",
    "silo_text",
    "snippets",
    "text",
    "content",
    "history",
    "undo_history",
    "redo_history",
    # Personal folders and silo structures
    "silos",
    "silo_category",
    "silo_folders",
    "silo_folders_all",
    "silo_folders_order",
    "silo_children",
    "silo_children_all",
    "silo_collapsed",
    "silo_collapsed_all",
    "silo_colors",
    "silo_colors_all",
    "silo_last_edited",
    "silo_last_edited_all",
    "silo_gaps",
    "silo_gaps_all",
    "silo_gap_names",
    "silo_gap_names_all",
    "silo_selected",
    "silo_selected_all",
    "silo_session_all",
    "silo_ticked",
    "silo_ticked_all",
    "silo_type_all",
    "silo_types",
    "silo_view_state_all",
    "trash_text_folder",
    "file_tags",
    "silo_home_states",
    "silo_done_marks",
    # Personal timers and queues
    "timers",
    "watcher_queues",
    "watcher_queues_all",
    "watcher_skill",
    # Archive content
    "archive_folders",
    "archive_folders_all",
    "archive_temp_presets",
    "archive_silos",
    "arc_silo_page",
    # History and searches
    "recent_search_terms",
    "recent_replace_terms",
    "recent_files",
    "search_history",
    "search_index",
    # Machine-specific paths and sync state
    "sync_path",
    "files_root_folder",
    "window_geometry",
    "window_x",
    "window_y",
}

# Neutral resets: keys that belong in DEFAULT_PROFILE but must be neutral / empty
# rather than taking local paths or discovered accounts from the current machine.
RESET_KEYS = {
    "limit_antigravity_dir": "",
    "limit_codex_homes": "",
    "limit_notifications": {},
    "limit_notification_state": {},
    "limit_gauges_hidden_accounts": [],
    "limit_gauges_account_labels": {},
    "limit_gauges_account_names": {},
    "limit_gauges_account_order": [],
    "project_sync": {},
    "project_sync_all": {},
    "project_sync_map": {},
    "project_sync_map_all": {},
    "silo_links": {},
    "silo_links_all": {},
    "archive_project_paths": {},
    "archive_project_paths_all": {},
    "silo_project_paths": {},
    "silo_project_paths_all": {},
    "typo_user_words": [],
    "hide_extra": "True",
    "search_visible": "False",
}


def _scrub_custom_colors(value, base_value):
    """custom_colors is an unconditional OVERLAY on the active theme.

    Stamping a key a theme already owns pins the current palette onto every
    theme (pick Vintage Classic and the background stays golden), so only the
    extras no theme defines may ship. Guarded by
    tests/test_state.py::test_custom_colors_never_shadow_a_theme.
    """
    if not isinstance(value, dict):
        return base_value
    from fastprompter.theme.themes import THEMES
    theme_keys = set()
    for spec in THEMES.values():
        theme_keys |= set((spec.get("raw_colors") or {}).keys())
    return {k: v for k, v in sorted(value.items()) if k not in theme_keys}


# key -> sanitizer(live_value, base_value). Applied to a value taken from the
# live profile, so a session value can never ship in a shape the shipped
# defaults are not allowed to carry.
SANITIZERS = {
    "custom_colors": _scrub_custom_colors,
}


def _coerce_to_base_type(value, base_value):
    """Keep the shipped default's TYPE.

    Settings round-trip through SQLite as text, so the live dict holds
    ``font_size='10'`` where the shipped default is the int ``10`` that every
    consumer (and the default-shape test) expects. Stamping the string back
    silently changes the type of a shipped default.
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


def extract_defaults_from_data(source_data: dict, base_defaults: dict = None) -> dict:
    """Extract a clean DEFAULT_PROFILE dict from a live data dictionary.

    Uses base_defaults as the authoritative schema of shipped configuration keys.
    Any personal content, private notes, silos, and machine paths are strictly
    excluded or reset.
    """
    if base_defaults is None:
        from fastprompter.core.default_profile import DEFAULT_PROFILE as _BASE
        base_defaults = _BASE

    result = {}
    for key in sorted(base_defaults.keys()):
        if key in DENYLIST:
            result[key] = base_defaults[key]
            continue

        if key in RESET_KEYS:
            result[key] = RESET_KEYS[key]
            continue

        if key in source_data:
            value = source_data[key]
            sanitize = SANITIZERS.get(key)
            if sanitize is not None:
                value = sanitize(value, base_defaults[key])
            result[key] = _coerce_to_base_type(value, base_defaults[key])
        else:
            result[key] = base_defaults[key]

    return result


def format_default_profile_py(new_profile: dict, original_source: str) -> str:
    """Format the default_profile.py module with new_profile dict while preserving docstring."""
    # Extract module docstring
    docstring_match = re.search(r'^(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')', original_source)
    docstring = docstring_match.group(0) if docstring_match else '"""Shipped defaults — the baked "current configuration"."""'

    # Build formatted dict representation
    lines = [docstring, "", "DEFAULT_PROFILE = {"]
    for key in sorted(new_profile.keys()):
        val = new_profile[key]
        formatted_val = pprint.pformat(val, indent=4, width=100)
        # If multi-line, indent subsequent lines by 4 spaces
        if "\n" in formatted_val:
            indented_lines = formatted_val.splitlines()
            formatted_val = "\n".join([indented_lines[0]] + ["    " + line for line in indented_lines[1:]])
        lines.append(f'    "{key}": {formatted_val},')
    lines.append("}")
    lines.append("")

    new_content = "\n".join(lines)
    # Validate syntax
    ast.parse(new_content)
    return new_content


def update_default_profile_from_state(state_or_data=None, profile_id: int = 1, dry_run: bool = False) -> dict:
    """Update `src/fastprompter/core/default_profile.py` from live state or data."""
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

    with open(_TARGET_FILE, "r", encoding="utf-8") as f:
        original_source = f.read()

    from fastprompter.core.default_profile import DEFAULT_PROFILE as base_defaults
    new_profile = extract_defaults_from_data(data, base_defaults)
    new_source = format_default_profile_py(new_profile, original_source)

    if not dry_run:
        with open(_TARGET_FILE, "w", encoding="utf-8") as f:
            f.write(new_source)

    return {
        "keys_count": len(new_profile),
        "target_file": _TARGET_FILE,
        "dry_run": dry_run,
        "profile": new_profile,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stamp live settings into repo DEFAULT_PROFILE.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to file")
    parser.add_argument("--profile", type=int, default=1, help="Profile ID to read settings from (default: 1)")
    args = parser.parse_args()

    print(f"Reading live settings from profile {args.profile}...")
    res = update_default_profile_from_state(profile_id=args.profile, dry_run=args.dry_run)

    mode_label = "[DRY-RUN] Would update" if args.dry_run else "Successfully updated"
    print(f"{mode_label} {res['target_file']}")
    print(f"Total keys stamped: {res['keys_count']}")

    # Print summary of key settings
    p = res["profile"]
    print("\nStamped Settings Highlights:")
    print(f"  Theme:               {p.get('theme')}")
    print(f"  UI Scale:            {p.get('ui_scale')}")
    print(f"  Sound UI:            {p.get('sound_ui')} (Volume: {p.get('sound_volume')})")
    print(f"  Always on Top:       {p.get('always_on_top')}")
    print(f"  Hide Extra:          {p.get('hide_extra')}")
    print(f"  Interval Notifs:     {len(p.get('interval_notifs', []))} configured")
    print(f"  Window Presets:      {len(p.get('window_presets', []))} slots")
    print(f"  Sound Quick Bar:     {len(p.get('sound_quick_bar', []))} slots")
    print("\nVerified: All personal text, silos, and private paths were excluded.")


if __name__ == "__main__":
    main()
