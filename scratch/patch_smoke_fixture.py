import glob

target_files = glob.glob(r"tests_smoke\test_*.py")

for filepath in target_files:
    with open(filepath, encoding='utf-8') as f:
        content = f.read()
    
    if '@pytest.fixture(scope="module")\ndef win():' in content:
        # We need to replace the module-level fixture with the function-level fixture using monkeypatch
        # We find the fixture block.
        
        # We'll use a regex replacement or exact string replacement if it's consistent.
        # Let's check consistency by finding the block exactly.
        block_old = """@pytest.fixture(scope="module")
def win():
    # Isolate from real data / running instances
    state_mod.get_db_path = lambda profile_id=1: os.path.join(_tmpdir, f"smoke_{profile_id}.db")
    state_mod.run_portable_backup = lambda data: None
    FastPrompter.setup_single_instance_server = lambda self: None
    FastPrompter.register_all_hotkeys = lambda self: None
    FastPrompter.unregister_all_hotkeys = lambda self: None

    w = FastPrompter()
    yield w
    w.auto_save_timer.stop()
    w.topmost_timer.stop()
    w._cache_timer.stop()
    w.state.conn = None  # skip final DB write on close
    w.conn = None"""

        block_new = """@pytest.fixture(scope="function")
def win(monkeypatch):
    # Isolate from real data / running instances
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
    w.state.conn = None  # skip final DB write on close
    w.conn = None
    w.close()
    w.deleteLater()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()"""

        if block_old in content:
            content = content.replace(block_old, block_new)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Patched {filepath}")
        else:
            print(f"Fixture block not found exactly in {filepath}")
