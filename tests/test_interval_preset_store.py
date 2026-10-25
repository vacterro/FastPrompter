"""T-1517 Part B: durable interval-preset library tests.

Acceptance scope:
- schema validation and rejection of bounds/types
- single_rule vs collection enforcement
- persistence across store re-instantiations
- atomic writes (crash/failure leaves prior file intact)
- CRUD operations (create, update, rename, duplicate, delete)
- delete isolation
- import/export round-trip and validation
"""

from __future__ import annotations

import json
import os

import pytest

from fastprompter.core.interval_preset_store import (
    KIND_COLLECTION,
    KIND_SINGLE,
    MAX_NAME_LEN,
    MAX_RULES,
    IntervalPresetStore,
    PresetValidationError,
    clean_preset,
    clean_rule,
)


@pytest.fixture
def store(tmp_path):
    return IntervalPresetStore(directory=str(tmp_path / "presets"))


def _sample_rule(**kwargs):
    r = {
        "name": "Hourly Bell",
        "minutes": 60,
        "enabled": True,
        "sound": "file:newday.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
    }
    r.update(kwargs)
    return r


# --- 1. Basic CRUD and persistence ------------------------------------------

def test_create_and_load_persists(store):
    r = _sample_rule()
    created = store.create_preset("My Hourly", [r], kind=KIND_SINGLE)
    assert created["id"]
    assert created["name"] == "My Hourly"
    assert created["kind"] == KIND_SINGLE
    assert len(created["rules"]) == 1

    # Reload from fresh store instance
    store2 = IntervalPresetStore(directory=store.directory)
    loaded = store2.load()
    assert len(loaded) == 1
    assert loaded[0]["id"] == created["id"]
    assert loaded[0]["name"] == "My Hourly"
    assert loaded[0]["rules"][0]["sound"] == "file:newday.wav"


def test_update_preset(store):
    created = store.create_preset("Workday", [_sample_rule()], kind=KIND_SINGLE)
    pid = created["id"]
    updated = store.update_preset(pid, name="Workday Shift")
    assert updated["name"] == "Workday Shift"

    fresh = store.get(pid)
    assert fresh["name"] == "Workday Shift"


def test_rename_preset(store):
    created = store.create_preset("Alpha", [_sample_rule()], kind=KIND_SINGLE)
    pid = created["id"]
    store.rename_preset(pid, "Beta")
    assert store.get(pid)["name"] == "Beta"


def test_duplicate_preset(store):
    created = store.create_preset("Original", [_sample_rule()], kind=KIND_SINGLE)
    pid = created["id"]
    dup = store.duplicate_preset(pid)
    assert dup["id"] != pid
    assert dup["name"] == "Original (copy)"
    assert dup["rules"][0]["id"] != created["rules"][0]["id"]
    assert store.count() == 2


def test_delete_preset_and_isolation(store):
    p1 = store.create_preset("P1", [_sample_rule()], kind=KIND_SINGLE)
    p2 = store.create_preset("P2", [_sample_rule()], kind=KIND_SINGLE)
    assert store.count() == 2

    assert store.delete_preset(p1["id"]) is True
    assert store.get(p1["id"]) is None
    assert store.get(p2["id"]) is not None
    assert store.count() == 1
    # Deleting nonexistent is False
    assert store.delete_preset(p1["id"]) is False


# --- 2. Single-rule vs Collection enforcement -------------------------------

def test_single_rule_enforces_exactly_one_rule(store):
    with pytest.raises(PresetValidationError, match="exactly one rule"):
        store.create_preset("Bad Single", [_sample_rule(), _sample_rule()], kind=KIND_SINGLE)

    with pytest.raises(PresetValidationError, match="exactly one rule"):
        store.create_preset("Empty Single", [], kind=KIND_SINGLE)


def test_collection_allows_multiple_rules(store):
    r1 = _sample_rule(name="R1")
    r2 = _sample_rule(name="R2")
    coll = store.create_preset("Dual", [r1, r2], kind=KIND_COLLECTION)
    assert coll["kind"] == KIND_COLLECTION
    assert len(coll["rules"]) == 2


def test_collection_requires_at_least_one_rule(store):
    with pytest.raises(PresetValidationError, match="at least one rule"):
        store.create_preset("Empty Coll", [], kind=KIND_COLLECTION)


# --- 3. Schema boundaries and validation ------------------------------------

def test_invalid_name_rejected(store):
    with pytest.raises(PresetValidationError, match="must not be empty"):
        store.create_preset("", [_sample_rule()], kind=KIND_SINGLE)

    with pytest.raises(PresetValidationError, match="too long"):
        store.create_preset("A" * (MAX_NAME_LEN + 1), [_sample_rule()], kind=KIND_SINGLE)


def test_invalid_rule_field_types_rejected():
    with pytest.raises(PresetValidationError, match="minutes must be an integer"):
        clean_rule(_sample_rule(minutes="not_an_int"), strict=True)

    with pytest.raises(PresetValidationError, match="must be a boolean"):
        clean_rule(_sample_rule(enabled="invalid_bool"), strict=True)


def test_runtime_fields_stripped():
    r = _sample_rule(last_fired=12345.0, last_fired_minute="12:00")
    cleaned = clean_rule(r, strict=False)
    assert "last_fired" not in cleaned
    assert "last_fired_minute" not in cleaned


def test_max_rules_enforced():
    rules = [_sample_rule(name=f"R{i}") for i in range(MAX_RULES + 1)]
    with pytest.raises(PresetValidationError, match="at most"):
        clean_preset({"name": "Overflow", "kind": KIND_COLLECTION, "rules": rules}, strict=True)


# --- 4. Atomic writes & error containment -----------------------------------

def test_atomic_failure_preserves_old(store, monkeypatch):
    created = store.create_preset("Safe", [_sample_rule()], kind=KIND_SINGLE)
    pid = created["id"]
    path = store._path_for(pid)
    before_content = open(path, "rb").read()

    # Inject an error into os.fsync or write
    def boom(*args, **kwargs):
        raise OSError("disk full simulated")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        store.update_preset(pid, name="Clobbered?")

    # File on disk remains intact and byte-identical
    assert open(path, "rb").read() == before_content
    assert store.get(pid)["name"] == "Safe"


# --- 5. Import and Export roundtrip -----------------------------------------

def test_export_import_roundtrip(store, tmp_path):
    p = store.create_preset("Exportable", [_sample_rule()], kind=KIND_SINGLE)
    doc = store.export_preset(p["id"])
    assert doc["name"] == "Exportable"

    # Import into another store
    store2 = IntervalPresetStore(directory=str(tmp_path / "store2"))
    imported = store2.import_preset(doc)
    assert imported["id"] == p["id"]
    assert imported["name"] == "Exportable"
    assert store2.count() == 1


def test_import_collision_without_overwrite_fails(store):
    p = store.create_preset("First", [_sample_rule()], kind=KIND_SINGLE)
    with pytest.raises(PresetValidationError, match="already exists"):
        store.import_preset(p, overwrite=False)

    # With overwrite=True succeeds
    store.import_preset(p, overwrite=True)
    assert store.count() == 1


def test_import_document_bytes(store):
    payload = json.dumps({
        "schema_version": 1,
        "id": "ext_preset",
        "name": "External",
        "kind": KIND_SINGLE,
        "rules": [_sample_rule()],
    }).encode("utf-8")

    imported = store.import_document_bytes(payload)
    assert imported["id"] == "ext_preset"
    assert store.get("ext_preset") is not None


# --- 6. PRESET-01 / PRESET-02: cold initialization barrier --------------------

class TestColdInitBarrier:
    """PRESET-01/PRESET-02: a freshly-constructed store with no prior ``load()``
    call must still see existing files on disk before any ID collision check.

    Before the fix, ``import_preset`` and ``create_preset`` checked the in-memory
    ``_presets`` dict (empty until ``load`` was called), so an import could
    silently overwrite a file sitting on disk, and a create could clobber an
    existing preset that ``load`` had never seen. ``_ensure_loaded`` is the
    barrier that forces the disk read.
    """

    def test_import_collision_detected_on_cold_store(self, tmp_path):
        """Importing a preset whose id already exists on disk must raise,
        even on a store that has never called ``load``."""
        dir_a = tmp_path / "store"
        dir_a.mkdir()
        store = IntervalPresetStore(directory=str(dir_a))
        created = store.create_preset("Original", [_sample_rule()], kind=KIND_SINGLE)

        # Fresh store -- cold, _presets is empty
        store2 = IntervalPresetStore(directory=str(dir_a))
        assert store2._loaded is False
        assert store2._presets == {}

        with pytest.raises(PresetValidationError, match="already exists"):
            store2.import_preset(created)

    def test_create_collision_detected_on_cold_store(self, tmp_path):
        """Creating a preset with an explicit id that exists on disk must raise
        on a cold store."""
        dir_a = tmp_path / "store"
        dir_a.mkdir()
        store = IntervalPresetStore(directory=str(dir_a))
        created = store.create_preset("Original", [_sample_rule()], kind=KIND_SINGLE)

        store2 = IntervalPresetStore(directory=str(dir_a))
        assert store2._loaded is False

        with pytest.raises(PresetValidationError, match="already exists"):
            store2.create_preset(
                "Collision", [_sample_rule()], kind=KIND_SINGLE,
                preset_id=created["id"])

    def test_get_returns_disk_state_on_cold_store(self, tmp_path):
        """A cold ``get`` must reflect files written by another store."""
        dir_a = tmp_path / "store"
        dir_a.mkdir()
        store = IntervalPresetStore(directory=str(dir_a))
        created = store.create_preset("Cold", [_sample_rule()], kind=KIND_SINGLE)

        store2 = IntervalPresetStore(directory=str(dir_a))
        assert store2._loaded is False
        loaded = store2.get(created["id"])
        assert loaded is not None
        assert loaded["name"] == "Cold"


# --- 7. PRESET-03 / PRESET-04: replace_all transactional integrity -------------

class TestReplaceAllIntegrity:
    """PRESET-03: ``replace_all`` must validate the entire batch BEFORE writing
    anything, so a rejected document leaves the existing library intact.
    PRESET-04: deletions of stale entries happen last, so a crash mid-batch
    never leaves a partially-wiped library.
    """

    def test_replace_all_rejected_before_any_write(self, tmp_path, monkeypatch):
        """If any document in the batch is invalid, the entire library is
        untouched -- no files are added, modified, or deleted."""
        store = IntervalPresetStore(directory=str(tmp_path / "store"))
        original = store.create_preset("Keep", [_sample_rule()], kind=KIND_SINGLE)

        dir_before = os.listdir(store.directory)
        # The file must exist with known content
        original_path = store._path_for(original["id"])
        original_bytes = open(original_path, "rb").read()

        # Bad batch: second entry has an invalid rule (minutes out of range)
        bad_rule = _sample_rule()
        bad_rule["minutes"] = 999999  # out of allowed range
        with pytest.raises(PresetValidationError):
            store.replace_all([
                _sample_rule_rule(),
                {"id": "bad", "name": "Bad", "kind": KIND_SINGLE,
                 "rules": [bad_rule]},
            ])

        # Directory contents unchanged
        assert os.listdir(store.directory) == dir_before
        # Original file byte-identical
        assert open(original_path, "rb").read() == original_bytes
        # In-memory state unchanged
        assert store.count() == 1
        assert store.get(original["id"])["name"] == "Keep"


    def test_replace_all_removes_stale_after_writing_new(self, tmp_path):
        """Valid batch writes all new files BEFORE removing stale ones.

        PRESET-03: replace_all must not deadlock by calling delete_preset
        (which re-acquires the lock) from inside the held lock. The fix
        uses _delete_preset_locked directly. Stale presets are removed
        after all new files are committed, so a crash mid-batch leaves
        extra files behind -- never a partially-wiped library.
        """
        store = IntervalPresetStore(directory=str(tmp_path / "store"))
        p1 = store.create_preset("P1", [_sample_rule(name="R1")], kind=KIND_SINGLE)

        new_rule = _sample_rule(name="R_new")
        batch = [
            {"id": "p2", "name": "P2", "kind": KIND_SINGLE, "rules": [new_rule]},
        ]

        # This must not deadlock -- the old code called self.delete_preset inside
        # the held self._lock (a non-reentrant threading.Lock).
        store.replace_all(batch)

        # p1 was present before but is not in the new batch -> deleted
        assert store.get(p1["id"]) is None
        # The new preset p2 is now present
        assert store.get("p2") is not None
        # p2 file exists on disk
        assert os.path.isfile(store._path_for("p2"))
        # p1 file is gone from disk
        assert not os.path.exists(store._path_for(p1["id"]))


def _sample_rule_rule():
    """Return a valid clean rule dict for replace_all batches."""
    return {
        "id": "r1",
        "name": "Test Rule",
        "minutes": 60,
        "enabled": True,
        "sound": "file:newday.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
    }


def test_replace_all_duplicate_id_in_batch_rejected(tmp_path):
    """Two documents with the same id in one batch is a hard error -- not a
    silent second-write that overwrites the first."""
    store = IntervalPresetStore(directory=str(tmp_path / "store"))
    rule = _sample_rule_rule()
    dup_doc = {
        "id": "same", "name": "Dup", "kind": KIND_SINGLE,
        "rules": [rule],
    }
    with pytest.raises(PresetValidationError, match="duplicate preset id"):
        store.replace_all([dup_doc, dup_doc])
