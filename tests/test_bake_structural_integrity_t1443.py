"""T-1443: Structural integrity and source-owned code preservation for default profile bake.

Covers:
1. Prefix before DEFAULT_PROFILE remains byte-identical.
2. Suffix after DEFAULT_PROFILE remains byte-identical.
3. Ordinary COPY value is updated.
4. NEUTRAL behaviour unchanged.
5. EXCLUDED behaviour unchanged.
6. interval_notifs is SOURCE_OWNED.
7. SOURCE_OWNED policy sets disjoint from all other sets.
8. Real default_profile.py keeps DAYPART_CHIME_RULES import, _INTERVAL_NOTIFS_DEFAULT, and symbolic mapping.
9. Conflicting live interval_notifs cannot replace canonical default.
10. Effective reloaded DEFAULT_PROFILE equals plan.profile.
11. Candidate semantic failure leaves real target byte-identical.
12. Concurrent target modification causes BakeConcurrentModificationError and preserves external bytes.
13. Syntax-invalid candidate cannot touch target.
14. Dry-run remains write-free.
"""

import hashlib
import pathlib

import pytest

from fastprompter.core import default_profile
from fastprompter.core.interval_presets import DAYPART_CHIME_RULES
from tools import set_default_from_current as bake

_REAL_DEFAULT_PROFILE_PATH = pathlib.Path(default_profile.__file__).resolve()

_SAMPLE_SOURCE = (
    '"""Module header docstring with copyright (C) 2026."""\n'
    "\n"
    "import copy\n"
    "import sys\n"
    "from fastprompter.core.interval_presets import DAYPART_CHIME_RULES\n"
    "\n"
    "# Leading helper and declaration\n"
    "def _helper():\n"
    "    return 42\n"
    "\n"
    "_INTERVAL_NOTIFS_DEFAULT = copy.deepcopy(DAYPART_CHIME_RULES)\n"
    "\n"
    "DEFAULT_PROFILE = {\n"
    '    "altw_bullet_char": "•",\n'
    '    "interval_notifs": _INTERVAL_NOTIFS_DEFAULT,\n'
    '    "language": "EST",\n'
    '    "sound_volume": "0.09",\n'
    "}\n"
    "\n"
    "# Suffix comments and exports\n"
    "def get_default_profile():\n"
    "    return copy.deepcopy(DEFAULT_PROFILE)\n"
    "\n"
    '__all__ = ["DEFAULT_PROFILE", "get_default_profile"]\n'
)


def _split_sample_around_assignment(source: str):
    marker_start = "DEFAULT_PROFILE = {"
    marker_end = "}\n\n# Suffix"
    idx_start = source.index(marker_start)
    idx_end = source.index(marker_end) + 2  # include closing bracket and newline
    prefix = source[:idx_start]
    suffix = source[idx_end:]
    return prefix, suffix


def test_1_prefix_before_default_profile_remains_byte_identical(tmp_path):
    target = tmp_path / "default_profile.py"
    target.write_text(_SAMPLE_SOURCE, encoding="utf-8")
    prefix_expected, _ = _split_sample_around_assignment(_SAMPLE_SOURCE)

    new_profile = {
        "altw_bullet_char": "-",
        "interval_notifs": DAYPART_CHIME_RULES,
        "language": "EN",
        "sound_volume": "0.50",
    }
    formatted = bake.format_default_profile_py(new_profile, _SAMPLE_SOURCE)
    prefix_actual, _ = _split_sample_around_assignment(formatted)

    assert prefix_actual == prefix_expected
    assert "_helper():" in prefix_actual
    assert "_INTERVAL_NOTIFS_DEFAULT = copy.deepcopy(DAYPART_CHIME_RULES)" in prefix_actual


def test_2_suffix_after_default_profile_remains_byte_identical(tmp_path):
    _, suffix_expected = _split_sample_around_assignment(_SAMPLE_SOURCE)

    new_profile = {
        "altw_bullet_char": "-",
        "interval_notifs": DAYPART_CHIME_RULES,
        "language": "EN",
        "sound_volume": "0.50",
    }
    formatted = bake.format_default_profile_py(new_profile, _SAMPLE_SOURCE)
    _, suffix_actual = _split_sample_around_assignment(formatted)

    assert suffix_actual == suffix_expected
    assert "def get_default_profile():" in suffix_actual
    assert '__all__ = ["DEFAULT_PROFILE", "get_default_profile"]' in suffix_actual


def test_3_ordinary_copy_value_is_updated(tmp_path):
    target = tmp_path / "default_profile.py"
    target.write_text(_REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    live["sound_volume"] = "0.77"
    live["sidebar_right"] = "False"

    plan = bake.build_bake_plan(live, check_assets=False)
    assert plan.profile["sound_volume"] == "0.77"
    assert plan.profile["sidebar_right"] == "False"

    result = bake.apply_bake_plan(plan, target_file=str(target))
    assert result["roundtrip_equal"] is True

    reloaded = bake._reload_written_module(str(target))
    assert reloaded["sound_volume"] == "0.77"
    assert reloaded["sidebar_right"] == "False"


def test_4_neutral_behaviour_unchanged():
    live = dict(default_profile.DEFAULT_PROFILE)
    live["image_viewer_mode"] = "custom"
    live["image_viewer_path"] = r"C:\Users\secret\viewer.exe"
    live["limit_claude_homes"] = r"C:\Users\secret\claude"

    plan = bake.build_bake_plan(live, check_assets=False)
    assert plan.profile["image_viewer_mode"] == "system"
    assert plan.profile["image_viewer_path"] == ""
    assert plan.profile["limit_claude_homes"] == ""


def test_5_excluded_behaviour_unchanged():
    live = dict(default_profile.DEFAULT_PROFILE)
    live["text"] = "Sensitive user document"
    live["timers"] = [{"id": "t1"}]
    live["window_geometry"] = "0,0,1920,1080"
    live["window_presets_capture_state"] = "MODIFIED_LIVE_VALUE"

    plan = bake.build_bake_plan(live, check_assets=False)
    assert "text" not in plan.profile
    assert "timers" not in plan.profile
    assert "window_geometry" not in plan.profile
    assert (
        plan.profile["window_presets_capture_state"]
        == default_profile.DEFAULT_PROFILE["window_presets_capture_state"]
    )



def test_6_interval_notifs_is_source_owned():
    assert "interval_notifs" in bake.SOURCE_OWNED_KEYS
    assert bake.classify_key("interval_notifs") == "source_owned"


def test_7_source_owned_policy_sets_disjoint_from_all_other_sets():
    assert bake.SOURCE_OWNED_KEYS.isdisjoint(bake.COPY_KEYS)
    assert bake.SOURCE_OWNED_KEYS.isdisjoint(set(bake.NEUTRAL_KEYS.keys()))
    assert bake.SOURCE_OWNED_KEYS.isdisjoint(bake.EXCLUDED_KEYS)
    assert bake.SOURCE_OWNED_KEYS.isdisjoint(bake.DROP_KEYS)
    conflicts = bake.policy_conflicts()
    assert conflicts == []



def test_8_real_default_profile_py_keeps_chime_rules_import_and_symbolic_mapping(tmp_path):
    real_content = _REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8")
    target = tmp_path / "default_profile.py"
    target.write_text(real_content, encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    live["sound_volume"] = "0.55"
    plan = bake.build_bake_plan(live, check_assets=False)
    bake.apply_bake_plan(plan, target_file=str(target))

    updated_content = target.read_text(encoding="utf-8")
    assert "from fastprompter.core.interval_presets import DAYPART_CHIME_RULES" in updated_content
    assert "_INTERVAL_NOTIFS_DEFAULT = copy.deepcopy(DAYPART_CHIME_RULES)" in updated_content
    assert '"interval_notifs": _INTERVAL_NOTIFS_DEFAULT,' in updated_content


def test_9_conflicting_live_interval_notifs_cannot_replace_canonical_default(tmp_path):
    target = tmp_path / "default_profile.py"
    target.write_text(_REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    live["interval_notifs"] = [
        {"id": "hacked_chime", "name": "Hack", "minutes": 1, "enabled": False}
    ]

    plan = bake.build_bake_plan(live, check_assets=False)
    assert plan.profile["interval_notifs"] == DAYPART_CHIME_RULES

    bake.apply_bake_plan(plan, target_file=str(target))
    reloaded = bake._reload_written_module(str(target))
    assert reloaded["interval_notifs"] == DAYPART_CHIME_RULES

    updated_content = target.read_text(encoding="utf-8")
    assert "hacked_chime" not in updated_content
    assert '"interval_notifs": _INTERVAL_NOTIFS_DEFAULT,' in updated_content


def test_10_effective_reloaded_default_profile_equals_plan_profile(tmp_path):
    target = tmp_path / "default_profile.py"
    target.write_text(_REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    plan = bake.build_bake_plan(live, check_assets=False)
    result = bake.apply_bake_plan(plan, target_file=str(target))

    assert result["roundtrip_equal"] is True
    reloaded = bake._reload_written_module(str(target))
    assert reloaded == plan.profile


def test_11_candidate_semantic_failure_leaves_real_target_byte_identical(tmp_path, monkeypatch):
    target = tmp_path / "default_profile.py"
    target.write_text(_REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    live = dict(default_profile.DEFAULT_PROFILE)
    plan = bake.build_bake_plan(live, check_assets=False)

    # Simulate semantic mismatch during candidate reload
    def _fake_reload(path):
        bad = dict(plan.profile)
        bad["sound_volume"] = "corrupted_semantic_value"
        return bad

    monkeypatch.setattr(bake, "_reload_written_module", _fake_reload)

    with pytest.raises(RuntimeError, match="does not round-trip equal"):
        bake.apply_bake_plan(plan, target_file=str(target))

    after_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert after_sha == before_sha


def test_12_concurrent_target_modification_causes_error_and_preserves_external_bytes(tmp_path, monkeypatch):
    target = tmp_path / "default_profile.py"
    target.write_text(_REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    plan = bake.build_bake_plan(live, check_assets=False)

    orig_reload = bake._reload_written_module

    def _simulated_concurrent_edit(path):
        target.write_text("# CONCURRENT EXTERNAL EDIT\n", encoding="utf-8")
        return orig_reload(path)

    monkeypatch.setattr(bake, "_reload_written_module", _simulated_concurrent_edit)

    with pytest.raises(bake.BakeConcurrentModificationError, match="modified concurrently"):
        bake.apply_bake_plan(plan, target_file=str(target))

    assert target.read_text(encoding="utf-8") == "# CONCURRENT EXTERNAL EDIT\n"


def test_13_syntax_invalid_candidate_cannot_touch_target(tmp_path):
    target = tmp_path / "default_profile.py"
    malformed_source = '"""broken"""\n\nDEFAULT_PROFILE = (not a dict)\n'
    target.write_text(malformed_source, encoding="utf-8")

    live = dict(default_profile.DEFAULT_PROFILE)
    plan = bake.build_bake_plan(live, check_assets=False)

    with pytest.raises(bake.BakePolicyError):
        bake.apply_bake_plan(plan, target_file=str(target))

    assert target.read_text(encoding="utf-8") == malformed_source


def test_14_dry_run_remains_write_free(tmp_path):
    target = tmp_path / "default_profile.py"
    initial_content = _REAL_DEFAULT_PROFILE_PATH.read_text(encoding="utf-8")
    target.write_text(initial_content, encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    live = dict(default_profile.DEFAULT_PROFILE)
    live["sound_volume"] = "0.99"
    plan = bake.build_bake_plan(live, check_assets=False)

    result = bake.apply_bake_plan(plan, target_file=str(target), dry_run=True)
    assert result["dry_run"] is True
    assert result["roundtrip_equal"] is None

    after_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert after_sha == before_sha
