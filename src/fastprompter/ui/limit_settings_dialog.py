"""Dedicated settings window for AI quota gauges, sources, and alerts."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core.usage_limits.cli_tools import (
    INSTALLERS,
    install_status,
    launch_installer,
)
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    MONTHLY,
    WEEKLY,
    account_has_usage,
    account_usable_now,
    base_key,
)
from fastprompter.core.usage_limits.notifications import (
    normalized_rule,
    notification_key,
)
from fastprompter.ui.limit_account_selector import (
    LimitAccountSelector,
    account_display_name,
    hidden_account_keys,
)
from fastprompter.ui.limit_colors import (
    ROLES,
    resolve_hex,
)
from fastprompter.ui.limit_colors import (
    SETTING_KEY as COLOR_SETTING_KEY,
)
from fastprompter.ui.limit_colors import (
    overrides as color_overrides,
)
from fastprompter.ui.limit_overview import LimitOverview


def _request_limit_sound(manager, kind, key, ref, volume, *, preview=False):
    """One attributable AI-limit request through the existing sound owner."""
    from fastprompter.core.logging import logger
    from fastprompter.core.sound_manager import get_sound_file_for_event

    resolved_ref = ref[len("file:"):] if str(ref).startswith("file:") else None
    sounds_dir = getattr(manager, "_sounds_dir", None)
    if resolved_ref is None and sounds_dir:
        try:
            resolved_ref = get_sound_file_for_event(ref, manager._data, sounds_dir)
        except Exception:
            resolved_ref = None
    outcome = "ERROR"
    try:
        result = (manager.preview_sound_ref(ref, volume) if preview
                  else manager.play_sound_ref(ref, volume))
        outcome = "REQUEST_ACCEPTED" if result else "NOT_STARTED"
        return result
    finally:
        # One line per alert/Test request, never per UI refresh. The existing
        # SoundManager diagnostic ring carries the transport outcome when a
        # request reached it; this line also covers missing refs and errors.
        logger.info(
            "ai_limit_audio domain=%s rule_key=%s stored_ref=%r "
            "resolved_ref=%r volume=%r playback_outcome=%s",
            kind, key, ref, resolved_ref, volume, outcome,
        )


def _window_name(window) -> str:
    """Human window name, prefixed by its quota pool when there is one.

    An account with several independent pools (Antigravity bills Gemini models
    and Claude/GPT models separately) reports two windows that are both "7
    days"; without the pool name the alert sections would be indistinguishable.
    """
    key = base_key(window.key)
    pool = getattr(window, "group_label", "") or ""
    prefix = f"{pool} · " if pool else ""
    if key == FIVE_HOUR:
        return f"{prefix}5 hours"
    if key == WEEKLY:
        return f"{prefix}7 days"
    if key == MONTHLY:
        return f"{prefix}30 days"
    if key == "spend_limit":
        return f"{prefix}spend limit"
    if key == "quota":
        return f"{prefix}quota"
    mins = window.duration_minutes
    if isinstance(mins, (int, float)) and mins > 0:
        if mins < 1440:
            return f"{prefix}{int(mins / 60)} hours"
        return f"{prefix}{int(mins / 1440)} days"
    return f"{prefix}{key}"


def _desktop_window_name(key: str) -> str:
    """Window label from a bare key (no UsageWindow to read a duration from)."""
    return {FIVE_HOUR: "5h", WEEKLY: "7d", MONTHLY: "30d",
            "spend_limit": "spend", "quota": "quota"}.get(base_key(key),
                                                          base_key(key))


class LimitSettingsDialog(QDialog):
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win
        self.data = main_win.data
        self.service = main_win.limit_service
        self._suppress_preview = True
        self.setWindowTitle("AI Limit Settings")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(560, 360)

        saved_geom = self.data.get("limit_settings_geometry") if isinstance(self.data, dict) else None
        restored = False
        if saved_geom and isinstance(saved_geom, str):
            try:
                restored = bool(self.restoreGeometry(bytes.fromhex(saved_geom)))
            except Exception:
                restored = False
        if not restored:
            self.resize(740, 520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(3)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self._build_overview_tab()
        self._build_gauges_tab()
        self._build_alerts_tab()
        self._build_colors_tab()
        self._build_sources_tab()

        # Unified bottom action bar: refresh, banked reset activation, status, and Close
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 2, 14, 2)
        bottom_bar.setSpacing(6)

        self.btn_refresh = QPushButton("Refresh limits now")
        self.btn_refresh.setToolTip("Probe every account again (same as a sweep)")
        self.btn_refresh.clicked.connect(self._refresh_now)
        bottom_bar.addWidget(self.btn_refresh)

        self.btn_activate_reset = QPushButton("Activate reset")
        self.btn_activate_reset.setToolTip("Consume 1 banked reset credit to refill quota")
        self.btn_activate_reset.clicked.connect(self._activate_first_banked_reset)
        self.btn_activate_reset.hide()
        bottom_bar.addWidget(self.btn_activate_reset)

        self.lbl_overview_status = QLabel("")
        self._hint_style(self.lbl_overview_status)
        bottom_bar.addWidget(self.lbl_overview_status)

        self.lbl_hidden_banked = QLabel("")
        self.lbl_hidden_banked.setStyleSheet(
            "color: #4FB6A8; font-size: 10px; font-weight: bold;")
        self.lbl_hidden_banked.setWordWrap(True)
        self.lbl_hidden_banked.hide()
        bottom_bar.addWidget(self.lbl_hidden_banked)

        bottom_bar.addStretch(1)

        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(70)
        self.btn_close.clicked.connect(self.reject)
        bottom_bar.addWidget(self.btn_close)

        outer.addLayout(bottom_bar)
        self._refresh_overview_status()

        # A manual/automatic sweep can discover a plan-specific window (for
        # example Codex Free monthly). Rebuild alert rows on the GUI thread.
        main_win.limit_gauges._result_ready.connect(self._limits_updated)
        # Periodic sync timer to keep reset countdowns, status, and overview live
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(1000)
        self._sync_timer.timeout.connect(self._tick_sync)
        self._sync_timer.start()
        # Combos are populated above; arm live preview only once that is done,
        # so a rebuild's programmatic setCurrentIndex never plays a sound.
        self._suppress_preview = False

    def _preview_sound(self, ref, volume):
        """Hear a sound as you browse it in the rule combos."""
        if self._suppress_preview:
            return
        try:
            self.main_win.sound_manager.preview_sound_ref(ref, volume)
        except Exception:
            pass

    def _rule_volume(self, key, reset=False):
        """Live volume of a rule — read at fire time so preview honours it."""
        try:
            rule = normalized_rule(self._rules().get(key))
            return rule["reset_volume" if reset else "volume"]
        except Exception:
            return 1.0

    def _tick_sync(self):
        overview = getattr(self, "overview", None)
        if overview is not None and overview.isVisible():
            overview.update()
        self._refresh_overview_status()

    def _limits_updated(self):
        self.account_selector.sync()
        self._rebuild_alert_rows()
        self._refresh_claude_status()
        self._refresh_antigravity_status()
        self._refresh_zcode_status()
        self._refresh_freebuff_status()
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.refresh()
        self._refresh_overview_status()
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("Refresh limits now")

    def _save_geometry(self):
        try:
            if isinstance(self.data, dict):
                self.data["limit_settings_geometry"] = bytes(self.saveGeometry()).hex()
                self._commit()
        except Exception:
            pass

    def done(self, r):
        if hasattr(self, "_sync_timer"):
            self._sync_timer.stop()
        try:
            self.main_win.limit_gauges._result_ready.disconnect(self._limits_updated)
        except Exception:
            pass
        self._save_geometry()
        super().done(r)

    def closeEvent(self, event):
        if hasattr(self, "_sync_timer"):
            self._sync_timer.stop()
        try:
            self.main_win.limit_gauges._result_ready.disconnect(self._limits_updated)
        except Exception:
            pass
        self._save_geometry()
        super().closeEvent(event)

    def _commit(self):
        mark = getattr(self.main_win, "mark_dirty", None)
        if callable(mark):
            mark("settings")

    def _hint_style(self, label):
        """Small caption colour — one settable role, not four hex constants."""
        if label is None:
            return
        label.setStyleSheet(f"color: {resolve_hex(self.main_win, 'hint')}; "
                            "font-size: 10px;")

    # -- overview --------------------------------------------------------
    def _build_overview_tab(self):
        """Full-size horizontal bars: every vendor, every window, one screen.

        The header gauge is deliberately 3 px wide; this is where the same
        facts get room to be read as numbers instead of glanced at.
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        from fastprompter.ui.flow_layout import FlowLayout
        fill_row = FlowLayout(h_spacing=8, v_spacing=4)
        fill_row.setContentsMargins(0, 0, 0, 0)
        fill_row.setSpacing(6)
        fill_row.addWidget(QLabel("Bars show"))
        self.cmb_fill = QComboBox()
        self.cmb_fill.addItem("Remaining left (drains like fuel)", "remaining")
        self.cmb_fill.addItem("Used up (grows like progress)", "used")
        fill_index = self.cmb_fill.findData(
            str(self.data.get("limit_gauges_fill", "remaining")))
        self.cmb_fill.setCurrentIndex(max(0, fill_index))
        self.cmb_fill.setToolTip(
            "Remaining: a full bar means quota is available, the bar empties "
            "as you spend it, and the caption reads \"24% left\".\n"
            "Used: an empty bar means nothing is spent, the bar fills up, and "
            "the same window reads \"76% used\".\n"
            "Applies to these bars, their captions, and the header gauge.")
        self.cmb_fill.currentIndexChanged.connect(self._set_fill_mode)
        fill_row.addWidget(self.cmb_fill)
        self.cb_overview_hide_zero = QCheckBox("Hide 0% usage accounts")
        self.cb_overview_hide_zero.setChecked(
            self.data.get("limit_gauges_hide_zero_usage", "False") == "True")
        self.cb_overview_hide_zero.setToolTip(
            "Completely hide accounts that have 0% usage across both 5h and weekly windows.\n"
            "They will appear only when they actually have usage (> 0%).")
        self.cb_overview_hide_zero.toggled.connect(self._set_hide_zero_usage)
        fill_row.addWidget(self.cb_overview_hide_zero)
        self.cb_overview_hide_unusable = QCheckBox(
            "Only available 5h windows")
        self.cb_overview_hide_unusable.setChecked(
            self.data.get("limit_gauges_hide_unusable_5h", "False") == "True")
        self.cb_overview_hide_unusable.setToolTip(
            "Hide accounts whose 5-hour window is exhausted, even when the "
            "weekly pool still has quota — they cannot do work right now.\n"
            "For Antigravity: a quota pool whose windows are all spent is "
            "hidden; only pools that still have quota are shown.")
        self.cb_overview_hide_unusable.toggled.connect(
            self._set_hide_unusable_5h)
        fill_row.addWidget(self.cb_overview_hide_unusable)
        intro = QLabel(
            "Gold healthy, olive < 50%, red < 20%. Numbers reported by providers.")
        self._hint_style(intro)
        fill_row.addWidget(intro)
        lay.addLayout(fill_row)

        self.overview_scroll = QScrollArea()
        self.overview_scroll.setWidgetResizable(True)
        self.overview = LimitOverview(self.main_win, self.service)
        self.overview_scroll.setWidget(self.overview)
        lay.addWidget(self.overview_scroll, 1)

        # Onboarding / auto-connect card (shown when 0 accounts discovered)
        self.card_onboarding = QFrame()
        self.card_onboarding.setFrameShape(QFrame.Shape.StyledPanel)
        card_lay = QVBoxLayout(self.card_onboarding)
        card_lay.setContentsMargins(10, 8, 10, 8)
        card_lay.setSpacing(4)

        title_lbl = QLabel("Connect AI Limit Metrics")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        card_lay.addWidget(title_lbl)

        desc_lbl = QLabel(
            "FastPrompter monitors live quota and reset countdowns for Codex (OpenAI), "
            "Claude Code, Antigravity (Google), and ZCode (GLM Coding Plan). "
            "Click below to automatically diagnose, repair, and connect your AI limits."
        )
        desc_lbl.setWordWrap(True)
        self._hint_style(desc_lbl)
        card_lay.addWidget(desc_lbl)

        btn_row = QHBoxLayout()
        self.btn_auto_connect = QPushButton("⚡ Auto-Detect & Connect All AI Limits")
        self.btn_auto_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_connect.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 4px 10px; }"
        )
        self.btn_auto_connect.clicked.connect(self._run_auto_troubleshoot)
        btn_row.addWidget(self.btn_auto_connect)

        self.btn_open_sources = QPushButton("Configure Sources…")
        self.btn_open_sources.clicked.connect(
            lambda: self.tabs.setCurrentIndex(
                self.tabs.indexOf(getattr(self, "sources_page", None))
                if hasattr(self, "sources_page") else (self.tabs.count() - 1)
            )
        )
        btn_row.addWidget(self.btn_open_sources)
        btn_row.addStretch(1)
        card_lay.addLayout(btn_row)

        self.lbl_onboarding_status = QLabel("")
        self.lbl_onboarding_status.setWordWrap(True)
        self._hint_style(self.lbl_onboarding_status)
        card_lay.addWidget(self.lbl_onboarding_status)

        lay.addWidget(self.card_onboarding)

        self.tabs.addTab(page, "Limits")

    def _activate_first_banked_reset(self):
        snap = self.service.state_copy
        for a in snap.accounts:
            s = snap.snapshots.get(a.key)
            if s and getattr(s, "banked_resets", 0):
                overview = getattr(self, "overview", None)
                if overview is not None:
                    overview._prompt_activate_reset(s)
                return

    def _set_fill_mode(self, _index):
        """One setting for both the overview bars and the header gauge."""
        self.data["limit_gauges_fill"] = self.cmb_fill.currentData()
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.update()
        self.main_win.limit_gauges.refresh_view()
        self._commit()

    def _update_onboarding_status(self):
        label = getattr(self, "lbl_onboarding_status", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.troubleshooter import diagnose_all
            diag = diagnose_all(self.data)
            parts = []
            for k in ("codex", "claude", "antigravity", "zcode"):
                rep = diag.get(k, {})
                parts.append(f"{rep.get('title', k)}: {rep.get('summary', 'unknown')}")
            label.setText("Detection scan:\n• " + "\n• ".join(parts))
        except Exception:
            pass

    def _refresh_overview_status(self):
        label = getattr(self, "lbl_overview_status", None)
        if label is None:
            return
        snap = self.service.state_copy
        total = len(snap.accounts)
        ok = sum(1 for s in snap.snapshots.values()
                 if getattr(s, "status", None) == "OK")
        stale = sum(1 for s in snap.snapshots.values()
                    if getattr(s, "status", None) == "STALE")
        banked_total = sum(getattr(s, "banked_resets", 0) or 0
                           for s in snap.snapshots.values())
        btn = getattr(self, "btn_activate_reset", None)
        if btn is not None:
            if banked_total > 0:
                res_suffix = "s" if banked_total != 1 else ""
                btn.setText(f"Activate reset ({banked_total} banked reset{res_suffix})")
                btn.show()
            else:
                btn.hide()
        if not total:
            if hasattr(self, "card_onboarding"):
                self.card_onboarding.show()
                self._update_onboarding_status()
            if hasattr(self, "overview_scroll"):
                self.overview_scroll.hide()
            label.setText("no accounts discovered · click Auto-Detect above")
            return
        else:
            if hasattr(self, "card_onboarding"):
                self.card_onboarding.hide()
            if hasattr(self, "overview_scroll"):
                self.overview_scroll.show()
        parts = [f"{ok}/{total} accounts reporting"]
        if stale:
            parts.append(f"{stale} stale")
        if snap.status in ("PROBING", "DISCOVERING"):
            parts.append(snap.status.lower())
        label.setText(" · ".join(parts))

        # Surface hidden accounts that have banked resets available
        hb_label = getattr(self, "lbl_hidden_banked", None)
        if hb_label is not None:
            hidden_keys = hidden_account_keys(self.data)
            hide_zero = str(self.data.get(
                "limit_gauges_hide_zero_usage", "False")) == "True"
            hide_unusable = str(self.data.get(
                "limit_gauges_hide_unusable_5h", "False")) == "True"
            hidden_banked: list[str] = []
            for a in snap.accounts:
                is_hidden = a.key in hidden_keys
                if not is_hidden and hide_zero:
                    is_hidden = not account_has_usage(
                        snap.snapshots.get(a.key))
                if not is_hidden and hide_unusable:
                    is_hidden = not account_usable_now(
                        snap.snapshots.get(a.key))
                if not is_hidden:
                    continue
                s = snap.snapshots.get(a.key)
                br = getattr(s, "banked_resets", 0) or 0
                if br > 0:
                    name = account_display_name(a, self.data)
                    res_w = "reset" if br == 1 else "resets"
                    hidden_banked.append(f"{name} ({br} banked {res_w})")
            if hidden_banked:
                hb_label.setText(
                    "⚠ Hidden: " + ", ".join(hidden_banked)
                    + " — unhide or activate")
                hb_label.show()
            else:
                hb_label.hide()

    # -- gauges/accounts -------------------------------------------------
    def _build_gauges_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        options_v = QVBoxLayout()
        options_v.setSpacing(3)

        row1 = QHBoxLayout()
        self.cb_enabled = QCheckBox("Show AI limit gauges in the header")
        self.cb_enabled.setChecked(
            self.data.get("limit_gauges", "False") == "True")
        self.cb_enabled.toggled.connect(self._set_master_enabled)
        row1.addWidget(self.cb_enabled)
        row1.addStretch(1)
        options_v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("Style"))
        self.cmb_style = QComboBox()
        self.cmb_style.addItem("Bars", "bars")
        self.cmb_style.addItem("Dots", "dots")
        self.cmb_style.addItem("Stacked", "stack")
        self.cmb_style.setToolTip(
            "Bars: one thin vertical bar per quota window, side by side.\n"
            "Dots: the same windows as pie-filled dots.\n"
            "Stacked: one horizontal bar per window, stacked bottom-up in a "
            "single column (up to 4 tall), so an account takes one bar of "
            "width however many windows it reports.")
        index = self.cmb_style.findData(
            str(self.data.get("limit_gauges_style", "bars")))
        self.cmb_style.setCurrentIndex(max(0, index))
        self.cmb_style.currentIndexChanged.connect(self._set_style)
        row2.addWidget(self.cmb_style)

        self.cb_vendor_tint = QCheckBox("Vendor tint")
        self.cb_vendor_tint.setChecked(
            self.data.get("limit_gauges_vendor_tint", "True") == "True")
        self.cb_vendor_tint.setToolTip(
            "Nudge each bar towards its vendor's own colour — the same hue the "
            "reset countdown uses (Claude terracotta, Codex blue, Antigravity "
            "violet), muted so the quota level still reads first.")
        self.cb_vendor_tint.toggled.connect(self._set_vendor_tint)
        row2.addWidget(self.cb_vendor_tint)

        self.cb_labels = QCheckBox("Show account badges in header")
        self.cb_labels.setChecked(
            self.data.get("limit_gauges_show_labels", "False") == "True")
        self.cb_labels.setToolTip(
            "Badges still disappear automatically in ultra-narrow windows")
        self.cb_labels.toggled.connect(self._set_show_labels)
        row2.addWidget(self.cb_labels)
        row2.addStretch(1)
        options_v.addLayout(row2)

        row3 = QHBoxLayout()
        self.cb_hide_zero = QCheckBox(
            "Hide accounts with 0% usage (5h & weekly)")
        self.cb_hide_zero.setChecked(
            self.data.get("limit_gauges_hide_zero_usage", "False") == "True")
        self.cb_hide_zero.setToolTip(
            "Completely hide accounts that have 0% usage across both 5h and weekly windows.\n"
            "They will appear only when they actually have usage (> 0%).")
        self.cb_hide_zero.toggled.connect(self._set_hide_zero_usage)
        row3.addWidget(self.cb_hide_zero)
        row3.addStretch(1)
        options_v.addLayout(row3)

        row3b = QHBoxLayout()
        self.cb_hide_unusable = QCheckBox(
            "Only available 5h windows")
        self.cb_hide_unusable.setChecked(
            self.data.get("limit_gauges_hide_unusable_5h", "False") == "True")
        self.cb_hide_unusable.setToolTip(
            "Hide accounts whose 5-hour window is exhausted, even when the "
            "weekly pool still has quota — they cannot do work right now.\n"
            "For Antigravity: a quota pool whose windows are all spent is "
            "hidden; only pools that still have quota are shown.")
        self.cb_hide_unusable.toggled.connect(self._set_hide_unusable_5h)
        row3b.addWidget(self.cb_hide_unusable)
        row3b.addStretch(1)
        options_v.addLayout(row3b)
        lay.addLayout(options_v)

        help_label = QLabel(
            "Choose accounts, give them optional names, and edit the short "
            "header badge. An empty Header field hides only that account's "
            "badge; the quota marks remain visible.")
        help_label.setWordWrap(True)
        lay.addWidget(help_label)
        self.account_selector = LimitAccountSelector(
            self.main_win, self.service)
        lay.addWidget(self.account_selector)
        lay.addStretch(1)
        self.tabs.addTab(page, "Gauges & accounts")

    def _set_master_enabled(self, checked):
        self.data["limit_gauges"] = "True" if checked else "False"
        master = getattr(self.main_win, "cb_limit_gauges", None)
        if master is not None and master.isChecked() != checked:
            master.blockSignals(True)
            master.setChecked(checked)
            master.blockSignals(False)
        self.main_win.limit_gauges.sync()
        self._commit()

    def _set_style(self, _index):
        self.data["limit_gauges_style"] = self.cmb_style.currentData()
        self.main_win.limit_gauges.refresh_view()
        self._commit()

    def _set_vendor_tint(self, checked):
        self.data["limit_gauges_vendor_tint"] = "True" if checked else "False"
        self.main_win.limit_gauges.refresh_view()
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.update()
        self._commit()

    def _set_show_labels(self, checked):
        self.data["limit_gauges_show_labels"] = "True" if checked else "False"
        self.main_win.limit_gauges.refresh_view()
        self._commit()

    def _set_hide_zero_usage(self, checked):
        val = "True" if checked else "False"
        self.data["limit_gauges_hide_zero_usage"] = val
        if hasattr(self, "cb_hide_zero") and self.cb_hide_zero.isChecked() != bool(checked):
            self.cb_hide_zero.blockSignals(True)
            self.cb_hide_zero.setChecked(bool(checked))
            self.cb_hide_zero.blockSignals(False)
        if hasattr(self, "cb_overview_hide_zero") and self.cb_overview_hide_zero.isChecked() != bool(checked):
            self.cb_overview_hide_zero.blockSignals(True)
            self.cb_overview_hide_zero.setChecked(bool(checked))
            self.cb_overview_hide_zero.blockSignals(False)
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.refresh()
        self.main_win.limit_gauges.refresh_view()
        if hasattr(self, "account_selector"):
            self.account_selector.sync()
        if hasattr(self.main_win, "_update_limit_timer_label"):
            self.main_win._update_limit_timer_label()
        self._refresh_overview_status()
        self._commit()

    def _set_hide_unusable_5h(self, checked):
        """Show only accounts whose 5h window is currently available.

        One toggle for both surfaces (overview bars and header gauge), the
        same way the 0%-usage rule is shared. Also drops the windows of an
        Antigravity quota pool in which every window is spent — those cannot
        do work right now either.
        """
        val = "True" if checked else "False"
        self.data["limit_gauges_hide_unusable_5h"] = val
        if hasattr(self, "cb_hide_unusable") and self.cb_hide_unusable.isChecked() != bool(checked):
            self.cb_hide_unusable.blockSignals(True)
            self.cb_hide_unusable.setChecked(bool(checked))
            self.cb_hide_unusable.blockSignals(False)
        if hasattr(self, "cb_overview_hide_unusable") and self.cb_overview_hide_unusable.isChecked() != bool(checked):
            self.cb_overview_hide_unusable.blockSignals(True)
            self.cb_overview_hide_unusable.setChecked(bool(checked))
            self.cb_overview_hide_unusable.blockSignals(False)
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.refresh()
        self.main_win.limit_gauges.refresh_view()
        if hasattr(self, "account_selector"):
            self.account_selector.sync()
        if hasattr(self.main_win, "_update_limit_timer_label"):
            self.main_win._update_limit_timer_label()
        self._refresh_overview_status()
        self._commit()

    # -- notifications ---------------------------------------------------
    def _build_alerts_tab(self):
        self.alert_page = QWidget()
        page_lay = QVBoxLayout(self.alert_page)
        page_lay.setContentsMargins(2, 2, 2, 2)
        page_lay.setSpacing(3)
        intro = QLabel(
            "Per account/window: threshold, popup, sound and volume. An "
            "alert fires once per reset window and re-arms when quota "
            "rises above its threshold.")
        intro.setWordWrap(True)
        page_lay.addWidget(intro)

        # --- Notification Appearance & Behavior Box ---
        notif_box = QGroupBox("Notification appearance")
        notif_box_lay = QGridLayout(notif_box)
        notif_box_lay.setContentsMargins(6, 4, 6, 4)
        notif_box_lay.setHorizontalSpacing(8)
        notif_box_lay.setVerticalSpacing(4)

        # Duration
        notif_box_lay.addWidget(QLabel("Duration:"), 0, 0)
        self.cmb_notif_duration = QComboBox()
        self.cmb_notif_duration.addItem("5 seconds", 5)
        self.cmb_notif_duration.addItem("8 seconds", 8)
        self.cmb_notif_duration.addItem("10 seconds", 10)
        self.cmb_notif_duration.addItem("15 seconds", 15)
        self.cmb_notif_duration.addItem("30 seconds", 30)
        self.cmb_notif_duration.addItem("60 seconds", 60)
        self.cmb_notif_duration.addItem("Until dismissed", 0)
        cur_dur = int(self.data.get("limit_notif_duration_sec", 10))
        dur_idx = self.cmb_notif_duration.findData(cur_dur)
        if dur_idx >= 0:
            self.cmb_notif_duration.setCurrentIndex(dur_idx)
        else:
            self.cmb_notif_duration.addItem(f"{cur_dur} seconds", cur_dur)
            self.cmb_notif_duration.setCurrentIndex(self.cmb_notif_duration.count() - 1)
        self.cmb_notif_duration.currentIndexChanged.connect(self._set_notif_duration)
        notif_box_lay.addWidget(self.cmb_notif_duration, 0, 1)

        # Symbol / Emoji
        notif_box_lay.addWidget(QLabel("Symbol:"), 0, 2)
        self.cmb_notif_symbol = QComboBox()
        self.cmb_notif_symbol.setEditable(True)
        symbol_presets = [
            ("⚡ Lightning", "⚡"),
            ("⚠️ Warning", "⚠️"),
            ("🔔 Bell", "🔔"),
            ("🤖 AI", "🤖"),
            ("⏳ Hourglass", "⏳"),
            ("🚨 Siren", "🚨"),
            ("★ Star", "★"),
            ("↻ Reset", "↻"),
            ("(none)", ""),
        ]
        cur_sym = str(self.data.get("limit_notif_symbol", "⚡"))
        found_sym = False
        for lbl, sym in symbol_presets:
            self.cmb_notif_symbol.addItem(lbl, sym)
            if sym == cur_sym:
                self.cmb_notif_symbol.setCurrentIndex(self.cmb_notif_symbol.count() - 1)
                found_sym = True
        if not found_sym:
            self.cmb_notif_symbol.setEditText(cur_sym)
        self.cmb_notif_symbol.currentTextChanged.connect(self._set_notif_symbol)
        notif_box_lay.addWidget(self.cmb_notif_symbol, 0, 3)

        # Color / Accent
        notif_box_lay.addWidget(QLabel("Color:"), 1, 0)
        color_h = QHBoxLayout()
        color_h.setSpacing(4)
        self.cmb_notif_color = QComboBox()
        color_presets = [
            ("Theme accent", ""),
            ("Golden Yellow", "#D9B340"),
            ("Amber Warning", "#E69500"),
            ("Crimson Red", "#C0392B"),
            ("Emerald Green", "#27AE60"),
            ("Sky Blue", "#2980B9"),
            ("Purple Violet", "#8E44AD"),
        ]
        cur_col = str(self.data.get("limit_notif_color", ""))
        found_col = False
        for lbl, col in color_presets:
            self.cmb_notif_color.addItem(lbl, col)
            if col == cur_col:
                self.cmb_notif_color.setCurrentIndex(self.cmb_notif_color.count() - 1)
                found_col = True
        if not found_col and cur_col:
            self.cmb_notif_color.addItem(f"Custom ({cur_col})", cur_col)
            self.cmb_notif_color.setCurrentIndex(self.cmb_notif_color.count() - 1)
        self.cmb_notif_color.currentIndexChanged.connect(self._set_notif_color)
        color_h.addWidget(self.cmb_notif_color, 1)

        self.btn_pick_notif_color = QPushButton("Pick…")
        self.btn_pick_notif_color.setFixedWidth(52)
        self.btn_pick_notif_color.setToolTip("Pick custom notification accent color")
        self.btn_pick_notif_color.clicked.connect(self._pick_custom_notif_color)
        color_h.addWidget(self.btn_pick_notif_color)
        notif_box_lay.addLayout(color_h, 1, 1)

        # Test popup button
        self.btn_test_notif = QPushButton("Test popup")
        self.btn_test_notif.setToolTip("Show sample notification with current appearance settings")
        self.btn_test_notif.clicked.connect(self._test_notification_appearance)
        notif_box_lay.addWidget(self.btn_test_notif, 1, 2, 1, 2)

        page_lay.addWidget(notif_box)

        # Copy one configured section onto the rest. Configuring five windows
        # by hand is the same eight fields five times, and the sections almost
        # always want to be identical.
        copy_row = QHBoxLayout()
        copy_row.setSpacing(4)
        copy_row.addWidget(QLabel("Copy alert settings from:"))
        self.cmb_copy_from = QComboBox()
        self.cmb_copy_from.setMinimumWidth(230)
        self.cmb_copy_from.setToolTip(
            "The section whose settings are the template")
        copy_row.addWidget(self.cmb_copy_from, 1)
        self.btn_copy_to_all = QPushButton("Apply to all")
        self.btn_copy_to_all.setToolTip(
            "Overwrite every other section with this one, field for field")
        self.btn_copy_to_all.clicked.connect(self._copy_rule_to_all)
        copy_row.addWidget(self.btn_copy_to_all)
        page_lay.addLayout(copy_row)
        self.lbl_copy_hint = QLabel("")
        self.lbl_copy_hint.setWordWrap(True)
        self._hint_style(self.lbl_copy_hint)
        page_lay.addWidget(self.lbl_copy_hint)

        self.alert_scroll = QScrollArea()
        self.alert_scroll.setWidgetResizable(True)
        page_lay.addWidget(self.alert_scroll)
        self.tabs.addTab(self.alert_page, "Notifications")
        self._rebuild_alert_rows()

    def _get_current_notif_duration(self) -> int:
        data = self.cmb_notif_duration.currentData()
        return int(data) if data is not None else 10

    def _get_current_notif_symbol(self) -> str:
        text = self.cmb_notif_symbol.currentText().strip()
        idx = self.cmb_notif_symbol.currentIndex()
        if idx >= 0 and self.cmb_notif_symbol.itemText(idx) == text:
            data = self.cmb_notif_symbol.itemData(idx)
            if data is not None:
                return str(data)
        data_idx = self.cmb_notif_symbol.findData(text)
        if data_idx >= 0:
            return str(self.cmb_notif_symbol.itemData(data_idx))
        if " " in text:
            parts = text.split(" ")
            if len(parts[0]) <= 3:
                return parts[0]
        return text

    def _get_current_notif_color(self) -> str:
        return str(self.cmb_notif_color.currentData() or "")

    def _set_notif_duration(self, _idx):
        dur = self._get_current_notif_duration()
        self.data["limit_notif_duration_sec"] = dur
        self._commit()

    def _set_notif_symbol(self, _text):
        sym = self._get_current_notif_symbol()
        self.data["limit_notif_symbol"] = sym
        self._commit()

    def _set_notif_color(self, _idx):
        col = self._get_current_notif_color()
        self.data["limit_notif_color"] = col
        self._commit()

    def _pick_custom_notif_color(self):
        from PyQt6.QtWidgets import QColorDialog
        cur = self.data.get("limit_notif_color", "") or "#D9B340"
        col = QColorDialog.getColor(QColor(cur), self, "Select Notification Accent Color")
        if col.isValid():
            hex_val = col.name()
            self.data["limit_notif_color"] = hex_val
            idx = self.cmb_notif_color.findData(hex_val)
            if idx < 0:
                self.cmb_notif_color.addItem(f"Custom ({hex_val})", hex_val)
                idx = self.cmb_notif_color.count() - 1
            self.cmb_notif_color.setCurrentIndex(idx)
            self._commit()

    def _test_notification_appearance(self):
        sym = self._get_current_notif_symbol()
        dur = self._get_current_notif_duration()
        col = self._get_current_notif_color()
        self.main_win._show_limit_popup(
            "AI limit test",
            "Sample notification: duration, color, and symbol preview.",
            duration_sec=dur,
            color=col,
            symbol=sym,
        )

    def _account_windows(self, account):
        snap = self.service.state_copy.snapshots.get(account.key)
        windows = list(getattr(snap, "windows", ()) or ())
        windows = [window for window in windows if window.available]
        if windows:
            return windows
        from fastprompter.core.usage_limits.model import UsageWindow
        # An unprobed account still needs alert rows, but they must be the
        # windows that provider CAN report: offering Antigravity a "7 days"
        # rule would create a rule key no sweep ever fills.
        if account.provider_id == "antigravity":
            return [UsageWindow.unavailable("quota")]
        return [
            UsageWindow.unavailable(FIVE_HOUR),
            UsageWindow.unavailable(WEEKLY),
        ]

    def _rebuild_alert_rows(self):
        old = self.alert_scroll.takeWidget() if hasattr(self, "alert_scroll") else None
        if old is not None:
            old.deleteLater()
        self._suppress_preview = True
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        accounts = self.service.state_copy.accounts
        # (label, key) of every rule section on screen, in draw order. Built
        # here because this is the only place that knows what was rendered —
        # the copy controls below must never offer a section that is not there.
        self._alert_sections = []
        if not accounts:
            lay.addWidget(QLabel("No accounts detected. Use Sources → Refresh now."))
        for account in accounts:
            for window in self._account_windows(account):
                self._add_alert_rule(lay, account, window)
        lay.addStretch(1)
        self.alert_scroll.setWidget(host)
        self._suppress_preview = False
        self._refresh_copy_controls()

    # -- copy one section's settings onto others --------------------------
    def _refresh_copy_controls(self):
        """Repopulate the source combo from the sections actually rendered."""
        combo = getattr(self, "cmb_copy_from", None)
        if combo is None:
            return
        sections = getattr(self, "_alert_sections", [])
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, key in sections:
            combo.addItem(label, key)
        if previous is not None:
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)
        enabled = len(sections) > 1
        combo.setEnabled(enabled)
        self.btn_copy_to_all.setEnabled(enabled)
        if not enabled:
            self.lbl_copy_hint.setText(
                "Nothing to copy: fewer than two alert sections exist."
                if not sections else
                "Only one alert section exists — nothing to copy it onto.")
        else:
            self.lbl_copy_hint.setText(
                f"{len(sections)} sections. Copying overwrites every field: "
                "on/off, threshold, popup, sound, volume, and the reset half.")

    def _copy_rule_to_all(self):
        """Make every other section identical to the chosen one.

        Copies the WHOLE rule (both halves, every toggle and volume), because
        "exactly" is the request. The suppression state is reset for each target
        so the copied threshold gets one honest chance to fire against the
        current quota. Any resulting alerts are safely coalesced by
        _check_limit_notifications to prevent sound/toast flooding.
        """
        combo = getattr(self, "cmb_copy_from", None)
        if combo is None:
            return
        source_key = combo.currentData()
        sections = getattr(self, "_alert_sections", [])
        targets = [key for _label, key in sections if key != source_key]
        if not source_key or not targets:
            return
        rules = self._rules()
        template = normalized_rule(rules.get(source_key))
        state = self.data.get("limit_notification_state")
        for key in targets:
            rules[key] = dict(template)
            if isinstance(state, dict):
                state.pop(key, None)
        self.main_win.limit_gauges.sync()
        self._commit()
        self._rebuild_alert_rows()
        source_label = combo.currentText()
        self.lbl_copy_hint.setText(
            f"Copied \"{source_label}\" onto {len(targets)} other section(s).")
        self.main_win._check_limit_notifications()

    def _sound_inventory(self):
        if hasattr(self, "_sound_inventory_cache"):
            return self._sound_inventory_cache
        items = [("Notification event", "notify")]
        try:
            for rel in self.main_win.sound_manager.get_available_sounds() or ():
                items.append((rel, f"file:{rel}"))
        except Exception:
            pass
        self._sound_inventory_cache = items
        return items

    def _rules(self):
        rules = self.data.get("limit_notifications")
        if not isinstance(rules, dict):
            rules = {}
            self.data["limit_notifications"] = rules
        return rules

    def _add_alert_rule(self, parent_lay, account, window):
        key = notification_key(account.key, window.key)
        rule = normalized_rule(self._rules().get(key))
        title = (f"{account_display_name(account, self.data)} — "
                 f"{_window_name(window)}")
        # Registered for the copy controls: same label, same order, same keys.
        self._alert_sections.append((title, key))
        box = QGroupBox(title)
        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(3, 2, 3, 2)
        box_lay.setSpacing(1)
        row = QHBoxLayout()
        row.setSpacing(3)

        enabled = QCheckBox("Alert")
        enabled.setChecked(rule["enabled"] == "True")
        enabled.toggled.connect(
            lambda value, k=key: self._set_rule(k, "enabled", value))
        row.addWidget(enabled)

        row.addWidget(QLabel("Remaining ≤"))
        threshold = QDoubleSpinBox()
        threshold.setRange(0.0, 100.0)
        threshold.setDecimals(1)
        threshold.setSingleStep(5.0)
        threshold.setSuffix(" %")
        threshold.setValue(rule["threshold"])
        threshold.valueChanged.connect(
            lambda value, k=key: self._set_rule(k, "threshold", value))
        row.addWidget(threshold)

        popup = QCheckBox("Popup")
        popup.setChecked(rule["show_notification"] == "True")
        popup.toggled.connect(
            lambda value, k=key: self._set_rule(
                k, "show_notification", value))
        row.addWidget(popup)

        sound_enabled = QCheckBox("Sound")
        sound_enabled.setChecked(rule["sound_enabled"] == "True")
        sound_enabled.toggled.connect(
            lambda value, k=key: self._set_rule(k, "sound_enabled", value))
        row.addWidget(sound_enabled)

        sound = QComboBox()
        sound.setMinimumWidth(170)
        for text, ref in self._sound_inventory():
            sound.addItem(text, ref)
        sound_index = sound.findData(rule["sound"])
        if sound_index < 0:
            sound.addItem(rule["sound"], rule["sound"])
            sound_index = sound.count() - 1
        sound.setCurrentIndex(sound_index)
        sound.currentIndexChanged.connect(
            lambda _i, k=key, combo=sound: self._set_rule(
                k, "sound", combo.currentData()))
        sound.currentIndexChanged.connect(
            lambda _i, k=key, combo=sound: self._preview_sound(
                combo.currentData(), self._rule_volume(k)))
        row.addWidget(sound, 1)

        row.addWidget(QLabel("Vol"))
        volume = QDoubleSpinBox()
        volume.setRange(0.0, 1.0)
        volume.setDecimals(2)
        volume.setSingleStep(0.05)
        volume.setValue(rule["volume"])
        volume.valueChanged.connect(
            lambda value, k=key: self._set_rule(k, "volume", value))
        row.addWidget(volume)

        test = QPushButton("Test")
        test.clicked.connect(
            lambda _checked=False, k=key: self._test_rule(k, "low"))
        row.addWidget(test)
        box_lay.addLayout(row)

        reset_row = QHBoxLayout()
        reset_row.setSpacing(3)
        reset_enabled = QCheckBox("Alert when limit resets — time to work")
        reset_enabled.setChecked(rule["reset_enabled"] == "True")
        reset_enabled.toggled.connect(
            lambda value, k=key: self._set_rule(
                k, "reset_enabled", value))
        reset_row.addWidget(reset_enabled)

        reset_popup = QCheckBox("Popup")
        reset_popup.setChecked(rule["reset_show_notification"] == "True")
        reset_popup.toggled.connect(
            lambda value, k=key: self._set_rule(
                k, "reset_show_notification", value))
        reset_row.addWidget(reset_popup)

        reset_sound_enabled = QCheckBox("Sound")
        reset_sound_enabled.setChecked(rule["reset_sound_enabled"] == "True")
        reset_sound_enabled.toggled.connect(
            lambda value, k=key: self._set_rule(
                k, "reset_sound_enabled", value))
        reset_row.addWidget(reset_sound_enabled)

        reset_sound = QComboBox()
        reset_sound.setMinimumWidth(170)
        for text, ref in self._sound_inventory():
            reset_sound.addItem(text, ref)
        reset_sound_index = reset_sound.findData(rule["reset_sound"])
        if reset_sound_index < 0:
            reset_sound.addItem(rule["reset_sound"], rule["reset_sound"])
            reset_sound_index = reset_sound.count() - 1
        reset_sound.setCurrentIndex(reset_sound_index)
        reset_sound.currentIndexChanged.connect(
            lambda _i, k=key, combo=reset_sound: self._set_rule(
                k, "reset_sound", combo.currentData()))
        reset_sound.currentIndexChanged.connect(
            lambda _i, k=key, combo=reset_sound: self._preview_sound(
                combo.currentData(), self._rule_volume(k, reset=True)))
        reset_row.addWidget(reset_sound, 1)

        reset_row.addWidget(QLabel("Vol"))
        reset_volume = QDoubleSpinBox()
        reset_volume.setRange(0.0, 1.0)
        reset_volume.setDecimals(2)
        reset_volume.setSingleStep(0.05)
        reset_volume.setValue(rule["reset_volume"])
        reset_volume.valueChanged.connect(
            lambda value, k=key: self._set_rule(
                k, "reset_volume", value))
        reset_row.addWidget(reset_volume)

        reset_test = QPushButton("Test reset")
        reset_test.clicked.connect(
            lambda _checked=False, k=key: self._test_rule(k, "reset"))
        reset_row.addWidget(reset_test)
        box_lay.addLayout(reset_row)
        parent_lay.addWidget(box)

    def _set_rule(self, key, field, value):
        rules = self._rules()
        rule = normalized_rule(rules.get(key))
        if field in (
                "enabled", "sound_enabled", "show_notification",
                "reset_enabled", "reset_sound_enabled",
                "reset_show_notification"):
            value = "True" if value else "False"
        rule[field] = value
        rules[key] = normalized_rule(rule)
        # A changed threshold/policy is a new user decision; let it alert once
        # against the current quota instead of being suppressed by old state.
        state = self.data.get("limit_notification_state")
        if isinstance(state, dict) and field in ("enabled", "threshold"):
            entry = state.get(key)
            if isinstance(entry, dict):
                entry.pop("low_alerted", None)
                entry.pop("low_threshold", None)
        self.main_win.limit_gauges.sync()
        self._commit()
        if field in ("enabled", "reset_enabled") and value == "True":
            self.main_win._check_limit_notifications()
            if not self.service.state_copy.snapshots:
                self.service.refresh()

    def _test_rule(self, key, kind="low"):
        rule = normalized_rule(self._rules().get(key))
        prefix = "reset_" if kind == "reset" else ""
        if rule[f"{prefix}sound_enabled"] == "True":
            _request_limit_sound(
                self.main_win.sound_manager, kind, key,
                rule[f"{prefix}sound"], rule[f"{prefix}volume"], preview=True,
            )
        if rule[f"{prefix}show_notification"] == "True":
            message = ("Limit reset — quota is available again. Time to work."
                       if kind == "reset"
                       else "Remaining quota crossed the configured threshold.")
            self.main_win._show_limit_popup(
                "AI limit reset test" if kind == "reset" else "AI limit test",
                message)

    # -- colours ---------------------------------------------------------
    def _build_colors_tab(self):
        """Every colour the AI-limit surfaces paint, one swatch each.

        The gauge, the bars above, the reset countdown and these captions used
        to carry their own hex constants in three source files; this tab is the
        single place that owns them, and a role left untouched still follows the
        active theme rather than a frozen default.
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        intro = QLabel(
            "Colours for every AI-limit surface: the header gauge, the bars on "
            "the Limits tab, the reset countdown and the captions here. A "
            "colour you never touch follows the active theme; \"Reset\" on a "
            "row returns it to that.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self._color_buttons = {}
        for row, role in enumerate(ROLES):
            name = QLabel(role.label)
            name.setToolTip(role.tooltip)
            grid.addWidget(name, row, 0)

            swatch = QPushButton()
            swatch.setFixedWidth(96)
            swatch.setToolTip(role.tooltip)
            swatch.clicked.connect(
                lambda _checked=False, key=role.key: self._pick_color(key))
            grid.addWidget(swatch, row, 1)
            self._color_buttons[role.key] = swatch

            reset = QPushButton("Reset")
            reset.setFixedWidth(52)
            reset.setToolTip("Follow the theme / built-in default again")
            reset.clicked.connect(
                lambda _checked=False, key=role.key: self._reset_color(key))
            grid.addWidget(reset, row, 2)
        grid.setColumnStretch(0, 1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        reset_all = QPushButton("Reset every colour")
        reset_all.setToolTip(
            "Drop all AI-limit colour overrides and follow the theme again")
        reset_all.clicked.connect(self._reset_all_colors)
        row.addWidget(reset_all)
        self.lbl_color_hint = QLabel("")
        self._hint_style(self.lbl_color_hint)
        row.addWidget(self.lbl_color_hint, 1)
        lay.addLayout(row)
        self.tabs.addTab(page, "Colours")
        self._refresh_color_buttons()

    def _refresh_color_buttons(self):
        """Paint each swatch in the colour it currently resolves to."""
        buttons = getattr(self, "_color_buttons", {})
        if not buttons:
            return
        active = color_overrides(self.data)
        for key, button in buttons.items():
            value = resolve_hex(self.main_win, key)
            # Readable label on any swatch: the text follows the colour's own
            # luminance instead of a fixed black or white that vanishes on half
            # the palette.
            ink = "#000000" if QColor(value).lightness() > 140 else "#ffffff"
            button.setStyleSheet(
                f"background-color: {value}; color: {ink}; "
                "border: 1px solid #000000; padding: 1px 2px;")
            button.setText(value + ("" if key in active else " *"))
        hint = getattr(self, "lbl_color_hint", None)
        if hint is not None:
            hint.setText("* follows the active theme")

    def _pick_color(self, key):
        from PyQt6.QtWidgets import QColorDialog
        current = QColor(resolve_hex(self.main_win, key))
        chosen = QColorDialog.getColor(current, self, "Pick Color")
        if not chosen.isValid():
            return
        overrides = dict(color_overrides(self.data))
        overrides[key] = chosen.name()
        self.data[COLOR_SETTING_KEY] = overrides
        self._colors_changed()

    def _reset_color(self, key):
        overrides = dict(color_overrides(self.data))
        if overrides.pop(key, None) is None:
            return
        self.data[COLOR_SETTING_KEY] = overrides
        self._colors_changed()

    def _reset_all_colors(self):
        if not color_overrides(self.data):
            return
        self.data[COLOR_SETTING_KEY] = {}
        self._colors_changed()

    def _colors_changed(self):
        """Repaint every surface that reads the palette, not just this tab."""
        self._refresh_color_buttons()
        self._apply_hint_colors()
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.update()
        gauges = getattr(self.main_win, "limit_gauges", None)
        if gauges is not None:
            gauges.refresh_view()
        timer_label = getattr(self.main_win, "_update_limit_timer_label", None)
        if callable(timer_label):
            timer_label()
        status = getattr(self.main_win, "_apply_limit_hint_style", None)
        if callable(status):
            status(getattr(self.main_win, "lbl_limit_status", None))
        self._commit()

    def _apply_hint_colors(self):
        """Recolour this window's own caption labels."""
        for name in ("lbl_overview_status", "lbl_copy_hint",
                     "lbl_codex_sources", "lbl_claude_sources",
                     "lbl_claude_accounts",
                     "lbl_antigravity_sources", "lbl_zcode_sources",
                     "lbl_troubleshoot_status", "lbl_onboarding_status",
                     "lbl_color_hint"):
            self._hint_style(getattr(self, name, None))

    # -- agent CLIs (the most reliable source) ----------------------------
    def _build_cli_group(self, parent_lay):
        """Install/repair the vendor CLIs, one row each.

        A CLI is the best source there is: it authenticates the way the vendor
        intends and the numbers come from the vendor's own server instead of a
        file whose meaning had to be inferred. Claude's ``/usage`` is the only
        Claude source carrying percentages AND reset times; Antigravity's is the
        only one carrying a percentage at all.

        The command is shown before it runs, and running it is one explicit
        confirmation away — piping a remote script into a shell is never
        something this dialog does on its own.
        """
        box = QGroupBox("Agent CLIs")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(2)
        intro = QLabel(
            "FastPrompter reads quota by asking each vendor's own CLI. Where a "
            "CLI is missing it falls back to whatever that vendor writes to "
            "disk, which is less exact — or, for Antigravity, only its refusals.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self._cli_rows = {}
        for row, tool in enumerate(INSTALLERS):
            name = QLabel(tool.label)
            grid.addWidget(name, row, 0)
            state = QLabel("")
            state.setWordWrap(True)
            self._hint_style(state)
            grid.addWidget(state, row, 1)
            button = QPushButton("")
            button.setFixedWidth(120)
            button.clicked.connect(
                lambda _checked=False, key=tool.key: self._install_cli(key))
            grid.addWidget(button, row, 2)
            self._cli_rows[tool.key] = (state, button)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.lbl_cli_hint = QLabel("")
        self.lbl_cli_hint.setWordWrap(True)
        self._hint_style(self.lbl_cli_hint)
        lay.addWidget(self.lbl_cli_hint)
        parent_lay.addWidget(box)
        self._refresh_cli_rows()

    def _refresh_cli_rows(self):
        rows = getattr(self, "_cli_rows", {})
        for key, (state, button) in rows.items():
            info = install_status(key)
            if info["installed"]:
                state.setText(f"installed · {info['path']}")
                button.setText("Reinstall / update")
            else:
                state.setText(f"not installed · lands in {info['target']}")
                button.setText("Install…")

    def _install_cli(self, key):
        """Ask, then run the vendor's official installer in a console window."""
        info = install_status(key)
        if not info.get("known"):
            return
        verb = "Reinstall" if info["installed"] else "Install"
        answer = QMessageBox.question(
            self, f"{verb} {info['label']}",
            f"{verb} {info['label']} by running the official installer from "
            f"{info['source']}?\n\n"
            f"Command:\n{info['command']}\n\n"
            f"Installs to: {info['target']}\n\n"
            "A console window opens so you can watch it and answer any prompt. "
            "FastPrompter does not modify the command.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            launch_installer(key)
        except Exception as exc:
            QMessageBox.warning(
                self, f"{verb} {info['label']}",
                f"Could not start the installer:\n\n{exc}")
            return
        self.lbl_cli_hint.setText(
            f"{info['label']}: installer started in a separate window. When it "
            "finishes, press \"Refresh accounts and limits now\" — a new CLI is "
            "picked up without restarting FastPrompter.")

    # -- sources ---------------------------------------------------------
    def _build_sources_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)
        host = QWidget()
        scroll.setWidget(host)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        form = QFormLayout()

        self.spin_refresh = QSpinBox()
        self.spin_refresh.setRange(30, 3600)
        self.spin_refresh.setSuffix(" s")
        try:
            value = int(self.data.get("limit_gauges_refresh_sec", 180))
        except (TypeError, ValueError):
            value = 180
        self.spin_refresh.setValue(value)
        self.spin_refresh.valueChanged.connect(self._set_refresh)
        form.addRow("Refresh every", self.spin_refresh)

        self.extra_homes = QLineEdit(
            str(self.data.get("limit_codex_homes", "") or ""))
        self.extra_homes.setPlaceholderText("D:\\codex-work, E:\\codex-personal")
        self.extra_homes.editingFinished.connect(self._set_extra_homes)
        form.addRow("Extra Codex homes", self.extra_homes)

        self.claude_homes = QLineEdit(
            str(self.data.get("limit_claude_homes", "") or ""))
        self.claude_homes.setPlaceholderText(
            "empty = ~/.claude plus any ~/.claude-* home")
        self.claude_homes.setToolTip(
            "One CLAUDE_CONFIG_DIR per extra Claude account. Homes named "
            "~/.claude-<name> are found on their own; list a path here only "
            "when the account lives somewhere else. Each becomes its own "
            "gauge, read with its own credentials.")
        self.claude_homes.editingFinished.connect(self._set_claude_homes)
        form.addRow("Extra Claude homes", self.claude_homes)

        self.antigravity_dir = QLineEdit(
            str(self.data.get("limit_antigravity_dir", "") or ""))
        self.antigravity_dir.setPlaceholderText(
            "empty = detected ~/.gemini/antigravity")
        self.antigravity_dir.setToolTip(
            "Only for a relocated or portable Antigravity install. Its data "
            "lives under ~/.gemini/antigravity, not ~/.antigravity.")
        self.antigravity_dir.editingFinished.connect(self._set_antigravity_dir)
        form.addRow("Antigravity folder", self.antigravity_dir)

        self.zcode_config = QLineEdit(
            str(self.data.get("limit_zcode_config", "") or ""))
        self.zcode_config.setPlaceholderText(
            "empty = detected ~/.zcode/v2/config.json")
        self.zcode_config.setToolTip(
            "Only for a relocated or portable ZCode install. FastPrompter "
            "reads the plan's API key from this file and never stores or logs "
            "it.")
        self.zcode_config.editingFinished.connect(self._set_zcode_config)
        form.addRow("ZCode config file", self.zcode_config)
        lay.addLayout(form)

        top_bar = QHBoxLayout()
        self.btn_auto_troubleshoot = QPushButton("⚡ Auto-Troubleshoot & Auto-Repair All")
        self.btn_auto_troubleshoot.setToolTip(
            "Scan all AI sources, repair stale bridges, adopt candidate paths, "
            "and automatically enable detected coding plans.")
        self.btn_auto_troubleshoot.clicked.connect(self._run_auto_troubleshoot)
        top_bar.addWidget(self.btn_auto_troubleshoot)

        refresh = QPushButton("Refresh accounts and limits now")
        refresh.clicked.connect(self._refresh_now)
        top_bar.addWidget(refresh)
        lay.addLayout(top_bar)

        self.lbl_troubleshoot_status = QLabel("")
        self._hint_style(self.lbl_troubleshoot_status)
        lay.addWidget(self.lbl_troubleshoot_status)

        self._build_cli_group(lay)

        # Codex section
        codex_box = QGroupBox("Codex (ChatGPT / OpenAI)")
        codex_lay = QVBoxLayout(codex_box)
        codex_lay.setContentsMargins(3, 2, 3, 2)
        codex_lay.setSpacing(2)
        codex_note = QLabel(
            "Codex quota is probed directly from the CLI via `codex app-server`. "
            "It authenticates via ~/.codex/auth.json (or sibling homes) and "
            "spends no quota.")
        codex_note.setWordWrap(True)
        codex_lay.addWidget(codex_note)

        codex_btn_row = QHBoxLayout()
        self.btn_codex_login = QPushButton("Log in to Codex…")
        self.btn_codex_login.setToolTip("Opens a console window to run 'codex login'")
        self.btn_codex_login.clicked.connect(lambda: self._launch_login("codex"))
        codex_btn_row.addWidget(self.btn_codex_login)
        codex_btn_row.addStretch(1)
        codex_lay.addLayout(codex_btn_row)

        self.lbl_codex_sources = QLabel()
        self.lbl_codex_sources.setWordWrap(True)
        self._hint_style(self.lbl_codex_sources)
        codex_lay.addWidget(self.lbl_codex_sources)
        lay.addWidget(codex_box)

        claude_row = QHBoxLayout()
        self.btn_claude = QPushButton()
        self.btn_claude.clicked.connect(self._toggle_claude)
        claude_row.addWidget(self.btn_claude)
        self.btn_claude_login = QPushButton("Log in to Claude…")
        self.btn_claude_login.clicked.connect(lambda: self._launch_login("claude"))
        claude_row.addWidget(self.btn_claude_login)
        self.lbl_claude = QLabel()
        self.lbl_claude.setWordWrap(True)
        claude_row.addWidget(self.lbl_claude, 1)
        lay.addLayout(claude_row)
        # T-1267: with two or more Claude accounts the single aggregate row
        # is REPLACED by one bridge row per account, each carrying its own
        # Connect/Disconnect/Reconnect action bound to that account's exact
        # home. Empty and hidden until a refresh finds a multi-account
        # roster; the single-account case keeps the historical row above.
        self.claude_bridge_rows_box = QWidget()
        self.claude_bridge_rows_lay = QVBoxLayout(self.claude_bridge_rows_box)
        self.claude_bridge_rows_lay.setContentsMargins(0, 0, 0, 0)
        self.claude_bridge_rows_lay.setSpacing(2)
        self._claude_bridge_rows: dict[str, dict] = {}
        self.claude_bridge_rows_box.hide()
        lay.addWidget(self.claude_bridge_rows_box)
        explanation = QLabel(
            "Claude limits come from four read-only sources: the Claude Code "
            "CLI's own /usage answer (exact percentages AND reset times, the "
            "best of them), its status line, Claude Desktop's usage sampler "
            "(keeps the gauges alive when Claude Code is not running), and "
            "the refusals Claude Code journals when the API blocks a window. "
            "Nothing is estimated, and the existing status-line configuration "
            "is preserved and restored on disconnect. A second account is a "
            "second CLAUDE_CONFIG_DIR: ~/.claude-<name> homes are detected "
            "automatically, others go in 'Extra Claude homes' above. Each "
            "account row below connects or disconnects THAT account's own "
            "home only; the single row shown for one account acts on the "
            "default ~/.claude home.")
        explanation.setWordWrap(True)
        lay.addWidget(explanation)
        # T-1266 C6: the detection answer comes FIRST and is always shown --
        # including at one account. "How many Claude accounts does
        # FastPrompter think I have, and where did each come from?" used to be
        # answerable only by counting gauges, and the per-home diagnostic
        # lines appeared only once a second home existed, so a second account
        # that failed to be detected explained itself with silence.
        self.lbl_claude_accounts = QLabel()
        self.lbl_claude_accounts.setWordWrap(True)
        self._hint_style(self.lbl_claude_accounts)
        lay.addWidget(self.lbl_claude_accounts)
        self.lbl_claude_sources = QLabel()
        self.lbl_claude_sources.setWordWrap(True)
        self._hint_style(self.lbl_claude_sources)
        lay.addWidget(self.lbl_claude_sources)

        antigravity_note = QLabel(
            "Antigravity's CLI (agy) reports exact percentages for every quota "
            "pool it bills — its own Gemini models and the Claude/GPT models it "
            "hosts are separate pools with separate weekly and 5-hour limits. "
            "Without the CLI only its own 429 refusals are readable: the window "
            "reads 0% until that reset and then reports unknown again, never an "
            "invented number.")
        antigravity_note.setWordWrap(True)
        lay.addWidget(antigravity_note)

        agy_row = QHBoxLayout()
        self.btn_antigravity_login = QPushButton("Log in to Antigravity…")
        self.btn_antigravity_login.clicked.connect(lambda: self._launch_login("antigravity"))
        agy_row.addWidget(self.btn_antigravity_login)
        agy_row.addStretch(1)
        lay.addLayout(agy_row)

        self.lbl_antigravity_sources = QLabel()
        self.lbl_antigravity_sources.setWordWrap(True)
        self._hint_style(self.lbl_antigravity_sources)
        lay.addWidget(self.lbl_antigravity_sources)

        self._build_zcode_group(lay)
        self._build_freebuff_group(lay)
        lay.addStretch(1)
        self.sources_page = page
        self.tabs.addTab(page, "Sources")
        self._refresh_codex_status()
        self._refresh_claude_status()
        self._refresh_antigravity_status()
        self._refresh_zcode_status()

    # -- ZCode: the one source that goes over the network ------------------
    def _build_zcode_group(self, parent_lay):
        """Opt-in switch, plan list, and exactly what enabling it will do.

        Every other source is a local file or a local CLI. ZCode has neither —
        no ``/usage`` command exists and its cached quota sits in a LevelDB the
        running app holds open — so the only way to read it is the endpoint its
        own client calls. That is a credentialed outbound request, which is
        never something to switch on quietly, so the consent lives here with the
        exact destination written out.
        """
        self.cb_zcode = QCheckBox("Read ZCode (GLM Coding Plan) limits")
        self.cb_zcode.setChecked(
            str(self.data.get("limit_zcode_enabled", "False")) == "True")
        self.cb_zcode.setToolTip(
            "One HTTPS GET per sweep to https://api.z.ai"
            "/api/monitor/usage/quota/limit, authenticated with the API key "
            "already in your ZCode config. It is a billing monitor, not a "
            "model call, so it spends no tokens and no quota.")
        self.cb_zcode.toggled.connect(self._toggle_zcode)
        parent_lay.addWidget(self.cb_zcode)

        note = QLabel(
            "ZCode is the only limit source that leaves this machine: it ships "
            "no /usage command, and its own cached numbers sit in a database "
            "the running app keeps locked. When enabled, FastPrompter asks the "
            "same monitor endpoint the ZCode app asks, reading the API key from "
            "ZCode's config for one Authorization header — never logged, never "
            "stored, never shown. Only Z.ai and BigModel hosts are accepted, "
            "over verified HTTPS. Reported: the 5-hour prompt pool and the "
            "weekly quota, both from the plan's own credit meter.")
        note.setWordWrap(True)
        parent_lay.addWidget(note)

        self.lbl_zcode_sources = QLabel()
        self.lbl_zcode_sources.setWordWrap(True)
        self._hint_style(self.lbl_zcode_sources)
        parent_lay.addWidget(self.lbl_zcode_sources)

        self.btn_zcode_quick_enable = QPushButton("Enable detected ZCode Plan")
        self.btn_zcode_quick_enable.setToolTip("Turn on ZCode limit monitoring for detected plans")
        self.btn_zcode_quick_enable.clicked.connect(lambda: self.cb_zcode.setChecked(True))
        self.btn_zcode_quick_enable.hide()
        parent_lay.addWidget(self.btn_zcode_quick_enable)

    def _set_zcode_config(self):
        self.data["limit_zcode_config"] = self.zcode_config.text().strip()
        self._commit()
        self.service.reconfigure_async(self.data)
        self._refresh_zcode_status()

    def _toggle_zcode(self, checked):
        self.data["limit_zcode_enabled"] = "True" if checked else "False"
        self._commit()
        self.service.reconfigure_async(self.data)
        self.account_selector.sync(force=True)
        self._refresh_zcode_status()

    def _refresh_zcode_status(self):
        """One line per configured plan, so a silent gauge is explainable."""
        label = getattr(self, "lbl_zcode_sources", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.providers.zcode import (
                source_status,
            )
            state = source_status(
                str(self.data.get("limit_zcode_config", "") or "") or None)
        except Exception as exc:
            label.setText(f"ZCode sources unavailable: {exc}")
            return
        btn_quick = getattr(self, "btn_zcode_quick_enable", None)
        usable = [p for p in state.get("plans", []) if p.get("has_key")]
        if btn_quick is not None:
            if usable and str(self.data.get("limit_zcode_enabled", "False")) != "True":
                btn_quick.show()
            else:
                btn_quick.hide()
        if not state["config_found"]:
            label.setText("ZCode: config not found at "
                          f"{state['config_path'] or '?'}")
            return
        lines = [f"Config: {state['config_path']}"]
        if not state["plans"]:
            lines.append("Plans: none usable — log in to a Coding Plan in "
                         "ZCode, or the entry is disabled there")
        for plan in state["plans"]:
            if not plan["endpoint"]:
                detail = ("configured host is not a known Z.ai / BigModel "
                          "endpoint — refusing to send credentials there")
            elif plan["has_key"]:
                detail = f"key present · {plan['endpoint']}"
            else:
                detail = "no API key in ZCode's config"
            lines.append(f"{plan['label']}: {detail}")
        if str(self.data.get("limit_zcode_enabled", "False")) != "True":
            lines.append("Currently off — nothing is requested.")
        label.setText("\n".join(lines))

    def _build_freebuff_group(self, parent_lay):
        """Opt-in switch and exactly what enabling it will do.

        Freebuff is the second limit source that leaves this machine: its
        desktop app keeps quota in memory only, so the only truthful read is
        the same session endpoint the app itself polls — a read-only GET that
        admits no session and spends no Freebucks. The token comes from
        Freebuff's own state file, never from FastPrompter.
        """
        self.cb_freebuff = QCheckBox("Read Freebuff (Freebucks) limits")
        self.cb_freebuff.setChecked(
            str(self.data.get("limit_freebuff_enabled", "False")) == "True")
        self.cb_freebuff.setToolTip(
            "One read-only HTTPS GET per sweep to www.codebuff.com"
            "/api/v1/freebuff/session — the same call Freebuff Desktop itself "
            "makes to refresh its header. It creates no session and spends no "
            "Freebucks.")
        self.cb_freebuff.toggled.connect(self._toggle_freebuff)
        parent_lay.addWidget(self.cb_freebuff)

        note = QLabel(
            "Freebuff Desktop shows its Freebucks balance in memory only, so "
            "FastPrompter asks the same session endpoint the app itself polls "
            "— a read-only GET (no session is created, nothing is spent). The "
            "sign-in token is read from Freebuff's own state file for one "
            "Authorization header — never logged, never stored, never shown. "
            "Only the vendor's own host is accepted, over verified HTTPS. "
            "Reported: the daily Freebucks pool, the wallet balance, and "
            "per-model prices in the tooltip.")
        note.setWordWrap(True)
        parent_lay.addWidget(note)

        self.lbl_freebuff_sources = QLabel()
        self.lbl_freebuff_sources.setWordWrap(True)
        self._hint_style(self.lbl_freebuff_sources)
        parent_lay.addWidget(self.lbl_freebuff_sources)

        self.btn_freebuff_quick_enable = QPushButton("Enable detected Freebuff account")
        self.btn_freebuff_quick_enable.setToolTip(
            "Turn on Freebuff limit monitoring for the signed-in account")
        self.btn_freebuff_quick_enable.clicked.connect(
            lambda: self.cb_freebuff.setChecked(True))
        self.btn_freebuff_quick_enable.hide()
        parent_lay.addWidget(self.btn_freebuff_quick_enable)

        # T-1243 spec 27: the FULL model-price table lives here, compact and
        # sorted by price then model -- the hover panel only shows a bounded
        # subset and points at this view.
        self.lbl_freebuff_prices_title = QLabel("Freebuff model prices")
        self._hint_style(self.lbl_freebuff_prices_title)
        self.lbl_freebuff_prices_title.hide()
        parent_lay.addWidget(self.lbl_freebuff_prices_title)
        self.tbl_freebuff_prices = QTableWidget(0, 2)
        self.tbl_freebuff_prices.setHorizontalHeaderLabels(["Model", "FB/hour"])
        self.tbl_freebuff_prices.verticalHeader().setVisible(False)
        self.tbl_freebuff_prices.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_freebuff_prices.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection)
        self.tbl_freebuff_prices.setShowGrid(False)
        self.tbl_freebuff_prices.setAlternatingRowColors(True)
        self.tbl_freebuff_prices.setMaximumHeight(190)
        self.tbl_freebuff_prices.hide()
        parent_lay.addWidget(self.tbl_freebuff_prices)

    def _toggle_freebuff(self, checked):
        self.data["limit_freebuff_enabled"] = "True" if checked else "False"
        self._commit()
        self.service.reconfigure_async(self.data)
        self.account_selector.sync(force=True)
        self._refresh_freebuff_status()

    def _refresh_freebuff_status(self):
        """One line: is Freebuff signed in, and what would enabling read."""
        label = getattr(self, "lbl_freebuff_sources", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.providers.freebuff import (
                source_status,
            )
            state = source_status(
                str(self.data.get("limit_freebuff_state", "") or "") or None,
                enabled=str(self.data.get("limit_freebuff_enabled", "False")) == "True")
        except Exception as exc:
            label.setText(f"Freebuff sources unavailable: {exc}")
            return
        btn_quick = getattr(self, "btn_freebuff_quick_enable", None)
        signed_in = bool(state.get("signed_in"))
        if btn_quick is not None:
            if signed_in and not state.get("enabled"):
                btn_quick.show()
            else:
                btn_quick.hide()
        account = state.get("account") or {}
        who = account.get("name") or account.get("email") or "signed in"
        if not state.get("state_found"):
            label.setText("Freebuff: Desktop state not found at "
                          f"{state.get('state_path') or '?'}")
            return
        if not signed_in:
            label.setText("Freebuff: not signed in — sign in inside Freebuff "
                          "Desktop first")
            return
        lines = [f"Freebuff: signed in as {who} · read-only GET "
                 f"{state.get('endpoint', '')}"]
        if not state.get("enabled"):
            lines.append("Currently off — nothing is requested.")
        label.setText("\n".join(lines))
        self._refresh_freebuff_prices()

    def _freebuff_prices(self) -> dict:
        """The newest model-price map from the service snapshot ({} if none)."""
        try:
            snapshot = self.service.state_copy
        except Exception:
            return {}
        for account in getattr(snapshot, "accounts", ()) or ():
            if getattr(account, "provider_id", "") != "freebuff":
                continue
            shot = (getattr(snapshot, "snapshots", {}) or {}).get(account.key)
            meta = getattr(shot, "provider_metadata", None) or {}
            prices = meta.get("model_prices")
            if isinstance(prices, dict) and prices:
                return prices
        return {}

    def _refresh_freebuff_prices(self):
        """Fill the compact Model / FB-hour table; hide it when unknown."""
        table = getattr(self, "tbl_freebuff_prices", None)
        title = getattr(self, "lbl_freebuff_prices_title", None)
        if table is None:
            return
        from fastprompter.core.usage_limits.freebuff_format import (
            full_price_rows,
        )

        rows = full_price_rows(self._freebuff_prices())
        table.setRowCount(len(rows))
        for index, (name, price) in enumerate(rows):
            table.setItem(index, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(price)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(index, 1, item)
        table.resizeColumnsToContents()
        table.setVisible(bool(rows))
        if title is not None:
            title.setVisible(bool(rows))

    def _set_antigravity_dir(self):
        self.data["limit_antigravity_dir"] = self.antigravity_dir.text().strip()
        self._commit()
        self.service.reconfigure_async(self.data)

    def _refresh_antigravity_status(self):
        label = getattr(self, "lbl_antigravity_sources", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.providers.antigravity import (
                source_status,
            )
            state = source_status(
                str(self.data.get("limit_antigravity_dir", "") or "") or None)
        except Exception as exc:
            label.setText(f"Antigravity sources unavailable: {exc}")
            return
        if not state["installed"]:
            label.setText(f"Antigravity: not found at {state['data_dir'] or '?'}")
            return
        lines = []
        if state.get("cli_installed"):
            if state.get("cli_authenticated", True):
                lines.append(f"CLI: {state['cli_path']} · exact percentages per "
                             "quota pool")
            else:
                lines.append(f"CLI: {state['cli_path']} · not logged in (click "
                             "'Log in to Antigravity…' below to authenticate)")
        else:
            lines.append("CLI: not installed — install it above; without it "
                         "only Antigravity's own refusals are readable")
        if state["blocked_until"]:
            import datetime
            until = datetime.datetime.fromtimestamp(
                state["blocked_until"]).strftime("%a %H:%M")
            lines.append(f"Refusal journal: quota blocked until {until}")
        elif state["observed_at"]:
            import datetime
            seen = datetime.datetime.fromtimestamp(
                state["observed_at"]).strftime("%d.%m %H:%M")
            lines.append(f"Refusal journal: no active block · last refusal {seen}")
        else:
            lines.append("Refusal journal: no refusal recorded")
        label.setText("\n".join(lines))

    def _set_refresh(self, value):
        self.data["limit_gauges_refresh_sec"] = int(value)
        self.main_win.limit_gauges.sync()
        self._commit()

    def _set_extra_homes(self):
        self.data["limit_codex_homes"] = self.extra_homes.text().strip()
        self._commit()
        self.service.reconfigure_async(self.data)

    def _set_claude_homes(self):
        self.data["limit_claude_homes"] = self.claude_homes.text().strip()
        self._commit()
        self.service.reconfigure_async(self.data)
        self._refresh_claude_accounts()
        self._refresh_claude_sources()

    def _refresh_codex_status(self):
        label = getattr(self, "lbl_codex_sources", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.providers.codex import source_status
            extra = [h.strip() for h in str(self.data.get("limit_codex_homes", "") or "").split(",") if h.strip()]
            status = source_status(extra)
        except Exception as exc:
            label.setText(f"Codex sources unavailable: {exc}")
            return
        lines = []
        if status.get("cli_installed"):
            lines.append(f"CLI: {status['cli_path']} · ready for JSON-RPC probe")
            if hasattr(self, "btn_codex_login"):
                self.btn_codex_login.setEnabled(True)
        else:
            lines.append("CLI: not installed — install it above under Agent CLIs")
            if hasattr(self, "btn_codex_login"):
                self.btn_codex_login.setEnabled(False)
        homes = status.get("homes", [])
        if status.get("auth_found"):
            active = [h["path"] for h in homes if h.get("has_auth")]
            lines.append(f"Authentication: active ({len(active)} home(s) with auth.json)")
        else:
            if homes:
                lines.append("Authentication: not logged in (~/.codex/auth.json missing) · click 'Log in to Codex…'")
            else:
                lines.append("Authentication: no Codex home directory found · click 'Log in to Codex…' to authenticate")
        label.setText("\n".join(lines))

    def _refresh_now(self):
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("Refreshing...")
        self.service.discover()
        self.service.refresh()
        self.account_selector.sync(force=True)
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.refresh()
        self._refresh_overview_status()
        self._refresh_cli_rows()
        self._refresh_codex_status()
        self._refresh_claude_status()
        self._refresh_antigravity_status()
        self._refresh_zcode_status()
        self._refresh_freebuff_status()
        if hasattr(self.main_win, "limit_gauges"):
            self.main_win.limit_gauges.refresh_view()
        if hasattr(self.main_win, "_update_limit_timer_label"):
            self.main_win._update_limit_timer_label()

    def _claude_accounts(self) -> list:
        """The service's discovered Claude accounts (empty when unknown)."""
        try:
            state = self.service.state_copy
            return [a for a in state.accounts
                    if getattr(a, "provider_id", "") == "claude"]
        except Exception:
            return []

    @staticmethod
    def claude_bridge_row_state(home) -> tuple[str, str]:
        """(status text, button label) for ONE Claude home. Qt-free.

        Raises nothing: an unreadable home reports a configuration error for
        ITSELF and never for its siblings.
        """
        from fastprompter.core.usage_limits.claude_statusline import bridge_status
        try:
            status = bridge_status(home)
        except Exception as exc:
            return f"Configuration error: {exc}", "Connect Claude Code"
        if status.get("stale"):
            # The command records absolute interpreter/launcher paths, so a
            # moved checkout or a switch to the frozen build leaves Claude
            # Code running a path that no longer exists — silently.
            return ("Connected to an OLD FastPrompter path · press "
                    "Reconnect to repair"), "Reconnect Claude Code"
        if status["connected"] and status["has_cache"]:
            return "Connected · structured limits received", "Disconnect Claude Code"
        if status["connected"]:
            return "Connected · waiting for first Claude API response", "Disconnect Claude Code"
        return "Not connected", "Connect Claude Code"

    def _sync_claude_bridge_rows(self, accounts) -> None:
        """Rebuild per-account bridge rows only when the roster changes.

        Each row's button is bound to the account's EXACT home at creation
        and never rebound in place (T-1267): a home that disappears takes
        its row and its binding with it, a new home gets a fresh row, and a
        plain status refresh can never silently re-target an action at a
        different account.
        """
        box = getattr(self, "claude_bridge_rows_box", None)
        if box is None:
            return
        homes = {account.source_path: account for account in accounts}
        for home in list(self._claude_bridge_rows):
            if home not in homes:
                row = self._claude_bridge_rows.pop(home)
                row["widget"].setParent(None)
                row["widget"].deleteLater()
        for home, account in homes.items():
            row = self._claude_bridge_rows.get(home)
            if row is None:
                widget = QWidget()
                row_lay = QHBoxLayout(widget)
                row_lay.setContentsMargins(0, 0, 0, 0)
                label = QLabel()
                label.setWordWrap(True)
                button = QPushButton()
                button.clicked.connect(
                    lambda _checked=False, bound=home:
                        self._toggle_claude_for_home(bound))
                row_lay.addWidget(label, 1)
                row_lay.addWidget(button)
                self.claude_bridge_rows_lay.addWidget(widget)
                row = {"widget": widget, "label": label, "button": button}
                self._claude_bridge_rows[home] = row
            text, button_text = self.claude_bridge_row_state(home)
            row["label"].setText(f"{account.display_name} · {home}\n{text}")
            row["button"].setText(button_text)
        box.setVisible(bool(self._claude_bridge_rows))

    def _toggle_claude_for_home(self, home) -> None:
        """Connect, disconnect, or repair ONE Claude home's status-line bridge.

        The action carries the EXACT account home that initiated it (T-1267):
        no default-home fallback, and no other home's settings, sidecar
        backup or rate-limit cache is touched. A STALE bridge needs a
        reinstall, not a disconnect: disconnecting would hand the user back
        their old status line and leave the feed off, when what they asked
        for is the feed working again.
        """
        from fastprompter.core.usage_limits.claude_statusline import (
            bridge_status,
            install_bridge,
            uninstall_bridge,
        )
        try:
            status = bridge_status(home)
            if status.get("stale"):
                install_bridge(home)
            elif status.get("connected"):
                uninstall_bridge(home)
            else:
                install_bridge(home)
        except Exception as exc:
            QMessageBox.warning(
                self, "Claude Code limits",
                "Could not update the Claude statusLine for\n"
                f"{home}:\n\n{exc}")
        self._refresh_claude_status()
        service = getattr(self, "service", None)
        reconfigure = getattr(service, "reconfigure_async", None)
        if reconfigure is not None:
            reconfigure(self.data)

    def _refresh_claude_status(self):
        accounts = self._claude_accounts()
        button = getattr(self, "btn_claude", None)
        label = getattr(self, "lbl_claude", None)
        if len(accounts) > 1:
            # T-1267: a multi-account roster gets one control row per
            # account; the aggregate row would act on the default
            # ~/.claude home no matter which account the user meant.
            if button is not None:
                button.hide()
            if label is not None:
                label.hide()
            self._sync_claude_bridge_rows(accounts)
            self._refresh_claude_accounts()
            self._refresh_claude_sources()
            return
        if button is not None:
            button.show()
        if label is not None:
            label.show()
        self._sync_claude_bridge_rows([])
        default_home = None
        if accounts:
            default_home = accounts[0].source_path
        try:
            from fastprompter.core.usage_limits.claude_statusline import bridge_status
            status = bridge_status(default_home)
            if status.get("stale"):
                # The command records absolute interpreter/launcher paths, so a
                # moved checkout or a switch to the frozen build leaves Claude
                # Code running a path that no longer exists — silently.
                text = ("Connected to an OLD FastPrompter path · press "
                        "Reconnect to repair")
            elif status["connected"] and status["has_cache"]:
                text = "Connected · structured limits received"
            elif status["connected"]:
                text = "Connected · waiting for first Claude API response"
            else:
                text = "Not connected"
            if button is not None:
                if status.get("stale"):
                    button.setText("Reconnect Claude Code")
                else:
                    button.setText(
                        "Disconnect Claude Code" if status["connected"]
                        else "Connect Claude Code")
            if label is not None:
                label.setText(text)
        except Exception as exc:
            if button is not None:
                button.setText("Connect Claude Code")
            if label is not None:
                label.setText(f"Configuration error: {exc}")
        self._refresh_claude_accounts()
        self._refresh_claude_sources()

    def claude_accounts_lines(self) -> list[str]:
        """The detection summary, as plain lines. One row per account.

        Deliberately Qt-free so the CONTENT can be asserted directly: the
        count sentence, then name / badge / home / credentials / status line /
        current quota-data state for every discovered Claude account. The data
        state is read from the service snapshots the gauges draw, so this row
        and the header can never disagree, and nothing here is invented when a
        source is silent.
        """
        from fastprompter.core.usage_limits.providers.claude import (
            accounts_report,
            detected_summary,
        )
        from fastprompter.ui.limit_account_selector import short_account_label
        try:
            state = self.service.state_copy
            accounts = [a for a in state.accounts
                        if getattr(a, "provider_id", "") == "claude"]
            rows = accounts_report(accounts, state.snapshots)
        except Exception as exc:
            return [f"Claude accounts unavailable: {exc}"]
        badges = {}
        for account in accounts:
            try:
                badges[account.key] = short_account_label(account, self.data)
            except Exception:
                badges[account.key] = ""
        lines = [detected_summary(len(rows))]
        for row in rows:
            badge = badges.get(row["key"], "")
            origin = "default home" if row["is_default"] else row["kind"]
            creds = "yes" if row["has_credentials"] else "no"
            if not row["bridge_connected"]:
                bridge = "no"
            elif row["bridge_has_cache"]:
                bridge = "yes (cache present)"
            else:
                bridge = "yes (no cache yet)"
            badge_text = f" [{badge}]" if badge else ""
            name = row["name"]
            path = row["path"]
            lines.append(f"  {name}{badge_text} · {origin} · {path}")
            lines.append(
                f"      credentials: {creds} · status line: {bridge}"
                f" · quota data: {row['data_state']}")
        return lines

    def _refresh_claude_accounts(self):
        label = getattr(self, "lbl_claude_accounts", None)
        if label is None:
            return
        label.setText("\n".join(self.claude_accounts_lines()))

    def _refresh_claude_sources(self):
        """One line per Claude source, so a silent gauge is explainable."""
        label = getattr(self, "lbl_claude_sources", None)
        if label is None:
            return
        try:
            from fastprompter.core.usage_limits.providers.claude import (
                homes_status,
                source_status,
            )
            state = source_status()
        except Exception as exc:
            label.setText(f"Claude sources unavailable: {exc}")
            return
        lines = []
        try:
            from fastprompter.core.usage_limits.service import parse_home_list
            homes = homes_status(parse_home_list(
                self.data.get("limit_claude_homes", "")))
        except Exception:
            homes = []
        if len(homes) > 1:
            # Only worth the two extra lines once a second account exists; on a
            # single-account machine this block stays invisible.
            for home in homes:
                role = "default" if home["is_default"] else home["kind"]
                bridge = ("status line connected" if home["bridge_connected"]
                          else "status line not connected \u00b7 read via CLI")
                lines.append(f"Home ({role}): {home['path']} \u00b7 {bridge}")
        if state.get("cli_installed"):
            lines.append(f"CLI: {state['cli_path']} · exact percentages and "
                         "reset times")
        else:
            lines.append("CLI: not installed — install it above for exact "
                         "percentages and reset times")
        if state["bridge_connected"]:
            lines.append("Status line (default home): connected · "
                         + ("cache present" if state["bridge_has_cache"]
                            else "no cache yet (Claude Code must render it)"))
        else:
            lines.append("Status line (default home): not connected")
        windows = state["desktop_windows"]
        if windows:
            age = state["desktop_age_s"] or 0
            detail = ", ".join(
                f"{_desktop_window_name(key)} {value:.0f}% used"
                for key, value in sorted(windows.items()))
            freshness = "live" if state["desktop_fresh"] else "stale"
            lines.append(f"Claude Desktop sampler: {detail} · "
                         f"{int(age // 60)} min old ({freshness})")
        else:
            lines.append("Claude Desktop sampler: no samples found")
        blocked = state["blocked_windows"]
        if blocked:
            import datetime
            detail = ", ".join(
                f"{_desktop_window_name(key)} until "
                + datetime.datetime.fromtimestamp(
                    block["resets_at"]).strftime("%H:%M")
                for key, block in sorted(blocked.items()))
            lines.append(f"Claude Code refusals: blocked {detail}")
        label.setText("\n".join(lines))

    def _toggle_claude(self):
        """The single-account row: act on the DEFAULT account's own home.

        Historical default-account behaviour (T-1267), now carrying the
        discovered default home explicitly instead of relying on the
        ambient ~/.claude; with no discovered account the bridge layer's
        own default resolution applies, exactly as before.
        """
        accounts = self._claude_accounts()
        home = None
        for account in accounts:
            if (getattr(account, "metadata", None) or {}).get("is_default"):
                home = account.source_path
                break
        if home is None and accounts:
            home = accounts[0].source_path
        self._toggle_claude_for_home(home)

    def _run_auto_troubleshoot(self):
        """Perform automated safe repairs and scan all providers."""
        try:
            from fastprompter.core.usage_limits.troubleshooter import auto_heal_all
            result = auto_heal_all(self.data, self.service)
        except Exception as exc:
            QMessageBox.warning(self, "Auto-Troubleshoot", f"Auto-troubleshoot failed:\n\n{exc}")
            return

        self._commit()
        self.account_selector.sync(force=True)
        overview = getattr(self, "overview", None)
        if overview is not None:
            overview.refresh()
        self._refresh_overview_status()
        self._refresh_cli_rows()
        self._refresh_codex_status()
        self._refresh_claude_status()
        self._refresh_antigravity_status()
        self._refresh_zcode_status()
        self._refresh_freebuff_status()
        if hasattr(self.main_win, "limit_gauges"):
            self.main_win.limit_gauges.sync()
            self.main_win.limit_gauges.refresh_view()

        healed = result.get("healed", [])
        remaining = result.get("remaining_issues", [])
        accounts_count = result.get("accounts_count", 0)

        status_text = f"Auto-heal: {len(healed)} fix(es) · {accounts_count} account(s) reporting"
        if hasattr(self, "lbl_troubleshoot_status"):
            self.lbl_troubleshoot_status.setText(status_text)

        if not getattr(self, "_suppress_dialogs_for_tests", False):
            self._show_troubleshoot_summary(healed, remaining, accounts_count, result.get("diagnostics", {}))

    def _show_troubleshoot_summary(self, healed, remaining, accounts_count, diagnostics):
        dialog = QDialog(self)
        dialog.setWindowTitle("AI Limits Auto-Troubleshoot")
        dialog.setMinimumWidth(460)
        lay = QVBoxLayout(dialog)
        lay.setSpacing(8)

        if healed:
            box_h = QGroupBox("Automated Repairs Completed")
            box_h_lay = QVBoxLayout(box_h)
            for h in healed:
                lbl = QLabel(f"✓ {h}")
                lbl.setStyleSheet("color: #4caf50; font-weight: bold;")
                box_h_lay.addWidget(lbl)
            lay.addWidget(box_h)

        if accounts_count > 0:
            succ = QLabel(f"★ {accounts_count} account(s) reporting quota live!")
            succ.setStyleSheet("font-weight: bold; font-size: 12px;")
            lay.addWidget(succ)

        if remaining:
            box_r = QGroupBox("Remaining Setup Items")
            box_r_lay = QVBoxLayout(box_r)
            for r in remaining:
                lbl = QLabel(f"• {r}")
                lbl.setWordWrap(True)
                box_r_lay.addWidget(lbl)
            lay.addWidget(box_r)

            act_box = QHBoxLayout()
            codex_diag = diagnostics.get("codex", {})
            if codex_diag.get("status_code") == "needs_login":
                btn = QPushButton("Log in to Codex…")
                btn.clicked.connect(lambda: [dialog.accept(), self._launch_login("codex")])
                act_box.addWidget(btn)
            elif codex_diag.get("status_code") == "needs_install":
                btn = QPushButton("Install Codex CLI")
                btn.clicked.connect(lambda: [dialog.accept(), self._install_cli("codex")])
                act_box.addWidget(btn)

            claude_diag = diagnostics.get("claude", {})
            if claude_diag.get("status_code") == "needs_install":
                btn = QPushButton("Install Claude CLI")
                btn.clicked.connect(lambda: [dialog.accept(), self._install_cli("claude")])
                act_box.addWidget(btn)

            agy_diag = diagnostics.get("antigravity", {})
            if not agy_diag.get("details", {}).get("cli_installed"):
                btn = QPushButton("Install Antigravity CLI")
                btn.clicked.connect(lambda: [dialog.accept(), self._install_cli("antigravity")])
                act_box.addWidget(btn)
            elif agy_diag.get("status_code") == "needs_login":
                # The CLI is present but has no stored session, so probing is
                # refused on purpose (no surprise browser). Offer the explicit
                # login here — auto-pressing it would be the popup we avoid.
                btn = QPushButton("Log in to Antigravity…")
                btn.clicked.connect(lambda: [dialog.accept(), self._launch_login("antigravity")])
                act_box.addWidget(btn)

            lay.addLayout(act_box)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_box.addWidget(close_btn)
        lay.addLayout(btn_box)
        dialog.exec()

    def _launch_login(self, vendor: str):
        try:
            from fastprompter.core.usage_limits.troubleshooter import launch_vendor_login
            if vendor == "antigravity":
                msg = (
                    "FastPrompter is about to open a console named "
                    "'FastPrompter - Antigravity sign-in'. A Google sign-in page may "
                    "then open in your browser.\n\n"
                    "1. Sign in with your Google account in the browser.\n"
                    "2. Copy the authorization code shown there.\n"
                    "3. Paste that code into the named console window and press Enter.\n\n"
                    "Do not paste the code into the Antigravity editor or the "
                    "FastPrompter text area. A code from an earlier sign-in cannot be "
                    "reused.\n\n"
                    "Dismiss this message to start sign-in. When it finishes, return here "
                    "and click 'Refresh limits now'."
                )
                # Explain the otherwise alarming browser/code flow BEFORE it
                # starts.  The visible console repeats the destination while
                # the browser is open, so the instruction cannot disappear at
                # the exact moment it is needed.
                QMessageBox.information(
                    self, "Antigravity sign-in instructions", msg)
                launch_vendor_login(vendor)
            else:
                launch_vendor_login(vendor)
                msg = (
                    f"A console window opened for {vendor.title()} login.\n\n"
                    "Complete the login in that window, then return here and click "
                    "'Refresh accounts and limits now'."
                )
                QMessageBox.information(
                    self, f"Log in to {vendor.title()}", msg)
        except Exception as exc:
            QMessageBox.warning(self, f"Log in to {vendor.title()}", f"Could not launch login:\n\n{exc}")
