import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from fastprompter.core.translations import tr

class SaipenViewerDialog(QDialog):
    def __init__(self, main_win, saipen_dir, initial_tab="STATE"):
        super().__init__(main_win)
        self.main_win = main_win
        self.saipen_dir = saipen_dir
        self.lang = getattr(main_win, "_current_lang", "EN")
        
        self.setWindowTitle(tr("SAIPEN Viewer", self.lang) + f" - {saipen_dir}")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.text_state = QTextEdit()
        self.text_state.setReadOnly(True)
        self.text_board = QTextEdit()
        self.text_board.setReadOnly(True)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        
        try:
            base_size = self.main_win._font_size
        except AttributeError:
            base_size = 11
            
        try:
            family = self.main_win._font_family
        except AttributeError:
            family = "Verdana"
            
        try:
            scale = self.main_win._ui_scale
        except AttributeError:
            scale = 1.0
            
        font_size = max(8, int(round(base_size * scale)))
        
        try:
            from fastprompter.utils.fonts import resolve_family, no_aa
            font = no_aa(QFont(resolve_family(family), font_size))
        except ImportError:
            font = QFont(family, font_size)
            
        self.text_state.setFont(font)
        self.text_board.setFont(font)
        self.text_log.setFont(font)
        
        self.tabs.addTab(self.text_state, tr("STATE", self.lang))
        self.tabs.addTab(self.text_board, tr("BOARD", self.lang))
        self.tabs.addTab(self.text_log, tr("LOG", self.lang))
        
        self.reload_files()
        
        btn_layout = QHBoxLayout()
        btn_reload = QPushButton(tr("Reload", self.lang))
        btn_reload.clicked.connect(self.reload_files)
        btn_close = QPushButton(tr("Close", self.lang))
        btn_close.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_reload)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
        
        if hasattr(self.main_win, "apply_button_size"):
            self.main_win.apply_button_size(btn_reload, 30)
            self.main_win.apply_button_size(btn_close, 30)
        
        idx = {"STATE": 0, "BOARD": 1, "LOG": 2}.get(initial_tab.upper(), 0)
        self.tabs.setCurrentIndex(idx)
        
    def reload_files(self):
        files = {
            "STATE.md": self.text_state,
            "BOARD.md": self.text_board,
            "LOG.md": self.text_log
        }
        for filename, editor in files.items():
            path = os.path.join(self.saipen_dir, filename)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                        editor.setPlainText(text)
                        if filename == "LOG.md":
                            editor.moveCursor(editor.textCursor().MoveOperation.End)
                        else:
                            editor.moveCursor(editor.textCursor().MoveOperation.Start)
                except Exception as e:
                    editor.setPlainText(f"Error reading {filename}: {e}")
            else:
                editor.setPlainText(f"File not found: {filename}")
