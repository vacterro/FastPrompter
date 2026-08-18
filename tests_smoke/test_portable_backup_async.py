"""Phase-9 (third pass): portable backup runs on a shared worker thread.

Proves:
* dispatching a backup does not block the caller
* shutdown is explicit and bounded
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.utils.portable_backup as pb

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_backup_async_")


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "portable")
    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: d)
    pb.last_success_by_profile.clear()
    pb.set_backup_sink(None)
    yield d
    pb.set_backup_sink(None)


def _data():
    return {
        "cats_order": ["A"],
        "categories": {"A": [{"name": "s", "text": "snip"}]},
        "temp_presets_all": {"A": ["alpha"]},
        "archive_temp_presets_all": {"A": []},
    }


def _day(backup_dir):
    return os.path.join(backup_dir, time.strftime("%Y-%m-%d"))


def test_backup_does_not_block_the_caller(backup_dir, monkeypatch):
    from fastprompter import main as m
    m._install_portable_backup_sink()

    real_export = pb._do_export

    def slow_export(snap, profile_id=1):
        time.sleep(0.5)
        return real_export(snap, profile_id=profile_id)

    monkeypatch.setattr(pb, "_do_export", slow_export)
    pb.last_success_by_profile.clear()
    t0 = time.monotonic()
    pb.run_portable_backup(_data())         # dispatch, must not block
    assert time.monotonic() - t0 < 0.3, "portable backup blocked the caller"

    # the worker writes the COMPLETE snapshot eventually
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _app.processEvents()
        if os.path.isfile(os.path.join(_day(backup_dir), pb._COMPLETE_MARKER)):
            break
        time.sleep(0.01)
    assert os.path.isfile(os.path.join(_day(backup_dir), pb._COMPLETE_MARKER))
    m.backup_worker_shutdown_global()
