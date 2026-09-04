"""Lazy settings tabs builder for FastPrompter.

Constructs Window, Editor, Clock, and Data settings pages on first reveal,
avoiding startup overhead and stylesheet re-polishing on unshown widgets.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from fastprompter.core.translations import tr
from fastprompter.main import _SettingsGroupBox, _SettingsPage
from fastprompter.ui.flow_layout import flow_widget


def build_settings_tabs(self):
    def create_footer_cb(text, tooltip, checked, callback):
        cb = QCheckBox(text)
        cb.setToolTip(tooltip)
        cb.setChecked(checked)
        if callback:
            cb.toggled.connect(self.play_tick_sound)
            cb.toggled.connect(callback)
        cb._en_text = text
        cb._en_tooltip = tooltip
        return cb

    self.cb_top = create_footer_cb(
        "📌 Always on Top",
        "Keep the window above all others",
        self.data.get("always_on_top", "True") == "True",
        self.toggle_aot,
    )
    self.cb_lock_window = create_footer_cb(
        "🔒 Lock Window",
        "Freeze the window's position and size",
        self.data.get("window_locked", "False") == "True",
        self.set_lock_state,
    )
    self.cb_normal_window = create_footer_cb(
        "🪟 Normal Window",
        "Use a standard OS window frame and taskbar entry",
        self.data.get("normal_window", "False") == "True",
        self.apply_window_flags,
    )
    self.cb_tray = create_footer_cb(
        "📉 Tray Icon",
        "Keep an icon in the system tray",
        self.data.get("tray_visible", "True") == "True",
        self.on_tray_toggled,
    )
    self.cb_sidebar = create_footer_cb(
        "▶ Sidebar Right",
        "Move the snippet/silo sidebar to the right side",
        self.data.get("sidebar_right", "False") == "True",
        self.toggle_sidebar_position,
    )
    self.cb_custom_cursors = create_footer_cb(
        "\u2196 My Cursors",
        "Use the cursor set the program has copied.\n"
        "First time on, it copies your current Windows set.\n"
        "Animated cursors keep their default shape - Qt cannot read them.",
        self.data.get("custom_cursors", "False") == "True",
        self.toggle_custom_cursors,
    )
    self.cb_static_cursor = create_footer_cb(
        "\u2b1a Static Cursor",
        "Keep one pointer image everywhere.\n"
        "No I-beam over text, no hand over links or buttons -\n"
        "the arrow never changes shape while the app is focused.",
        self.data.get("static_cursor", "False") == "True",
        self.toggle_static_cursor,
    )
    self.cb_focus = create_footer_cb(
        "👁 Hide on Click-Out",
        "Hide the window when you click outside of it\nGlobal toggle: Alt+A",
        self.data.get("close_on_focus_loss", "True") == "True",
        self.mark_dirty,
    )
    self.cb_tray_activate = create_footer_cb(
        "🔼 Tray Click Activates",
        "When on, clicking the tray icon always brings the window to focus.\nWhen off, clicking hides it (like Alt+X).",
        self.data.get("tray_click_activates", "True") == "True",
        self.mark_dirty,
    )
    self.cb_snippet_arrows = create_footer_cb(
        "↕ Snippet Arrows",
        "Show the ▲ ▶ ▼ paste buttons on snippet rows\n"
        "(insert at top / at cursor / at bottom)",
        self.data.get("snippet_arrows", "False") == "True",
        lambda checked: (
            self.data.update({"snippet_arrows": "True" if checked else "False"})
            or self.mark_dirty()
            or self.refresh_snippets_panel()
        ),
    )
    self.cb_silo_ticks = create_footer_cb(
        "✅ Silo Ticks",
        "Show the ✅ done-mark button when hovering a silo.\n"
        "Off by default — Ctrl+Shift+click a silo toggles its tick either way.",
        self.data.get("silo_ticks_enabled", "False") == "True",
        lambda checked: (
            self.data.update({"silo_ticks_enabled": "True" if checked else "False"})
            or self.mark_dirty()
            or self.refresh_temp_presets()
        ),
    )
    self.cb_ctrl_c = create_footer_cb(
        "📋 Ctrl+C Hides",
        "Copying with Ctrl+C also hides the window\n(copy & get back to work in one stroke)",
        self.data.get("ctrl_c_closes", "True") == "True",
        self.mark_dirty,
    )
    self.cb_lock_cursor = create_footer_cb(
        "🖱 Open at Cursor",
        "The hotkey opens the window at your mouse cursor",
        self.data.get("lock_to_cursor", "False") == "True",
        self.on_lock_cursor_toggled,
    )
    self.cb_customize_toolbar = create_footer_cb(
        "🧩 Customize Toolbar",
        "Drag the top-bar buttons to reorder them. Dashed boxes are\n"
        "flexible gaps — drop a button on either side to move it between\n"
        "the left / centre / right zones. Use the ↺ button (or right-click\n"
        "this text) to reset to the default order.",
        self.data.get("customize_toolbar", "False") == "True",
        self.on_customize_toolbar_toggled,
    )
    self.cb_numbox_tabs = create_footer_cb(
        "# Number Tabs",
        "Show numbered boxes instead of the project dropdown",
        self.data.get("numbox_tabs", "False") == "True",
        self._toggle_numbox_mode,
    )
    # Number-box geometry. With the project cap at 100 these are what keep
    # the row from running off the header, so they live beside the toggle.
    self.spin_numbox_per_row = QSpinBox()
    self.spin_numbox_per_row.setRange(1, 100)
    self.spin_numbox_per_row.setToolTip(tr(
        "How many number boxes per row before they wrap", self._current_lang))
    self.spin_numbox_per_row.setValue(self.numbox_per_row())
    self.spin_numbox_per_row.valueChanged.connect(
        lambda v: self._on_numbox_geometry_changed("numbox_per_row", v))
    self.spin_numbox_size = QSpinBox()
    self.spin_numbox_size.setRange(14, 40)
    self.spin_numbox_size.setSuffix(" px")
    self.spin_numbox_size.setToolTip(tr(
        "Size of one number box", self._current_lang))
    self.spin_numbox_size.setValue(self.numbox_button_size())
    self.spin_numbox_size.valueChanged.connect(
        lambda v: self._on_numbox_geometry_changed("numbox_btn_size", v))
    numbox_row = QHBoxLayout()
    numbox_row.setContentsMargins(0, 0, 0, 0)
    numbox_row.setSpacing(4)
    numbox_row.addWidget(QLabel(tr("Per row:", self._current_lang)))
    numbox_row.addWidget(self.spin_numbox_per_row)
    numbox_row.addWidget(QLabel(tr("Size:", self._current_lang)))
    numbox_row.addWidget(self.spin_numbox_size)
    numbox_row.addStretch(1)

    self.cb_window_presets = create_footer_cb(
        "🗔 Ctrl+Q Presets",
        "Add a 'Presets' page to the Ctrl+Q picker holding your own\n"
        "saved window positions (S saves, Del removes, 1-0 applies)",
        self.data.get("window_presets_enabled", "True") == "True",
        lambda checked: (
            self.data.update(
                {"window_presets_enabled": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_files_dock = create_footer_cb(
        "🗂 Files Sidebar",
        "Keep the silo file panel docked as a collapsible sidebar on the\n"
        "side opposite the silo list, instead of a separate window.\n"
        "The 📁 button then opens and closes it.",
        self.data.get("file_panel_docked", "False") == "True",
        self._on_files_dock_toggled,
    )
    self.cb_toolbar_bottom = create_footer_cb(
        "⬇ Toolbar at Bottom",
        "Put the toolbar under the editor instead of above it.\n"
        "Same buttons, same order — only the side changes.",
        self.data.get("toolbar_position", "top") == "bottom",
        self.apply_toolbar_position,
    )
    self.cb_fast_zones = create_footer_cb(
        "⚡ Fast Ctrl+Q",
        "Skip the zone picker: every Ctrl+Q jumps straight to the next\n"
        "zone of the page chosen below and cycles through them",
        self.data.get("fancyzones_fast", "False") == "True",
        lambda checked: (
            self.data.update(
                {"fancyzones_fast": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_fast_zone_page = QComboBox()
    self.cb_fast_zone_page.setToolTip(tr(
        "Which page Fast mode cycles through", self._current_lang))
    self._reload_fast_zone_pages()
    self.cb_fast_zone_page.currentIndexChanged.connect(
        self._on_fast_zone_page_changed)
    fast_row = QHBoxLayout()
    fast_row.setContentsMargins(0, 0, 0, 0)
    fast_row.setSpacing(4)
    fast_row.addWidget(QLabel(tr("Fast page:", self._current_lang)))
    fast_row.addWidget(self.cb_fast_zone_page)
    fast_row.addStretch(1)

    self.btn_manage_presets = QPushButton(tr("Manage presets", self._current_lang))
    self.btn_manage_presets.setToolTip(tr(
        "Reorder, rename, re-capture or delete your Ctrl+Q window presets",
        self._current_lang))
    self.btn_manage_presets.clicked.connect(self.open_window_presets)
    self.cb_customize_toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.cb_customize_toolbar.customContextMenuRequested.connect(
        lambda _p: self.reset_toolbar_order())
    self.cb_silo_home = create_footer_cb(
        "🏠 Silos at Start",
        "Place the cursor at the top of a silo when opening it",
        self.data.get("silo_home", "False") == "True",
        self.on_silo_home_toggled,
    )
    self.cb_portable_backup = create_footer_cb(
        "💾 Auto Backup (.md)",
        "Mirror silos & snippets as Markdown files to Documents\\.fastprompter\\",
        self.data.get("portable_backup_enabled", "True") == "True",
        lambda checked: (
            self.data.update({"portable_backup_enabled": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_wrap = create_footer_cb(
        "↩ Word Wrap",
        "Wrap long lines instead of scrolling horizontally",
        self.data.get("word_wrap", "True") == "True",
        self.on_wrap_toggled,
    )
    self.cb_line_heat = create_footer_cb(
        "🌡 Line Heat",
        "Tint lines you edited recently, cooling as they age.\n"
        "Shows at a glance where you have just been working.",
        self.data.get("line_heat", "False") == "True",
        lambda checked: (
            self.data.update({"line_heat": "True" if checked else "False"})
            or self.mark_dirty()
            or self.text_area.viewport().update()
        ),
    )
    self.cb_hover_line = create_footer_cb(
        "🖱 Hover Line",
        "Faintly brighten the line under the mouse cursor",
        self.data.get("hover_line", "True") == "True",
        lambda checked: (
            self.data.update({"hover_line": "True" if checked else "False"})
            or self.mark_dirty()
            or self.text_area.viewport().update()
        ),
    )
    self.cb_code_monospace = create_footer_cb(
        "⌨ Monospace Code",
        "Render `code` and ``` blocks in Consolas.\n"
        "Off: use the editor's own font instead.",
        self.data.get("code_monospace", "True") == "True",
        lambda checked: (
            self.data.update({"code_monospace": "True" if checked else "False"})
            or self.mark_dirty()
            or self._apply_code_font()
        ),
    )
    self.cb_line_numbers = create_footer_cb(
        "🔢 Line Numbers",
        "Show a line-number gutter\n(click it to place colored margin marks)",
        self.data.get("show_line_numbers", "False") == "True",
        self.set_line_numbers,  # routes through the single source of truth
    )
    self.cb_code_gutter = create_footer_cb(
        "🔢 Auto # on Code",
        "Auto-show line numbers inside ``` code blocks even when the gutter\n"
        "is off. Off by default so the Line Numbers toggle stays a clean on/off.",
        self.data.get("code_auto_gutter", "False") == "True",
        lambda checked: (
            self.data.update({"code_auto_gutter": "True" if checked else "False"})
            or self.mark_dirty()
            or self.text_area.update_line_number_area_width()
            or self.text_area.line_number_area.update()
        ),
    )
    # keep the header pin button in sync with the always-on-top checkbox
    self.cb_top.toggled.connect(
        lambda c: hasattr(self, "btn_pin_top") and self.btn_pin_top.setChecked(c))

    self.cb_line_marks = create_footer_cb(
        "🔴 Line Marks",
        "Enable click-to-mark in line numbers (Red dot, Yellow Rhombus, Blue square)",
        self.data.get("line_marks", "False") == "True",
        lambda checked: self.data.update({"line_marks": "True" if checked else "False"})
                        or self.mark_dirty()
                        or (self.text_area.line_number_area.update() if hasattr(self, "text_area") and hasattr(self.text_area, "line_number_area") else None)
    )

    self.cb_token_count = create_footer_cb(
        "\ud83d\udd22 Token Counter",
        "Show an estimated input-token count beside the line count",
        self.data.get("show_token_count", "False") == "True",
        lambda checked: (
            self.data.update(
                {"show_token_count": "True" if checked else "False"})
            or self._update_token_count_label()
            or self.mark_dirty()
        ),
    )
    self.cb_token_mode = QComboBox()
    self.cb_token_mode.addItem(tr("chars", self._current_lang), "chars")
    self.cb_token_mode.addItem(tr("words", self._current_lang), "words")
    mode = self.data.get("token_mode", "chars")
    self.cb_token_mode.setCurrentIndex(1 if mode == "words" else 0)
    self.cb_token_mode.setToolTip(tr(
        "How the estimate is weighted: characters per token,\n"
        "or tokens per word", self._current_lang))
    self.cb_token_mode.currentIndexChanged.connect(self._on_token_mode_changed)
    self.spin_token_weight = QDoubleSpinBox()
    self.spin_token_weight.setRange(0.1, 20.0)
    self.spin_token_weight.setSingleStep(0.1)
    self.spin_token_weight.setDecimals(2)
    self.spin_token_weight.setToolTip(tr(
        "Chars per token (chars mode) or tokens per word (words mode).\n"
        "Defaults: 4.0 and 1.33", self._current_lang))
    try:
        self.spin_token_weight.setValue(float(self.data.get("token_weight", 4.0)))
    except (TypeError, ValueError):
        self.spin_token_weight.setValue(4.0)
    self.spin_token_weight.valueChanged.connect(self._on_token_weight_changed)
    token_row = QHBoxLayout()
    token_row.setContentsMargins(0, 0, 0, 0)
    token_row.setSpacing(4)
    token_row.addWidget(QLabel(tr("Tokens by:", self._current_lang)))
    token_row.addWidget(self.cb_token_mode)
    token_row.addWidget(self.spin_token_weight)
    token_row.addStretch(1)

    # "\u2192 Ctrl+E Center" used to live here. It was the two-state face of
    # an alignment that is now chosen per line - title, rule and bullet
    # each on their own - in the Ctrl+E\u2026 dialog, and a checkbox has
    # nowhere to put right or justified. Two controls for one setting,
    # one of which could only ever tell half the truth. The ctrl_e_center
    # KEY is still read (see core/header.read_settings) so a profile
    # saved with it keeps its centring.
    self.cb_zebra = create_footer_cb(
        "🦓 Zebra Stripes",
        "Lightly shade every other line for readability",
        self.data.get("zebra_lines", "False") == "True",
        lambda checked: (
            self.data.update({"zebra_lines": "True" if checked else "False"})
            or self.text_area.viewport().update()
            or self.mark_dirty()
        ),
    )
    self.cb_hide_shortkeys = create_footer_cb(
        "⌨ Hide Key Hints",
        "Hide the F1-F10 shortcut labels on snippet buttons",
        self.data.get("hide_shortkeys", "False") == "True",
        self.on_hide_shortkeys_toggled,
    )
    # Text alignment combo
    self.lbl_align = QLabel(tr("Align:", self._current_lang))
    self.cb_align_combo = QComboBox()
    self.cb_align_combo.addItem(tr("Left", self._current_lang), "left")
    self.cb_align_combo.addItem(tr("Center", self._current_lang), "center")
    self.cb_align_combo.addItem(tr("Right", self._current_lang), "right")
    saved_align = self.data.get("text_align", "left")
    idx = self.cb_align_combo.findData(saved_align)
    if idx >= 0:
        self.cb_align_combo.setCurrentIndex(idx)
    self.cb_align_combo.currentIndexChanged.connect(self._on_align_changed)

    # How a pasted image lands. "Pill" is the collapsed golden chip you
    # can click to open; the other two are for people who want the raw
    # markdown or just the path.
    self.lbl_img_paste = QLabel(tr("Pasted image:", self._current_lang))
    self.cb_img_paste = QComboBox()
    self.cb_img_paste.addItem(tr("Pill (clickable)", self._current_lang), "pill")
    self.cb_img_paste.addItem(tr("Markdown link", self._current_lang), "link")
    self.cb_img_paste.addItem(tr("Plain path", self._current_lang), "path")
    self.cb_img_paste.setToolTip(tr(
        "Pill: ![](...) — collapses to a clickable chip\n"
        "Markdown link: [name](...) — plain link text\n"
        "Plain path: the file path on its own", self._current_lang))
    _idx = self.cb_img_paste.findData(self.data.get("image_paste_style", "pill"))
    if _idx >= 0:
        self.cb_img_paste.setCurrentIndex(_idx)
    self.cb_img_paste.currentIndexChanged.connect(
        lambda i: (self.data.update(
            {"image_paste_style": self.cb_img_paste.itemData(i) or "pill"})
            or self.mark_dirty()))

    # Silos down the side, or across the top as tabs.
    self.lbl_silo_mode = QLabel(tr("Silos:", self._current_lang))
    self.cb_silo_mode = QComboBox()
    self.cb_silo_mode.addItem(tr("Sidebar", self._current_lang), "sidebar")
    self.cb_silo_mode.addItem(tr("Horizontal tabs", self._current_lang), "tabs")
    self.cb_silo_mode.setToolTip(tr(
        "Sidebar: the usual column down the left\n"
        "Horizontal tabs: a strip above the editor — child silos have no\n"
        "room on a bar, so they move into the parent's right-click menu",
        self._current_lang))
    _idx = self.cb_silo_mode.findData(self.data.get("silo_tabs_mode", "sidebar"))
    if _idx >= 0:
        self.cb_silo_mode.setCurrentIndex(_idx)
    self.cb_silo_mode.currentIndexChanged.connect(
        lambda i: self.apply_silo_tabs_mode(
            (self.cb_silo_mode.itemData(i) or "sidebar") == "tabs"))

    self.cb_double_line = create_footer_cb(
        "⇕ Double-Space Lists",
        "With Auto-Bullet on, Enter after a list item adds a blank\n"
        "line before the next bullet — spaced, easy-to-read lists",
        self.data.get("bullet_double_line", "False") == "True",
        lambda checked: (
            self.data.update({"bullet_double_line": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_bold_titles = create_footer_cb(
        "𝗕 Bold # Titles",
        "Bold the sidebar title of silos and snippets whose\n"
        "content starts with a '#' markdown header",
        self.data.get("bold_hash_titles", "True") == "True",
        lambda checked: (
            self.data.update({"bold_hash_titles": "True" if checked else "False"})
            or self.mark_dirty()
            or self.refresh_temp_presets()
            or self.refresh_snippets_panel()
            or self.refresh_archive_panel()
        ),
    )
    self.cb_silo_pinned_gap = create_footer_cb(
        "➖ Pinned Gap",
        "Show a visual separator between pinned and unpinned silos",
        self.data.get("silo_pinned_gap", "True") == "True",
        lambda checked: (
            self.data.update({"silo_pinned_gap": "True" if checked else "False"})
            or self.mark_dirty()
            or self.refresh_temp_presets()
            or self.refresh_snippets_panel()
        ),
    )
    self.cb_conceal = create_footer_cb(
        "👁 Hide Markup (Live)",
        "Obsidian-style Live Preview: hide **, *, __, ~~ and ` markers so\n"
        "the text reads as rendered. The line the caret is on still shows\n"
        "its markers, so it stays editable.",
        self.data.get("live_preview_conceal", "False") == "True",
        lambda checked: (
            self.data.update({"live_preview_conceal": "True" if checked else "False"})
            or self.mark_dirty()
            or self._apply_conceal_mode()
        ),
    )
    self.cb_hr_visual = create_footer_cb(
        "➖ Render HR Lines",
        "Render ---/***/___ dividers as crisp visual lines instead of raw text",
        self.data.get("hr_visual_line", "True") == "True",
        lambda checked: (
            self.data.update({"hr_visual_line": "True" if checked else "False"})
            or self.mark_dirty()
            or (getattr(self, "highlighter", None) and self.highlighter.update_hr_as_line(checked))
            or (hasattr(self, "text_area") and hasattr(self.text_area, "viewport") and self.text_area.viewport().update())
        ),
    )
    self.cb_date_rect = create_footer_cb(
        "📅 Show Date Widget",
        "Show a floating date and time rectangle in the top-right\n"
        "corner of the text editor",
        self.data.get("show_date_rect", "True") == "True",
        lambda checked: (
            self.data.update({"show_date_rect": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_timer_minutes = create_footer_cb(
        "⏳ Timer Minutes",
        "Always show minutes in the top-right timer countdown\n"
        "(otherwise a long timer reads just '4d' or '2h')",
        self.data.get("timer_show_minutes", "False") == "True",
        lambda checked: (
            self.data.update(
                {"timer_show_minutes": "True" if checked else "False"})
            or self._update_timer_label()
            or self.mark_dirty()
        ),
    )
    self.cb_date_seconds = create_footer_cb(
        "⏱ Date Seconds",
        "Show seconds in the date widget (hh:mm:ss instead of hh:mm)",
        self.data.get("date_seconds", "True") == "True",
        lambda checked: (
            self.data.update({"date_seconds": "True" if checked else "False"})
            or self.mark_dirty()
        ),
    )
    self.cb_analog_clock = create_footer_cb(
        "🕒 Analog Clock",
        "Show a mini analog clock (hour + minute hands)\nnext to the date widget",
        self.data.get("analog_clock", "False") == "True",
        lambda checked: (
            self.data.update({"analog_clock": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.cb_date_daypart = create_footer_cb(
        "🌞 Day Word",
        "Show the time-of-day word (Morning / Day / Evening / Night)\n"
        "after the clock in the date widget",
        self.data.get("date_daypart", "True") == "True",
        lambda checked: (
            self.data.update({"date_daypart": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.cb_date_emoji = create_footer_cb(
        "🎭 Emoji Day State",
        "Show an emoji (🌅/☀️/🌇/🌙) instead of the time-of-day word",
        self.data.get("date_emoji", "False") == "True",
        lambda checked: (
            self.data.update({"date_emoji": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.cb_date_text_month = create_footer_cb(
        "🔤 Text Month",
        "Show month as text instead of numbers (17 Jul instead of 17.07)",
        self.data.get("date_text_month", "False") == "True",
        lambda checked: (
            self.data.update({"date_text_month": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.cb_date_ampm = create_footer_cb(
        "🕐 12-Hour Clock",
        "Show time as 09:05 PM instead of 21:05 — applies to the date\n"
        "widget, Ctrl+E headers and the end-of-line timestamp",
        self.data.get("date_ampm", "False") == "True",
        lambda checked: (
            self.data.update({"date_ampm": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.cb_limit_gauges = create_footer_cb(
        "📊 AI Limit Gauges",
        "Show AI usage-limit bars (remaining quota per window) next to\n"
        "the timer. Auto-detects every Codex account, Claude and\n"
        "Antigravity install. Click the bars to refresh; hover for details.",
        self.data.get("limit_gauges",
                      self.data.get("codex_gauges", "False")) == "True",
        lambda checked: (
            self.data.update({"limit_gauges": "True" if checked else "False"})
            or self.mark_dirty()
            or self._update_date_label()
        ),
    )
    self.btn_limit_settings = QPushButton(tr(
        "Limit settings…", self._current_lang))
    self.btn_limit_settings.setToolTip(tr(
        "Accounts, labels, providers and per-limit notifications",
        self._current_lang))
    self.btn_limit_settings.clicked.connect(
        self.open_limit_settings_dialog)
    self.cb_sound = create_footer_cb(
        "🔊 UI Sounds",
        "Play click sounds for buttons and actions.\n"
        "You can place your own .wav files in the 'sound' folder to override:\n"
        "• newbutton1.wav (New button)\n"
        "• savebutton1.wav (Save button)\n"
        "• button1.wav (Click/Silo)\n"
        "• button2.wav (Snippet)\n"
        "• tickbox1.wav (Checkbox)\n"
        "• delete1.wav (Delete)\n"
        "• clear1.wav (Clear)",
        self.data.get("sound_ui", "False") == "True",
        self.on_sound_toggled,
    )
    self.cb_typewriter = create_footer_cb(
        "⌨ Typewriter",
        "Play a typewriter tick for every typed character.\n"
        "Place 'type1.wav' in the 'sound' folder to use your own typing sound.",
        self.data.get("sound_typewriter", "False") == "True",
        self.on_typewriter_toggled,
    )
    self.cb_trash_vision = create_footer_cb(
        "🗑 Trash Vision",
        "Show the Trash category for deleted snippets",
        self.data.get("trash_vision", "False") == "True",
        self.toggle_trash_vision,
    )
    self.cb_silo_color_box = create_footer_cb(
        "🎨 Silo Color Box",
        "Show the little clickable color box on '#' silos\n"
        "(click to cycle colors, right-click for the full picker)",
        self.data.get("silo_color_box", "True") == "True",
        lambda checked: (
            self.data.update({"silo_color_box": "True" if checked else "False"})
            or self.mark_dirty()
            or self.refresh_temp_presets()
        ),
    )

    div_row = QHBoxLayout()
    div_row.setContentsMargins(0, 0, 0, 0)
    div_row.setSpacing(4)
    lbl_div = QLabel(tr("Line button gaps:", getattr(self, "_current_lang", "EN")))
    lbl_div._en_text = "Line button gaps:"
    lbl_div.setToolTip(tr(
        "Blank lines the Line button and the toolbar divider put around ---.\n"
        "Ctrl+W does NOT read these - it has its own per-scenario spacing in\n"
        "the Ctrl+W... dialog, which is why changing these here did nothing.",
        getattr(self, "_current_lang", "EN")))
    div_row.addWidget(lbl_div)
    self.spin_div_before = QSpinBox()
    self.spin_div_before.setRange(0, 6)
    self.spin_div_before.setToolTip(tr("Lines before ---", getattr(self, "_current_lang", "EN")))
    try:
        self.spin_div_before.setValue(int(self.data.get("divider_lines_before", 2)))
    except (TypeError, ValueError):
        self.spin_div_before.setValue(2)
    self.spin_div_before.valueChanged.connect(
        lambda v: (self.data.update({"divider_lines_before": str(v)}), self.mark_dirty())
    )
    div_row.addWidget(self.spin_div_before)
    self.spin_div_after = QSpinBox()
    self.spin_div_after.setRange(1, 6)
    self.spin_div_after.setToolTip(tr("Lines after --- (before the fresh bullet)", getattr(self, "_current_lang", "EN")))
    try:
        self.spin_div_after.setValue(int(self.data.get("divider_lines_after", 3)))
    except (TypeError, ValueError):
        self.spin_div_after.setValue(3)
    self.spin_div_after.valueChanged.connect(
        lambda v: (self.data.update({"divider_lines_after": str(v)}), self.mark_dirty())
    )
    div_row.addWidget(self.spin_div_after)
    div_row.addStretch(1)

    # ── Smart Ctrl+W — open full dialog ──
    ctrlw_btn_row = QHBoxLayout()
    ctrlw_btn_row.setContentsMargins(0, 0, 0, 0)
    ctrlw_btn_row.setSpacing(4)
    self.btn_ctrlw_settings = QPushButton(tr("Ctrl+W…", getattr(self, "_current_lang", "EN")))
    self.btn_ctrlw_settings.setToolTip(tr(
        "Configure Smart Ctrl+W behavior per context scenario:\n"
        "• Divider insertion and bullet\n"
        "• Blank-line spacing (global or per scenario)\n"
        "• Action when pressing on an existing divider",
        getattr(self, "_current_lang", "EN")))
    self.btn_ctrlw_settings.clicked.connect(self.open_ctrlw_settings)
    ctrlw_btn_row.addWidget(self.btn_ctrlw_settings)
    self.btn_altw_settings = QPushButton(tr("Alt+W…", getattr(self, "_current_lang", "EN")))
    self.btn_altw_settings.setToolTip(tr(
        "Alt+W is Ctrl+W turned around: the new point goes ABOVE the\n"
        "line you are on and the existing text moves down.\n"
        "Same settings, kept separately so the two directions can be\n"
        "tuned apart.",
        getattr(self, "_current_lang", "EN")))
    self.btn_altw_settings.clicked.connect(self.open_altw_settings)
    ctrlw_btn_row.addWidget(self.btn_altw_settings)
    ctrlw_btn_row.addStretch(1)

    files_row = QHBoxLayout()
    files_row.setContentsMargins(0, 0, 0, 0)
    files_row.setSpacing(4)
    self.btn_files_root = QPushButton(tr("Files Folder…", getattr(self, "_current_lang", "EN")))
    self.btn_files_root.setToolTip(tr(
        "Choose where silo file containers are stored.\n"
        "Default: data/files next to the app.",
        getattr(self, "_current_lang", "EN")))
    self.btn_files_root.clicked.connect(self.pick_files_root)
    files_row.addWidget(self.btn_files_root)
    btn_files_root_reset = QPushButton("↺")
    btn_files_root_reset.setToolTip(tr("Reset silo files location to the default data/files", getattr(self, "_current_lang", "EN")))
    btn_files_root_reset.setFixedWidth(24)
    btn_files_root_reset.clicked.connect(self.reset_files_root)
    files_row.addWidget(btn_files_root_reset)
    files_row.addStretch(1)

    dev_row = QHBoxLayout()
    dev_row.setContentsMargins(0, 0, 0, 0)
    dev_row.setSpacing(4)
    self.btn_set_defaults = QPushButton(tr("Set Defaults from Current", getattr(self, "_current_lang", "EN")))
    self.btn_set_defaults.setToolTip(tr(
        "Developer tool: stamp current UI settings, themes, sounds and presets\n"
        "as repo base DEFAULT_PROFILE (excludes personal notes, text and silos).",
        getattr(self, "_current_lang", "EN")))

    def _on_set_defaults_clicked():
        from tools.set_default_from_current import update_default_profile_from_state
        reply = QMessageBox.question(
            self,
            tr("Set Defaults from Current", getattr(self, "_current_lang", "EN")),
            tr("Update repository DEFAULT_PROFILE with current settings?\n\n"
               "All personal text, silos, and private paths will be excluded.",
               getattr(self, "_current_lang", "EN")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                res = update_default_profile_from_state(self.data)
                QMessageBox.information(
                    self,
                    tr("Defaults Updated", getattr(self, "_current_lang", "EN")),
                    f"Successfully stamped {res.get('keys_count', 0)} settings into DEFAULT_PROFILE!\n\n"
                    f"File: {res.get('target_file')}",
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    tr("Update Failed", getattr(self, "_current_lang", "EN")),
                    str(e),
                )

    self.btn_set_defaults.clicked.connect(_on_set_defaults_clicked)
    dev_row.addWidget(self.btn_set_defaults)

    self.btn_exit_app = QPushButton(tr("Exit FastPrompter", getattr(self, "_current_lang", "EN")))
    self.btn_exit_app._en_text = "Exit FastPrompter"
    self.btn_exit_app.setToolTip(tr(
        "Exit FastPrompter (Ctrl+Alt+Shift+Q)\nSave all data and quit application.",
        getattr(self, "_current_lang", "EN")))
    self.btn_exit_app.clicked.connect(self.quit_app)
    dev_row.addWidget(self.btn_exit_app)
    dev_row.addStretch(1)

    vol_row = QHBoxLayout()
    vol_row.setContentsMargins(0, 0, 0, 0)
    vol_row.setSpacing(4)
    _lbl_vol = QLabel(tr("Volume:", getattr(self, "_current_lang", "EN")))
    _lbl_vol._en_text = "Volume:"
    vol_row.addWidget(_lbl_vol)
    vol_row.addWidget(self.spin_volume)
    vol_row.addStretch(1)

    # Sound settings button
    self.btn_sound_settings = QPushButton(tr("Sound Settings...", getattr(self, "_current_lang", "EN")))
    self.btn_sound_settings.clicked.connect(self.open_sound_settings_dialog)
    self.btn_sound_settings._en_text = "Sound Settings..."
    _sound_btn_tip = ("Every sound the app makes: pick the file, the volume "
                      "and whether it plays at all, per event")
    self.btn_sound_settings.setToolTip(
        tr(_sound_btn_tip, getattr(self, "_current_lang", "EN")))
    self.btn_sound_settings._en_tooltip = _sound_btn_tip

    # CS 1.6 UI style checkbox
    self.cb_cs_style = create_footer_cb(
        "CS 1.6 UI Style",
        "Use Counter-Strike 1.6 style sounds for silo interactions:\n"
        "• Hover: buttonrollover.wav\n"
        "• Click: buttonclick.wav\n"
        "• Release: buttonclickrelease.wav",
        self.data.get("cs_style", "False") == "True",
        self.on_cs_style_toggled,
    )
    self.cb_cs_style._en_text = "CS 1.6 UI Style"
    self.cb_cs_style._en_tooltip = "Use Counter-Strike 1.6 style sounds for silo interactions:\n• Hover: buttonrollover.wav\n• Click: buttonclick.wav\n• Release: buttonclickrelease.wav"

    self.spin_cursor_blink = QSpinBox()
    self.spin_cursor_blink.setRange(0, 2000)
    self.spin_cursor_blink.setSingleStep(50)
    self.spin_cursor_blink.setSuffix(" ms")
    self.spin_cursor_blink.setSpecialValueText(tr("No blink", self._current_lang))
    self.spin_cursor_blink.setToolTip(tr(
        "Cursor blink cycle (ms). 0 = solid, no blink.\n"
        "Default: 530 on Windows.", self._current_lang))
    try:
        self.spin_cursor_blink.setValue(int(self.data.get("cursor_blink_ms",
                                       QApplication.cursorFlashTime())))
    except (TypeError, ValueError):
        self.spin_cursor_blink.setValue(530)
    self.spin_cursor_blink.valueChanged.connect(self._on_cursor_blink_changed)
    blink_row = QHBoxLayout()
    blink_row.setContentsMargins(0, 0, 0, 0)
    blink_row.setSpacing(4)
    blink_row.addWidget(QLabel(tr("Cursor blink:", self._current_lang)))
    blink_row.addWidget(self.spin_cursor_blink)
    blink_row.addStretch(1)

    hdr_row = QHBoxLayout()
    hdr_row.setContentsMargins(0, 0, 0, 0)
    hdr_row.setSpacing(4)
    lbl_hdr = QLabel(tr("Header Fmt:", getattr(self, "_current_lang", "EN")))
    lbl_hdr._en_text = "Header Fmt:"
    lbl_hdr.setToolTip(tr(
        "Template for the Ctrl+E header.\n"
        "{text} — the line's text\n{time} — timestamp\n"
        "{state} — Morning / Day / Evening / Night\n"
        "Markdown markers (** __ etc.) are yours to add or drop.",
        getattr(self, "_current_lang", "EN")))
    hdr_row.addWidget(lbl_hdr)
    self.le_hdr_fmt = QLineEdit()
    self.le_hdr_fmt.setPlaceholderText("{text} ({time})")
    self.le_hdr_fmt.setText(self.data.get("ctrl_e_format", "{text} ({time})"))
    self.le_hdr_fmt.textChanged.connect(
        lambda v: (self.data.update({"ctrl_e_format": v}), self.mark_dirty())
    )
    hdr_row.addWidget(self.le_hdr_fmt)
    btn_hdr_edit = QPushButton(tr("Edit…", getattr(self, "_current_lang", "EN")))
    btn_hdr_edit.setToolTip(tr("Open the header format editor (placeholders, presets, live preview)", getattr(self, "_current_lang", "EN")))
    btn_hdr_edit.setFixedWidth(44)
    btn_hdr_edit.clicked.connect(self.open_header_format_editor)
    hdr_row.addWidget(btn_hdr_edit)


    def _settings_group(title, items, min_width=0):
        """A compact titled box of related controls.

        Headers are fixed height (16px) with a subtle bottom rule so they never
        balloon into empty blocks. Content is top-aligned with a trailing stretch
        so controls stay tight and never get pushed below the bottom edge.
        """
        box = _SettingsGroupBox()
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setObjectName("SettingsGroup")
        box.setStyleSheet(
            "#SettingsGroup { background: rgba(255,255,255,0.025);"
            " border: 1px solid rgba(255,255,255,0.08);"
            " border-radius: 0px; }"
        )
        col = QVBoxLayout(box)
        col.setContentsMargins(4, 2, 4, 3)
        col.setSpacing(2)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QLabel(tr(title, self._current_lang))
        header._en_text = title
        header.setFixedHeight(16)
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        header.setStyleSheet(
            "font-weight: bold; font-size: 10px; color: #c9a84c; padding: 0 2px;"
            " border-bottom: 1px solid rgba(255,255,255,0.06);"
        )
        col.addWidget(header)

        inner = flow_widget(items, h_spacing=8, v_spacing=3)
        if min_width:
            inner.setMinimumWidth(min_width)
        col.addWidget(inner)
        col.addStretch(1)

        box._inner = inner
        box._chrome_h = 24
        box.setSizePolicy(QSizePolicy.Policy.Preferred,
                          QSizePolicy.Policy.MinimumExpanding)
        box._weight = len(items)
        return box

    # --- UI gaps: silo spacing + splitter handle width ---
    gap_row = QHBoxLayout()
    gap_row.setContentsMargins(0, 0, 0, 0)
    gap_row.setSpacing(4)
    lbl_gap = QLabel(tr("UI Gaps:", self._current_lang))
    lbl_gap.setStyleSheet("color: #808080;")
    gap_row.addWidget(lbl_gap)

    self.spin_silo_gap = QSpinBox()
    self.spin_silo_gap.setRange(0, 50)
    self.spin_silo_gap.setToolTip(tr("Silo Gap Height", self._current_lang))
    try:
        self.spin_silo_gap.setValue(int(self.data.get("silo_gap_height", 8)))
    except (TypeError, ValueError):
        self.spin_silo_gap.setValue(8)

    def _update_gap(v):
        self.data.update({"silo_gap_height": str(v)})
        if hasattr(self, "silo_gap_widget"):
            self.silo_gap_widget.setFixedHeight(v)
        if hasattr(self, "sections_gap_widget"):
            self.sections_gap_widget.setFixedHeight(v)
        self.mark_dirty()
        # user-defined gaps (T-590) share this height, so repaint them too
        if self.data.get("silo_gaps"):
            self.refresh_temp_presets()

    self.spin_silo_gap.valueChanged.connect(_update_gap)
    gap_row.addWidget(self.spin_silo_gap)

    self.spin_drag_width = QSpinBox()
    self.spin_drag_width.setRange(1, 50)
    self.spin_drag_width.setToolTip(tr("Splitter Handle Width", self._current_lang))
    try:
        self.spin_drag_width.setValue(int(self.data.get("splitter_width", 1)))
    except (TypeError, ValueError):
        self.spin_drag_width.setValue(1)

    def _update_drag(v):
        self.data.update({"splitter_width": str(v)})
        if hasattr(self, "splitter"):
            self.splitter.setHandleWidth(v)
        self.mark_dirty()

    self.spin_drag_width.valueChanged.connect(_update_drag)
    gap_row.addWidget(self.spin_drag_width)
    gap_row.addStretch(1)

    # --- T-591: mirror silo text onto disk ---
    sync_row = QHBoxLayout()
    sync_row.setSpacing(4)
    lbl_sync = QLabel(tr("Sync to disk:", self._current_lang))
    lbl_sync.setStyleSheet("color: #808080;")
    sync_row.addWidget(lbl_sync)

    self.combo_sync_mode = QComboBox()
    self.combo_sync_mode.addItems(["Off", "Silo", "Hierarchy"])
    self.combo_sync_mode.setToolTip(tr(
        "Off: no mirror.\n"
        "Silo: keep a copy of the current silo on disk.\n"
        "Hierarchy: mirror every silo, children in subfolders.\n"
        "One-way (app to disk) — files are never read back or deleted.",
        self._current_lang))
    mode_now = self.data.get("sync_mode", "Off")
    if mode_now not in ("Off", "Silo", "Hierarchy"):
        mode_now = "Off"
    self.combo_sync_mode.setCurrentText(mode_now)
    self.combo_sync_mode.currentTextChanged.connect(
        lambda m: (self.data.update({"sync_mode": m}), self.mark_dirty(),
                   self.sync_to_disk(force=True)))
    sync_row.addWidget(self.combo_sync_mode)

    self.btn_sync_path = QPushButton(tr("Folder…", self._current_lang))
    self.btn_sync_path.setToolTip(self.data.get("sync_path", "") or tr("No folder chosen", self._current_lang))

    def _pick_sync_path():
        self.ignore_focus_loss = True
        try:
            d = QFileDialog.getExistingDirectory(
                self, tr("Choose sync folder", self._current_lang),
                self.data.get("sync_path", "") or "")
        finally:
            self.ignore_focus_loss = False
        if d:
            self.data.update({"sync_path": d})
            self.btn_sync_path.setToolTip(d)
            self.mark_dirty()
            self.sync_to_disk(force=True)

    self.btn_projects_mgr = QPushButton(tr("Projects…", self._current_lang))
    self.btn_projects_mgr.setToolTip(tr(
        "Choose which projects appear in the tab list", self._current_lang))
    self.btn_projects_mgr.clicked.connect(self.open_projects_manager)
    sync_row.addWidget(self.btn_projects_mgr)
    self.btn_sync_path.clicked.connect(_pick_sync_path)
    sync_row.addWidget(self.btn_sync_path)
    sync_row.addStretch(1)

    # --- hover line + line heat tuning ---
    lbl_heat = QLabel(tr("Line tint:", self._current_lang))
    lbl_heat.setStyleSheet("color: #808080;")

    def _pct_spin(key, default, tip, suffix="%"):
        spin = QSpinBox()
        spin.setRange(1, 60)
        spin.setSuffix(suffix)
        spin.setToolTip(tr(tip, self._current_lang))
        try:
            spin.setValue(int(self.data.get(key, default)))
        except (TypeError, ValueError):
            spin.setValue(default)

        def _upd(v):
            self.data.update({key: str(v)})
            self.mark_dirty()
            self.text_area.viewport().update()

        spin.valueChanged.connect(_upd)
        return spin

    self.spin_hover_opacity = _pct_spin(
        "hover_line_opacity", 10, "Hover line opacity")
    self.spin_heat_strength = _pct_spin(
        "line_heat_strength", 18, "Line heat strength")

    self.spin_heat_minutes = QSpinBox()
    self.spin_heat_minutes.setRange(1, 43200)
    self.spin_heat_minutes.setSuffix(tr(" min", self._current_lang))
    self.spin_heat_minutes.setToolTip(tr(
        "How long a line stays tinted after you edit it", self._current_lang))
    try:
        self.spin_heat_minutes.setValue(int(self.data.get("line_heat_minutes", 1440)))
    except (TypeError, ValueError):
        self.spin_heat_minutes.setValue(1440)

    def _upd_minutes(v):
        self.data.update({"line_heat_minutes": str(v)})
        self.mark_dirty()
        self.text_area.viewport().update()

    self.spin_heat_minutes.valueChanged.connect(_upd_minutes)

    self.cb_heat_palette = QComboBox()
    self.cb_heat_palette.setToolTip(tr(
        "Colour spectrum for edited lines.\nAuto follows the theme accent.",
        self._current_lang))
    for label, val in (("Warm", "warm"), ("Cool", "cool"), ("Auto", "accent")):
        self.cb_heat_palette.addItem(tr(label, self._current_lang), val)
    cur_pal = self.data.get("line_heat_palette", "warm")
    pal_idx = self.cb_heat_palette.findData(cur_pal)
    if pal_idx >= 0:
        self.cb_heat_palette.setCurrentIndex(pal_idx)

    def _upd_pal(i):
        self.data.update({"line_heat_palette": self.cb_heat_palette.itemData(i)})
        self.mark_dirty()
        self.text_area.viewport().update()

    self.cb_heat_palette.currentIndexChanged.connect(_upd_pal)

    self.btn_hover_colour = QPushButton(tr("Hover colour", self._current_lang))
    self.btn_hover_colour.setToolTip(tr(
        "Pick the hover highlight colour.\n"
        "Right-click to go back to following the theme.",
        self._current_lang))
    self.btn_hover_colour.clicked.connect(self.pick_hover_colour)
    self.btn_hover_colour.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    self.btn_hover_colour.customContextMenuRequested.connect(
        lambda _p: self.reset_hover_colour())

    # --- typecheck (typo checker): dictionary underlines, default OFF ---
    self.cb_typo_check = create_footer_cb(
        "✏ Typo check (dictionary)",
        "Underline words the built-in dictionary does not know, with "
        "right-click suggestions and an 'add to dictionary' entry.\n"
        "Off by default. Smart skips: code fences, URLs, identifiers, "
        "acronyms; non-Latin scripts are only judged once the "
        "dictionary covers them.",
        self.data.get("typo_check_enabled", "False") == "True",
        lambda checked: (self.data.update(
            {"typo_check_enabled": "True" if checked else "False"})
            or self.mark_dirty()
            or self._typo_check_tick()),
    )
    self.btn_typo_colour = QPushButton(tr("Underline colour", self._current_lang))
    self.btn_typo_colour.setToolTip(tr(
        "Pick the colour of the typo underlines", self._current_lang))
    self.btn_typo_colour.clicked.connect(self.pick_typo_colour)
    self.btn_typo_colour._en_text = "Underline colour"
    self.btn_typo_colour._en_tooltip = "Pick the colour of the typo underlines"
    self.btn_typo_clear = QPushButton(tr("Clear my words", self._current_lang))
    self.btn_typo_clear.setToolTip(tr(
        "Forget every word you added to the dictionary", self._current_lang))
    self.btn_typo_clear.clicked.connect(self.clear_typo_words)
    self.btn_typo_clear._en_text = "Clear my words"
    self.btn_typo_clear._en_tooltip = "Forget every word you added to the dictionary"

    # --- passed events: the date counter turns red when a set event's
    # time has passed and was not acknowledged (colour is user-pickable)
    self.cb_passed_alert = create_footer_cb(
        "⚠ Passed-event alert",
        "Colour the date/time counter when a calendar event's time has "
        "passed and was not acknowledged — so a missed event is not "
        "forgotten. Right-click the date label to clear it.",
        self.data.get("passed_alert_enabled", "True") == "True",
        lambda checked: (self.data.update(
            {"passed_alert_enabled": "True" if checked else "False"})
            or self.mark_dirty()
            or self._apply_date_alert_style()),
    )
    self.btn_passed_colour = QPushButton(
        tr("Alert colour", self._current_lang))
    self.btn_passed_colour.setToolTip(tr(
        "Colour of the date counter when an event has passed\n"
        "(right-click to reset to the default red)", self._current_lang))
    self.btn_passed_colour.clicked.connect(self.pick_passed_colour)
    self.btn_passed_colour.setContextMenuPolicy(
        Qt.ContextMenuPolicy.CustomContextMenu)
    self.btn_passed_colour.customContextMenuRequested.connect(
        lambda _p: self.reset_passed_colour())
    self.btn_passed_colour._en_text = "Alert colour"
    self.btn_passed_colour._en_tooltip = (
        "Colour of the date counter when an event has passed\n"
        "(right-click to reset to the default red)")

    # --- Sync-Project settings: include/exclude + live behaviour -------
    self.cb_sync_recursive = create_footer_cb(
        "📁 Include subfolders",
        "Watch the whole folder tree (on) or only the top folder (off)",
        self.data.get("sync_recursive", "True") == "True",
        self._save_sync_recursive,
    )
    self.cb_sync_live = create_footer_cb(
        "👁 Watch live",
        "Apply external file changes in real time. Off: the folder is "
        "only read when you convert or re-scan the project.",
        self.data.get("sync_live_watch", "True") == "True",
        lambda checked: (self.data.update(
            {"sync_live_watch": "True" if checked else "False"})
            or self.mark_dirty()
            or self._start_project_watcher()),
    )
    self.spin_sync_max_kb = QSpinBox()
    self.spin_sync_max_kb.setRange(8, 10240)
    self.spin_sync_max_kb.setSuffix(" KB")
    self.spin_sync_max_kb.setToolTip(tr(
        "Files larger than this are not synced", self._current_lang))
    try:
        self.spin_sync_max_kb.setValue(int(self.data.get("sync_max_kb", "512")))
    except (TypeError, ValueError):
        self.spin_sync_max_kb.setValue(512)

    def _upd_sync_max(v):
        self.data.update({"sync_max_kb": str(v)})
        if self._sync_config():
            self._rescan_project_sync()
        self.mark_dirty()

    self.spin_sync_max_kb.valueChanged.connect(_upd_sync_max)
    lbl_sync_max = QLabel(tr("Max file size:", self._current_lang))
    lbl_sync_max._en_text = "Max file size:"

    self.ed_sync_include = QLineEdit(self.data.get("sync_include", ""))
    self.ed_sync_include.setPlaceholderText(".txt .md .py .js …")
    self.ed_sync_include.setToolTip(tr(
        "File extensions treated as text, separated by spaces or commas",
        self._current_lang))
    self.ed_sync_include.setMaximumWidth(360)
    self.ed_sync_include.editingFinished.connect(self._save_sync_include)
    self.ed_sync_include._en_tooltip = (
        "File extensions treated as text, separated by spaces or commas")
    lbl_sync_inc = QLabel(tr("Include extensions:", self._current_lang))
    lbl_sync_inc._en_text = "Include extensions:"

    self.ed_sync_exclude = QLineEdit(self.data.get("sync_exclude", ""))
    self.ed_sync_exclude.setPlaceholderText("node_modules, .git, *.min.js …")
    self.ed_sync_exclude.setToolTip(tr(
        "Names or patterns never synced: directories by name, files via "
        "wildcards (e.g. *.min.js)", self._current_lang))
    self.ed_sync_exclude.setMaximumWidth(360)
    self.ed_sync_exclude.editingFinished.connect(self._save_sync_exclude)
    self.ed_sync_exclude._en_tooltip = (
        "Names or patterns never synced: directories by name, files via "
        "wildcards (e.g. *.min.js)")
    lbl_sync_exc = QLabel(tr("Exclude names/patterns:", self._current_lang))
    lbl_sync_exc._en_text = "Exclude names/patterns:"


    # Tabs instead of three side-by-side columns. Three columns need the
    # full panel width to be readable at all; one tab at a time stays
    # legible in a narrow window, and FlowLayout reflows each tab down to
    # a single column rather than clipping the right-hand side.

    def _tab(items, columns=None):
        """A zero-waste settings tab: groups stretch into balanced columns filling 100% width."""
        host = _SettingsPage()
        host.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Maximum)
        grid = QGridLayout(host)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        n = len(items)
        cols = columns if columns is not None else (n if n <= 5 else 4)

        for idx, item in enumerate(items):
            r = idx // cols
            c = idx % cols
            grid.addWidget(item, r, c)
            item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        for c in range(cols):
            grid.setColumnStretch(c, 1)

        def totalHeightForWidth(w):
            if not items:
                return 0
            margins = grid.contentsMargins()
            pad_w = margins.left() + margins.right()
            h_space = grid.horizontalSpacing()
            v_space = grid.verticalSpacing()
            col_w = max(1, (w - pad_w - (cols - 1) * h_space) // cols)

            num_rows = (len(items) + cols - 1) // cols
            total_h = margins.top() + margins.bottom()
            for r in range(num_rows):
                row_items = items[r * cols : (r + 1) * cols]
                row_h = 0
                for it in row_items:
                    if hasattr(it, "heightForWidth") and it.hasHeightForWidth():
                        h = it.heightForWidth(col_w)
                    elif hasattr(it, "sizeHint"):
                        h = it.sizeHint().height()
                    else:
                        h = 40
                    row_h = max(row_h, h)
                total_h += row_h
            if num_rows > 1:
                total_h += (num_rows - 1) * v_space
            return total_h

        host.totalHeightForWidth = totalHeightForWidth
        grid.totalHeightForWidth = totalHeightForWidth
        return host

    # self.settings_tabs is already created on self
    self.settings_tabs.setDocumentMode(True)
    # Never taller than the tab actually needs. QTabWidget expands
    # vertically by default, so in a QVBoxLayout it happily swallowed
    # hundreds of pixels of empty panel below a single row of checkboxes.
    self.settings_tabs.setSizePolicy(QSizePolicy.Policy.Preferred,
                                     QSizePolicy.Policy.Maximum)
    # (attribute, english title) — kept for retranslation
    self._settings_tab_titles = ("Window", "Editor", "Clock", "Data")

    # Toolbar order had its own reset; splitter widths, sidebar side and
    # window size had none, so a window dragged somewhere unusable could
    # only be fixed by deleting the database.
    self.btn_copy_cursors = QPushButton(tr("Copy my set", self._current_lang))
    self.btn_copy_cursors.setToolTip(tr(
        "Copy your current Windows cursors INTO the program.\n"
        "The program then keeps using them even if you change\n"
        "the system scheme later. Press again to re-copy.",
        self._current_lang))
    self.btn_copy_cursors.clicked.connect(lambda: self.capture_cursor_set())

    self.btn_install_cursors = QPushButton(tr("Set in system", self._current_lang))
    self.btn_install_cursors.setToolTip(tr(
        "Install the program's copied set as the Windows default\n"
        "(asks first). Right-click: open the full cursor set online.",
        self._current_lang))
    self.btn_install_cursors.clicked.connect(self.install_cursors_to_system)

    def _cursor_btn_mouse(event):
        if event.button() == Qt.MouseButton.RightButton:
            from fastprompter.ui.cursor_theme import DEVIANTART_URL
            QDesktopServices.openUrl(QUrl(DEVIANTART_URL))
            event.accept()
            return
        QPushButton.mousePressEvent(self.btn_install_cursors, event)

    self.btn_install_cursors.mousePressEvent = _cursor_btn_mouse

    self.btn_reset_layout = QPushButton(tr("Reset UI Layout", self._current_lang))
    self.btn_reset_layout.setToolTip(tr(
        "Put the toolbar, sidebar and window size back to defaults.\n"
        "Text, snippets and silos are not touched.", self._current_lang))
    self.btn_reset_layout.clicked.connect(self.reset_ui_layout)

    # Compact Sync-Project input rows so they don't bloat the Data tab vertically
    sync_max_row = QHBoxLayout()
    sync_max_row.setContentsMargins(0, 0, 0, 0)
    sync_max_row.setSpacing(4)
    sync_max_row.addWidget(lbl_sync_max)
    sync_max_row.addWidget(self.spin_sync_max_kb)
    sync_max_row.addStretch(1)

    sync_inc_row = QHBoxLayout()
    sync_inc_row.setContentsMargins(0, 0, 0, 0)
    sync_inc_row.setSpacing(4)
    sync_inc_row.addWidget(lbl_sync_inc)
    sync_inc_row.addWidget(self.ed_sync_include)

    sync_exc_row = QHBoxLayout()
    sync_exc_row.setContentsMargins(0, 0, 0, 0)
    sync_exc_row.setSpacing(4)
    sync_exc_row.addWidget(lbl_sync_exc)
    sync_exc_row.addWidget(self.ed_sync_exclude)

    cur_idx = self.settings_tabs.currentIndex()
    self.settings_tabs.blockSignals(True)
    while self.settings_tabs.count():
        self.settings_tabs.removeTab(0)

    # --- TAB 0: WINDOW (5 balanced columns across 1 row, 100% width) ---
    self.settings_tabs.addTab(_tab([
        _settings_group("Window behaviour", [
            self.cb_top, self.cb_lock_window, self.cb_normal_window,
            self.cb_tray,
        ]),
        _settings_group("Layout", [
            self.cb_sidebar, self.cb_customize_toolbar,
            self.cb_numbox_tabs, numbox_row, self.cb_files_dock,
            self.cb_toolbar_bottom, self.btn_reset_layout,
        ]),
        _settings_group("Window presets", [
            self.cb_window_presets, self.btn_manage_presets,
            self.cb_fast_zones, fast_row,
        ]),
        _settings_group("Silo look", [
            self.cb_silo_color_box, self.cb_trash_vision,
        ]),
        _settings_group("Mouse cursors", [
            self.cb_custom_cursors, self.cb_static_cursor,
            self.btn_copy_cursors, self.btn_install_cursors,
        ]),
    ], columns=5), tr("Window", self._current_lang))

    # --- TAB 1: EDITOR (4 balanced columns x 2 rows, 100% width) ---
    self.settings_tabs.addTab(_tab([
        _settings_group("Dividers & headers", [
            div_row, ctrlw_btn_row, hdr_row, self.cb_hr_visual, self.cb_conceal,
        ]),
        _settings_group("Typing", [
            self.cb_focus, self.cb_tray_activate, self.cb_wrap, self.cb_ctrl_c,
            self.cb_lock_cursor, self.cb_double_line, blink_row,
        ]),
        _settings_group("Line appearance", [
            self.cb_line_numbers, self.cb_line_marks, self.cb_zebra,
            self.cb_bold_titles, self.lbl_align, self.cb_align_combo,
        ]),
        _settings_group("Line metadata", [
            self.lbl_img_paste, self.cb_img_paste,
            self.cb_token_count, token_row,
        ]),
        _settings_group("Line heat", [
            self.cb_line_heat, lbl_heat, self.spin_heat_strength,
            self.spin_heat_minutes, self.cb_heat_palette,
        ]),
        _settings_group("Hover line", [
            self.cb_hover_line, self.spin_hover_opacity,
            self.btn_hover_colour,
        ]),
        _settings_group("Code blocks", [
            self.cb_code_gutter, self.cb_code_monospace,
        ]),
        _settings_group("Typos", [
            self.cb_typo_check, self.btn_typo_colour,
            self.btn_typo_clear,
        ]),
    ], columns=4), tr("Editor", self._current_lang))

    # --- TAB 2: CLOCK (3 balanced columns across 1 row, 100% width) ---
    self.settings_tabs.addTab(_tab([
        _settings_group("Clock", [
            self.cb_analog_clock, self.cb_date_rect, self.cb_date_seconds,
            self.cb_date_ampm,
        ]),
        _settings_group("Date", [
            self.cb_date_daypart, self.cb_date_emoji,
            self.cb_date_text_month, self.cb_passed_alert, self.btn_passed_colour,
        ]),
        _settings_group("Passed events", [
            self.cb_timer_minutes, self.cb_limit_gauges, self.lbl_limit_status,
            self.btn_limit_settings,
        ]),
    ], columns=3), tr("Clock", self._current_lang))

    # --- TAB 3: DATA (4 balanced columns across 1 row, 100% width) ---
    self.settings_tabs.addTab(_tab([
        _settings_group("Silo list", [
            self.cb_silo_home, self.cb_silo_pinned_gap, self.cb_silo_ticks,
            self.cb_snippet_arrows, self.cb_hide_shortkeys, gap_row,
            self.lbl_silo_mode, self.cb_silo_mode,
        ]),
        _settings_group("Sound", [
            self.cb_sound, self.cb_typewriter, vol_row,
            self.cb_cs_style, self.btn_sound_settings,
        ]),
        _settings_group("Files & backup", [
            self.cb_portable_backup, files_row, sync_row, dev_row,
        ]),
        _settings_group("Sync-Project", [
            self.cb_sync_live, self.cb_sync_recursive,
            sync_max_row, sync_inc_row, sync_exc_row,
        ]),
    ], columns=4), tr("Data", self._current_lang))

    self.settings_tabs.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
    self.settings_tabs.blockSignals(False)

    self._apply_settings_language()
    if hasattr(self, "_theme_cache") and self._theme_cache:
        self.mini_settings_frame.setStyleSheet(self._theme_cache.get("mini_settings", ""))
    self._fit_settings_tabs(self.settings_tabs.currentIndex())
