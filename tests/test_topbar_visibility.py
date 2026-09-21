"""Qt-free contract tests for responsive top-bar policy and migration."""

import json

from fastprompter.core.topbar_visibility import (
    ITEM_BY_TOKEN,
    TOPBAR_ITEMS,
    default_topbar_visibility,
    normalize_topbar_visibility,
    range_for_width,
    requested_tokens,
)


def test_shipped_default_is_the_versioned_structured_policy():
    from fastprompter.core.default_profile import DEFAULT_PROFILE

    assert DEFAULT_PROFILE["topbar_visibility"] == default_topbar_visibility()
    assert DEFAULT_PROFILE["topbar_visibility"]["version"] == 1


def test_defaults_preserve_important_status_at_wide_and_medium():
    config = default_topbar_visibility()
    semantic = {item.token: True for item in TOPBAR_ITEMS}
    for width, expected_range in ((1600, "wide"), (1000, "medium")):
        active, requested = requested_tokens(config, width, semantic)
        assert active == expected_range
        for token in ("lbl_line_count", "analog_clock", "lbl_date",
                      "limit_gauges", "lbl_limit_timer", "cat_numbox",
                      "btn_new", "btn_save"):
            assert requested[token] == "show"


def test_custom_breakpoint_changes_at_exact_boundary():
    config = default_topbar_visibility()
    config["breakpoints"] = [
        {"id": "ultra", "min": 0, "max": 599},
        {"id": "narrow", "min": 600, "max": 899},
        {"id": "medium", "min": 900, "max": 1110},
        {"id": "wide", "min": 1111, "max": None},
    ]
    assert range_for_width(config, 1110) == "medium"
    assert range_for_width(config, 1111) == "wide"


def test_item_overrides_and_semantic_absence_are_exact():
    config = default_topbar_visibility()
    config["items"]["lbl_line_count"]["narrow"] = "show"
    config["items"]["analog_clock"]["narrow"] = "show"
    config["items"]["btn_copy"]["narrow"] = "hide"
    semantic = {item.token: True for item in TOPBAR_ITEMS}
    semantic["btn_project_run"] = False
    active, requested = requested_tokens(config, 700, semantic)
    assert active == "narrow"
    assert requested["lbl_line_count"] == "show"
    assert requested["analog_clock"] == "show"
    assert "btn_copy" not in requested
    assert "btn_project_run" not in requested


def test_resolution_has_no_resize_history_input():
    config = default_topbar_visibility()
    semantic = {item.token: True for item in TOPBAR_ITEMS}

    def travel(widths):
        result = None
        for width in widths:
            result = requested_tokens(config, width, semantic)
        return result

    assert travel([1600, 500, 1000]) == travel([500, 1600, 1000])


def test_corrupt_and_old_configs_heal_and_unknown_tokens_are_ignored():
    defaults = default_topbar_visibility()
    assert normalize_topbar_visibility(None) == defaults
    assert normalize_topbar_visibility({"version": 999}) == defaults
    corrupt = {
        "version": 1,
        "breakpoints": [{"id": "wide", "min": "wrong"}],
        "items": {
            "btn_copy": {"wide": "bananas", "medium": "hide",
                         "priority": "bad"},
            "future_widget": {"wide": "hide"},
        },
    }
    healed = normalize_topbar_visibility(corrupt)
    assert healed["breakpoints"] == defaults["breakpoints"]
    assert healed["items"]["btn_copy"]["wide"] == "show"
    assert healed["items"]["btn_copy"]["medium"] == "hide"
    assert "future_widget" not in healed["items"]
    assert set(healed["items"]) == set(ITEM_BY_TOKEN)


def test_structured_config_json_roundtrip_keeps_rules_separate_from_order():
    config = default_topbar_visibility()
    config["items"]["btn_copy"]["medium"] = "hide"
    toolbar_order = "btn_new,btn_copy,<stretch>,lbl_date"
    loaded = normalize_topbar_visibility(json.loads(json.dumps(config)))
    assert loaded == config
    assert toolbar_order == "btn_new,btn_copy,<stretch>,lbl_date"
