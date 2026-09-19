# nuitka-project: --standalone
# nuitka-project: --onefile
# nuitka-project: --enable-plugin=pyqt6
# nuitka-project: --include-package=fastprompter
# nuitka-project: --windows-console-mode=disable
# nuitka-project: --windows-icon-from-ico=_res/fastprompter.ico
# nuitka-project: --product-name=FastPrompter
# nuitka-project: --product-version=0.8.68
# nuitka-project: --file-description=FastPrompter portable snippet manager
# nuitka-project: --python-flag=no_docstrings
# nuitka-project: --python-flag=no_asserts
# nuitka-project: --output-dir=build
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --include-qt-plugins=platforms,styles,imageformats,multimedia
# T-1238: QtMultimedia is the CANONICAL audio backend (QSoundEffect gives
# real multi-channel mixing, per-channel volume, native looping and a real
# per-channel stop).  Excluding it shipped a NullTransport EXE where
# Overlay/Stack/Replace, voice phrases and ambience could not work at all.
# nuitka-project: --include-module=PyQt6.QtMultimedia
# nuitka-project: --include-data-dir=src/fastprompter/sound=sound
# T-1238-E1.4 ASSET SAFETY: the private _vault/ namespace holds GoldSrc
# VOX/FVOX voice material that belongs to its owners, not to this release.
# It stays fully usable on the developer's own machine and is IMPORTED by
# each user from their own copy of the game (Audio Hub -> Voice -> Import
# GoldSrc / AMX...), but it is never bundled into a build.
# nuitka-project: --noinclude-data-files=sound/_vault/vox/*
# nuitka-project: --noinclude-data-files=sound/_vault/fvox/*
# nuitka-project: --noinclude-data-files=sound/_vault/gman/*
# nuitka-project: --noinclude-data-files=sound/_vault/amx_ultimate/*
# nuitka-project: --include-data-dir=src/fastprompter/presets=presets
# nuitka-project: --include-data-dir=_res=_res

import sys
import os
import traceback
import ctypes

# Add src to Python path so it can find fastprompter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


_REQUIRED_STARTUP_MODULES = ("PyQt6", "markdown")


def _ensure_venv_python():
    """Re-exec under the project venv interpreter when startup dependencies are missing.

    Windows opens .pyw files with whatever interpreter is associated with
    them (usually the system Python, which has no project dependencies).
    The real environment lives in the uv-managed .venv next to this file,
    so relaunch there instead of dying with ModuleNotFoundError.
    """
    venv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".venv"))
    # Already running under the venv -> let the real error surface.
    if os.path.normcase(sys.executable).startswith(os.path.normcase(venv_dir) + os.sep):
        return

    missing = []
    for mod in _REQUIRED_STARTUP_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        return

    exe = "pythonw.exe" if sys.stdout is None else "python.exe"
    venv_py = os.path.join(venv_dir, "Scripts", exe)
    if os.path.exists(venv_py):
        os.execv(venv_py, [venv_py] + sys.argv)
    raise RuntimeError(
        f"Required startup module(s) {', '.join(missing)} not installed for current interpreter "
        f"({sys.executable}).\nExpected venv interpreter not found at:\n{venv_py}"
    )


if __name__ == "__main__":
    try:
        # Claude Code invokes this lightweight mode from its status-line hook.
        # It must run before PyQt/instance locking and must never open a window.
        if "--claude-statusline-bridge" in sys.argv:
            from fastprompter.core.usage_limits.claude_statusline import bridge_main
            sys.exit(bridge_main())
        _ensure_venv_python()
        # Import inside the guard so a broken bundle/env also produces
        # a visible error dialog + crash.log instead of dying silently.
        from fastprompter.main import main_entry

        main_entry()
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code == 0:
            sys.exit(0)
        error_msg = traceback.format_exc()
        crash_log = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "crash.log")
        with open(crash_log, "w", encoding="utf-8") as f:
            f.write(error_msg)
        # MessageBoxW takes (HWND, Text, Caption, Type). 0x10 is MB_ICONERROR.
        # This guarantees crashes are loud and visible, directly satisfying Debater's Immediate Feedback Wrapper requirement.
        ctypes.windll.user32.MessageBoxW(0, f"FastPrompter crashed fatally:\n\n{error_msg}", "FastPrompter Fatal Error", 0x10)
        sys.exit(1)
