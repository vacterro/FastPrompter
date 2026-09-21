"""Tests for reconstructed Ambience Workspace UX (Table + Inspector, Multi-select, Bulk edit, Truthful Transport)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from fastprompter.core.ambience_engine import (
    REPEAT_EVERY_INTERVAL,
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    TRIGGER_TIME_WINDOW,
    TRIGGER_WEATHER,
    TRIGGER_WEEKDAY,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.ambience_store import AmbienceStore, new_rule_id, rule_templates
from fastprompter.core.audio_hub import AudioHub, FakeMultiChannelTransport
from fastprompter.ui.ambience_controller import AmbienceController
from fastprompter.ui.audio_hub_pages import AmbiencePage

_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class _FakeManager:
    def __init__(self, hub):
        self._hub = hub
        self.stop_all_listeners = []

    def audio_hub(self):
        return self._hub

    def add_stop_all_listener(self, cb):
        self.stop_all_listeners.append(cb)

    def stop_all_sound(self):
        self._hub.stop_all()
        for cb in list(self.stop_all_listeners):
            cb()


class _MockDialog(QWidget):
    def __init__(self, manager):
        super().__init__()
        self._sound_manager = manager
        self._available = ["rain.wav", "wind.wav", "waves.wav", "birds.wav"]


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "audio.db"


@pytest.fixture()
def workspace(db_path):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    manager = _FakeManager(hub)
    store = AmbienceStore(str(db_path))
    engine = AmbienceEngine(hub)
    controller = AmbienceController(parent, manager, store=store, engine=engine)
    dialog = _MockDialog(manager)
    page = AmbiencePage(dialog, "en", controller=controller)

    yield {
        "page": page,
        "controller": controller,
        "store": store,
        "manager": manager,
        "dialog": dialog,
    }

    controller.shutdown()
    # T-1286: receiver-scoped retirement. Bare deleteLater() is never
    # delivered without an event loop; the accumulated backlog stalled
    # tests/test_timer_fire.py's watchdog when a later test pumped one.
    from _qt_retire import retire
    retire(page, dialog, parent)


def _make_rule(**kwargs) -> AmbienceRule:
    base = dict(
        id=new_rule_id(),
        name="TestRule",
        sound_ref="rain.wav",
        volume=0.5,
        trigger=TRIGGER_ALWAYS,
        repeat=REPEAT_LOOP,
        enabled=True,
        fade_in_ms=100,
        fade_out_ms=200,
        interval_seconds=60,
        start="08:00",
        end="18:00",
        weekdays=["monday", "wednesday"],
        weekday="friday",
        weather="rain",
    )
    base.update(kwargs)
    return AmbienceRule(**base)


class TestAmbienceInspectorSelection:
    def test_empty_table_inspector_state(self, workspace):
        page = workspace["page"]
        assert page.table.rowCount() == 0
        assert page.selected_rule() is None
        assert not page.insp_name.isEnabled()
        assert not page.insp_sound.isEnabled()
        assert not page.insp_volume.isEnabled()

    def test_single_selection_populates_inspector(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r1 = _make_rule(name="Forest Rain", sound_ref="rain.wav", volume=0.75, enabled=True)
        controller.save_rule(r1)
        page.reload()

        assert page.table.rowCount() == 1
        assert page.selected_rule().id == r1.id
        assert page.insp_name.text() == "Forest Rain"
        assert page.insp_name.isEnabled()
        assert page.insp_sound.currentData() == "rain.wav"
        assert page.insp_enabled.isChecked() is True
        assert page.insp_volume.value() == 0.75
        assert "Forest Rain" in page.lbl_inspector.text()

    def test_conditional_trigger_visibility(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r = _make_rule(trigger=TRIGGER_ALWAYS)
        controller.save_rule(r)
        page.reload()

        # ALWAYS: all condition containers hidden
        assert page.insp_time_container.isHidden()
        assert page.insp_weekday_container.isHidden()
        assert page.insp_weather_container.isHidden()

        # Switch to TIME_WINDOW
        page.insp_trigger.setCurrentIndex(page.insp_trigger.findData(TRIGGER_TIME_WINDOW))
        assert not page.insp_time_container.isHidden()
        assert page.insp_weekday_container.isHidden()
        assert page.insp_weather_container.isHidden()

        # Switch to WEEKDAY
        page.insp_trigger.setCurrentIndex(page.insp_trigger.findData(TRIGGER_WEEKDAY))
        assert page.insp_time_container.isHidden()
        assert not page.insp_weekday_container.isHidden()
        assert page.insp_weather_container.isHidden()

        # Switch to WEATHER
        page.insp_trigger.setCurrentIndex(page.insp_trigger.findData(TRIGGER_WEATHER))
        assert page.insp_time_container.isHidden()
        assert page.insp_weekday_container.isHidden()
        assert not page.insp_weather_container.isHidden()

    def test_conditional_repeat_visibility(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r = _make_rule(repeat=REPEAT_LOOP)
        controller.save_rule(r)
        page.reload()

        assert page.insp_interval_container.isHidden()

        page.insp_repeat.setCurrentIndex(page.insp_repeat.findData(REPEAT_EVERY_INTERVAL))
        assert not page.insp_interval_container.isHidden()


class TestAmbienceInspectorEdits:
    def test_single_rule_field_edits(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r1 = _make_rule(name="Initial", volume=0.3, sound_ref="wind.wav")
        controller.save_rule(r1)
        page.reload()

        # Edit name
        page.insp_name.setText("Updated Name")
        page._on_name_edited("Updated Name")
        assert controller.rules()[0].name == "Updated Name"
        assert page.table.item(0, 1).text() == "Updated Name"

        # Edit volume
        page.insp_volume.setValue(0.85)
        assert controller.rules()[0].volume == 0.85
        assert page.table.item(0, 6).text() == "0.85"

        # Edit fades
        page.insp_fade_in.setValue(500)
        page.insp_fade_out.setValue(1500)
        assert controller.rules()[0].fade_in_ms == 500
        assert controller.rules()[0].fade_out_ms == 1500
        assert page.table.item(0, 7).text() == "500/1500 ms"


class TestAmbienceMultiSelectAndBulkEdit:
    def test_multi_selection_mixed_states(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r1 = _make_rule(name="Rule 1", sound_ref="rain.wav", volume=0.4, enabled=True)
        r2 = _make_rule(name="Rule 2", sound_ref="wind.wav", volume=0.8, enabled=False)
        controller.save_rule(r1)
        controller.save_rule(r2)
        page.reload()

        # Select both rows
        page.table.selectAll()
        assert len(page.selected_rules()) == 2

        # Name should be disabled and show multiple
        assert not page.insp_name.isEnabled()
        assert "multiple" in page.insp_name.text().lower() or "—" in page.insp_name.text()

        # Sound is mixed
        assert page.insp_sound.currentData() == "__mixed__"

        # Enabled is partially checked
        assert page.insp_enabled.checkState() == Qt.CheckState.PartiallyChecked

    def test_atomic_bulk_update_across_selected_rules(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r1 = _make_rule(name="Rule 1", volume=0.2, sound_ref="rain.wav")
        r2 = _make_rule(name="Rule 2", volume=0.4, sound_ref="wind.wav")
        r3 = _make_rule(name="Rule 3", volume=0.6, sound_ref="waves.wav")
        controller.save_rule(r1)
        controller.save_rule(r2)
        controller.save_rule(r3)
        page.reload()

        # Select only r1 and r2
        from PyQt6.QtCore import QItemSelectionModel
        page.table.clearSelection()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        page.table.selectionModel().select(page.table.model().index(0, 0), flags)
        page.table.selectionModel().select(page.table.model().index(1, 0), flags)
        selected_ids = {r.id for r in page.selected_rules()}
        assert selected_ids == {r1.id, r2.id}

        # Bulk change volume
        page.insp_volume.setValue(0.9)

        rules_after = {r.id: r for r in controller.rules()}
        assert rules_after[r1.id].volume == 0.9
        assert rules_after[r2.id].volume == 0.9
        assert rules_after[r3.id].volume == 0.6  # Unchanged!

        # Table items updated
        assert page.table.item(0, 6).text() == "0.90"
        assert page.table.item(1, 6).text() == "0.90"
        assert page.table.item(2, 6).text() == "0.60"

        # Selection remained preserved
        assert {r.id for r in page.selected_rules()} == {r1.id, r2.id}


class TestAmbienceSoundlessRuleInvariant:
    def test_soundless_rule_cannot_be_enabled(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r = _make_rule(name="Silent Rule", sound_ref="", enabled=False)
        controller.save_rule(r)
        page.reload()

        # Attempt to enable via table checkbox
        page._toggle(r.id, True)
        assert controller.rules()[0].enabled is False

        # Attempt to enable via inspector
        page.insp_enabled.setChecked(True)
        page._on_enabled_clicked()
        assert controller.rules()[0].enabled is False


class TestAmbienceTransportAndPersistence:
    def test_transport_flow_start_pause_resume_stop(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r = _make_rule(name="Layer", sound_ref="rain.wav", enabled=True)
        controller.save_rule(r)
        page.reload()

        assert controller.state() == "stopped"
        assert "STOPPED" in page.lbl_state.text()
        assert page.btn_start.isEnabled()
        assert not page.btn_pause.isEnabled()
        assert not page.btn_stop.isEnabled()

        # 1. Start
        page.btn_start.click()
        assert controller.state() == "running"
        assert "RUNNING" in page.lbl_state.text()
        assert not page.btn_start.isEnabled()
        assert page.btn_pause.isEnabled()
        assert page.btn_stop.isEnabled()
        assert "Pause" in page.btn_pause.text()

        # 2. Pause
        page.btn_pause.click()
        assert controller.state() == "paused"
        assert "PAUSED" in page.lbl_state.text()
        assert "Resume" in page.btn_pause.text()
        # PAUSED: Start is NOT a second start path; Resume is the only one.
        assert not page.btn_start.isEnabled()
        assert page.btn_pause.isEnabled()
        assert page.btn_stop.isEnabled()

        # 3. Resume
        page.btn_pause.click()
        assert controller.state() == "running"
        assert "RUNNING" in page.lbl_state.text()
        assert "Pause" in page.btn_pause.text()

        # 4. Stop
        page.btn_stop.click()
        assert controller.state() == "stopped"
        assert "STOPPED" in page.lbl_state.text()
        assert page.btn_start.isEnabled()
        assert not page.btn_pause.isEnabled()
        assert not page.btn_stop.isEnabled()

    def test_autostart_checkbox_persistence(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]

        assert controller.desired_enabled() is False
        assert page.cb_autostart.isChecked() is False

        page.cb_autostart.setChecked(True)
        assert controller.desired_enabled() is True

        page.cb_autostart.setChecked(False)
        assert controller.desired_enabled() is False

    def test_stop_all_sound_does_not_clear_autostart(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        manager = workspace["manager"]

        page.cb_autostart.setChecked(True)
        assert controller.desired_enabled() is True

        page.btn_start.click()
        assert controller.state() == "running"

        # Fire STOP ALL SOUND
        manager.stop_all_sound()

        assert controller.state() == "stopped"
        # Autostart wish is preserved!
        assert controller.desired_enabled() is True
        assert page.cb_autostart.isChecked() is True


class TestAmbienceActions:
    def test_add_rule_creates_and_selects_new_rule(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        assert len(controller.rules()) == 0

        page._add()
        assert len(controller.rules()) == 1
        assert page.table.rowCount() == 1
        assert page.selected_rule() is not None
        assert page.selected_rule().name == "Ambience"
        assert page.selected_rule().enabled is False

    def test_duplicate_rule(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r = _make_rule(name="Original", sound_ref="wind.wav", volume=0.7)
        controller.save_rule(r)
        page.reload()

        page.table.selectRow(0)
        page._duplicate()

        rules = controller.rules()
        assert len(rules) == 2
        assert rules[1].name.startswith("Original")
        assert rules[1].volume == 0.7
        assert rules[1].sound_ref == "wind.wav"

    def test_delete_rule(self, workspace):
        page = workspace["page"]
        controller = workspace["controller"]
        r1 = _make_rule(name="R1")
        r2 = _make_rule(name="R2")
        controller.save_rule(r1)
        controller.save_rule(r2)
        page.reload()

        page.table.selectRow(0)
        page._delete()

        rules = controller.rules()
        assert len(rules) == 1
        assert rules[0].id == r2.id

    def test_add_templates(self, workspace):
        """The DELIBERATE bulk action adds the whole set."""
        page = workspace["page"]
        controller = workspace["controller"]
        assert len(controller.rules()) == 0

        page._add_templates_bulk(rule_templates())
        rules = controller.rules()
        assert len(rules) > 0
        assert page.table.rowCount() == len(rules)

    def test_template_chooser_lists_names_and_adds_exactly_one(
            self, workspace, monkeypatch):
        """A single explicit choice inserts one rule; nothing is batched."""
        from PyQt6.QtWidgets import QMenu

        page = workspace["page"]
        controller = workspace["controller"]
        assert len(controller.rules()) == 0

        seen = {}

        real_init = QMenu.__init__

        def spy_init(self, *a, **k):
            real_init(self, *a, **k)
            seen["menu"] = self

        def choose_first(self, *a, **k):
            # Pick the first template the chooser offered — the real action
            # object, so the label and its handler are exercised together.
            for action in self.actions():
                if action.text() and "Add all" not in action.text():
                    action.trigger()
                    break
            return None

        monkeypatch.setattr(QMenu, "__init__", spy_init)
        monkeypatch.setattr(QMenu, "exec", choose_first)
        page._add_templates()

        labels = [a.text() for a in seen["menu"].actions()]
        assert any("Always ambience" in text for text in labels)
        assert any("Add all" in text for text in labels)
        assert len(controller.rules()) == 1
        assert page.table.rowCount() == 1

    def test_template_chooser_cancel_adds_nothing(self, workspace, monkeypatch):
        from PyQt6.QtWidgets import QMenu

        page = workspace["page"]
        controller = workspace["controller"]
        assert len(controller.rules()) == 0

        monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)
        page._add_templates()
        assert controller.rules() == []
        assert page.table.rowCount() == 0

    def test_add_all_is_a_separate_deliberate_action(
            self, workspace, monkeypatch):
        """Red control: bulk insertion exists ONLY behind its own action."""
        from PyQt6.QtWidgets import QMenu

        page = workspace["page"]
        controller = workspace["controller"]
        assert len(controller.rules()) == 0

        seen = {}
        real_init = QMenu.__init__

        def spy_init(self, *a, **k):
            real_init(self, *a, **k)
            seen["menu"] = self

        def choose_add_all(self, *a, **k):
            for action in self.actions():
                if "Add all" in action.text():
                    action.trigger()
                    break
            return None

        monkeypatch.setattr(QMenu, "__init__", spy_init)
        monkeypatch.setattr(QMenu, "exec", choose_add_all)
        page._add_templates()

        expected = len(rule_templates())
        assert expected > 1
        assert len(controller.rules()) == expected

