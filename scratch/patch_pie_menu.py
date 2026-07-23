import os

filepath = 'src/fastprompter/ui/pie_menu.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Remove pynput import
text = text.replace("from pynput import keyboard\n", "")

# 2. Remove kb_listener from __init__
text = text.replace("self.kb_listener = None\n", "")

# 3. Replace showEvent, hideEvent, closeEvent, on_global_key_press with keyPressEvent
old_events = """    def showEvent(self, event):
        super().showEvent(event)
        if self.kb_listener is None:
            self.kb_listener = keyboard.Listener(on_press=self.on_global_key_press)
            self.kb_listener.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.kb_listener is not None:
            self.kb_listener.stop()
            self.kb_listener = None

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.kb_listener is not None:
            self.kb_listener.stop()
            self.kb_listener = None

    def on_global_key_press(self, key):
        if key == keyboard.Key.esc:
            QMetaObject.invokeMethod(self, "close", Qt.ConnectionType.QueuedConnection)"""

new_events = """    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)"""

if old_events in text:
    text = text.replace(old_events, new_events)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched pie_menu.py successfully.")
else:
    print("WARNING: Could not find old_events in pie_menu.py!")
