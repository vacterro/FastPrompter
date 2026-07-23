import os
import re

filepath = 'src/fastprompter/ui/pie_menu.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Remove pynput import
text = re.sub(r'^from pynput import keyboard\n', '', text, flags=re.MULTILINE)

# 2. Remove kb_listener from __init__
text = re.sub(r'\s*self\.kb_listener = None\n', '\n', text)

# 3. Replace showEvent, hideEvent, closeEvent, on_global_key_press with keyPressEvent
pattern = re.compile(r'    def showEvent.*?Connection\)', re.DOTALL)

new_events = """    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)"""

if pattern.search(text):
    text = pattern.sub(lambda m: new_events, text)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched pie_menu.py successfully via regex.")
else:
    print("WARNING: Could not find regex pattern in pie_menu.py!")
