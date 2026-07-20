from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from fastprompter.core.translations import tr

class SiloSettingsDialog(QDialog):
    def __init__(self, main_win, global_idx):
        super().__init__(main_win)
        self.main_win = main_win
        self.global_idx = str(global_idx)
        self.lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Configure Project Paths", self.lang))
        self.setMinimumWidth(400)
        
        self.paths = self.main_win.data.get("silo_project_paths", {}).get(self.global_idx, {})
        if not isinstance(self.paths, dict):
            self.paths = {}
            
        layout = QVBoxLayout(self)
        
        # Project Folder
        layout.addWidget(QLabel(tr("Project Folder (📂):", self.lang)))
        hbox_folder = QHBoxLayout()
        self.edit_folder = QLineEdit(self.paths.get("folder", ""))
        self.edit_folder.setPlaceholderText(tr("Path to external project folder...", self.lang))
        btn_browse_folder = QPushButton("...")
        btn_browse_folder.clicked.connect(self._browse_folder)
        hbox_folder.addWidget(self.edit_folder)
        hbox_folder.addWidget(btn_browse_folder)
        layout.addLayout(hbox_folder)
        
        # Executable File
        layout.addWidget(QLabel(tr("Executable File (▶️):", self.lang)))
        hbox_exe = QHBoxLayout()
        self.edit_exe = QLineEdit(self.paths.get("executable", ""))
        self.edit_exe.setPlaceholderText(tr("Path to any file to launch...", self.lang))
        btn_browse_exe = QPushButton("...")
        btn_browse_exe.clicked.connect(self._browse_exe)
        hbox_exe.addWidget(self.edit_exe)
        hbox_exe.addWidget(btn_browse_exe)
        layout.addLayout(hbox_exe)
        
        # Action Buttons
        hbox_actions = QHBoxLayout()
        hbox_actions.addStretch()
        btn_save = QPushButton(tr("Save", self.lang))
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton(tr("Cancel", self.lang))
        btn_cancel.clicked.connect(self.reject)
        hbox_actions.addWidget(btn_save)
        hbox_actions.addWidget(btn_cancel)
        layout.addLayout(hbox_actions)
        
        self.main_win.apply_button_size(btn_save, 30)
        self.main_win.apply_button_size(btn_cancel, 30)
        self.main_win.apply_button_size(btn_browse_folder, 24, 24)
        self.main_win.apply_button_size(btn_browse_exe, 24, 24)
        
    def _browse_folder(self):
        start_dir = self.edit_folder.text() or ""
        folder = QFileDialog.getExistingDirectory(self, tr("Select Project Folder", self.lang), start_dir)
        if folder:
            self.edit_folder.setText(folder)
            
    def _browse_exe(self):
        import os
        start_dir = self.edit_exe.text() or self.edit_folder.text() or ""
        if start_dir and not os.path.isdir(start_dir) and os.path.isdir(os.path.dirname(start_dir)):
            start_dir = os.path.dirname(start_dir)
        file, _ = QFileDialog.getOpenFileName(self, tr("Select Executable File", self.lang), start_dir, "All Files (*.*)")
        if file:
            self.edit_exe.setText(file)

    def accept(self):
        folder = self.edit_folder.text().strip()
        exe = self.edit_exe.text().strip()
        
        # mutate in place — this dict is aliased into silo_project_paths_all
        # for the active category; rebinding it would orphan that alias
        all_paths = self.main_win.data.setdefault("silo_project_paths", {})
        if not folder and not exe:
            all_paths.pop(self.global_idx, None)
        else:
            all_paths[self.global_idx] = {"folder": folder, "executable": exe}

        self.main_win.mark_dirty()
        super().accept()
