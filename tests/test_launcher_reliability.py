"""T-1161: launcher reliability — _ensure_venv_python re-exec logic.

The function lives in FastPrompter.pyw (the application entry point).
It re-execs the process under the project .venv interpreter when PyQt6
is missing from the current interpreter, enabling double-click / autostart
to work without a ModuleNotFoundError crash dialog.
"""

import builtins
import importlib.util
import os
import sys


def _load_pyw():
    """Load FastPrompter.pyw as a module (the __main__ guard stays off) and
    return the module object so tests can redirect its __file__/globals."""
    spec = importlib.util.spec_from_file_location(
        "FastPrompter",
        os.path.join(os.path.dirname(__file__), "..", "FastPrompter.pyw"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_pyqt6_import(monkeypatch):
    """Make only the PyQt6 import fail (everything else passes through)."""
    real_import = builtins.__import__

    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6":
            raise ImportError("PyQt6 missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded)


def test_launcher_returns_when_pyqt6_available():
    """When PyQt6 is importable, _ensure_venv_python must return without
    raising or re-executing."""
    import PyQt6  # noqa: F401
    mod = _load_pyw()
    mod._ensure_venv_python()


def test_launcher_raises_when_venv_missing(monkeypatch, tmp_path):
    """When PyQt6 is missing and the .venv does not exist, a RuntimeError
    with the expected path must be raised."""
    _no_pyqt6_import(monkeypatch)
    mod = _load_pyw()
    fake_root = str(tmp_path / "project")
    monkeypatch.setattr(mod, "__file__",
                        os.path.join(fake_root, "FastPrompter.pyw"))
    monkeypatch.setattr(sys, "executable",
                        os.path.join(str(tmp_path), "system", "python.exe"))
    import pytest
    with pytest.raises(RuntimeError) as exc_info:
        mod._ensure_venv_python()
    assert ".venv" in str(exc_info.value)
    assert "venv interpreter not found" in str(exc_info.value)


def test_launcher_calls_execv_when_pyqt6_missing_and_venv_exists(
        monkeypatch, tmp_path):
    """When PyQt6 is missing and the project .venv exists, the function
    must call os.execv with the venv interpreter path.  Because os.execv
    replaces the process, we make our stub raise SystemExit."""
    import pytest
    _no_pyqt6_import(monkeypatch)
    mod = _load_pyw()
    fake_root = str(tmp_path / "project")
    venv_py = os.path.join(fake_root, ".venv", "Scripts", "python.exe")
    monkeypatch.setattr(mod, "__file__",
                        os.path.join(fake_root, "FastPrompter.pyw"))
    monkeypatch.setattr(sys, "executable",
                        os.path.join(str(tmp_path), "system", "python.exe"))
    real_exists = os.path.exists
    calls = []

    def _fake_execv(p, a):
        calls.append((p, a))
        raise SystemExit(0)

    monkeypatch.setattr(os, "execv", _fake_execv)
    monkeypatch.setattr(os.path, "exists",
                        lambda p: True if p == venv_py
                        else real_exists(p))
    with pytest.raises(SystemExit) as exc_info:
        mod._ensure_venv_python()
    assert exc_info.value.code == 0
    assert len(calls) == 1, f"expected one os.execv call, got {calls}"
    assert "python.exe" in calls[0][0]
    assert ".venv" in calls[0][0]
