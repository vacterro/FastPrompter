import os

filepath = 'src/fastprompter/main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

lines = text.split('\n')

# 1. Add buttons in init_ui
init_idx = -1
for i, line in enumerate(lines):
    if 'self.btn_project_folder.clicked.connect(self._open_silo_project_folder)' in line:
        init_idx = i
        break

new_buttons = """        self.btn_saipen_state = QPushButton("STATE")
        self.apply_button_size(self.btn_saipen_state, 20)
        self.btn_saipen_state.clicked.connect(lambda: self.open_saipen_dialog("STATE"))
        self.btn_saipen_state.hide()

        self.btn_saipen_board = QPushButton("BOARD")
        self.apply_button_size(self.btn_saipen_board, 20)
        self.btn_saipen_board.clicked.connect(lambda: self.open_saipen_dialog("BOARD"))
        self.btn_saipen_board.hide()

        self.btn_saipen_log = QPushButton("LOG")
        self.apply_button_size(self.btn_saipen_log, 20)
        self.btn_saipen_log.clicked.connect(lambda: self.open_saipen_dialog("LOG"))
        self.btn_saipen_log.hide()
"""
lines.insert(init_idx + 2, new_buttons)

# 2. Add them to header_layout
header_idx = -1
for i, line in enumerate(lines):
    if 'self.header_layout.addWidget(self.btn_project_run)' in line:
        header_idx = i
        break

if header_idx != -1:
    new_header = """        self.header_layout.addWidget(self.btn_saipen_state)
        self.header_layout.addWidget(self.btn_saipen_board)
        self.header_layout.addWidget(self.btn_saipen_log)"""
    lines.insert(header_idx + 1, new_header)

# Wait, btn_project_run is not added to header_layout explicitly there? Let's check where it's added.
# Ah, the overflow menu uses it. We also need to add them to OVERFLOW MENU!
# def _overflow_hidden_buttons(self):
#    return ( ... ("btn_saipen_state", "Saipen State"), ... )
overflow_idx = -1
for i, line in enumerate(lines):
    if '("btn_project_run", "Run project"),' in line:
        overflow_idx = i
        break

if overflow_idx != -1:
    lines.insert(overflow_idx + 1, '          ("btn_saipen_state", "Saipen STATE"),\n          ("btn_saipen_board", "Saipen BOARD"),\n          ("btn_saipen_log", "Saipen LOG"),')

# btn_configs translation
btn_config_idx = -1
for i, line in enumerate(lines):
    if '("btn_project_run", None, "Run Executable", None),' in line:
        btn_config_idx = i
        break
if btn_config_idx != -1:
    lines.insert(btn_config_idx + 1, '            ("btn_saipen_state", None, "Saipen STATE", None),\n            ("btn_saipen_board", None, "Saipen BOARD", None),\n            ("btn_saipen_log", None, "Saipen LOG", None),')

# 3. Update visibility in _update_project_buttons
update_proj_idx = -1
for i, line in enumerate(lines):
    if 'def update_project_buttons(self):' in line:
        update_proj_idx = i
        break

if update_proj_idx != -1:
    for i in range(update_proj_idx, len(lines)):
        if 'if hasattr(self, "btn_project_run"):' in lines[i]:
            vis_idx = i
            break
    
    new_vis = """        has_saipen = False
        if folder:
            has_saipen = os.path.isdir(os.path.join(folder, ".saipen"))
        if hasattr(self, "btn_saipen_state"):
            self.btn_saipen_state.setVisible(has_saipen)
            self.btn_saipen_board.setVisible(has_saipen)
            self.btn_saipen_log.setVisible(has_saipen)
"""
    lines.insert(vis_idx + 2, new_vis)

# 4. Add open_saipen_dialog
end_files_btn_idx = -1
for i, line in enumerate(lines):
    if 'def _update_files_button(self):' in line:
        end_files_btn_idx = i
        break

open_saipen = """    def open_saipen_dialog(self, tab):
        from fastprompter.ui.saipen_dialog import SaipenViewerDialog
        import sip
        paths = self.data.get("silo_project_paths", {}).get(str(self.active_temp_slot), {})
        folder = paths.get("folder", "")
        if folder:
            import os
            saipen_dir = os.path.join(folder, ".saipen")
            if os.path.isdir(saipen_dir):
                if hasattr(self, "_saipen_dialog") and getattr(self, "_saipen_dialog", None) is not None and not sip.isdeleted(self._saipen_dialog) and self._saipen_dialog.isVisible():
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
if end_files_btn_idx != -1:
    lines.insert(end_files_btn_idx, open_saipen)


# 5. Patch changeEvent again
start_idx = -1
for i, line in enumerate(lines):
    if 'def changeEvent(self, event):' in line:
        start_idx = i
        break

end_idx = -1
for i in range(start_idx + 1, len(lines)):
    if 'def eventFilter(self, obj, event):' in lines[i]:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
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
    lines[start_idx:end_idx] = new_changeEvent_block.split('\n')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Restored Saipen integration successfully.')
