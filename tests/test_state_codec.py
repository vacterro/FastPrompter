"""P1-15: one structured-setting codec contract per persisted key.

The decode path used to be a hand-grown branch chain with duplicated truth:
``folder_trash_log`` fell into the broad dict-like JSON branch, so corrupt
data degraded to ``{}`` although its default and every consumer require a
LIST of (original, trashed) pairs, and many keys silently accepted
syntactically valid JSON of the WRONG top-level type. All structured keys
now decode through the ``_STRUCTURED_CODECS`` registry:

* corrupt JSON        -> the key's own correct default (deep-copied)
* valid JSON, wrong type -> the key's own correct default
* legacy str(dict)/str(list) rows -> ast recovery where historically needed
* valid JSON of the right type -> round-tripped unchanged (Unicode included)
"""

import json
import sqlite3

import pytest

import fastprompter.core.state as state_mod
from fastprompter.core.state import FastPrompterState


@pytest.fixture
def state_from(tmp_path, monkeypatch):
    counter = [0]

    def _make(rows):
        counter[0] += 1
        db = str(tmp_path / f"codec_{counter[0]}.db")
        monkeypatch.setattr(state_mod, "get_db_path",
                            lambda profile_id=1, _db=db: _db)
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data, profile_id=1: None)
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        for key, value in rows:
            conn.execute("INSERT INTO settings VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        return FastPrompterState(profile_id=1)

    return _make


class TestWrongTypeAndCorruptDecode:
    def test_corrupt_folder_trash_log_falls_back_to_list(self, state_from):
        s = state_from([("folder_trash_log", "{bad json")])
        try:
            assert s.data["folder_trash_log"] == []
        finally:
            s.conn.close()

    def test_wrong_type_valid_json_folder_trash_log_falls_back_to_list(
            self, state_from):
        # a dict is syntactically valid JSON but the wrong top-level type:
        # consumers unpack (original, trashed) pairs, so a dict would raise
        s = state_from([("folder_trash_log", "{}")])
        try:
            assert s.data["folder_trash_log"] == []
        finally:
            s.conn.close()

    def test_wrong_type_string_folder_trash_log_falls_back_to_list(
            self, state_from):
        s = state_from([("folder_trash_log", json.dumps("not a list"))])
        try:
            assert s.data["folder_trash_log"] == []
        finally:
            s.conn.close()

    def test_timers_dict_valid_json_falls_back_to_list(self, state_from):
        # timers is a LIST of timer dicts; {} would make load_timers see a
        # mapping and silently drop every timer
        s = state_from([("timers", "{}")])
        try:
            assert s.data["timers"] == []
        finally:
            s.conn.close()

    def test_dict_setting_with_list_json_falls_back_to_dict(self, state_from):
        s = state_from([("silo_folders", "[]")])
        try:
            assert s.data["silo_folders"] == {}
        finally:
            s.conn.close()

    def test_malformed_dict_setting_falls_back_to_dict(self, state_from):
        s = state_from([("category_file_dirs", "nope")])
        try:
            assert s.data["category_file_dirs"] == {}
        finally:
            s.conn.close()


class TestLegacyAstRecovery:
    def test_str_dict_productivity_timer_recovers(self, state_from):
        s = state_from([("productivity_timer", "{'work': 25, 'rest': 5}")])
        try:
            assert s.data["productivity_timer"] == {"work": 25, "rest": 5}
        finally:
            s.conn.close()

    def test_str_list_silo_gaps_recovers(self, state_from):
        s = state_from([("silo_gaps", "[1, 3]")])
        try:
            assert s.data["silo_gaps"] == [1, 3]
        finally:
            s.conn.close()

    def test_ast_recovery_rejects_wrong_type(self, state_from):
        # legacy row that evaluates to the wrong type: dict for a list key
        s = state_from([("silo_gaps", "{'a': 1}")])
        try:
            assert s.data["silo_gaps"] == []
        finally:
            s.conn.close()


class TestRoundTripAndIsolation:
    def test_valid_unicode_round_trip(self, state_from):
        value = {"0": "\u30d5\u30a9\u30eb\u30c0\u30fc-\u30c6\u30b9\u30c8",
                 "1": "\U0001F600 emoji \u65e5\u672c\u8a9e"}
        s = state_from([("silo_folders", json.dumps(value))])
        try:
            assert s.data["silo_folders"] == value
        finally:
            s.conn.close()

    def test_cats_order_type_checked(self, state_from):
        s = state_from([("cats_order", "{}")])
        try:
            assert s.data["cats_order"] == ["Code", "Text", "Misc"]
        finally:
            s.conn.close()

    def test_adopted_default_is_a_fresh_deep_copy(self, state_from):
        s1 = state_from([("silo_children", "{bad")])
        s2 = state_from([("silo_colors", "[not json")])
        try:
            assert s1.data["silo_children"] == {}
            assert s2.data["silo_colors"] == {}
            # mutating one adoption must never leak into another state's
            s1.data["silo_children"]["cat"] = {"1": [2]}
            assert "cat" not in s2.data["silo_colors"]
        finally:
            s1.conn.close()
            s2.conn.close()


class TestSingleCodecContract:
    def test_every_json_setting_has_exactly_one_codec(self):
        assert set(state_mod._STRUCTURED_CODECS) == set(state_mod._JSON_SETTINGS)

    def test_every_codec_contract_is_well_formed(self):
        for key, (expected, default, legacy_ast) in \
                state_mod._STRUCTURED_CODECS.items():
            assert expected in (list, dict), key
            assert isinstance(default, expected), key
            assert isinstance(legacy_ast, bool), key

    def test_no_structured_key_is_also_a_scalar_key(self):
        scalars = ("last_tab_idx", "active_temp_slot", "font_size",
                   "ui_scale", "window_locked", "sidebar_right", "hide_font")
        for key in scalars:
            assert key not in state_mod._STRUCTURED_CODECS
