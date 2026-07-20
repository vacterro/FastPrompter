import os
import re

main_path = r"v:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    main_code = f.read()

# Fix T-163: Add import datetime at the top, replace __import__('datetime')
if "import datetime" not in main_code[:500]:
    main_code = main_code.replace("import os", "import os\nimport datetime", 1)
main_code = main_code.replace("__import__('datetime')", "datetime")
main_code = main_code.replace("        import datetime\n", "")

# Fix T-162: untranslated tooltips in main.py
# Example: self.btn_sidebar_toggle.setToolTip("Toggle Sidebar (Ctrl+B)") -> self.btn_sidebar_toggle.setToolTip(tr("Toggle Sidebar (Ctrl+B)", lang))
# We will just do a regex replace for setToolTip("...") if it's not already wrapped.
def replace_tooltip(m):
    obj = m.group(1)
    text = m.group(2)
    # If text already has tr(, ignore
    if "tr(" in text:
        return m.group(0)
    # some tooltips might have formatted text, but usually they are simple strings
    if text.startswith('f"') or text.startswith("f'"):
        return m.group(0) # skip f-strings for simple regex
    if 'lang' not in main_code[m.start():m.start()+200]:
        # we might need to use self.lang or getattr
        pass
    
    return f"{obj}.setToolTip(tr({text}, getattr(self, '_current_lang', 'EN')))"

main_code = re.sub(r"(self\.btn_[a-zA-Z0-9_]+)\.setToolTip\((['\"].*?['\"])\)", replace_tooltip, main_code)
main_code = re.sub(r"(btn)\.setToolTip\((['\"].*?['\"])\)", replace_tooltip, main_code)

# Fix T-166: hide_and_save() slow sync db save
# change self.save_data_to_db(force=True) to self.save_data_to_db(force=False) or run it async?
# Actually, the ticket says "hide_and_save() does full save_data_to_db(force=True) synchronously — slow I/O blocks the hide animation"
# Let's fix it by doing QTimer.singleShot(10, lambda: self.save_data_to_db(force=True))
main_code = main_code.replace("        self.hide_window()\n        self.save_data_to_db(force=True)", "        self.hide_window()\n        QTimer.singleShot(10, lambda: self.save_data_to_db(force=True))")

# Fix T-169: btn_bullet_toggle.setToolTip hardcodes ON/OFF
main_code = main_code.replace('state = "ON" if val == "True" else "OFF"', 'state = tr("ON", lang) if val == "True" else tr("OFF", lang)')

with open(main_path, "w", encoding="utf-8") as f:
    f.write(main_code)

print("Applied fixes to main.py")
