import os
import re

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

old_event = """    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        import sip
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowDeactivate):
            if not self.isActiveWindow() and not self.isMinimized():
                if getattr(self, "cb_focus", None) and self.cb_focus.isChecked():
                    help_dlg = getattr(self, "_help_dialog", None)
                    help_open = (
                        help_dlg is not None
                        and not sip.isdeleted(help_dlg)
                        and help_dlg.isVisible()
                    )
                    saipen_dlg = getattr(self, "_saipen_dialog", None)
                    saipen_open = (
                        saipen_dlg is not None
                        and not sip.isdeleted(saipen_dlg)
                        and saipen_dlg.isVisible()
                    )"""

new_event = """    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowDeactivate):
            if not self.isActiveWindow() and not self.isMinimized():
                if getattr(self, "cb_focus", None) and self.cb_focus.isChecked():
                    help_dlg = getattr(self, "_help_dialog", None)
                    help_open = False
                    if help_dlg is not None:
                        try:
                            help_open = help_dlg.isVisible()
                        except RuntimeError:
                            pass
                    
                    saipen_dlg = getattr(self, "_saipen_dialog", None)
                    saipen_open = False
                    if saipen_dlg is not None:
                        try:
                            saipen_open = saipen_dlg.isVisible()
                        except RuntimeError:
                            pass"""

if old_event in text:
    text = text.replace(old_event, new_event)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Patched changeEvent successfully.")
else:
    print("WARNING: Could not find old_event in main.py!")
