"""Regression: a GUI launch must never leave an empty black console window.

The EXE is built as a GUI-subsystem binary (--windows-console-mode=disable),
but two things can still put a console on the desktop:

* a launcher/shortcut that starts the app from cmd/powershell hands it an
  inherited console handle;
* a background subprocess spawned without CREATE_NO_WINDOW flashes a window.

Interactive installer/login consoles are deliberately excluded: the user is
supposed to watch and answer those.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_launcher():
    spec = importlib.util.spec_from_file_location(
        "fastprompter_launcher_under_test", ROOT / "FastPrompter.pyw")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gui_launch_detaches_inherited_console(monkeypatch):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher.os, "name", "nt")
    calls = []

    class _Kernel32:
        def FreeConsole(self):
            calls.append("FreeConsole")
            return 1

    class _Windll:
        kernel32 = _Kernel32()

    monkeypatch.setattr(launcher.ctypes, "windll", _Windll(), raising=False)
    launcher._detach_inherited_console()
    assert calls == ["FreeConsole"]


def test_statusline_hook_uses_no_window(monkeypatch):
    from fastprompter.core.usage_limits import claude_statusline as cs

    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after capturing flags")

    # Real subprocess.run, captured through monkeypatch on the module object.
    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    monkeypatch.setattr(cs.os, "name", "nt")
    monkeypatch.setattr(
        cs, "_read_json_object",
        lambda path, missing_ok=True: {"original_status_line": {
            "command": "echo hi"}})
    try:
        cs._forward_original(b"{}", pathlib.Path("."))
    except RuntimeError:
        pass
    if os.name == "nt":
        assert seen.get("creationflags") == 0x08000000


def test_background_launchers_never_request_new_console():
    source = (ROOT / "src" / "fastprompter" / "core" / "usage_limits"
              / "cli_tools.py").read_text(encoding="utf-8")
    # The only CREATE_NEW_CONSOLE sites must be the two documented interactive
    # helpers; no background path may open one.
    assert source.count("CREATE_NEW_CONSOLE") == 2
    for name in ("launch_installer", "launch_login"):
        assert name in source
