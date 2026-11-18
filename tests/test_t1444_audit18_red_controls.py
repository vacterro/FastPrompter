"""T-1444 / SRC-140: RED controls for the audit/18.md three-wave handoff.

Fourteen verified findings arrived as one external audit. Each has its own
clause in the contract (SRC-140:R001..R014) and each gets its own control here,
because R010 forbids collapsing the planes: a test that opens a dialog is not
evidence that the mechanism behind it behaves, and a test named "concurrency"
has to create a real concurrency.

Every control below reproduces the auditor's own deterministic reproduction
against this checkout, so the RED half is measured rather than quoted:

* R001 preset id accepted then invisible (data loss on the next cold load)
* R002 sync discovery starves when the mapping is at capacity
* R004 clock search skips the only valid minute of a one-minute window
* R005 elapsed countdown reports "due now" for a deadline hours in the past
* R006 strict import truncates fractional numbers instead of refusing them
* R007 restore publishes its safety snapshot over the selected source
* R008 concurrent ambience writers lose one accepted update; a corrupt row is
  deleted by an unrelated edit
* R009 portable backup certifies COMPLETE while omitting an orphan category
* R010 pack publication follows a Windows junction out of the managed library
* R011 cyclic personal-audio aliases raise RecursionError
* R012 coverage ownership lookup is quadratic in cold traversal
* R013 detached-media association is cubic-like in alternating documents
* R014 selection coverage re-normalizes the whole document per requirement

R003 is the export-fidelity finding the auditor itself marks "reconcile with
T-1443 / SRC-139"; it has no control here because owning it twice would be the
duplicate ticket it warns against. Its reconciliation is proven by the T-1443
suite instead.

Nothing in this module captures foreground focus, injects input, or writes the
operator's live data tree: every filesystem case builds its own temporary root.
"""

import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))


def _full_rule(**overrides):
    """A complete rule: strict mode requires every integer field to be present."""
    rule = {
        "name": "Hourly Bell",
        "minutes": 30,
        "enabled": True,
        "sound": "",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 540,
        "end_minute": 600,
    }
    rule.update(overrides)
    return rule


# ---------------------------------------------------------------------------
# R001 - preset namespace: an id the reader will not surface must not be stored
# ---------------------------------------------------------------------------


def test_hidden_preset_id_is_refused_at_creation(tmp_path):
    """CORE-001 (P0): ``create_preset('.hidden')`` used to succeed.

    ``_path_for`` accepted a dot-prefixed id, ``_read_all`` skipped every name
    beginning with ``.`` as transaction metadata, so the document was written
    and then became invisible to the very next cold load. The user loses the
    preset they just made, with no error at all.
    """
    from fastprompter.core.interval_preset_store import (
        IntervalPresetStore,
        PresetValidationError,
    )

    store = IntervalPresetStore(str(tmp_path))

    with pytest.raises(PresetValidationError):
        store.create_preset("Hidden", [_full_rule()], preset_id=".hidden")

    # Nothing was written, so a fresh store cannot report a phantom preset.
    fresh = IntervalPresetStore(str(tmp_path))
    assert fresh.get(".hidden") is None
    assert [p["id"] for p in fresh.load()] == []


def test_reserved_journal_name_is_refused_as_preset_id(tmp_path):
    """The batch journal is transaction metadata, never a preset document."""
    from fastprompter.core.interval_preset_store import (
        IntervalPresetStore,
        PresetValidationError,
    )

    store = IntervalPresetStore(str(tmp_path))
    with pytest.raises(PresetValidationError):
        store.create_preset("Journal", [_full_rule()],
                            preset_id=".batch-journal")


def test_ordinary_preset_ids_still_round_trip(tmp_path):
    """The refusal is targeted: a normal id survives create and cold load."""
    from fastprompter.core.interval_preset_store import IntervalPresetStore

    store = IntervalPresetStore(str(tmp_path))
    created = store.create_preset("Morning", [_full_rule()], preset_id="a1b2c3")
    fresh = IntervalPresetStore(str(tmp_path))
    loaded = fresh.get(created["id"])
    assert loaded is not None
    assert loaded["name"] == "Morning"


@pytest.mark.parametrize("preset_id", ["aux", "com1", "lpt1", "nul.json"])
def test_device_name_preset_id_is_refused_at_creation(tmp_path, preset_id):
    """CORE-001, still reachable after the dot-prefix repair.

    Windows accepts a DEVICE name as a filename: ``create_preset`` reported
    success, ``os.listdir`` never showed the document, and the next cold load
    returned nothing. That is the same loss the dot-prefix rule closes -- a
    preset the user made that no reader can surface -- reached through a
    spelling the prefix check cannot see. The refusal must happen before any
    filesystem mutation, so a fresh store sees an empty directory.
    """
    from fastprompter.core.interval_preset_store import (
        IntervalPresetStore,
        PresetValidationError,
    )

    store = IntervalPresetStore(str(tmp_path))
    with pytest.raises(PresetValidationError):
        store.create_preset("Device", [_full_rule()], preset_id=preset_id)

    assert list(tmp_path.iterdir()) == []
    assert [p["id"] for p in IntervalPresetStore(str(tmp_path)).load()] == []


def test_control_character_preset_id_is_refused_not_raised_as_oserror(tmp_path):
    """An id with a control character must be a VALIDATION refusal.

    The write path raised ``OSError(EINVAL)`` from ``open``, which is not an
    error a caller of this API is told to expect; the preset simply failed to
    save with an unrelated exception. Validation owns that decision.
    """
    from fastprompter.core.interval_preset_store import (
        IntervalPresetStore,
        PresetValidationError,
    )

    with pytest.raises(PresetValidationError):
        IntervalPresetStore(str(tmp_path)).create_preset(
            "Control", [_full_rule()], preset_id="a\x08b")


# ---------------------------------------------------------------------------
# R002 - Sync-Project discovery must reach eligible unmapped files at capacity
# ---------------------------------------------------------------------------


def test_scan_reaches_new_file_when_mapping_is_full(tmp_path):
    """CORE-002 (P1): 99 mapped + 1 eligible must still discover the new one.

    The call site computed ``free_count = 100 - len(mapping)`` and handed that
    as the retention bound BEFORE any exclusion, so the bounded heap kept the
    lexicographically smallest paths -- which are exactly the 99 already
    mapped -- and the only eligible new file was never seen. The scan already
    accepts ``exclude_paths``; the repair is to use it before the bound.
    """
    from fastprompter.core.project_sync import scan_folder

    for index in range(100):
        (tmp_path / f"f{index:03d}.txt").write_text("x", encoding="utf-8")
    mapping = {str(i): f"f{i:03d}.txt" for i in range(99)}

    free_count = max(0, 100 - len(mapping))
    assert free_count == 1

    files = scan_folder(str(tmp_path), None, None, recursive=True,
                       limit=free_count,
                       exclude_paths=set(mapping.values()))
    new_files = [f for f in files if f not in set(mapping.values())]
    assert new_files == ["f099.txt"]


def test_scan_exclusion_preserves_order_and_identity(tmp_path):
    """Excluded paths never appear, and the retained set stays sorted."""
    from fastprompter.core.project_sync import scan_folder

    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    files = scan_folder(str(tmp_path), None, None, recursive=True,
                       exclude_paths={"b.txt", "d.txt"})
    assert files == ["a.txt", "c.txt"]


def test_scan_cancellation_still_returns_empty(tmp_path):
    """A cancelled scan is the empty signal, never a partial list."""
    from fastprompter.core.project_sync import scan_folder

    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert scan_folder(str(tmp_path), None, None,
                       should_cancel=lambda: True) == []


def test_rescan_discovery_reaches_new_file_at_capacity(tmp_path):
    """CORE-002 through the real rescan path, not just the scanner.

    The scanner already honours ``exclude_paths``; the defect lived in
    ``_rescan_project_sync``, which bounded its scan to the number of FREE
    slots before excluding anything already mapped. With 99 of 100 bindings
    used, the bound kept the 99 smallest paths and the 100th file -- the only
    eligible new one -- was never discovered.
    """
    import fastprompter.main as main_mod

    fake = _RescanDouble(tmp_path)
    for index in range(100):
        (tmp_path / f"f{index:03d}.txt").write_text("x", encoding="utf-8")
    fake.data["project_sync_map"] = {str(i): f"f{i:03d}.txt" for i in range(99)}
    fake.data["temp_presets"] = [""] * 99

    main_mod.FastPrompter._rescan_project_sync(fake)

    discovered = set(fake.data["project_sync_map"].values())
    assert "f099.txt" in discovered, (
        "a full mapping must still discover the eligible unmapped file; "
        f"mapped now: {sorted(discovered)}")


class _RescanDouble:
    """Minimal owner for ``_rescan_project_sync`` (mirrors the repo's double)."""

    def __init__(self, root):
        self.root = root
        self.data = {"project_sync_map": {}}
        self._invalidated = []
        self._eol_cache = {}
        self._bom_cache = {}
        self._last_applied = {}

    def _sync_config(self):
        return True

    def _sync_root(self):
        return str(self.root)

    def _sync_include(self):
        return [".txt"]

    def _sync_exclude(self):
        return []

    def _sync_recursive(self):
        return True

    def _sync_max_bytes(self):
        return 4096

    def _sync_invalidate_binding(self, key, path):
        self._invalidated.append((key, path))

    def _sync_baseline_key(self, slot, path):
        return f"{slot}:{path}"

    def _sync_side_digest(self, text):
        return text

    def _ensure_temp_presets(self):
        return self.data.setdefault("temp_presets", [])

    def _start_project_watcher(self):
        pass

    def _update_project_tooltip(self):
        pass

    def mark_dirty(self):
        pass

    def refresh_temp_presets(self):
        pass


# ---------------------------------------------------------------------------
# R004 - clock-aligned countdown must agree with the scheduler
# ---------------------------------------------------------------------------


def test_one_minute_window_countdown_matches_scheduler():
    """CORE-004: a 09:01-only rule must count down 60s at 09:00.

    ``next_clock_occurrence`` advanced with
    ``next_clock_boundary(probe + timedelta(minutes=1), ..., inclusive=False)``
    and ``next_clock_boundary`` with ``inclusive=False`` ALREADY moves to the
    next boundary, so with ``minutes=1`` every probe skipped the following
    eligible minute. The scheduler still fired; the top bar said "no next".
    """
    from fastprompter.core.interval_schedule import (
        is_due_now,
        seconds_until_next,
    )

    rule = {
        "minutes": 1,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 541,
        "end_minute": 541,
    }
    now = datetime.datetime(2026, 10, 30, 9, 0)
    assert seconds_until_next(rule, now) == 60.0
    assert is_due_now(rule, datetime.datetime(2026, 10, 30, 9, 1)) is True


def test_clock_search_does_not_skip_a_narrow_window():
    """Every eligible boundary of a one-minute window is reachable."""
    from fastprompter.core.interval_schedule import next_clock_occurrence

    rule = {
        "minutes": 1,
        "align_mode": "clock",
        "all_day": False,
        "start_minute": 541,
        "end_minute": 541,
    }
    now = datetime.datetime(2026, 10, 30, 8, 59)
    assert next_clock_occurrence(rule, now, inclusive=False) == \
        datetime.datetime(2026, 10, 30, 9, 1)


def test_clock_cadence_regressions_unchanged():
    """Non-divisor cadences keep their existing boundaries."""
    from fastprompter.core.interval_schedule import next_clock_occurrence

    now = datetime.datetime(2026, 10, 30, 9, 0)
    for minutes in (45, 90):
        nxt = next_clock_occurrence({"minutes": minutes}, now, inclusive=False)
        assert nxt is not None
        assert nxt > now
        # Still a whole-minute boundary of the requested cadence.
        assert nxt.second == 0
        assert nxt.tzinfo is None


# ---------------------------------------------------------------------------
# R005 - elapsed countdown must reconcile an overdue deadline with "now"
# ---------------------------------------------------------------------------


def test_elapsed_countdown_respects_current_window_when_deadline_past(
        monkeypatch):
    """CORE-005: a deadline that expired inside an earlier window is re-based.

    At 15:00 the 09:30 deadline belongs to a closed window. The scheduler's
    active-hours guard refuses to fire, but ``next_elapsed_occurrence``
    returned the expired deadline because its minute WAS inside the window, so
    the countdown sat at 0.0 forever.
    """
    import fastprompter.core.interval_schedule as schedule

    now = datetime.datetime(2026, 10, 30, 15, 0)
    monkeypatch.setattr("time.time", lambda: now.timestamp())

    rule = {
        "minutes": 30,
        "align_mode": "elapsed",
        "all_day": False,
        "start_minute": 540,
        "end_minute": 600,
        "last_fired": datetime.datetime(2026, 10, 30, 9, 0).timestamp(),
    }
    remaining = schedule.seconds_until_next(rule, now)
    assert remaining is not None
    assert remaining > 0.0
    # Next genuine opening is tomorrow 09:00, i.e. 18 hours away.
    assert remaining == pytest.approx(64800.0, abs=1.0)


def test_elapsed_overdue_inside_window_is_immediately_eligible(monkeypatch):
    """Inside the active window an overdue deadline is due right now."""
    import fastprompter.core.interval_schedule as schedule

    now = datetime.datetime(2026, 10, 30, 9, 45)
    monkeypatch.setattr("time.time", lambda: now.timestamp())
    rule = {
        "minutes": 30,
        "align_mode": "elapsed",
        "all_day": False,
        "start_minute": 540,
        "end_minute": 600,
        "last_fired": datetime.datetime(2026, 10, 30, 9, 0).timestamp(),
    }
    assert schedule.seconds_until_next(rule, now) == 0.0


def test_elapsed_future_deadline_keeps_remaining_time(monkeypatch):
    """A deadline still in the future is untouched by the reconciliation."""
    import fastprompter.core.interval_schedule as schedule

    now = datetime.datetime(2026, 10, 30, 9, 10)
    monkeypatch.setattr("time.time", lambda: now.timestamp())
    rule = {
        "minutes": 30,
        "align_mode": "elapsed",
        "all_day": False,
        "start_minute": 540,
        "end_minute": 600,
        "last_fired": datetime.datetime(2026, 10, 30, 9, 0).timestamp(),
    }
    assert schedule.seconds_until_next(rule, now) == pytest.approx(1200.0)


# ---------------------------------------------------------------------------
# R006 - strict import rejects lossy numeric coercion
# ---------------------------------------------------------------------------


def test_strict_import_refuses_fractional_interval_values():
    """CORE-006: ``int(1.9)`` is a silent rewrite, not an import."""
    from fastprompter.core.interval_preset_store import PresetValidationError, clean_preset

    doc = {
        "schema_version": 1,
        "name": "Fractional",
        "kind": "single_rule",
        "rules": [{"minutes": 1.9, "start_minute": 0.5,
                   "end_minute": 1439.5}],
    }
    with pytest.raises(PresetValidationError):
        clean_preset(doc, strict=True)


def test_strict_import_refuses_fractional_schema_version():
    from fastprompter.core.interval_preset_store import (
        PresetValidationError,
        clean_preset,
    )

    with pytest.raises(PresetValidationError):
        clean_preset({"schema_version": 1.5, "name": "V", "kind": "single_rule",
                      "rules": [{"minutes": 30}]}, strict=True)


def test_strict_import_keeps_integer_and_legacy_forms():
    """Valid integers and legacy integer STRINGS must still round-trip."""
    from fastprompter.core.interval_preset_store import clean_preset

    doc = {
        "schema_version": 1,
        "name": "Ints",
        "kind": "single_rule",
        "rules": [{"minutes": "30", "start_minute": "540",
                   "end_minute": 600}],
    }
    out = clean_preset(doc, strict=True)
    rule = out["rules"][0]
    assert (rule["minutes"], rule["start_minute"], rule["end_minute"]) == \
        (30, 540, 600)


def test_non_strict_healing_path_is_unchanged():
    """The compatibility path still heals rather than refusing."""
    from fastprompter.core.interval_preset_store import clean_rule

    healed = clean_rule({"minutes": 1.9, "start_minute": 0.5})
    assert healed["minutes"] == 1
    assert healed["start_minute"] == 0


# ---------------------------------------------------------------------------
# R007 - restore must never publish safety over the selected source
# ---------------------------------------------------------------------------


def _make_state_db(path, marker):
    """A real FastPrompter database whose Code preset carries ``marker``."""
    import fastprompter.core.state as state_mod
    from fastprompter.core.state import FastPrompterState

    os.makedirs(os.path.dirname(path), exist_ok=True)
    state_mod.get_db_path = lambda profile_id=1: path
    state = FastPrompterState(profile_id=1)
    state.data["temp_presets_all"]["Code"][0] = marker
    state.data["categories"]["Code"][0] = {"name": "snip", "text": marker}
    state.mark_dirty()
    state.save_data_to_db(marker, force=True, sync=True)
    state.conn.close()


def _marker_of(path):
    import fastprompter.core.state as state_mod
    from fastprompter.core.state import FastPrompterState

    state_mod.get_db_path = lambda profile_id=1: path
    state = FastPrompterState(profile_id=1)
    value = state.data["temp_presets_all"]["Code"][0]
    state.conn.close()
    return value


def test_restore_safety_source_not_overwritten(tmp_path):
    """W2-001 (P0): selecting the safety path itself must not destroy it.

    The destination of the automatic pre-restore snapshot is deterministic
    (``destination + ".prerestore.bak"``) and nothing compared the SELECTED
    source against it. Restoring from that file therefore overwrote the very
    bytes it was about to read, reported success, and restored "current" while
    the older restore point was gone forever.
    """
    from fastprompter.core.state import restore_database

    live = str(tmp_path / "live.db")
    safety = live + ".prerestore.bak"
    _make_state_db(live, "current")
    _make_state_db(safety, "older")
    before = open(safety, "rb").read()

    restore_database(safety, live)

    assert _marker_of(live) == "older", "the requested older contents must load"
    assert open(safety, "rb").read() == before, \
        "the selected source must stay byte-identical"


def test_restore_from_alias_path_also_protects_the_source(tmp_path):
    """An alternate spelling of the safety path is the same file."""
    from fastprompter.core.state import restore_database

    live = str(tmp_path / "live.db")
    safety = live + ".prerestore.bak"
    _make_state_db(live, "current")
    _make_state_db(safety, "older")
    alias = os.path.join(str(tmp_path), ".", "live.db.prerestore.bak")

    restore_database(alias, live)
    assert _marker_of(live) == "older"


def test_ordinary_restore_still_leaves_a_distinct_safety_copy(tmp_path):
    """A non-aliasing source keeps the normal pipeline and safety artifact."""
    from fastprompter.core.state import restore_database

    live = str(tmp_path / "live.db")
    other = str(tmp_path / "other.db")
    _make_state_db(live, "current")
    _make_state_db(other, "older")

    restore_database(other, live)
    assert _marker_of(live) == "older"
    safety = live + ".prerestore.bak"
    assert os.path.isfile(safety)
    assert _marker_of(safety) == "current"


# ---------------------------------------------------------------------------
# R008 - ambience mutations are atomic across read, decision and commit
# ---------------------------------------------------------------------------


def _ambience_store(path):
    from fastprompter.core.ambience_store import AmbienceStore

    return AmbienceStore(path)


def test_ambience_parallel_upserts_keep_both(tmp_path):
    """W2-002 (P0): two stores, two accepted updates, one survivor.

    ``upsert_rule`` read with ``load_rules`` and then replaced the ENTIRE table
    through ``save_rules``. Each store owned only its own RLock, so the second
    writer's stale snapshot deleted the first writer's row even though both
    calls returned success.
    """
    from fastprompter.core.ambience_store import AmbienceRule, AmbienceStore

    db = str(tmp_path / "audio.db")
    first = _ambience_store(db)
    second = _ambience_store(db)
    first.save_rules([])

    barrier = threading.Barrier(2, timeout=10)
    original = AmbienceStore.load_rules

    def synced(self):
        read = original(self)
        barrier.wait()
        return read

    AmbienceStore.load_rules = synced
    errors = []

    def work(store, rule):
        try:
            store.upsert_rule(rule)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            errors.append(exc)

    threads = [
        threading.Thread(target=work,
                         args=(first, AmbienceRule(id="r0", name="A",
                                                   sound_ref=""))),
        threading.Thread(target=work,
                         args=(second, AmbienceRule(id="r1", name="B",
                                                    sound_ref=""))),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
    finally:
        AmbienceStore.load_rules = original

    assert errors == []
    durable = {rule.id for rule in AmbienceStore(db).load_rules()}
    assert durable == {"r0", "r1"}


def test_ambience_edit_does_not_erase_unreadable_other_rule(tmp_path):
    """W2-002: a corrupt row is recovery evidence, not a candidate for deletion."""
    import sqlite3

    from fastprompter.core.ambience_store import AMBIENCE_TABLE, AmbienceRule

    db = str(tmp_path / "audio.db")
    store = _ambience_store(db)
    store.save_rules([])
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"INSERT INTO {AMBIENCE_TABLE}(id, position, payload) "
            "VALUES(?, ?, ?)", ("bad", 0, "{broken-json"))

    store.upsert_rule(AmbienceRule(id="good", name="G", sound_ref=""))

    with sqlite3.connect(db) as conn:
        ids = {row[0] for row in conn.execute(
            f"SELECT id FROM {AMBIENCE_TABLE}")}
    assert "bad" in ids, "an unreadable row must survive an unrelated edit"
    assert "good" in ids


def test_ambience_ordering_and_reload_unchanged(tmp_path):
    """Stable ids and position order survive a normal write/reload cycle."""
    from fastprompter.core.ambience_store import AmbienceRule

    db = str(tmp_path / "audio.db")
    store = _ambience_store(db)
    store.save_rules([
        AmbienceRule(id="b", name="B", sound_ref=""),
        AmbienceRule(id="a", name="A", sound_ref=""),
    ])
    assert [r.id for r in _ambience_store(db).load_rules()] == ["b", "a"]


# ---------------------------------------------------------------------------
# R009 - portable backup completeness does not depend on cats_order
# ---------------------------------------------------------------------------


def _export(tmp_path, monkeypatch, data):
    import fastprompter.utils.portable_backup as portable_backup

    monkeypatch.setattr(portable_backup, "get_portable_backup_dir",
                        lambda: str(tmp_path / "portable-backup"))
    portable_backup._do_export(dict(data), profile_id=1)
    return tmp_path / "portable-backup"


def test_portable_complete_includes_orphan_snippet(tmp_path, monkeypatch):
    """W2-003 (P1): ``if cats and categories`` skipped every orphan category.

    The category component map is built from the authoritative ``categories``
    mapping precisely so a recovered category missing from ``cats_order`` is
    still exported -- and then the snippet branch was gated on ``cats``. The
    unique text vanished, and ``_COMPLETE`` was published anyway.
    """
    day = _export(tmp_path, monkeypatch, {
        "cats_order": [],
        "categories": {"Orphan": [{"name": "N", "text": "SENTINEL-EXACT"}]},
        "temp_presets_all": {},
        "archive_temp_presets_all": {},
        "temp_presets": [],
        "archive_temp_presets": [],
    })
    exported = [p for p in day.rglob("*.md") if p.is_file()]
    assert any("SENTINEL-EXACT" in p.read_text(encoding="utf-8")
               for p in exported), \
        "the orphan category's snippet must appear in some exported document"


def test_complete_marker_implies_content_present(tmp_path, monkeypatch):
    """``_COMPLETE`` must not certify a snapshot missing user content."""
    root = _export(tmp_path, monkeypatch, {
        "cats_order": [],
        "categories": {"Orphan": [{"name": "N", "text": "SECOND-SENTINEL"}]},
        "temp_presets_all": {},
        "archive_temp_presets_all": {},
        "temp_presets": [],
        "archive_temp_presets": [],
    })
    markers = list(root.rglob("_COMPLETE"))
    assert markers, "a successful export must publish the COMPLETE marker"
    day = markers[0].parent
    assert any("SECOND-SENTINEL" in found.read_text(encoding="utf-8")
               for found in day.rglob("*.md") if found.is_file()), \
        "a COMPLETE generation must actually contain the user's content"


def test_ordered_categories_still_export(tmp_path, monkeypatch):
    """The normal ordered path is unchanged."""
    root = _export(tmp_path, monkeypatch, {
        "cats_order": ["Code"],
        "categories": {"Code": [{"name": "N", "text": "ORDERED-TEXT"}]},
        "temp_presets_all": {},
        "archive_temp_presets_all": {},
        "temp_presets": [],
        "archive_temp_presets": [],
    })
    assert any("ORDERED-TEXT" in found.read_text(encoding="utf-8")
               for found in root.rglob("*.md") if found.is_file())


# ---------------------------------------------------------------------------
# R010 - sound-pack publication enforces PHYSICAL containment
# ---------------------------------------------------------------------------


def _junction(link, target):
    """Create a Windows directory junction; return True on success.

    Junctions need no administrative privilege, which is exactly why the
    lexical prefix check in ``_publish_pack_sounds`` was insufficient: an
    unprivileged user can plant one inside the managed library.
    """
    if os.name != "nt":
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except OSError:
            return False
    result = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                            capture_output=True, text=True)
    return result.returncode == 0 and os.path.isdir(link)


def _wav_bytes(path):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    with open(str(path), "rb") as handle:
        return handle.read()


def test_pack_import_cannot_escape_via_existing_junction(tmp_path):
    """W2-004 (P1): a junction inside ``imported/`` redirected the write.

    ``target.startswith(imported_root + os.sep)`` is a statement about the
    SPELLING of a path, not about where the bytes land. ``os.makedirs`` and
    ``os.replace`` follow the redirected parent, so the pack wrote
    ``outside/escape.wav`` and reported the logical in-library path.
    """
    import fastprompter.core.sound_presets as sound_presets

    sounds = tmp_path / "sounds"
    imported = sounds / "imported"
    outside = tmp_path / "outside"
    imported.mkdir(parents=True)
    outside.mkdir()

    if not _junction(str(imported / "bridge"), str(outside)):
        pytest.skip("cannot create a directory junction/symlink here")

    data = _wav_bytes(tmp_path / "t.wav")
    definition = {
        "events": {},
        "asset_manifest": {"bridge/escape.wav": hashlib.sha256(data).hexdigest()},
    }

    with pytest.raises(Exception):
        sound_presets._publish_pack_sounds(
            {"bridge/escape.wav": data}, str(sounds), definition)

    assert not (outside / "escape.wav").exists(), \
        "the pack must not write outside the managed library"


def test_ordinary_nested_pack_import_still_succeeds(tmp_path):
    """Contained nested members import normally, collision-free."""
    import fastprompter.core.sound_presets as sound_presets

    sounds = tmp_path / "sounds"
    sounds.mkdir()
    data = _wav_bytes(tmp_path / "t.wav")
    definition = {
        "events": {},
        "asset_manifest": {"sub/dir/ok.wav": hashlib.sha256(data).hexdigest()},
    }
    published = sound_presets._publish_pack_sounds(
        {"sub/dir/ok.wav": data}, str(sounds), definition)
    assert len(published) == 1
    assert os.path.isfile(published[0])
    assert os.path.normcase(os.path.abspath(published[0])).startswith(
        os.path.normcase(str(sounds)))


def test_manifest_mismatch_is_refused_before_any_write(tmp_path):
    """The integrity gate still runs first."""
    import fastprompter.core.sound_presets as sound_presets

    sounds = tmp_path / "sounds"
    sounds.mkdir()
    data = _wav_bytes(tmp_path / "t.wav")
    with pytest.raises(ValueError):
        sound_presets._publish_pack_sounds(
            {"a.wav": data}, str(sounds), {"events": {}, "asset_manifest": {}})


# ---------------------------------------------------------------------------
# R011 - personal-audio override resolution fails closed on cycles
# ---------------------------------------------------------------------------


@pytest.fixture
def personal_mode(monkeypatch):
    """conftest forces personal mode OFF for the whole tree; this branch needs it."""
    import fastprompter.core.sound_library as sound_library

    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "1")
    # The env-var path ignores the on-disk table, so the table branch is the
    # one under test: clear the env var and drive the file instead.
    monkeypatch.delenv("FASTPROMPTER_PERSONAL_AUDIO", raising=False)
    sound_library.invalidate_personal_audio_cache()
    yield sound_library
    sound_library.invalidate_personal_audio_cache()


def test_cyclic_personal_override_fails_closed(tmp_path, monkeypatch,
                                               personal_mode):
    """W2-005 (P2): A->B->A recursed until RecursionError escaped to callers."""
    sound_library = personal_mode

    config = tmp_path / "personal.json"
    config.write_text(json.dumps({
        "personal_override": True,
        "overrides": {"a.wav": "b.wav", "b.wav": "a.wav"},
    }), encoding="utf-8")
    monkeypatch.setattr(sound_library, "_personal_config_path",
                        lambda: str(config))
    sound_library.invalidate_personal_audio_cache()

    resolved = sound_library.resolve_sound_ref(
        "a.wav", builtin_root=str(tmp_path), user_root=str(tmp_path),
        addon_root_path=str(tmp_path))
    assert resolved is None


def test_self_override_fails_closed(tmp_path, monkeypatch, personal_mode):
    """A -> A is a cycle too."""
    sound_library = personal_mode

    config = tmp_path / "personal.json"
    config.write_text(json.dumps({
        "personal_override": True,
        "overrides": {"self.wav": "self.wav"},
    }), encoding="utf-8")
    monkeypatch.setattr(sound_library, "_personal_config_path",
                        lambda: str(config))
    sound_library.invalidate_personal_audio_cache()

    assert sound_library.resolve_sound_ref(
        "self.wav", builtin_root=str(tmp_path), user_root=str(tmp_path),
        addon_root_path=str(tmp_path)) is None


def test_valid_override_chain_still_resolves(tmp_path, monkeypatch,
                                             personal_mode):
    """A -> B -> C with a real file at C keeps working."""
    sound_library = personal_mode

    user = tmp_path / "user"
    user.mkdir()
    (user / "c.wav").write_bytes(b"RIFF")
    config = tmp_path / "personal.json"
    config.write_text(json.dumps({
        "personal_override": True,
        "overrides": {"a.wav": "b.wav", "b.wav": "c.wav"},
    }), encoding="utf-8")
    monkeypatch.setattr(sound_library, "_personal_config_path",
                        lambda: str(config))
    sound_library.invalidate_personal_audio_cache()

    resolved = sound_library.resolve_sound_ref(
        "a.wav", builtin_root=str(tmp_path), user_root=str(user),
        addon_root_path=str(tmp_path))
    assert resolved is not None
    assert os.path.basename(resolved) == "c.wav"


# ---------------------------------------------------------------------------
# R012 - coverage ownership lookup must not be quadratic in cold traversal
# ---------------------------------------------------------------------------


def _coverage_map(count):
    from fastprompter.core.silo_coverage import CoverageItem, CoverageMap

    items = tuple(
        CoverageItem(req_id=f"R{i}", line_start=i, line_end=i,
                     text=f"requirement {i}", state="fresh")
        for i in range(count))
    return CoverageMap(requirements=items)


def test_coverage_lookup_is_not_quadratic():
    """PERF-001 (P1): cold traversal must not scan the requirement tuple.

    The defect was that ``get_line_state`` walked BACKWARDS over every earlier
    requirement start for each unseen line, so the first pass cost
    O(lines x requirements). This control inspects the mechanism itself: the
    ownership structure must be bounded by the number of BOUNDARIES (at most
    2N), never by a per-line scan of the requirement tuple.

    A wall-clock ratio is not usable here. It measures the machine and its
    load, not the algorithm: it passed in isolation and failed inside a loaded
    suite run on identical bytes. The audit's own rule -- avoid
    hardware-specific timing pass thresholds -- applies to its own controls.
    """
    for count in (500, 2000):
        coverage = _coverage_map(count)
        assert len(coverage._bounds) <= 2 * count, (
            f"{count} requirements produced {len(coverage._bounds)} "
            "ownership boundaries")
        # Every line resolves, and resolution cannot have consulted more
        # entries than the structure holds.
        assert len(coverage._owners) == len(coverage._bounds)
        for line in range(count):
            owner = coverage._owner_for(line)
            assert owner is not None and owner.req_id == f"R{line}"


def test_ownership_structure_grows_linearly_not_quadratically():
    """A 4x larger document may cost at most ~4x the boundaries, not ~16x."""
    small = len(_coverage_map(250)._bounds)
    large = len(_coverage_map(1000)._bounds)
    assert large <= 4 * small + 4, (
        f"boundary count grew {small} -> {large} for a 4x document")


def test_coverage_lookup_preserves_first_tuple_owner():
    """Overlapping and duplicate-start intervals keep tuple precedence."""
    from fastprompter.core.silo_coverage import CoverageItem, CoverageMap

    items = (
        CoverageItem(req_id="wide", line_start=0, line_end=20, text="w",
                     state="fresh"),
        CoverageItem(req_id="narrow", line_start=5, line_end=5, text="n",
                     state="covered"),
        CoverageItem(req_id="narrow2", line_start=5, line_end=9, text="n2",
                     state="partial"),
    )
    coverage = CoverageMap(requirements=items)
    state, owner = coverage.get_line_state(5)
    assert owner.req_id == "wide", "the first requirement in tuple order wins"
    assert state == "fresh"
    assert coverage.get_line_state(50) == (None, None)


# ---------------------------------------------------------------------------
# R013 - detached-media association must not scale cubic-like
# ---------------------------------------------------------------------------


def _alternating_document(count):
    parts = ["# header\n"]
    for index in range(count):
        parts.append(f"- Requirement {index}\n")
        parts.append(f"![a](media/{index:04d}.png)\n")
    return "".join(parts)


def _build_index(count):
    """Build an index over a detached-media document (no timing involved)."""
    from fastprompter.core.silo_bundle import BundleItem
    from fastprompter.core.silo_index import build_silo_index

    items = [BundleItem(source=f"/x/{i:04d}.png",
                        display_name=f"{i:04d}.png",
                        member=f"media/{i:04d}.png", media_type="image",
                        size=1, added_epoch=0.0, added_source="doc",
                        doc_index=i, origin="inline", available=True)
             for i in range(count)]
    return build_silo_index(_alternating_document(count), "source.md", items)


def _requirement_id_reads(count):
    """How many times indexing reads a requirement ``id``.

    PERF-002 is a COUNT. The defect was that every media block snapshotted
    ``prev_req_ids`` (one ``.id`` read per requirement in the group) and then
    tested membership against that tuple inside a full requirement scan, so
    the reads grew with requirements x blocks. Counting the reads proves the
    mechanism directly; a wall-clock ratio only proves how loaded the machine
    was when the suite happened to run.
    """
    from fastprompter.core import silo_index
    from fastprompter.core.silo_bundle import BundleItem

    items = [BundleItem(source=f"/x/{i:04d}.png",
                        display_name=f"{i:04d}.png",
                        member=f"media/{i:04d}.png", media_type="image",
                        size=1, added_epoch=0.0, added_source="doc",
                        doc_index=i, origin="inline", available=True)
             for i in range(count)]
    reads = [0]
    base = silo_index.RequirementItem

    class _CountingItem(base):
        def __getattribute__(self, name):
            if name == "id":
                reads[0] += 1
            return object.__getattribute__(self, name)

    silo_index.RequirementItem = _CountingItem
    try:
        silo_index.build_silo_index(_alternating_document(count), "source.md",
                                    items)
    finally:
        silo_index.RequirementItem = base
    return reads[0]


def test_detached_media_indexing_reads_each_id_a_bounded_number_of_times():
    """PERF-002 (P1): association cost must be linear in the document.

    Measured on the pre-repair bytes: 50 requirements cost 6673 ``id`` reads
    and 400 cost 403398 -- an 8x document costing 60x. The prefix-slice repair
    makes it 398 and 3198, i.e. 8x for 8x.
    """
    small = _requirement_id_reads(50)
    large = _requirement_id_reads(400)
    assert large <= 16 * small, (
        f"id reads scale superlinearly: 50 -> {small}, 400 -> {large}")
    # Linear shape: no more than a constant number of reads per requirement
    # and per media block.
    assert large <= 40 * 400, f"{large} id reads for 400 requirements"


def test_detached_media_association_is_preserved():
    """Previous/next association and unscoped classification are unchanged."""
    index = _build_index(4)
    assert len(index.requirements) == 4
    assert len(index.media_evidence) == 4
    associations = [e.association for e in index.media_evidence]
    assert associations[0] == "adjacent_previous"
    assert all(a in ("adjacent_previous", "adjacent_next", "group", "unscoped")
               for a in associations)


def test_unscoped_media_are_classified_once():
    """Unscoped evidence identities are unique (no duplicate appends)."""
    from fastprompter.core.silo_bundle import BundleItem
    from fastprompter.core.silo_index import build_silo_index

    items = [BundleItem(source=f"/x/{i:04d}.png", display_name=f"{i:04d}.png",
                        member=f"media/{i:04d}.png", media_type="image",
                        size=1, added_epoch=0.0, added_source="doc",
                        doc_index=i, origin="inline", available=True)
             for i in range(20)]
    index = build_silo_index("# header\n", "source.md", items)
    members = [e.member for e in index.media_evidence if e.association == "unscoped"]
    assert sorted(members) == sorted(set(members))


# ---------------------------------------------------------------------------
# R014 - selection coverage computes invariant work once
# ---------------------------------------------------------------------------


def _selection_document(count):
    return "\n".join(f"- Requirement number {i} with unique body text"
                     for i in range(count))


class _CountingText(str):
    """A string that records how often it is normalized.

    PERF-003 is a COUNT, not a duration: the defect was that
    ``selected_text.split()`` ran once per requirement. Counting the calls
    proves the mechanism directly. A wall-clock ratio can be flattered by a
    fast machine and can also fail on a loaded one -- neither says anything
    about whether the invariant work was hoisted.
    """

    splits = 0

    def split(self, *args, **kwargs):
        type(self).splits += 1
        return super().split(*args, **kwargs)


def test_selection_normalizes_the_selection_once_not_per_requirement():
    """PERF-003 (P1): selected_text was re-split for EVERY requirement.

    The count must not grow with the document: 50 requirements and 1600
    requirements must both normalize at most once.
    """
    from fastprompter.core.silo_coverage import create_bundle_coverage_event

    counts = {}
    for count in (50, 1600):
        document = _selection_document(count)
        _CountingText.splits = 0
        event = create_bundle_coverage_event(
            silo_id="S", bundle_kind="selection", archive_name="a.zip",
            markdown_text=document, selected_text=_CountingText(document),
            selected_span=(0, len(document)))
        assert len(event.receipts) == count
        counts[count] = _CountingText.splits

    assert counts[1600] <= 1, (
        f"{counts[1600]} normalizations for 1600 requirements")
    assert counts[1600] == counts[50], (
        f"normalization count scales with document size: {counts}")


def test_supplied_text_does_not_change_receipts_over_the_exact_span():
    """Both fields supplied must yield exactly what span-only yields."""
    from fastprompter.core.silo_coverage import create_bundle_coverage_event

    document = _selection_document(200)
    span = (0, len(document))

    def build(selected_text):
        event = create_bundle_coverage_event(
            silo_id="S", bundle_kind="selection", archive_name="a.zip",
            markdown_text=document, selected_text=selected_text,
            selected_span=span)
        return [(r.coverage_key, r.duplicate_ordinal, r.coverage_kind,
                 r.covered_segment) for r in event.receipts]

    assert build(document) == build(None)


def test_selection_classification_is_unchanged():
    """Full/partial classification, ordinals and identity stay identical."""
    from fastprompter.core.silo_coverage import create_bundle_coverage_event

    document = _selection_document(3)
    full = create_bundle_coverage_event(
        silo_id="S", bundle_kind="selection", archive_name="a.zip",
        markdown_text=document, selected_text=document,
        selected_span=(0, len(document)))
    assert len(full.receipts) == 3
    assert {r.coverage_kind for r in full.receipts} == {"full"}
    assert [r.duplicate_ordinal for r in full.receipts] == [1, 1, 1]


def test_partial_selection_stays_partial():
    """A selection covering only the first requirement is partial at most."""
    from fastprompter.core.silo_coverage import create_bundle_coverage_event

    document = _selection_document(3)
    first_line = document.splitlines()[0]
    event = create_bundle_coverage_event(
        silo_id="S", bundle_kind="selection", archive_name="a.zip",
        markdown_text=document, selected_text=first_line,
        selected_span=(0, len(first_line)))
    assert event is not None
    covered = [r for r in event.receipts]
    assert len(covered) == 1
    assert covered[0].coverage_kind in ("full", "partial")
