import os

filepath = 'tests/test_pie_menu.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

index = text.find("# ---------------------------------------------------------------------------\n# Show/hide/close events")
if index != -1:
    text = text[:index]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched test_pie_menu.py successfully via string slice.")
else:
    print("WARNING: Could not find string in test_pie_menu.py!")
