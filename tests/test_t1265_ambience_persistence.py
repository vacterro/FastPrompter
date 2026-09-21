"""T-1265 C2: ambience remembers whether the user wants it running.

Before this, ambience was ON only until the next launch. ``AmbienceController``
stopped the engine in its constructor and nothing ever restored it, and
``AmbienceStore`` persisted rules and weather but never the one fact that
decides whether anything sounds at all.

The fix splits two things that were conflated:

* the **desired** state -- ``ambience_settings_v1.runtime_enabled`` in
  ``audio.db``, application-global, written ONLY when the user explicitly
  starts or stops ambience;
* the **runtime** state -- the timers and the engine, which shutdown and
  STOP ALL SOUND are allowed to silence WITHOUT touching the wish.

That split is the whole ticket: without it, one press of STOP ALL SOUND would
quietly disable ambience for every future session.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core.ambience_engine import (  # noqa: E402
    REPEAT_LOOP,
    TRIGGER_ALWAYS,
    AmbienceEngine,
    AmbienceRule,
)
from fastprompter.core.ambience_store import (  # noqa: E402
    AmbienceStore,
    new_rule_id,
)
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.ui.ambience_controller import AmbienceController  # noqa: E402

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


class _Manager:
    """Minimal SoundManager stand-in that also carries the STOP ALL hook."""

    def __init__(self, hub) -> None:
        self._hub = hub
        self.stop_all_listeners = []

    def audio_hub(self):
        return self._hub

    def add_stop_all_listener(self, callback):
        self.stop_all_listeners.append(callback)

    def stop_all_sound(self):
        """What SoundManager.stop_all_sound() does, in miniature."""
        self._hub.stop_all()
        for callback in list(self.stop_all_listeners):
            callback()


def _rule(**kwargs) -> AmbienceRule:
    base = dict(id=new_rule_id(), name="Rain", sound_ref="rain.wav",
                volume=0.5, trigger=TRIGGER_ALWAYS, repeat=REPEAT_LOOP,
                enabled=True, fade_in_ms=0, fade_out_ms=0)
    base.update(kwargs)
    return AmbienceRule(**base)


class _Session:
    """One application session over a given ``audio.db``."""

    def __init__(self, db_path):
        _ensure_app()
        self.parent = QObject()
        self.transport = FakeMultiChannelTransport()
        self.hub = AudioHub(transport=self.transport)
        self.manager = _Manager(self.hub)
        self.store = AmbienceStore(str(db_path))
        self.engine = AmbienceEngine(self.hub)
        self.controller = AmbienceController(
            self.parent, self.manager, store=self.store, engine=self.engine)

    def launch(self):
        """What main.py does right after building the controller."""
        return self.controller.start_if_remembered()

    def close(self):
        """What _shutdown_application does: silence, never re-decide."""
        self.controller.shutdown()
        self.parent.deleteLater()


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "audio.db"


@pytest.fixture()
def session(db_path):
    live = _Session(db_path)
    yield live
    live.close()


class TestDesiredStatePersistence:
    def test_a_fresh_install_is_off(self, session):
        assert session.store.runtime_enabled() is False
        assert session.controller.desired_enabled() is False
        assert session.launch() is False
        assert session.controller.state() == "stopped"

    def test_start_persists_on(self, session):
        session.controller.start()
        assert session.store.runtime_enabled() is True

    def test_stop_persists_off(self, session):
        session.controller.start()
        session.controller.stop()
        assert session.store.runtime_enabled() is False

    def test_the_toggle_writes_both_directions(self, session):
        session.controller.toggle(True)
        assert session.store.runtime_enabled() is True
        session.controller.toggle(False)
        assert session.store.runtime_enabled() is False

    def test_an_unreadable_store_reads_as_off_rather_than_raising(self,
                                                                 session):
        def boom():
            raise OSError("audio.db is gone")

        session.controller.store.runtime_enabled = boom
        assert session.controller.desired_enabled() is False


class TestRestartRestoresTheWish:
    def test_a_new_session_autostarts_after_start(self, db_path, session):
        session.controller.start()
        session.close()

        second = _Session(db_path)
        try:
            assert second.launch() is True
            assert second.controller.state() == "running"
            assert second.controller.is_running()
        finally:
            second.close()

    def test_a_new_session_stays_stopped_after_stop(self, db_path, session):
        session.controller.start()
        session.controller.stop()
        session.close()

        second = _Session(db_path)
        try:
            assert second.launch() is False
            assert second.controller.state() == "stopped"
            assert not second.controller.is_running()
        finally:
            second.close()

    def test_enabled_rules_resume_and_disabled_ones_stay_silent(self, db_path,
                                                                session):
        session.store.save_rules([
            _rule(name="Loud", sound_ref="rain.wav", enabled=True),
            _rule(name="Quiet", sound_ref="wind.wav", enabled=False),
        ])
        session.controller.reload_rules()
        session.controller.start()
        session.close()

        second = _Session(db_path)
        try:
            assert second.launch() is True
            playing = list(second.transport.channels.values())
            refs = {str(channel.get("path", channel)) for channel in playing}
            assert playing, "the remembered ON state started nothing"
            assert not any("wind" in ref for ref in refs)
        finally:
            second.close()

    def test_restoring_is_not_a_new_user_decision(self, db_path, session):
        """``start_if_remembered`` must not re-write what it just read."""
        session.controller.start()
        session.close()

        second = _Session(db_path)
        writes = []
        original = second.store.set_runtime_enabled
        second.store.set_runtime_enabled = lambda value: (
            writes.append(value) or original(value))
        try:
            assert second.launch() is True
            assert writes == []
        finally:
            second.close()


class TestTransientSilenceKeepsTheWish:
    def test_shutdown_silences_without_rewriting_on(self, db_path, session):
        session.controller.start()
        assert session.store.runtime_enabled() is True
        session.controller.shutdown()
        assert session.store.runtime_enabled() is True

    def test_stop_all_sound_silences_this_session_only(self, session):
        session.store.save_rules([_rule()])
        session.controller.reload_rules()
        session.controller.start()
        assert session.transport.channels

        session.manager.stop_all_sound()
        assert session.controller.state() == "stopped"
        assert not session.controller.is_running()   # timers retired too
        assert session.store.runtime_enabled() is True   # wish intact

    def test_the_next_session_comes_back_on_after_stop_all(self, db_path,
                                                           session):
        session.controller.start()
        session.manager.stop_all_sound()
        session.close()

        second = _Session(db_path)
        try:
            assert second.launch() is True
            assert second.controller.state() == "running"
        finally:
            second.close()

    def test_stop_runtime_only_is_the_same_contract(self, session):
        session.controller.start()
        session.controller.stop_runtime_only()
        assert session.controller.state() == "stopped"
        assert session.store.runtime_enabled() is True

    def test_the_controller_registered_itself_for_stop_all(self, session):
        assert session.manager.stop_all_listeners, (
            "STOP ALL SOUND would leave the ambience timers running")


class TestOneTimerSet:
    def test_no_duplicate_timers_after_a_remembered_start(self, db_path,
                                                          session):
        session.store.save_rules([_rule(), _rule(name="Second",
                                                 sound_ref="wind.wav")])
        session.controller.reload_rules()
        session.controller.start()
        session.close()

        second = _Session(db_path)
        try:
            second.launch()
            from PyQt6.QtCore import QTimer
            timers = [child for child in second.controller.children()
                      if isinstance(child, QTimer)]
            # evaluation + fade + weather, whatever the rule count
            assert len(timers) == 3
        finally:
            second.close()

    def test_repeated_starts_do_not_multiply_timers(self, session):
        from PyQt6.QtCore import QTimer
        for _ in range(4):
            session.controller.start()
        timers = [child for child in session.controller.children()
                  if isinstance(child, QTimer)]
        assert len(timers) == 3


class _FakeDialog(QObject):
    """Only what AmbiencePage touches (it parents into it and reads refs)."""

    _available = []

    def __init__(self, manager):
        super().__init__()
        self._sound_manager = manager


def _page(session):
    from PyQt6.QtWidgets import QWidget

    from fastprompter.ui.audio_hub_pages import AmbiencePage

    host = QWidget()
    session._page_host = host          # keep the C++ parent alive
    return AmbiencePage(host, "EN", session.controller)


class TestSettingsToggle:
    """T-1265 C2: ONE visible control, and it always tells the truth."""

    def test_it_reads_start_while_stopped(self, session):
        page = _page(session)
        assert page.ambience_toggle_text() == "Start ambience"
        assert page.btn_ambience_toggle.isChecked() is False

    def test_clicking_it_starts_and_relabels_without_reopening(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)     # what a click does
        assert session.controller.state() == "running"
        assert page.ambience_toggle_text() == "Stop ambience"
        assert page.btn_ambience_toggle.isChecked() is True
        assert session.store.runtime_enabled() is True

    def test_clicking_it_again_stops_and_persists_off(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_ambience_toggle.setChecked(False)
        assert session.controller.state() == "stopped"
        assert page.ambience_toggle_text() == "Start ambience"
        assert session.store.runtime_enabled() is False

    def test_it_follows_a_runtime_change_it_did_not_cause(self, session):
        """STOP ALL SOUND elsewhere must not leave the button lying."""
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        session.manager.stop_all_sound()
        assert page.btn_ambience_toggle.isChecked() is False
        assert page.ambience_toggle_text() == "Start ambience"

    def test_refreshing_the_label_does_not_toggle_the_runtime(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        for _ in range(3):
            page._refresh_state()
        assert session.controller.state() == "running"

    def test_a_restored_session_opens_with_the_switch_already_on(self,
                                                                 db_path,
                                                                 session):
        session.controller.start()
        session.close()

        second = _Session(db_path)
        try:
            second.launch()
            page = _page(second)
            assert page.btn_ambience_toggle.isChecked() is True
            assert page.ambience_toggle_text() == "Stop ambience"
        finally:
            second.close()

    def test_pause_is_secondary_and_only_offered_while_running(self, session):
        page = _page(session)
        assert page.btn_pause.isEnabled() is False
        page.btn_ambience_toggle.setChecked(True)
        assert page.btn_pause.isEnabled() is True

class TestPauseResumeIsReversible:
    """T-1265 B2: the secondary control is truthful AND reversible.

    It was hard-wired to ``controller.pause()`` and hard-labelled "Pause
    ambience". ``_runtime_on()`` only treats ``stopped`` as off, so a PAUSED
    runtime kept the button enabled, kept the Pause label and re-paused on
    every further click: Resume was unreachable from the UI entirely.
    """

    def test_stopped_offers_nothing_to_pause(self, session):
        page = _page(session)
        assert session.controller.state() == "stopped"
        assert page.btn_pause.isEnabled() is False
        assert page.ambience_pause_text() == "Pause ambience"

    def test_running_offers_pause(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        assert session.controller.state() == "running"
        assert page.btn_pause.isEnabled() is True
        assert page.ambience_pause_text() == "Pause ambience"
        assert page.btn_pause.text() == "Pause ambience"

    def test_clicking_pause_pauses_and_relabels_to_resume(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        assert session.controller.state() == "paused"
        assert page.ambience_pause_text() == "Resume ambience"
        assert page.btn_pause.text() == "Resume ambience"
        assert page.btn_pause.isEnabled() is True

    def test_clicking_resume_runs_again(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        assert session.controller.state() == "paused"
        page.btn_pause.click()
        assert session.controller.state() == "running"
        assert page.ambience_pause_text() == "Pause ambience"

    def test_pause_resume_round_trips_any_number_of_times(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        for _ in range(3):
            page.btn_pause.click()
            assert session.controller.state() == "paused"
            page.btn_pause.click()
            assert session.controller.state() == "running"

    def test_the_primary_toggle_still_reads_stop_while_paused(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        assert page.ambience_toggle_text() == "Stop ambience"
        assert page.btn_ambience_toggle.isChecked() is True

    def test_stopping_from_paused_persists_off(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        assert session.controller.state() == "paused"
        page.btn_ambience_toggle.setChecked(False)   # user stops it
        assert session.controller.state() == "stopped"
        assert session.store.runtime_enabled() is False
        assert page.btn_pause.isEnabled() is False
        assert page.ambience_pause_text() == "Pause ambience"

    def test_stop_all_sound_from_paused_keeps_the_remembered_wish(self,
                                                                 session):
        """Emergency silence is not "never start ambience again"."""
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        session.manager.stop_all_sound()
        assert session.controller.state() == "stopped"
        assert session.store.runtime_enabled() is True
        assert page.btn_pause.isEnabled() is False

    def test_starting_again_after_a_pause_clears_the_hold(self, session):
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        page.btn_pause.click()
        page.btn_ambience_toggle.setChecked(False)
        page.btn_ambience_toggle.setChecked(True)
        assert session.controller.state() == "running"
        assert page.ambience_pause_text() == "Pause ambience"

    def test_a_runtime_pause_nobody_clicked_still_relabels(self, session):
        """The page follows the controller, not only its own handlers."""
        page = _page(session)
        page.btn_ambience_toggle.setChecked(True)
        session.controller.pause()          # e.g. another window
        assert page.ambience_pause_text() == "Resume ambience"
        assert page.btn_pause.text() == "Resume ambience"
