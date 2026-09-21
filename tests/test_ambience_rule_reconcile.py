"""SRC-021 CORE-001: the audible runtime must converge to the rule set.

`AmbienceEngine.set_rules()` used to be a blind list assignment. `evaluate()`
only walks rules still present in `_rules` and skips disabled ones, so once a
rule left the set there was no branch left that could retire its layer:

* deleting or disabling an AUDIBLE rule left the sound playing forever, with
  the workspace and the store already claiming it was gone;
* editing an audible rule's source or volume left the OLD channel sounding
  while the UI showed the new value.

Every test below asserts on the hub's real channel state (what was started,
what was physically stopped, what the live volume is), never on the engine's
own bookkeeping -- the defect was precisely a disagreement between the two.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from fastprompter.core.ambience_engine import (
    REPEAT_EVERY_INTERVAL,
    REPEAT_LOOP,
    REPEAT_ON_ENTER,
    TRIGGER_ALWAYS,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.ambience_store import AmbienceStore


class _Result:
    def __init__(self, channel: str) -> None:
        self.channel = channel


class RecordingHub:
    """Hub double: real channel liveness, not engine bookkeeping."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, float]] = []
        self.stopped: list[str] = []
        self.volume_calls: list[tuple[str, float]] = []
        self.live: dict[str, dict] = {}

    def start_channel(self, path, *, event="", bus="ambience", volume=1.0,
                      loop=False):
        self.entries.append((event, path, float(volume)))
        handle = f"h{len(self.entries)}"
        self.live[handle] = {"path": path, "volume": float(volume),
                             "loop": bool(loop)}
        return _Result(handle)

    def stop_channel_handle(self, handle):
        self.stopped.append(handle)
        self.live.pop(handle, None)

    def set_channel_volume(self, handle, volume):
        self.volume_calls.append((handle, float(volume)))
        if handle in self.live:
            self.live[handle]["volume"] = float(volume)

    def channel_alive(self, handle):
        return bool(handle) and handle in self.live


def _rule(**kwargs) -> AmbienceRule:
    base = dict(id="r1", name="Rule", sound_ref="A.wav", volume=0.8,
                trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP, enabled=True,
                fade_in_ms=0, fade_out_ms=0)
    base.update(kwargs)
    return AmbienceRule(**base)


def _audible(hub: RecordingHub) -> AmbienceEngine:
    """An engine with exactly one rule actually sounding."""
    engine = AmbienceEngine(hub, max_layers=4)
    engine.set_rules([_rule()])
    engine.evaluate()
    assert len(hub.live) == 1
    return engine


# -- removal and disable ----------------------------------------------------


class TestRemovalConvergesRuntime:
    def test_emptying_the_rule_set_silences_the_layer(self):
        hub = RecordingHub()
        engine = _audible(hub)
        engine.set_rules([])
        assert hub.live == {}                 # physically stopped
        assert hub.stopped == ["h1"]
        assert engine.active_rules() == []

    def test_disabling_an_audible_rule_silences_it(self):
        hub = RecordingHub()
        engine = _audible(hub)
        engine.set_rules([_rule(enabled=False)])
        assert hub.live == {}
        assert engine.active_rules() == []

    def test_a_layer_already_fading_out_is_retired_too(self):
        """A fading layer is still sounding; removing its rule must cut it."""
        hub = RecordingHub()
        engine = AmbienceEngine(hub, max_layers=4)
        engine.set_rules([_rule(fade_out_ms=500)])
        engine.evaluate()
        engine.set_rules([])                  # rule gone -> starts a fade
        assert engine.active_rules() == []
        engine.set_rules([])                  # as-if the workspace re-saved
        assert hub.live == {}                 # nothing left audible


# -- configuration convergence ---------------------------------------------


class TestConfigConvergesRuntime:
    def test_material_source_change_restarts_exactly_once(self):
        hub = RecordingHub()
        engine = _audible(hub)
        engine.set_rules([_rule(sound_ref="B.wav")])
        assert [path for _e, path, _v in hub.entries] == ["A.wav", "B.wav"]
        assert hub.stopped == ["h1"]          # old one retired, not leaked
        assert len(hub.live) == 1             # never two at once
        assert engine.layer_handle("r1") == "h2"

    def test_repeat_change_restarts_because_looping_changed(self):
        hub = RecordingHub()
        engine = _audible(hub)
        engine.set_rules([_rule(repeat=REPEAT_EVERY_INTERVAL)])
        assert len(hub.entries) == 2
        assert len(hub.live) == 1

    def test_volume_only_change_updates_the_live_channel_in_place(self):
        hub = RecordingHub()
        engine = _audible(hub)
        engine.set_rules([_rule(volume=0.25)])
        assert len(hub.entries) == 1          # NOT restarted
        assert hub.stopped == []
        assert hub.live["h1"]["volume"] == pytest.approx(0.25)
        assert engine.layer_volume("r1") == pytest.approx(0.25)

    def test_volume_change_during_fade_in_re_aims_the_target(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub, max_layers=4)
        engine.set_rules([_rule(fade_in_ms=500)])
        engine.evaluate()
        assert engine.layer_volume("r1") == 0.0     # fade has not landed
        engine.set_rules([_rule(volume=0.4, fade_in_ms=500)])
        assert engine.layer_volume("r1") == 0.0     # still owned by the fade
        engine.tick_fades(500)
        assert engine.layer_volume("r1") == pytest.approx(0.4)

    def test_an_unchanged_rule_is_never_restarted(self):
        hub = RecordingHub()
        engine = _audible(hub)
        for _ in range(3):
            engine.set_rules([_rule()])
        assert len(hub.entries) == 1
        assert hub.stopped == []
        assert engine.layer_handle("r1") == "h1"


# -- per-rule state must not be inherited ----------------------------------


class TestTriggerStateIsNotInherited:
    def test_disable_then_reenable_fires_on_enter_again(self):
        hub = RecordingHub()
        engine = AmbienceEngine(hub, max_layers=4)
        engine.set_rules([_rule(repeat=REPEAT_ON_ENTER)])
        assert engine.evaluate() == ["r1"]          # entered
        assert engine.evaluate() == []              # still in, no re-fire
        engine.set_rules([_rule(repeat=REPEAT_ON_ENTER, enabled=False)])
        engine.set_rules([_rule(repeat=REPEAT_ON_ENTER)])
        assert engine.evaluate() == ["r1"]          # fresh entry, not stale

    def test_interval_state_is_dropped_for_a_disabled_rule(self):
        hub = RecordingHub()
        clock = {"t": 0.0}
        engine = AmbienceEngine(hub, clock=lambda: clock["t"], max_layers=4)
        engine.set_rules([_rule(repeat=REPEAT_EVERY_INTERVAL,
                                interval_seconds=60)])
        engine.evaluate()
        clock["t"] = 120.0
        engine.set_rules([_rule(repeat=REPEAT_EVERY_INTERVAL,
                                interval_seconds=60, enabled=False)])
        engine.set_rules([_rule(repeat=REPEAT_EVERY_INTERVAL,
                                interval_seconds=60)])
        # A re-enabled rule starts fresh and re-arms from NOW, so the long
        # gap while it was disabled can never fire an immediate catch-up.
        engine.evaluate()
        clock["t"] = 121.0
        assert engine.evaluate() == []


# -- the controller route the operator actually uses ------------------------


class TestControllerRoute:
    def test_delete_rule_while_audible_silences_runtime_and_store(
            self, tmp_path):
        pytest.importorskip("PyQt6.QtWidgets")
        from PyQt6.QtCore import QObject
        from PyQt6.QtWidgets import QApplication

        from fastprompter.ui.ambience_controller import AmbienceController

        app = QApplication.instance() or QApplication([])
        # The parent must be held by the test: a bare temporary QObject is
        # collected as soon as the call returns, taking the controller's C++
        # side with it and turning the next signal emission into a RuntimeError.
        parent = QObject()
        hub = RecordingHub()
        store = AmbienceStore(db_path=str(tmp_path / "ambience.sqlite"))
        store.save_rules([_rule()])
        engine = AmbienceEngine(hub, max_layers=4)
        controller = AmbienceController(parent, None, store=store,
                                        engine=engine)
        try:
            engine.start_ambience()
            engine.evaluate()
            assert len(hub.live) == 1            # the rule is audible
            controller.delete_rule("r1")
            assert hub.live == {}                # runtime converged
            assert hub.stopped == ["h1"]
            assert [r.id for r in store.load_rules()] == []   # store too
        finally:
            controller.shutdown()
            app.processEvents()
