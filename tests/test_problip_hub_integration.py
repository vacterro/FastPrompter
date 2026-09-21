"""T-1238-B/G: Problip cue enters the hub through the PROBLIP bus.

The catalog provides the sound; the hub provides bus, mode and provenance.
No second audio scheduler is created: the Problip controller's future play
callback routes through ``AudioHub.play`` on bus ``PROBLIP`` with the
user's per-Problip mode, and STOP ALL also silences Problip cues.
"""

from __future__ import annotations

from fastprompter.core.audio_hub import (
    AudioHub,
    Bus,
    FakeMultiChannelTransport,
    Outcome,
    PlaybackMode,
)
from fastprompter.sound.problip.catalog import (
    SoundCatalog,
    choose_playable_sound,
    resolve_sound_path,
)


class TestCatalogToHub:
    def test_catalog_sounds_resolve_to_real_files(self):
        for entry in SoundCatalog.all:
            path = resolve_sound_path(entry.sound_id)
            assert path is not None, entry.sound_id

    def test_cue_routes_through_problip_bus(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        entry = choose_playable_sound(SoundCatalog.ids(),
                                      random_source=lambda n: 0)
        path = resolve_sound_path(entry.sound_id)
        outcome = hub.play(path, event="problip_cue", bus=Bus.PROBLIP,
                           mode=PlaybackMode.MIX)
        assert outcome in (Outcome.PLAYED, Outcome.MIXED)
        record = hub.provenance()[-1]
        assert record["bus"] == "problip"
        assert record["event"] == "problip_cue"

    def test_problip_replace_never_kills_ambience_or_ui(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        hub.play("amb.wav", bus=Bus.AMBIENCE, mode=PlaybackMode.MIX)
        hub.play("click.wav", bus=Bus.UI, mode=PlaybackMode.MIX)
        hub.play("al.wav", bus=Bus.PROBLIP, mode=PlaybackMode.MIX)
        # A REPLACE on the PROBLIP bus must stay bus-scoped.
        hub.play("al2.wav", bus=Bus.PROBLIP, mode=PlaybackMode.REPLACE)
        paths = {ch["path"] for ch in transport.channels.values()}
        assert "amb.wav" in paths and "click.wav" in paths
        assert "al.wav" not in paths and "al2.wav" in paths

    def test_stop_all_silences_problip_and_future_cue_allowed(self):
        transport = FakeMultiChannelTransport()
        hub = AudioHub(transport=transport)
        hub.play("al.wav", bus=Bus.PROBLIP, mode=PlaybackMode.QUEUE)
        hub.play("al2.wav", bus=Bus.PROBLIP, mode=PlaybackMode.QUEUE)
        hub.stop_all()
        assert len(transport.channels) == 0
        entry = choose_playable_sound(SoundCatalog.ids(),
                                      random_source=lambda n: 1)
        path = resolve_sound_path(entry.sound_id)
        assert hub.play(path, bus=Bus.PROBLIP) in (
            Outcome.PLAYED, Outcome.MIXED)

    def test_at_most_one_pending_problip_entry(self):
        """Rapid missed cues never build a Problip backlog."""
        transport = FakeMultiChannelTransport()
        # Voice (high priority) owns the single transient voice; Problip
        # plays QUEUE on its own bus -- the bounded queue must be respected.
        hub = AudioHub(transport=transport, max_queue=1)
        hub.play("p1.wav", bus=Bus.PROBLIP, mode=PlaybackMode.QUEUE)
        assert hub.play("p2.wav", bus=Bus.PROBLIP,
                        mode=PlaybackMode.QUEUE) is Outcome.QUEUED
        assert hub.play("p3.wav", bus=Bus.PROBLIP,
                        mode=PlaybackMode.QUEUE) is Outcome.DROPPED_QUEUE_FULL
        d = hub.diagnostics()
        assert d["queue_depths"]["problip"] == 1
