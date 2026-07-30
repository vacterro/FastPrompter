import glob
import re

target_files = glob.glob(r"tests_smoke\test_*.py")

# Regex to match the function fixture and replace it with a more robust teardown
fixture_pattern = re.compile(
    r'@pytest\.fixture\(scope="function"\)\n'
    r'def win\(monkeypatch\):\n'
    r'(?:    #.*\n)*'
    r'    monkeypatch\.setattr\(state_mod, "get_db_path", lambda profile_id=1: os\.path\.join\(_tmpdir, f"[^"]+"\)\)\n'
    r'    monkeypatch\.setattr\(state_mod, "run_portable_backup", lambda data: None, raising=False\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "setup_single_instance_server", lambda self: None, raising=False\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "register_all_hotkeys", lambda self: None, raising=False\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "unregister_all_hotkeys", lambda self: None, raising=False\)\n'
    r'\n?'
    r'    w = FastPrompter\(\)\n'
    r'    yield w\n'
    r'    w\.auto_save_timer\.stop\(\)\n'
    r'    w\.topmost_timer\.stop\(\)\n'
    r'    w\._cache_timer\.stop\(\)\n'
    r'    w\.state\.conn = None\n'
    r'    w\.conn = None\n'
    r'    w\.close\(\)\n'
    r'    w\.deleteLater\(\)\n'
    r'    from PySide6\.QtWidgets import QApplication\n'
    r'    QApplication\.processEvents\(\)',
    re.MULTILINE
)

def build_replacement(match):
    return """@pytest.fixture(scope="function")
def win(monkeypatch):
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: os.path.join(_tmpdir, f"smoke_{profile_id}.db"))
    monkeypatch.setattr(state_mod, "run_portable_backup", lambda data: None, raising=False)
    monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None, raising=False)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None, raising=False)
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None, raising=False)

    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.hide()
    
    # Cancel any pending extra selection updates to prevent segfaults
    if getattr(w.editor, "_sel_refresh_pending", False):
        w.editor._sel_refresh_pending = False
        
    w.deleteLater()
    
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent
    QApplication.instance().setStyleSheet("") # Clear global stylesheet to prevent crashes on dead widgets
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()"""

for filepath in target_files:
    with open(filepath, encoding='utf-8') as f:
        content = f.read()

    new_content, count = fixture_pattern.subn(build_replacement, content)
    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched robust teardown in {filepath}")
    else:
        print(f"Could not match fixture in {filepath}")
