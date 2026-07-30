import glob
import re

target_files = glob.glob(r"tests_smoke\test_*.py")

# Regex to match the win fixture
fixture_pattern = re.compile(
    r'@pytest\.fixture\(scope="module"\)\n'
    r'def win\(\):\n'
    r'(?:    #.*\n)*'
    r'    state_mod\.get_db_path = lambda profile_id=1: os\.path\.join\(_tmpdir, f"[^"]+"\)\n'
    r'    state_mod\.run_portable_backup = lambda data: None\n'
    r'    FastPrompter\.setup_single_instance_server = lambda self: None\n'
    r'    FastPrompter\.register_all_hotkeys = lambda self: None\n'
    r'    FastPrompter\.unregister_all_hotkeys = lambda self: None\n'
    r'\n?'
    r'    w = FastPrompter\(\)\n'
    r'    yield w\n'
    r'    w\.auto_save_timer\.stop\(\)\n'
    r'    w\.topmost_timer\.stop\(\)\n'
    r'    w\._cache_timer\.stop\(\)\n'
    r'    w\.state\.conn = None(?:  #.*)?\n'
    r'    w\.conn = None',
    re.MULTILINE
)

def build_replacement(match):
    # Extract the DB path part dynamically if we care, but actually we can just use "smoke_{profile_id}.db" for all of them
    return """@pytest.fixture(scope="function")
def win(monkeypatch):
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: os.path.join(_tmpdir, f"smoke_{profile_id}.db"))
    monkeypatch.setattr(state_mod, "run_portable_backup", lambda data: None)
    monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None)
    monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None)
    monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None)

    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None
    w.conn = None
    w.close()
    w.deleteLater()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()"""

for filepath in target_files:
    if filepath.endswith("test_app_smoke.py"):
        continue  # Already patched

    with open(filepath, encoding='utf-8') as f:
        content = f.read()

    new_content, count = fixture_pattern.subn(build_replacement, content)
    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched regex in {filepath}")
    else:
        print(f"Could not match fixture in {filepath}")
