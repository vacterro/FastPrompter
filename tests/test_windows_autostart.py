"""T-1238-C4.3: the Windows autostart entry, against a FAKE registry.

No test in this suite may write to the real registry.  The contract proven
here is that a write is verified by reading it back, that disable removes
only FastPrompter's own value, and that source runs refuse truthfully
instead of registering a path that will not exist tomorrow.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.ui import windows_autostart as autostart  # noqa: E402


class FakeRegistry:
    """Just enough winreg to prove the contract."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_READ = 1
    KEY_SET_VALUE = 2

    def __init__(self, values: dict | None = None, *, readonly=False) -> None:
        self.values: dict[str, str] = dict(values or {})
        self.readonly = readonly

    class _Key:
        def __init__(self, owner) -> None:
            self.owner = owner

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def OpenKey(self, _root, _path, _reserved=0, _access=0):
        return self._Key(self)

    def CreateKey(self, _root, _path):
        return self._Key(self)

    def QueryValueEx(self, key, name):
        if name not in key.owner.values:
            raise OSError(2, "not found")
        return key.owner.values[name], self.REG_SZ

    def SetValueEx(self, key, name, _reserved, _kind, value):
        if key.owner.readonly:
            raise OSError(5, "access denied")
        key.owner.values[name] = value

    def DeleteValue(self, key, name):
        if key.owner.readonly:
            raise OSError(5, "access denied")
        key.owner.values.pop(name, None)


class SilentlyFailingRegistry(FakeRegistry):
    """Accepts the write and keeps nothing: the exact bug verification catches."""

    def SetValueEx(self, key, name, _reserved, _kind, value):
        return None


class TestEnable:
    def test_a_verified_write_reports_success(self):
        registry = FakeRegistry()
        ok, message = autostart.set_autostart(True, registry,
                                              command='"C:/app/FP.exe"')
        assert ok and message == ""
        assert registry.values[autostart.VALUE_NAME] == '"C:/app/FP.exe"'

    def test_a_silent_write_failure_is_reported_not_believed(self):
        registry = SilentlyFailingRegistry()
        ok, message = autostart.set_autostart(True, registry,
                                              command='"C:/app/FP.exe"')
        assert ok is False
        assert "verified" in message

    def test_a_denied_write_is_reported(self):
        registry = FakeRegistry(readonly=True)
        ok, message = autostart.set_autostart(True, registry, command='"x"')
        assert ok is False and message


class TestDisable:
    def test_disable_removes_only_our_own_value(self):
        registry = FakeRegistry({autostart.VALUE_NAME: '"C:/app/FP.exe"',
                                 "SomeoneElse": "C:/other/thing.exe"})
        ok, _message = autostart.set_autostart(False, registry)
        assert ok
        assert autostart.VALUE_NAME not in registry.values
        assert registry.values["SomeoneElse"] == "C:/other/thing.exe"

    def test_disabling_when_absent_is_still_success(self):
        registry = FakeRegistry()
        assert autostart.set_autostart(False, registry)[0] is True


class TestSourceRuns:
    def test_running_from_source_refuses_with_a_reason(self, monkeypatch):
        monkeypatch.setattr(autostart, "is_packaged", lambda: False)
        reason = autostart.unavailable_reason()
        if autostart._registry() is None:
            assert "Windows" in reason
        else:
            assert "packaged" in reason
        ok, message = autostart.set_autostart(True)
        assert ok is False and message

    def test_a_packaged_run_reports_available(self, monkeypatch):
        if autostart._registry() is None:
            pytest.skip("no Windows registry on this platform")
        monkeypatch.setattr(autostart, "is_packaged", lambda: True)
        assert autostart.unavailable_reason() == ""


class TestReadback:
    def test_read_returns_none_without_an_entry(self):
        assert autostart.read_autostart(FakeRegistry()) is None

    def test_read_returns_the_registered_command(self):
        registry = FakeRegistry({autostart.VALUE_NAME: '"C:/app/FP.exe"'})
        assert autostart.read_autostart(registry) == '"C:/app/FP.exe"'
