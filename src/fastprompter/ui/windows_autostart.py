"""Windows "Start with FastPrompter" registry entry (T-1238-C4.3).

Packaged builds only.  From source there is no stable executable to
register, so the control is disabled and says why instead of writing a
registry value that would launch a python interpreter after the checkout
moves.

Every write is VERIFIED by reading the value back: a silently failing
registry write that leaves a checkbox ticked is worse than a refusal.
Disable removes only FastPrompter's own entry, never anything else.
"""

from __future__ import annotations

import os
import sys

#: HKCU is per-user and needs no elevation.  Never HKLM.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FastPrompter"


def is_packaged() -> bool:
    """True only for a frozen build with a real executable to register."""
    return bool(getattr(sys, "frozen", False))


def executable_path() -> str:
    """The exact current EXE path, quoted for the registry."""
    return os.path.abspath(sys.executable)


def _registry():
    """The winreg module, or None where there is no Windows registry."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None
    return winreg


def unavailable_reason() -> str:
    """Why the control is disabled, in plain words ("" when available)."""
    if _registry() is None:
        return "Windows autostart is only available on Windows."
    if not is_packaged():
        return ("Windows autostart is only available in the packaged build "
                "(running from source has no stable executable path).")
    return ""


def read_autostart(registry=None) -> str | None:
    """The currently registered command, or None when there is no entry."""
    winreg = registry if registry is not None else _registry()
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def set_autostart(enabled: bool, registry=None,
                  command: str | None = None) -> tuple[bool, str]:
    """Enable or disable autostart; returns ``(ok, message)``.

    ``registry`` is injectable so the test suite proves the contract against
    a fake registry and never touches the real one.
    """
    winreg = registry if registry is not None else _registry()
    if winreg is None:
        return False, "Windows autostart is only available on Windows."
    if registry is None and not is_packaged():
        return False, unavailable_reason()

    target = command if command is not None else f'"{executable_path()}"'
    try:
        if enabled:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, target)
        else:
            existing = read_autostart(winreg)
            if existing is None:
                return True, ""  # already absent; nothing of ours to remove
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
    except OSError as exc:
        return False, f"Could not write the autostart entry: {exc}"

    # Verify by reading it back -- an unverified write is not a success.
    current = read_autostart(winreg)
    if enabled and current != target:
        return False, "The autostart entry could not be verified after writing."
    if not enabled and current is not None:
        return False, "The autostart entry could not be removed."
    return True, ""
