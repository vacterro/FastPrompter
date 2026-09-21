"""The fifth Settings tab: PROBLIP (T-1238-C2).

This module OWNS the page widgets and nothing else.  It binds to the one
application-owned :class:`ProblipController`: opening or closing Settings,
switching tabs or applying a sound preset must never recreate the
controller, restart its timer or rewrite its statistics.

Everything user-visible carries its English source in ``_en_text`` /
``_en_tooltip`` so the existing live-retranslation sweep picks it up.
"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from fastprompter.core import sound_library
from fastprompter.core.problip import IntervalMode, ProblipState
from fastprompter.core.problip_store import PLAYBACK_MODES
from fastprompter.core.translations import tr
from fastprompter.sound.problip.catalog import SOUND_CATALOG

_is_deleted = sip.isdeleted

#: 100,000 blips is the product's irreversible milestone.
MILESTONE_TARGET = 100_000

#: (persisted value, English label) for the interval selector.
INTERVAL_CHOICES = (
    (IntervalMode.RANDOM_4_7.value, "Random 4-7 s"),
    (IntervalMode.FIXED_5S.value, "5 s"),
    (IntervalMode.FIXED_10S.value, "10 s"),
    (IntervalMode.FIXED_15S.value, "15 s"),
    (IntervalMode.FIXED_20S.value, "20 s"),
    (IntervalMode.FIXED_30S.value, "30 s"),
    (IntervalMode.PULSE.value, "Pulse"),
    (IntervalMode.MANUAL.value, "Manual"),
)

#: (persisted value, English label) for the Problip playback selector.
PLAYBACK_CHOICES = (
    ("inherit", "Inherit"),
    ("mix", "Overlay"),
    ("queue", "Stack"),
    ("replace", "Replace"),
    ("skip_busy", "Skip while busy"),
)

_STATE_LABELS = {
    ProblipState.STOPPED: "OFF",
    ProblipState.STARTING: "STARTING",
    ProblipState.RUNNING: "ON",
    ProblipState.ERROR: "ERR",
}


def _label(text: str, lang: str) -> QLabel:
    widget = QLabel(tr(text, lang))
    widget._en_text = text
    return widget


def _button(text: str, lang: str, tooltip: str = "") -> QPushButton:
    widget = QPushButton(tr(text, lang))
    widget._en_text = text
    if tooltip:
        widget.setToolTip(tr(tooltip, lang))
        widget._en_tooltip = tooltip
    return widget


def _checkbox(text: str, lang: str, tooltip: str = "") -> QCheckBox:
    widget = QCheckBox(tr(text, lang))
    widget._en_text = text
    if tooltip:
        widget.setToolTip(tr(tooltip, lang))
        widget._en_tooltip = tooltip
    return widget


def _row(*widgets, spacing: int = 4) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return host


class ProblipSettingsPage:
    """Builds and binds the Problip settings widgets.

    The page is a plain builder, not a QWidget subclass: the host settings
    panel supplies the group/tab chrome so Problip looks exactly like every
    other FastPrompter settings page and inherits the global theme (no local
    theme selector, by contract).
    """

    def __init__(self, host, controller, lang: str) -> None:
        self.host = host
        self.controller = controller
        self.lang = lang
        self._loading = False
        self._glow_anim: QPropertyAnimation | None = None
        self._glow_effect: QGraphicsOpacityEffect | None = None
        self._build_widgets()
        self._connect_controller()
        self.reload()

    # -- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        lang = self.lang

        # --- PROBLIP -------------------------------------------------------
        self.lbl_status = QLabel("OFF")
        self.lbl_status.setObjectName("ProblipStatus")
        self.lbl_status.setMinimumWidth(64)
        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        self.btn_start = _button("Start", lang, "Start Problip")
        self.btn_stop = _button("Stop", lang, "Stop Problip")
        self.btn_test = _button(
            "Test", lang,
            "Play one Problip sound now. No statistics, no interval change.")
        self.lbl_blips = QLabel("")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_test.clicked.connect(self._on_test)
        self.row_controls = _row(self.lbl_status, self.btn_start,
                                 self.btn_stop, self.btn_test,
                                 self.lbl_blips, None)

        # --- INTERVAL ------------------------------------------------------
        self.cb_interval = QComboBox()
        for value, text in INTERVAL_CHOICES:
            self.cb_interval.addItem(tr(text, lang), value)
        self.cb_interval._en_items = [t for _v, t in INTERVAL_CHOICES]
        self.cb_interval.currentIndexChanged.connect(self._on_interval_changed)
        self.lbl_from = _label("From:", lang)
        self.lbl_to = _label("To:", lang)
        self.sp_from = QSpinBox()
        self.sp_from.setRange(1, 3600)
        self.sp_to = QSpinBox()
        self.sp_to.setRange(1, 3600)
        self.sp_from.valueChanged.connect(self._on_manual_changed)
        self.sp_to.valueChanged.connect(self._on_manual_changed)
        self.row_manual = _row(self.lbl_from, self.sp_from,
                               self.lbl_to, self.sp_to, None)
        self.row_interval = _row(self.cb_interval, None)

        # --- SOUND POOL ----------------------------------------------------
        self.pool_boxes: dict[str, QCheckBox] = {}
        pool_widgets: list[QWidget] = []
        for entry in SOUND_CATALOG:
            box = _checkbox(entry.display_name, lang)
            box.toggled.connect(
                lambda checked, sid=entry.sound_id: self._on_pool_toggled(sid,
                                                                         checked))
            self.pool_boxes[entry.sound_id] = box
            pool_widgets.append(box)
        self.pool_rows = [_row(*pool_widgets[0:3], None),
                          _row(*pool_widgets[3:6], None)]
        # T-1242: ONE compact action for custom sounds -- never a long file
        # list on the main page.  The Manage dialog owns import/selection.
        self.btn_custom = _button(
            "Manage...", lang,
            "Add your own WAVs to the Problip pool (copied into the "
            "managed sound library)")
        self.btn_custom.clicked.connect(self._on_manage_custom)
        self.row_custom = _row(self.btn_custom, None)
        self.lbl_pool_warning = QLabel("")
        self.lbl_pool_warning.setWordWrap(True)
        self.lbl_pool_warning.setVisible(False)

        self.lbl_volume = _label("Volume:", lang)
        self.sl_volume = QSlider(Qt.Orientation.Horizontal)
        self.sl_volume.setRange(0, 100)
        self.lbl_volume_value = QLabel("0")
        self.sl_volume.valueChanged.connect(self._on_volume_moving)
        self.sl_volume.sliderReleased.connect(self._on_volume_released)
        self.row_volume = _row(self.lbl_volume, self.sl_volume,
                               self.lbl_volume_value)

        self.lbl_playback = _label("Playback:", lang)
        self.cb_playback = QComboBox()
        for value, text in PLAYBACK_CHOICES:
            self.cb_playback.addItem(tr(text, lang), value)
        self.cb_playback._en_items = [t for _v, t in PLAYBACK_CHOICES]
        self.cb_playback.currentIndexChanged.connect(self._on_playback_changed)
        self.row_playback = _row(self.lbl_playback, self.cb_playback, None)

        # --- STATISTICS ----------------------------------------------------
        self.lbl_today = QLabel("")
        self.lbl_week = QLabel("")
        self.lbl_month = QLabel("")
        self.lbl_total = QLabel("")
        # T-1246: two rows of two, not one row of four -- the four-label row
        # was the widest card on the page (704 px) and forced every other
        # group into its row, leaving blank stripes around the short ones.
        self.row_stats = QWidget()
        stats_grid = QGridLayout(self.row_stats)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(12)
        stats_grid.setVerticalSpacing(1)
        for index, label in enumerate((self.lbl_today, self.lbl_week,
                                       self.lbl_month, self.lbl_total)):
            stats_grid.addWidget(label, index // 2, index % 2)
        stats_grid.setColumnStretch(2, 1)
        self.pb_milestone = QProgressBar()
        self.pb_milestone.setRange(0, MILESTONE_TARGET)
        self.pb_milestone.setTextVisible(True)
        self.lbl_earned = _label("EARNED", lang)
        self.lbl_earned.setVisible(False)

        # --- EFFECTS -------------------------------------------------------
        self.cb_counter = _checkbox(
            "Show counter", lang, "Show the Problip counter in Settings")
        self.cb_glow = _checkbox(
            "Blip Glow", lang, "Flash the Problip page softly on each cue")
        self.cb_autostart = _checkbox(
            "Start with Windows", lang,
            "Launch FastPrompter when Windows starts (packaged build only)")
        self.cb_counter.toggled.connect(
            lambda v: self._persist(show_counter=bool(v)))
        self.cb_glow.toggled.connect(
            lambda v: self._persist(blip_glow_enabled=bool(v)))
        self.cb_autostart.toggled.connect(self._on_autostart_toggled)
        self.row_effects = _row(self.cb_counter, self.cb_glow, None)
        self.row_autostart = _row(self.cb_autostart, None)

        # --- AUDIO ---------------------------------------------------------
        self.btn_audio_hub = _button(
            "Open Audio Hub...", lang,
            "Events, presets, playback, voice and ambience")
        self.btn_stop_all = _button(
            "STOP ALL SOUND", lang,
            "Immediately silence every sound, queue and ambience layer")
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self.btn_audio_hub.clicked.connect(self._on_open_audio_hub)
        self.row_audio = _row(self.btn_audio_hub, self.btn_stop_all, None)

        # --- HELP ----------------------------------------------------------
        self.lbl_help = _label(
            "Problip plays one short cue at your chosen interval so a long "
            "writing session keeps its rhythm. Pick the interval, pick which "
            "of the six sounds may play, and choose how a cue behaves when "
            "other audio is already playing.", lang)
        self.lbl_help.setWordWrap(True)
        # T-1246: never a sliver column of one word per line
        self.lbl_help.setMinimumWidth(180)

    # -- controller binding ---------------------------------------------------

    def _connect_controller(self) -> None:
        controller = self.controller
        controller.stateChanged.connect(self._on_state_changed)
        controller.statsChanged.connect(lambda _s: self.refresh_stats())
        controller.settingsChanged.connect(lambda _s: self.reload())
        controller.errorChanged.connect(self._on_error_changed)
        controller.cuePlayed.connect(self.flash_glow)

    def groups(self) -> list[tuple[str, list[QWidget]]]:
        """(English group title, widgets) for the host's group chrome."""
        return [
            ("Problip", [self.row_controls, self.lbl_error]),
            ("Interval", [self.row_interval, self.row_manual]),
            ("Sound pool", [*self.pool_rows, self.row_custom,
                            self.lbl_pool_warning,
                            self.row_volume, self.row_playback]),
            ("Statistics", [self.row_stats, self.pb_milestone,
                            self.lbl_earned]),
            ("Effects", [self.row_effects, self.row_autostart]),
            ("Audio", [self.row_audio]),
            ("Help", [self.lbl_help]),
        ]

    # -- loading --------------------------------------------------------------

    def reload(self) -> None:
        """Reflect controller state; never write anything back."""
        settings = self.controller.settings
        self._loading = True
        try:
            index = self.cb_interval.findData(str(settings.interval_mode))
            self.cb_interval.setCurrentIndex(max(0, index))
            self.sp_from.setValue(settings.manual_from_seconds)
            self.sp_to.setValue(settings.manual_to_seconds)
            selected = set(settings.selected_sound_ids)
            # A built-in counts as selected when persisted bare OR pinned
            # with its explicit builtin-id: token (T-1242 pool forms).
            for sound_id, box in self.pool_boxes.items():
                box.setChecked(sound_id in selected
                               or f"builtin-id:{sound_id}" in selected)
            self.sl_volume.setValue(settings.volume_percent)
            self.lbl_volume_value.setText(str(settings.volume_percent))
            mode_index = self.cb_playback.findData(settings.playback_mode)
            self.cb_playback.setCurrentIndex(max(0, mode_index))
            self.cb_counter.setChecked(settings.show_counter)
            self.cb_glow.setChecked(settings.blip_glow_enabled)
            self.cb_autostart.setChecked(settings.windows_autostart)
        finally:
            self._loading = False
        self._sync_manual_visibility()
        self.refresh_pool_marks()
        self.refresh_stats()
        self.refresh_state()

    def refresh_state(self) -> None:
        state = self.controller.state
        self.lbl_status.setText(tr(_STATE_LABELS.get(state, "OFF"), self.lang))
        running = self.controller.is_running()
        # C2.3: START must not look available while it is already starting.
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        error = self.controller.error or ""
        self.lbl_error.setText(error)
        self.lbl_error.setVisible(bool(error))

    def refresh_stats(self) -> None:
        try:
            snapshot = self.controller.stats()
        except Exception:
            return
        show = self.controller.settings.show_counter
        self.lbl_today.setText(f"{tr('Today', self.lang)}: {snapshot.today}")
        self.lbl_week.setText(f"{tr('This week', self.lang)}: {snapshot.week}")
        self.lbl_month.setText(f"{tr('This month', self.lang)}: {snapshot.month}")
        self.lbl_total.setText(f"{tr('Total', self.lang)}: {snapshot.total}")
        # T-1242 (spec 18): Show counter hides ONLY the compact "N BLIPS"
        # readout.  Today/Week/Month/Total and the milestone bar are detailed
        # statistics and stay visible in every state.
        self.row_stats.setVisible(True)
        self.pb_milestone.setValue(min(MILESTONE_TARGET, int(snapshot.total)))
        earned = bool(getattr(snapshot, "earned_premium", False))
        self.lbl_earned.setVisible(earned)
        self.lbl_blips.setText(
            f"{snapshot.total} {tr('BLIPS', self.lang)}"
            if show and self.controller.is_running() else "")

    def refresh_pool_marks(self) -> None:
        """C2.4: an unavailable asset is marked, never silently deselected."""
        status = self.controller.pool_status()
        missing = set(status.missing_ids) | set(status.invalid_ids)
        # Map missing tokens back to their built-in checkbox (bare or pinned).
        for sound_id, box in self.pool_boxes.items():
            unavailable = (sound_id in missing
                           or f"builtin-id:{sound_id}" in missing)
            box.setProperty("unavailable", unavailable)
            base = getattr(box, "_en_text", box.text())
            box.setText(tr(base, self.lang)
                        + (f" ({tr('unavailable', self.lang)})"
                           if unavailable else ""))
        warning = status.warning or ""
        self.lbl_pool_warning.setText(tr(warning, self.lang) if warning else "")
        self.lbl_pool_warning.setVisible(bool(warning))

    # -- user actions ----------------------------------------------------------

    def _persist(self, **changes) -> None:
        if self._loading:
            return
        self.controller.update_settings(**changes)

    def _on_start(self) -> None:
        self.lbl_status.setText(tr("STARTING", self.lang))
        self.btn_start.setEnabled(False)
        self.controller.start()
        self.refresh_state()

    def _on_stop(self) -> None:
        self.controller.stop()
        self.refresh_state()

    def _on_test(self) -> None:
        ok, message = self.controller.test()
        if not ok:
            self.lbl_error.setText(message)
            self.lbl_error.setVisible(True)
        # A failed TEST must not change the remembered run preference.

    def _on_stop_all(self) -> None:
        try:
            self.controller._sound_manager.stop_all_sound()
        except Exception:
            pass

    def _on_open_audio_hub(self) -> None:
        """T-1242 spec A1: the canonical opener is MainWindow's
        ``open_sound_settings_dialog`` (the same handler the Sound button in
        the settings panel binds).  The old lookup used a name that exists
        nowhere, so ``callable()`` swallowed the miss and the button did
        literally nothing (A5).  A failure is now a visible bounded
        diagnostic, never silent.
        """
        host = self.host
        opener = (getattr(host, "open_sound_settings_dialog", None)
                  or getattr(host, "open_sound_settings", None))
        if not callable(opener):
            self._record_audio_hub_open_failed(
                "no opener on host", RuntimeError(type(host).__name__))
            return
        try:
            opener()
        except Exception as exc:                      # noqa: BLE001 - A5
            self._record_audio_hub_open_failed("opener raised", exc)

    def _record_audio_hub_open_failed(self, reason: str, exc: Exception) -> None:
        """Bounded AUDIO_HUB_OPEN_FAILED diagnostic: no traceback spam."""
        message = (f"{reason}: {type(exc).__name__}: {exc}"[:200]
                   if isinstance(exc, Exception) else reason)
        try:
            sound_manager = getattr(self.controller, "_sound_manager", None)
            provenance = getattr(sound_manager, "_provenance", None)
            if provenance is not None:
                provenance.append({
                    "op": "AUDIO_HUB_OPEN_FAILED", "detail": message,
                    "outcome": "FAILED",
                })
        except Exception:
            pass
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(True)

    def _on_interval_changed(self, _index: int) -> None:
        if self._loading:
            return
        self.controller.set_interval_mode(self.cb_interval.currentData())
        self._sync_manual_visibility()

    def _on_manual_changed(self, _value: int) -> None:
        if self._loading:
            return
        self.controller.set_manual_range(self.sp_from.value(),
                                         self.sp_to.value())

    def _sync_manual_visibility(self) -> None:
        manual = self.cb_interval.currentData() == IntervalMode.MANUAL.value
        self.row_manual.setVisible(manual)

    def _on_pool_toggled(self, sound_id: str, checked: bool) -> None:
        if self._loading:
            return
        # Persisted selection = current tokens (bare six-ID form is kept for
        # built-ins so existing databases read it unchanged) + custom refs.
        selected = [sid for sid, box in self.pool_boxes.items() if box.isChecked()]
        selected += [token for token in self._custom_pool_tokens()
                     if token not in selected]
        if not selected:
            # C2.4: the last selected sound cannot be unchecked.
            self._loading = True
            try:
                self.pool_boxes[sound_id].setChecked(True)
            finally:
                self._loading = False
            return
        self.controller.update_settings(selected_sound_ids=selected)
        self.refresh_pool_marks()

    def _custom_pool_tokens(self) -> list[str]:
        """Managed-library refs currently in the persisted pool."""
        return [t for t in self.controller.settings.selected_sound_ids
                if t.startswith(sound_library.USER_PREFIX)]

    def _on_manage_custom(self) -> None:
        """Open the compact custom-sound manager (import / select / remove)."""
        from fastprompter.ui.problip_custom_sounds import ProblipCustomDialog

        dialog = ProblipCustomDialog(self.host, self.lang,
                                     self.controller)
        if dialog.exec():
            self.reload()
            self.refresh_pool_marks()

    def _on_volume_moving(self, value: int) -> None:
        # C2.5: dragging is silent; only the release previews.
        self.lbl_volume_value.setText(str(value))

    def _on_volume_released(self) -> None:
        if self._loading:
            return
        self.controller.update_settings(volume_percent=self.sl_volume.value())
        self.controller.test()

    def _on_playback_changed(self, _index: int) -> None:
        if self._loading:
            return
        mode = self.cb_playback.currentData()
        if mode in PLAYBACK_MODES:
            self.controller.update_settings(playback_mode=mode)

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        from fastprompter.ui.windows_autostart import set_autostart

        ok, message = set_autostart(bool(checked))
        if not ok:
            self._loading = True
            try:
                self.cb_autostart.setChecked(not checked)
            finally:
                self._loading = False
            self.lbl_error.setText(message)
            self.lbl_error.setVisible(True)
            return
        self._persist(windows_autostart=bool(checked))

    # -- signals from the controller --------------------------------------------

    def _on_state_changed(self, _state: str) -> None:
        self.refresh_state()
        self.refresh_stats()

    def _on_error_changed(self, message: str) -> None:
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(bool(message))

    # -- glow -------------------------------------------------------------------

    def flash_glow(self) -> None:
        """C2.6: one subtle theme-accent flash, only while the page is visible.

        Never opens Settings, never raises the window, never steals focus.
        ONE animation object for the life of the page: a newer cue restarts
        the same object.  It is deliberately NOT DeleteWhenStopped -- that
        deleted the C++ object out from under the Python reference and the
        next cue crashed with "wrapped C/C++ object of type
        QPropertyAnimation has been deleted".
        """
        target = self.row_controls
        if target is None or _is_deleted(target) or not target.isVisible():
            return
        if self._glow_effect is None or _is_deleted(self._glow_effect):
            self._glow_effect = QGraphicsOpacityEffect(target)
            target.setGraphicsEffect(self._glow_effect)
            self._glow_anim = None
        if self._glow_anim is None or _is_deleted(self._glow_anim):
            animation = QPropertyAnimation(self._glow_effect, b"opacity",
                                           target)
            animation.setDuration(320)
            animation.setStartValue(0.35)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._glow_anim = animation
        try:
            self._glow_anim.stop()
            self._glow_anim.start()
        except RuntimeError:
            # The effect or the animation was torn down between the checks
            # above and here (page rebuild): drop them and skip this flash.
            self._glow_anim = None
            self._glow_effect = None

    # -- retranslation ----------------------------------------------------------

    def retranslate(self, lang: str) -> None:
        """Live language switch for the widgets the generic sweep cannot see."""
        self.lang = lang
        for combo in (self.cb_interval, self.cb_playback):
            items = getattr(combo, "_en_items", [])
            for index, english in enumerate(items):
                if index < combo.count():
                    combo.setItemText(index, tr(english, lang))
        self.refresh_pool_marks()
        self.refresh_stats()
        self.refresh_state()
