"""Ctrl+E header settings.

Was a one-line template box: the title's wording was configurable and
nothing else. The rule under it, the gap below that, the bullet left ready
and the alignment were all hardcoded in main.py, so the only way to change
the shape of a header was to edit the source.

Laid out like the Ctrl+W page now - switches on the left, a live
before/after underneath, explanations in tooltips - and every part of the
block is a setting. The preview is built by core/header.py, the same
function the editor inserts with.

The template is a plain string with placeholders:
    {text}  — the line's own text
    {time}  — the date/time stamp (honouring the date settings)
    {state} — the time-of-day word (Morning / Day / Evening / Night)
Everything else is kept verbatim.
"""

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from fastprompter.core import header as header_core
from fastprompter.ui.flow_layout import FlowLayout
from fastprompter.core.translations import tr

DEFAULT_TEMPLATE = header_core.DEFAULTS["ctrl_e_format"]

# A Ctrl+E line always starts with "# ", which the editor already renders
# bold + gold + larger. Wrapping the title in **__ __** on top of that only
# prints literal ** __ markers over an already-bold header — pure clutter.
# So every preset is markerless: the header IS the bold.
_PRESETS = [
    ("Title + time", "{text} ({time})"),
    ("Day + time", "{text} — {state} {time}"),
    ("Dotted", "{text}  ·  {time}"),
    ("Dash + time", "{text} — {time}"),
    ("Title only", "{text}"),
]

# Old marker-heavy templates -> their clean equivalents; used to migrate a
# format the user saved before this cleanup so their asterisks disappear too.
LEGACY_TEMPLATE_MIGRATION = {
    "**__{text}__** ({time})": "{text} ({time})",
    "**{text}** — {state} {time}": "{text} — {state} {time}",
    "__{text}__ ({time})": "{text} ({time})",
    "**{text}** ({time})": "{text} ({time})",
}

_PREVIEW_CSS = (
    "QLabel{background:#1b1b1b;border:1px solid #3a3a3a;padding:4px 6px;"
    "color:#c8c8c8;font-family:Consolas,'Courier New',monospace;font-size:11px;}"
)
_DIM = "color:#888;font-size:11px;"

_ALIGN_ITEMS = [
    ("Left", "left"),
    ("Centered", "center"),
    ("Right", "right"),
    ("Justified", "justify"),
]


class HeaderFormatDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self._lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr("Ctrl+E — Header", self._lang))
        self.setModal(True)
        self.setMinimumWidth(560)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        cfg = header_core.read_settings(main_win.data)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── the title line ──
        head = QLabel("<b>" + tr("Title line", self._lang) + "</b>")
        head.setToolTip(tr(
            "How Ctrl+E rewrites the line it is pressed on.\n"
            "{text} is the line's own words, {time} the stamp, {state} the\n"
            "time-of-day word. Everything else is kept exactly as typed.",
            self._lang))
        root.addWidget(head)

        template = cfg["format"]
        if template in LEGACY_TEMPLATE_MIGRATION:
            template = LEGACY_TEMPLATE_MIGRATION[template]
            self.main_win.data["ctrl_e_format"] = template
            self.main_win.mark_dirty()

        self.edit = QLineEdit(template)
        self.edit.setToolTip(head.toolTip())
        self.edit.textChanged.connect(self._refresh)
        root.addWidget(self.edit)

        ins = QHBoxLayout()
        ins.setSpacing(4)
        for label, token in (("{text}", "{text}"), ("{time}", "{time}"),
                             ("{state}", "{state}")):
            b = QPushButton(label)
            b.setToolTip(tr("Insert this placeholder at the cursor", self._lang))
            b.clicked.connect(lambda _c, t=token: self._insert(t))
            ins.addWidget(b)
        for label, wrap in (("B", "**"), ("I", "*"), ("U", "__"), ("S", "~~")):
            b = QPushButton(label)
            b.setFixedWidth(28)
            b.setToolTip(tr(
                "Wrap the selection in this markdown marker. The header is "
                "already bold on its own, so these are usually clutter.",
                self._lang))
            b.clicked.connect(lambda _c, m=wrap: self._wrap(m))
            ins.addWidget(b)
        ins.addStretch(1)
        root.addLayout(ins)

        # a flow, not a row: five translated preset names do not fit on one
        # line at the dialog's minimum width, and the last one was clipped
        prow = FlowLayout(margin=0, h_spacing=4, v_spacing=4)
        lbl_pre = QLabel(tr("Presets:", self._lang))
        lbl_pre.setToolTip(tr("Ready-made title lines. Click one, then edit it.", self._lang))
        prow.addWidget(lbl_pre)
        for name, tmpl in _PRESETS:
            b = QPushButton(tr(name, self._lang))
            b.setToolTip(tmpl)
            b.clicked.connect(lambda _c, t=tmpl: self.edit.setText(t))
            prow.addWidget(b)
        root.addLayout(prow)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # ── the block under the title ──
        head2 = QLabel("<b>" + tr("What goes under it", self._lang) + "</b>")
        head2.setToolTip(tr(
            "Ctrl+E does not only rewrite the line - it lays out a whole "
            "block:\nthe title, an optional --- rule, a gap, and a bullet "
            "left ready to type on.", self._lang))
        root.addWidget(head2)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.cb_rule = QCheckBox(tr("rule ———", self._lang))
        self.cb_rule.setToolTip(tr(
            "Draw a --- line straight under the title. Off leaves the title "
            "on its own.", self._lang))
        self.cb_rule.setChecked(cfg["rule"])
        self.cb_rule.toggled.connect(self._refresh)
        row.addWidget(self.cb_rule)

        lbl_gap = QLabel(tr("gap:", self._lang))
        lbl_gap.setToolTip(tr(
            "Empty lines between the rule and the bullet - the room you get "
            "to write in. 0 puts the bullet straight underneath.", self._lang))
        row.addWidget(lbl_gap)
        self.sb_gap = QSpinBox()
        self.sb_gap.setRange(0, 6)
        self.sb_gap.setMaximumWidth(48)
        self.sb_gap.setToolTip(lbl_gap.toolTip())
        self.sb_gap.setValue(cfg["gap_after"])
        self.sb_gap.valueChanged.connect(self._refresh)
        row.addWidget(self.sb_gap)

        row.addSpacing(8)
        self.cb_bullet = QCheckBox(tr("bullet", self._lang))
        self.cb_bullet.setToolTip(tr(
            "Leave a fresh point below and put the caret on it. Off leaves "
            "the caret on the title.", self._lang))
        self.cb_bullet.setChecked(cfg["bullet"])
        self.cb_bullet.toggled.connect(self._on_bullet_toggled)
        row.addWidget(self.cb_bullet)

        self.cb_bullet_char = QComboBox()
        self.cb_bullet_char.setEditable(True)
        self.cb_bullet_char.setMinimumWidth(70)
        self.cb_bullet_char.setToolTip(tr(
            "The character that point starts with. Type your own if none of "
            "these fit.", self._lang))
        for ch in ("•", "-", "*", "+", "▸", "◦", "→"):
            self.cb_bullet_char.addItem(ch, ch)
        self.cb_bullet_char.setCurrentText(cfg["bullet_char"])
        self.cb_bullet_char.setEnabled(cfg["bullet"])
        self.cb_bullet_char.currentTextChanged.connect(self._refresh)
        row.addWidget(self.cb_bullet_char)
        row.addStretch(1)
        root.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        lbl_align = QLabel(tr("Align title:", self._lang))
        lbl_align.setToolTip(tr(
            "Where the title sits in the width of the editor. Only the title "
            "line moves - the rule, the gap and the bullet stay put.\n"
            "Centred titles are remembered across a reload; the other "
            "directions are applied as the header is written.", self._lang))
        row2.addWidget(lbl_align)
        self.cb_align = QComboBox()
        self.cb_align.setToolTip(lbl_align.toolTip())
        for name, val in _ALIGN_ITEMS:
            self.cb_align.addItem(tr(name, self._lang), val)
        idx = self.cb_align.findData(cfg["align"])
        if idx >= 0:
            self.cb_align.setCurrentIndex(idx)
        self.cb_align.currentIndexChanged.connect(self._refresh)
        row2.addWidget(self.cb_align)

        row2.addSpacing(12)
        self.cb_stamp_every = QCheckBox(tr("stamp every header", self._lang))
        self.cb_stamp_every.setToolTip(tr(
            "Off (default): only the first header in a silo carries the "
            "timestamp - it dates the note, and the ones below are section "
            "markers.\nOn: every header gets the full title line.",
            self._lang))
        self.cb_stamp_every.setChecked(cfg["stamp_every"])
        self.cb_stamp_every.toggled.connect(self._refresh)
        row2.addWidget(self.cb_stamp_every)
        row2.addStretch(1)
        root.addLayout(row2)

        # ── before / after ──
        hint = QLabel(tr(
            "· marks an empty line, │ the caret. Press Ctrl+E on the left, "
            "get the right.", self._lang))
        hint.setStyleSheet(_DIM)
        hint.setWordWrap(True)
        root.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(4)
        cap_b = QLabel(tr("before", self._lang))
        cap_b.setStyleSheet(_DIM)
        cap_a = QLabel(tr("after Ctrl+E", self._lang))
        cap_a.setStyleSheet(_DIM)
        grid.addWidget(cap_b, 0, 0)
        grid.addWidget(cap_a, 0, 2)
        self.pv_before = QLabel()
        self.pv_before.setStyleSheet(_PREVIEW_CSS)
        self.pv_before.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.pv_before.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        arrow = QLabel("→")
        arrow.setStyleSheet(_DIM)
        self.pv_after = QLabel()
        self.pv_after.setStyleSheet(_PREVIEW_CSS)
        self.pv_after.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.pv_after.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # the old single-pane name; kept so callers/tests that ask for "the
        # preview" get the meaningful half rather than an AttributeError
        self.preview = self.pv_after
        grid.addWidget(self.pv_before, 1, 0)
        grid.addWidget(arrow, 1, 1)
        grid.addWidget(self.pv_after, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        root.addLayout(grid)

        # ── buttons ──
        brow = QHBoxLayout()
        reset = QPushButton(tr("Reset to Default", self._lang))
        reset.setToolTip(tr("Put every setting on this page back to the shipped default.", self._lang))
        reset.clicked.connect(self._reset)
        brow.addWidget(reset)
        brow.addStretch(1)
        cancel = QPushButton(tr("Cancel", self._lang))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("OK", self._lang))
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        brow.addWidget(cancel)
        brow.addWidget(ok)
        root.addLayout(brow)

        self._refresh()

    # ── template field helpers ──
    def _insert(self, token):
        self.edit.insert(token)
        self.edit.setFocus()

    def _wrap(self, marker):
        if self.edit.hasSelectedText():
            sel = self.edit.selectedText()
            start = self.edit.selectionStart()
            full = self.edit.text()
            self.edit.setText(full[:start] + marker + sel + marker + full[start + len(sel):])
        else:
            self.edit.insert(marker + marker)
        self.edit.setFocus()

    def _on_bullet_toggled(self, checked):
        self.cb_bullet_char.setEnabled(checked)
        self._refresh()

    # ── live preview ──
    def _cfg(self):
        """The settings as the widgets currently stand."""
        bullet_char = self.cb_bullet_char.currentText()
        return {
            "format": self.edit.text() or DEFAULT_TEMPLATE,
            "rule": self.cb_rule.isChecked(),
            "gap_after": self.sb_gap.value(),
            "bullet": self.cb_bullet.isChecked(),
            "bullet_char": bullet_char if bullet_char.strip() else "•",
            "align": self.cb_align.currentData() or "left",
            "stamp_every": self.cb_stamp_every.isChecked(),
        }

    def _stamp(self):
        """The same stamp the editor would write, from the date settings."""
        now = datetime.datetime.now()
        h = now.hour
        state = ("Morning" if 5 <= h < 12 else "Day" if 12 <= h < 17
                 else "Evening" if 17 <= h < 22 else "Night")
        d = self.main_win.data
        m_fmt = "%d %b" if d.get("date_text_month", "False") == "True" else "%d.%m"
        try:
            t_fmt = self.main_win._clock_time_fmt()
        except Exception:
            t_fmt = "%H:%M"
        ts = now.strftime(f"{m_fmt} - {t_fmt}")
        if "{state}" in self.edit.text():
            time_str = ts
        elif d.get("date_daypart", "True") == "True":
            time_str = f"{state} {ts}"
        else:
            time_str = ts
        return time_str, state

    def sample_line(self, template):
        """Render the template with sample values — matches the editor."""
        time_str, state = self._stamp()
        return header_core.header_line(
            template, tr("Sample title", self._lang), time_str, state)

    def _refresh(self, *_):
        cfg = self._cfg()
        time_str, state = self._stamp()
        before, after = header_core.simulate(
            cfg, title=tr("Sample title", self._lang),
            time_str=time_str, state=state)
        self.pv_before.setText(header_core.render_preview(before))
        self.pv_after.setText(header_core.render_preview(after))
        # the alignment cannot be shown in a monospace box, so say it
        align = cfg["align"]
        self.pv_after.setAlignment(
            Qt.AlignmentFlag.AlignTop | {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
                "justify": Qt.AlignmentFlag.AlignLeft,
            }[align])

    def _reset(self):
        d = header_core.DEFAULTS
        self.edit.setText(d["ctrl_e_format"])
        self.cb_rule.setChecked(d["ctrl_e_rule"] == "True")
        self.sb_gap.setValue(int(d["ctrl_e_gap_after"]))
        self.cb_bullet.setChecked(d["ctrl_e_bullet"] == "True")
        self.cb_bullet_char.setCurrentText(d["ctrl_e_bullet_char"])
        idx = self.cb_align.findData(d["ctrl_e_align"])
        if idx >= 0:
            self.cb_align.setCurrentIndex(idx)
        self.cb_stamp_every.setChecked(d["ctrl_e_stamp_every"] == "True")
        self._refresh()

    def _accept(self):
        cfg = self._cfg()
        d = self.main_win.data
        d["ctrl_e_format"] = cfg["format"]
        d["ctrl_e_rule"] = "True" if cfg["rule"] else "False"
        d["ctrl_e_gap_after"] = str(cfg["gap_after"])
        d["ctrl_e_bullet"] = "True" if cfg["bullet"] else "False"
        d["ctrl_e_bullet_char"] = cfg["bullet_char"]
        d["ctrl_e_align"] = cfg["align"]
        d["ctrl_e_stamp_every"] = "True" if cfg["stamp_every"] else "False"
        # the old boolean is what the settings checkbox still shows; keep it
        # agreeing with the alignment instead of letting the two contradict
        d["ctrl_e_center"] = "True" if cfg["align"] == "center" else "False"
        self.main_win.mark_dirty()
        if hasattr(self.main_win, "le_hdr_fmt"):
            self.main_win.le_hdr_fmt.setText(cfg["format"])
        cb = getattr(self.main_win, "cb_ctrl_e_center", None)
        if cb is not None:
            try:
                cb.blockSignals(True)
                cb.setChecked(cfg["align"] == "center")
            finally:
                cb.blockSignals(False)
        self.accept()
