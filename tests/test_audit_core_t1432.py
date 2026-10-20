"""T-1432 (SRC-093) core-cluster regressions: CORE-002 and CORE-003.

CORE-003: ``silo_pack_coverage`` must round-trip through SQLite as a JSON
dict, so ``CoverageStore.from_dict`` sees a dict after a restart. A row an
older build wrote with ``str(dict)`` (single-quoted) must recover through
``ast.literal_eval``; the next save rewrites canonical JSON.

CORE-002: a mutated persisted silo setting is silently dropped unless the
settings domain is marked dirty — with a clean generation the save takes the
partial/``ui_settings`` path and never re-encodes a key that was not handed to
it. ``main._silo_save_settings`` is the one place every bundle-settings writer
now routes through; the state-layer contract it relies on is proven here.
"""

import json

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.silo_coverage import CoverageStore, create_bundle_coverage_event
from fastprompter.core.state import FastPrompterState


@pytest.fixture
def make_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / "f.db"))
    monkeypatch.setattr(
        "fastprompter.utils.portable_backup.run_portable_backup",
        lambda data, profile_id=1, **_kw: None)

    def _make():
        s = FastPrompterState(profile_id=1)
        s._last_backup_time_by_profile.clear()
        return s

    return _make


def _read_setting_rows(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT key, value FROM settings").fetchall())
    finally:
        conn.close()


def _real_coverage_payload():
    """A payload exactly as ``_record_bundle_coverage`` would persist it."""
    store = CoverageStore()
    event = create_bundle_coverage_event(
        silo_id="S1",
        bundle_kind="silo_bundle",
        archive_name="p_bundle_20261005_201705_FPB6-12015852B4DD.zip",
        markdown_text="# Alpha\n\n- one\n- two\n",
    )
    assert event is not None
    store.record_event(event)
    return store.to_dict()


# --- CORE-003 -------------------------------------------------------------

def test_core003_coverage_key_is_registered_in_both_tables():
    assert "silo_pack_coverage" in state_mod._JSON_SETTINGS
    assert state_mod._STRUCTURED_CODECS["silo_pack_coverage"] == (dict, {}, True)


def test_core003_coverage_roundtrips_as_dict(make_state, tmp_path):
    s = make_state()
    payload = _real_coverage_payload()
    assert payload  # a non-empty ledger
    s.data["silo_pack_coverage"] = payload
    s.mark_dirty("settings")
    assert s.save_data_to_db("", force=True) is True

    # the stored row is canonical JSON, not a str(dict) blob
    raw = _read_setting_rows(tmp_path / "f.db")["silo_pack_coverage"]
    assert json.loads(raw) == payload

    s2 = make_state()
    reloaded = s2.data["silo_pack_coverage"]
    assert isinstance(reloaded, dict)
    assert reloaded == payload
    # and the consumer reconstructs the same store
    assert CoverageStore.from_dict(reloaded).to_dict() == payload


def test_core003_legacy_str_repr_row_recovers(make_state, tmp_path):
    """A pre-fix row written with str(dict) is single-quoted, not JSON."""
    payload = _real_coverage_payload()
    legacy = str(payload)  # single quotes -> JSON rejects it
    with pytest.raises(json.JSONDecodeError):
        json.loads(legacy)

    import sqlite3
    s = make_state()
    s.save_data_to_db("", force=True)  # lands the schema
    conn = sqlite3.connect(tmp_path / "f.db")
    try:
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                     ("silo_pack_coverage", legacy))
        conn.commit()
    finally:
        conn.close()

    s2 = make_state()
    recovered = s2.data["silo_pack_coverage"]
    assert isinstance(recovered, dict)
    assert recovered == payload

    # a clean save then rewrites canonical JSON
    s2.mark_dirty("settings")
    assert s2.save_data_to_db("", force=True) is True
    raw = _read_setting_rows(tmp_path / "f.db")["silo_pack_coverage"]
    assert json.loads(raw) == payload


def test_core003_malformed_row_falls_closed(make_state, tmp_path):
    import sqlite3
    s = make_state()
    s.save_data_to_db("", force=True)
    conn = sqlite3.connect(tmp_path / "f.db")
    try:
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                     ("silo_pack_coverage", "not-a-dict"))
        conn.commit()
    finally:
        conn.close()

    s2 = make_state()
    assert s2.data["silo_pack_coverage"] == {}
    # coverage consumes it without raising
    assert CoverageStore.from_dict(s2.data["silo_pack_coverage"]).to_dict() == {}


# --- CORE-002 -------------------------------------------------------------

def test_core002_clean_generation_drops_unmarked_mutation(make_state, tmp_path):
    """The mechanism the audit names: no dirty mark -> the change is lost."""
    payload = _real_coverage_payload()
    s = make_state()
    s.save_data_to_db("", force=True)  # gen now clean
    s.data["silo_pack_coverage"] = payload
    # deliberately NO mark_dirty -> clean-generation save takes partial path
    assert s.save_data_to_db("") is True

    s2 = make_state()
    assert s2.data.get("silo_pack_coverage") in ({}, None)


def test_core002_dirty_mark_persists_mutation(make_state, tmp_path):
    """_silo_save_settings marks dirty, so the same mutation survives."""
    payload = _real_coverage_payload()
    s = make_state()
    s.save_data_to_db("", force=True)  # gen now clean
    s.data["silo_pack_coverage"] = payload
    s.mark_dirty("settings")           # what _silo_save_settings does
    assert s.save_data_to_db("") is True

    s2 = make_state()
    assert s2.data["silo_pack_coverage"] == payload


def test_core002_helper_marks_and_saves():
    """main._silo_save_settings marks the settings domain and saves once."""
    import inspect

    from fastprompter import main as main_mod
    src = inspect.getsource(main_mod.FastPrompter._silo_save_settings)
    assert 'mark_dirty("settings")' in src
    assert "save_data_to_db" in src


def test_core002_bundle_writers_route_through_helper():
    """Every persisted bundle-settings writer names the one helper."""
    import inspect

    from fastprompter import main as main_mod
    for name in ("_record_bundle_coverage", "_silo_bundle_apply_retention",
                 "_silo_bundle_record_success", "_silo_media_note_first_seen",
                 "_silo_bundle_remember_defaults", "_silo_bundle_history"):
        src = inspect.getsource(getattr(main_mod.FastPrompter, name))
        assert "_silo_save_settings" in src, name
        assert "save_data_to_db" not in src, name


# --- CORE-004 -------------------------------------------------------------

def _bare_profile_host(data, coverage_store="__unset__"):
    """Minimal host carrying just what the shipped reset method touches."""
    import types
    obj = types.SimpleNamespace()
    obj.data = data
    obj.text_area = None
    obj.silo_docs = []
    obj.archive_docs = []
    obj._category_document_cache = {}
    obj._document_fingerprint_cache = {}
    obj._line_count_cache = {}
    obj._editor_text_snaps = "x"
    obj._last_cached_text = "x"
    if coverage_store != "__unset__":
        obj._coverage_store = coverage_store
    return obj


def test_core004_cache_rebinds_from_new_profile_data():
    from fastprompter.main import FastPrompter

    host = _bare_profile_host(
        {"temp_presets": [], "archive_temp_presets": [],
         "silo_pack_coverage": _real_coverage_payload()},
        coverage_store=CoverageStore.from_dict(_real_coverage_payload()))
    assert set(host._coverage_store.to_dict()) == {"S1"}

    # The successful-switch boundary: data has moved to profile B, then the
    # central profile-cache reset runs.
    host.data = {"temp_presets": [], "archive_temp_presets": [],
                 "silo_pack_coverage": {"B1": []}}
    FastPrompter._reset_profile_document_caches(host)

    assert getattr(host, "_coverage_store", None) is None
    # and the getter now derives strictly from B's data
    store_b = CoverageStore.from_dict(host.data["silo_pack_coverage"])
    assert set(store_b.to_dict()) == {"B1"}


def test_core004_reset_runs_only_after_a_successful_switch():
    import inspect

    from fastprompter import main as main_mod
    src = inspect.getsource(main_mod.FastPrompter.change_profile)
    assert src.count("self._reset_profile_document_caches()") == 1
    i_switch = src.index("switched = self.state.switch_profile")
    i_data = src.index("self.data = self.state.data")
    i_reset = src.index("self._reset_profile_document_caches()")
    assert i_switch < i_data < i_reset


def test_core004_refusal_paths_return_before_the_data_swap():
    """Every refusal in change_profile returns before self.data is replaced,
    so _reset_profile_document_caches (and the cache drop) never runs."""
    import inspect

    from fastprompter import main as main_mod
    src = inspect.getsource(main_mod.FastPrompter.change_profile)
    i_data = src.index("self.data = self.state.data")
    before = src[:i_data]
    assert before.count("self.state.switch_profile(") == 1
    assert "return" in before  # refusal paths bail out before the swap
