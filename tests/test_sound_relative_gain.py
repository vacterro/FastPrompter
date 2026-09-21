"""T-1242 spec 10-12: per-event gain is RELATIVE dB, not an absolute level.

The old control was 0..10 where 0 was a magic "inherit global" sentinel, so
an event could only ever be quieter than the master and the sentinel read to
users as "muted".  These tests pin the replacement contract:

    effective = clamp(global_master * 10 ** (gain_db / 20), 0.0, 1.0)
"""

import math

import pytest

from fastprompter.core.sound_manager import (
    GAIN_DB_MAX,
    GAIN_DB_MIN,
    GAIN_SCHEMA_KEY,
    GAIN_SCHEMA_VERSION,
    clamp_gain_db,
    effective_event_volume,
    factor_to_gain_db,
    gain_db_to_factor,
    get_event_gain_db,
    get_event_volume,
    global_volume,
    migrate_sound_settings,
    parse_gain_db,
)


def _data(master="0.29", **events):
    return {"sound_volume": master,
            "sound_events": {k: dict(v) for k, v in events.items()}}


class TestRange:
    def test_the_control_spans_minus_24_to_plus_12(self):
        assert GAIN_DB_MIN == -24.0
        assert GAIN_DB_MAX == 12.0

    def test_out_of_range_values_clamp(self):
        assert clamp_gain_db(-99) == GAIN_DB_MIN
        assert clamp_gain_db(99) == GAIN_DB_MAX

    def test_zero_db_is_unity(self):
        assert gain_db_to_factor(0.0) == pytest.approx(1.0)

    def test_six_db_steps_are_the_familiar_halving_and_doubling(self):
        assert gain_db_to_factor(-6.0) == pytest.approx(0.5, abs=0.01)
        assert gain_db_to_factor(6.0) == pytest.approx(2.0, abs=0.01)

    def test_factor_to_gain_db_round_trips(self):
        for db in (-24.0, -12.0, -6.0, 0.0, 3.0, 12.0):
            assert factor_to_gain_db(gain_db_to_factor(db)) == pytest.approx(db)

    def test_a_non_positive_ratio_is_the_floor_not_a_math_domain_error(self):
        assert factor_to_gain_db(0.0) == GAIN_DB_MIN
        assert factor_to_gain_db(-1.0) == GAIN_DB_MIN


class TestParsing:
    @pytest.mark.parametrize("raw", [None, "", True, "abc", object()])
    def test_unreadable_values_are_none_not_a_guess(self, raw):
        assert parse_gain_db(raw) is None

    def test_stored_strings_parse(self):
        assert parse_gain_db("-6.0") == -6.0
        assert parse_gain_db(" 3 ") == 3.0


class TestEffectiveVolume:
    def test_zero_db_is_exactly_the_global_volume(self):
        data = _data("0.29", click={"gain_db": "0.0"})
        assert effective_event_volume("click", data) == pytest.approx(0.29)

    def test_negative_gain_is_quieter_than_global(self):
        data = _data("0.29", click={"gain_db": "-6.0"})
        assert effective_event_volume("click", data) == pytest.approx(
            0.29 * 0.5, abs=0.005)

    def test_positive_gain_is_louder_than_global(self):
        data = _data("0.29", click={"gain_db": "6.0"})
        assert effective_event_volume("click", data) == pytest.approx(
            0.29 * 2.0, abs=0.01)

    def test_the_master_stays_authoritative_and_the_result_never_exceeds_one(self):
        data = _data("0.9", click={"gain_db": "12.0"})
        assert effective_event_volume("click", data) == 1.0

    def test_a_muted_master_mutes_every_event_whatever_its_gain(self):
        data = _data("0.0", click={"gain_db": "12.0"})
        assert effective_event_volume("click", data) == 0.0

    def test_get_event_volume_is_the_effective_amplitude(self):
        data = _data("0.5", click={"gain_db": "-12.0"})
        assert get_event_volume("click", data) == effective_event_volume(
            "click", data)

    def test_an_unknown_event_is_simply_the_global_volume(self):
        data = _data("0.42")
        assert get_event_volume("nope", data) == pytest.approx(0.42)


class TestMigration:
    def test_blank_legacy_volume_migrates_to_zero_db(self):
        data = _data("0.29", click={"file": "a.wav", "volume": ""})
        migrate_sound_settings(data)
        assert data["sound_events"]["click"]["gain_db"] == "0.0"

    def test_an_explicit_legacy_level_preserves_todays_audible_relation(self):
        # 0.145 absolute against a 0.29 master is exactly half = -6 dB.
        data = _data("0.29", click={"file": "a.wav", "volume": "0.145"})
        migrate_sound_settings(data)
        assert float(data["sound_events"]["click"]["gain_db"]) == pytest.approx(
            -6.0, abs=0.1)
        assert effective_event_volume("click", data) == pytest.approx(
            0.145, abs=0.002)

    def test_a_legacy_level_louder_than_global_migrates_to_positive_gain(self):
        data = _data("0.25", click={"file": "a.wav", "volume": "0.5"})
        migrate_sound_settings(data)
        assert float(data["sound_events"]["click"]["gain_db"]) == pytest.approx(
            6.0, abs=0.1)

    def test_a_ratio_beyond_the_control_range_clamps(self):
        data = _data("0.01", click={"file": "a.wav", "volume": "1.0"})
        migrate_sound_settings(data)
        assert float(data["sound_events"]["click"]["gain_db"]) == GAIN_DB_MAX

    def test_a_muted_master_migrates_safely_instead_of_dividing_by_zero(self):
        data = _data("0.0", click={"file": "a.wav", "volume": "0.5"})
        migrate_sound_settings(data)
        assert data["sound_events"]["click"]["gain_db"] == "0.0"
        assert effective_event_volume("click", data) == 0.0

    def test_migration_is_idempotent(self):
        data = _data("0.29", click={"file": "a.wav", "volume": "0.145"})
        migrate_sound_settings(data)
        first = data["sound_events"]["click"]["gain_db"]
        migrate_sound_settings(data)
        assert data["sound_events"]["click"]["gain_db"] == first

    def test_the_schema_marker_is_written(self):
        data = _data("0.29", click={"file": "a.wav"})
        migrate_sound_settings(data)
        assert data[GAIN_SCHEMA_KEY] == GAIN_SCHEMA_VERSION

    def test_the_legacy_field_survives_for_a_downgrade(self):
        data = _data("0.29", click={"file": "a.wav", "volume": "0.145"})
        migrate_sound_settings(data)
        assert data["sound_events"]["click"]["volume"] == "0.145"

    def test_an_unmigrated_profile_still_reproduces_its_old_loudness(self):
        """A profile written by an older build reads correctly WITHOUT a
        migration pass -- the fallback derives the same relation."""
        data = _data("0.29", click={"file": "a.wav", "volume": "0.145"})
        assert get_event_gain_db("click", data) == pytest.approx(-6.0, abs=0.1)
        assert effective_event_volume("click", data) == pytest.approx(
            0.145, abs=0.002)


class TestFormula:
    def test_the_formula_is_the_documented_one(self):
        data = _data("0.37", click={"gain_db": "-9.0"})
        master = global_volume(data)
        expected = max(0.0, min(1.0, master * (10 ** (-9.0 / 20))))
        assert effective_event_volume("click", data) == pytest.approx(expected)
        assert not math.isnan(expected)
