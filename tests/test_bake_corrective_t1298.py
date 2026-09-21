"""SRC-029 corrective regression matrix (T-1298).

Covers:
A. customized safe profile -> exact safe settings preserved
B. sidebar open on the right -> baked profile starts open
C. modern sound-event map with gain_db/mode -> fields preserved, no downgrade
D. new appearance sound events -> never omitted because an old base lacked them
E. personal silo/text values -> excluded
F. machine account paths -> neutral
G. interval last_fired -> neutral
H. release language -> EN
I. packaged sound refs -> accepted
J. managed-only/missing sound ref -> explicit refusal, never silent substitution
K. dry-run does not write
L. cancelled preview does not write
M. fresh-profile roundtrip equals sanitized snapshot
N. frozen EXE cannot mutate repository defaults
O. reset queue narrow-card layout keeps essential columns readable
"""

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QMessageBox as _RealMessageBox  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

from tools import set_default_from_current as bake  # noqa: E402


def _wav(root: pathlib.Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF0000WAVEfmt ")


@pytest.fixture
def assets(tmp_path):
    builtin = tmp_path / "packaged"
    user = tmp_path / "managed"
    builtin.mkdir()
    user.mkdir()
    for name in ("tick_on.wav", "pickup_grenade_03.wav", "KILLFADE.wav",
                 "fiveseven_clipout.wav", "ui_save.wav", "button1.wav",
                 "menu1.wav", "chime_bell_ding1.wav"):
        _wav(builtin, name)
    return str(builtin), str(user)


def _live_custom_profile(with_events=True):
    profile = {
        "theme": "Golden Default",
        "language": "EST",
        "sidebar_right": "True",
        "saved_sidebar_size": "258",
        "splitter_sizes_right": [0, 768, 258],
        "sound_ui": "True",
        "sound_typewriter": "True",
        "sound_volume": "0.09",
        "saved_sound_mappings": {"click": "tick_on.wav"},
        "sound_quick_bar": ["file:tick_on.wav"],
        "limit_colors": {"reset_codex": "#4bc0ff"},
        "limit_codex_homes": "C:\\Users\\Example\\.codex",
        "limit_claude_homes": "C:\\Users\\Example\\.claude-work",
        "limit_freebuff_state": "C:\\Users\\Example\\state.json",
        "limit_zcode_config": "C:\\Users\\Example\\zcode.json",
        "limit_gauges_hidden_accounts": ["claude:deadbeef"],
        "limit_notifications": {"claude:x|five_hour": {"enabled": "True"}},
        "limit_notification_state": {"claude:x|five_hour": 1},
        "silo_text": "SECRET PERSONAL TEXT",
        "temp_presets": ["# secret"],
        "silo_folders_all": {"Code": {"1": "private_repo"}},
        "timers": [{"name": "private deadline"}],
        "line_marks_data": {"1": 3},
        "last_geometry": "702,346,1033,679",
        "recent_files": ["C:\\secret\\file.md"],
    }
    if with_events:
        profile["sound_events"] = {
            "click": {"file": "tick_on.wav", "enabled": "True",
                      "volume": "", "gain_db": "-3.0", "mode": "single"},
            "paste": {"file": "pickup_grenade_03.wav", "enabled": "True",
                      "volume": "", "gain_db": "-1.0", "mode": "single"},
            "clear": {"file": "KILLFADE.wav", "enabled": "True",
                      "volume": "", "gain_db": "-2.9", "mode": "single"},
            "delete": {"file": "fiveseven_clipout.wav", "enabled": "True",
                       "volume": "", "gain_db": "0.0", "mode": "single"},
            "app_show": {"file": "menu1.wav", "enabled": "False",
                         "volume": "", "gain_db": "-4.0", "mode": "single"},
            "hover_card_show": {"file": "chime_bell_ding1.wav",
                                "enabled": "False", "volume": "",
                                "gain_db": "0.0", "mode": "single"},
        }
    profile["interval_notifs"] = [{
        "id": "interval_default_noon", "name": "Noon (12:00)", "minutes": 60,
        "enabled": True, "sound": "file:tick_on.wav", "volume": 0.05,
        "show_notification": True, "show_in_top_bar": False,
        "align_mode": "clock", "all_day": False,
        "start_minute": 720, "end_minute": 779,
        "last_fired": 1789808400.17,
        "last_fired_minute": "2026-09-19 12:00",
    }]
    profile["temp_timer_settings"] = {
        "name": "Temp Timer", "increment_minutes": 15,
        "sound": "file:tick_on.wav", "volume": 0.05, "sound_mode": "single",
        "show_notification": True, "show_in_top_bar": True,
        "sound_rules": [], "last_fired": 123.0,
    }
    profile["productivity_timer"] = {
        "work_seconds": 2730, "break_seconds": 930, "breaks_enabled": True,
        "completed_cycles": 7, "work_sound": "file:tick_on.wav",
        "break_sound": "file:ui_save.wav", "volume": 0.05,
        "sound_enabled": True,
    }
    profile["window_presets"] = [{
        "name": "Preset 4", "x": 0.3656, "y": 0.3203, "w": 0.538,
        "h": 0.6287, "state": "normal"}]
    return profile


def _plan(source=None, base=None, check_assets=False, assets=None):
    kwargs = {}
    if assets is not None:
        builtin, user = assets
        kwargs = {"builtin_root": builtin, "user_root": user}
    return bake.build_bake_plan(
        source if source is not None else _live_custom_profile(),
        base, check_assets=check_assets, **kwargs)


# ---------------------------------------------------------------------------
# A/B/C/D/E/F/G/H -- extraction contract
# ---------------------------------------------------------------------------

def test_a_safe_custom_preferences_survive_exactly():
    plan = _plan()
    assert plan.ok
    profile = plan.profile
    assert profile["theme"] == "Golden Default"
    assert profile["sound_volume"] == "0.09"
    assert profile["sound_typewriter"] == "True"
    assert profile["saved_sidebar_size"] == "258"
    assert profile["sound_events"]["click"]["file"] == "tick_on.wav"
    assert profile["sound_events"]["paste"]["file"] == "pickup_grenade_03.wav"
    assert profile["sound_events"]["clear"]["file"] == "KILLFADE.wav"
    assert profile["sound_events"]["delete"]["file"] == "fiveseven_clipout.wav"
    assert profile["saved_sound_mappings"]["click"] == "tick_on.wav"
    assert profile["limit_colors"] == {"reset_codex": "#4bc0ff"}


def test_b_baked_sidebar_geometry_is_open_on_the_right():
    profile = _plan().profile
    assert profile["sidebar_right"] == "True"
    sizes = profile["splitter_sizes_right"]
    assert sizes == [0, 768, 258]
    assert sizes[-1] > 0, "the sidebar pane must carry a non-zero width"
    assert int(profile["saved_sidebar_size"]) > 0


def test_c_modern_sound_event_fields_are_never_downgraded():
    source = _live_custom_profile()
    base = {"sound_events": {"click": {"file": "legacy.wav",
                                       "enabled": "True", "volume": ""}}}
    plan = bake.build_bake_plan(source, base, check_assets=False)
    entry = plan.profile["sound_events"]["click"]
    assert entry["file"] == "tick_on.wav"
    assert entry["gain_db"] == "-3.0"
    assert entry["mode"] == "single"
    assert entry["enabled"] == "True"


def test_d_new_appearance_events_survive_an_old_base():
    base = {"sound_events": {"click": {"file": "legacy.wav"}}}
    plan = bake.build_bake_plan(_live_custom_profile(), base,
                                check_assets=False)
    events = plan.profile["sound_events"]
    assert "app_show" in events and events["app_show"]["file"] == "menu1.wav"
    assert "hover_card_show" in events

    # 70-event modern map: every entry and its gain/mode survives.
    source = _live_custom_profile()
    source["sound_events"] = {
        f"event_{i}": {"file": "tick_on.wav", "enabled": "True",
                       "gain_db": f"-{i / 10}", "mode": "single"}
        for i in range(70)}
    plan = bake.build_bake_plan(source, {"sound_events": {}},
                                check_assets=False)
    baked = plan.profile["sound_events"]
    assert len(baked) == 70
    assert baked["event_69"]["gain_db"] == "-6.9"
    assert baked["event_69"]["mode"] == "single"


def test_e_personal_content_is_excluded():
    source = _live_custom_profile()
    # Formatted-block maps are keyed by PERSONAL silo headings: they may never
    # ship even though they look like a UI preference.
    source["aligned_blocks"] = '{"# Personal heading": "center"}'
    source["centered_blocks"] = '["# Personal heading"]'
    plan = bake.build_bake_plan(source, check_assets=False)
    profile = plan.profile
    for leaked in ("SECRET PERSONAL TEXT", "# secret", "private_repo",
                   "private deadline", "C:\\secret\\file.md",
                   "Personal heading"):
        assert leaked not in repr(profile)
    assert "aligned_blocks" not in profile
    assert "centered_blocks" not in profile
    assert "line_marks_data" not in profile
    assert "last_geometry" not in profile
    assert "files_root" not in profile


def test_policy_sets_are_disjoint():
    assert bake.policy_conflicts() == []


def test_f_machine_account_state_is_neutral():
    profile = _plan().profile
    assert profile["limit_codex_homes"] == ""
    assert profile["limit_claude_homes"] == ""
    assert profile["limit_zcode_config"] == ""
    assert profile["limit_freebuff_state"] == ""
    assert profile["limit_gauges_hidden_accounts"] == []
    assert profile["limit_notifications"] == {}
    assert profile["limit_notification_state"] == {}


def test_g_interval_last_fired_is_neutral_but_rule_survives():
    rule = _plan().profile["interval_notifs"][0]
    assert rule["last_fired"] == 0.0
    assert rule["last_fired_minute"] == ""
    assert rule["id"] == "interval_default_noon"
    assert rule["minutes"] == 60
    assert rule["enabled"] is True
    assert rule["sound"] == "file:tick_on.wav"


def test_h_language_release_override_is_en():
    plan = _plan()
    assert plan.profile["language"] == "EN"
    assert any("release override" in w for w in plan.warnings)


# ---------------------------------------------------------------------------
# I/J -- sound asset validation
# ---------------------------------------------------------------------------

def test_i_packaged_references_are_accepted(assets):
    plan = _plan(check_assets=True, assets=assets)
    assert plan.ok, [a.ref for a in plan.refused]
    assert plan.assets
    assert all(a.status == bake.PACKAGED for a in plan.assets)


def test_j_managed_only_is_refused_never_substituted(tmp_path):
    builtin = tmp_path / "packaged"
    user = tmp_path / "managed"
    builtin.mkdir()
    user.mkdir()
    for name in ("tick_on.wav", "pickup_grenade_03.wav", "KILLFADE.wav",
                 "fiveseven_clipout.wav", "ui_save.wav", "menu1.wav",
                 "chime_bell_ding1.wav"):
        _wav(builtin, name)
    _wav(user, "custom_click.wav")
    source = _live_custom_profile()
    source["sound_events"] = {
        "click": {"file": "custom_click.wav", "enabled": "True",
                  "gain_db": "0.0", "mode": "single"}}
    plan = bake.build_bake_plan(source, check_assets=True,
                                builtin_root=str(builtin),
                                user_root=str(user))
    assert not plan.ok
    assert [a.status for a in plan.refused] == [bake.MANAGED_ONLY]
    # The refused mapping is NOT silently swapped for a default sound.
    assert plan.profile["sound_events"]["click"]["file"] == "custom_click.wav"

    target = tmp_path / "default_profile.py"
    target.write_text('"""x"""\n\nDEFAULT_PROFILE = {}\n', encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    with pytest.raises(bake.BakeRefusalError):
        bake.apply_bake_plan(plan, target_file=str(target))
    assert target.read_text(encoding="utf-8") == before


def test_j2_missing_reference_is_refused(tmp_path):
    builtin = tmp_path / "packaged"
    user = tmp_path / "managed"
    builtin.mkdir()
    user.mkdir()
    for name in ("tick_on.wav", "pickup_grenade_03.wav", "KILLFADE.wav",
                 "fiveseven_clipout.wav", "ui_save.wav", "menu1.wav",
                 "chime_bell_ding1.wav"):
        _wav(builtin, name)
    source = _live_custom_profile()
    source["sound_events"] = {
        "click": {"file": "nowhere.wav", "enabled": "True"}}
    plan = bake.build_bake_plan(source, check_assets=True,
                                builtin_root=str(builtin),
                                user_root=str(user))
    assert not plan.ok
    assert [a.status for a in plan.refused] == [bake.MISSING]


# ---------------------------------------------------------------------------
# K/L/M/N -- write-path safety
# ---------------------------------------------------------------------------

def test_k_dry_run_does_not_write(tmp_path):
    plan = _plan()
    target = tmp_path / "default_profile.py"
    target.write_text('"""sentinel"""\n\nDEFAULT_PROFILE = {}\n',
                      encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    result = bake.apply_bake_plan(plan, target_file=str(target), dry_run=True)
    assert result["dry_run"] is True
    assert result["roundtrip_equal"] is None
    assert target.read_text(encoding="utf-8") == before


def test_m_fresh_profile_roundtrip_equals_sanitized_snapshot(tmp_path):
    plan = _plan()
    target = tmp_path / "default_profile.py"
    target.write_text('"""header"""\n\nDEFAULT_PROFILE = {}\n',
                      encoding="utf-8")
    result = bake.apply_bake_plan(plan, target_file=str(target))
    assert result["roundtrip_equal"] is True
    # An INDEPENDENT read of the written file (no AST-only trust) equals the
    # sanitized snapshot for every shippable key.
    reloaded = bake._reload_written_module(str(target))
    assert reloaded == plan.profile
    assert reloaded["sound_volume"] == "0.09"
    assert reloaded["sidebar_right"] == "True"
    assert reloaded["language"] == "EN"
    assert reloaded["interval_notifs"][0]["last_fired"] == 0.0


def test_n_frozen_build_cannot_mutate_repository_defaults(tmp_path, monkeypatch):
    plan = _plan()
    target = tmp_path / "default_profile.py"
    target.write_text('"""sentinel"""\n\nDEFAULT_PROFILE = {}\n',
                      encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    monkeypatch.setattr(bake, "is_frozen_build", lambda: True)
    with pytest.raises(bake.BakeFrozenError):
        bake.apply_bake_plan(plan, target_file=str(target))
    assert target.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Schema completeness guard (SRC-029 §14)
# ---------------------------------------------------------------------------

def test_every_shipped_default_key_is_classified():
    from fastprompter.core.default_profile import DEFAULT_PROFILE
    missing = bake.assert_policy_covers(DEFAULT_PROFILE.keys())
    assert missing == [], missing


def test_unclassified_new_setting_fails_the_bake():
    with pytest.raises(bake.BakePolicyError):
        bake.build_bake_plan({"theme": "X", "brand_new_setting_zzz": 1},
                             {"theme": "Y"}, check_assets=False)


def test_extract_raises_on_unclassified_key():
    with pytest.raises(bake.BakePolicyError):
        bake.extract_defaults_from_data(
            {"theme": "X", "brand_new_setting_zzz": 1}, {"theme": "Y"})


# ---------------------------------------------------------------------------
# L (UI contract) -- cancelled preview does not write
# ---------------------------------------------------------------------------

def test_l_cancelled_preview_does_not_write(monkeypatch):
    from fastprompter.ui import settings_builder

    calls = []
    plan = _plan()

    class _FakeButton:
        def __init__(self):
            self.enabled = True

        def setEnabled(self, value):  # noqa: N802
            self.enabled = value

    class _FakeBox:
        ButtonRole = _RealMessageBox.ButtonRole
        clicked = None
        detail = ""

        def __init__(self, parent=None):
            self.buttons = []

        def setWindowTitle(self, text):  # noqa: N802
            pass

        def setText(self, text):
            pass

        def setDetailedText(self, text):  # noqa: N802
            _FakeBox.detail = text

        def addButton(self, text, role):  # noqa: N802
            button = _FakeButton()
            self.buttons.append(button)
            return button

        def exec(self):
            # Simulate the operator pressing Cancel (last button).
            _FakeBox.clicked = self.buttons[-1]

        def clickedButton(self):  # noqa: N802
            return _FakeBox.clicked

    monkeypatch.setattr(settings_builder, "QMessageBox", _FakeBox)
    monkeypatch.setattr(bake, "apply_bake_plan",
                        lambda *a, **kw: calls.append((a, kw)))
    decided = settings_builder.confirm_bake_plan(plan, None, "EN")
    assert decided is False
    assert calls == []
    assert "SAFE VALUES COPIED" in _FakeBox.detail


def test_l2_apply_preview_is_explicit(monkeypatch):
    from fastprompter.ui import settings_builder

    class _FakeButton:
        def setEnabled(self, value):  # noqa: N802
            pass

    class _FakeBox:
        ButtonRole = _RealMessageBox.ButtonRole

        def __init__(self, parent=None):
            self.buttons = []

        def setWindowTitle(self, text):  # noqa: N802
            pass

        def setText(self, text):
            pass

        def setDetailedText(self, text):  # noqa: N802
            pass

        def addButton(self, text, role):  # noqa: N802
            button = _FakeButton()
            self.buttons.append(button)
            return button

        def exec(self):
            self._clicked = self.buttons[0]

        def clickedButton(self):  # noqa: N802
            return self._clicked

    monkeypatch.setattr(settings_builder, "QMessageBox", _FakeBox)
    from fastprompter.ui import settings_builder as sb
    assert sb.confirm_bake_plan(_plan(), None, "EN") is True


# ---------------------------------------------------------------------------
# O -- reset queue narrow card layout
# ---------------------------------------------------------------------------

def _rows():
    return [
        {"n": 1, "account": "Claude Work Account Long", "pool": "Claude and GPT models",
         "window": "Weekly", "left": "3d 4h 2m", "color": "#d9932f"},
        {"n": 2, "account": "Codex Personal", "pool": "",
         "window": "5h", "left": "42m", "color": "#4bc0ff"},
    ]


_LABELS = {"Account": "Account", "Pool": "Pool", "Window": "Window",
           "Left": "Left"}


def test_o_narrow_card_keeps_essential_columns_readable():
    from fastprompter.ui.reset_queue_card import render_table, required_width

    rows = _rows()

    def measure(text):
        return len(text) * 7  # deterministic char-width proxy

    wide_required = required_width(rows, _LABELS, measure)
    narrow_available = 240

    html = render_table(rows, header="Next resets", labels=_LABELS,
                        available_width=narrow_available, measure=measure)
    assert "Account / Pool" in html
    # Account is elided to the documented budget, never clipped by the popup,
    # and the Pool stacks under it in the same cell.
    assert "Claude Work Account" in html
    assert "<br/>" in html
    assert "Claude and GPT mode" in html
    assert "Weekly" in html and "3d 4h 2m" in html
    assert "42m" in html
    # wide composition would need more than the popup can give
    assert wide_required > narrow_available


def test_o2_wide_card_keeps_the_five_column_composition():
    from fastprompter.ui.reset_queue_card import render_table, required_width

    rows = _rows()

    def measure(text):
        return len(text) * 7

    wide_required = required_width(rows, _LABELS, measure)
    html = render_table(rows, header="Next resets", labels=_LABELS,
                        available_width=wide_required + 40, measure=measure)
    assert "Account / Pool" not in html
    assert html.count("<tr>") == 3          # header + two rows
