# nuitka-project: --standalone
# nuitka-project: --onefile
# nuitka-project: --enable-plugin=pyqt6
# nuitka-project: --include-package=fastprompter
# nuitka-project: --windows-console-mode=disable
# nuitka-project: --windows-icon-from-ico=_res/fastprompter.ico
# nuitka-project: --product-name=FastPrompter
# nuitka-project: --product-version=0.5.0
# nuitka-project: --file-description=FastPrompter portable snippet manager
# nuitka-project: --python-flag=no_docstrings
# nuitka-project: --python-flag=no_asserts
# nuitka-project: --output-dir=build
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --include-qt-plugins=platforms,styles,imageformats
# nuitka-project: --nofollow-import-to=PyQt6.QtMultimedia
# nuitka-project: --include-data-dir=src/fastprompter/sound=sound
# nuitka-project: --include-data-dir=_res=_res

import sys
import os
import traceback
import ctypes

# Add src to Python path so it can find fastprompter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

if __name__ == "__main__":
    try:
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
