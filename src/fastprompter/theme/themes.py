def _clamp_byte(v):
    return max(0, min(255, int(round(v))))


def _hex_to_rgb(h):
    """#rgb or #rrggbb -> (r, g, b). Invalid input falls back to mid grey."""
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def blend_hex(c1, c2, t):
    """Blend two hex colors: t=0 -> c1, t=1 -> c2.

    Shared by every widget that has to derive a theme-aware shade from the
    active theme's raw_colors (drop overlay, analog clock, markdown
    highlighter, header bar) — previously each kept its own private copy.
    """
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return "#{:02x}{:02x}{:02x}".format(
        _clamp_byte(r1 + (r2 - r1) * t),
        _clamp_byte(g1 + (g2 - g1) * t),
        _clamp_byte(b1 + (b2 - b1) * t),
    )


def header_tint(raw):
    """Background of the header/toolbar bar for a theme's raw colours.

    Lives here because two places need the identical value: theme_mixin
    paints the bar with it, and the mini clock fills its own rectangle with
    it. When only theme_mixin knew the formula, the clock kept whatever was
    behind it when it was built and showed the Default theme's tint on every
    other theme - a visible square that never followed the theme.
    """
    return blend_hex(raw.get("bg_main", "#1a1a1a"),
                     raw.get("accent", "#bfa65e"), 0.16)


def hex_to_rgba(h, alpha):
    """Hex color -> 'rgba(r, g, b, a)' for QSS. alpha is 0.0-1.0."""
    r, g, b = _hex_to_rgb(h)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, float(alpha))):.2f})"


def scrollbar_qss(raw_colors):
    """Thin, ghost-until-hovered scrollbars tinted from the active theme.

    Native scrollbars dominate the window visually; this keeps them 7px,
    trackless and near-invisible at rest, fading up on hover.
    """
    accent = raw_colors.get("accent", "#bfa65e")
    return f"""
QScrollBar:vertical {{ background: transparent; width: 7px; margin: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 7px; margin: 0px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {hex_to_rgba(accent, 0.28)}; border: none; border-radius: 0px; min-height: 24px; min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {hex_to_rgba(accent, 0.85)}; }}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{ background: {accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def generate_custom_theme(c):
    # copy first: this used to c.setdefault() straight into the caller's dict,
    # silently mutating shared config references
    c = dict(c or {})
    _defaults = {"bg_main":"#1a1a1a","bg_text":"#2c2c2c","text_main":"#c0c0c0","border_light":"#4d4d4d","border_dark":"#0a0a0a","btn_bg":"#3a3a3a","btn_text":"#d0d0d0","btn_pressed":"#4a4a4a","accent":"#bfa65e"}
    for k, v in _defaults.items():
        c.setdefault(k, v)
    return {
        "stylesheet": f"""
QWidget {{ background-color: {c['bg_main']}; color: {c['text_main']}; font-size: 11px; }}
QMainWindow {{ background-color: {c['bg_main']}; border: 1px solid {c['border_dark']}; }}
QTextEdit {{ background-color: {c['bg_text']}; color: {c['text_main']}; border: 1px solid {c['border_dark']}; padding: 2px; }}
QPushButton {{ background-color: {c['btn_bg']}; color: {c['btn_text']}; border: 1px solid {c['border_dark']}; padding: 2px 4px; }}
QPushButton:pressed, QPushButton:checked {{ background-color: {c['btn_pressed']}; border: 1px inset {c['border_dark']}; color: {c['accent']}; padding: 4px 2px 0px 6px; }}
QTabBar::tab {{ background: {c['btn_bg']}; border: 1px solid {c['border_dark']}; padding: 3px 8px; color: {c['text_main']}; }}
QTabBar::tab:selected {{ background: {c['bg_main']}; border: 1px solid {c['accent']}; font-weight: bold; color: {c['accent']}; padding: 4px 7px 2px 9px; }}
QTabBar::scroller {{ width: 36px; }}
QMenu {{ background-color: {c['btn_bg']}; border: 1px solid {c['border_dark']}; }}
QMenu::item:selected {{ background-color: {c['accent']}; color: {c['bg_main']}; }}
QSpinBox, QComboBox, QLineEdit {{ background-color: {c['bg_text']}; color: {c['text_main']}; border: 1px solid {c['border_dark']}; padding: 1px; }}
QCheckBox {{ color: {c['text_main']}; spacing: 4px; padding: 0px; margin: 0px; }}
QCheckBox::indicator {{ width: 10px; height: 10px; background: {c['bg_main']}; border: 1px solid {c['border_dark']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['border_dark']}; }}
QToolTip {{ color: {c['text_main']}; background-color: {c['bg_main']}; border: 1px solid {c['border_dark']}; padding: 2px; }}
QSplitter::handle {{ background-color: {c['border_dark']}; }}
#SearchFrame {{ background-color: {c['bg_text']}; border: 1px solid {c['border_dark']}; border-radius: 0px; padding: 0px; }}
QDockWidget {{ margin: 0px; padding: 0px; border: 0px; }}
QDockWidget::title {{ padding: 1px; border: 1px solid {c['border_dark']}; background-color: {c['bg_main']}; margin: 0px; }}
""",
        "preset_colors": [c['bg_main']] * 10,
        "active_temp_color": c['btn_bg'],
        "inactive_temp_color": c['bg_main'],
        "tray_color": c['accent'],
        "btn_new": f"background-color: {c['btn_bg']}; color: {c['text_main']}; font-weight: bold; font-size: 11px; padding: 4px; border: 1px solid {c['border_dark']};",
        "btn_save": f"background-color: {c['btn_bg']}; color: {c['text_main']}; font-weight: bold; font-size: 11px; padding: 4px; border: 1px solid {c['border_dark']};",
        "lbl_help": f"font-size: 12px; color: {c['text_main']};",
        "lbl_title": f"font-weight: bold; color: {c['text_main']};",
        "mini_settings": f"QFrame {{ background-color: {c['bg_main']}; border: 1px solid {c['border_dark']}; padding: 0px; }}",
        "raw_colors": c
    }

THEMES = {
    # You can easily add your own themes! Just uncomment the block below and adjust colors:
    # "My Awesome Theme": generate_custom_theme({
    #     "bg_main": "#1a1a1a", "bg_text": "#2c2c2c", "text_main": "#c0c0c0",
    #     "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
    #     "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
    #     "accent": "#ff00aa"
    # }),
    "Default": generate_custom_theme({
        "bg_main": "#1a1a1a", "bg_text": "#2c2c2c", "text_main": "#c0c0c0",
        "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
        "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
        "accent": "#5a7a96"
    }),
    "Golden Vintage": {
        "stylesheet": """
QWidget { background-color: #1a1a1a; color: #c4ba9f; font-size: 11px; }
QMainWindow { background-color: #1a1a1a; border: 1px solid #4a4a4a; }
QTextEdit { background-color: #0f0f0f; color: #dcd3b6; border: 1px inset #050505; padding: 2px; }
QPushButton { background-color: #2b2b2b; color: #bfa65e; border: 1px outset #4a4a4a; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #1c1c1c; border: 1px inset #050505; color: #d6be76; }
QTabBar::tab { background: #2b2b2b; border: 1px outset #4a4a4a; padding: 3px 8px; color: #7a7566; }
QTabBar::tab:selected { background: #1c1c1c; border: 1px inset #050505; font-weight: bold; color: #d6be76; }
QTabBar::scroller { width: 36px; }
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
        "mini_settings": "QFrame { background-color: #2b2b2b; border: 1px solid #4a4a4a; padding: 2px; }",
        "raw_colors": {
            "bg_main": "#1a1a1a", "bg_text": "#0f0f0f", "text_main": "#c4ba9f",
            "border_light": "#4a4a4a", "border_dark": "#050505",
            "btn_bg": "#2b2b2b", "btn_pressed": "#1c1c1c", "btn_text": "#bfa65e",
            "accent": "#d6be76"
        }
    },
    "Golden Default": {
        "stylesheet": """
QWidget { background-color: #232018; color: #d4c89a; font-size: 11px; }
QMainWindow { background-color: #232018; border: 1px solid #5a5040; }
QTextEdit { background-color: #1a1810; color: #e8dbb0; border: 1px inset #100e08; padding: 2px; }
QPushButton { background-color: #332e22; color: #c9a84c; border: 1px outset #5a5040; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #232018; border: 1px inset #100e08; color: #f0d060; }
QTabBar::tab { background: #332e22; border: 1px outset #5a5040; padding: 3px 8px; color: #8a8070; }
QTabBar::tab:selected { background: #232018; border: 1px inset #100e08; font-weight: bold; color: #f0d060; }
QTabBar::scroller { width: 36px; }
QMenu { background-color: #232018; border: 1px outset #5a5040; }
QMenu::item:selected { background-color: #c9a84c; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #1a1810; color: #d4c89a; border: 1px inset #100e08; padding: 2px; }
QCheckBox { color: #d4c89a; }
QCheckBox::indicator { width: 12px; height: 12px; background: #1a1810; border: 1px inset #100e08; }
QCheckBox::indicator:checked { background: #c9a84c; }
QToolTip { color: #ffffff; background-color: #332e22; border: 1px solid #c9a84c; padding: 2px; }
QSplitter::handle { background-color: #332e22; }
#SearchFrame { background-color: #232018; border: 1px solid #5a5040; border-radius: 2px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 2px; border: 1px outset #5a5040; background-color: #332e22; margin: 0px; }
""",
        "preset_colors": ["#282310","#2a2818","#282520","#2a2318","#231828", "#28281a","#1a2828","#28182a","#28281a","#232018"],
        "active_temp_color": "#3d3820",
        "inactive_temp_color": "#232018",
        "tray_color": "#a05010",
        "btn_new": "background-color: #5a4520; color: #ffe599; font-weight: bold; padding: 4px; border: 1px outset #6a5530;",
        "btn_save": "background-color: #1e3040; color: #90d8f0; font-weight: bold; padding: 4px; border: 1px outset #2e4860;",
        "lbl_help": "font-size: 12px; color: #90d8f0;",
        "lbl_title": "font-weight: bold; color: #c9a84c;",
        "mini_settings": "QFrame { background-color: #332e22; border: 1px solid #5a5040; padding: 2px; }",
        "raw_colors": {
            "bg_main": "#232018", "bg_text": "#1a1810", "text_main": "#d4c89a",
            "border_light": "#5a5040", "border_dark": "#100e08",
            "btn_bg": "#332e22", "btn_pressed": "#232018", "btn_text": "#c9a84c",
            "accent": "#f0d060"
        }
    },
    "Vintage Dark": {
        "stylesheet": """
QWidget { background-color: #1b1b1b; color: #c0c0c0; font-size: 11px; }
QMainWindow { background-color: #1b1b1b; border: 2px solid #4d4d4d; }
QTextEdit { background-color: #181818; color: #c0c0c0; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; padding: 2px; }
QPushButton { background-color: #2b2b2b; color: #c0c0c0; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #141414; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; color: #5a7a96; padding: 4px 2px 0px 6px; }
QTabBar::tab { background: #2b2b2b; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a; padding: 3px 8px; color: #969696; }
QTabBar::tab:selected { background: #1b1b1b; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; font-weight: bold; color: #5a7a96; padding: 4px 7px 2px 9px; }
QTabBar::scroller { width: 36px; }
QMenu { background-color: #2b2b2b; border: 2px solid #4d4d4d; }
QMenu::item:selected { background-color: #5a7a96; color: #000000; }
QSpinBox, QComboBox, QLineEdit { background-color: #181818; color: #c0c0c0; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; padding: 1px; }
QCheckBox { color: #c0c0c0; spacing: 4px; padding: 0px; margin: 0px; }
QCheckBox::indicator { width: 10px; height: 10px; background: #181818; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; }
QCheckBox::indicator:checked { background: #5a7a96; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; }
QToolTip { color: #c0c0c0; background-color: #2b2b2b; border: 1px solid #4d4d4d; padding: 2px; }
QSplitter::handle { background-color: #1b1b1b; }
#SearchFrame { background-color: #141414; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a; border-radius: 0px; padding: 0px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 1px; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a; background-color: #2b2b2b; margin: 0px; }
""",
        "preset_colors": ["#1b1b1b"] * 10,
        "active_temp_color": "#203a4f",
        "inactive_temp_color": "#1b1b1b",
        "tray_color": "#8b4513",
        "btn_new": "background-color: #2b2b2b; color: #5a7a96; font-weight: bold; font-size: 11px; padding: 4px; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a;",
        "btn_save": "background-color: #1e1e1e; color: #c0c0c0; font-weight: bold; font-size: 11px; padding: 4px; border: 2px solid; border-top-color: #4d4d4d; border-left-color: #4d4d4d; border-right-color: #0a0a0a; border-bottom-color: #0a0a0a;",
        "lbl_help": "font-size: 12px; color: #5a7a96;",
        "lbl_title": "font-weight: bold; color: #c0c0c0;",
        "mini_settings": "QFrame { background-color: #141414; border: 2px solid; border-top-color: #0a0a0a; border-left-color: #0a0a0a; border-right-color: #4d4d4d; border-bottom-color: #4d4d4d; padding: 0px; }",
        "raw_colors": {
            "bg_main": "#1b1b1b", "bg_text": "#181818", "text_main": "#c0c0c0",
            "border_light": "#4d4d4d", "border_dark": "#0a0a0a",
            "btn_bg": "#2b2b2b", "btn_pressed": "#141414", "btn_text": "#c0c0c0",
            "accent": "#5a7a96"
        }
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
QTabBar::scroller { width: 36px; }
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
        "mini_settings": "QFrame { background-color: #c0c0c0; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; } QLabel { color: #000000; } QCheckBox { color: #000000; } QComboBox, QSpinBox { background-color: #ffffff; color: #000000; border: 2px solid #808080; border-bottom-color: #ffffff; border-right-color: #ffffff; } QPushButton { background-color: #c0c0c0; color: #000000; border: 2px solid #ffffff; border-bottom-color: #808080; border-right-color: #808080; }",
        "raw_colors": {
            "bg_main": "#c0c0c0", "bg_text": "#ffffff", "text_main": "#000000",
            "border_light": "#ffffff", "border_dark": "#808080",
            "btn_bg": "#c0c0c0", "btn_pressed": "#e6e6e6", "btn_text": "#000000",
            "accent": "#5e7a7a"
        }
    },
    "Dark 2 (OLED)": {
        "stylesheet": """
QWidget { background-color: #000000; color: #a0a0a0; font-size: 11px; }
QMainWindow { background-color: #000000; border: 1px solid #1a1a1a; }
QTextEdit { background-color: #000000; color: #b0b0b0; border: 1px solid #1a1a1a; padding: 2px; }
QPushButton { background-color: #0a0a0a; color: #a0a0a0; border: 1px solid #1a1a1a; padding: 2px 4px; }
QPushButton:pressed, QPushButton:checked { background-color: #141414; border: 1px inset #050505; color: #ffffff; padding: 4px 2px 0px 6px; }
QTabBar::tab { background: #0a0a0a; border: 1px solid #1a1a1a; padding: 3px 8px; color: #666666; }
QTabBar::tab:selected { background: #000000; border: 1px solid #333333; font-weight: bold; color: #ffffff; padding: 4px 7px 2px 9px; }
QTabBar::scroller { width: 36px; }
QMenu { background-color: #050505; border: 1px solid #1a1a1a; }
QMenu::item:selected { background-color: #1a1a1a; color: #ffffff; }
QSpinBox, QComboBox, QLineEdit { background-color: #050505; color: #a0a0a0; border: 1px solid #1a1a1a; padding: 1px; }
QCheckBox { color: #a0a0a0; spacing: 4px; padding: 0px; margin: 0px; }
QCheckBox::indicator { width: 10px; height: 10px; background: #000000; border: 1px solid #1a1a1a; }
QCheckBox::indicator:checked { background: #1a1a1a; border: 1px solid #333333; }
QToolTip { color: #a0a0a0; background-color: #000000; border: 1px solid #1a1a1a; padding: 2px; }
QSplitter::handle { background-color: #050505; }
#SearchFrame { background-color: #050505; border: 1px solid #1a1a1a; border-radius: 0px; padding: 0px; }
QDockWidget { margin: 0px; padding: 0px; border: 0px; }
QDockWidget::title { padding: 1px; border: 1px solid #1a1a1a; background-color: #050505; margin: 0px; }
""",
        "preset_colors": ["#000000"] * 10,
        "active_temp_color": "#1a1a1a",
        "inactive_temp_color": "#000000",
        "tray_color": "#333333",
        "btn_new": "background-color: #050505; color: #ffffff; font-weight: bold; font-size: 11px; padding: 4px; border: 1px solid #333333;",
        "btn_save": "background-color: #050505; color: #ffffff; font-weight: bold; font-size: 11px; padding: 4px; border: 1px solid #333333;",
        "lbl_help": "font-size: 12px; color: #666666;",
        "lbl_title": "font-weight: bold; color: #666666;",
        "mini_settings": "QFrame { background-color: #000000; border: 1px solid #1a1a1a; padding: 0px; }",
        "raw_colors": {
            "bg_main": "#000000", "bg_text": "#000000", "text_main": "#a0a0a0",
            "border_light": "#333333", "border_dark": "#1a1a1a",
            "btn_bg": "#0a0a0a", "btn_pressed": "#141414", "btn_text": "#a0a0a0",
            "accent": "#ffffff"
        }
    },
    # Popular community palettes. Built through generate_custom_theme() so
    # they carry the same 9-key raw_colors schema every theme-aware widget
    # reads — no extra wiring needed for any of them.
    "Dracula": generate_custom_theme({
        "bg_main": "#282a36", "bg_text": "#21222c", "text_main": "#f8f8f2",
        "border_light": "#6272a4", "border_dark": "#191a21",
        "btn_bg": "#44475a", "btn_pressed": "#565a72", "btn_text": "#f8f8f2",
        "accent": "#bd93f9",
    }),
    "Nord": generate_custom_theme({
        "bg_main": "#2e3440", "bg_text": "#272c36", "text_main": "#d8dee9",
        "border_light": "#4c566a", "border_dark": "#232831",
        "btn_bg": "#3b4252", "btn_pressed": "#4c566a", "btn_text": "#eceff4",
        "accent": "#88c0d0",
    }),
    "Solarized Dark": generate_custom_theme({
        "bg_main": "#002b36", "bg_text": "#073642", "text_main": "#93a1a1",
        "border_light": "#586e75", "border_dark": "#001f27",
        "btn_bg": "#073642", "btn_pressed": "#0a4655", "btn_text": "#eee8d5",
        "accent": "#268bd2",
    }),
}
