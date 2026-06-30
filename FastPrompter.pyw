import sys
import os
import traceback
import ctypes

# Add src to Python path so it can find fastprompter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fastprompter.main import main_entry

if __name__ == "__main__":
    try:
        main_entry()
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code == 0:
            sys.exit(0)
        error_msg = traceback.format_exc()
        with open(os.path.join(os.path.dirname(__file__), "crash.log"), "w", encoding="utf-8") as f:
            f.write(error_msg)
        # MessageBoxW takes (HWND, Text, Caption, Type). 0x10 is MB_ICONERROR.
        # This guarantees crashes are loud and visible, directly satisfying Debater's Immediate Feedback Wrapper requirement.
        ctypes.windll.user32.MessageBoxW(0, f"FastPrompter crashed fatally:\n\n{error_msg}", "FastPrompter Fatal Error", 0x10)
        sys.exit(1)
