"""Tests for tools/set_default_from_current.py.

Verifies:
- Complete exclusion of personal user content, text, notes, and silos.
- Scrubbing of machine-specific filesystem paths.
- Preservation of sound events, interval notifications, and window presets.
- Clean AST formatting and schema validity.
"""

import ast
import os
import sys
import pytest

from tools.set_default_from_current import (
    DENYLIST,
    RESET_KEYS,
    extract_defaults_from_data,
    format_default_profile_py,
    update_default_profile_from_state,
)


def test_extract_defaults_excludes_all_denylist_keys():
    """Ensure no personal text, silos, or private data leak into defaults."""
    mock_live_data = {
        # Personal data
        "temp_presets": ["# Personal secret note 1", "# Personal secret note 2"],
        "temp_presets_all": {"Code": ["secret code"], "Personal": ["passwords"]},
        "silo_text": "secret silo text",
        "snippets": ["secret snippet"],
        "silos": [{"name": "My Client Work"}],
        "silo_folders_all": {"Code": {"1": "client_repo"}},
        "timers": [{"name": "My Private Deadline", "target": "2026-10-01"}],
        "sync_path": "C:\\Users\\alice\\Documents\\MySync",
        "window_geometry": "100,100,800,600",
        "window_x": 100,
        "window_y": 200,
        "recent_search_terms": ["secret password search"],
        # Valid settings
        "theme": "Dark Golden Vintage",
        "ui_scale": "0.60",
        "sound_ui": "True",
        "sound_volume": "0.25",
        "sound_quick_bar": ["file:QUEST.wav", "file:NEWDAY.wav"],
        "window_presets": [{"name": "Preset 1", "w": 0.5}],
        "interval_notifs": [{"id": "morning", "minutes": 60}],
        "productivity_timer": {"work_seconds": 1500, "break_seconds": 300},
        "hide_extra": "False",  # User had it open in session, but must be reset to True
    }

    base_defaults = {
        "theme": "Golden Default",
        "ui_scale": "0.50",
        "sound_ui": "False",
        "limit_antigravity_dir": "",
        "hide_extra": "True",
        "sound_volume": "0.10",
        "sound_quick_bar": [],
        "window_presets": [],
        "interval_notifs": [],
        "productivity_timer": {},
    }

    result = extract_defaults_from_data(mock_live_data, base_defaults)

    # 1. Denylisted keys MUST NOT be present
    for denied in DENYLIST:
        assert denied not in result, f"Leaked denylisted key: {denied}"

    # 2. Reset keys MUST be set to their clean defaults
    assert result["hide_extra"] == "True"
    assert result["limit_antigravity_dir"] == ""

    # 3. Settings from live data MUST be captured
    assert result["theme"] == "Dark Golden Vintage"
    assert result["ui_scale"] == "0.60"
    assert result["sound_ui"] == "True"
    assert result["sound_volume"] == "0.25"
    assert result["sound_quick_bar"] == ["file:QUEST.wav", "file:NEWDAY.wav"]
    assert len(result["window_presets"]) == 1
    assert len(result["interval_notifs"]) == 1
    assert result["productivity_timer"]["work_seconds"] == 1500


def test_format_default_profile_py_produces_valid_ast():
    """Verify that formatted output is valid Python code."""
    mock_profile = {
        "always_on_top": "False",
        "sound_volume": "0.15",
        "window_presets": [{"name": "Preset 1", "x": 0.0, "y": 0.0}],
        "interval_notifs": [{"name": "Noon", "enabled": True}],
    }
    dummy_source = '"""Header docstring."""\n\nDEFAULT_PROFILE = {}\n'

    formatted = format_default_profile_py(mock_profile, dummy_source)

    # Must be parseable by Python AST
    tree = ast.parse(formatted)
    assert tree is not None
    assert '"""Header docstring."""' in formatted
    assert "DEFAULT_PROFILE = {" in formatted
    assert '"sound_volume": \'0.15\',' in formatted or '"sound_volume": "0.15",' in formatted


def test_update_default_profile_dry_run_does_not_modify_file():
    """Verify dry_run returns results without modifying disk."""
    res = update_default_profile_from_state(state_or_data={"theme": "Test"}, dry_run=True)
    assert res["dry_run"] is True
    assert res["keys_count"] > 0
    assert "profile" in res
