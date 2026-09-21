"""T-1284 / audit/10 CORE-004: one canonical cross-store dependency enumerator
for managed ``user:`` sound refs.

Deletion surfaces used to scan only a local subset of consumers, so a Remove
could leave saved presets / ambience rules pointing at a vanished file with no
warning. ``sound_dependencies.dependencies_for_ref`` is now the ONE enumerator
both Problip and the Audio Hub call.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core import sound_dependencies  # noqa: E402

REF = "user:imported/custom.wav"


def test_events_and_pool_are_reported():
    data = {"sound_events": {"click": {"file": REF},
                             "hover": {"file": "other.wav"}}}
    deps = sound_dependencies.dependencies_for_ref(
        REF, data=data, problip_sound_ids=[REF, "tick"],
        include_persistent_stores=False)
    assert deps.problip_pool is True
    assert deps.events == ["click"]
    assert deps.any() is True
    assert deps.is_unknown() is False


def test_unreferenced_ref_reports_nothing():
    deps = sound_dependencies.dependencies_for_ref(
        REF, data={"sound_events": {}}, problip_sound_ids=["tick"],
        include_persistent_stores=False)
    assert deps.any() is False
    assert deps.events == []


def test_unreadable_store_is_unknown_not_empty(monkeypatch):
    """A store that cannot be opened must be reported, never silently empty."""
    def boom(*a, **k):
        raise OSError("db locked")

    monkeypatch.setattr("fastprompter.core.sound_presets.PresetStore", boom)
    monkeypatch.setattr("fastprompter.core.ambience_store.AmbienceStore", boom)
    deps = sound_dependencies.dependencies_for_ref(
        REF, data={"sound_events": {}}, problip_sound_ids=[],
        include_persistent_stores=True)
    assert deps.is_unknown() is True
    assert "presets" in deps.impact_unknown
    assert "ambience" in deps.impact_unknown


def test_presets_and_ambience_are_enumerated(tmp_path, monkeypatch):
    """A ref used by a saved preset and a saved ambience rule is fully listed."""

    from fastprompter.core.ambience_engine import AmbienceRule
    from fastprompter.core.ambience_store import AmbienceStore
    from fastprompter.core.sound_presets import PresetStore

    preset_db = tmp_path / "audio.db"
    ambience_db = tmp_path / "ambience.db"
    store = PresetStore(str(preset_db))
    store.upsert({
        "schema_version": 1, "id": "p1", "name": "P1",
        "events": {"click": {"file": REF}},
    }, user_override=False)
    amb = AmbienceStore(str(ambience_db))
    amb.save_rules([AmbienceRule(id="r1", name="R1", sound_ref=REF)])

    monkeypatch.setattr(
        "fastprompter.core.sound_presets.PresetStore",
        lambda: PresetStore(str(preset_db)))
    monkeypatch.setattr(
        "fastprompter.core.ambience_store.AmbienceStore",
        lambda: AmbienceStore(str(ambience_db)))

    deps = sound_dependencies.dependencies_for_ref(
        REF, data={"sound_events": {}}, problip_sound_ids=None,
        include_persistent_stores=True)
    assert "p1" in deps.presets
    assert "r1" in deps.ambience_rules
    assert deps.is_unknown() is False
