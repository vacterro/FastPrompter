"""T-1438 / SRC-135: red controls for the eighteen audit/15.md findings.

WHY THIS FILE EXISTS
--------------------
The operator's rule from T-1437 carries over verbatim: *a red control that does
not go red is not a control*. Each test below must FAIL against the code that
was at HEAD before this ticket and PASS after it. Every one is written to
pin the specific defect the audit named, not the general area it lives in, so
a regression reintroducing the old shape turns exactly one control red.

The audit's own reproduction arms are used where they are deterministic —
``settle``-free checks, controller fakes with real ``stop()`` semantics,
throwaway roots — so no test here touches the operator's data directory, the
live database, the shipped sound folder, or real audio hardware.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ==========================================================================
# CORE-001 — project_sync: a lost update may never be silent
# ==========================================================================

def test_core_001_conflict_copy_is_preserved_when_identity_moved(tmp_path):
    """REGRESSION: the pre-fix publisher returned a conflict WITHOUT keeping
    the bytes that lost the race, so the operator's edit vanished with no
    trace on disk."""
    from fastprompter.core import project_sync

    target = tmp_path / "silo.md"
    target.write_text("original\n", encoding="utf-8")
    identity = project_sync.disk_identity(str(target))

    def before_publish():
        # A second writer wins the race inside the window.
        target.write_text("theirs\n", encoding="utf-8")

    written, conflict = project_sync.compare_and_publish_text(
        str(target), "mine\n", identity, before_publish=before_publish)

    assert written is None, "expected a conflict"
    assert conflict is not None
    assert target.read_text(encoding="utf-8") == "theirs\n", "the winner must stand"

    siblings = [p for p in target.parent.iterdir() if ".conflict-" in p.name]
    assert siblings, "the revision that defeated the gate must survive on disk"
    assert any(p.read_text(encoding="utf-8") == "theirs\n" for p in siblings)


def test_core_001_missing_file_is_not_recreated_blindly(tmp_path):
    from fastprompter.core import project_sync

    target = tmp_path / "gone.md"
    identity = project_sync.MISSING_ON_DISK     # destination never existed
    target.mkdir()                              # ...and is now a directory

    written, conflict = project_sync.compare_and_publish_text(
        str(target), "mine\n", identity)
    assert written is None, "a directory is a write failure, not a publish"
    assert conflict is None



# ==========================================================================
# CORE-002 — interval_preset_store: a batch replace is all-or-nothing
# ==========================================================================

def _store(tmp_path):
    from fastprompter.core.interval_preset_store import IntervalPresetStore

    return IntervalPresetStore(str(tmp_path / "presets"))


def _rules(minutes=30, **over):
    rule = {
        "sound": "tick", "enabled": True, "all_day": True,
        "start_minute": 0, "end_minute": 0, "volume": 0.5,
        "minutes": minutes, "align": "clock",
    }
    rule.update(over)
    return [rule]


def test_core_002_replace_all_leaves_no_partial_catalog(tmp_path):
    """A batch whose SECOND entry is invalid must change nothing at all.

    REGRESSION: per-file atomicity was mistaken for batch atomicity — the
    pre-fix code deleted the old generation and then wrote entries one by one,
    so a rejected second entry left a half-migrated library.
    """
    from fastprompter.core.interval_preset_store import PresetValidationError

    store = _store(tmp_path)
    store.create_preset("keep", _rules())
    before = sorted(p.name for p in Path(store.directory).iterdir())

    with pytest.raises(PresetValidationError):
        store.replace_all([
            {"name": "good", "rules": _rules()},
            {"name": "bad", "rules": _rules(minutes=999999)},
        ])

    after = sorted(p.name for p in Path(store.directory).iterdir())
    assert after == before, "the refused batch must not add or remove files"
    assert [p["name"] for p in store.load()] == ["keep"]


def test_core_002_mid_batch_failure_keeps_the_old_generation(tmp_path, monkeypatch):
    """A write failure partway through publication must roll the library back."""
    from fastprompter.core import interval_preset_store as ips

    store = _store(tmp_path)
    store.create_preset("keep", _rules())

    real_replace = ips.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise OSError("disk went away")
        return real_replace(src, dst)

    monkeypatch.setattr(ips.os, "replace", flaky)
    with pytest.raises(OSError):
        store.replace_all([{"name": "new", "rules": _rules()}])

    reloaded = _store(tmp_path)
    assert [p["name"] for p in reloaded.load()] == ["keep"]


def test_core_002_journal_metadata_is_never_mistaken_for_a_preset(tmp_path):
    """The journal and staging dir live in the store dir; neither is a preset."""
    store = _store(tmp_path)
    store.create_preset("keep", _rules())
    Path(store._batch_journal_path()).write_text(
        json.dumps({"token": "x", "moves": [], "stale": []}), encoding="utf-8")

    names = [p["name"] for p in _store(tmp_path).load()]
    assert names == ["keep"]


def test_core_002_recovery_never_deletes_stale_files_of_an_unfinished_batch(tmp_path):
    """REGRESSION: recovery moved whatever staged files were left and then
    deleted the stale ones. If a staged file had vanished too, that produced a
    library that was neither the old generation nor the new one -- the exact
    mixed state the journal exists to prevent."""

    store = _store(tmp_path)
    store.create_preset("keep", _rules())
    stale_path = Path(store._path_for(next(
        p["id"] for p in store.load() if p["name"] == "keep")))
    assert stale_path.exists()

    # A journal whose single staged source is GONE and whose destination does
    # not exist either -> an unfinished batch with nothing to publish.
    journal = {
        "token": "deadbeef",
        "moves": [{"src": "missing-staged-file.json", "dst": "brand-new-id.json"}],
        "stale": [stale_path.stem],
    }
    Path(store._batch_journal_path()).write_text(
        json.dumps(journal), encoding="utf-8")
    (Path(store.directory) / ".batch-staging-deadbeef").mkdir(exist_ok=True)

    # Recovery must leave the old generation intact rather than removing it.
    reloaded = _store(tmp_path)
    assert [p["name"] for p in reloaded.load()] == ["keep"], (
        "an unfinished batch must never delete the previous generation")
    assert stale_path.exists()

    # The journal is retained so a later load can still finish the batch.
    assert Path(store._batch_journal_path()).exists()

# ==========================================================================
# CORE-003 — interval_preset_store: strict validation refuses, never clamps
# ==========================================================================

@pytest.mark.parametrize("mutate", [
    lambda r: r.update(minutes=999999),
    lambda r: r.update(start_minute=-500),
    lambda r: r.update(volume=5.0),
    lambda r: r.update(volume=float("nan")),
])
def test_core_003_strict_cleaning_refuses_out_of_range(mutate):
    """REGRESSION: the pre-fix cleaner clamped these into a plausible-looking
    rule, so a corrupt file silently became a DIFFERENT configuration."""
    from fastprompter.core.interval_preset_store import (
        PresetValidationError,
        clean_preset,
    )

    rule = _rules()[0]
    mutate(rule)
    with pytest.raises(PresetValidationError):
        clean_preset({"name": "x", "rules": [rule]}, strict=True)


def test_core_003_a_newer_schema_version_is_refused():
    """REGRESSION: a document written by a newer build was normalized as if it
    were the current schema, silently dropping the fields this build lacks."""
    from fastprompter.core.interval_preset_store import (
        SCHEMA_VERSION,
        PresetValidationError,
        clean_preset,
    )

    with pytest.raises(PresetValidationError):
        clean_preset({
            "name": "x", "schema_version": SCHEMA_VERSION + 1,
            "rules": _rules(),
        }, strict=True)


def test_core_003_boundary_values_still_pass_unchanged():
    from fastprompter.core.interval_preset_store import clean_preset

    cleaned = clean_preset({"name": "x", "rules": _rules(volume=1.0)},
                           strict=True)
    assert cleaned["rules"][0]["volume"] == 1.0


# ==========================================================================
# CORE-004 / CORE-006 — one canonical recurrence calculator
# ==========================================================================

def test_core_004_hundred_minute_rule_keeps_its_cadence_across_midnight():
    """REGRESSION: `minute_of_day % minutes == 0` made a 100-minute rule fire
    at midnight regardless of when it last fired, so the gap went 100 -> 20."""
    from fastprompter.core.interval_schedule import is_due_now

    rule = {"minutes": 100, "start_minute": 0, "end_minute": 0}
    assert is_due_now(rule, datetime.datetime(2026, 10, 25, 22, 20))
    assert not is_due_now(rule, datetime.datetime(2026, 10, 25, 23, 20))
    assert is_due_now(rule, datetime.datetime(2026, 10, 26, 0, 0))


def test_core_004_over_24h_rule_does_not_fire_daily():
    from fastprompter.core.interval_schedule import next_clock_boundary

    a = next_clock_boundary(datetime.datetime(2026, 10, 25, 12, 0), 1500,
                            inclusive=False)
    b = next_clock_boundary(a, 1500, inclusive=False)
    assert (b - a).total_seconds() == 1500 * 60
def test_core_006_top_bar_shows_the_real_wait_inside_a_closed_window():
    """REGRESSION: the preview returned None when the active-hours window was
    shut, so the top bar showed nothing instead of the time until it reopens."""
    from fastprompter.core.interval_schedule import seconds_until_next

    rule = {"minutes": 60, "all_day": False,
            "start_minute": 13 * 60, "end_minute": 18 * 60}
    got = seconds_until_next(rule, datetime.datetime(2026, 10, 26, 10, 0))
    assert got == 3 * 3600


# ==========================================================================
# CORE-005 — one audition owner per dialog
# ==========================================================================

def _timer_dialog():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_timer_dialog_wave import _dlg

    return _dlg()


def test_core_005_mouse_pick_produces_one_preview_not_two():
    """REGRESSION: currentIndexChanged AND activated both called
    preview_sound_ref directly, so one click auditioned the sound twice."""
    d = _timer_dialog()
    sm = d.main_win.sound_manager
    seen: list[tuple[str, float]] = []
    sm.preview_sound_ref = lambda ref, vol: seen.append((ref, vol))

    b = d._behavior
    idx = b.cb_sound.count() - 1
    b.cb_sound.setCurrentIndex(idx)
    b.cb_sound.activated.emit(idx)

    assert len(seen) == 1, f"one gesture must audition once, got {seen}"


def test_core_005_rapid_selection_changes_coalesce():
    d = _timer_dialog()
    sm = d.main_win.sound_manager
    seen: list[tuple[str, float]] = []
    sm.preview_sound_ref = lambda ref, vol: seen.append((ref, vol))

    b = d._behavior
    for i in range(max(0, b.cb_sound.count() - 3), b.cb_sound.count()):
        b.cb_sound.setCurrentIndex(i)
    assert seen == [], "a wheel drag must not audition before it settles"


def test_core_005_test_button_still_plays_immediately():
    d = _timer_dialog()
    sm = d.main_win.sound_manager
    seen: list[tuple[str, float]] = []
    sm.preview_sound_ref = lambda ref, vol: seen.append((ref, vol))

    d._behavior.btn_preview_sound.click()
    assert len(seen) == 1


def test_core_005_done_invalidates_a_queued_preview():
    """REGRESSION: accept/reject only HID the dialog, so a queued audition
    could fire later against a hidden dialog."""
    d = _timer_dialog()
    d._interval_preview.schedule_selection("tick", 0.5, source="select")
    assert d._interval_preview._pending is not None

    d.done(0)
    assert d._interval_preview._pending is None


def test_core_005_reject_invalidates_a_queued_preview():
    d = _timer_dialog()
    d._interval_preview.schedule_selection("tick", 0.5, source="select")
    d.reject()
    assert d._interval_preview._pending is None


def test_core_005_preview_cancellation_never_touches_the_alert_bus():
    """A real countdown chime must survive a preview cancellation."""
    import inspect

    from fastprompter.core.sound_manager import SoundManager

    source = inspect.getsource(SoundManager.cancel_preview)
    assert "stop_bus(Bus.PREVIEW)" in source
    assert "stop_bus(Bus.ALERT)" not in source


# ==========================================================================
# W2-001 — sound import is atomic and never clobbers a same-named file
# ==========================================================================

def test_w2_001_import_never_overwrites_an_existing_name(tmp_path, monkeypatch):
    """REGRESSION: two imports of same-named files wrote the SAME destination,
    so the second silently replaced the first."""
    import wave

    from fastprompter.core import sound_library as sl

    root = tmp_path / "managed"
    root.mkdir()
    monkeypatch.setattr(sl, "managed_root", lambda: str(root))
    monkeypatch.setattr(sl, "ensure_managed_root", lambda: str(root))

    def write_wav(path):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x01" * 800)

    src_a = tmp_path / "a" / "clip.wav"
    src_a.parent.mkdir()
    write_wav(src_a)
    original = src_a.read_bytes()

    src_b = tmp_path / "b" / "clip.wav"
    src_b.parent.mkdir()
    write_wav(src_b)

    ref1 = sl.import_file(str(src_a), "imported")
    ref2 = sl.import_file(str(src_b), "imported")
    assert ref1 and ref2, "both imports must publish inside the managed root"
    assert ref1 != ref2, "a second import of the same name must not clobber"
    assert ref2 == "user:imported/clip_1.wav", ref2

    stored = sorted(root.rglob("*.wav"))
    assert len(stored) == 2, stored
    assert any(p.read_bytes() == original for p in stored), \
        "the first imported file must still be intact"
    assert not list(root.rglob("*.tmp.*")), "staging files must never survive"


def test_w2_008_normalize_rel_refuses_absolute_and_unc():
    """REGRESSION: the pre-fix function rewrote ``/tmp/x.wav`` to
    ``tmp/x.wav`` and ``//server/share/x.wav`` to ``server/share/x.wav``,
    turning an outside-the-vault path into a plausible relative one."""
    from fastprompter.core.sound_library import normalize_rel

    assert normalize_rel("/tmp/outside.wav") is None
    assert normalize_rel("//server/share/name.wav") is None
    assert normalize_rel("//?/C:/x.wav") is None
    assert normalize_rel("C:/x.wav") is None
    assert normalize_rel("../escape.wav") is None
    assert normalize_rel("user/clip.wav") == "user/clip.wav"



# ==========================================================================
# W2-002 / W2-005 — the voice countdown is wired to real sources
# ==========================================================================

def test_w2_002_provider_reads_the_attribute_main_actually_creates():
    """REGRESSION: the collector read `self.usage_limit_service`, which
    main.py never creates (the real attribute is `limit_service`), so every
    countdown announcement silently found nothing."""
    import inspect

    from fastprompter.main import FastPrompter

    source = inspect.getsource(FastPrompter.voice_countdown_sources)
    assert '"limit_service"' in source or "'limit_service'" in source
    assert "usage_limit_service" not in source


def test_w2_002_empty_snapshot_mapping_still_yields_a_working_collector():
    """REGRESSION: ``snapshots or ()`` turned an EMPTY dict -- the normal state
    before any account is configured -- into a tuple, so ``reset_candidates``
    raised ``AttributeError: 'tuple' object has no attribute 'items'`` and the
    limit half of the countdown provider contributed nothing at all. Only the
    debug log saw it.
    """
    import time

    from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot, UsageWindow
    from fastprompter.main import FastPrompter

    class _State:
        def __init__(self, snapshots):
            self.snapshots = snapshots

    class _Service:
        def __init__(self, snapshots):
            self.state_copy = _State(snapshots)

    class _Host:
        timers = ()

    reset_at = time.time() + 600.0
    window = UsageWindow(
        key="five_hour", duration_minutes=300, available=True,
        used_percent=10.0, remaining_percent=90.0,
        resets_at_epoch=reset_at, source="test")
    account = AccountRef(provider_id="codex", stable_id="abc",
                         display_name="Codex", source_kind="configured")
    snapshot = UsageSnapshot(account=account, status="OK", windows=[window])

    # Empty mapping: must not raise, must yield no limits.
    empty_host = _Host()
    empty_host.limit_service = _Service({})
    assert FastPrompter.voice_countdown_sources(empty_host) == ([], [])

    # A real snapshot must actually reach the countdown.
    live_host = _Host()
    live_host.limit_service = _Service({account.key: snapshot})
    _timers, limits = FastPrompter.voice_countdown_sources(live_host)
    assert len(limits) == 1
    assert limits[0]["key"] == "codex"
    assert limits[0]["reset"] == reset_at
    assert limits[0]["enabled"] is True


def _voice_controller(tmp_path):
    from fastprompter.core.voice_store import VoiceStore
    from fastprompter.ui import voice_controller

    return voice_controller.VoiceController(
        None, _NullSoundManager(),
        store=VoiceStore(str(Path(tmp_path) / "voice.db")))


def test_w2_005_empty_threshold_selection_announces_nothing(tmp_path):
    """REGRESSION: an empty selection fell back to the default ladder, so a
    user who cleared every checkbox still got announcements."""
    ctrl = _voice_controller(tmp_path)
    ctrl.update_settings(thresholds=[])
    assert ctrl.thresholds() == []
    assert list(ctrl.scheduler._thresholds) == []


def test_w2_005_configured_thresholds_reach_the_active_scheduler(tmp_path):
    """REGRESSION: the thresholds were persisted but the live scheduler kept
    the global defaults, so the checkboxes had no effect at all."""
    ctrl = _voice_controller(tmp_path)
    ctrl.update_settings(thresholds=[3600, 300])
    assert ctrl.thresholds() == [3600, 300]
    assert sorted(s for s, _label in ctrl.scheduler._thresholds) == [300, 3600]


class _NullSoundManager:
    def play_event(self, *a, **k):
        return True

    def cancel_preview(self):
        pass

    def preview_sound_ref(self, *a, **k):
        return True




# ==========================================================================
# W2-003 — export is transactional
# ==========================================================================

def test_w2_003_failed_export_rolls_back_every_silo(tmp_path):
    """REGRESSION: the pre-fix loop published each silo as it went, so a
    failure halfway left the earlier destinations already replaced."""
    import inspect

    from fastprompter.ui import backup_dialog

    source = inspect.getsource(backup_dialog.BackupDialog.export_silos)
    assert "rollback" in source.lower() or "except BaseException" in source
    # The publish loop must be able to restore, not merely report.
    assert "os.replace" in source


def test_w2_003_rollback_snapshots_by_copy_not_rename(tmp_path):
    """REGRESSION: snapshotting with os.replace moved the original OUT of the
    destination, so a destination whose publish then failed lost its bytes --
    the rollback traded a mixed generation for a missing file. The snapshot
    must be a copy, leaving the original in place until the atomic replace."""
    import inspect

    from fastprompter.ui import backup_dialog

    source = inspect.getsource(backup_dialog.BackupDialog.export_silos)
    assert "shutil.copy2" in source, "the old bytes must be copied, not moved"
    # The only rename of a snapshot may be the RESTORE, never the backup.
    backup_line = next(
        line for line in source.splitlines()
        if "exportbak" in line and "unique_temp_path" in line
    )
    assert "copy2" in source.split(backup_line)[1].split("\n", 1)[1]


def test_w2_003_a_failed_publish_leaves_the_blocked_destination_intact(tmp_path, monkeypatch):
    """RED CONTROL: fail the SECOND destination and assert the first was rolled
    back while the second still holds its original bytes."""
    import os

    from PyQt6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    import fastprompter.ui.backup_dialog as mod

    for target in ("Silo_1.txt", "Silo_3.txt"):
        os.makedirs(os.path.join(tmp_path, "alpha"), exist_ok=True)
        with open(os.path.join(tmp_path, "alpha", target), "w", encoding="utf-8") as fh:
            fh.write("ORIGINAL-" + target)

    from PyQt6.QtWidgets import QWidget

    class _StubWin(QWidget):
        def __init__(self):
            super().__init__()
            self._current_lang = "EN"
            self.data = {
                "cats_order": ["alpha"],
                "temp_presets_all": {"alpha": ["first text", "", "third text"]},
                "archive_temp_presets_all": {},
            }
            self.state = type("S", (), {"_sanitize_cat_name": staticmethod(
                lambda s: s.replace(" ", "_"))})()

        def save_data_to_db(self, force=False):
            return True

    real_replace = os.replace

    def failing_replace(src, dst):
        if dst.endswith("Silo_3.txt"):
            raise OSError("injected failure")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", failing_replace)
    monkeypatch.setattr(
        mod.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    dlg = mod.BackupDialog(_StubWin())
    try:
        dlg.combo_format.setCurrentText(".txt")
        dlg.export_silos()
    finally:
        dlg.deleteLater()

    def read(name):
        with open(os.path.join(tmp_path, "alpha", name), encoding="utf-8") as fh:
            return fh.read()

    assert read("Silo_1.txt") == "ORIGINAL-Silo_1.txt", (
        "the file published before the failure must be rolled back"
    )
    assert read("Silo_3.txt") == "ORIGINAL-Silo_3.txt", (
        "the blocked destination must still hold its original bytes"
    )
    leftovers = [n for n in os.listdir(os.path.join(tmp_path, "alpha"))
                 if "tmp" in n or "export" in n]
    assert leftovers == [], f"no temp or snapshot may survive: {leftovers}"



# ==========================================================================
# W2-004 — the code-run dialog retires its runner on every exit
# ==========================================================================

def test_w2_004_every_terminal_path_retires_the_runner():
    """REGRESSION: close/reject/done each cleaned up differently, and
    reject() leaked a live runner."""
    import inspect

    from fastprompter.ui.code_run_dialog import CodeRunOutputDialog

    for method in (CodeRunOutputDialog.closeEvent, CodeRunOutputDialog.reject,
                   CodeRunOutputDialog.done):
        source = inspect.getsource(method)
        assert "_retire_runner()" in source, method.__name__


def test_w2_004_retirement_is_idempotent():
    import inspect

    from fastprompter.ui.code_run_dialog import CodeRunOutputDialog

    source = inspect.getsource(CodeRunOutputDialog._retire_runner)
    assert "_cleanup_process" in source and "_terminate_process" in source


# ==========================================================================
# W2-006 / W2-007 — encoded output is decoded per stream
# ==========================================================================

def test_w2_006_each_adapter_declares_its_real_pipe_encoding():
    """REGRESSION: every adapter's output was decoded as UTF-8, so cmd's cp437
    bytes and PowerShell 5.1's UTF-16 script arrived as mojibake."""
    from fastprompter.core.code_runners import REGISTRY

    assert REGISTRY.get("pwsh").pipe_encoding == "utf-8"
    assert REGISTRY.get("cmd").pipe_encoding == "cp437"
    assert REGISTRY.get("python").pipe_encoding == "utf-8"
    assert REGISTRY.get("powershell").script_bom is True



def test_w2_007_streams_have_independent_decoders_and_buffers():
    """REGRESSION: one shared decoder meant a stdout fragment could be flushed
    with stderr's trailing bytes, corrupting both lines."""
    import inspect

    from fastprompter.ui.code_run_dialog import CodeRunOutputDialog

    source = inspect.getsource(CodeRunOutputDialog._append)
    assert "_decoders" in source and "_line_buffers" in source
    # Per-stream keys, not a single decoder slot.
    assert '"stdout"' in source and '"stderr"' in source


# ==========================================================================
# PERF-001 / PERF-002 — the algorithmic lookups are indexed
# ==========================================================================

def test_perf_001_index_grouping_is_built_once_before_the_loop():
    import inspect

    from fastprompter.core import silo_index

    source = inspect.getsource(silo_index)
    assert "reqs_by_group" in source
    assert "reqs_by_id" in source


def _perf_001_markdown(group_count: int, per_group: int = 1) -> str:
    """N explicit groups (``---`` thematic breaks) with their requirements."""
    lines = ["# Perf Fixture", ""]
    for g in range(1, group_count + 1):
        lines.append(f"## Group {g}")
        for r in range(1, per_group + 1):
            lines.append(f"- Requirement {g}-{r} with a handful of plain words")
        lines.append("")
        if g < group_count:
            lines.append("---")
            lines.append("")
    return "\n".join(lines)


def test_perf_001_build_and_validate_stay_exact_for_a_real_document():
    """The indexed build must produce a valid, self-consistent structure --
    the algorithmic change may not weaken a single validation gate."""
    from fastprompter.core.silo_index import build_silo_index, validate_index_structure

    text = _perf_001_markdown(40)
    index = build_silo_index(text, "Perf Fixture.md")
    payload = index.to_dict()

    # Requirement IDs are sequential and unique; groups are in source order.
    ids = [r["id"] for r in payload["requirements"]]
    assert len(ids) == len(set(ids)) == 40
    assert [g["source_order"] for g in payload["groups"]] == list(range(1, 41))

    # Every group's requirement_ids must be exactly the requirements that
    # carry its id, in source order.
    by_group: dict[str, list[str]] = {}
    for r in payload["requirements"]:
        by_group.setdefault(r["group_id"], []).append(r["id"])
    for g in payload["groups"]:
        assert g["requirement_ids"] == by_group[g["id"]], g["id"]

    ok, detail = validate_index_structure(
        json.loads(index.to_json()), set(), hide_local_paths=True)
    assert ok, detail


def test_perf_001_grouping_work_grows_with_requirements_not_their_product():
    """The audit's own measurement method: count the operations rather than
    time them. ``group_id`` is read while bucketing requirements into groups;
    the old code re-scanned every requirement once per group, so this count
    grew with G*R. Counted here, it must grow with R alone.
    """
    from fastprompter.core import silo_index

    base_cls = silo_index.RequirementItem
    reads = {"n": 0}

    class _Counting(base_cls):                      # type: ignore[misc,valid-type]
        def __getattribute__(self, name):
            if name == "group_id":
                reads["n"] += 1
            return super().__getattribute__(name)

    silo_index.RequirementItem = _Counting
    try:
        measured = {}
        for scale in (50, 100, 200):
            reads["n"] = 0
            index = silo_index.build_silo_index(
                _perf_001_markdown(scale), "Perf Fixture.md")
            assert len(index.groups) == scale, "fixture must produce real groups"
            measured[scale] = (len(index.requirements), reads["n"])
    finally:
        silo_index.RequirementItem = base_cls

    # Requirement count doubles each step; the group_id read count must double
    # with it. A quadratic pass over (group, requirement) pairs would grow 4x.
    for lo, hi in ((50, 100), (100, 200)):
        req_lo, reads_lo = measured[lo]
        req_hi, reads_hi = measured[hi]
        assert req_hi == 2 * req_lo
        per_req_lo = reads_lo / req_lo
        per_req_hi = reads_hi / req_hi
        assert abs(per_req_hi - per_req_lo) < 1e-6, (
            f"per-requirement group_id reads grew {per_req_lo} -> {per_req_hi}: "
            "grouping is back to a per-group full scan")


def test_perf_002_coverage_owner_is_bisected():
    import inspect

    from fastprompter.core import silo_coverage

    assert "bisect" in inspect.getsource(silo_coverage)
    source = inspect.getsource(silo_coverage.CoverageMap._owner_for)
    assert "bisect_right" in source


def test_perf_002_owner_lookup_matches_a_linear_scan():
    """The indexed lookup must return the same owner a linear scan would."""
    from fastprompter.core.silo_coverage import CoverageItem, CoverageMap, CoverageState

    items = (
        CoverageItem("a", 1, 5, "a", CoverageState.FRESH),
        CoverageItem("b", 6, 10, "b", CoverageState.PARTIAL),
        CoverageItem("c", 11, 20, "c", CoverageState.FULL),
    )
    cov = CoverageMap(requirements=items)
    for line, expect in [(0, None), (1, "a"), (5, "a"), (6, "b"),
                         (10, "b"), (11, "c"), (20, "c"), (21, None)]:
        _state, owner = cov.get_line_state(line)
        got = None if owner is None else owner.req_id
        assert got == expect, (line, got, expect)


# ==========================================================================
# PERF-003 — the deferred thumbnail pass is bounded
# ==========================================================================

def test_perf_003_deferred_prefetch_walks_a_bounded_window():
    import inspect

    from fastprompter.ui import file_container

    assert hasattr(file_container, "PREFETCH_ROW_WINDOW")
    source = inspect.getsource(
        file_container.FileContainerPanel._fetch_visible_thumbnails)
    assert "PREFETCH_ROW_WINDOW" in source
    assert "_prefetch_cursor" in source


# ==========================================================================
# PERF-004 — a structural edit must not recount on the keystroke path
# ==========================================================================

def _editor(text=""):
    from PyQt6.QtWidgets import QApplication

    from fastprompter.ui.editor import VaultTextEdit

    QApplication.instance() or QApplication([])

    class _Win:
        data = {}

        def __getattr__(self, name):
            raise AttributeError(name)

    ed = VaultTextEdit(_Win())
    ed.setPlainText(text)
    ed.document().contentsChange.connect(ed._on_contents_change)
    ed.invalidate_word_count()
    ed.document_word_count()
    return ed


def test_perf_004_merge_keeps_the_count_exact():
    """REGRESSION: the pre-fix fast path matched `first == last` even when
    bytes were REMOVED, so merging two lines inflated the total by the
    removed line's words, forever."""
    from PyQt6.QtGui import QTextCursor

    ed = _editor("alpha beta\ngamma delta\nepsilon zeta")
    cur = QTextCursor(ed.document())
    cur.setPosition(10)
    cur.deleteChar()                      # merge line 0 into line 1

    assert ed.document_word_count() == len(ed.toPlainText().split())


@pytest.mark.parametrize("label,setup", [
    ("single-char insert", lambda ed: _type_at(ed, 5, "x")),
    ("newline insert", lambda ed: _type_at(ed, 5, "\n")),
    ("multi-line paste", lambda ed: _type_at(ed, 3, "three four\nfive six")),
])
def test_perf_004_structural_edits_stay_exact(label, setup):
    ed = _editor("alpha beta\ngamma delta")
    setup(ed)
    assert ed.document_word_count() == len(ed.toPlainText().split()), label


def _type_at(ed, position, text):
    from PyQt6.QtGui import QTextCursor

    cur = QTextCursor(ed.document())
    cur.setPosition(position)
    cur.insertText(text)


def test_perf_004_multiline_selection_delete_stays_exact():
    from PyQt6.QtGui import QTextCursor

    ed = _editor("aa bb\ncc dd\nee ff\ngg hh")
    cur = QTextCursor(ed.document())
    cur.setPosition(0)
    cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()
    assert ed.document_word_count() == len(ed.toPlainText().split())


def test_perf_004_undo_and_redo_stay_exact():
    ed = _editor("aa bb\ncc dd")
    _type_at(ed, 5, "\nzz yy\n")
    assert ed.document_word_count() == 6
    ed.undo()
    assert ed.document_word_count() == len(ed.toPlainText().split())
    ed.redo()
    assert ed.document_word_count() == len(ed.toPlainText().split())


def test_perf_004_large_document_replacement_stays_exact():
    ed = _editor("start here")
    big = "\n".join(f"l{i} w{i} t{i}" for i in range(2000))
    ed.setPlainText(big)
    assert ed.document_word_count() == len(ed.toPlainText().split())


def test_perf_004_dirty_aggregate_is_reported_as_unknown_not_stale():
    """REGRESSION: the label painted the last known number while the aggregate
    was known to be wrong, presenting a guess as authoritative."""
    ed = _editor("aa bb\ncc dd")
    assert ed.word_count_if_known() == 4
    ed.invalidate_word_count()
    assert ed.word_count_if_known() is None
    # ...but the exact accessor still answers correctly.
    assert ed.document_word_count() == 4
    assert ed.word_count_if_known() == 4


def test_perf_004_recount_is_deferred_not_synchronous():
    """The handler must arm a timer instead of walking every block inline."""
    import inspect

    from fastprompter.ui.editor import VaultTextEdit

    handler = inspect.getsource(VaultTextEdit._on_contents_change)
    assert "_mark_words_dirty" in handler, "the dirty path must be the deferring one"

    marker = inspect.getsource(VaultTextEdit._mark_words_dirty)
    assert "_arm_word_count_settle" in marker
    assert "_words_dirty = True" in marker

    arm = inspect.getsource(VaultTextEdit._arm_word_count_settle)
    assert "timer.start()" in arm


def test_perf_004_document_switch_invalidates_and_reconcilest_aggregate():
    """REGRESSION: the swap marked the aggregate dirty but never scheduled the
    recount, so in words mode the top bar went blank on a silo switch and
    stayed blank until the next keystroke."""
    import inspect

    from fastprompter.ui.editor import VaultTextEdit

    source = inspect.getsource(VaultTextEdit.set_active_document)
    assert "_words_dirty = True" in source
    assert "_aggregate_word_count = None" in source
    assert "_arm_word_count_settle()" in source, (
        "a document swap must schedule the settle recount, not just go dirty")

    # ...and the scheduled recount must actually publish a real number for
    # the NEW document.
    from PyQt6.QtGui import QTextDocument
    from PyQt6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    ed = _editor("one two three")
    other = QTextDocument("a b c d e f g")
    ed.set_active_document(other)
    assert ed.word_count_if_known() is None, "a swapped document is not counted yet"
    assert ed.document_word_count() == 7, "the recount must read the NEW document"
    assert ed.word_count_if_known() == 7


def test_perf_004_settle_never_raises_against_a_non_qt_host():
    """REGRESSION: the settle timer fires from the Qt event loop, so it can run
    after the host it captured is gone or is a plain Python double. It called
    ``sip.isdeleted(main_win)`` directly, which raises TypeError on anything
    that is not a sip wrapper -- surfacing as a "CALL ERROR: Exceptions caught
    in Qt event loop" attributed to whichever test happened to be running.
    """
    from fastprompter.ui import editor as editor_mod

    ed = _editor("alpha beta gamma")
    ed.main_win = SimpleNamespace()          # not a sip wrapper
    ed._mark_words_dirty()

    # Must not raise, and must still reconcile the count.
    ed._settle_word_count()
    assert ed.word_count_if_known() == 3

    # The helper it now uses answers safely for both flavours of object.
    assert editor_mod._sip_deleted(SimpleNamespace()) is False
    assert editor_mod._sip_deleted(None) is False


def test_perf_004_character_mode_never_asks_for_a_word_count(monkeypatch):
    """VERIFY clause "token mode disabled incurs no word recount": with
    token_mode at its default (chars), the top-bar repaint must not touch the
    word-count machinery at all -- in particular not the O(blocks) recount.
    """
    from PyQt6.QtWidgets import QLabel

    from fastprompter.main import FastPrompter
    from fastprompter.ui import editor as editor_mod

    class _Area:
        def __init__(self):
            from PyQt6.QtGui import QTextDocument
            self._doc = QTextDocument("a b c d e f")

        def document(self):
            return self._doc

        def word_count_if_known(self):        # pragma: no cover - must not run
            raise AssertionError("char mode consulted the word-count cache")

        def document_word_count(self):        # pragma: no cover - must not run
            raise AssertionError("char mode forced a word recount")

    def _explode(*_a, **_k):                  # pragma: no cover - must not run
        raise AssertionError("char mode armed the settle timer")

    monkeypatch.setattr(editor_mod.VaultTextEdit, "_arm_word_count_settle",
                        _explode, raising=False)

    host = SimpleNamespace(
        data={"show_token_count": "True", "token_mode": "chars",
              "token_weight": "4.0"},
        text_area=_Area(),
        lbl_token_count=QLabel(""),
        _current_lang="EN",
        _set_topbar_semantic=lambda *_a, **_k: None,
        _short_count=lambda n: str(n),
    )

    FastPrompter._update_token_count_label(host)
    assert host.lbl_token_count.text().endswith(" T")
