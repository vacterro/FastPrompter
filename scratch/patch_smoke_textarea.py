import os
import glob

target_files = glob.glob(r"tests_smoke\test_*.py")

for filepath in target_files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content.replace(
        'if getattr(w.editor, "_sel_refresh_pending", False):\n        w.editor._sel_refresh_pending = False',
        'if getattr(w, "text_area", None) and getattr(w.text_area, "_sel_refresh_pending", False):\n        w.text_area._sel_refresh_pending = False'
    )
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched editor to text_area in {filepath}")
