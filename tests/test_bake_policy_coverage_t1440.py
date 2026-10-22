"""T-1440: bake policy must cover the PERSISTED-setting universe.

The pre-existing invariant only checked ``DEFAULT_PROFILE``. Runtime/profile
state that is persisted through the structured codecs but never shipped in the
base profile (``trash_consumed``, ``silo_bundle_meta_retry``,
``silo_pack_coverage``) therefore escaped the fail-closed gate and surfaced as
``Update Failed / unclassified settings present: silo_pack_coverage`` in the
Set Defaults from Current dialog.

These tests pin the actual contract: every key the state layer persists must be
explicitly classified by the bake policy, and runtime-only payloads must never
leak into the baked profile while a genuinely new unknown key still fails
closed.
"""

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import _JSON_SETTINGS, _STRUCTURED_CODECS
from tools.set_default_from_current import (
    EXCLUDED_KEYS,
    BakePolicyError,
    assert_policy_covers,
    build_bake_plan,
    policy_conflicts,
)

# The three keys this ticket closes: runtime/profile-owned state that must be
# excluded from a repository default bake, never copied and never neutralized
# into a shipped empty structure.
RUNTIME_EXCLUDED = (
    "trash_consumed",
    "silo_bundle_meta_retry",
    "silo_pack_coverage",
)


class TestPersistedUniverseIsClassified:
    def test_all_json_settings_keys_are_classified(self):
        assert assert_policy_covers(_JSON_SETTINGS) == []

    def test_codec_registry_matches_json_settings(self):
        # The bake policy must cover the SAME universe the codec pins; if these
        # two registries ever diverge, coverage of one proves nothing.
        assert set(_STRUCTURED_CODECS) == set(_JSON_SETTINGS)
        assert assert_policy_covers(_STRUCTURED_CODECS.keys()) == []

    def test_policy_conflicts_remain_empty(self):
        assert policy_conflicts() == []

    def test_runtime_keys_are_excluded_not_copied(self):
        for key in RUNTIME_EXCLUDED:
            assert key in EXCLUDED_KEYS, key


class TestRuntimePayloadsDoNotBake:
    def test_silo_pack_coverage_no_longer_raises(self):
        source = {
            "theme": "Dark Golden Vintage",
            "silo_pack_coverage": {
                "3": {"entries": [{"ts": 1, "archive": "a.zip"}], "path": "x"},
            },
        }
        plan = build_bake_plan(source, base_defaults={}, check_assets=False)
        assert plan.ok

    def test_silo_pack_coverage_absent_from_baked_profile(self):
        payload = {"7": {"coverage": 0.5, "events": ["packed", "archived"]}}
        plan = build_bake_plan(
            {"silo_pack_coverage": payload},
            base_defaults={}, check_assets=False)
        assert "silo_pack_coverage" not in plan.profile

    def test_silo_bundle_meta_retry_payload_does_not_leak(self):
        payload = {"4": {"stage": "metadata", "pending": ["a/", "b/"]}}
        plan = build_bake_plan(
            {"theme": "Golden", "silo_bundle_meta_retry": payload},
            base_defaults={}, check_assets=False)
        assert "silo_bundle_meta_retry" not in plan.profile

    def test_trash_consumed_markers_do_not_leak(self):
        payload = {"secret-note.md": True, "budget.md": True}
        plan = build_bake_plan(
            {"trash_consumed": payload},
            base_defaults={}, check_assets=False)
        assert "trash_consumed" not in plan.profile

    def test_mixed_bake_succeeds_and_omits_all_runtime_state(self):
        source = {
            "theme": "Dark Golden Vintage",
            "sound_volume": "0.25",
            "silo_pack_coverage": {"1": {"events": ["a"]}},
            "silo_bundle_meta_retry": {"1": {"stage": "meta"}},
            "trash_consumed": {"note.md": True},
        }
        plan = build_bake_plan(source, base_defaults={}, check_assets=False)

        # normal preference still bakes
        assert plan.profile["theme"] == "Dark Golden Vintage"
        assert plan.profile["sound_volume"] == "0.25"
        # runtime state is nowhere in the candidate profile
        blob = repr(plan.profile)
        for key in RUNTIME_EXCLUDED:
            assert key not in plan.profile
        assert "silo_pack_coverage" not in blob
        assert "events" not in blob


class TestFailClosedStillHolds:
    def test_brand_new_unknown_key_still_raises(self):
        with pytest.raises(BakePolicyError) as exc:
            build_bake_plan(
                {"brand_new_setting_zzz": "x"},
                base_defaults={}, check_assets=False)
        assert "brand_new_setting_zzz" in str(exc.value)

    def test_unknown_key_is_reported_by_assert_policy_covers(self):
        assert assert_policy_covers(["brand_new_setting_zzz"]) == [
            "brand_new_setting_zzz"]


def test_state_module_json_settings_is_the_test_source_of_truth():
    # Guards the import path this module relies on: the canonical registry is
    # state_mod._JSON_SETTINGS (a tuple), not a locally re-copied list.
    assert state_mod._JSON_SETTINGS is _JSON_SETTINGS
    assert isinstance(_JSON_SETTINGS, tuple)
