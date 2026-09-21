"""The Audio Hub inner pages: Presets, Playback, Voice, Ambience (T-1238-C3).

The Sound Settings dialog keeps its event table and grows a tab bar; each
page here is a plain QWidget builder bound to real stores and controllers.
Nothing on these pages is decorative: every button either persists something
or drives the one AudioHub.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fastprompter.core import sound_library
from fastprompter.core.ambience_engine import (
    REPEAT_EVERY_INTERVAL,
    REPEAT_LOOP,
    REPEAT_ON_ENTER,
    TRIGGER_ALWAYS,
    TRIGGER_TIME_WINDOW,
    TRIGGER_WEATHER,
    TRIGGER_WEEKDAY,
    WEATHER_CONDITIONS,
    WEEKDAY_NAMES,
    AmbienceRule,
)
from fastprompter.core.ambience_store import new_rule_id, rule_templates
from fastprompter.core.sound_presets import (
    PresetStore,
    apply_preset_to_profile,
    export_preset_json,
    export_preset_pack,
    import_preset_payload,
    missing_asset_events,
    open_preset_pack,
)
from fastprompter.core.translations import tr
from fastprompter.core.voice_engine import COUNTDOWN_THRESHOLDS, scan_goldsrc_folder
from fastprompter.core.voice_store import (
    PACK_TYPES,
    import_pack_files,
    imported_voice_root,
    pack_status,
)

#: (persisted value, English label) for every playback selector in the hub.
GLOBAL_MODE_CHOICES = (
    ("mix", "Overlay"),
    ("queue", "Stack"),
    ("replace", "Replace"),
)

EVENT_MODE_CHOICES = (("inherit", "Inherit"),) + GLOBAL_MODE_CHOICES

TRIGGER_CHOICES = (
    (TRIGGER_ALWAYS, "Always"),
    (TRIGGER_TIME_WINDOW, "Time window"),
    (TRIGGER_WEEKDAY, "Weekday"),
    (TRIGGER_WEATHER, "Weather"),
)

REPEAT_CHOICES = (
    (REPEAT_LOOP, "Loop"),
    (REPEAT_EVERY_INTERVAL, "Every interval"),
    (REPEAT_ON_ENTER, "On enter"),
)


def _label(text: str, lang: str) -> QLabel:
    widget = QLabel(tr(text, lang))
    widget._en_text = text
    return widget


def _button(text: str, lang: str, handler=None) -> QPushButton:
    widget = QPushButton(tr(text, lang))
    widget._en_text = text
    if handler is not None:
        widget.clicked.connect(handler)
    return widget


def _checkbox(text: str, lang: str) -> QCheckBox:
    widget = QCheckBox(tr(text, lang))
    widget._en_text = text
    return widget


def _combo(choices, lang: str) -> QComboBox:
    widget = QComboBox()
    for value, text in choices:
        widget.addItem(tr(text, lang), value)
    widget._en_items = [text for _value, text in choices]
    return widget


def _group(title: str, lang: str, *widgets) -> QGroupBox:
    box = QGroupBox(tr(title, lang))
    box._en_text = title
    layout = QVBoxLayout(box)
    layout.setContentsMargins(6, 4, 6, 6)
    layout.setSpacing(4)
    for widget in widgets:
        if isinstance(widget, QWidget):
            layout.addWidget(widget)
        else:
            layout.addLayout(widget)
    return box


def _row(*widgets) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return host


# ---------------------------------------------------------------------------
# C3.2 / C3.3 -- Presets + managed library
# ---------------------------------------------------------------------------


class PresetsPage(QWidget):
    """The REAL preset library: every action persists and survives restart."""

    def __init__(self, dialog, lang: str, store: PresetStore | None = None):
        super().__init__(dialog)
        self.dialog = dialog
        self.lang = lang
        self.store = store if store is not None else PresetStore()
        self._build()
        self.reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_a: self._refresh_detail())
        self.detail = QLabel("")
        self.detail.setWordWrap(True)

        actions = _row(
            _button("Apply", self.lang, self._apply),
            _button("Save", self.lang, self._save),
            _button("Save As", self.lang, self._save_as),
            _button("Duplicate", self.lang, self._duplicate),
            _button("Rename", self.lang, self._rename),
            _button("Delete", self.lang, self._delete),
            None,
        )
        transfer = _row(
            _button("Import", self.lang, self._import),
            _button("Export", self.lang, self._export),
            _button("Restore factory", self.lang, self._restore_factory),
            None,
        )
        library = _row(
            _button("Add sound...", self.lang, self._add_sound),
            _button("Add folder...", self.lang, self._add_folder),
            _button("Reveal imported library", self.lang, self._reveal_library),
            _button("Remove imported sound", self.lang, self._remove_imported),
            None,
        )
        layout.addWidget(_group("Presets", self.lang, self.list, actions,
                                transfer, self.detail))
        layout.addWidget(_group("Managed sound library", self.lang, library))

    # -- data ---------------------------------------------------------------

    def reload(self) -> None:
        selected = self.current_id()
        self.list.clear()
        for preset in self.store.list_presets():
            item = QListWidgetItem(str(preset.get("name") or preset["id"]))
            item.setData(Qt.ItemDataRole.UserRole, preset["id"])
            if preset.get("assets_missing"):
                item.setText(f"{item.text()} ({tr('incomplete', self.lang)})")
            self.list.addItem(item)
            if preset["id"] == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._refresh_detail()

    def current_id(self) -> str:
        item = self.list.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def current_preset(self) -> dict | None:
        preset_id = self.current_id()
        return self.store.get_preset(preset_id) if preset_id else None

    def _refresh_detail(self) -> None:
        preset = self.current_preset()
        if preset is None:
            self.detail.setText("")
            return
        missing = missing_asset_events(preset, sound_library.packaged_root())
        parts = [str(preset.get("description") or "")]
        if preset.get("assets_missing"):
            parts.append(tr(
                "This preset ships as a definition only: map your own files.",
                self.lang))
        if missing:
            parts.append(
                f"{tr('Missing assets', self.lang)}: {len(missing)}")
        self.detail.setText("\n".join(p for p in parts if p))

    # -- actions -------------------------------------------------------------

    def _apply(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        apply_preset_to_profile(preset, self.dialog._data)
        manager = self.dialog._sound_manager
        manager.invalidate_cache()
        manager.reload_playback_mode()
        self.dialog.reload_after_preset()

    def _current_definition(self, preset_id: str, name: str) -> dict:
        events = {
            event: dict(config) for event, config in
            (self.dialog._data.get("sound_events") or {}).items()
            if isinstance(config, dict)
        }
        return {
            "schema_version": 1,
            "id": preset_id,
            "name": name,
            "description": "",
            "builtin": False,
            "assets_missing": False,
            "global_mode": self.dialog._sound_manager.persisted_global_mode(),
            "events": events,
        }

    def _save(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        definition = self._current_definition(
            preset["id"], str(preset.get("name") or preset["id"]))
        definition["builtin"] = bool(preset.get("builtin"))
        self.store.upsert(definition, user_override=bool(preset.get("builtin")))
        self.reload()

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Save As", self.lang),
                                        tr("Preset name", self.lang))
        if not ok or not name.strip():
            return
        preset_id = f"preset_user_{abs(hash(name.strip())) % 10**10}"
        self.store.upsert(self._current_definition(preset_id, name.strip()))
        self.reload()

    def _duplicate(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        clone = dict(preset)
        clone["id"] = f"{preset['id']}_copy_{abs(hash(preset['id'])) % 10**6}"
        clone["name"] = f"{preset.get('name')} (copy)"
        clone["builtin"] = False
        self.store.upsert(clone)
        self.reload()

    def _rename(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        name, ok = QInputDialog.getText(
            self, tr("Rename", self.lang), tr("Preset name", self.lang),
            text=str(preset.get("name") or ""))
        if ok and name.strip():
            self.store.rename(preset["id"], name.strip())
            self.reload()

    def _delete(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        self.store.delete(preset["id"])
        self.reload()

    def _restore_factory(self) -> None:
        self.store.restore_factory()
        self.reload()

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("Import preset", self.lang), "",
            "FastPrompter sound (*.fpsoundpreset.json *.fpsoundpack)")
        if not path:
            return
        try:
            payload = open(path, "rb").read()
            if path.lower().endswith(".fpsoundpack"):
                definition, sounds = open_preset_pack(payload)
                import json as _json

                import_preset_payload(
                    _json.dumps(definition).encode("utf-8"), self.store,
                    sounds_dir=sound_library.ensure_managed_root(),
                    pack_sounds=sounds)
            else:
                import_preset_payload(payload, self.store)
        except Exception as exc:
            QMessageBox.warning(self, tr("Import failed", self.lang), str(exc))
            return
        self.reload()

    def _export(self) -> None:
        preset = self.current_preset()
        if preset is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("Export preset", self.lang),
            f"{preset.get('name') or preset['id']}.fpsoundpack",
            "FastPrompter pack (*.fpsoundpack);;Preset (*.fpsoundpreset.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".fpsoundpack"):
                payload, _included = export_preset_pack(
                    preset, sound_library.packaged_root())
            else:
                payload = export_preset_json(preset)
            with open(path, "wb") as handle:
                handle.write(payload)
        except Exception as exc:
            QMessageBox.warning(self, tr("Export failed", self.lang), str(exc))

    # -- managed library ------------------------------------------------------

    def _add_sound(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, tr("Add sound", self.lang), "", "WAV (*.wav)")
        added = sum(1 for path in paths if sound_library.import_file(path))
        if added:
            self.dialog.reload_sound_library()

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("Add folder", self.lang))
        if not folder:
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".wav"):
                if sound_library.import_file(os.path.join(folder, name)):
                    added += 1
        if added:
            self.dialog.reload_sound_library()

    def _reveal_library(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(sound_library.ensure_managed_root()))

    def _remove_imported(self) -> None:
        refs = sound_library.list_managed_sounds()
        if not refs:
            QMessageBox.information(
                self, tr("Managed sound library", self.lang),
                tr("Nothing has been imported yet.", self.lang))
            return
        ref, ok = QInputDialog.getItem(
            self, tr("Remove imported sound", self.lang),
            tr("Imported sound", self.lang), refs, 0, False)
        if not ok or not ref:
            return
        affected = self.dialog.events_using_ref(ref)
        message = tr("Remove this file from the managed library?", self.lang)
        # CORE-004 (audit/10): the Audio Hub used to see only current-profile
        # events. Ask the ONE canonical cross-store enumerator so Problip pool,
        # saved presets and saved ambience rules are reported too; an
        # unreadable store is surfaced as unknown impact, not silence.
        from fastprompter.core.sound_dependencies import dependencies_for_ref
        deps = dependencies_for_ref(
            ref, data=getattr(self.dialog, "_data", None),
            problip_sound_ids=None)
        extra = [
            f"{tr('Preset', self.lang)}: {pid}" for pid in deps.presets
        ] + [
            f"{tr('Ambience rule', self.lang)}: {rid}"
            for rid in deps.ambience_rules
        ] + [
            f"{tr('Unknown impact', self.lang)}: {store}"
            for store in deps.impact_unknown
        ]
        if affected or extra:
            message += "\n" + tr("Still mapped by", self.lang) + ": " + \
                ", ".join(list(affected) + extra)
        confirm = QMessageBox.question(
            self, tr("Remove imported sound", self.lang), message)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        sound_library.remove_managed_sound(ref)
        self.dialog.reload_sound_library()


# ---------------------------------------------------------------------------
# C3.4 / C3.5 -- Playback + STOP ALL
# ---------------------------------------------------------------------------


class PlaybackPage(QWidget):
    """The global Overlay/Stack/Replace setting and a truthful backend report."""

    def __init__(self, dialog, lang: str):
        super().__init__(dialog)
        self.dialog = dialog
        self.lang = lang
        self._loading = False
        self._build()
        self.reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.cb_global = _combo(GLOBAL_MODE_CHOICES, self.lang)
        self.cb_global.currentIndexChanged.connect(self._on_global_changed)
        self.lbl_global_help = _label(
            "Overlay lets different sounds play together. Stack plays them "
            "one after another in order. Replace lets the newest sound stop "
            "the current one. Ambience is never affected; only STOP ALL "
            "SOUND and Stop ambience silence it.", self.lang)
        self.lbl_global_help.setWordWrap(True)

        self.lbl_backend = QLabel("")
        self.lbl_backend.setWordWrap(True)
        self.lbl_channels = QLabel("")
        # T-1242 spec B8: the truthful, single-sourced engine line.
        self.lbl_engine_state = QLabel("")
        self.lbl_engine_state.setWordWrap(True)
        self.btn_refresh = _button("Refresh", self.lang, self.reload)
        self.btn_stop_all = _button("STOP ALL SOUND", self.lang,
                                    self._on_stop_all)

        layout.addWidget(_group("Global playback", self.lang,
                                _row(self.cb_global, None),
                                self.lbl_global_help))
        self.cb_render = QCheckBox(tr(
            "Pre-render sounds to the output device rate", self.lang))
        self.cb_render.setToolTip(tr(
            "On: each WAV is converted once to the device's own sample rate "
            "so the driver never resamples it. Off: the original file is "
            "played as it ships. Turn it off to compare if a sound seems "
            "coloured.", self.lang))
        self.cb_render.toggled.connect(self._on_render_toggled)

        self.cb_edge_pad = QCheckBox(tr(
            "Add silent margins to short sounds", self.lang))
        self.cb_edge_pad.setToolTip(tr(
            "A very short cue makes the output device open and close its "
            "stream inside a few milliseconds, and that transition can clip "
            "the attack and the tail. A little silence before and after the "
            "sound moves the transition off the audio. Nothing is faded and "
            "no sample is changed.", self.lang))
        self.cb_edge_pad.toggled.connect(self._on_edge_pad_toggled)

        layout.addWidget(_group("Engine", self.lang, self.lbl_backend,
                                self.lbl_channels, self.lbl_engine_state,
                                self.cb_render,
                                self.cb_edge_pad,
                                _row(self.btn_refresh, None)))
        layout.addWidget(_group("Emergency", self.lang,
                                _row(self.btn_stop_all, None)))
        layout.addStretch(1)

    def reload(self) -> None:
        manager = self.dialog._sound_manager
        status = manager.backend_status()
        self._loading = True
        try:
            index = self.cb_global.findData(manager.persisted_global_mode())
            self.cb_global.setCurrentIndex(max(0, index))
        finally:
            self._loading = False
        # T-1242 spec B4/B5: one call applies the persisted policy, clamps
        # pad to render, and returns the effective runtime values that the
        # transport will actually use -- the checkboxes below are the VIEW
        # of exactly that.
        effective_render, effective_pad = manager.apply_device_render_setting()
        from fastprompter.core.audio_render import (
            device_sample_rate,
        )

        self._loading = True
        try:
            self.cb_render.setChecked(effective_render)
            self.cb_edge_pad.setChecked(effective_pad)
            self.cb_edge_pad.setEnabled(effective_render)
        finally:
            self._loading = False
        rate = device_sample_rate()
        if rate:
            self.cb_render.setText(
                tr("Pre-render sounds to the output device rate", self.lang)
                + f" ({int(rate)} Hz)")
        # T-1242 spec B8: the engine line states the ACTIVE policy, sourced
        # from the same runtime the transport consumes -- no decorative text.
        self.lbl_engine_state.setText(
            f"{tr('Engine state', self.lang)}: "
            f"{tr('Pre-render', self.lang)}: "
            f"{'ON' if effective_render else 'OFF'}   "
            f"{tr('Silent margins', self.lang)}: "
            f"{'ON' if effective_pad else 'OFF'}   "
            f"{tr('Transport', self.lang)}: "
            f"{status.get('backend', '?')}")
        mixing = bool(status.get("capability_mixing"))
        # C3.4: never present Overlay as available on a backend that cannot mix.
        self.cb_global.setEnabled(mixing)
        backend = status.get("backend", "?")
        if mixing:
            text = f"{tr('Mixer available', self.lang)} ({backend})"
        else:
            text = (f"{tr('DEGRADED BACKEND', self.lang)} ({backend}): "
                    + tr("no real mixing; sounds cannot overlap on this "
                         "system, so Overlay/Stack/Replace are unavailable.",
                         self.lang))
        self.lbl_backend.setText(text)
        self.lbl_channels.setText(
            f"{tr('Active transient channels', self.lang)}: "
            f"{status.get('transient_channels', 0)}   "
            f"{tr('Queue depth', self.lang)}: {status.get('queue_depth', 0)}   "
            f"{tr('Active phrases', self.lang)}: "
            f"{status.get('active_sequences', 0)}")

    def _on_render_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        manager = self.dialog._sound_manager
        self.dialog._data[manager.DEVICE_RENDER_KEY] = (
            "True" if checked else "False")
        manager.apply_device_render_setting()
        manager.invalidate_cache()
        if hasattr(self.dialog, "_touch"):
            self.dialog._touch()
        # T-1242 spec B4: the render toggle changes pad's enablement, so the
        # view must be re-stamped from the model immediately -- otherwise the
        # pad checkbox keeps its old disabled/checked state until a manual
        # Refresh (part of the "toggle does not stick" report).
        self.reload()

    def _on_edge_pad_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        manager = self.dialog._sound_manager
        self.dialog._data[manager.EDGE_PAD_KEY] = (
            "True" if checked else "False")
        manager.apply_device_render_setting()
        manager.invalidate_cache()
        if hasattr(self.dialog, "_touch"):
            self.dialog._touch()

    def _on_global_changed(self, _index: int) -> None:
        if self._loading:
            return
        mode = self.cb_global.currentData()
        self.dialog._sound_manager.set_playback_mode(mode, persist=True)
        self.dialog._touch()

    def _on_stop_all(self) -> None:
        self.dialog._sound_manager.stop_all_sound()
        controller = getattr(self.dialog.main_win, "ambience_controller", None)
        if controller is not None:
            controller.stop()
        self.reload()


# ---------------------------------------------------------------------------
# C3.6 / C3.8 -- Voice
# ---------------------------------------------------------------------------


class VoicePage(QWidget):
    """Voice countdown wiring, pack readiness and GoldSrc/AMX import."""

    PACK_LABELS = (("vox", "VOX"), ("fvox", "FVOX"), ("gman", "G-Man"),
                   ("amx_ultimate", "AMX Ultimate"))

    def __init__(self, dialog, lang: str, controller=None):
        super().__init__(dialog)
        self.dialog = dialog
        self.lang = lang
        self.controller = controller
        self._loading = False
        self._build()
        self.reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.cb_enabled = _checkbox("Enabled", self.lang)
        self.cb_enabled.toggled.connect(
            lambda v: self._persist(enabled=bool(v)))
        self.cb_pack = _combo(self.PACK_LABELS, self.lang)
        self.cb_pack.currentIndexChanged.connect(
            lambda _i: self._persist(pack=self.cb_pack.currentData()))
        self.cb_timers = _checkbox("Normal timers", self.lang)
        self.cb_timers.toggled.connect(
            lambda v: self._persist(source_timers=bool(v)))
        self.cb_limits = _checkbox("AI Limits", self.lang)
        self.cb_limits.toggled.connect(
            lambda v: self._persist(source_limits=bool(v)))

        self.threshold_boxes: dict[int, QCheckBox] = {}
        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        for seconds, label in COUNTDOWN_THRESHOLDS:
            box = _checkbox(label, self.lang)
            box.toggled.connect(lambda _v: self._persist_thresholds())
            self.threshold_boxes[seconds] = box
            threshold_row.addWidget(box)
        threshold_row.addStretch(1)
        threshold_host = QWidget()
        threshold_host.setLayout(threshold_row)

        self.cb_mode = _combo(EVENT_MODE_CHOICES, self.lang)
        self.cb_mode.currentIndexChanged.connect(
            lambda _i: self._persist(mode=self.cb_mode.currentData()))
        self.sp_volume = QSpinBox()
        self.sp_volume.setRange(0, 100)
        self.sp_volume.setSuffix(" %")
        self.sp_volume.valueChanged.connect(
            lambda v: self._persist(volume_percent=int(v)))

        self.btn_test = _button("Test 30 minutes remaining", self.lang,
                                self._on_test)
        self.btn_import = _button("Import GoldSrc / AMX...", self.lang,
                                  self._on_import)
        self.btn_open = _button("Open imported folder", self.lang,
                                self._on_open_folder)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)

        layout.addWidget(_group("Voice countdown", self.lang,
                                _row(self.cb_enabled, self.cb_pack, None)))
        layout.addWidget(_group("Sources", self.lang,
                                _row(self.cb_timers, self.cb_limits, None)))
        layout.addWidget(_group("Thresholds", self.lang, threshold_host))
        layout.addWidget(_group("Playback", self.lang,
                                _row(self.cb_mode, _label("Volume:", self.lang),
                                     self.sp_volume, None)))
        layout.addWidget(_group("Packs", self.lang, self.lbl_status,
                                _row(self.btn_test, self.btn_import,
                                     self.btn_open, None)))
        layout.addStretch(1)

    def reload(self) -> None:
        self._loading = True
        try:
            if self.controller is not None:
                settings = self.controller.settings
                self.cb_enabled.setChecked(settings["enabled"])
                index = self.cb_pack.findData(settings["pack"])
                self.cb_pack.setCurrentIndex(max(0, index))
                self.cb_timers.setChecked(settings["source_timers"])
                self.cb_limits.setChecked(settings["source_limits"])
                for seconds, box in self.threshold_boxes.items():
                    box.setChecked(seconds in settings["thresholds"])
                mode_index = self.cb_mode.findData(settings["mode"])
                self.cb_mode.setCurrentIndex(max(0, mode_index))
                self.sp_volume.setValue(settings["volume_percent"])
            else:
                self.setEnabled(False)
        finally:
            self._loading = False
        self.refresh_status()

    def refresh_status(self) -> None:
        # ONE scan for every pack: pack_status() walks whole fragment folders
        # (VOX alone is 600+ files), so calling it per row cost seconds.
        status = pack_status()
        lines = []
        for kind, label in self.PACK_LABELS:
            info = status.get(kind, {})
            ready = tr("ready", self.lang) if info.get("is_ready") else tr(
                "missing", self.lang)
            source = (tr("imported", self.lang) if info.get("imported")
                      else tr("bundled", self.lang))
            lines.append(f"{label}: {ready} — {info.get('fragment_count', 0)} "
                         f"{tr('clips', self.lang)} ({source})")
        self.lbl_status.setText("\n".join(lines))

    def _persist(self, **changes) -> None:
        if self._loading or self.controller is None:
            return
        self.controller.update_settings(**changes)

    def _persist_thresholds(self) -> None:
        if self._loading or self.controller is None:
            return
        selected = [seconds for seconds, box in self.threshold_boxes.items()
                    if box.isChecked()]
        self.controller.update_settings(thresholds=selected)

    def _on_test(self) -> None:
        if self.controller is None:
            return
        ok, message = self.controller.test_phrase(1800)
        if not ok:
            QMessageBox.information(self, tr("Voice", self.lang), message)

    def _on_import(self) -> None:
        """C3.8: ONE user-selected root; scan it and nothing else."""
        if self.controller is None:
            return
        root = QFileDialog.getExistingDirectory(
            self, tr("Select the GoldSrc sound folder", self.lang))
        if not root:
            return
        found = scan_goldsrc_folder(root)
        total = sum(len(paths) for paths in found.values())
        if not total:
            QMessageBox.information(
                self, tr("Import GoldSrc / AMX...", self.lang),
                tr("No recognisable voice fragments were found there.",
                   self.lang))
            return
        summary = "\n".join(
            f"{kind}: {len(paths)}" for kind, paths in sorted(found.items())
            if paths)
        confirm = QMessageBox.question(
            self, tr("Import GoldSrc / AMX...", self.lang),
            f"{tr('Copy these into the managed library?', self.lang)}\n{summary}")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        copied = 0
        for kind, paths in found.items():
            if kind in PACK_TYPES:
                copied += import_pack_files(paths, kind)
        QMessageBox.information(
            self, tr("Import GoldSrc / AMX...", self.lang),
            f"{copied} {tr('clips imported', self.lang)}")
        self.refresh_status()

    def _on_open_folder(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        root = imported_voice_root(self.cb_pack.currentData() or "vox")
        os.makedirs(root, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(root))


# ---------------------------------------------------------------------------
# C3.9 / C3.10 / C3.11 -- Ambience
# ---------------------------------------------------------------------------


_COL_ON, _COL_NAME, _COL_SOUND, _COL_TRIGGER, _COL_CONDITION, _COL_REPEAT, \
    _COL_VOLUME, _COL_FADE, _COL_TEST = range(9)


class AmbienceRuleDialog(QDialog):
    """Edit ONE persisted ambience rule."""

    def __init__(self, parent, rule: AmbienceRule, lang: str, sound_refs):
        super().__init__(parent)
        self.lang = lang
        self.rule = rule
        self.setWindowTitle(tr("Ambience rule", lang))
        form = QFormLayout(self)

        self.ed_name = QLineEdit(rule.name)
        self.cb_sound = QComboBox()
        self.cb_sound.setEditable(False)
        for ref in sound_refs:
            self.cb_sound.addItem(ref, ref)
        if rule.sound_ref and self.cb_sound.findData(rule.sound_ref) < 0:
            self.cb_sound.addItem(rule.sound_ref, rule.sound_ref)
        self.cb_sound.setCurrentIndex(max(0, self.cb_sound.findData(rule.sound_ref)))

        self.cb_trigger = _combo(TRIGGER_CHOICES, lang)
        self.cb_trigger.setCurrentIndex(max(0, self.cb_trigger.findData(rule.trigger)))
        self.ed_start = QLineEdit(rule.start)
        self.ed_end = QLineEdit(rule.end)
        self.cb_weekday = QComboBox()
        for name in WEEKDAY_NAMES:
            self.cb_weekday.addItem(tr(name.capitalize(), lang), name)
        self.cb_weekday.setCurrentIndex(max(0, self.cb_weekday.findData(rule.weekday)))
        self.cb_weather = QComboBox()
        for name in WEATHER_CONDITIONS:
            self.cb_weather.addItem(tr(name.capitalize(), lang), name)
        self.cb_weather.setCurrentIndex(max(0, self.cb_weather.findData(rule.weather)))

        self.cb_repeat = _combo(REPEAT_CHOICES, lang)
        self.cb_repeat.setCurrentIndex(max(0, self.cb_repeat.findData(rule.repeat)))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(1, 86400)
        self.sp_interval.setSuffix(" s")
        self.sp_interval.setValue(rule.interval_seconds)
        self.sp_volume = QDoubleSpinBox()
        self.sp_volume.setRange(0.0, 1.0)
        self.sp_volume.setSingleStep(0.05)
        self.sp_volume.setValue(rule.volume)
        self.sp_fade_in = QSpinBox()
        self.sp_fade_in.setRange(0, 10_000)
        self.sp_fade_in.setSuffix(" ms")
        self.sp_fade_in.setValue(rule.fade_in_ms)
        self.sp_fade_out = QSpinBox()
        self.sp_fade_out.setRange(0, 10_000)
        self.sp_fade_out.setSuffix(" ms")
        self.sp_fade_out.setValue(rule.fade_out_ms)
        self.cb_enabled = _checkbox("Enabled", lang)
        self.cb_enabled.setChecked(rule.enabled)

        form.addRow(tr("Name", lang), self.ed_name)
        form.addRow(tr("Sound", lang), self.cb_sound)
        form.addRow(tr("Trigger", lang), self.cb_trigger)
        form.addRow(tr("From", lang), self.ed_start)
        form.addRow(tr("To", lang), self.ed_end)
        form.addRow(tr("Weekday", lang), self.cb_weekday)
        form.addRow(tr("Weather", lang), self.cb_weather)
        form.addRow(tr("Repeat", lang), self.cb_repeat)
        form.addRow(tr("Interval", lang), self.sp_interval)
        form.addRow(tr("Volume", lang), self.sp_volume)
        form.addRow(tr("Fade in", lang), self.sp_fade_in)
        form.addRow(tr("Fade out", lang), self.sp_fade_out)
        form.addRow("", self.cb_enabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_rule(self) -> AmbienceRule:
        self.rule.name = self.ed_name.text().strip() or self.rule.name
        self.rule.sound_ref = str(self.cb_sound.currentData() or "")
        self.rule.trigger = self.cb_trigger.currentData()
        self.rule.start = self.ed_start.text().strip() or "00:00"
        self.rule.end = self.ed_end.text().strip() or "23:59"
        self.rule.weekday = self.cb_weekday.currentData()
        self.rule.weather = self.cb_weather.currentData()
        self.rule.repeat = self.cb_repeat.currentData()
        self.rule.interval_seconds = self.sp_interval.value()
        self.rule.volume = self.sp_volume.value()
        self.rule.fade_in_ms = self.sp_fade_in.value()
        self.rule.fade_out_ms = self.sp_fade_out.value()
        # A rule with no sound can never be enabled: it would claim to run
        # while being silent forever.
        self.rule.enabled = bool(self.cb_enabled.isChecked()
                                 and self.rule.sound_ref)
        return self.rule


class AmbiencePage(QWidget):
    """Integrated ambience rule table + inspector bound to AmbienceController."""

    HEADERS = ("On", "Name", "Sound", "Trigger", "Condition", "Repeat",
               "Volume", "Fade", "Test")

    def __init__(self, dialog, lang: str, controller=None):
        super().__init__(dialog)
        self.dialog = dialog
        self.lang = lang
        self.controller = controller
        self._loading = False
        self._updating_inspector = False
        self._build()
        self.reload()

    def _build(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 1. Ambience layers table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(
            [tr(h, self.lang) for h in self.HEADERS])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_ON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_SOUND, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_TRIGGER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_CONDITION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_REPEAT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_VOLUME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_FADE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_TEST, QHeaderView.ResizeMode.ResizeToContents)

        table_actions = _row(
            _button("Add rule", self.lang, self._add),
            _button("Duplicate", self.lang, self._duplicate),
            _button("Delete", self.lang, self._delete),
            _button("Add templates", self.lang, self._add_templates),
            None,
        )

        table_group = _group("Ambience layers", self.lang, self.table, table_actions)
        main_layout.addWidget(table_group, 1)

        # 2. Rule Inspector
        self.inspector_group = QGroupBox(tr("Rule Inspector", self.lang))
        insp_layout = QVBoxLayout(self.inspector_group)
        insp_layout.setContentsMargins(6, 6, 6, 6)
        insp_layout.setSpacing(4)

        self.lbl_inspector = QLabel(tr("Select a rule to view and edit its properties", self.lang))
        insp_layout.addWidget(self.lbl_inspector)

        # Inspector controls row 1: Name, Sound, Enabled
        self.insp_name = QLineEdit()
        self.insp_name.setPlaceholderText(tr("Rule name", self.lang))
        self.insp_name.textEdited.connect(self._on_name_edited)

        self.insp_sound = QComboBox()
        self.insp_sound.currentIndexChanged.connect(self._on_sound_changed)

        self.insp_enabled = _checkbox("Enabled", self.lang)
        self.insp_enabled.clicked.connect(self._on_enabled_clicked)

        r1 = _row(
            _label("Name:", self.lang), self.insp_name,
            _label("Sound:", self.lang), self.insp_sound,
            self.insp_enabled,
            None,
        )
        insp_layout.addWidget(r1)

        # Inspector controls row 2: Trigger, Schedule / Weekday / Weather
        self.insp_trigger = _combo(TRIGGER_CHOICES, self.lang)
        self.insp_trigger.currentIndexChanged.connect(self._on_trigger_changed)

        # Conditional: Time window container
        self.insp_time_container = QWidget()
        time_layout = QHBoxLayout(self.insp_time_container)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(4)
        self.insp_start = QLineEdit("00:00")
        self.insp_start.setFixedWidth(50)
        self.insp_start.textEdited.connect(self._on_time_start_edited)
        self.insp_end = QLineEdit("23:59")
        self.insp_end.setFixedWidth(50)
        self.insp_end.textEdited.connect(self._on_time_end_edited)
        time_layout.addWidget(_label("From:", self.lang))
        time_layout.addWidget(self.insp_start)
        time_layout.addWidget(_label("To:", self.lang))
        time_layout.addWidget(self.insp_end)

        self.insp_days: dict[str, QCheckBox] = {}
        for day in WEEKDAY_NAMES:
            cb = QCheckBox(day[:2].capitalize())
            cb.setToolTip(tr(day.capitalize(), self.lang))
            cb.toggled.connect(self._on_weekday_box_toggled)
            time_layout.addWidget(cb)
            self.insp_days[day] = cb

        # Conditional: Weekday container
        self.insp_weekday_container = QWidget()
        weekday_layout = QHBoxLayout(self.insp_weekday_container)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        weekday_layout.setSpacing(4)
        self.insp_weekday = QComboBox()
        for d in WEEKDAY_NAMES:
            self.insp_weekday.addItem(tr(d.capitalize(), self.lang), d)
        self.insp_weekday.currentIndexChanged.connect(self._on_weekday_changed)
        weekday_layout.addWidget(_label("Day:", self.lang))
        weekday_layout.addWidget(self.insp_weekday)

        # Conditional: Weather container
        self.insp_weather_container = QWidget()
        weather_layout = QHBoxLayout(self.insp_weather_container)
        weather_layout.setContentsMargins(0, 0, 0, 0)
        weather_layout.setSpacing(4)
        self.insp_weather = QComboBox()
        for w in WEATHER_CONDITIONS:
            self.insp_weather.addItem(tr(w.capitalize(), self.lang), w)
        self.insp_weather.currentIndexChanged.connect(self._on_weather_changed)
        weather_layout.addWidget(_label("Condition:", self.lang))
        weather_layout.addWidget(self.insp_weather)

        r2 = _row(
            _label("Trigger:", self.lang), self.insp_trigger,
            self.insp_time_container,
            self.insp_weekday_container,
            self.insp_weather_container,
            None,
        )
        insp_layout.addWidget(r2)

        # Inspector controls row 3: Repeat, Interval, Volume, Fade In, Fade Out
        self.insp_repeat = _combo(REPEAT_CHOICES, self.lang)
        self.insp_repeat.currentIndexChanged.connect(self._on_repeat_changed)

        self.insp_interval_container = QWidget()
        interval_layout = QHBoxLayout(self.insp_interval_container)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.setSpacing(4)
        self.insp_interval = QSpinBox()
        self.insp_interval.setRange(1, 86400)
        self.insp_interval.setSuffix(" s")
        self.insp_interval.valueChanged.connect(self._on_interval_changed)
        interval_layout.addWidget(_label("Interval:", self.lang))
        interval_layout.addWidget(self.insp_interval)

        self.insp_volume = QDoubleSpinBox()
        self.insp_volume.setRange(0.0, 1.0)
        self.insp_volume.setSingleStep(0.05)
        self.insp_volume.setDecimals(2)
        self.insp_volume.valueChanged.connect(self._on_volume_changed)

        self.insp_fade_in = QSpinBox()
        self.insp_fade_in.setRange(0, 10_000)
        self.insp_fade_in.setSuffix(" ms")
        self.insp_fade_in.valueChanged.connect(self._on_fade_in_changed)

        self.insp_fade_out = QSpinBox()
        self.insp_fade_out.setRange(0, 10_000)
        self.insp_fade_out.setSuffix(" ms")
        self.insp_fade_out.valueChanged.connect(self._on_fade_out_changed)

        r3 = _row(
            _label("Repeat:", self.lang), self.insp_repeat,
            self.insp_interval_container,
            _label("Vol:", self.lang), self.insp_volume,
            _label("Fade in:", self.lang), self.insp_fade_in,
            _label("Fade out:", self.lang), self.insp_fade_out,
            None,
        )
        insp_layout.addWidget(r3)
        main_layout.addWidget(self.inspector_group)

        # 3. Truthful Transport & Status
        self.btn_start = _button("Start ambience", self.lang, self._start)
        self.btn_pause = _button("Pause ambience", self.lang, self._pause_or_resume)
        self.btn_stop = _button("Stop ambience", self.lang, self._stop)
        self.cb_autostart = _checkbox("Start ambience with FastPrompter", self.lang)
        self.cb_autostart.toggled.connect(self._on_autostart_toggled)
        self.lbl_state = QLabel("")

        # Retained for backwards compatibility with tests
        self.btn_ambience_toggle = QPushButton()
        self.btn_ambience_toggle.setCheckable(True)
        self.btn_ambience_toggle.toggled.connect(self._on_toggle)

        transport_row = _row(
            self.btn_start,
            self.btn_pause,
            self.btn_stop,
            self.cb_autostart,
            self.lbl_state,
            None,
        )
        main_layout.addWidget(transport_row)

        if self.controller is not None:
            try:
                self.controller.stateChanged.connect(
                    lambda _state: self._refresh_state())
            except (AttributeError, TypeError):
                pass

        # 4. Opt-in Weather
        self.cb_weather_enabled = _checkbox("Use weather (opt-in)", self.lang)
        self.cb_weather_enabled.toggled.connect(lambda _v: self._save_weather())
        self.ed_place = QLineEdit()
        self.ed_place.setPlaceholderText(tr("Place label", self.lang))
        self.sp_lat = QDoubleSpinBox()
        self.sp_lat.setRange(-90.0, 90.0)
        self.sp_lat.setDecimals(4)
        self.sp_lon = QDoubleSpinBox()
        self.sp_lon.setRange(-180.0, 180.0)
        self.sp_lon.setDecimals(4)
        self.btn_weather_save = _button("Save location", self.lang, self._save_weather)
        self.btn_weather_refresh = _button("Refresh now", self.lang, self._refresh_weather)
        self.lbl_weather = QLabel("")
        self.lbl_weather.setWordWrap(True)

        weather_box = _group(
            "Weather", self.lang,
            _row(self.cb_weather_enabled, None),
            _row(_label("Place:", self.lang), self.ed_place,
                 _label("Lat:", self.lang), self.sp_lat,
                 _label("Lon:", self.lang), self.sp_lon,
                 self.btn_weather_save, self.btn_weather_refresh, None),
            self.lbl_weather)
        main_layout.addWidget(weather_box)

    # -- data -----------------------------------------------------------------

    def reload(self) -> None:
        if self.controller is None:
            self.setEnabled(False)
            return
        rules = self.controller.rules()
        selected_ids = {r.id for r in self.selected_rules()}
        self._loading = True
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                on = QCheckBox()
                on.setChecked(rule.enabled)
                on.toggled.connect(
                    lambda checked, rid=rule.id: self._toggle(rid, checked))
                self.table.setCellWidget(row, _COL_ON, on)
                self._set_cell(row, _COL_NAME, rule.name, rule.id)
                self._set_cell(row, _COL_SOUND,
                               rule.sound_ref or tr("(none)", self.lang))
                self._set_cell(row, _COL_TRIGGER, rule.trigger)
                self._set_cell(row, _COL_CONDITION, _condition_text(rule))
                self._set_cell(row, _COL_REPEAT, rule.repeat)
                self._set_cell(row, _COL_VOLUME, f"{rule.volume:.2f}")
                self._set_cell(row, _COL_FADE,
                               f"{rule.fade_in_ms}/{rule.fade_out_ms} ms")
                test = QPushButton("▶")
                test.setFixedWidth(28)
                test.clicked.connect(
                    lambda _c, rid=rule.id: self._test(rid))
                self.table.setCellWidget(row, _COL_TEST, test)
        finally:
            self.table.blockSignals(False)
            self._loading = False

        # Restore previous selection if possible, otherwise select row 0
        self.table.clearSelection()
        restored = False
        if selected_ids:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, _COL_NAME)
                if item and str(item.data(Qt.ItemDataRole.UserRole)) in selected_ids:
                    self.table.selectRow(row)
                    restored = True
        if not restored and len(rules) > 0:
            self.table.selectRow(0)

        self._on_selection_changed()
        self._refresh_state()
        self._load_weather()

    def _set_cell(self, row: int, column: int, text: str,
                  rule_id: str = "") -> None:
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if rule_id:
            item.setData(Qt.ItemDataRole.UserRole, rule_id)
        self.table.setItem(row, column, item)

    def selected_rules(self) -> list[AmbienceRule]:
        if self.controller is None:
            return []
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        rules = self.controller.rules()
        res = []
        for row in selected_rows:
            item = self.table.item(row, _COL_NAME)
            if item is not None:
                rule_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
                for r in rules:
                    if r.id == rule_id:
                        res.append(r)
                        break
        return res

    def selected_rule(self) -> AmbienceRule | None:
        rules = self.selected_rules()
        return rules[0] if rules else None

    # -- selection & inspector synchronization --------------------------------

    def _on_selection_changed(self) -> None:
        rules = self.selected_rules()
        self._updating_inspector = True
        try:
            if not rules:
                self.lbl_inspector.setText(tr("Select a rule to view and edit its properties", self.lang))
                self._enable_inspector(False)
                return

            self._enable_inspector(True)
            self._rebuild_sound_combo()

            if len(rules) == 1:
                rule = rules[0]
                self.lbl_inspector.setText(f"{tr('Rule', self.lang)}: {rule.name}")
                self.insp_name.setEnabled(True)
                self.insp_name.setText(rule.name)

                # Sound
                self._set_combo_value(self.insp_sound, rule.sound_ref)

                # Enabled
                self.insp_enabled.setTristate(False)
                self.insp_enabled.setChecked(rule.enabled)

                # Trigger
                self._set_combo_value(self.insp_trigger, rule.trigger)
                self._update_conditional_trigger(rule.trigger)

                # Time window
                self.insp_start.setText(rule.start)
                self.insp_end.setText(rule.end)
                for day, cb in self.insp_days.items():
                    cb.blockSignals(True)
                    cb.setChecked(day in (rule.weekdays or []))
                    cb.blockSignals(False)

                # Weekday
                self._set_combo_value(self.insp_weekday, rule.weekday)

                # Weather
                self._set_combo_value(self.insp_weather, rule.weather)

                # Repeat
                self._set_combo_value(self.insp_repeat, rule.repeat)
                self._update_conditional_repeat(rule.repeat)
                self.insp_interval.setValue(rule.interval_seconds)

                # Volume & fades
                self.insp_volume.setValue(rule.volume)
                self.insp_fade_in.setValue(rule.fade_in_ms)
                self.insp_fade_out.setValue(rule.fade_out_ms)
            else:
                # Multi-selection: mixed states
                self.lbl_inspector.setText(f"{len(rules)} {tr('rules selected', self.lang)}")
                self.insp_name.setEnabled(False)
                self.insp_name.setText(tr("— (multiple) —", self.lang))

                # Sound
                sounds = {r.sound_ref for r in rules}
                if len(sounds) == 1:
                    self._set_combo_value(self.insp_sound, rules[0].sound_ref)
                else:
                    self._set_combo_mixed(self.insp_sound)

                # Enabled
                enables = {r.enabled for r in rules}
                if len(enables) == 1:
                    self.insp_enabled.setTristate(False)
                    self.insp_enabled.setChecked(rules[0].enabled)
                else:
                    self.insp_enabled.setTristate(True)
                    self.insp_enabled.setCheckState(Qt.CheckState.PartiallyChecked)

                # Trigger
                triggers = {r.trigger for r in rules}
                if len(triggers) == 1:
                    self._set_combo_value(self.insp_trigger, rules[0].trigger)
                    self._update_conditional_trigger(rules[0].trigger)
                else:
                    self._set_combo_mixed(self.insp_trigger)
                    self._update_conditional_trigger("__all__")

                # Time window / Weekdays
                starts = {r.start for r in rules}
                self.insp_start.setText(rules[0].start if len(starts) == 1 else "")
                self.insp_start.setPlaceholderText("00:00" if len(starts) == 1 else "—")

                ends = {r.end for r in rules}
                self.insp_end.setText(rules[0].end if len(ends) == 1 else "")
                self.insp_end.setPlaceholderText("23:59" if len(ends) == 1 else "—")

                for day, cb in self.insp_days.items():
                    cb.blockSignals(True)
                    day_matches = [day in (r.weekdays or []) for r in rules]
                    if all(day_matches):
                        cb.setCheckState(Qt.CheckState.Checked)
                    elif not any(day_matches):
                        cb.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        cb.setCheckState(Qt.CheckState.PartiallyChecked)
                    cb.blockSignals(False)

                # Weekday
                weekdays = {r.weekday for r in rules}
                if len(weekdays) == 1:
                    self._set_combo_value(self.insp_weekday, rules[0].weekday)
                else:
                    self._set_combo_mixed(self.insp_weekday)

                # Weather
                weathers = {r.weather for r in rules}
                if len(weathers) == 1:
                    self._set_combo_value(self.insp_weather, rules[0].weather)
                else:
                    self._set_combo_mixed(self.insp_weather)

                # Repeat
                repeats = {r.repeat for r in rules}
                if len(repeats) == 1:
                    self._set_combo_value(self.insp_repeat, rules[0].repeat)
                    self._update_conditional_repeat(rules[0].repeat)
                else:
                    self._set_combo_mixed(self.insp_repeat)
                    self._update_conditional_repeat("__all__")

                # Volume
                volumes = {round(r.volume, 2) for r in rules}
                if len(volumes) == 1:
                    self.insp_volume.setValue(rules[0].volume)

                # Fades
                fade_ins = {r.fade_in_ms for r in rules}
                if len(fade_ins) == 1:
                    self.insp_fade_in.setValue(rules[0].fade_in_ms)

                fade_outs = {r.fade_out_ms for r in rules}
                if len(fade_outs) == 1:
                    self.insp_fade_out.setValue(rules[0].fade_out_ms)
        finally:
            self._updating_inspector = False

    def _enable_inspector(self, enabled: bool) -> None:
        for w in (self.insp_name, self.insp_sound, self.insp_enabled,
                  self.insp_trigger, self.insp_repeat, self.insp_volume,
                  self.insp_fade_in, self.insp_fade_out, self.insp_start,
                  self.insp_end, self.insp_weekday, self.insp_weather,
                  self.insp_interval):
            w.setEnabled(enabled)
        for cb in self.insp_days.values():
            cb.setEnabled(enabled)

    def _rebuild_sound_combo(self) -> None:
        current = self.insp_sound.currentData()
        self.insp_sound.blockSignals(True)
        try:
            self.insp_sound.clear()
            self.insp_sound.addItem(tr("(none)", self.lang), "")
            for ref in self._sound_refs():
                if ref:
                    self.insp_sound.addItem(ref, ref)
            idx = self.insp_sound.findData(current)
            if idx >= 0:
                self.insp_sound.setCurrentIndex(idx)
        finally:
            self.insp_sound.blockSignals(False)

    def _set_combo_mixed(self, combo: QComboBox) -> None:
        idx = combo.findData("__mixed__")
        if idx < 0:
            combo.insertItem(0, tr("— (mixed) —", self.lang), "__mixed__")
            idx = 0
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _set_combo_value(self, combo: QComboBox, value) -> None:
        mixed_idx = combo.findData("__mixed__")
        if mixed_idx >= 0:
            combo.removeItem(mixed_idx)
        idx = combo.findData(value)
        combo.blockSignals(True)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _update_conditional_trigger(self, trigger: str) -> None:
        show_all = (trigger == "__all__")
        self.insp_time_container.setVisible(show_all or trigger == TRIGGER_TIME_WINDOW)
        self.insp_weekday_container.setVisible(show_all or trigger == TRIGGER_WEEKDAY)
        self.insp_weather_container.setVisible(show_all or trigger == TRIGGER_WEATHER)

    def _update_conditional_repeat(self, repeat: str) -> None:
        show_all = (repeat == "__all__")
        self.insp_interval_container.setVisible(show_all or repeat == REPEAT_EVERY_INTERVAL)

    # -- atomic bulk editing --------------------------------------------------

    def _bulk_update(self, **kwargs) -> None:
        rules = self.selected_rules()
        if not rules or self.controller is None:
            return
        target_ids = {r.id for r in rules}
        all_rules = self.controller.rules()
        for r in all_rules:
            if r.id in target_ids:
                for k, v in kwargs.items():
                    setattr(r, k, v)
                # Invariant: a rule with no sound can never be enabled
                if not r.sound_ref:
                    r.enabled = False
        self.controller.store.save_rules(all_rules)
        self.controller.reload_rules()
        self._sync_table_cells_preserve_selection(target_ids)

    def _sync_table_cells_preserve_selection(self, target_ids=None) -> None:
        if self.controller is None:
            return
        rules = self.controller.rules()
        was_loading = self._loading
        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, _COL_NAME)
                rid = str(item.data(Qt.ItemDataRole.UserRole)) if item else ""
                if target_ids and rid not in target_ids:
                    continue
                rule = next((x for x in rules if x.id == rid), None)
                if rule is not None:
                    on_widget = self.table.cellWidget(row, _COL_ON)
                    if isinstance(on_widget, QCheckBox):
                        on_widget.blockSignals(True)
                        on_widget.setChecked(rule.enabled)
                        on_widget.blockSignals(False)
                    self.table.item(row, _COL_NAME).setText(rule.name)
                    self.table.item(row, _COL_SOUND).setText(rule.sound_ref or tr("(none)", self.lang))
                    self.table.item(row, _COL_TRIGGER).setText(rule.trigger)
                    self.table.item(row, _COL_CONDITION).setText(_condition_text(rule))
                    self.table.item(row, _COL_REPEAT).setText(rule.repeat)
                    self.table.item(row, _COL_VOLUME).setText(f"{rule.volume:.2f}")
                    self.table.item(row, _COL_FADE).setText(f"{rule.fade_in_ms}/{rule.fade_out_ms} ms")
        finally:
            self._loading = was_loading

    def _on_name_edited(self, text: str) -> None:
        if self._updating_inspector or self.controller is None:
            return
        rules = self.selected_rules()
        if len(rules) == 1:
            name = text.strip() or rules[0].name
            self._bulk_update(name=name)

    def _on_sound_changed(self, idx: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        val = self.insp_sound.currentData()
        if val == "__mixed__":
            return
        self._bulk_update(sound_ref=str(val or ""))

    def _on_enabled_clicked(self) -> None:
        if self._updating_inspector or self.controller is None:
            return
        checked = self.insp_enabled.isChecked()
        self.insp_enabled.setTristate(False)
        self.insp_enabled.setChecked(checked)
        self._bulk_update(enabled=checked)

    def _on_trigger_changed(self, idx: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        val = self.insp_trigger.currentData()
        if val == "__mixed__":
            return
        self._update_conditional_trigger(str(val))
        self._bulk_update(trigger=str(val))

    def _on_weekday_changed(self, idx: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        val = self.insp_weekday.currentData()
        if val == "__mixed__":
            return
        self._bulk_update(weekday=str(val))

    def _on_weather_changed(self, idx: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        val = self.insp_weather.currentData()
        if val == "__mixed__":
            return
        self._bulk_update(weather=str(val))

    def _on_repeat_changed(self, idx: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        val = self.insp_repeat.currentData()
        if val == "__mixed__":
            return
        self._update_conditional_repeat(str(val))
        self._bulk_update(repeat=str(val))

    def _on_interval_changed(self, val: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(interval_seconds=int(val))

    def _on_volume_changed(self, val: float) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(volume=float(val))

    def _on_fade_in_changed(self, val: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(fade_in_ms=int(val))

    def _on_fade_out_changed(self, val: int) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(fade_out_ms=int(val))

    def _on_time_start_edited(self, text: str) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(start=text.strip() or "00:00")

    def _on_time_end_edited(self, text: str) -> None:
        if self._updating_inspector or self.controller is None:
            return
        self._bulk_update(end=text.strip() or "23:59")

    def _on_weekday_box_toggled(self, _checked: bool) -> None:
        if self._updating_inspector or self.controller is None:
            return
        active_days = [day for day, cb in self.insp_days.items() if cb.isChecked()]
        self._bulk_update(weekdays=active_days)

    # -- actions ---------------------------------------------------------------

    def _sound_refs(self) -> list[str]:
        refs = list(self.dialog._available)
        refs += sound_library.list_managed_sounds()
        return refs

    def _add(self) -> None:
        if self.controller is None:
            return
        new_rule = AmbienceRule(id=new_rule_id(), name="Ambience", sound_ref="",
                                enabled=False)
        self.controller.save_rule(new_rule)
        self.reload()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, _COL_NAME)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == new_rule.id:
                self.table.selectRow(row)
                break
        self.insp_name.setFocus()

    def _edit(self) -> None:
        """Inline editing in the inspector; focuses name field if single rule selected."""
        rule = self.selected_rule()
        if rule is not None and self.insp_name.isEnabled():
            self.insp_name.setFocus()

    def _duplicate(self) -> None:
        if self.controller is None:
            return
        selected = self.selected_rules()
        if not selected:
            return
        new_ids = []
        for r in selected:
            rules = self.controller.duplicate_rule(r.id)
            if rules:
                new_ids.append(rules[-1].id)
        self.reload()
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, _COL_NAME)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) in new_ids:
                self.table.selectRow(row)

    def _delete(self) -> None:
        if self.controller is None:
            return
        selected = self.selected_rules()
        if not selected:
            return
        for r in selected:
            self.controller.delete_rule(r.id)
        self.reload()

    def _toggle(self, rule_id: str, checked: bool) -> None:
        if self._loading or self.controller is None:
            return
        for rule in self.controller.rules():
            if rule.id != rule_id:
                continue
            if checked and not rule.sound_ref:
                self.reload()
                return
            rule.enabled = bool(checked)
            self.controller.save_rule(rule)
            break
        self.reload()

    def _test(self, rule_id: str) -> None:
        if self.controller is None:
            return
        for rule in self.controller.rules():
            if rule.id == rule_id and rule.sound_ref:
                path = sound_library.resolve_sound_ref(rule.sound_ref)
                if path:
                    self.dialog._sound_manager.audio_hub().play(
                        path, event="ambience_test", bus="preview",
                        volume=rule.volume, mode="mix")
                return

    def _add_templates(self) -> None:
        """Offer the available templates and add only what the user picks.

        The old shape looped over every template and saved it, so one click
        silently inserted the whole set — the user could not see what was
        available, could not take one, and had to delete the rest. This is a
        compact chooser: template names first, one explicit choice adds one
        rule, and "Add all" exists only as its OWN explicit action.
        """
        if self.controller is None:
            return
        templates = rule_templates()
        if not templates:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setFont(self.font())
        for template in templates:
            menu.addAction(
                tr(template.name, self.lang),
                lambda t=template: self._add_one_template(t))
        menu.addSeparator()
        menu.addAction(
            tr("Add all templates", self.lang),
            lambda: self._add_templates_bulk(templates))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _add_one_template(self, template) -> None:
        """Add exactly ONE chosen template. Cancel/miss adds nothing."""
        if self.controller is None or template is None:
            return
        self.controller.save_rule(template)
        self.reload()

    def _add_templates_bulk(self, templates) -> None:
        """The deliberate, separately chosen "add everything" action."""
        if self.controller is None:
            return
        for template in templates:
            self.controller.save_rule(template)
        self.reload()

    # -- transport & autostart -------------------------------------------------

    def _start(self) -> None:
        if self.controller is not None:
            self.controller.start(persist=False)
            self._refresh_state()

    def _pause_or_resume(self) -> None:
        """Hold the layers, or let them run again. Reversible."""
        if self.controller is None:
            return
        if self.controller.state() == "paused":
            self.controller.resume()
        else:
            self.controller.pause()
        self._refresh_state()

    def _pause(self) -> None:
        if self.controller is not None:
            self.controller.pause()
            self._refresh_state()

    def _resume(self) -> None:
        if self.controller is not None:
            self.controller.resume()
            self._refresh_state()

    def _stop(self) -> None:
        if self.controller is not None:
            self.controller.stop_runtime_only()
            self._refresh_state()

    def _on_toggle(self, checked: bool) -> None:
        if self.controller is None or self._loading:
            return
        self.controller.toggle(bool(checked))
        self._refresh_state()

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self.controller is None or self._loading:
            return
        self.controller._remember(bool(checked))

    def ambience_toggle_text(self) -> str:
        return "Stop ambience" if self._runtime_on() else "Start ambience"

    def ambience_pause_text(self) -> str:
        paused = (self.controller is not None
                  and self.controller.state() == "paused")
        return "Resume ambience" if paused else "Pause ambience"

    def _runtime_on(self) -> bool:
        if self.controller is None:
            return False
        return self.controller.state() != "stopped"

    def _refresh_state(self) -> None:
        if self.controller is None:
            return
        state = self.controller.state()
        diagnostics = self.controller.engine.diagnostics
        active_count = len(diagnostics.get("active_layers", []))
        if state == "stopped":
            self.lbl_state.setText(tr("STOPPED", self.lang))
        elif state == "running":
            self.lbl_state.setText(f"{tr('RUNNING', self.lang)} · {active_count} {tr('active', self.lang)}")
        elif state == "paused":
            self.lbl_state.setText(f"{tr('PAUSED', self.lang)} · {active_count} {tr('held', self.lang)}")
        else:
            self.lbl_state.setText(tr(state.upper(), self.lang))

        self._apply_transport_controls(state)

        blocked = self.cb_autostart.blockSignals(True)
        try:
            self.cb_autostart.setChecked(self.controller.desired_enabled())
        finally:
            self.cb_autostart.blockSignals(blocked)

        button = getattr(self, "btn_ambience_toggle", None)
        if button is not None:
            running = self._runtime_on()
            label = self.ambience_toggle_text()
            blk = button.blockSignals(True)
            try:
                button.setChecked(running)
                button.setText(tr(label, self.lang))
                button._en_text = label
            finally:
                button.blockSignals(blk)

    def _apply_transport_controls(self, state: str) -> None:
        """One explicit button contract per runtime state (T-1273 corrective).

        The old predicate ``start enabled whenever state != running`` made
        PAUSED offer Start, so clicking it restarted stopped layers while the
        held ones stayed held — a second Start path with different semantics
        from Resume. The states are now exhaustive and mutually exclusive:

        * STOPPED -> Start on, Pause off, Stop off
        * RUNNING -> Start off, Pause on, Stop on
        * PAUSED  -> Start off, Resume on, Stop on

        Resume is the SECONDARY control (its label follows ``state``), so
        "Start while paused" is unreachable rather than merely discouraged.
        """
        paused = state == "paused"
        running = state == "running"
        stopped = not paused and not running
        self.btn_start.setEnabled(stopped)
        self.btn_pause.setEnabled(not stopped)
        pause_label = self.ambience_pause_text()
        self.btn_pause.setText(tr(pause_label, self.lang))
        self.btn_pause._en_text = pause_label
        self.btn_stop.setEnabled(not stopped)

    # -- weather ------------------------------------------------------------------

    def _load_weather(self) -> None:
        if self.controller is None:
            return
        config = self.controller.weather_config()
        self._loading = True
        try:
            self.cb_weather_enabled.setChecked(bool(config["enabled"]))
            self.ed_place.setText(config["label"])
            self.sp_lat.setValue(config["latitude"] or 0.0)
            self.sp_lon.setValue(config["longitude"] or 0.0)
        finally:
            self._loading = False
        condition = self.controller.current_weather()
        self.lbl_weather.setText(
            f"{tr('Current condition', self.lang)}: "
            f"{tr(condition, self.lang) if condition else tr('unknown', self.lang)}")

    def _save_weather(self) -> None:
        if self._loading or self.controller is None:
            return
        self.controller.set_weather_config(
            enabled=self.cb_weather_enabled.isChecked(),
            label=self.ed_place.text().strip(),
            latitude=self.sp_lat.value(),
            longitude=self.sp_lon.value())
        self._load_weather()

    def _refresh_weather(self) -> None:
        if self.controller is not None:
            self.controller.refresh_weather_async()


def _condition_text(rule: AmbienceRule) -> str:
    if rule.trigger == TRIGGER_TIME_WINDOW:
        days = ",".join(rule.weekdays) if rule.weekdays else "*"
        return f"{rule.start}-{rule.end} {days}"
    if rule.trigger == TRIGGER_WEEKDAY:
        return rule.weekday
    if rule.trigger == TRIGGER_WEATHER:
        return rule.weather
    return "-"
