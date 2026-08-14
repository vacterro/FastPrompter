import os
import threading
import time

from PyQt6.QtWidgets import QApplication

from fastprompter import main as m
from tests_smoke.test_sync_async import _setup

pytest_plugins = ["tests_smoke.test_sync_async"]

_app = QApplication.instance() or QApplication([])


def _mirror_text(root):
    texts = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".md"):
                with open(os.path.join(base, name), encoding="utf-8") as fh:
                    texts.append(fh.read())
    return "\n".join(texts)


def _wait_for_idle(window, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if not window._sync_busy:
            return
        time.sleep(0.01)
    raise AssertionError(f"Sync stayed inflight at gen {window._sync_inflight_gen}")


def test_shutdown_final_write_cannot_be_overwritten_by_delayed_old_worker(
    win, monkeypatch, tmp_path
):
    root = _setup(win, tmp_path)
    started = threading.Event()
    release = threading.Event()
    real_write = m._sync_mechanical_write

    def delay_old_before_physical_write(snapshot, lock_timeout_s=None):
        text = next(iter(snapshot["files"].values()))
        if "generation 1" in text:
            started.set()
            assert release.wait(5.0), "test did not release generation 1"
        return real_write(snapshot, lock_timeout_s)

    monkeypatch.setattr(m, "_sync_mechanical_write", delay_old_before_physical_write)

    win.data["temp_presets"][0] = "# t\ngeneration 1"
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    assert started.wait(2.0), "generation 1 never reached worker"

    win.data["temp_presets"][0] = "# t\ngeneration 2"
    assert win._sync_shutdown(timeout_s=0.05) is False
    assert "generation 2" in _mirror_text(root)
    assert win._sync_busy is True

    release.set()
    _wait_for_idle(win)
    assert "generation 2" in _mirror_text(root)
    assert "generation 1" not in _mirror_text(root)


def test_shutdown_never_starts_concurrent_physical_writer(
    win, monkeypatch, tmp_path, caplog
):
    _setup(win, tmp_path)
    entered = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    counter_lock = threading.Lock()
    real_write = m._sync_mechanical_write

    def block_old_inside_physical_write(snapshot, lock_timeout_s=None):
        nonlocal active, max_active
        text = next(iter(snapshot["files"].values()))
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if "generation 1" in text:
                with m._SYNC_WRITE_LOCK:
                    entered.set()
                    assert release.wait(5.0), "test did not release generation 1"
                    return real_write(snapshot, lock_timeout_s)
            return real_write(snapshot, lock_timeout_s)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(m, "_sync_mechanical_write", block_old_inside_physical_write)

    win.data["temp_presets"][0] = "# t\ngeneration 1"
    win.sync_to_disk(force=True)
    win._sync_dispatch_pending()
    assert entered.wait(2.0), "generation 1 never acquired physical lock"

    win.data["temp_presets"][0] = "# t\ngeneration 2"
    assert win._sync_shutdown(timeout_s=0.05) is False
    assert max_active == 2  # fallback called primitive but never entered physical lock
    assert "physical Sync write lock timed out" in caplog.text
    assert win._sync_busy is True

    release.set()
    _wait_for_idle(win)
    # Latest-generation fence suppresses old publication after final request.
    assert "generation 1" not in _mirror_text(win.data["sync_path"])


def test_failed_final_destination_is_not_cached(win, monkeypatch, tmp_path):
    _setup(win, tmp_path)
    win.data["temp_presets"][0] = "# t\nfinal generation"
    snapshot = win._capture_sync_snapshot(force=True)
    assert snapshot is not None
    win._sync_gen += 1
    snapshot["gen"] = win._sync_gen
    m._sync_register_snapshot(snapshot)
    destination = next(iter(snapshot["files"]))

    monkeypatch.setattr(m.os, "replace", lambda *_args: (_ for _ in ()).throw(
        OSError("disk full")
    ))
    written, errors = m._sync_mechanical_write(snapshot)
    win._sync_inflight_gen = snapshot["gen"]
    win._sync_on_done(snapshot["gen"], snapshot, written, errors)

    assert written == []
    assert errors == [(destination, "disk full")]
    assert destination not in win._sync_written


def test_replacing_sync_root_itself_rejects_publication(win, tmp_path):
    import shutil

    root = _setup(win, tmp_path)
    os.makedirs(root, exist_ok=True)
    outside = str(tmp_path / "outside-root-swap")
    os.makedirs(outside)
    snapshot = win._capture_sync_snapshot(force=True)
    assert snapshot is not None

    shutil.rmtree(root)
    os.symlink(outside, root, target_is_directory=True)
    written, errors = m._sync_mechanical_write(snapshot)

    assert written == []
    assert errors and "captured root changed" in errors[0][1]
    assert os.listdir(outside) == []
