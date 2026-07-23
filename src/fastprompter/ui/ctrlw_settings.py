"""Ctrl+W settings.

Rewritten from a page of prose into a page of examples. Every card used to
carry two lines of explanation and one hard-coded sample string; six cards
of that is a wall nobody reads, and the samples were fixed text that went
stale the moment a spacing value changed. Now each card shows the real
before/after for its own scenario, recomputed from the widgets as they are
touched, and the sentences it replaced live in tooltips.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QFrame,
)

from fastprompter.core.ctrlw import (
    SCENES, SCENE_HELP, SCENE_TITLES, SCENE_TRIGGERS, S6_HELP,
    render_preview, simulate,
)
from fastprompter.core.translations import tr

KEYS = {
    "bullet_char": ("ctrlw_bullet_char", "•"),
    "blanks_before": ("ctrlw_blanks_before", "2"),
    "blanks_after": ("ctrlw_blanks_after", "3"),
}
SCENE_KEYS = ("divider", "bullet", "before", "after")

_PREVIEW_CSS = (
    "QLabel{background:#1b1b1b;border:1px solid #3a3a3a;padding:4px 6px;"
    "color:#c8c8c8;font-family:Consolas,'Courier New',monospace;font-size:11px;}"
)
_DIM = "color:#888;font-size:11px;"


def _default(key, prefix="ctrlw"):
    """The shipped value for a settings key, under either key set.

    Alt+W keeps its own copy of every value (prefix "altw"), so the two
    directions can be tuned apart; the defaults are identical because the
    block is the same block, only turned around.
    """
    key = key.replace(prefix + "_", "ctrlw_", 1)
    vals = {
        "ctrlw_bullet_char": "•",
        "ctrlw_blanks_before": "2",
        "ctrlw_blanks_after": "3",
        "ctrlw_s1_divider": "True", "ctrlw_s1_bullet": "True",
        "ctrlw_s1_before": "", "ctrlw_s1_after": "",
        "ctrlw_s2_divider": "True", "ctrlw_s2_bullet": "True",
        "ctrlw_s2_before": "", "ctrlw_s2_after": "",
        "ctrlw_s3_divider": "True", "ctrlw_s3_bullet": "False",
        "ctrlw_s3_before": "", "ctrlw_s3_after": "",
        "ctrlw_s4_divider": "True", "ctrlw_s4_bullet": "True",
        "ctrlw_s4_before": "", "ctrlw_s4_after": "",
        "ctrlw_s5_divider": "False", "ctrlw_s5_bullet": "True",
        "ctrlw_s5_before": "", "ctrlw_s5_after": "",
        "ctrlw_s6_action": "remove",
    }
    return vals.get(key, "")


class CtrlWSettingsDialog(QDialog):
    """The settings page for Ctrl+W, and for Alt+W with `upward=True`.

    One class, two key sets. Alt+W is the same block turned around, so it
    wants the same controls and the same live before/after - duplicating the
    page would have meant fixing every later bug twice.
    """

    def __init__(self, main_win, prefix="ctrlw", upward=False):
        super().__init__(main_win)
        self.main_win = main_win
        self.prefix = prefix
        self.upward = upward
        self.lang = getattr(main_win, "_current_lang", "EN")
        self.setWindowTitle(tr(
            "Alt+W — Smart Line (upward)" if upward else "Ctrl+W — Smart Line",
            self.lang))
        self.setMinimumSize(640, 560)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ── Global defaults ──
        head = QLabel("<b>" + tr("Defaults", self.lang) + "</b>")
        head.setToolTip(tr(
            "Ctrl+W inserts a divider and/or a bullet, choosing what to do "
            "from where the caret is.\nThese values apply to every scenario "
            "that does not override them.", self.lang))
        layout.addWidget(head)

        global_row = QHBoxLayout()
        global_row.setSpacing(6)

        lbl_bullet = QLabel(tr("Bullet:", self.lang))
        lbl_bullet.setToolTip(tr(
            "The character each new point starts with. Pick one from the "
            "list or type your own — the box is editable, so an emoji "
            "or → works too.", self.lang))
        global_row.addWidget(lbl_bullet)
        self.cb_bullet = QComboBox()
        self.cb_bullet.setEditable(True)  # the "text edit box" - any bullet
        self.cb_bullet.setToolTip(lbl_bullet.toolTip())
        self.cb_bullet.setMaxVisibleItems(8)
        self.cb_bullet.setMinimumWidth(70)
        for ch in ("•", "-", "*", "+", "▸", "◦", "→"):
            self.cb_bullet.addItem(ch, ch)
        self.cb_bullet.setCurrentText(
            str(self.main_win.data.get(f"{prefix}_bullet_char", "•")))
        self.cb_bullet.currentTextChanged.connect(self._refresh)
        global_row.addWidget(self.cb_bullet)
        global_row.addSpacing(12)

        lbl_bf = QLabel(tr("Gap above ———:", self.lang))
        lbl_bf.setToolTip(tr(
            "Newlines inserted before the divider. 2 leaves one empty line "
            "visible above it; 0 puts it straight under the text.", self.lang))
        global_row.addWidget(lbl_bf)
        self.sb_before = self._spin_from(f"{prefix}_blanks_before", 0, 6, 2)
        self.sb_before.setToolTip(lbl_bf.toolTip())
        global_row.addWidget(self.sb_before)

        lbl_af = QLabel(tr("Gap below:", self.lang))
        lbl_af.setToolTip(tr(
            "Newlines between the divider and the new point. 1 puts them on "
            "consecutive lines; 3 leaves two empty lines to write in.",
            self.lang))
        global_row.addWidget(lbl_af)
        self.sb_after = self._spin_from(f"{prefix}_blanks_after", 1, 6, 3)
        self.sb_after.setToolTip(lbl_af.toolTip())
        global_row.addWidget(self.sb_after)
        global_row.addStretch(1)
        layout.addLayout(global_row)

        self.sb_before.valueChanged.connect(self._refresh)
        self.sb_after.valueChanged.connect(self._refresh)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        hint = QLabel(tr(
            "Each card shows what Ctrl+W does to a sample note. "
            "· marks an empty line, │ the caret.", self.lang))
        hint.setStyleSheet(_DIM)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ── Scrollable scenario cards ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        sw = QWidget()
        self._scene_layout = QVBoxLayout(sw)
        self._scene_layout.setSpacing(8)
        self._scene_widgets = {}

        for sid, _title, _trigger in SCENES:
            self._scene_layout.addWidget(self._build_scene_card(sid))

        self._scene_layout.addWidget(self._build_s6_card())
        self._scene_layout.addStretch(1)

        scroll.setWidget(sw)
        layout.addWidget(scroll, 1)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_reset = QPushButton(tr("Reset defaults", self.lang))
        btn_reset.setToolTip(tr(
            "Put every value on this page back to the shipped default.",
            self.lang))
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_ok = QPushButton(tr("OK", self.lang))
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(tr("Cancel", self.lang))
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._refresh()

    # ── helpers ──
    def _spin_from(self, key, lo, hi, default):
        s = QSpinBox()
        s.setRange(lo, hi)
        try:
            s.setValue(int(self.main_win.data.get(key, str(default))))
        except (TypeError, ValueError):
            s.setValue(default)
        return s

    def _scene_val(self, sid, k, default=""):
        return self.main_win.data.get(f"{self.prefix}_{sid}_{k}", default)

    def _build_scene_card(self, sid):
        """One scenario: a title, its switches, and its live before/after."""
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setToolTip(SCENE_HELP.get(sid, "") + "\n\n"
                        + tr("Fires when: ", self.lang) + SCENE_TRIGGERS.get(sid, ""))
        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        lbl_title = QLabel(f"<b>{tr(SCENE_TITLES.get(sid, sid), self.lang)}</b>")
        lbl_title.setToolTip(card.toolTip())
        row.addWidget(lbl_title)
        row.addSpacing(8)

        cb_div = QCheckBox(tr("divider", self.lang))
        cb_div.setToolTip(tr(
            "Insert a --- line here. Off means only the bullet is added.",
            self.lang))
        cb_div.setChecked(self._scene_val(sid, "divider", "True") == "True")
        self._scene_widgets[f"{sid}_div"] = cb_div
        row.addWidget(cb_div)

        cb_bul = QCheckBox(tr("bullet", self.lang))
        cb_bul.setToolTip(tr(
            "Start a fresh point and leave the caret on it. Off means the "
            "divider goes in and the caret stays where the text is.",
            self.lang))
        cb_bul.setChecked(self._scene_val(sid, "bullet", "True") == "True")
        self._scene_widgets[f"{sid}_bul"] = cb_bul
        row.addWidget(cb_bul)

        row.addSpacing(8)
        cb_ovr = QCheckBox(tr("own gaps", self.lang))
        cb_ovr.setToolTip(tr(
            "Use spacing just for this scenario instead of the defaults at "
            "the top.", self.lang))
        has_ovr = (self._scene_val(sid, "before", "") != ""
                   or self._scene_val(sid, "after", "") != "")
        cb_ovr.setChecked(has_ovr)
        self._scene_widgets[f"{sid}_ovr"] = cb_ovr
        row.addWidget(cb_ovr)

        sb_bf = self._spin_from(f"{self.prefix}_{sid}_before", 0, 6, 2)
        sb_bf.setToolTip(tr("Newlines above the divider, this scenario only.", self.lang))
        sb_bf.setMaximumWidth(44)
        sb_bf.setEnabled(has_ovr)
        self._scene_widgets[f"{sid}_bf"] = sb_bf
        row.addWidget(sb_bf)

        sb_af = self._spin_from(f"{self.prefix}_{sid}_after", 1, 6, 3)
        sb_af.setToolTip(tr("Newlines below the divider, this scenario only.", self.lang))
        sb_af.setMaximumWidth(44)
        sb_af.setEnabled(has_ovr)
        self._scene_widgets[f"{sid}_af"] = sb_af
        row.addWidget(sb_af)
        row.addStretch(1)
        outer.addLayout(row)

        # ── before → after ──
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setSpacing(4)
        cap_b = QLabel(tr("before", self.lang))
        cap_b.setStyleSheet(_DIM)
        cap_a = QLabel(tr("after Ctrl+W", self.lang))
        cap_a.setStyleSheet(_DIM)
        grid.addWidget(cap_b, 0, 0)
        grid.addWidget(cap_a, 0, 2)

        pv_b = QLabel()
        pv_b.setStyleSheet(_PREVIEW_CSS)
        pv_b.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        pv_b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        arrow = QLabel("→")
        arrow.setStyleSheet(_DIM)
        pv_a = QLabel()
        pv_a.setStyleSheet(_PREVIEW_CSS)
        pv_a.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        pv_a.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(pv_b, 1, 0)
        grid.addWidget(arrow, 1, 1)
        grid.addWidget(pv_a, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        self._scene_widgets[f"{sid}_pv_b"] = pv_b
        self._scene_widgets[f"{sid}_pv_a"] = pv_a
        outer.addLayout(grid)

        def _toggle_override(checked):
            sb_bf.setEnabled(checked)
            sb_af.setEnabled(checked)
            self._refresh()

        cb_ovr.toggled.connect(_toggle_override)
        cb_div.toggled.connect(self._refresh)
        cb_bul.toggled.connect(self._refresh)
        sb_bf.valueChanged.connect(self._refresh)
        sb_af.valueChanged.connect(self._refresh)
        return card

    def _build_s6_card(self):
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setToolTip(S6_HELP)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        lbl = QLabel("<b>" + tr("Caret on a divider", self.lang) + "</b>")
        lbl.setToolTip(S6_HELP)
        row.addWidget(lbl)
        self.cb_s6_action = QComboBox()
        self.cb_s6_action.setToolTip(S6_HELP)
        self.cb_s6_action.addItem(tr("remove the divider", self.lang), "remove")
        self.cb_s6_action.addItem(tr("keep it, add a point below", self.lang), "bullet")
        self.cb_s6_action.addItem(tr("do nothing", self.lang), "skip")
        idx = self.cb_s6_action.findData(
            self.main_win.data.get(f"{self.prefix}_s6_action", "remove"))
        if idx >= 0:
            self.cb_s6_action.setCurrentIndex(idx)
        self.cb_s6_action.currentIndexChanged.connect(self._refresh)
        row.addWidget(self.cb_s6_action)
        row.addStretch(1)
        outer.addLayout(row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setSpacing(4)
        cap_b = QLabel(tr("before", self.lang))
        cap_b.setStyleSheet(_DIM)
        cap_a = QLabel(tr("after Ctrl+W", self.lang))
        cap_a.setStyleSheet(_DIM)
        grid.addWidget(cap_b, 0, 0)
        grid.addWidget(cap_a, 0, 2)
        pv_b = QLabel()
        pv_b.setStyleSheet(_PREVIEW_CSS)
        pv_b.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        arrow = QLabel("→")
        arrow.setStyleSheet(_DIM)
        pv_a = QLabel()
        pv_a.setStyleSheet(_PREVIEW_CSS)
        pv_a.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(pv_b, 1, 0)
        grid.addWidget(arrow, 1, 1)
        grid.addWidget(pv_a, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        self._scene_widgets["s6_pv_b"] = pv_b
        self._scene_widgets["s6_pv_a"] = pv_a
        outer.addLayout(grid)
        return card

    # ── live preview ──
    def _bullet_char(self):
        txt = self.cb_bullet.currentText()
        # an empty box would render a preview with an invisible bullet, which
        # reads as "bullet off" - fall back rather than show that
        return txt if txt.strip() else "•"

    def _gaps(self, sid):
        if self._scene_widgets[f"{sid}_ovr"].isChecked():
            return (self._scene_widgets[f"{sid}_bf"].value(),
                    self._scene_widgets[f"{sid}_af"].value())
        return self.sb_before.value(), self.sb_after.value()

    def _refresh(self, *_):
        if self._loading:
            return
        bullet = self._bullet_char()
        for sid, _t, _w in SCENES:
            bf, af = self._gaps(sid)
            before, after = simulate(
                sid,
                self._scene_widgets[f"{sid}_div"].isChecked(),
                self._scene_widgets[f"{sid}_bul"].isChecked(),
                bf, af, bullet, self.upward,
            )
            self._scene_widgets[f"{sid}_pv_b"].setText(render_preview(before))
            self._scene_widgets[f"{sid}_pv_a"].setText(render_preview(after))
        self._refresh_s6(bullet)

    def _refresh_s6(self, bullet):
        action = self.cb_s6_action.currentData() or "remove"
        src = "a thought\n\n---│\n\nnext"
        if action == "remove":
            out = "a thought\n│\n\nnext"
        elif action == "bullet":
            _bf, af = self.sb_before.value(), self.sb_after.value()
            out = "a thought\n\n---" + "\n" * af + bullet + " │\n\nnext"
        else:
            out = src
        self._scene_widgets["s6_pv_b"].setText(render_preview(src))
        self._scene_widgets["s6_pv_a"].setText(render_preview(out))

    def _reset_defaults(self):
        for _short, (key, default) in KEYS.items():
            self.main_win.data[key.replace("ctrlw_", self.prefix + "_", 1)] = default
        for sid, _t, _w in SCENES:
            for k in SCENE_KEYS:
                self.main_win.data[f"{self.prefix}_{sid}_{k}"] = _default(f"ctrlw_{sid}_{k}")
        self.main_win.data[f"{self.prefix}_s6_action"] = "remove"
        self.main_win.mark_dirty()
        self._reload_from_data()

    def _reload_from_data(self):
        d = self.main_win.data
        # reloading moves a dozen widgets, each of which would fire a full
        # repaint of every preview; refresh once at the end instead
        self._loading = True
        try:
            self.cb_bullet.setCurrentText(str(d.get(f"{self.prefix}_bullet_char", "•")))
            self.sb_before.setValue(int(d.get(f"{self.prefix}_blanks_before", 2)))
            self.sb_after.setValue(int(d.get(f"{self.prefix}_blanks_after", 3)))
            for sid, _t, _w in SCENES:
                self._scene_widgets[f"{sid}_div"].setChecked(
                    d.get(f"{self.prefix}_{sid}_divider", "True") == "True")
                self._scene_widgets[f"{sid}_bul"].setChecked(
                    d.get(f"{self.prefix}_{sid}_bullet", "True") == "True")
                b_s = d.get(f"{self.prefix}_{sid}_before", "")
                a_s = d.get(f"{self.prefix}_{sid}_after", "")
                has_ovr = b_s != "" or a_s != ""
                self._scene_widgets[f"{sid}_ovr"].setChecked(has_ovr)
                try:
                    self._scene_widgets[f"{sid}_bf"].setValue(int(b_s) if b_s else 2)
                except (TypeError, ValueError):
                    self._scene_widgets[f"{sid}_bf"].setValue(2)
                try:
                    self._scene_widgets[f"{sid}_af"].setValue(int(a_s) if a_s else 3)
                except (TypeError, ValueError):
                    self._scene_widgets[f"{sid}_af"].setValue(3)
                self._scene_widgets[f"{sid}_bf"].setEnabled(has_ovr)
                self._scene_widgets[f"{sid}_af"].setEnabled(has_ovr)
            idx = self.cb_s6_action.findData(d.get(f"{self.prefix}_s6_action", "remove"))
            if idx >= 0:
                self.cb_s6_action.setCurrentIndex(idx)
        finally:
            self._loading = False
        self._refresh()

    def accept(self):
        d = self.main_win.data
        d[f"{self.prefix}_bullet_char"] = self._bullet_char()
        d[f"{self.prefix}_blanks_before"] = str(self.sb_before.value())
        d[f"{self.prefix}_blanks_after"] = str(self.sb_after.value())
        for sid, _t, _w in SCENES:
            d[f"{self.prefix}_{sid}_divider"] = "True" if self._scene_widgets[f"{sid}_div"].isChecked() else "False"
            d[f"{self.prefix}_{sid}_bullet"] = "True" if self._scene_widgets[f"{sid}_bul"].isChecked() else "False"
            if self._scene_widgets[f"{sid}_ovr"].isChecked():
                d[f"{self.prefix}_{sid}_before"] = str(self._scene_widgets[f"{sid}_bf"].value())
                d[f"{self.prefix}_{sid}_after"] = str(self._scene_widgets[f"{sid}_af"].value())
            else:
                d[f"{self.prefix}_{sid}_before"] = ""
                d[f"{self.prefix}_{sid}_after"] = ""
        d[f"{self.prefix}_s6_action"] = self.cb_s6_action.currentData() or "remove"
        self.main_win.mark_dirty()
        super().accept()
