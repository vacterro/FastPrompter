import os

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_code = """    def open_queue_master(self):
        \"\"\"Alt+Shift+C: open the active silo's prompt queue.\"\"\"
        self.open_queue_dialog(master=False)"""

new_code = """    def open_queue_master(self):
        \"\"\"Alt+Shift+C: open the prompt queue on the All Silos tab.\"\"\"
        self.open_queue_dialog(master=True)"""

if old_code in text:
    text = text.replace(old_code, new_code)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Fixed open_queue_master in main.py")
else:
    print("WARNING: Could not find old_code in main.py!")
