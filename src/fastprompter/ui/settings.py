from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.translations import tr


class HotkeyWidget(QWidget):
    def __init__(self, default_text="", lang="EN"):
        super().__init__()
        self.lang = lang
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_key = QLabel(default_text if default_text is not None else "")
        self.lbl_key.setStyleSheet("font-weight: bold;")
        self.btn_bind = QPushButton(tr("Bind", self.lang))
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
            self.btn_bind.setText(tr("Bind", self.lang)); self.is_listening = False; self.clearFocus(); return

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
        self.btn_bind.setText(tr("Bind", self.lang))
        self.clearFocus()

    def setText(self, text):
        self.lbl_key.setText(text if text is not None else "")
        return self.lbl_key.text()

    def text(self):
        return self.lbl_key.text()

class DualHotkeyWidget(QWidget):
    def __init__(self, main_win, key_name, default1, default2=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.key_name = key_name
        lang = getattr(main_win, "_current_lang", "EN")
        self.hw1 = HotkeyWidget(main_win.data.get(key_name, default1), lang=lang)
        self.hw2 = HotkeyWidget(main_win.data.get(f"{key_name}_alt", default2), lang=lang)

        self.layout.addWidget(self.hw1)
        self.layout.addWidget(QLabel(" / "))
        self.layout.addWidget(self.hw2)

    def save_to_data(self, main_win):
        main_win.data[self.key_name] = self.hw1.text()
        main_win.data[f"{self.key_name}_alt"] = self.hw2.text()

    def reset_defaults(self, default1, default2=""):
        self.hw1.setText(default1)
        self.hw2.setText(default2)

class HotkeySettingsDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, '_current_lang', 'EN')
        self.main_win.unregister_all_hotkeys()
        self.setWindowTitle(tr("Configure Global Hotkeys", self.lang))
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        from PyQt6.QtWidgets import QScrollArea, QTabWidget
        self.tabs = QTabWidget()

        tab_global = QWidget()
        form_global = QFormLayout(tab_global)

        self.le_global = DualHotkeyWidget(self.main_win, "global_hotkey", "Alt+X", "F15")
        form_global.addRow(tr("Toggle UI (Global):", self.lang), self.le_global)
        self.le_pie = DualHotkeyWidget(self.main_win, "pie_menu_hotkey", "Shift+Alt+X")
        form_global.addRow(tr("Summon Quick List:", self.lang), self.le_pie)
        self.le_lock = DualHotkeyWidget(self.main_win, "lock_window_hotkey", "Alt+S")
        form_global.addRow(tr("Toggle Lock Window:", self.lang), self.le_lock)
        self.le_top = DualHotkeyWidget(self.main_win, "always_on_top_hotkey", "Alt+E")
        form_global.addRow(tr("Toggle Always on Top:", self.lang), self.le_top)
        self.le_sidebar = DualHotkeyWidget(self.main_win, "toggle_sidebar_hotkey", "Alt+D")
        form_global.addRow(tr("Toggle Sidebar:", self.lang), self.le_sidebar)
        self.le_hideout = DualHotkeyWidget(self.main_win, "hide_on_clickout_hotkey", "Alt+A")
        form_global.addRow(tr("Toggle Hide on Click-Out:", self.lang), self.le_hideout)

        self.snippet_inputs = []
        for i in range(5):
            le = DualHotkeyWidget(self.main_win, f"snippet_{i}_hotkey", f"Ctrl+Shift+Numpad{i+1}")
            self.snippet_inputs.append(le)
            form_global.addRow(tr("Paste Snippet {}:", self.lang).format(i+1), le)

        self.silo_inputs = []
        for i in range(5):
            le = DualHotkeyWidget(self.main_win, f"silo_{i}_hotkey", f"Alt+Shift+Numpad{i+1}")
            self.silo_inputs.append(le)
            form_global.addRow(tr("Paste Silo {}:", self.lang).format(i+1), le)

        scroll_global = QScrollArea()
        scroll_global.setWidgetResizable(True)
        scroll_global.setWidget(tab_global)
        self.tabs.addTab(scroll_global, tr("Global / Actions", self.lang))

        tab_app = QWidget()
        form_app = QFormLayout(tab_app)
        self.app_binds = [
            ("hk_new_snippet", "Ctrl+N", "New Empty Snippet"),
            ("hk_save_snippet", "Ctrl+S", "Save Snippet"),
            ("hk_export_silo", "Ctrl+Shift+S", "Export Silo to file"),
            ("hk_find", "Ctrl+F", "Find Text"),
            ("hk_replace", "Ctrl+H", "Replace Text"),
            ("hk_focus", "Ctrl+D", "Toggle Focus Mode"),
            ("hk_header", "Ctrl+E", "Header+Bold+Underline+Timestamp"),
            ("hk_bold", "Ctrl+B", "Bold / Unbold Line"),
            ("hk_undo", "Ctrl+Z", "Undo Text Change"),
            ("hk_divider", "Ctrl+W", "Insert Divider Line"),
            ("hk_snap", "Ctrl+Q", "Cycle Snap Corners"),
            ("hk_quit", "Ctrl+Alt+Shift+Q", "Quit Application")
        ]
        self.app_inputs = {}
        for key_name, default_hk, label in self.app_binds:
            le = HotkeyWidget(self.main_win.data.get(key_name, default_hk), lang=self.lang)
            self.app_inputs[key_name] = le
            form_app.addRow(label + ":", le)

        scroll_app = QScrollArea()
        scroll_app.setWidgetResizable(True)
        scroll_app.setWidget(tab_app)
        self.tabs.addTab(scroll_app, tr("In-App Shortcuts", self.lang))

        tab_drop = QWidget()
        form_drop = QFormLayout(tab_drop)
        from PyQt6.QtWidgets import QComboBox
        self.drop_combos = {}
        drop_options = [
            ("text", tr("📝 Drop as Text", self.lang)),
            ("editor_link", tr("🔗 Link in Text", self.lang)),
            ("files", tr("📥 Copy to Files 📁", self.lang)),
            ("files_link", tr("🔗 Link in Files 📁", self.lang))
        ]
        default_map = {"drop_top_left": "text", "drop_top_right": "editor_link", "drop_bot_left": "files", "drop_bot_right": "files_link"}
        for key, label in [
            ("drop_top_left", tr("Top Left Zone", self.lang)),
            ("drop_top_right", tr("Top Right Zone", self.lang)),
            ("drop_bot_left", tr("Bottom Left Zone", self.lang)),
            ("drop_bot_right", tr("Bottom Right Zone", self.lang))
        ]:
            cb = QComboBox()
            for val, text in drop_options: cb.addItem(text, val)
            idx = cb.findData(self.main_win.data.get(key, default_map[key]))
            if idx >= 0: cb.setCurrentIndex(idx)
            self.drop_combos[key] = cb
            form_drop.addRow(label + ":", cb)
            
        scroll_drop = QScrollArea()
        scroll_drop.setWidgetResizable(True)
        scroll_drop.setWidget(tab_drop)
        self.tabs.addTab(scroll_drop, tr("Drop Zones", self.lang))

        layout.addWidget(self.tabs)

        btn_layout, btn_reset, btn_save = QHBoxLayout(), QPushButton(tr("Reset Defaults", self.lang)), QPushButton(tr("Save Hotkeys", self.lang))
        btn_reset.clicked.connect(self.reset_defaults)
        btn_save.clicked.connect(self.save_hotkeys)
        btn_layout.addWidget(btn_reset); btn_layout.addStretch(); btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def reset_defaults(self):
        self.le_global.reset_defaults("Alt+X", "F15")
        self.le_pie.reset_defaults("Shift+Alt+X")
        self.le_lock.reset_defaults("Alt+S")
        self.le_top.reset_defaults("Alt+E")
        self.le_sidebar.reset_defaults("Alt+D")
        self.le_hideout.reset_defaults("Alt+A")
        for i, le in enumerate(self.snippet_inputs): le.reset_defaults(f"Ctrl+Shift+Numpad{i+1}")
        for i, le in enumerate(self.silo_inputs): le.reset_defaults(f"Alt+Shift+Numpad{i+1}")
        for key_name, default_hk, _ in getattr(self, "app_binds", []):
            if key_name in self.app_inputs:
                self.app_inputs[key_name].setText(default_hk)

    def save_hotkeys(self):
        self.le_global.save_to_data(self.main_win)
        self.le_pie.save_to_data(self.main_win)
        self.le_lock.save_to_data(self.main_win)
        self.le_top.save_to_data(self.main_win)
        self.le_sidebar.save_to_data(self.main_win)
        self.le_hideout.save_to_data(self.main_win)
        for le in self.snippet_inputs: le.save_to_data(self.main_win)
        for le in self.silo_inputs: le.save_to_data(self.main_win)
        for key_name, le in getattr(self, "app_inputs", {}).items():
            self.main_win.data[key_name] = le.text()
        for key_name, cb in getattr(self, "drop_combos", {}).items():
            self.main_win.data[key_name] = cb.currentData()
        self.main_win.setup_global_shortcuts()
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
        self.main_win = main_win
        self.lang = getattr(main_win, '_current_lang', 'EN')
        self.setWindowTitle(tr("Custom Theme Colors (RGB)", self.lang))
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        # Default custom colors
        cc = self.main_win.data.get("custom_colors", {
            "bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0",
            "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
            "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
            "accent": "#5a7a96", "edit_bg": "#2a3330",
            "overlay_new": "#6a5555", "overlay_recent": "#6a5a40",
            "overlay_day": "#5a5a30", "overlay_old": "#40506a"
        })
        if isinstance(cc, str):
            import ast
            try: cc = ast.literal_eval(cc)
            except Exception as e:
                from fastprompter.core.logging import logger
                logger.debug(f"Failed to parse custom_colors: {e}")
        if not isinstance(cc, dict):
            cc = {"bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0", "border_light": "#4d4d4d", "border_dark": "#0a0a0a", "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0", "accent": "#5a7a96", "edit_bg": "#2a3330", "overlay_new": "#6a5555", "overlay_recent": "#6a5a40", "overlay_day": "#5a5a30", "overlay_old": "#40506a"}

        # Ensure all keys exist if loading an old config or empty dict
        for fallback_key, fallback_val in {"bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0", "border_light": "#4d4d4d", "border_dark": "#0a0a0a", "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0", "accent": "#5a7a96", "edit_bg": "#2a3330", "overlay_new": "#6a5555", "overlay_recent": "#6a5a40", "overlay_day": "#5a5a30", "overlay_old": "#40506a"}.items():
            if fallback_key not in cc:
                cc[fallback_key] = fallback_val

        self.custom_colors = cc

        self.color_buttons = {}
        labels = {
            "bg_main": tr("Main Background", self.lang),
            "bg_text": tr("Text Area Background", self.lang),
            "text_main": tr("Main Text Color", self.lang),
            "border_light": tr("Border (Light edge)", self.lang),
            "border_dark": tr("Border (Dark edge)", self.lang),
            "btn_bg": tr("Button Background", self.lang),
            "btn_pressed": tr("Button Pressed", self.lang),
            "btn_text": tr("Button Text", self.lang),
            "accent": tr("Accent Color", self.lang),
            "edit_bg": tr("Editing Background", self.lang),
            "overlay_new": tr("Last Edited < 1 min", self.lang),
            "overlay_recent": tr("Last Edited < 1 hr", self.lang),
            "overlay_day": tr("Last Edited < 1 day", self.lang),
            "overlay_old": tr("Last Edited < 49 days", self.lang),
        }

        for key, name in labels.items():
            btn = QPushButton(self.custom_colors.get(key, "#000000"))
            btn.setStyleSheet(f"background-color: {btn.text()}; color: white; font-weight: bold;")
            btn.clicked.connect(lambda checked, k=key: self.pick_color(k))
            self.color_buttons[key] = btn
            self.form_layout.addRow(name + ":", btn)

        layout.addLayout(self.form_layout)
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton(tr("Reset", self.lang))
        btn_load_theme = QPushButton(tr("Load from Current Theme", self.lang))
        btn_save = QPushButton(tr("Save & Apply", self.lang))

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
        current_color = self.custom_colors.get(key, "#000000")
        color = QColorDialog.getColor(QColor(current_color), self, tr("Pick Color", self.lang))
        if color.isValid():
            hex_c = color.name()
            self.custom_colors[key] = hex_c
            btn = self.color_buttons[key]
            btn.setText(hex_c)
            btn.setStyleSheet(f"background-color: {hex_c}; color: {'black' if color.lightness() > 128 else 'white'}; font-weight: bold;")

    def load_from_theme(self):
        current_theme_name = self.main_win.data.get("theme", "Default")
        from PyQt6.QtGui import QColor

        from fastprompter.theme.themes import THEMES
        theme_data = THEMES.get(current_theme_name, THEMES["Default"])
        raw = theme_data.get("raw_colors", None)
        if not raw: return
        self.custom_colors = raw.copy()
        for k, btn in self.color_buttons.items():
            if k in self.custom_colors:
                hex_c = self.custom_colors[k]
                btn.setText(hex_c)
                col = QColor(hex_c)
                text_color = "black" if col.lightness() > 128 else "white"
                btn.setStyleSheet(f"background-color: {hex_c}; color: {text_color}; font-weight: bold;")

    def reset_colors(self):
        defaults = {
            "bg_main": "#1a1a1a", "bg_text": "#000000", "text_main": "#c0c0c0",
            "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
            "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
            "accent": "#5a7a96", "edit_bg": "#2a3330",
            "overlay_new": "#6a5555", "overlay_recent": "#6a5a40",
            "overlay_day": "#5a5a30", "overlay_old": "#40506a"
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
