"""Phase-5/6 (second pass): portable backup completion semantics + identity.

Proves:
* a snapshot is COMPLETE only when every mandatory export succeeded — the
  _COMPLETE marker is written last and is absent after any failure
* a failed export does NOT advance the throttle (immediate retry eligible)
* the previous known-good day snapshot survives a failed export
* collision-resistant filesystem identity: hostile and case-colliding project
  names export to distinct, recoverable paths
"""

import json
import os

import pytest

import fastprompter.utils.portable_backup as pb


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "portable")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
    pb._last_backup_time = 0.0
    yield d


def _data():
    return {
        "cats_order": ["Alpha", "A:B", "A?B", "Project", "project"],
        "categories": {
            "Alpha": [{"name": "s1", "text": "snippet-one"}],
            "A:B": [{"name": "s2", "text": "snippet-two"}],
            "A?B": [{"name": "s3", "text": "snippet-three"}],
            "Project": [],
            "project": [{"name": "s4", "text": "snippet-four"}],
        },
        "temp_presets_all": {
            "Alpha": ["alpha text"],
            "A:B": ["colon text"],
            "A?B": ["question text"],
            "Project": ["caps text"],
            "project": ["lower text"],
        },
        "archive_temp_presets_all": {
            "Alpha": ["alpha archive"],
        },
    }


def _day_dir(backup_dir):
    import time as _t
    return os.path.join(backup_dir, _t.strftime("%Y-%m-%d"))


def _complete(day):
    return os.path.isfile(os.path.join(day, pb._COMPLETE_MARKER))


class TestCompletionSemantics:
    def test_successful_snapshot_is_complete(self, backup_dir):
        pb._do_export(_data())
        day = _day_dir(backup_dir)
        assert _complete(day)
        meta = json.load(open(os.path.join(day, "_meta.json"), encoding="utf-8"))
        assert meta["complete"] is True

    def test_no_partial_dir_left_after_success(self, backup_dir):
        pb._do_export(_data())
        assert not os.path.exists(_day_dir(backup_dir) + ".partial")

    def test_failed_silo_write_has_no_complete_marker(self, backup_dir, monkeypatch):
        real = pb._write_raw

        def _boom(path, content):
            if "silo_001.md" in path:
                raise OSError("disk full")
            return real(path, content)

        monkeypatch.setattr(pb, "_write_raw", _boom)
        with pytest.raises(OSError):
            pb._do_export(_data())
        day = _day_dir(backup_dir)
        assert not _complete(day) if os.path.isdir(day) else True
        assert not os.path.exists(day + ".partial")

    def test_failed_manifest_write_has_no_complete_marker(self, backup_dir, monkeypatch):
        real = pb._write_raw

        def _boom(path, content):
            if path.endswith("_meta.json"):
                raise OSError("disk full")
            return real(path, content)

        monkeypatch.setattr(pb, "_write_raw", _boom)
        with pytest.raises(OSError):
            pb._do_export(_data())
        day = _day_dir(backup_dir)
        assert not (os.path.isdir(day) and _complete(day))
        assert not os.path.exists(day + ".partial")

    def test_failed_snapshot_keeps_previous_good_one(self, backup_dir, monkeypatch):
        pb._do_export(_data())                     # good snapshot
        day = _day_dir(backup_dir)
        assert _complete(day)
        good_files = sorted(
            os.path.relpath(os.path.join(r, f), day)
            for r, _d, fs in os.walk(day) for f in fs)

        real = pb._write_raw

        def _boom(path, content):
            if "archive_001.md" in path:
                raise OSError("disk full")
            return real(path, content)

        monkeypatch.setattr(pb, "_write_raw", _boom)
        with pytest.raises(OSError):
            pb._do_export(_data())

        # the previous good snapshot is still there, complete
        assert _complete(day)
        now_files = sorted(
            os.path.relpath(os.path.join(r, f), day)
            for r, _d, fs in os.walk(day) for f in fs)
        assert now_files == good_files

    def test_failed_export_does_not_throttle_retry(self, backup_dir, monkeypatch):
        real = pb._write_raw
        calls = {"n": 0}

        def _boom(path, content):
            calls["n"] += 1
            if calls["n"] == 1 and "silo_001.md" in path:
                raise OSError("first try fails")
            return real(path, content)

        monkeypatch.setattr(pb, "_write_raw", _boom)
        pb.run_portable_backup(_data())     # first attempt fails internally
        # run_portable_backup swallows the failure, so assert the throttle:
        # it must NOT have advanced, so a retry is eligible immediately
        assert pb._last_backup_time == 0.0
        pb.run_portable_backup(_data())     # retry succeeds
        assert _complete(_day_dir(backup_dir))
        assert pb._last_backup_time > 0.0


class TestCollisionResistantIdentity:
    def test_hostile_and_case_names_export_to_distinct_dirs(self, backup_dir):
        pb._do_export(_data())
        day = _day_dir(backup_dir)
        silos = sorted(os.listdir(os.path.join(day, "silos")))
        assert len(silos) == len(_data()["cats_order"]), silos
        # every logical project is independently recoverable
        marker_of = {}
        for comp in silos:
            files = os.listdir(os.path.join(day, "silos", comp))
            assert files
            content = "".join(
                open(os.path.join(day, "silos", comp, f),
                     encoding="utf-8").read()
                for f in files)
            for marker in ("alpha text", "colon text", "question text",
                           "caps text", "lower text"):
                if marker in content:
                    marker_of[marker] = comp
        assert marker_of["colon text"] != marker_of["question text"]
        assert marker_of["caps text"] != marker_of["lower text"]
        assert len(set(marker_of.values())) == 5

    def test_unicode_projects_stay_inside_and_distinct(self, tmp_path, monkeypatch):
        d = str(tmp_path / "uni")
        os.makedirs(d, exist_ok=True)
        monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
        pb._last_backup_time = 0.0
        data = _data()
        data["cats_order"] = ["Проект", "Проект 2"]
        data["temp_presets_all"] = {"Проект": ["one"], "Проект 2": ["two"]}
        data["categories"] = {}
        data["archive_temp_presets_all"] = {}
        pb._do_export(data)
        day = os.path.join(d, __import__("time").strftime("%Y-%m-%d"))
        comps = sorted(os.listdir(os.path.join(day, "silos")))
        assert len(comps) == 2
        assert _complete(day)


class TestPublicationRollback:
    """Phase-3: a failed publication must never lose the previous known-good
    COMPLETE generation."""

    def _tree(self, day):
        return sorted(
            os.path.relpath(os.path.join(r, f), day)
            for r, _d, fs in os.walk(day) for f in fs)

    def test_new_publish_failure_restores_previous_generation(self, backup_dir, monkeypatch):
        pb._do_export(_data())
        day = _day_dir(backup_dir)
        good = self._tree(day)
        assert _complete(day)

        real_rename = os.rename
        calls = {"n": 0}

        def _flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:          # old relocated OK, new->day fails
                raise OSError("rename failed mid-publish")
            return real_rename(src, dst)

        monkeypatch.setattr("os.rename", _flaky)
        with pytest.raises(OSError):
            pb._do_export(_data())

        # the previous known-good generation must be back at day_dir
        assert os.path.isdir(day)
        assert _complete(day)
        assert self._tree(day) == good, "previous COMPLETE snapshot lost"
        # no rollback sibling is left behind
        assert not any("rollback" in e for e in os.listdir(backup_dir))

    def test_first_publish_with_no_previous_day(self, backup_dir):
        pb._do_export(_data())
        day = _day_dir(backup_dir)
        assert _complete(day)
        assert self._tree(day)

    def test_successful_republication_leaves_no_rollback(self, backup_dir):
        pb._do_export(_data())
        pb._do_export(_data())          # a second, successful generation
        day = _day_dir(backup_dir)
        assert _complete(day)
        leftovers = [e for e in os.listdir(backup_dir)
                     if "rollback" in e or e.endswith(".partial")]
        assert leftovers == [], leftovers

    def test_failed_old_relocation_keeps_previous_and_drops_new(self, backup_dir, monkeypatch):
        pb._do_export(_data())
        day = _day_dir(backup_dir)
        good = self._tree(day)

        def _flaky(src, dst):
            raise OSError("cannot relocate the old generation")

        monkeypatch.setattr("os.rename", _flaky)
        with pytest.raises(OSError):
            pb._do_export(_data())

        assert self._tree(day) == good   # untouched
        assert not any("rollback" in e for e in os.listdir(backup_dir))


class TestAsyncDispatch:
    """Phase-9: portable backup can be dispatched async via an installed sink;
    the snapshot handed over is an immutable deep copy."""

    def test_snapshot_is_a_deep_copy(self, backup_dir):
        data = _data()
        snap = pb.capture_snapshot(data)
        data["temp_presets_all"]["Alpha"][0] = "MUTATED AFTER CAPTURE"
        data["categories"]["Alpha"][0]["text"] = "mutated"
        data["cats_order"].append("NEW")
        assert snap["temp_presets_all"]["Alpha"][0] == "alpha text"
        assert snap["categories"]["Alpha"][0]["text"] == "snippet-one"
        assert "NEW" not in snap["cats_order"]

    def test_sink_receives_immutable_snapshot(self, backup_dir):
        received = []

        def fake_sink(snapshot):
            received.append(snapshot)

        pb.set_backup_sink(fake_sink)
        try:
            pb._last_backup_time = 0.0
            pb.run_portable_backup(_data())
            assert len(received) == 1
            assert received[0]["temp_presets_all"]["Alpha"][0] == "alpha text"
            # dispatch alone must NOT advance the success throttle
            assert pb._last_backup_time == 0.0
        finally:
            pb.set_backup_sink(None)

    def test_without_sink_runs_synchronously(self, backup_dir):
        pb.set_backup_sink(None)
        pb._last_backup_time = 0.0
        pb.run_portable_backup(_data())
        assert _complete(_day_dir(backup_dir))
        assert pb._last_backup_time > 0.0

    def test_mark_success_advances_throttle(self, backup_dir):
        pb._last_backup_time = 0.0
        pb.mark_backup_success()
        assert pb._last_backup_time > 0.0
