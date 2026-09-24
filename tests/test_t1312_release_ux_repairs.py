"""T-1312: runtime/UX defects found before the 0.8.68 freeze.

A. Freebuff total-spendable badge in the AI-limit hover card header.
B. Show Trash toggle called the removed ``refresh_categories()`` and raised.
C. ``date_emoji`` fallbacks disagreed (settings "False", profile resync
   "True"); every path now derives from DEFAULT_PROFILE.
D. Settings buttons translated only at build time kept the language they were
   built in, so a live switch left Estonian buttons in a Russian panel.

All fixtures synthetic.
"""

import os
import pathlib
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _qt_retire import retire
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

_app = QApplication.instance() or QApplication(sys.argv)

import fastprompter.core.state as state_mod
from fastprompter.core.default_profile import DEFAULT_PROFILE
from fastprompter.core.profile_flags import profile_flag
from fastprompter.core.translations import tr
from fastprompter.core.usage_limits.freebuff_format import (
    format_amount,
    spendable_total,
)
from fastprompter.core.usage_limits.model import (
    OK,
    STALE,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.main import FastPrompter

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


# ---------------------------------------------------------------------------
# A. Freebuff total spendable badge
# ---------------------------------------------------------------------------

def _fb_snap(status=OK, daily=10.0, limit=105.0, wallet=15.0,
             total="auto", mode="freebucks"):
    acc = AccountRef("freebuff", "fb1", "Freebuff", "auto_default")
    windows = []
    if daily is not None:
        windows.append(UsageWindow(
            key="daily_amount", duration_minutes=1440, available=True,
            used_percent=(limit - daily) / limit * 100.0,
            remaining_percent=daily / limit * 100.0,
            used_amount=limit - daily, remaining_amount=daily,
            limit_amount=limit, unit="FB",
            resets_at_epoch=time.time() + 3600))
    meta = {"mode": mode, "wallet_balance": wallet, "unit": "FB"}
    if total == "auto":
        meta["total_balance"] = (daily or 0.0) + (wallet or 0.0)
    elif total is not None:
        meta["total_balance"] = total
    return UsageSnapshot(account=acc, status=status, windows=windows,
                         plan_type="starter", fetched_at=time.time(),
                         provider_metadata=meta)


class TestSpendableTotal:
    def test_vendor_total_is_the_truth(self):
        assert spendable_total(_fb_snap(total=25.0)) == 25.0

    def test_proven_zero_is_kept(self):
        assert spendable_total(_fb_snap(daily=0.0, wallet=0.0, total=0.0)) == 0.0

    def test_fallback_needs_both_amounts(self):
        assert spendable_total(_fb_snap(total=None)) == 25.0
        assert spendable_total(_fb_snap(total=None, wallet=None)) is None
        assert spendable_total(_fb_snap(total=None, daily=None)) is None

    def test_no_badge_for_non_freebucks_data(self):
        assert spendable_total(_fb_snap(mode="legacy")) is None

    @pytest.mark.parametrize("bad", [float("nan"), -1.0, True, "25"])
    def test_untrustworthy_total_is_not_shown(self, bad):
        assert spendable_total(_fb_snap(total=bad, wallet=None)) is None

    def test_format_has_no_float_tail(self):
        assert format_amount(25.0) == "25"
        assert format_amount(0.0) == "0"
        assert format_amount(7.333333333) == "7.33"
        assert format_amount(12.5) == "12.5"


def _tooltip(snap):
    from test_usage_limits_gauge_layout import _build
    gauges = _build(_app, [snap.account], {snap.account.key: snap})
    try:
        return gauges._build_tooltip()
    finally:
        gauges.main_win.close()


def _header_row(html_text):
    start = html_text.index("<b")
    return html_text[start:html_text.index("</tr>", start)]


class TestHoverBadge:
    def test_header_carries_total_and_detail_keeps_components(self):
        text = _tooltip(_fb_snap(daily=10.0, wallet=15.0, total=25.0))
        assert "&nbsp;25&nbsp;" in _header_row(text)
        assert "10/105 FB" in text
        assert "Wallet: <b>15 FB</b>" in text

    def test_empty_daily_pool_badge_is_wallet(self):
        text = _tooltip(_fb_snap(daily=0.0, wallet=15.0, total=15.0))
        assert "&nbsp;15&nbsp;" in _header_row(text)

    def test_explicit_zero_total_renders_zero(self):
        text = _tooltip(_fb_snap(daily=0.0, wallet=0.0, total=0.0))
        assert "&nbsp;0&nbsp;" in _header_row(text)

    @pytest.mark.parametrize("status", ["ERROR", "UNAVAILABLE", "AUTH_REQUIRED"])
    def test_failed_state_fabricates_no_badge(self, status):
        text = _tooltip(_fb_snap(status=status, total=25.0))
        assert "&nbsp;25&nbsp;" not in text

    def test_stale_badge_wears_stale_tint(self, monkeypatch):
        fresh = _header_row(_tooltip(_fb_snap(total=25.0)))
        stale = _header_row(_tooltip(_fb_snap(status=STALE, total=25.0)))
        assert "&nbsp;25&nbsp;" in stale
        fresh_bg = fresh.split("background-color:")[1].split(";")[0]
        stale_bg = stale.split("background-color:")[1].split(";")[0]
        assert fresh_bg != stale_bg


# ---------------------------------------------------------------------------
# Real window fixture (B, C, D)
# ---------------------------------------------------------------------------

@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / f"t_{profile_id}.db"))
    for name in ("setup_single_instance_server", "register_all_hotkeys",
                 "unregister_all_hotkeys"):
        monkeypatch.setattr(FastPrompter, name, lambda self: None)
    from fastprompter.core.usage_limits.service import UsageLimitService
    monkeypatch.setattr(UsageLimitService, "schedule_auto", lambda *a, **kw: None)
    w = FastPrompter()
    w._ensure_settings_built()
    yield w
    if getattr(w, "limit_service", None) is not None:
        try:
            w.limit_service.shutdown()
        except Exception:
            pass
    w._wait_for_undo_saves()
    w._logical_finalized = True
    w.tray_icon.hide()
    w.close()
    retire(w)


# ---------------------------------------------------------------------------
# B. Show Trash toggle
# ---------------------------------------------------------------------------

def _combo_items(w):
    return [w.cat_combo.itemData(i) for i in range(w.cat_combo.count())]


def _setup_projects(w, hidden=()):
    for name in ("Alpha", "Beta", "Gamma"):
        w.data["categories"].setdefault(name, [])
        if name not in w.data["cats_order"]:
            w.data["cats_order"].append(name)
    w.data["hidden_categories"] = list(hidden)
    w.rebuild_cat_combo(keep="Beta")
    assert w.get_current_category() == "Beta"


class TestTrashToggle:
    def test_no_stale_refresh_categories_caller(self):
        hits = [p for p in (SRC / "fastprompter").rglob("*.py")
                if "refresh_categories" in p.read_text(encoding="utf-8")]
        assert hits == []

    def test_toggle_on_keeps_project_and_adds_trash(self, win):
        _setup_projects(win)
        win.toggle_trash_vision(True)
        assert win.get_current_category() == "Beta"
        assert "Trash" in _combo_items(win)
        assert win.data["cats_order"].count("Trash") == 1
        assert win.data["trash_vision"] == "True"

    def test_toggle_off_keeps_project_and_removes_trash(self, win):
        _setup_projects(win)
        win.toggle_trash_vision(True)
        win.toggle_trash_vision(False)
        assert win.get_current_category() == "Beta"
        assert "Trash" not in _combo_items(win)
        assert "Trash" not in win.data["cats_order"]
        assert "Trash" in win.data["categories"]      # nothing deleted

    def test_hidden_projects_stay_hidden(self, win):
        _setup_projects(win, hidden=("Gamma",))
        win.toggle_trash_vision(True)
        assert "Gamma" not in _combo_items(win)
        assert win.get_current_category() == "Beta"
        assert win.cat_combo.currentText() == "Beta"
        win.toggle_trash_vision(False)
        assert "Gamma" not in _combo_items(win)
        assert win.cat_combo.currentData() == "Beta"

    def test_existing_trash_is_not_duplicated(self, win):
        _setup_projects(win)
        win.data["categories"]["Trash"] = []
        win.data["cats_order"].append("Trash")
        win.toggle_trash_vision(True)
        assert win.data["cats_order"].count("Trash") == 1
        assert _combo_items(win).count("Trash") == 1

    def test_repeated_toggles_are_idempotent(self, win):
        _setup_projects(win)
        for state in (True, False, True):
            win.toggle_trash_vision(state)
        items = _combo_items(win)
        assert len(items) == len(set(items))
        assert items.count("Trash") == 1
        assert len(win._cat_num_buttons) == win.cat_combo.count()
        assert win.get_current_category() == "Beta"

    def test_toggle_marks_profile_dirty(self, win):
        _setup_projects(win)
        calls = []
        win.mark_dirty = lambda *a, **k: calls.append(1)
        win.toggle_trash_vision(True)
        assert calls

    def test_persisted_state_reproduces_visible_result(self, win):
        _setup_projects(win)
        win.toggle_trash_vision(True)
        shown = _combo_items(win)
        assert win.save_data_to_db(force=True)
        reloaded = state_mod.FastPrompterState(win.state.profile_id)
        try:
            assert reloaded.data["trash_vision"] == "True"
            hidden = set(reloaded.data.get("hidden_categories") or [])
            visible = [c for c in reloaded.data["cats_order"]
                       if c not in hidden]
            assert visible == shown
        finally:
            if reloaded.conn is not None:
                reloaded.conn.close()


# ---------------------------------------------------------------------------
# C. date_emoji single source of truth
# ---------------------------------------------------------------------------

@pytest.fixture
def night(win, monkeypatch):
    monkeypatch.setattr(type(win), "_day_part", staticmethod(lambda h: "Night"))
    monkeypatch.setattr(win, "_topbar_detail_mode", lambda token: "full")
    # PERF-004 skips the label while hidden; offscreen windows never show.
    monkeypatch.setattr(win, "isVisible", lambda: True)
    win.data["show_date_rect"] = "True"
    win.data["date_daypart"] = "True"
    return win


class TestDateEmoji:
    def test_every_reader_uses_the_shipped_default(self):
        assert profile_flag({}, "date_emoji") is (
            DEFAULT_PROFILE["date_emoji"] == "True")
        main = (SRC / "fastprompter" / "main.py").read_text(encoding="utf-8")
        builder = (SRC / "fastprompter" / "ui" / "settings_builder.py"
                   ).read_text(encoding="utf-8")
        for text in (main, builder):
            assert 'get("date_emoji", "' not in text
            assert 'get("date_daypart", "' not in text
        assert '("cb_date_emoji", "date_emoji", "True")' not in main

    def test_live_toggle_false_to_true_and_back(self, night):
        w = night
        w.data["date_emoji"] = "False"
        w._update_date_label()
        assert "Night" in w.lbl_date.text()
        assert "🌙" not in w.lbl_date.text()
        w.cb_date_emoji.setChecked(True)
        assert w.data["date_emoji"] == "True"
        assert "🌙" in w.lbl_date.text()
        w.cb_date_emoji.setChecked(False)
        assert w.data["date_emoji"] == "False"
        assert "🌙" not in w.lbl_date.text()
        assert "Night" in w.lbl_date.text()

    def test_daypart_off_renders_neither(self, night):
        w = night
        w.data["date_daypart"] = "False"
        w.data["date_emoji"] = "True"
        w._update_date_label()
        assert "🌙" not in w.lbl_date.text()
        assert "Night" not in w.lbl_date.text()

    def test_profile_a_true_profile_b_false(self, night):
        w = night
        for value, emoji in (("True", True), ("False", False), ("True", True)):
            w.data["date_emoji"] = value
            w._resync_profile_widgets()
            w._update_date_label()
            assert w.cb_date_emoji.isChecked() is emoji
            assert ("🌙" in w.lbl_date.text()) is emoji

    def test_missing_legacy_key_reads_shipped_default(self, night):
        w = night
        w.cb_date_emoji.blockSignals(True)
        w.cb_date_emoji.setChecked(True)          # stale widget state
        w.cb_date_emoji.blockSignals(False)
        w.data.pop("date_emoji", None)
        w._resync_profile_widgets()
        w._update_date_label()
        expected = DEFAULT_PROFILE["date_emoji"] == "True"
        assert w.cb_date_emoji.isChecked() is expected
        assert ("🌙" in w.lbl_date.text()) is expected

    def test_russian_ui_with_emoji(self, night):
        w = night
        w._on_language_changed("RU")
        w.data["date_emoji"] = "True"
        w._update_date_label()
        assert "🌙" in w.lbl_date.text()
        assert tr("Night", "RU") not in w.lbl_date.text()
        w.data["date_emoji"] = "False"
        w._update_date_label()
        assert tr("Night", "RU") in w.lbl_date.text()


def test_date_rendering_does_not_need_settings(monkeypatch, tmp_path):
    """The topbar decision reads data alone; Settings is lazy."""
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / f"t_{profile_id}.db"))
    for name in ("setup_single_instance_server", "register_all_hotkeys",
                 "unregister_all_hotkeys"):
        monkeypatch.setattr(FastPrompter, name, lambda self: None)
    from fastprompter.core.usage_limits.service import UsageLimitService
    monkeypatch.setattr(UsageLimitService, "schedule_auto", lambda *a, **kw: None)
    w = FastPrompter()
    try:
        assert not getattr(w, "_settings_built", False)
        monkeypatch.setattr(type(w), "_day_part", staticmethod(lambda h: "Night"))
        monkeypatch.setattr(w, "_topbar_detail_mode", lambda token: "full")
        monkeypatch.setattr(w, "isVisible", lambda: True)
        w.data.update({"show_date_rect": "True", "date_daypart": "True",
                       "date_emoji": "True"})
        w._update_date_label()
        assert "🌙" in w.lbl_date.text()
    finally:
        w._wait_for_undo_saves()
        w._logical_finalized = True
        w.tray_icon.hide()
        w.close()
        retire(w)


# ---------------------------------------------------------------------------
# D. Settings language coherence
# ---------------------------------------------------------------------------

_GROUPS = ("Window behaviour", "Layout", "Toolbar", "Window presets", "Date")


def _group_widgets(w):
    for box in w.mini_settings_frame.findChildren(QWidget):
        if box.objectName() != "SettingsGroup":
            continue
        titles = [lbl._en_text for lbl in box.findChildren(QLabel)
                  if getattr(lbl, "_en_text", None)]
        if titles and titles[0] in _GROUPS:
            yield box


class TestSettingsLanguage:
    def test_static_buttons_carry_their_english_source(self, win):
        missing = [b.text() for box in _group_widgets(win)
                   for b in box.findChildren(QPushButton)
                   if b.text() and not getattr(b, "_en_text", None)]
        assert missing == []
        assert win.btn_reset_layout._en_text == "Reset UI Layout"
        assert win.btn_manage_presets._en_text == "Manage presets"

    def test_est_then_ru_leaves_no_estonian_behind(self, win):
        win._on_language_changed("EST")
        assert win.btn_reset_layout.text() == tr("Reset UI Layout", "EST")
        win._on_language_changed("RU")
        for box in _group_widgets(win):
            for widget in box.findChildren(QWidget):
                en = getattr(widget, "_en_text", None)
                if en and hasattr(widget, "text"):
                    assert widget.text() == tr(en, "RU"), en
                tip = getattr(widget, "_en_tooltip", None)
                # some tooltips are re-composed later (hotkey suffix), so
                # the contract is only: no Estonian left behind
                if tip and tr(tip, "EST") != tr(tip, "RU"):
                    assert widget.toolTip() != tr(tip, "EST"), tip
        assert win.btn_reset_layout.text() == tr("Reset UI Layout", "RU")

    @pytest.mark.parametrize("lang", ["RU", "EST"])
    def test_visible_groups_are_translated(self, win, lang):
        win._on_language_changed(lang)
        untranslated = []
        for box in _group_widgets(win):
            for widget in box.findChildren(QWidget):
                for attr in ("_en_text", "_en_tooltip"):
                    en = getattr(widget, attr, None)
                    if en and tr(en, lang) == en:
                        untranslated.append(en)
        assert untranslated == []

    def test_image_viewer_caption_follows_language(self, win):
        win.data["image_viewer_mode"] = "system"
        win._on_language_changed("RU")
        assert win.btn_image_viewer.text() == f"🖼 {tr('System default', 'RU')}"
        win._on_language_changed("EN")
        assert win.btn_image_viewer.text() == "🖼 System default"
