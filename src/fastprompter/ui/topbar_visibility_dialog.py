"""Editor for the versioned responsive top-bar policy."""

from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.topbar_visibility import (
    RANGE_IDS,
    TOPBAR_ITEMS,
    default_topbar_visibility,
    normalize_topbar_visibility,
    range_for_width,
)
from fastprompter.core.translations import tr

# -- toggle-button group that replaces QComboBox in every table cell ---------

_BTN_STYLE = (
    "QPushButton { font-size: 10px; padding: 1px 4px; border: 1px solid #555; "
    "border-radius: 2px; min-width: 36px; }"
    "QPushButton:checked { font-weight: bold; background: #4A4A3A; "
    "border-color: #A89050; color: #E8D888; }"
    "QPushButton:disabled { color: #777; }"
)


class RuleButtonGroup(QWidget):
    """Exclusive toggle-button row — drop-in replacement for QComboBox.

    Stores (rule, detail) tuples identical to what the old combo stored.
    Exposes .currentData(), .setCurrentIndex(i), .count(), .itemData(i),
    .isEnabled(), .setEnabled(b), .setToolTip(t) — the full API surface
    that TopbarVisibilityDialog touches.
    """

    def __init__(self, choices: list[tuple[str, tuple]], parent=None):
        super().__init__(parent)
        self._choices = list(choices)  # [(label, (rule, detail)), ...]
        self._buttons: list[QPushButton] = []
        self._current = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        for i, (label, _data) in enumerate(self._choices):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(_BTN_STYLE)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                              QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _checked, idx=i: self._select(idx))
            lay.addWidget(btn)
            self._buttons.append(btn)
        if self._buttons:
            self._buttons[0].setChecked(True)

    # -- combo-compatible API ------------------------------------------------
    def currentData(self):  # noqa: N802
        return self._choices[self._current][1]

    def setCurrentIndex(self, i: int):  # noqa: N802
        if 0 <= i < len(self._buttons):
            self._select(i)

    def count(self) -> int:
        return len(self._choices)

    def itemData(self, i: int):  # noqa: N802
        return self._choices[i][1] if 0 <= i < len(self._choices) else None

    def isEnabled(self) -> bool:  # noqa: N802
        return super().isEnabled()

    def setEnabled(self, b: bool):  # noqa: N802
        super().setEnabled(b)
        for btn in self._buttons:
            btn.setEnabled(b)

    def setToolTip(self, t: str):  # noqa: N802
        super().setToolTip(t)
        for btn in self._buttons:
            btn.setToolTip(t)

    # -- internal ------------------------------------------------------------
    def _select(self, idx: int):
        self._current = idx
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == idx)


class TopbarVisibilityDialog(QDialog):
    """Responsive range, per-item rule and fallback-priority editor."""

    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.lang = getattr(main_win, "_current_lang", "EN")
        self._config = copy.deepcopy(main_win._topbar_visibility_config())
        self._range_boxes: dict[tuple[str, str], RuleButtonGroup] = {}
        self._priority_boxes: dict[str, QSpinBox] = {}
        self.setWindowTitle(tr("Top bar button visibility", self.lang))
        self.resize(900, 560)
        self.setMinimumSize(640, 500)
        try:
            self.setStyleSheet(main_win.styleSheet())
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        ranges = QGroupBox(tr("Width ranges", self.lang))
        grid = QGridLayout(ranges)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(4)
        grid.addWidget(QLabel(tr("Narrow starts", self.lang)), 0, 0)
        grid.addWidget(QLabel(tr("Medium starts", self.lang)), 0, 2)
        grid.addWidget(QLabel(tr("Wide starts", self.lang)), 0, 4)
        starts = {e["id"]: e["min"] for e in self._config["breakpoints"]}
        self.spin_narrow = self._breakpoint_spin(starts["narrow"])
        self.spin_medium = self._breakpoint_spin(starts["medium"])
        self.spin_wide = self._breakpoint_spin(starts["wide"])
        grid.addWidget(self.spin_narrow, 0, 1)
        grid.addWidget(self.spin_medium, 0, 3)
        grid.addWidget(self.spin_wide, 0, 5)
        grid.addWidget(QLabel(tr(
            "Rules use effective toolbar width: UI scaling above 100% reduces it.",
            self.lang)), 1, 0, 1, 6)
        root.addWidget(ranges)

        status = QHBoxLayout()
        self.lbl_window_width = QLabel()
        self.lbl_effective_width = QLabel()
        self.lbl_active_range = QLabel()
        status.addWidget(self.lbl_window_width)
        status.addWidget(self.lbl_effective_width)
        status.addWidget(self.lbl_active_range)
        status.addStretch(1)
        root.addLayout(status)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        self.in_filter = QLineEdit()
        self.in_filter.setPlaceholderText(
            tr("Filter buttons (e.g. clock, date, format)...", self.lang))
        self.in_filter.setClearButtonEnabled(True)
        self.in_filter.textChanged.connect(self._filter_items)
        filter_bar.addWidget(self.in_filter, 2)

        self.combo_category = QComboBox()
        self.combo_category.addItem(tr("All categories", self.lang), None)
        seen_groups = []
        for it in TOPBAR_ITEMS:
            if it.group not in seen_groups:
                seen_groups.append(it.group)
        for g in seen_groups:
            count = sum(1 for it in TOPBAR_ITEMS if it.group == g)
            self.combo_category.addItem(f"{tr(g, self.lang)} ({count})", g)
        self.combo_category.currentIndexChanged.connect(self._filter_items)
        filter_bar.addWidget(self.combo_category, 1)

        self.combo_preset = QComboBox()
        self.combo_preset.addItem(tr("Presets / Quick setup...", self.lang), None)
        self.combo_preset.addItem(tr("Balanced (Default)", self.lang), "balanced")
        self.combo_preset.addItem(tr("Minimal (Focus)", self.lang), "minimal")
        self.combo_preset.addItem(tr("Status Focus", self.lang), "status_focus")
        self.combo_preset.addItem(tr("Show All", self.lang), "show_all")
        self.combo_preset.currentIndexChanged.connect(self._preset_picked)
        filter_bar.addWidget(self.combo_preset, 1)

        self.cb_show_priority = QCheckBox(
            tr("Show priority (advanced)", self.lang))
        self.cb_show_priority.setChecked(False)
        self.cb_show_priority.toggled.connect(self._toggle_priority_column)
        filter_bar.addWidget(self.cb_show_priority)

        root.addLayout(filter_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        mass = QHBoxLayout()
        self.btn_show_range = QPushButton(tr("Show all in active range", self.lang))
        self.btn_hide_range = QPushButton(tr("Hide optional in active range", self.lang))
        self.btn_copy_wide = QPushButton(tr("Copy Wide to Medium", self.lang))
        self.btn_defaults = QPushButton(tr("Restore defaults", self.lang))
        self.btn_show_range.clicked.connect(lambda: self._set_active_range("show"))
        self.btn_hide_range.clicked.connect(lambda: self._set_active_range("hide"))
        self.btn_copy_wide.clicked.connect(self._copy_wide_to_medium)
        self.btn_defaults.clicked.connect(self._restore_defaults)
        for button in (self.btn_show_range, self.btn_hide_range,
                       self.btn_copy_wide, self.btn_defaults):
            mass.addWidget(button)
        mass.addStretch(1)
        root.addLayout(mass)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self.apply_changes)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for spin in (self.spin_narrow, self.spin_medium, self.spin_wide):
            spin.valueChanged.connect(self._breakpoints_changed)
        self._rebuild_table()
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._update_width_preview)
        self._preview_timer.start(250)
        self._update_width_preview()

    def _breakpoint_spin(self, value):
        spin = QSpinBox()
        spin.setRange(200, 10000)
        spin.setSuffix(" px")
        spin.setValue(int(value))
        return spin

    def _tr_range(self, range_id):
        return tr(range_id.capitalize(), self.lang)

    def _rule_combo(self, item, range_id, row):
        if item.compact:
            choices = [
                (tr("Show — Full", self.lang), ("show", "full")),
                (tr("Show — Compact", self.lang), ("show", "compact")),
                (tr("Auto — Full", self.lang), ("auto", "full")),
                (tr("Auto — Compact", self.lang), ("auto", "compact")),
                (tr("Hide", self.lang), ("hide", row.get("detail", {}).get(range_id, "full"))),
            ]
            current = (row[range_id], row.get("detail", {}).get(range_id, "full"))
        else:
            choices = [
                (tr("Show", self.lang), ("show", None)),
                (tr("Auto", self.lang), ("auto", None)),
                (tr("Hide", self.lang), ("hide", None)),
            ]
            current = (row[range_id], None)
        group = RuleButtonGroup(choices)
        matched = False
        for i in range(group.count()):
            if group.itemData(i) == current:
                group.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            group.setCurrentIndex(0)
        if not item.configurable:
            group.setEnabled(False)
            group.setToolTip(tr(
                "Locked: this access control keeps the top bar recoverable.",
                self.lang))
        return group

    def _rebuild_table(self):
        self._range_boxes.clear()
        self._priority_boxes.clear()
        self.table.setRowCount(len(TOPBAR_ITEMS))
        for row_index, item in enumerate(TOPBAR_ITEMS):
            row = self._config["items"][item.token]
            label = tr(item.label, self.lang)
            group = tr(item.group, self.lang)
            cell = QTableWidgetItem(f"{label}  [{group}]")
            cell.setData(Qt.ItemDataRole.UserRole, item.token)
            if not item.configurable:
                cell.setToolTip(tr(
                    "Locked: this access control keeps the top bar recoverable.",
                    self.lang))
            self.table.setItem(row_index, 0, cell)
            for col, rid in enumerate(RANGE_IDS, 1):
                combo = self._rule_combo(item, rid, row)
                self.table.setCellWidget(row_index, col, combo)
                self._range_boxes[(item.token, rid)] = combo
            priority = QSpinBox()
            priority.setRange(0, 1000)
            priority.setValue(int(row["priority"]))
            priority.setEnabled(item.configurable)
            priority.setToolTip(tr(
                "Higher priority survives longer when Auto items do not fit.",
                self.lang))
            self.table.setCellWidget(row_index, 5, priority)
            self._priority_boxes[item.token] = priority
        self.table.setColumnHidden(
            5, not getattr(self, "cb_show_priority", None)
            or not self.cb_show_priority.isChecked())
        if hasattr(self, "in_filter"):
            self._filter_items()
        self._update_headers()

    def _toggle_priority_column(self, checked):
        self.table.setColumnHidden(5, not checked)

    def _filter_items(self):
        query = self.in_filter.text().strip().lower() if hasattr(self, "in_filter") else ""
        selected_cat = self.combo_category.currentData() if hasattr(self, "combo_category") else None
        for row_index, item in enumerate(TOPBAR_ITEMS):
            matches_query = True
            if query:
                item_label = tr(item.label, self.lang).lower()
                group_label = tr(item.group, self.lang).lower()
                matches_query = (query in item_label
                                 or query in group_label
                                 or query in item.token.lower())
            matches_cat = True
            if selected_cat is not None:
                matches_cat = (item.group == selected_cat)
            self.table.setRowHidden(row_index, not (matches_query and matches_cat))

    def _set_item_combo(self, token, rid, rule, detail=None):
        combo = self._range_boxes.get((token, rid))
        if combo is None or not combo.isEnabled():
            return
        for i in range(combo.count()):
            data = combo.itemData(i)
            if detail is not None:
                if data == (rule, detail):
                    combo.setCurrentIndex(i)
                    return
            else:
                if data[0] == rule:
                    combo.setCurrentIndex(i)
                    return

    def _preset_picked(self, index):
        preset_id = self.combo_preset.currentData()
        if not preset_id:
            return
        if preset_id == "balanced":
            defaults = default_topbar_visibility()
            for item in TOPBAR_ITEMS:
                if not item.configurable:
                    continue
                for rid in RANGE_IDS:
                    target_rule = defaults["items"][item.token][rid]
                    detail = defaults["items"][item.token].get("detail", {}).get(rid, "full") if item.compact else None
                    self._set_item_combo(item.token, rid, target_rule, detail)
        elif preset_id == "minimal":
            for item in TOPBAR_ITEMS:
                if not item.configurable:
                    continue
                for rid in RANGE_IDS:
                    if rid == "wide":
                        rule = "show"
                    elif rid == "medium":
                        rule = "show" if item.group in ("Status", "Projects") else "hide" if item.group == "Formatting" else "auto"
                    else:
                        rule = "show" if item.token in ("btn_new", "btn_save") else "auto" if item.group == "Status" else "hide"
                    self._set_item_combo(item.token, rid, rule)
        elif preset_id == "status_focus":
            for item in TOPBAR_ITEMS:
                if not item.configurable:
                    continue
                for rid in RANGE_IDS:
                    if item.group == "Status":
                        rule = "show" if rid != "ultra" else "auto"
                    elif item.token in ("btn_new", "btn_save"):
                        rule = "show"
                    else:
                        rule = "auto" if rid == "wide" else "hide"
                    self._set_item_combo(item.token, rid, rule)
        elif preset_id == "show_all":
            for item in TOPBAR_ITEMS:
                if not item.configurable:
                    continue
                for rid in RANGE_IDS:
                    self._set_item_combo(item.token, rid, "show")
        self.combo_preset.blockSignals(True)
        self.combo_preset.setCurrentIndex(0)
        self.combo_preset.blockSignals(False)

    def _read_table(self):
        for item in TOPBAR_ITEMS:
            row = self._config["items"][item.token]
            for rid in RANGE_IDS:
                rule, detail = self._range_boxes[(item.token, rid)].currentData()
                row[rid] = rule
                if item.compact and detail:
                    row.setdefault("detail", {})[rid] = detail
            row["priority"] = self._priority_boxes[item.token].value()

    def _breakpoints_changed(self):
        narrow = self.spin_narrow.value()
        medium = max(narrow + 1, self.spin_medium.value())
        wide = max(medium + 1, self.spin_wide.value())
        self.spin_medium.blockSignals(True)
        self.spin_wide.blockSignals(True)
        self.spin_medium.setValue(medium)
        self.spin_wide.setValue(wide)
        self.spin_medium.blockSignals(False)
        self.spin_wide.blockSignals(False)
        self._config["breakpoints"] = [
            {"id": "ultra", "min": 0, "max": narrow - 1},
            {"id": "narrow", "min": narrow, "max": medium - 1},
            {"id": "medium", "min": medium, "max": wide - 1},
            {"id": "wide", "min": wide, "max": None},
        ]
        self._update_width_preview()

    def _active_range(self):
        return range_for_width(self._config, self.main_win._topbar_effective_width())

    def _update_headers(self):
        active = self._active_range()
        headers = [tr("Item", self.lang)]
        for rid in RANGE_IDS:
            marker = "★ " if rid == active else ""
            headers.append(marker + self._tr_range(rid))
        headers.append(tr("Priority", self.lang))
        self.table.setHorizontalHeaderLabels(headers)
        header_item = self.table.horizontalHeaderItem(0)
        if header_item:
            header_item.setToolTip(tr("Toolbar button or widget name", self.lang))
        wide_item = self.table.horizontalHeaderItem(1)
        if wide_item:
            wide_item.setToolTip(f"{tr('Wide screens', self.lang)} (>= {self.spin_wide.value()} px)")
        med_item = self.table.horizontalHeaderItem(2)
        if med_item:
            med_item.setToolTip(f"{tr('Medium screens', self.lang)} ({self.spin_medium.value()}–{self.spin_wide.value() - 1} px)")
        nar_item = self.table.horizontalHeaderItem(3)
        if nar_item:
            nar_item.setToolTip(f"{tr('Narrow screens', self.lang)} ({self.spin_narrow.value()}–{self.spin_medium.value() - 1} px)")
        ult_item = self.table.horizontalHeaderItem(4)
        if ult_item:
            ult_item.setToolTip(f"{tr('Ultra-narrow screens', self.lang)} (< {self.spin_narrow.value()} px)")
        prio_item = self.table.horizontalHeaderItem(5)
        if prio_item:
            prio_item.setToolTip(tr("Higher priority survives longer when space is constrained", self.lang))

    def _update_width_preview(self):
        raw = self.main_win.width()
        effective = int(round(self.main_win._topbar_effective_width()))
        active = range_for_width(self._config, effective)
        self.lbl_window_width.setText(
            f"{tr('Current window width', self.lang)}: {raw} px")
        self.lbl_effective_width.setText(
            f"{tr('Effective toolbar width', self.lang)}: {effective} px")
        self.lbl_active_range.setText(
            f"{tr('Active range', self.lang)}: {self._tr_range(active)}")
        self._update_headers()

    def _set_active_range(self, rule):
        rid = self._active_range()
        for row_index, item in enumerate(TOPBAR_ITEMS):
            if not item.configurable:
                continue
            if self.table.isRowHidden(row_index):
                continue
            combo = self._range_boxes[(item.token, rid)]
            for index in range(combo.count()):
                if combo.itemData(index)[0] == rule:
                    combo.setCurrentIndex(index)
                    break

    def _copy_wide_to_medium(self):
        for row_index, item in enumerate(TOPBAR_ITEMS):
            if not item.configurable or self.table.isRowHidden(row_index):
                continue
            source = self._range_boxes[(item.token, "wide")].currentData()
            target = self._range_boxes[(item.token, "medium")]
            for i in range(target.count()):
                if target.itemData(i) == source:
                    target.setCurrentIndex(i)
                    break

    def _restore_defaults(self):
        self._config = default_topbar_visibility()
        starts = {e["id"]: e["min"] for e in self._config["breakpoints"]}
        for spin, rid in ((self.spin_narrow, "narrow"),
                          (self.spin_medium, "medium"),
                          (self.spin_wide, "wide")):
            spin.blockSignals(True)
            spin.setValue(starts[rid])
            spin.blockSignals(False)
        if hasattr(self, "in_filter"):
            self.in_filter.clear()
        if hasattr(self, "combo_category"):
            self.combo_category.setCurrentIndex(0)
        if hasattr(self, "combo_preset"):
            self.combo_preset.blockSignals(True)
            self.combo_preset.setCurrentIndex(0)
            self.combo_preset.blockSignals(False)
        if hasattr(self, "cb_show_priority"):
            self.cb_show_priority.setChecked(False)
        self._rebuild_table()
        self._update_width_preview()

    def apply_changes(self):
        self._read_table()
        self._breakpoints_changed()
        self._config = normalize_topbar_visibility(self._config)
        self.main_win.data["topbar_visibility"] = copy.deepcopy(self._config)
        self.main_win.mark_dirty()
        self.main_win._apply_header_density()

    def _accept(self):
        self.apply_changes()
        self.accept()
