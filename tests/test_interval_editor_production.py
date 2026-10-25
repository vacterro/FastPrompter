"""Integration tests for the interval reminder editor against the production
backend getter (FastPrompter._interval_notifs / interval_rule_*).

Uses a _FakeMain that binds the real FastPrompter backend methods so the dialog
exercises the same authoritative mutation path as the shipped app. Also covers
a cloned-dict backend (getter returns fresh copies every call).
"""

import copy
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTime  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.main import FastPrompter  # noqa: E402
from fastprompter.ui.timer_dialog import (  # noqa: E402
    DAYPART_CHIME_RULES,
    TimerDialog,
)

_APP = QApplication.instance() or QApplication([])


def _bind_production(fake):
    for name in (
        "_INTERVAL_NOTIF_DEFAULT",
        "_INTERVAL_EDITABLE_FIELDS",
        "_heal_interval_rule",
        "_interval_notifs",
        "interval_rule_list",
        "interval_rule_get",
        "interval_rule_update",
        "interval_rule_add",
        "interval_rule_delete",
        "interval_rule_reorder",
        "interval_rule_set_enabled",
    ):
        attr = getattr(FastPrompter, name)
        if callable(attr):
            setattr(fake, name, attr.__get__(fake, type(fake)))
        else:
            setattr(fake, name, attr)
    if "interval_notifs" not in fake.data:
        fake.data["interval_notifs"] = copy.deepcopy(DAYPART_CHIME_RULES)


class _FakePomo:
    breaks_enabled = True
    repeat_alarm = False
    running = False
    state = "idle"
    phase = "work"
    alarm_pending = False
    remaining = 0
    work_seconds = 25 * 60
    break_seconds = 5 * 60

    def describe(self):
        return ""

    def apply_durations(self, **kw):
        pass

    def toggle(self):
        pass

    def reset(self):
        pass

    def skip_phase(self):
        pass

    def on_productivity_changed(self):
        pass


class _ProdMain(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self._current_lang = "EN"
        self.saved = 0
        self.dirty = False
        self.timers = []
        self.productivity_timer = _FakePomo()
        from fastprompter.core.sound_manager import SoundManager
        self.sound_manager = SoundManager(None, {})
        self.data["interval_notifs"] = copy.deepcopy(DAYPART_CHIME_RULES)
        _bind_production(self)

    def styleSheet(self):
        return ""

    def mark_dirty(self, *_args):
        self.dirty = True

    def save_timers_to_data(self):
        self.saved += 1

    def _update_timer_label(self):
        pass

    def save_productivity_timer(self):
        pass

    def on_productivity_changed(self):
        pass

    def test_timer_notification(self, timer, delay):
        pass


def _dlg():
    return TimerDialog(_ProdMain())


def test_backend_identity_stable():
    m = _ProdMain()
    first = m._interval_notifs()
    second = m._interval_notifs()
    assert first is second
    assert first[0] is second[0]
    assert first is m.data["interval_notifs"]


def test_backend_duplicate_ids_collapsed():
    m = _ProdMain()
    m.data["interval_notifs"] = [
        {"id": "dup", "name": "A", "minutes": 30, "enabled": True, "sound": None,
         "volume": 0.5, "show_notification": False, "show_in_top_bar": False,
         "align_mode": "clock", "all_day": True, "start_minute": 0, "end_minute": 1439,
         "last_fired": 0.0, "last_fired_minute": ""},
        {"id": "dup", "name": "B", "minutes": 45, "enabled": True, "sound": None,
         "volume": 0.5, "show_notification": False, "show_in_top_bar": False,
         "align_mode": "clock", "all_day": True, "start_minute": 0, "end_minute": 1439,
         "last_fired": 0.0, "last_fired_minute": ""},
    ]
    rules = m._interval_notifs()
    assert len(rules) == 1
    assert rules[0]["name"] == "A"


def test_save_persists_across_reload():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_in_name.setText("Renamed Persist")
    assert d._interval_save() is True
    d2 = TimerDialog(d.main_win)
    names = [d2.interval_list.topLevelItem(i).text(1) for i in range(d2.interval_list.topLevelItemCount())]
    assert "Renamed Persist" in names
    d2.close()


def test_new_mints_unique_id():
    d = _dlg()
    before = [r["id"] for r in d.main_win._interval_notifs()]
    d.interval_in_name.setText("Brand New")
    rid = d._interval_new()
    assert isinstance(rid, str) and rid
    assert rid not in before
    after = [r["id"] for r in d.main_win._interval_notifs()]
    assert rid in after
    assert len(after) == len(before) + 1


def test_delete_by_id():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    rid = d._interval_cur
    assert d._interval_delete() is True
    assert all(r.get("id") != rid for r in d.main_win._interval_notifs())


def test_reorder_persists_and_preserves_last_fired():
    d = _dlg()
    rules = d.main_win._interval_notifs()
    rules[0]["last_fired"] = 777.0
    lf_id = rules[0]["id"]
    ids = [r["id"] for r in reversed(rules)]
    assert d._interval_apply_order(ids) is True
    reordered = [r["id"] for r in d.main_win._interval_notifs()]
    assert reordered == ids
    r = d.main_win.interval_rule_get(lf_id)
    assert r["last_fired"] == 777.0


def test_toggle_enabled_persists_only_enabled():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    rid = d._interval_cur
    d.interval_in_name.setText("STAGED NAME")
    original_name = d.main_win.interval_rule_get(rid)["name"]
    d.interval_quick_toggle.setChecked(False)
    d._interval_toggle_selected_enabled()
    r = d.main_win.interval_rule_get(rid)
    assert r["enabled"] is False
    assert r["name"] == original_name


def test_runtime_fields_preserved_on_update():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    rid = d._interval_cur
    d.main_win.interval_rule_get(rid)["last_fired"] = 555.0
    d.main_win.interval_rule_get(rid)["last_fired_minute"] = "12:34"
    d.interval_in_name.setText("Updated")
    d._interval_save()
    r = d.main_win.interval_rule_get(rid)
    assert r["name"] == "Updated"
    assert r["last_fired"] == 555.0
    assert r["last_fired_minute"] == "12:34"


def test_dirty_state_cancel_keeps_form():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_in_name.setText("Dirty")
    d._interval_prompt_handler = lambda: "cancel"
    second = d.interval_list.topLevelItem(1)
    d._interval_on_current_changed(second, item)
    assert d._interval_cur == d._interval_item_rule_id(item)
    assert d.interval_in_name.text() == "Dirty"


def test_reset_all_replaces_and_backup_restores():
    d = _dlg()
    # add a custom rule so reset actually changes the collection
    d.main_win.interval_rule_add({"name": "CustomX", "minutes": 15})
    before_ids = [r["id"] for r in d.main_win._interval_notifs()]
    d._interval_confirm_handler = lambda w: True
    d._interval_prompt_handler = lambda: "discard"
    assert d._interval_reset_defaults() is True
    after_ids = [r["id"] for r in d.main_win._interval_notifs()]
    assert after_ids != before_ids
    assert d._interval_restore_backup() is True
    restored_ids = [r["id"] for r in d.main_win._interval_notifs()]
    assert restored_ids == before_ids


def test_cross_midnight_window_valid():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_cb_allday.setChecked(False)
    d.interval_time_start.setTime(QTime(22, 0))
    d.interval_time_end.setTime(QTime(6, 0))
    fields = d._interval_fields_from_form()
    assert fields["start_minute"] == 1320
    assert fields["end_minute"] == 360
    d._interval_save()
    r = d.main_win.interval_rule_get(d._interval_cur)
    assert r["start_minute"] == 1320
    assert r["end_minute"] == 360


def test_clock_vs_elapsed_distinct():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_cb_align.setCurrentIndex(d.interval_cb_align.findData("elapsed"))
    fields = d._interval_fields_from_form()
    assert fields["align_mode"] == "elapsed"
    d._interval_save()
    r = d.main_win.interval_rule_get(d._interval_cur)
    assert r["align_mode"] == "elapsed"


def test_midnight_safe_times():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_cb_allday.setChecked(False)
    d.interval_time_start.setTime(QTime(0, 0))
    d.interval_time_end.setTime(QTime(23, 59))
    fields = d._interval_fields_from_form()
    assert fields["start_minute"] == 0
    assert fields["end_minute"] == 1439


def test_malformed_missing_ids_repaired_no_drop():
    d = _dlg()
    data = d.main_win.data["interval_notifs"]
    data.append({"name": "NoId", "minutes": 10})
    data.append({"id": "", "name": "EmptyId", "minutes": 10})
    data.append({"id": "dup2", "name": "D1", "minutes": 10})
    data.append({"id": "dup2", "name": "D2", "minutes": 10})
    before = len(data)
    d._interval_reload()
    after = len(d.main_win.data["interval_notifs"])
    assert after == before
    ids = [r["id"] for r in d.main_win.data["interval_notifs"]]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == len(ids)


def test_duplicate_names_allowed():
    d = _dlg()
    d.interval_in_name.setText("SameName")
    d._interval_new()
    d.interval_in_name.setText("SameName")
    rid2 = d._interval_new()
    assert rid2 is not None
    names = [r["name"] for r in d.main_win._interval_notifs()]
    assert names.count("SameName") >= 2


def test_custom_sound_ref_preserved():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d._interval_set_sound("file:my_custom.wav")
    d._interval_save()
    r = d.main_win.interval_rule_get(d._interval_cur)
    assert "my_custom" in str(r.get("sound"))


def test_list_columns_five():
    d = _dlg()
    assert d.interval_list.columnCount() == 5


def test_contextual_editing_heading():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    assert "Editing:" in d.interval_lbl_editing.text()


def test_quick_toggle_checkbox_exists():
    d = _dlg()
    assert hasattr(d, "interval_quick_toggle")


def test_reset_selected_vs_reset_all_buttons():
    d = _dlg()
    assert hasattr(d, "interval_btn_reset_selected")
    assert hasattr(d, "interval_btn_defaults")


def test_revert_button_exists():
    d = _dlg()
    assert hasattr(d, "interval_btn_revert")
# ---- cloned-dict backend ----

class _ClonedMain(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self._current_lang = "EN"
        self.dirty = False
        self.timers = []
        self.productivity_timer = _FakePomo()
        from fastprompter.core.sound_manager import SoundManager
        self.sound_manager = SoundManager(None, {})
        self.data["interval_notifs"] = copy.deepcopy(DAYPART_CHIME_RULES)

    def styleSheet(self):
        return ""

    def _interval_notifs(self):
        return [copy.deepcopy(r) for r in self.data.get("interval_notifs", [])]

    def mark_dirty(self, *_args):
        self.dirty = True

    def save_timers_to_data(self):
        pass

    def _update_timer_label(self):
        pass

    def save_productivity_timer(self):
        pass

    def on_productivity_changed(self):
        pass

    def test_timer_notification(self, timer, delay):
        pass


def _dlg_cloned():
    return TimerDialog(_ClonedMain())


def test_cloned_backend_identity_not_required():
    m = _ClonedMain()
    first = m._interval_notifs()
    second = m._interval_notifs()
    assert first is not second


def test_cloned_backend_save_persists():
    d = _dlg_cloned()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    d.interval_in_name.setText("Cloned Persist")
    assert d._interval_save() is True
    names = [r.get("name") for r in d.main_win.data["interval_notifs"]]
    assert "Cloned Persist" in names


def test_cloned_backend_delete_persists():
    d = _dlg_cloned()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    rid = d._interval_cur
    assert d._interval_delete() is True
    assert all(r.get("id") != rid for r in d.main_win.data["interval_notifs"])


def test_cloned_backend_reorder_persists():
    d = _dlg_cloned()
    ids = [r["id"] for r in reversed(d.main_win.data["interval_notifs"])]
    assert d._interval_apply_order(ids) is True
    stored = [r["id"] for r in d.main_win.data["interval_notifs"]]
    assert stored == ids


def test_cloned_backend_new_persists():
    d = _dlg_cloned()
    d.interval_in_name.setText("Cloned New")
    rid = d._interval_new()
    assert rid is not None
    assert any(r.get("id") == rid for r in d.main_win.data["interval_notifs"])


def test_reset_selected_canonical_restores():
    d = _dlg()
    # find a rule whose id matches a preset
    target = None
    for r in d.main_win._interval_notifs():
        if r["id"] in {p["id"] for p in DAYPART_CHIME_RULES}:
            target = r["id"]
            break
    assert target is not None
    # select it
    for i in range(d.interval_list.topLevelItemCount()):
        it = d.interval_list.topLevelItem(i)
        if d._interval_item_rule_id(it) == target:
            d._interval_load(it)
            break
    # mutate name
    d.interval_in_name.setText("MUTATED")
    d._interval_save()
    # reset selected should restore preset name
    assert d._interval_reset_selected() is True
    r = d.main_win.interval_rule_get(target)
    assert r["name"] != "MUTATED"


def test_reset_selected_noncanonical_returns_false():
    d = _dlg()
    item = d.interval_list.topLevelItem(0)
    d._interval_load(item)
    rule = d.main_win.interval_rule_get(d._interval_cur)
    rule["id"] = "custom_xyz_unique"
    rule["name"] = "CustomNameUnique"
    assert d._interval_preset_source(rule) is None


# --- My Presets wiring (T-1517) ---------------------------------------------


def _rule(**kw):
    base = {
        "name": "Test Rule",
        "minutes": 60,
        "enabled": True,
        "sound": "file:newday.wav",
        "volume": 0.05,
        "show_notification": True,
        "show_in_top_bar": False,
        "align_mode": "clock",
        "all_day": True,
        "start_minute": 0,
        "end_minute": 1439,
    }
    base.update(kw)
    return base


def test_preset_store_is_shared_per_host(tmp_path):
    d = _dlg()
    store = d._interval_preset_store()
    assert store is d._interval_preset_store()
    # a second dialog on the same host shares the store
    d2 = TimerDialog(d.main_win)
    assert d2._interval_preset_store() is store
    d.close()
    d2.close()


def test_preset_store_directory_injectable(tmp_path):
    """A test host can inject its own store directory (isolated per test)."""
    m = _ProdMain()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    m._interval_preset_store = IntervalPresetStore(
        directory=str(tmp_path / "presets"))
    d = TimerDialog(m)
    assert d._interval_preset_store().directory == str(tmp_path / "presets")
    d.close()


def test_snapshot_strips_runtime_history():
    d = _dlg()
    rules = d._interval_preset_store_snapshot()
    for rule in rules:
        assert "last_fired" not in rule
        assert "last_fired_minute" not in rule


def test_save_current_persists_a_user_preset(tmp_path, monkeypatch):
    m = _ProdMain()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    m._interval_preset_store = IntervalPresetStore(
        directory=str(tmp_path / "presets"))
    d = TimerDialog(m)
    d._interval_preset_save_named("Saved Preset")
    assert d.main_win._interval_preset_store.count() == 1
    stored = d.main_win._interval_preset_store.load()[0]
    assert stored["name"] == "Saved Preset"

    d.close()


def test_apply_user_preset_adds_its_rules(tmp_path):
    d = _dlg()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    store = IntervalPresetStore(directory=str(tmp_path / "presets"))
    d.main_win._interval_preset_store = store
    preset = store.create_preset("Added By Test", [_rule(name="Added One")],
                                 kind="single_rule")
    before = len(d.main_win.data["interval_notifs"])
    d._interval_apply_user_preset("add_user", preset["id"])
    names = [r.get("name") for r in d.main_win.data["interval_notifs"]]
    assert "Added One" in names
    assert len(d.main_win.data["interval_notifs"]) == before + 1
    d.close()


def test_apply_user_preset_replaces_all_rules(tmp_path):
    d = _dlg()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    store = IntervalPresetStore(directory=str(tmp_path / "presets"))
    d.main_win._interval_preset_store = store
    preset = store.create_preset(
        "Replacement", [_rule(name="Only Rule")], kind="single_rule")
    d._interval_apply_user_preset("replace_user", preset["id"])
    names = [r.get("name") for r in d.main_win.data["interval_notifs"]]
    assert names == ["Only Rule"]
    d.close()


def test_apply_missing_user_preset_is_a_noop(tmp_path):
    d = _dlg()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    store = IntervalPresetStore(directory=str(tmp_path / "presets"))
    d.main_win._interval_preset_store = store
    before = list(d.main_win.data["interval_notifs"])
    d._interval_apply_user_preset("add_user", "does_not_exist")
    assert list(d.main_win.data["interval_notifs"]) == before
    d.close()


def test_preset_pick_returns_none_when_empty(tmp_path):
    d = _dlg()
    from fastprompter.core.interval_preset_store import IntervalPresetStore
    store = IntervalPresetStore(directory=str(tmp_path / "presets"))
    d.main_win._interval_preset_store = store
    assert d._interval_preset_pick("Pick") is None
    d.close()
