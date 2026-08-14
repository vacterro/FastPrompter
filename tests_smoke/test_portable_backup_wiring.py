import os
import threading
import time

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from fastprompter.utils import portable_backup as pb

_app = QApplication.instance() or QApplication([])


def _data(text):
    return {
        "cats_order": ["A"],
        "categories": {"A": [{"name": "snippet", "text": text}]},
        "temp_presets_all": {"A": [text]},
        "archive_temp_presets_all": {"A": []},
    }


def _silo_path(backup_dir):
    day = time.strftime("%Y-%m-%d")
    return os.path.join(backup_dir, day, "silos", "a", "silo_001.md")


def _wait_for_idle(timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if m._BACKUP_INFLIGHT_GEN == 0 and m._BACKUP_PENDING is None:
            return
        time.sleep(0.01)
    pytest.fail(
        "portable backup did not become idle: "
        f"inflight={m._BACKUP_INFLIGHT_GEN}, pending={m._BACKUP_PENDING!r}"
    )


@pytest.fixture()
def production_backup(tmp_path, monkeypatch):
    backup_dir = str(tmp_path / "portable")
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: backup_dir)
    monkeypatch.setattr(pb, "_BACKUP_THROTTLE", 0)

    m.backup_worker_shutdown_global()
    m._BACKUP_GEN = 0
    m._BACKUP_LAST_SUCCESS_GEN = 0
    m._BACKUP_LAST_FAILED_GEN = 0
    pb._last_backup_time = 0.0
    pb.set_backup_sink(None)
    m._BACKUP_SINK_INSTALLED = False
    m._install_portable_backup_sink()
    yield backup_dir
    assert m.backup_worker_shutdown_global() is True
    pb.set_backup_sink(None)
    m._BACKUP_SINK_INSTALLED = False


def test_real_factory_completes_two_consecutive_backups(production_backup):
    pb.run_portable_backup(_data("generation A"))
    _wait_for_idle()

    path = _silo_path(production_backup)
    assert "generation A" in open(path, encoding="utf-8").read()
    assert m._BACKUP_INFLIGHT_GEN == 0

    worker = m._BACKUP_WORKER
    pb.run_portable_backup(_data("generation B"))
    _wait_for_idle()

    assert m._BACKUP_WORKER is worker
    assert "generation B" in open(path, encoding="utf-8").read()
    assert m._BACKUP_INFLIGHT_GEN == 0
    assert m._BACKUP_PENDING is None


def test_backup_worker_and_completion_have_explicit_thread_owners(
    production_backup, monkeypatch
):
    worker_threads = []
    completion_threads = []
    real_export = pb._do_export
    real_complete = m._backup_on_done

    def record_export(snapshot):
        worker_threads.append(QThread.currentThread())
        return real_export(snapshot)

    def record_completion(*args):
        completion_threads.append(QThread.currentThread())
        return real_complete(*args)

    monkeypatch.setattr(pb, "_do_export", record_export)
    monkeypatch.setattr(m, "_backup_on_done", record_completion)
    pb.run_portable_backup(_data("thread ownership"))
    _wait_for_idle()

    assert worker_threads == [m._BACKUP_THREAD]
    assert completion_threads == [_app.thread()]


def test_real_completion_drains_newest_coalesced_backup(
    production_backup, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    exported = []
    real_export = pb._do_export

    def blocking_export(snapshot):
        text = snapshot["temp_presets_all"]["A"][0]
        exported.append(text)
        if text == "generation A":
            started.set()
            assert release.wait(5.0), "test did not release generation A"
        return real_export(snapshot)

    monkeypatch.setattr(pb, "_do_export", blocking_export)

    pb.run_portable_backup(_data("generation A"))
    assert started.wait(2.0), "generation A never reached production worker"
    pb.run_portable_backup(_data("generation B"))
    pb.run_portable_backup(_data("generation C"))

    assert m._BACKUP_PENDING["temp_presets_all"]["A"] == ["generation C"]
    release.set()
    _wait_for_idle()

    assert exported == ["generation A", "generation C"]
    assert "generation C" in open(
        _silo_path(production_backup), encoding="utf-8"
    ).read()
    assert m._BACKUP_INFLIGHT_GEN == 0
    assert m._BACKUP_PENDING is None


def test_failed_newest_generation_is_immediately_retryable(
    production_backup, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    exported = []
    real_export = pb._do_export

    def export_with_newest_failure(snapshot):
        text = snapshot["temp_presets_all"]["A"][0]
        exported.append(text)
        if text == "generation A":
            started.set()
            assert release.wait(5.0), "test did not release generation A"
        if text == "generation B":
            raise OSError("disk full")
        return real_export(snapshot)

    monkeypatch.setattr(pb, "_do_export", export_with_newest_failure)
    monkeypatch.setattr(pb, "_BACKUP_THROTTLE", 120)

    pb.run_portable_backup(_data("generation A"))
    assert started.wait(2.0), "generation A never reached production worker"
    pb.run_portable_backup(_data("generation B"))
    release.set()
    _wait_for_idle()

    assert m._BACKUP_LAST_SUCCESS_GEN == 1
    assert m._BACKUP_LAST_FAILED_GEN == 2
    assert pb._last_backup_time == 0.0

    pb.run_portable_backup(_data("generation C"))
    _wait_for_idle()
    assert exported == ["generation A", "generation B", "generation C"]
    assert "generation C" in open(
        _silo_path(production_backup), encoding="utf-8"
    ).read()
    assert m._BACKUP_LAST_SUCCESS_GEN == 3


def test_clean_busy_shutdown_allows_worker_recreation(
    production_backup, monkeypatch
):
    started = threading.Event()
    real_export = pb._do_export

    def slow_export(snapshot):
        started.set()
        time.sleep(0.1)
        return real_export(snapshot)

    monkeypatch.setattr(pb, "_do_export", slow_export)
    pb.run_portable_backup(_data("before shutdown"))
    assert started.wait(2.0), "backup never became physically busy"
    old_worker = m._BACKUP_WORKER

    assert m.backup_worker_shutdown_global() is True
    assert m._BACKUP_WORKER is None
    assert m._BACKUP_THREAD is None
    assert m._BACKUP_PENDING is None
    assert m._BACKUP_INFLIGHT_GEN == 0

    pb._last_backup_time = 0.0
    pb.run_portable_backup(_data("after recreation"))
    _wait_for_idle()
    assert m._BACKUP_WORKER is not old_worker
    assert "after recreation" in open(
        _silo_path(production_backup), encoding="utf-8"
    ).read()
