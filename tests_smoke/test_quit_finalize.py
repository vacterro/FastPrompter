"""P0-6: quit refuses a failed final save; watcher is quiesced BEFORE the
event loop dies; closeEvent does not double-save after the pre-quit
finalize; watcher quiesce keeps unresolved sends pending.

Run with the smoke suite (needs a real Qt)::

    uv run pytest tests_smoke/test_quit_finalize.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_quit_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, "q.db")
    state_mod.run_portable_backup = lambda data, profile_id=1: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None
    w = FastPrompter()
    w.resize(960, 540)
    w.show()
    _app.processEvents()
    yield w
    try:
        w._watcher_shutdown()
    except Exception:
        pass
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w.close()


def test_quit_refuses_when_final_save_fails(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or False)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))
    win._logical_finalized = False
    win.quit_app()
    assert order == ["save"]
    assert getattr(win, "_logical_finalized", False) is False


def test_quit_finalizes_then_quits_when_save_ok(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: order.append("quit"))
    win._logical_finalized = False
    win.quit_app()
    assert order == ["save", "quit"]
    assert getattr(win, "_logical_finalized", False) is True


def test_pre_quit_finalize_quiesces_watcher_before_save(win, monkeypatch):
    order = []
    monkeypatch.setattr(win, "_watcher_begin_quiesce",
                        lambda timeout_s=1.5: order.append("quiesce") or True)
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: order.append("save") or True)
    win._logical_finalized = False
    assert win._pre_quit_logical_finalize() is True
    assert order == ["quiesce", "save"]
    assert getattr(win, "_logical_finalized", False) is True


def test_close_event_skips_save_after_pre_quit_finalize(win, monkeypatch):
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    win._logical_finalized = True
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == []


def test_close_event_saves_when_not_pre_finalized(win, monkeypatch):
    saves = []
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=False: saves.append(force) or True)
    win._logical_finalized = False
    win.show()
    _app.processEvents()
    win.close()
    _app.processEvents()
    assert saves == [True]


def test_quiesce_disarms_and_blocks_new_sends(win, monkeypatch):
    win._watcher_init()
    win._watcher_send_active = False
    win._watcher_quiescing = False
    disarmed = []
    monkeypatch.setattr(win._watcher_engine, "disarm",
                        lambda reason="disarmed": disarmed.append(reason))
    assert win._watcher_begin_quiesce(timeout_s=0.01) is True
    assert disarmed == ["application is quitting"]
    assert win._watcher_quiescing is False

    # while quiescing, a new dispatch is refused and nothing is emitted
    win._watcher_quiescing = True
    calls = []
    monkeypatch.setattr(win, "_watcher_ensure_worker",
                        lambda: calls.append("worker") or None)
    win._watcher_dispatch_send(object())
    assert calls == []
    win._watcher_quiescing = False
    assert win._watcher_send_active is False


def test_send_result_clears_active_flag(win, monkeypatch):
    import time

    from fastprompter.core.watcher.queue import SiloQueue

    win._watcher_init()
    win._watcher_send_active = True
    win._watcher_send_gen = 7

    class T:
        ws_url = "ws://127.0.0.1:1/devtools/browser"

        def matches(self, discover_fn=None):
            return (True, "ok")

    slot = win._queue_slot_key()
    win._watcher_engine.arm(T(), slot, [], "", now=time.monotonic())
    win.prompt_queues[slot] = SiloQueue([])
    win._watcher_engine.state = "sending"

    from fastprompter.core.watcher.sender import SendResult
    # CORE-003: a physical send result carries its dispatch token; remove it
    # before the generation check so the barrier is cleared for THIS send.
    win._watcher_send_token_seq += 1
    token = win._watcher_send_token_seq
    win._watcher_send_physical_tokens.add(token)
    win._watcher_on_send_result(object(), 7, SendResult(False, "gone"), token)
    assert win._watcher_send_active is False
