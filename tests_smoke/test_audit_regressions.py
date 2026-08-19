"""Regression tests for the P0/P1 audit baseline — every fixed finding gets
a failing test on the pre-fix code.

Run with the smoke suite (needs a real Qt)::

    uv run pytest tests_smoke/test_audit_regressions.py -q
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

import fastprompter.core.state as state_mod
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_audit_")


@pytest.fixture(scope="module")
def win():
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"a_{profile_id}.db")
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


class _FakeWin32:
    def __init__(self, hwnd=4242, title="Agent", cls="ConsoleWindowClass"):
        self.hwnd, self.title, self.cls = hwnd, title, cls
        self.alive = True

    def info(self, hwnd):
        if hwnd != self.hwnd or not self.alive:
            return None
        return {"title": self.title, "cls": self.cls, "pid": 999}


def _steady_probe():
    from fastprompter.core.watcher.probes import Probe

    class Steady(Probe):
        kind = "steady"

        def _read(self):
            return "unchanging"

    return Steady(quiet_ms=0)


# ============================ P0-4: portable backup profile ==============


def test_backup_worker_exports_under_snapshot_profile_id(win, monkeypatch):
    from fastprompter.main import _PortableBackupWorker
    from fastprompter.utils import portable_backup as pb

    seen = {}

    def fake_export(data, profile_id=1):
        seen["profile_id"] = profile_id

    monkeypatch.setattr(pb, "_do_export", fake_export)
    worker = _PortableBackupWorker()
    worker._run({"text": "x", "profile_id": 2}, 1)
    assert seen["profile_id"] == 2
    worker._run({"text": "y"}, 2)
    assert seen["profile_id"] == 1


# ============================ P0-5: file container ownership =============


def test_file_panel_discards_stale_refresh_results(win):
    panel = win._ensure_file_container()
    folder = panel.folder or win._files_root()
    os.makedirs(folder, exist_ok=True)
    probe = os.path.join(folder, "x.txt")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("x")
    panel.folder = folder
    panel._container_owner_id = "owner-A"
    panel._container_gen = 5
    items = [(probe, "x.txt", None, 0, False)]

    panel._on_refresh_list_result("owner-A", folder, 5, items, 1)
    assert panel.file_list.count() == 1
    assert panel.file_list.item(0).text() == "x.txt"

    # Stale owner, stale generation, or a different folder must not repaint.
    panel._on_refresh_list_result("owner-OLD", folder, 5, items, 9)
    panel._on_refresh_list_result("owner-A", folder, 4, items, 9)
    panel._on_refresh_list_result("owner-A", folder + "-elsewhere", 5, items, 9)
    assert panel.file_list.count() == 1
    assert panel.file_list.item(0).text() == "x.txt"
    assert panel.lbl_count.text() == "1 file(s)"


# ============================ P0-6: del_silo abort =======================


def test_del_silo_aborts_when_folder_retirement_fails(win, monkeypatch):
    win.data["temp_presets"] = ["alpha", "beta"]
    win.active_temp_slot = 0
    win.active_is_archive = False
    win.silo_docs = [None, None]
    # The active slot's live editor text is flushed BEFORE the retirement
    # decision; seed it so the flush is a no-op on the slot's content.
    win.text_area.setPlainText("alpha")
    monkeypatch.setattr(win, "_delete_file_container", lambda cat, d: "FAILED")
    before = len(win.data_undo_stack)

    win.del_silo(0)

    assert win.data["temp_presets"] == ["alpha", "beta"]
    assert len(win.data_undo_stack) == before


def test_del_silo_aborts_when_root_unavailable(win, monkeypatch):
    win.data["temp_presets"] = ["alpha", "beta"]
    win.active_temp_slot = 0
    win.active_is_archive = False
    win.silo_docs = [None, None]
    monkeypatch.setattr(win, "_delete_file_container", lambda cat, d: "ROOT_UNAVAILABLE")
    before = len(win.data_undo_stack)

    win.del_silo(0)

    assert win.data["temp_presets"] == ["alpha", "beta"]
    assert len(win.data_undo_stack) == before


# ============================ P0-7: clear_temp / trim abort ==============


def test_clear_temp_aborts_when_folder_retirement_fails(win, monkeypatch):
    win.data["temp_presets"] = ["alpha", "beta"]
    win.active_temp_slot = 0
    win.active_is_archive = False
    win.silo_docs = [None, None]
    monkeypatch.setattr(win, "_delete_file_container", lambda cat, d: "ROOT_UNAVAILABLE")
    before = len(win.data_undo_stack)

    win.clear_temp(0)

    assert win.data["temp_presets"] == ["alpha", "beta"]
    assert len(win.data_undo_stack) == before


def test_trim_archive_aborts_and_keeps_all_slots(win, monkeypatch):
    win.data["archive_temp_presets"] = ["alpha", ""]
    win.archive_docs = [None, None]
    monkeypatch.setattr(win, "_delete_file_container", lambda cat, d: "FAILED")

    win._trim_archive()

    assert win.data["archive_temp_presets"] == ["alpha", ""]


def test_trim_archive_succeeds_when_folders_retire(win, monkeypatch):
    win.data["archive_temp_presets"] = ["alpha", "", "beta", ""]
    win.archive_docs = [None, None, None, None]
    monkeypatch.setattr(win, "_delete_file_container", lambda cat, d: "EMPTY_REMOVED")

    win._trim_archive()

    assert win.data["archive_temp_presets"] == ["alpha", "beta"]


# ============================ P0-8: del_category rollback ================


def test_del_category_rolls_back_retired_folders_on_cleanup_failure(
        win, tmp_path, monkeypatch):
    # A second category so the delete path is reachable. The synthetic row is
    # inserted at index 0 in BOTH the combo and cats_order so the combo's
    # current-index handling stays consistent. The tab-switch signal is
    # disconnected for the duration (an instance-attr override would not
    # work: PyQt captures the bound method at connect time).
    win.cat_combo.currentIndexChanged.disconnect()
    win.cat_combo.currentIndexChanged.connect(lambda index: None)
    win.cat_combo.insertItem(0, "B", "B")
    win.cat_combo.setCurrentIndex(0)
    win.data["cats_order"].insert(0, "B")
    win.data["categories"]["B"] = [""] * 100

    root = win._files_root()
    cat_dir = "files_audit_B"
    win.data["category_file_dirs"]["B"] = cat_dir
    import uuid
    unique = "assets-" + uuid.uuid4().hex[:8]
    trash = os.path.join(root, "_trash", unique)
    os.makedirs(trash)
    with open(os.path.join(trash, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("x")
    original = os.path.join(root, cat_dir, "assets")
    win.data["folder_trash_log"] = [[original, trash]]

    monkeypatch.setattr(win, "_delete_file_container",
                        lambda cat, d: "MOVED_TO_TRASH")
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)

    def boom():
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(win, "mark_dirty", boom)
    try:
        with pytest.raises(RuntimeError):
            win.del_category()

        # The already-retired folder was moved BACK out of _trash.
        assert os.path.isfile(os.path.join(original, "f.txt"))
        assert not os.path.isdir(trash)
        assert win.data["folder_trash_log"] == []
    finally:
        win.cat_combo.currentIndexChanged.disconnect()
        win.cat_combo.currentIndexChanged.connect(win.on_tab_changed)
        import shutil
        shutil.rmtree(os.path.join(root, cat_dir), ignore_errors=True)


# ============================ P1-4: category files dir fail-closed =======


def test_category_files_dir_returns_none_on_unreachable_root(win, monkeypatch):
    kept_root = win.data.get("files_root")
    kept_map = dict(win.data.get("category_file_dirs", {}))
    try:
        win.data["category_file_dirs"] = {}
        win.data["files_root"] = os.path.join(_tmpdir, "no-such-share")
        assert win._category_files_dir("Main") is None
    finally:
        win.data["files_root"] = kept_root
        win.data["category_file_dirs"] = kept_map


def test_category_files_dir_returns_persisted_component_without_probe(win):
    kept_map = dict(win.data.get("category_file_dirs", {}))
    try:
        win.data["category_file_dirs"] = {"Main": "files_Main"}
        assert win._category_files_dir("Main") == "files_Main"
    finally:
        win.data["category_file_dirs"] = kept_map


# ============================ P1-5: file count ownership =================


def test_stale_file_count_result_is_not_painted(win, monkeypatch):
    seen = []
    prof = win.state.profile_id

    class _Lbl:
        def setText(self, t):
            seen.append(t)

        def show(self):
            pass

        def hide(self):
            pass

    class _FakeBtn:
        def __init__(self, idx):
            self.global_idx = idx
            self._lbl_file_count = _Lbl()

        def isHidden(self):
            return False

    fake = _FakeBtn(0)
    fake_arch = _FakeBtn(0)
    monkeypatch.setattr(win, "silo_buttons", [fake])
    monkeypatch.setattr(win, "archive_buttons", [fake_arch])
    monkeypatch.setattr(win, "_silo_folder_dir",
                        lambda idx, is_archive=False: "/path/a")
    monkeypatch.setattr(win, "active_is_archive", False)

    win._on_file_count_result("/path/a", 42, 0, False, "WRONG-category", prof)
    assert seen == []
    win._on_file_count_result("/path/a", 42, 0, False,
                              win.get_current_category(), 999)
    assert seen == []
    win._on_file_count_result(
        "/path/a", 42, 0, True, win.get_current_category(), prof)
    assert seen == []
    win._on_file_count_result(
        "/path/a", 42, 0, False, win.get_current_category(), prof)
    assert seen == ["📁 42"]
    seen.clear()

    # P1-4: an archive result routes to the ARCHIVE row, never the silo row
    monkeypatch.setattr(win, "active_is_archive", True)
    win._on_file_count_result("/path/a", 42, 0, True,
                              win.get_current_category(), prof)
    assert seen == ["📁 42"]


# ============================ P1-6: tooltip ownership ====================


def test_stale_tooltip_result_is_not_painted(win, monkeypatch):
    calls = []
    prof = win.state.profile_id

    class _Btn:
        pass

    btn = _Btn()
    btn.setToolTip = lambda t: calls.append(t)
    monkeypatch.setattr(win, "btn_files", btn)
    monkeypatch.setattr(win, "active_temp_slot", 0)
    monkeypatch.setattr(win, "_silo_folder_dir",
                        lambda idx, is_archive=False: "/f")

    win._on_tooltip_result("/f", "summary-A", 0, False, "WRONG-category", prof)
    assert calls == []
    win._on_tooltip_result("/f", "summary-B", 0, False,
                           win.get_current_category(), 999)
    assert calls == []
    win._on_tooltip_result("/f", "summary-C", 0, True,
                           win.get_current_category(), prof)
    assert calls == []
    win._on_tooltip_result("/f", "summary-D", 1, False,
                           win.get_current_category(), prof)
    assert calls == []
    win._on_tooltip_result("/f", "summary-E", 0, False,
                           win.get_current_category(), prof)
    assert len(calls) == 1
    assert calls[0].endswith("summary-E")


# ============================ P1-1 / P0-9: watcher verification ==========


def _cdp_armed(win):
    from fastprompter.core.watcher.queue import SiloQueue

    win._watcher_init()

    class T:
        ws_url = "ws://127.0.0.1:1/devtools/browser"

        def matches(self, discover_fn=None):
            return (True, "ok")

    win._watcher_target = T()
    win._watcher_blocked_fn = None
    win._watcher_verify_state = "unverified"
    win._watcher_verify_inflight = False
    win._watcher_verify_gen = 0
    slot = win._queue_slot_key()
    win._watcher_engine.arm(
        win._watcher_target, slot, [_steady_probe()], "", now=time.monotonic())
    win.prompt_queues[slot] = SiloQueue([])
    return slot


def test_cdp_tick_holds_until_verify_cached(win):
    _cdp_armed(win)
    eng = win.watcher_engine()

    win._watcher_tick_inner()
    assert eng._ticks == 0
    assert win._watcher_verify_inflight is True

    for _ in range(100):
        _app.processEvents()
        if win._watcher_verify_state == "ready":
            break
        time.sleep(0.02)
    assert win._watcher_verify_state == "ready"

    win._watcher_tick_inner()
    assert eng._ticks == 1
    win.watcher_disarm()


def test_cdp_hold_blocked_holds_and_reverts(win):
    _cdp_armed(win)
    eng = win.watcher_engine()
    win._watcher_verify_inflight = True
    win._watcher_verify_gen += 1
    gen = win._watcher_verify_gen

    win._watcher_on_verify_result("hold_blocked", gen, True, True, "read failed")

    assert eng.state == "watching"
    assert eng._seen_busy is False
    assert win._watcher_verify_state == "unverified"


def test_cdp_hold_target_disarms(win):
    _cdp_armed(win)
    eng = win.watcher_engine()
    win._watcher_verify_inflight = True
    win._watcher_verify_gen += 1
    gen = win._watcher_verify_gen

    win._watcher_on_verify_result("hold_target", gen, False, False, "the page is gone")

    assert eng.armed is False
    assert "gone" in eng.reason


def test_cdp_stale_verification_is_dropped(win):
    _cdp_armed(win)
    eng = win.watcher_engine()
    win._watcher_verify_gen += 1
    win._watcher_on_verify_result("hold_target", 0, False, False, "stale")
    assert eng.armed is True


def test_arming_with_unreadable_blocker_is_refused(win, monkeypatch):
    from fastprompter.core.watcher import win32 as win32_mod
    from fastprompter.core.watcher.adapter import Adapter

    win.watcher_disarm()
    fake = _FakeWin32()
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: fake.info(hwnd))
    monkeypatch.setattr(win32_mod, "probe_for",
                        lambda api=None: (lambda h: fake.info(h)))

    adapter = Adapter("blk", probes=[_steady_probe()],
                      blocker_pattern="[DENIED]", transport="post")
    ok, reason = win.watcher_arm(fake.hwnd, adapter)

    assert ok is False
    assert "blocker" in reason
    assert not win.watcher_engine().armed


def test_arming_without_blocker_still_works(win, monkeypatch):
    from fastprompter.core.watcher import win32 as win32_mod
    from fastprompter.core.watcher.adapter import Adapter

    fake = _FakeWin32()
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: fake.info(hwnd))
    monkeypatch.setattr(win32_mod, "probe_for",
                        lambda api=None: (lambda h: fake.info(h)))

    adapter = Adapter("ok", probes=[_steady_probe()], transport="post")
    ok, reason = win.watcher_arm(fake.hwnd, adapter)

    assert ok is True
    win.watcher_disarm()


# ============================ P1-2 / P1-3: undo drain truth ==============


def test_wait_for_undo_saves_dispatches_pending_timer(win):
    win._undo_save_threads = set()
    win._undo_save_failed = False
    win._save_undo_state()
    assert win._undo_timer.isActive()

    assert win._wait_for_undo_saves() is True
    assert not win._undo_timer.isActive()
    assert win._undo_save_threads == set()


def test_undo_save_failure_is_reported(win, monkeypatch):
    import fastprompter.main as main_mod

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(main_mod.os, "replace", boom)
    win._undo_save_failed = False
    win._save_undo_state()          # arm a real pending snapshot
    win._dispatch_undo_save()

    assert win._wait_for_undo_saves() is False


def test_undo_failure_in_earlier_batch_is_not_masked(win, monkeypatch):
    """P1-8: a publication failure in batch N must survive a NEW dispatch's
    flag reset — per-job results, not one window-wide flag."""
    import json
    import threading
    import time

    calls = {"n": 0}
    ev = threading.Event()
    real_dump = json.dump

    def flaky_dump(obj, f, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            ev.wait(10)
            raise OSError("disk full during dump")
        return real_dump(obj, f, **kw)

    monkeypatch.setattr(json, "dump", flaky_dump)
    win._undo_save_failed = False
    win._undo_save_threads = set()
    win._undo_save_jobs = {}
    win._undo_pending_jobs = {}

    win._save_undo_state()          # batch 1
    win._dispatch_undo_save()
    time.sleep(0.3)                 # worker 1 blocked inside dump

    win._save_undo_state()          # batch 2 — resets the shared flag
    win._dispatch_undo_save()

    ev.set()
    assert win._wait_for_undo_saves() is False, \
        "batch-1 failure must not be masked by batch-2's flag reset"


# ============================ P1-8: hotkey status truth ==================


def test_hotkey_registration_failure_is_reported(win, monkeypatch):
    from fastprompter.ui import hotkey_mixin as hm

    monkeypatch.setattr(hm.ctypes.windll.user32, "RegisterHotKey",
                        lambda *a: 0)
    assert win._register_single("Alt+X", 1) is False
    assert 1 not in win.registered_hotkeys


def test_hotkey_registration_success_is_reported(win, monkeypatch):
    from fastprompter.ui import hotkey_mixin as hm

    monkeypatch.setattr(hm.ctypes.windll.user32, "RegisterHotKey",
                        lambda *a: 1)
    assert win._register_single("Alt+X", 1) is True
    assert 1 in win.registered_hotkeys
    hm.ctypes.windll.user32.UnregisterHotKey(0, 0)
    win.registered_hotkeys.clear()


def test_hotkey_unregister_failure_is_reported(win, monkeypatch):
    from fastprompter.ui import hotkey_mixin as hm

    # The shared smoke fixture stubs this method out; restore the real one
    # so the P1-8 status contract is actually exercised.
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys",
                        hm.HotkeyMixin.unregister_all_hotkeys)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys",
                        hm.HotkeyMixin.register_all_hotkeys)

    # Fake OS: id 1 releases cleanly, id 2 refuses (still live in the OS).
    unreg = {1: 1, 2: 0}

    def fake_unregister(hwnd, hk_id):
        return unreg.get(hk_id, 1)

    monkeypatch.setattr(hm.ctypes.windll.user32, "UnregisterHotKey",
                        fake_unregister)

    win.registered_hotkeys = [1, 2]
    assert win.unregister_all_hotkeys() is False
    # Only the OS-confirmed release is dropped; the refused id stays tracked
    # so the local model keeps parity with the real OS registrations.
    assert win.registered_hotkeys == [2]

    # Re-registration of id 2 must refuse (still bound in the fake OS) and
    # must NOT create an untracked stale binding; model == fake-OS truth.
    def fake_register(hwnd, hk_id, mod, vk):
        return hk_id != 2

    monkeypatch.setattr(hm.ctypes.windll.user32, "RegisterHotKey",
                        fake_register)
    assert win.register_all_hotkeys() is False
    assert 2 in win.registered_hotkeys


# ============================ T-811: watcher quiesce =========================


def _arm_post(win, monkeypatch):
    """Arm the watcher against a fake win32 (post) target, CDP-free."""
    from fastprompter.core.watcher import win32 as win32_mod
    from fastprompter.core.watcher.adapter import Adapter

    fake = _FakeWin32()
    monkeypatch.setattr(win32_mod, "window_info",
                        lambda hwnd, api=None: fake.info(hwnd))
    monkeypatch.setattr(win32_mod, "probe_for",
                        lambda api=None: (lambda h: fake.info(h)))
    adapter = Adapter("ok", probes=[_steady_probe()], transport="post")
    ok, reason = win.watcher_arm(fake.hwnd, adapter)
    assert ok is True


def _simulate_inflight_send(win, text="hello"):
    """Put the watcher into a believable in-flight SENDING state with one
    pending queue item, and return (item, intent)."""
    from fastprompter.core.watcher.engine import SendIntent
    from fastprompter.core.watcher.queue import QueueItem, SiloQueue

    slot = win._queue_slot_key()
    item = QueueItem(text=text)
    queue = SiloQueue([item])
    win.prompt_queues[slot] = queue
    win._watcher_engine.queue_key = slot
    intent = SendIntent(item.id, text, slot, "", time.monotonic())
    win._watcher_engine.pending = intent
    win._watcher_engine.state = "sending"
    win._watcher_send_gen = 1
    win._watcher_send_active = True
    win._watcher_start_timer()
    return item, intent


def test_quiesce_timeout_keeps_watcher_armed_and_later_send_becomes_sent(
        win, monkeypatch):
    """T-811: a quiesce that times out while a send is in flight must NOT
    disarm the engine; the late success (which arrives after the timeout)
    must still be applied and the prompt becomes SENT exactly once — never
    left PENDING for a duplicate resend."""
    from fastprompter.core.watcher.sender import SendResult

    _arm_post(win, monkeypatch)
    try:
        item, intent = _simulate_inflight_send(win)
        refused = win._watcher_begin_quiesce(timeout_s=0.05)
        # refused: watcher runtime rolled back, still armed, send still active
        assert refused is False
        assert win._watcher_engine.armed is True
        assert win._watcher_timer.isActive() is True
        assert win._watcher_send_active is True
        assert item.state == "pending"
        # the late success arrives now (engine still armed)
        win._watcher_on_send_result(intent, 1, SendResult(True, "ok", "hello"))
        assert item.state == "sent"
        assert win._watcher_send_active is False
        assert win._watcher_engine.sent_count == 1
    finally:
        win.watcher_disarm()


def test_quiesce_success_disarms_after_send_resolves(win, monkeypatch):
    """T-811: when the in-flight send resolves before the timeout, the quiesce
    commits the disarm and the prompt is marked sent."""
    from fastprompter.core.watcher.sender import SendResult

    _arm_post(win, monkeypatch)
    try:
        item, intent = _simulate_inflight_send(win)
        # resolve the send immediately, before quiescing
        win._watcher_on_send_result(intent, 1, SendResult(True, "ok", "hello"))
        assert item.state == "sent"
        ok = win._watcher_begin_quiesce(timeout_s=0.2)
        assert ok is True
        assert win._watcher_engine.armed is False
        assert win._watcher_engine.sent_count == 1
    finally:
        win.watcher_disarm()


def test_quiesce_success_blocks_new_sends(win, monkeypatch):
    """T-811: after a successful quiesce the watcher is disarmed, so no new
    send can be dispatched even though the event loop still lives."""
    _arm_post(win, monkeypatch)
    try:
        ok = win._watcher_begin_quiesce(timeout_s=0.2)
        assert ok is True
        assert win._watcher_engine.armed is False
        before = win._watcher_send_active
        win._watcher_tick_inner()   # engine disarmed -> no dispatch
        assert win._watcher_send_active == before
    finally:
        win.watcher_disarm()


def test_quiesce_refusal_does_not_reopen_live_db(win, monkeypatch):
    """T-808/T-811 overlap: a restore that hits the fatal path must not reopen
    the live database in-process. We inject FatalRestoreError and assert
    restore_db does NOT call state.init_db() (which would reopen the live
    connection)."""
    from fastprompter.core.state import FatalRestoreError

    init_calls = {"n": 0}
    real_init = win.state.init_db

    def counting_init():
        init_calls["n"] += 1
        return real_init()

    monkeypatch.setattr(win.state, "init_db", counting_init)
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
        lambda *a, **k: ("/some/backup.db", ""))
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        "fastprompter.core.state.restore_database",
        lambda *a, **k: (_ for _ in ()).throw(FatalRestoreError("fatal")))

    had_conn = win.state.conn is not None
    win.restore_db()
    # fatal path: never reopened in-process
    assert init_calls["n"] == 0
    # the connection was closed by restore_db before the restore call
    assert win.state.conn is None
    # and `had_conn` documents the prior state for clarity (no assertion)
    _ = had_conn

