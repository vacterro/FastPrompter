"""Invariant tests for per-category state aliasing.

Proves the Phase-6 invariants:

* ``bind_active_category`` re-binds EVERY per-category flat alias to the
  given category - a category switch can never leave an alias bound to
  another category's ``_all`` entry.
* switching A -> B -> A repeatedly does not leak state across categories,
  including through a save/reload round trip.
* the alias registry and the per-category store registry are consistent
  (one source of truth, no orphaned stores).
* a corrupted ``_all`` store is replaced instead of raising.
"""

import fastprompter.core.state as state_mod
from fastprompter.core.state import (
    _PER_CATEGORY_ALIASES,
    _PER_CATEGORY_STATE_KEYS,
    FastPrompterState,
    bind_active_category,
)

ALIASES = dict(_PER_CATEGORY_ALIASES)

# Stores with no flat data-key alias, and why:
#  silo_last_edited_all  -> bound to the instance attribute self.silo_last_edited
#  silo_session_all      -> per-project single entry, not a flat alias
#  silo_view_state_all   -> accessed via helpers, no flat alias
_NON_ALIASED = {"silo_last_edited_all", "silo_session_all", "silo_view_state_all"}


def _data_with_sentinels():
    """A data dict where category A and B hold distinct sentinels everywhere."""
    data = {
        "temp_presets_all": {"A": ["a0"], "B": ["b0"]},
        "archive_temp_presets_all": {"A": ["a1"], "B": ["b1"]},
        "pinned_silos_all": {"A": [1], "B": [2]},
        "silo_ticked_all": {"A": [1], "B": [2]},
        "silo_children_all": {"A": {1: [2]}, "B": {3: [4]}},
        "silo_collapsed_all": {"A": [1], "B": [2]},
        "silo_colors_all": {"A": {"1": "red"}, "B": {"2": "blue"}},
        "silo_gaps_all": {"A": [1], "B": [2]},
        "silo_folders_all": {"A": {"1": "a-folder"}, "B": {"2": "b-folder"}},
        "archive_silo_folders_all": {"A": {"1": "a-arc"}, "B": {"2": "b-arc"}},
        "silo_project_paths_all": {"A": {"1": "a-path"}, "B": {"2": "b-path"}},
        "archive_project_paths_all": {"A": {"1": "a-apath"}, "B": {"2": "b-apath"}},
        "watcher_queues_all": {"A": {"1": []}, "B": {"2": []}},
        "silo_types_all": {"A": {"1": "kanban"}, "B": {"2": "table"}},
    }
    # silo_type_all is the real store name (the flat alias is silo_types)
    data["silo_type_all"] = data.pop("silo_types_all")
    return data


class TestBindActiveCategory:
    def test_binds_every_alias_to_the_target_category(self):
        data = _data_with_sentinels()
        bind_active_category(data, "A")
        for flat in ALIASES:
            assert data[flat] is data[ALIASES[flat]]["A"], flat
        bind_active_category(data, "B")
        for flat in ALIASES:
            assert data[flat] is data[ALIASES[flat]]["B"], flat

    def test_no_cross_category_leakage_switching_a_b_a(self):
        data = _data_with_sentinels()

        bind_active_category(data, "A")
        data["pinned_silos"].append(99)      # mutate A's list
        data["silo_colors"]["5"] = "mutated"  # mutate A's dict

        bind_active_category(data, "B")
        data["pinned_silos"].append(77)      # mutate B's list
        data["silo_colors"]["6"] = "mutated-b"

        bind_active_category(data, "A")
        assert data["pinned_silos"] == [1, 99]
        assert data["silo_colors"] == {"1": "red", "5": "mutated"}
        # B's mutation did not touch A
        bind_active_category(data, "B")
        assert data["pinned_silos"] == [2, 77]
        assert data["silo_colors"] == {"2": "blue", "6": "mutated-b"}

    def test_missing_category_gets_a_fresh_empty_store(self):
        data = _data_with_sentinels()
        bind_active_category(data, "New")
        assert data["temp_presets"] == [""] * 10
        assert data["archive_temp_presets"] == []
        assert data["pinned_silos"] == []
        assert data["silo_colors"] == {}
        # a fresh empty store is a deep copy, not a shared list
        data["temp_presets"][0] = "x"
        bind_active_category(data, "Newer")
        assert data["temp_presets"] == [""] * 10

    def test_corrupt_all_store_is_replaced(self):
        data = _data_with_sentinels()
        data["watcher_queues_all"] = "{not a dict}"   # str(dict) from an old DB
        data["pinned_silos_all"] = [1, 2]             # valid JSON, wrong type
        bind_active_category(data, "A")
        assert isinstance(data["watcher_queues_all"], dict)
        assert data["watcher_queues"] is data["watcher_queues_all"]["A"]
        assert isinstance(data["pinned_silos_all"], dict)
        assert data["pinned_silos"] == []

    def test_registry_covers_every_per_category_store(self):
        # every store that HAS a flat alias must be a real per-category store
        for all_key in ALIASES.values():
            assert all_key in _PER_CATEGORY_STATE_KEYS, all_key
        # every per-category store is either aliased or explicitly documented
        for key in _PER_CATEGORY_STATE_KEYS:
            assert key in ALIASES.values() or key in _NON_ALIASED, key


class TestAliasPersistence:
    def test_no_leakage_through_save_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: str(tmp_path / "alias.db"))
        monkeypatch.setattr(
            "fastprompter.utils.portable_backup.run_portable_backup",
            lambda data, profile_id=1, **_kw: None)

        s = FastPrompterState(profile_id=1)
        try:
            data = s.data
            # give two categories distinct sentinels in every per-category store
            for cat in ("A", "B"):
                data["cats_order"].append(cat)
                data["categories"][cat] = [None] * 100
                for all_key in ALIASES.values():
                    data.setdefault(all_key, {})[cat] = {}
                data["temp_presets_all"][cat] = [f"{cat}-silo"]
                data["archive_temp_presets_all"][cat] = [f"{cat}-archive"]
                data["pinned_silos_all"][cat] = [1] if cat == "A" else [2]
                data["silo_colors_all"][cat] = {"1": cat + "-red"}

            bind_active_category(data, "A")
            data["pinned_silos"].append(10)
            s.mark_dirty()
            s.save_data_to_db("A text", force=True)
            s.conn.close()

            s2 = FastPrompterState(profile_id=1)
            try:
                bind_active_category(s2.data, "A")
                assert s2.data["temp_presets"][0] == "A-silo"
                assert s2.data["pinned_silos"] == [1, 10]
                assert s2.data["silo_colors"] == {"1": "A-red"}
                bind_active_category(s2.data, "B")
                assert s2.data["temp_presets"][0] == "B-silo"
                assert s2.data["pinned_silos"] == [2]      # A's 10 did not leak
                assert s2.data["silo_colors"] == {"1": "B-red"}
            finally:
                s2.conn.close()
        finally:
            s.conn.close()
