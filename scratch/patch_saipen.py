import os

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

lines = text.split('\n')

# 1. Update open_saipen_dialog
start_idx = -1
for i, line in enumerate(lines):
    if 'def open_saipen_dialog(self, tab):' in line:
        start_idx = i
        break

end_idx = -1
for i in range(start_idx + 1, len(lines)):
    if 'def _update_files_button(self):' in line:
        end_idx = i
        break

new_saipen_block = """    def open_saipen_dialog(self, tab):
        from fastprompter.ui.saipen_dialog import SaipenViewerDialog
        import sip
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        folder = paths.get("folder", "")
        if folder:
            import os
            saipen_dir = os.path.join(folder, ".saipen")
            if os.path.isdir(saipen_dir):
                if hasattr(self, "_saipen_dialog") and not sip.isdeleted(self._saipen_dialog) and self._saipen_dialog.isVisible():
                    self._saipen_dialog.raise_()
                    self._saipen_dialog.activateWindow()
                    for i in range(self._saipen_dialog.tabs.count()):
                        if self._saipen_dialog.tabs.tabText(i) == tab:
                            self._saipen_dialog.tabs.setCurrentIndex(i)
                            break
                else:
                    self._saipen_dialog = SaipenViewerDialog(self, saipen_dir, tab)
                    self._saipen_dialog.show()

"""
lines[start_idx:end_idx] = new_saipen_block.split('\n')[:-1]

# 2. Update changeEvent
start_idx = -1
for i, line in enumerate(lines):
    if 'def changeEvent(self, event):' in line:
        start_idx = i
        break

end_idx = -1
for i in range(start_idx + 1, len(lines)):
    if 'def eventFilter(self, obj, event):' in line:
        end_idx = i
        break

new_changeEvent_block = """    def changeEvent(self, event):
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
                    )
                    if (
                        not getattr(self, "ignore_focus_loss", False)
                        and not getattr(self, "is_locked", False)
                        and not help_open
                        and not saipen_open
                    ):
                        self.hide_and_save()
        super().changeEvent(event)

"""
lines[start_idx:end_idx] = new_changeEvent_block.split('\n')[:-1]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Applied patches successfully.')
