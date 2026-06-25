from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLabel, QPushButton, QDialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

class HotkeyWidget(QWidget):
    def __init__(self, default_text=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_key = QLabel(default_text)
        self.lbl_key.setStyleSheet("font-weight: bold;")
        self.btn_bind = QPushButton("Bind")
        self.btn_bind.setFixedWidth(50)
        self.btn_bind.clicked.connect(self.start_listening)
        self.layout.addWidget(self.lbl_key)
        self.layout.addWidget(self.btn_bind)
        self.is_listening = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
    def start_listening(self):
        self.is_listening = True
        self.btn_bind.setText("...")
        self.setFocus()
        
    def keyPressEvent(self, event):
        if not self.is_listening:
            super().keyPressEvent(event); return
        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta): return
        if key == Qt.Key.Key_Escape:
            self.btn_bind.setText("Bind"); self.is_listening = False; self.clearFocus(); return
            
        modifiers, parts = event.modifiers(), []
        if modifiers & Qt.KeyboardModifier.ControlModifier: parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier: parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier: parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier: parts.append("Win")
        
        key_str = QKeySequence(key).toString()
        if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and Qt.Key.Key_0 <= key <= Qt.Key.Key_9: key_str = f"Numpad{chr(key)}"
        if key_str:
            parts.append(key_str)
            self.setText("+".join(parts))
        self.is_listening = False
        self.btn_bind.setText("Bind")
        self.clearFocus()

    def setText(self, text):
        self.lbl_key.setText(text)
        
    def text(self):
        return self.lbl_key.text()

class HotkeySettingsDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.main_win = main_win
        self.main_win.unregister_all_hotkeys()
        self.setWindowTitle("Configure Global Hotkeys")
        self.setMinimumWidth(400)
        
        layout, form_layout = QVBoxLayout(self), QFormLayout()
        
        self.le_global = HotkeyWidget(self.main_win.data.get("global_hotkey", "Alt+X"))
        form_layout.addRow("Toggle UI (Global):", self.le_global)
        self.le_pie = HotkeyWidget(self.main_win.data.get("pie_menu_hotkey", "Shift+Alt+X"))
        form_layout.addRow("Summon Quick List:", self.le_pie)
        self.le_lock = HotkeyWidget(self.main_win.data.get("lock_window_hotkey", "Ctrl+Shift+L"))
        form_layout.addRow("Toggle Lock Window:", self.le_lock)
        self.le_top = HotkeyWidget(self.main_win.data.get("always_on_top_hotkey", "Ctrl+Shift+E"))
        form_layout.addRow("Toggle Always on Top:", self.le_top)
        
        self.snippet_inputs = []
        for i in range(10):
            le = HotkeyWidget(self.main_win.data.get(f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i+1 if i < 9 else 0}"))
            self.snippet_inputs.append(le)
            form_layout.addRow(f"Paste Snippet {i+1}:", le)
            
        layout.addLayout(form_layout)
        
        btn_layout, btn_reset, btn_save = QHBoxLayout(), QPushButton("Reset Defaults"), QPushButton("Save Hotkeys")
        btn_reset.clicked.connect(self.reset_defaults)
        btn_save.clicked.connect(self.save_hotkeys)
        btn_layout.addWidget(btn_reset); btn_layout.addStretch(); btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        
    def reset_defaults(self):
        self.le_global.setText("Alt+X")
        self.le_pie.setText("Shift+Alt+X")
        self.le_lock.setText("Ctrl+Shift+L")
        self.le_top.setText("Ctrl+Shift+E")
        for i, le in enumerate(self.snippet_inputs): le.setText(f"Ctrl+Shift+Numpad{i+1 if i < 9 else 0}")
         
    def save_hotkeys(self):
        self.main_win.data["global_hotkey"] = self.le_global.text()
        self.main_win.data["pie_menu_hotkey"] = self.le_pie.text()
        self.main_win.data["lock_window_hotkey"] = self.le_lock.text()
        self.main_win.data["always_on_top_hotkey"] = self.le_top.text()
        for i, le in enumerate(self.snippet_inputs): self.main_win.data[f"snippet_{i}_hotkey"] = le.text()
        self.main_win.mark_dirty()
        self.main_win.save_data_to_db(force=True)
        self.accept()
        
    def accept(self):
        self.main_win.register_all_hotkeys(); super().accept()
        
    def reject(self):
        self.main_win.register_all_hotkeys(); super().reject()

from PyQt6.QtWidgets import QColorDialog

class ColorConfigDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.main_win = main_win
        self.setWindowTitle("Custom Theme Colors (RGB)")
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        
        # Default custom colors
        cc = self.main_win.data.get("custom_colors", {
            "bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0",
            "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
            "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
            "accent": "#5a7a96"
        })
        if isinstance(cc, str):
            import ast
            try: cc = ast.literal_eval(cc)
            except Exception: pass
        if not isinstance(cc, dict):
            cc = {"bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0", "border_light": "#4d4d4d", "border_dark": "#0a0a0a", "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0", "accent": "#5a7a96"}
        self.custom_colors = cc
        
        self.color_buttons = {}
        labels = {
            "bg_main": "Main Background", "bg_text": "Text Area Background",
            "text_main": "Main Text Color", "border_light": "Border (Light edge)",
            "border_dark": "Border (Dark edge)", "btn_bg": "Button Background",
            "btn_pressed": "Button Pressed", "btn_text": "Button Text",
            "accent": "Accent Color"
        }
        
        for key, name in labels.items():
            btn = QPushButton(self.custom_colors.get(key, "#000000"))
            btn.setStyleSheet(f"background-color: {btn.text()}; color: white; font-weight: bold;")
            btn.clicked.connect(lambda checked, k=key: self.pick_color(k))
            self.color_buttons[key] = btn
            self.form_layout.addRow(name + ":", btn)
            
        layout.addLayout(self.form_layout)
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton("Сбросить")
        btn_load_theme = QPushButton("Взять с текущей темы")
        btn_save = QPushButton("Save & Apply")
        
        btn_reset.clicked.connect(self.reset_colors)
        btn_load_theme.clicked.connect(self.load_from_theme)
        btn_save.clicked.connect(self.save_colors)
        
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_load_theme)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
    def pick_color(self, key):
        from PyQt6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.custom_colors[key]), self, "Pick Color")
        if color.isValid():
            hex_c = color.name()
            self.custom_colors[key] = hex_c
            btn = self.color_buttons[key]
            btn.setText(hex_c)
            btn.setStyleSheet(f"background-color: {hex_c}; color: {'black' if color.lightness() > 128 else 'white'}; font-weight: bold;")
            
    def load_from_theme(self):
        current_theme_name = self.main_win.data.get("theme", "Default")
        from fastprompter.theme.themes import THEMES
        theme_data = THEMES.get(current_theme_name, THEMES["Default"])
        raw = theme_data.get("raw_colors", None)
        if not raw: return
        self.custom_colors = raw.copy()
        for k, btn in self.color_buttons.items():
            if k in self.custom_colors:
                hex_c = self.custom_colors[k]
                btn.setText(hex_c)
                btn.setStyleSheet(f"background-color: {hex_c}; color: white; font-weight: bold;")

    def reset_colors(self):
        defaults = {
            "bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0",
            "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
            "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
            "accent": "#5a7a96"
        }
        self.custom_colors = defaults
        for k, btn in self.color_buttons.items():
            hex_c = defaults[k]
            btn.setText(hex_c)
            btn.setStyleSheet(f"background-color: {hex_c}; color: white; font-weight: bold;")
            
    def save_colors(self):
        self.main_win.data["custom_colors"] = self.custom_colors
        self.main_win.data["theme"] = "Custom"
        self.main_win.mark_dirty()
        self.main_win.apply_theme()
        if hasattr(self.main_win, 'cb_theme'):
            idx = self.main_win.cb_theme.findText("Custom")
            if idx >= 0: self.main_win.cb_theme.setCurrentIndex(idx)
        self.accept()
