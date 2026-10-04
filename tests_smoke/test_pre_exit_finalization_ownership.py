"""W2-002 P0: Pre-exit logical finalization ownership contracts A-L.

Verifies:
1. Logical finalization (quiesce + final durable save) happens strictly BEFORE
   QApplication.quit() while the Qt event loop is alive.
2. A failed final save or watcher quiesce refuses quit, leaves the event loop alive,
   and keeps UI retryable.
3. Post-event-loop teardown (_shutdown_application) performs physical retirement only;
   it never calls logical finalization or saves as fallback.
4. Mutex is released only after mutating workers retire; unclean retirement retains mutex.
5. Direct exit static guard ensures no unapproved application quit/exit calls exist.
6. sys.exit(app.exec()) is eliminated; teardown completes before exit code propagation.
"""

import ast
import inspect
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fastprompter.core.state as state_mod
from fastprompter import main as m
from fastprompter.main import FastPrompter

_app = QApplication.instance() or QApplication([])
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_w2_002_")


@pytest.fixture(scope="module")
def win(smoke_win):
    w = smoke_win.create(show=True, size=(960, 540))
    yield w
    smoke_win.retire(w)


# Contract A: FINAL SAVE REFUSAL
def test_contract_a_final_save_refusal(win, monkeypatch):
    quit_calls = []
    exit_calls = []
    teardown_calls = []

    monkeypatch.setattr(win, "_pre_quit_logical_finalize", lambda: False)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_calls.append(True))
    monkeypatch.setattr(QApplication, "exit", lambda *a: exit_calls.append(True), raising=False)
    monkeypatch.setattr(m, "_shutdown_application", lambda *a: teardown_calls.append(True))

    win._logical_finalized = False
    win._quit_in_progress = False

    win.quit_app()

    # Assert: QApplication.quit not called, exit not called, teardown not initiated
    assert quit_calls == []
    assert exit_calls == []
    assert teardown_calls == []
    assert getattr(win, "_logical_finalized", False) is False

    # Assert: retry remains possible
    monkeypatch.setattr(win, "_pre_quit_logical_finalize", lambda: True)
    monkeypatch.setattr(win.sound_manager, "play_to_completion", lambda name: None)
    win.quit_app()
    assert quit_calls == [True]


# Contract B: FINAL SAVE SUCCESS
def test_contract_b_final_save_success(win, monkeypatch):
    events = []

    monkeypatch.setattr(win, "_pre_quit_logical_finalize",
                        lambda: events.append("FINALIZER") or True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: events.append("QT_QUIT"))
    monkeypatch.setattr(win.sound_manager, "play_to_completion",
                        lambda name: events.append(f"SOUND_{name}"))

    win._logical_finalized = False
    win._quit_in_progress = False

    win.quit_app()

    assert "FINALIZER" in events
    assert "QT_QUIT" in events
    assert events.index("FINALIZER") < events.index("QT_QUIT")
    assert events.count("QT_QUIT") == 1


# Contract C: WATCHER QUIESCE FAILURE
def test_contract_c_watcher_quiesce_failure(win, monkeypatch):
    events = []

    monkeypatch.setattr(win, "_watcher_begin_quiesce",
                        lambda: False, raising=False)
    monkeypatch.setattr(win, "save_data_to_db",
                        lambda force=True: events.append("SAVE_DB") or True)
    monkeypatch.setattr(QApplication, "quit",
                        lambda: events.append("QT_QUIT"))

    win._logical_finalized = False
    win._quit_in_progress = False

    win.quit_app()

    assert "SAVE_DB" not in events
    assert "QT_QUIT" not in events
    assert getattr(win, "_logical_finalized", False) is False

    # Retry is possible
    monkeypatch.setattr(win, "_watcher_begin_quiesce",
                        lambda: True, raising=False)
    monkeypatch.setattr(win.sound_manager, "play_to_completion", lambda name: None)
    win.quit_app()
    assert "SAVE_DB" in events
    assert "QT_QUIT" in events


# Contract D: POST-LOOP TEARDOWN
def test_contract_d_post_loop_teardown(monkeypatch):
    events = []

    class FinalizedFakeWindow:
        _close_workers_clean = True
        _logical_finalized = True
        ipc = None
        conn = None
        state = None

        def _pre_quit_logical_finalize(self):
            events.append("LOGICAL_FINALIZE")
            return True

        def save_data_to_db(self, force=True):
            events.append("SAVE_DATA_TO_DB")
            return True

        def close(self):
            events.append("WINDOW_CLOSE")

        def _wait_for_undo_saves(self):
            events.append("UNDO_RETIRED")
            return True

        def deleteLater(self):
            events.append("WINDOW_DELETE")

    class FakeApp:
        def processEvents(self):
            events.append("PROCESS_EVENTS")

    class FakeLock:
        def release(self):
            events.append("LOCK_RELEASE")

    win = FinalizedFakeWindow()
    app = FakeApp()
    lock = FakeLock()

    clean = m._shutdown_application(win, app, lock)

    assert clean is True
    assert "LOGICAL_FINALIZE" not in events
    assert "SAVE_DATA_TO_DB" not in events
    assert "UNDO_RETIRED" in events
    assert "LOCK_RELEASE" in events


# Contract E: REGRESSION TRAP
def test_contract_e_regression_trap_no_logical_finalization_in_teardown():
    class TrapWindow:
        _close_workers_clean = True
        _logical_finalized = True
        ipc = None
        conn = None
        state = None

        def _pre_quit_logical_finalize(self):
            raise AssertionError("TRAP: post-loop teardown attempted _pre_quit_logical_finalize!")

        def save_data_to_db(self, force=True):
            raise AssertionError("TRAP: post-loop teardown attempted save_data_to_db!")

        def close(self):
            pass

        def _wait_for_undo_saves(self):
            return True

        def deleteLater(self):
            pass

    class FakeApp:
        def processEvents(self):
            pass

    class FakeLock:
        def release(self):
            pass

    # Must never raise AssertionError
    clean = m._shutdown_application(TrapWindow(), FakeApp(), FakeLock())
    assert clean is True


# Contract F: EXIT ORDER
def test_contract_f_exit_order(monkeypatch):
    events = []

    class DbRec:
        def close(self):
            events.append("DB_CLOSE")

    class FakeWindow:
        _close_workers_clean = True
        _logical_finalized = False
        _quit_in_progress = False
        conn = DbRec()
        state = None
        ipc = None

        def _cancel_timer_test_jobs(self):
            pass

        def _watcher_begin_quiesce(self):
            events.append("LOGICAL_QUIESCE")
            return True

        def _watcher_commit_quiesce(self):
            pass

        def save_data_to_db(self, force=True):
            events.append("FINAL_DURABLE_SAVE")
            return True

        def _watcher_shutdown(self):
            events.append("PHYSICAL_WRITER_RETIREMENT")
            return True

        def _wait_for_undo_saves(self):
            return True

        def close(self):
            pass

        def deleteLater(self):
            pass

    fake_win = FakeWindow()
    fake_win.sound_manager = type(
        "SM",
        (),
        {
            "play_to_completion": lambda s, n: None,
            "stop_all_sound": lambda s: None,
            "shutdown": lambda s: None,
        },
    )()
    fake_win.quit_app = lambda: FastPrompter.quit_app(fake_win)
    fake_win._pre_quit_logical_finalize = lambda: FastPrompter._pre_quit_logical_finalize(fake_win)

    class FakeApp:
        def exec(self):
            fake_win.quit_app()
            events.append("EVENT_LOOP_RETURN")
            return 0

        def processEvents(self):
            pass

    class FakeLock:
        def release(self):
            events.append("MUTEX_RELEASE")

    monkeypatch.setattr(QApplication, "quit", lambda: events.append("QT_QUIT_REQUEST"))

    app = FakeApp()
    lock = FakeLock()

    exit_code = app.exec()
    clean = m._shutdown_application(fake_win, app, lock)

    assert clean is True
    assert exit_code == 0
    assert events == [
        "LOGICAL_QUIESCE",
        "FINAL_DURABLE_SAVE",
        "QT_QUIT_REQUEST",
        "EVENT_LOOP_RETURN",
        "PHYSICAL_WRITER_RETIREMENT",
        "DB_CLOSE",
        "MUTEX_RELEASE",
    ]


# Contract G: FAILED PHYSICAL RETIREMENT
def test_contract_g_failed_physical_retirement_retains_mutex():
    class FakeWindow:
        _close_workers_clean = True
        ipc = None
        conn = None
        state = None

        def _sync_shutdown(self):
            return False  # mutating worker fails/times out

        def _wait_for_undo_saves(self):
            return True

        def close(self):
            pass

        def deleteLater(self):
            pass

    class FakeApp:
        def processEvents(self):
            pass

    class FakeLock:
        def __init__(self):
            self.released = False

        def release(self):
            self.released = True

    lock = FakeLock()
    clean = m._shutdown_application(FakeWindow(), FakeApp(), lock)

    assert clean is False
    assert lock.released is False


# Contract H: DIRECT EXIT STATIC GUARD
def test_contract_h_direct_exit_static_guard():
    src_dir = Path(m.__file__).parent
    violations = []

    approved_methods = {
        ("main.py", "QApplication.quit"): {"quit_app"},
    }

    forbidden_attrs = {"quit", "exit"}
    forbidden_classes = {"QApplication", "QCoreApplication", "qApp"}

    class ScopeVisitor(ast.NodeVisitor):
        def __init__(self, rel_path):
            self.rel_path = rel_path
            self.current_func = None

        def visit_FunctionDef(self, node):
            old = self.current_func
            self.current_func = node.name
            self.generic_visit(node)
            self.current_func = old

        def visit_AsyncFunctionDef(self, node):
            old = self.current_func
            self.current_func = node.name
            self.generic_visit(node)
            self.current_func = old

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in forbidden_attrs:
                    target = None
                    if isinstance(node.func.value, ast.Name):
                        target = node.func.value.id
                    elif isinstance(node.func.value, ast.Attribute):
                        target = node.func.value.attr

                    if target in forbidden_classes:
                        call_sig = f"{target}.{attr}"
                        allowed_funcs = approved_methods.get((self.rel_path, call_sig))
                        if allowed_funcs is None or self.current_func not in allowed_funcs:
                            violations.append((self.rel_path, node.lineno, call_sig, self.current_func))
            self.generic_visit(node)

    for py_file in src_dir.rglob("*.py"):
        rel_path = py_file.relative_to(src_dir).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        ScopeVisitor(rel_path).visit(tree)

    assert violations == [], f"Direct exit calls found outside approved: {violations}"



# Contract I: SYS.EXIT CONTROL FLOW
def test_contract_i_sys_exit_control_flow():
    source = inspect.getsource(m.main_entry)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "exit"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "sys"):
                for arg in node.args:
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "exec":
                        pytest.fail("sys.exit(app.exec()) detected! Teardown must run before sys.exit.")

    assert "sys.exit(app.exec())" not in source
    assert "exit_code = app.exec()" in source
    assert "_shutdown_application(window, app, lock)" in source


# Contract J: DOUBLE FINALIZATION
def test_contract_j_double_finalization(win, monkeypatch):
    calls = []
    orig_finalize = win._pre_quit_logical_finalize

    def spy_finalize():
        calls.append(True)
        return orig_finalize()

    monkeypatch.setattr(win, "_pre_quit_logical_finalize", spy_finalize)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(win.sound_manager, "play_to_completion", lambda name: None)

    win._logical_finalized = False
    win._quit_in_progress = False

    win.quit_app()
    assert len(calls) == 1

    class FakeApp:
        def processEvents(self):
            pass

    class FakeLock:
        def release(self):
            pass

    m._shutdown_application(win, FakeApp(), FakeLock())
    assert len(calls) == 1


# Contract K: CLOSE EVENT
def test_contract_k_close_event_skips_save_when_logical_finalized(win, monkeypatch):
    saves = []
    monkeypatch.setattr(win, "save_data_to_db", lambda force=True: saves.append(True) or True)

    # T-1300: this module-scoped window keeps its periodic autosave timer
    # running between tests. In a long combined run the 10s tick is overdue,
    # fires inside processEvents() below, and calls the patched save — which
    # looks like a closeEvent save but is not. This contract is about
    # closeEvent, so own the owned background timers for the assertion and
    # restore their active state afterwards.
    owned = [getattr(win, name, None)
             for name in ("auto_save_timer", "_cache_timer")]
    was_active = [t.isActive() if t is not None else False for t in owned]
    for t in owned:
        if t is not None:
            t.stop()
    try:
        win._logical_finalized = True
        win.show()
        _app.processEvents()
        win.close()
        _app.processEvents()
    finally:
        for t, active in zip(owned, was_active):
            if t is not None and active:
                t.start()

    assert saves == []


# Contract L: REFUSED QUIT UI
def test_contract_l_refused_quit_ui(win, monkeypatch):
    ui_actions = []

    monkeypatch.setattr(win, "_pre_quit_logical_finalize", lambda: False)
    monkeypatch.setattr(win, "show", lambda: ui_actions.append("SHOW"))
    monkeypatch.setattr(win, "raise_", lambda: ui_actions.append("RAISE"))
    monkeypatch.setattr(win, "activateWindow", lambda: ui_actions.append("ACTIVATE"))
    if hasattr(win, "tray_icon"):
        monkeypatch.setattr(win.tray_icon, "show", lambda: ui_actions.append("TRAY_SHOW"))

    win._logical_finalized = False
    win._quit_in_progress = False

    win.quit_app()

    assert "SHOW" in ui_actions
    assert "RAISE" in ui_actions
    assert "ACTIVATE" in ui_actions
    if hasattr(win, "tray_icon"):
        assert "TRAY_SHOW" in ui_actions


# PLATFORM / WINDOWS ACCEPTANCE (Steps 1-10)
def test_windows_acceptance_flow(monkeypatch, tmp_path):
    import uuid

    from fastprompter.core.instance_lock import PRIMARY, InstanceLock, bootstrap_ownership

    mutex_name = rf"Local\FastPrompter_Acceptance_{uuid.uuid4().hex}"
    lock1 = InstanceLock(name=mutex_name)
    role1, _ = bootstrap_ownership(lock1, lambda: False)
    assert role1 == PRIMARY

    db_file = str(tmp_path / "acceptance.db")
    state_mod.get_db_path = lambda profile_id=1: db_file
    state_mod.run_portable_backup = lambda data, profile_id=1: None

    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None

    # 1. Start FastPrompter with isolated test data
    w = FastPrompter()
    w.resize(600, 400)
    w.show()
    _app.processEvents()

    # 2. Make a dirty edit
    w.text_area.setPlainText("dirty test data for Windows acceptance")

    # 3. Force the logical finalizer to refuse once
    refused = [True]

    def conditional_finalize():
        if refused[0]:
            return False
        return orig_finalize()

    orig_finalize = w._pre_quit_logical_finalize
    monkeypatch.setattr(w, "_pre_quit_logical_finalize", conditional_finalize)
    quit_requested = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requested.append(True))
    monkeypatch.setattr(w.sound_manager, "play_to_completion", lambda name: None)

    # 4. Trigger Exit
    w.quit_app()

    # 5. Verify process remains alive
    assert quit_requested == []
    assert getattr(w, "_logical_finalized", False) is False
    assert lock1._owned is True

    # Second process cannot become primary while first instance is alive
    def _probe_role():
        import subprocess
        script = f"""
from fastprompter.core.instance_lock import InstanceLock, bootstrap_ownership
lock = InstanceLock(name={mutex_name!r})
role, _ = bootstrap_ownership(lock, lambda: False)
print(role, flush=True)
lock.release()
"""
        res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
        assert res.returncode == 0, res.stderr
        return res.stdout.strip()

    assert _probe_role() != PRIMARY

    # 6. Verify application remains usable/retryable
    w.text_area.setPlainText("updated dirty data on retry")
    _app.processEvents()

    # 7. Allow finalizer success
    refused[0] = False

    # 8. Trigger Exit again
    w.quit_app()

    # 9. Verify orderly process exit
    assert quit_requested == [True]
    assert getattr(w, "_logical_finalized", False) is True

    # Physical retirement executes
    class MockApp:
        def processEvents(self):
            pass

    clean = m._shutdown_application(w, MockApp(), lock1)
    assert clean is True
    assert lock1._owned is False

    # 10. Start a second instance only after the first has physically retired/released ownership
    assert _probe_role() == PRIMARY
