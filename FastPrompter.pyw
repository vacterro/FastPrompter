# nuitka-project: --standalone
# nuitka-project: --onefile
# nuitka-project: --enable-plugin=pyqt6
# nuitka-project: --include-package=fastprompter
# nuitka-project: --windows-console-mode=disable
# nuitka-project: --windows-icon-from-ico=_res/fastprompter.ico
# nuitka-project: --product-name=FastPrompter
# nuitka-project: --product-version=0.8.65
# nuitka-project: --file-description=FastPrompter portable snippet manager
# nuitka-project: --python-flag=no_docstrings
# nuitka-project: --python-flag=no_asserts
# nuitka-project: --output-dir=build
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --include-qt-plugins=platforms,styles,imageformats
# nuitka-project: --nofollow-import-to=PyQt6.QtMultimedia
# nuitka-project: --include-data-dir=src/fastprompter/sound=sound
# nuitka-project: --include-data-dir=src/fastprompter/presets=presets
# nuitka-project: --include-data-dir=_res=_res

import sys
import os
import traceback
import ctypes

# Add src to Python path so it can find fastprompter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def _ensure_venv_python():
    """Re-exec under the project venv interpreter when PyQt6 is missing.

    Windows opens .pyw files with whatever interpreter is associated with
    them (usually the system Python, which has no project dependencies).
    The real environment lives in the uv-managed .venv next to this file,
    so relaunch there instead of dying with ModuleNotFoundError.
    """
    # Already running under the venv -> let the real error surface.
    venv_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts")
    if sys.executable.lower().startswith(venv_scripts.lower()):
        return
    try:
        import PyQt6  # noqa: F401 -- availability probe
        return
    except ImportError:
        pass
    exe = "pythonw.exe" if sys.stdout is None else "python.exe"
    venv_py = os.path.join(venv_scripts, exe)
    if os.path.exists(venv_py):
        os.execv(venv_py, [venv_py] + sys.argv)
    raise RuntimeError(
        "PyQt6 is not installed for the current interpreter "
        f"({sys.executable}).\nExpected venv interpreter not found at:\n{venv_py}"
    )


if __name__ == "__main__":
    try:
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
