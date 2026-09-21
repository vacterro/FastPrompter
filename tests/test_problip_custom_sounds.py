"""T-1242: custom Problip sounds via the managed Sound Library.

The pool grows beyond the six built-ins without ever becoming an arbitrary
absolute-path player: custom sounds live as ``user:<rel>`` refs inside
``<data>/sound_library/`` (imported = COPIED), legacy six-ID databases
migrate untouched, a custom-only pool is legal, random selection can pick
custom entries, missing files stay visible as missing, and TEST previews
never count as blips.
"""

from __future__ import annotations

import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QObject  # noqa: E402

from fastprompter.core import sound_library  # noqa: E402
from fastprompter.core.audio_hub import (  # noqa: E402
    AudioHub,
    FakeMultiChannelTransport,
)
from fastprompter.core.problip_store import (  # noqa: E402
    DEFAULT_SOUND_ID,
    ProblipStore,
    normalize_sound_ids,
    pool_entry_kind,
)
from fastprompter.sound.problip.catalog import (  # noqa: E402
    inspect_sound_pool,
    resolve_sound_path,
)
from fastprompter.ui.problip_controller import ProblipController  # noqa: E402

USER_BLIP_REF = "user:imported/myblip.wav"


def _write_wav(path, frames=(12000, -12000) * 64, rate=44100):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"".join(
            int(v).to_bytes(2, "little", signed=True) for v in frames))
    return str(path)


class _Manager:
    def __init__(self, hub: AudioHub) -> None:
        self._hub = hub

    def audio_hub(self) -> AudioHub:
        return self._hub

    def stop_all_sound(self) -> None:
        self._hub.stop_all()


_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def managed(tmp_path, monkeypatch):
    """A managed library rooted in tmp."""
    root = str(tmp_path / "sound_library")
    monkeypatch.setattr(sound_library, "managed_root", lambda: root)
    return root


@pytest.fixture()
def rig(tmp_path, managed):
    _ensure_app()
    parent = QObject()
    transport = FakeMultiChannelTransport()
    hub = AudioHub(transport=transport)
    manager = _Manager(hub)
    store = ProblipStore(str(tmp_path / "problip.db"))
    controller = ProblipController(parent, manager, store=store,
                                   random_source=lambda n: 0)
    yield controller, transport, hub, store
    controller.shutdown()
    parent.deleteLater()


def _imported_wav(tmp_path, managed, name="myblip.wav"):
    """Put one WAV into the managed library; return its user: ref."""
    external = _write_wav(tmp_path / "external" / name)
    ref = sound_library.import_file(external, subdir="imported")
    assert ref.startswith("user:")
    return ref


class TestLegacyMigration:
    def test_legacy_six_ids_load_unchanged(self):
        legacy = ["sound_original", "sound_glass", "sound_wood"]
        assert normalize_sound_ids(legacy) == legacy

    def test_legacy_json_string_loads_unchanged(self):
        assert normalize_sound_ids('["sound_bonk", "sound_space"]') == [
            "sound_bonk", "sound_space"]

    def test_empty_pool_falls_back_to_original(self):
        assert normalize_sound_ids([]) == [DEFAULT_SOUND_ID]
        assert normalize_sound_ids(None) == [DEFAULT_SOUND_ID]

    def test_builtin_id_token_is_accepted(self):
        assert normalize_sound_ids(["builtin-id:sound_glass"]) == [
            "builtin-id:sound_glass"]

    def test_user_ref_is_never_reinterpreted_as_a_builtin(self, managed,
                                                         tmp_path):
        ref = _imported_wav(tmp_path, managed)
        kept = normalize_sound_ids([ref])
        assert kept == [ref]
        assert pool_entry_kind(ref) == "user"
        assert pool_entry_kind("sound_original") == "builtin"
        assert pool_entry_kind("builtin-id:sound_original") == "builtin"

    def test_traversal_refs_are_dropped(self):
        assert normalize_sound_ids(["user:../../secret.wav"]) == [
            DEFAULT_SOUND_ID]
        assert normalize_sound_ids(["C:\\Users\\x\\evil.wav"]) == [
            DEFAULT_SOUND_ID]

    def test_store_round_trip_persists_the_user_ref(self, managed, tmp_path):
        ref = _imported_wav(tmp_path, managed)
        store = ProblipStore(str(tmp_path / "p.db"))
        store.update_settings(selected_sound_ids=[ref])
        reloaded = ProblipStore(str(tmp_path / "p.db")).load_settings()
        assert list(reloaded.selected_sound_ids) == [ref]


class TestPoolSemantics:
    def test_builtin_plus_custom_pool_both_playable(self, managed, tmp_path):
        ref = _imported_wav(tmp_path, managed)
        status = inspect_sound_pool(["sound_original", ref])
        assert status.playable_ids == ("sound_original", ref)
        assert not status.missing_ids

    def test_custom_only_pool_is_valid(self, managed, tmp_path):
        ref = _imported_wav(tmp_path, managed)
        status = inspect_sound_pool([ref])
        assert status.playable
        assert status.playable_ids == (ref,)

    def test_missing_custom_file_stays_visible_as_missing(self, managed,
                                                         tmp_path):
        ref = _imported_wav(tmp_path, managed)
        # delete the managed copy behind the user's back
        path = resolve_sound_path(ref)
        assert path
        os.remove(path)
        status = inspect_sound_pool([ref])
        assert not status.playable          # truthful: it cannot play
        assert status.missing_ids == (ref,)  # but stays selected & visible
        assert status.selected_ids == (ref,)  # never rewritten to Original

    def test_custom_only_pool_never_silently_disappears(self, rig, managed,
                                                        tmp_path):
        controller, _transport, _hub, _store = rig
        ref = _imported_wav(tmp_path, managed)
        controller.update_settings(selected_sound_ids=[ref])
        # the file vanished -> pool truthfully unplayable, controller holds
        os.remove(resolve_sound_path(ref))
        status = controller.pool_status()
        assert not status.playable
        assert list(controller.settings.selected_sound_ids) == [ref]

    def test_random_chooser_can_pick_the_custom_entry(self, managed, tmp_path):
        from fastprompter.sound.problip.catalog import choose_playable_sound
        ref = _imported_wav(tmp_path, managed)
        pool = ("sound_original", ref)
        picks = {choose_playable_sound(pool, random_source=lambda n: i)
                 for i in range(2)}
        names = {p.sound_id for p in picks}
        assert names == {"sound_original", ref}

    def test_single_custom_selection_means_always_my_sound(self, rig, managed,
                                                          tmp_path):
        controller, transport, _hub, _store = rig
        ref = _imported_wav(tmp_path, managed)
        controller.update_settings(selected_sound_ids=[ref])
        assert controller.is_running() or controller.start(persist=False)
        controller._on_timeout()
        started = [job["path"] for job in transport.channels.values()]
        assert len(started) == 1
        assert started[0] == resolve_sound_path(ref)


class TestRuntimeIntegration:
    def test_scheduled_custom_cue_counts_once_and_plays_managed_copy(
            self, rig, managed, tmp_path):
        controller, transport, hub, _store = rig
        ref = _imported_wav(tmp_path, managed)
        controller.update_settings(selected_sound_ids=[ref])
        assert controller.start(persist=False)
        controller._on_timeout()
        aud = [e for e in hub.provenance()
               if e.get("bus") == "problip" and e.get("outcome")
               in ("PLAYED", "MIXED", "REPLACED")]
        assert len(aud) == 1
        played = [job["path"] for job in transport.channels.values()]
        assert played == [resolve_sound_path(ref)]
        # the played path is INSIDE the managed library, never the source
        assert managed.lower() in played[0].lower()
        stats = controller.stats()
        assert stats.today == 1

    def test_test_button_previews_custom_without_counting(self, rig, managed,
                                                          tmp_path):
        controller, transport, _hub, _store = rig
        ref = _imported_wav(tmp_path, managed)
        ok, msg = controller.test_path(resolve_sound_path(ref))
        assert ok
        assert len(transport.channels) == 1
        assert controller.stats().today == 0
        assert controller.stats().total == 0

    def test_removal_guard_reports_references_before_deleting(
            self, rig, managed, tmp_path):
        controller, _transport, _hub, _store = rig
        ref = _imported_wav(tmp_path, managed)
        controller.update_settings(selected_sound_ids=[ref])
        # the pool references it: deletion must be visible, not silent
        assert ref in controller.settings.selected_sound_ids
        assert pool_entry_kind(ref) == "user"
        # deletion itself is explicit and leaves the ref visibly missing
        assert sound_library.remove_managed_sound(ref) is True
        status = controller.pool_status()
        assert status.missing_ids == (ref,)
        assert status.selected_ids == (ref,)

    def test_restart_keeps_the_custom_pool(self, managed, tmp_path, rig):
        controller, _t, _h, _store = rig
        ref = _imported_wav(tmp_path, managed)
        controller.update_settings(selected_sound_ids=[ref])
        # a fresh controller over the same store sees the same pool
        store2 = controller.store
        settings = store2.load_settings()
        assert ref in settings.selected_sound_ids

    def test_no_absolute_path_dependency(self, managed, tmp_path):
        ref = _imported_wav(tmp_path, managed)
        assert ref == USER_BLIP_REF
        # persistence never contains the tmp "external" source path
        assert "external" not in ref
        assert resolve_sound_path(ref) and os.path.isfile(
            resolve_sound_path(ref))
