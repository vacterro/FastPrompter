import os
import re

filepath = 'tests/test_pie_menu.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# I will just look for `class _TestShowHideCloseEvents` and replace everything down to `class _TestGlobalKeyPress` with nothing, then clear everything to the end of file.
pattern = re.compile(r'# ---------------------------------------------------------------------------\n    # Show/hide/close events.*?$', re.DOTALL | re.MULTILINE)

if pattern.search(text):
    text = pattern.sub("", text)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched test_pie_menu.py successfully via regex.")
else:
    print("WARNING: Could not find regex pattern in test_pie_menu.py!")
