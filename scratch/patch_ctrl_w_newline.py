import os

filepath = 'src/fastprompter/ui/formatting_mixin.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_logic = """        if top_type == "TEXT" and bottom_type == "TEXT":
            text_to_insert = "---\\n\\n"
            offset = 3
        else:
            if top_type != "DIVIDER":
                text_to_insert += "---\\n\\n"
                offset += 5"""

new_logic = """        if top_type == "TEXT" and bottom_type == "TEXT":
            text_to_insert = "\\n---\\n\\n"
            offset = 5
        else:
            if top_type != "DIVIDER":
                text_to_insert += "\\n---\\n\\n"
                offset += 6"""

if old_logic in text:
    text = text.replace(old_logic, new_logic)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched insert_add_line successfully.")
else:
    print("WARNING: Could not find old_logic in main.py!")
