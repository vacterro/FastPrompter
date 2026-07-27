import os
import glob
import re

target_files = glob.glob(r"tests_smoke\test_*.py")

# Regex to match the win fixture
fixture_pattern = re.compile(
    r'@pytest\.fixture\(scope="function"\)\n'
    r'def win\(monkeypatch\):\n'
    r'(?:    #.*\n)*'
    r'    monkeypatch\.setattr\(state_mod, "get_db_path", lambda profile_id=1: os\.path\.join\(_tmpdir, f"[^"]+"\)\)\n'
    r'    monkeypatch\.setattr\(state_mod, "run_portable_backup", lambda data: None\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "setup_single_instance_server", lambda self: None\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "register_all_hotkeys", lambda self: None\)\n'
    r'    monkeypatch\.setattr\(FastPrompter, "unregister_all_hotkeys", lambda self: None\)\n',
    re.MULTILINE
)

def build_replacement(match):
    # Extract the DB path part
    return match.group(0).replace(
        'monkeypatch.setattr(state_mod, "run_portable_backup", lambda data: None)',
        'monkeypatch.setattr(state_mod, "run_portable_backup", lambda data: None, raising=False)'
    ).replace(
        'monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None)',
        'monkeypatch.setattr(FastPrompter, "setup_single_instance_server", lambda self: None, raising=False)'
    ).replace(
        'monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None)',
        'monkeypatch.setattr(FastPrompter, "register_all_hotkeys", lambda self: None, raising=False)'
    ).replace(
        'monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None)',
        'monkeypatch.setattr(FastPrompter, "unregister_all_hotkeys", lambda self: None, raising=False)'
    )

for filepath in target_files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content, count = fixture_pattern.subn(build_replacement, content)
    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched regex raising=False in {filepath}")
    else:
        print(f"Could not match fixture in {filepath}")
