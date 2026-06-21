THEMES = {
    "Original Gold": {
        "stylesheet": """
QWidget { background-color: #1a1a1a; color: #c4ba9f; font-size: 11px; }
QMainWindow { background-color: #1a1a1a; border: 1px solid #4a4a4a; }
QTextEdit { background-color: #0f0f0f; color: #dcd3b6; border: 1px inset #050505; padding: 2px; }
QPushButton { background-color: #2b2b2b; color: #bfa65e; border: 1px outset #4a4a4a; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #1c1c1c; border: 1px inset #050505; color: #d6be76; }
QTabBar::tab { background: #2b2b2b; border: 1px outset #4a4a4a; padding: 3px 8px; color: #7a7566; }
QTabBar::tab:selected { background: #1c1c1c; border: 1px inset #050505; font-weight: bold; color: #d6be76; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #1c1c1c; border: 1px outset #4a4a4a; }
QMenu::item:selected { background-color: #bfa65e; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #0f0f0f; color: #c4ba9f; border: 1px inset #050505; padding: 2px; }
QCheckBox { color: #c4ba9f; }
QCheckBox::indicator { width: 12px; height: 12px; background: #0f0f0f; border: 1px inset #050505; }
QCheckBox::indicator:checked { background: #bfa65e; }
QToolTip { color: #ffffff; background-color: #2b2b2b; border: 1px solid #bfa65e; padding: 2px; }
QSplitter::handle { background-color: #2b2b2b; }
#SearchFrame { background-color: #1c1c1c; border: 1px solid #4a4a4a; border-radius: 2px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 2px; border: 1px outset #4a4a4a; background-color: #2b2b2b; margin: 0px; }
""",
        "preset_colors": ["#1e1e1e","#24221c","#1c2420","#241f1c","#1c1c24", "#22241c","#1c2224","#241c22","#24241c","#1a1a1a"],
        "active_temp_color": "#3a3a2a",
        "inactive_temp_color": "#1c1c1c",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #4a3b1f; color: #ffeb99; font-weight: bold; padding: 4px; border: 1px outset #5a4b2f;",
        "btn_save": "background-color: #1b2c3b; color: #8acee6; font-weight: bold; padding: 4px; border: 1px outset #2c4257;",
        "lbl_help": "font-size: 12px; color: #8acee6;",
        "lbl_title": "font-weight: bold; color: #bfa65e;",
        "mini_settings": "QFrame { background-color: #2b2b2b; border: 1px solid #4a4a4a; padding: 2px; }"
    },
    "Vintage Dark": {
        "stylesheet": """
QWidget { background-color: #1a1a1a; color: #c0c0c0; font-size: 11px; }
QMainWindow { background-color: #1a1a1a; border: 2px solid #808080; }
QTextEdit { background-color: #000000; color: #c0c0c0; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; padding: 2px; }
QPushButton { background-color: #2b2b2b; color: #c0c0c0; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #141414; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; color: #5a7a96; padding: 4px 2px 0px 6px; }
QTabBar::tab { background: #2b2b2b; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000; padding: 3px 8px; color: #969696; }
QTabBar::tab:selected { background: #1a1a1a; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; font-weight: bold; color: #5a7a96; padding: 4px 7px 2px 9px; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #2b2b2b; border: 2px solid #808080; }
QMenu::item:selected { background-color: #5a7a96; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #000000; color: #c0c0c0; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; padding: 1px; }
QCheckBox { color: #c0c0c0; spacing: 4px; padding: 0px; margin: 0px; }
QCheckBox::indicator { width: 10px; height: 10px; background: #000000; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; }
QCheckBox::indicator:checked { background: #5a7a96; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; }
QToolTip { color: #c0c0c0; background-color: #2b2b2b; border: 1px solid #808080; padding: 2px; }
QSplitter::handle { background-color: #1a1a1a; }
#SearchFrame { background-color: #141414; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000; border-radius: 0px; padding: 0px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 1px; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000; background-color: #2b2b2b; margin: 0px; }
""",
        "preset_colors": ["#1a1a1a"] * 10,
        "active_temp_color": "#203a4f",
        "inactive_temp_color": "#1a1a1a",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #2b2b2b; color: #5a7a96; font-weight: bold; font-size: 11px; padding: 4px; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000;",
        "btn_save": "background-color: #1e1e1e; color: #c0c0c0; font-weight: bold; font-size: 11px; padding: 4px; border: 2px solid; border-top-color: #808080; border-left-color: #808080; border-right-color: #000000; border-bottom-color: #000000;",
        "lbl_help": "font-size: 12px; color: #5a7a96;",
        "lbl_title": "font-weight: bold; color: #c0c0c0;",
        "mini_settings": "QFrame { background-color: #141414; border: 2px solid; border-top-color: #000000; border-left-color: #000000; border-right-color: #808080; border-bottom-color: #808080; padding: 0px; }"
    },
    "Vintage Classic": {
        "stylesheet": """
QWidget { background-color: #c0c0c0; color: #000000; font-size: 11px; }
QMainWindow { background-color: #c0c0c0; border: 2px solid #808080; }
QTextEdit { background-color: #ffffff; color: #000000; border: 2px inset #808080; padding: 4px; }
QPushButton { background-color: #c0c0c0; color: #000000; border: 2px outset #ffffff; padding: 3px 6px; }
QPushButton:pressed, QPushButton:checked { background-color: #e6e6e6; border: 2px inset #808080; color: #5e7a7a; }
QTabBar::tab { background: #c0c0c0; border: 2px outset #ffffff; padding: 4px 10px; color: #202020; }
QTabBar::tab:selected { background: #e6e6e6; border: 2px inset #808080; font-weight: bold; color: #5e7a7a; }
QTabBar::scroller { width: 0px; }
QMenu { background-color: #c0c0c0; border: 2px outset #ffffff; }
QMenu::item:selected { background-color: #5e7a7a; color: #ffffff; }
QSpinBox, QComboBox, QLineEdit { background-color: #ffffff; color: #000000; border: 2px inset #808080; padding: 2px; }
QCheckBox { color: #000000; }
QCheckBox::indicator { width: 12px; height: 12px; background: #ffffff; border: 2px inset #808080; }
QCheckBox::indicator:checked { background: #5e7a7a; }
QToolTip { color: #000000; background-color: #ffffff; border: 1px solid #000000; padding: 4px; }
QSplitter::handle { background-color: #c0c0c0; }
#SearchFrame { background-color: #c0c0c0; border: 1px solid #808080; border-radius: 2px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 2px; border: 2px outset #ffffff; background-color: #c0c0c0; margin: 0px; }
""",
        "preset_colors": ["#d4d0c8", "#c0c0c0", "#a0a0a0", "#c0c0c0"],
        "active_temp_color": "#5e7a7a",
        "inactive_temp_color": "#e6e6e6",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #c0c0c0; color: #5e7a7a; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #ffffff;",
        "btn_save": "background-color: #c0c0c0; color: #000000; font-weight: bold; font-size: 12px; padding: 6px; border: 2px outset #ffffff;",
        "lbl_help": "font-size: 14px; color: #808080;",
        "lbl_title": "font-weight: bold; color: #000000;",
        "mini_settings": "QFrame { background-color: #c0c0c0; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; } QLabel { color: #000000; } QCheckBox { color: #000000; } QComboBox, QSpinBox { background-color: #ffffff; color: #000000; border: 2px solid #808080; border-bottom-color: #ffffff; border-right-color: #ffffff; } QPushButton { background-color: #c0c0c0; color: #000000; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; }"
    }
}
