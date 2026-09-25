"""Tests for hiding 0% usage accounts in AI limits."""

import dataclasses
import os
import sys
import tempfile
import time

import pytest
from PyQt6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_app = QApplication.instance() or QApplication(sys.argv)
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_limits_")

from _qt_retire import retire

import fastprompter.core.state as state_mod
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    MONTHLY,
    OK,
    STALE,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    account_has_usage,
    account_usable_now,
    display_windows,
    qualified_key,
)
from fastprompter.main import FastPrompter


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setattr(state_mod, "get_db_path",
                        lambda profile_id=1: str(tmp_path / f"test_{profile_id}.db"))
    for name in ("setup_single_instance_server", "register_all_hotkeys",
                 "unregister_all_hotkeys"):
        monkeypatch.setattr(FastPrompter, name, lambda self: None)
    from fastprompter.core.usage_limits.service import UsageLimitService
    monkeypatch.setattr(UsageLimitService, "schedule_auto", lambda *a, **kw: None)

    w = FastPrompter()
    yield w

    if hasattr(w, "limit_service") and w.limit_service is not None:
        try:
            w.limit_service.shutdown()
        except Exception:
            pass
    from PyQt6.QtCore import QEvent, QTimer
    w._wait_for_undo_saves()
    for timer in w.findChildren(QTimer):
        timer.stop()
    w._logical_finalized = True
    w.tray_icon.hide()
    w.close()
    # T-1286: receiver-scoped retirement (was deleteLater(), never delivered
    # without an event loop; the backlog stalled tests/test_timer_fire.py).
    retire(w)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _make_snapshot(provider="claude", status=OK, five_h_used=0.0, weekly_used=0.0):
    acc = AccountRef(provider, f"stable_{provider}", f"Test {provider}", "auto_default")
    windows = [
        UsageWindow(FIVE_HOUR, 300, True, five_h_used, 100.0 - five_h_used),
        UsageWindow(WEEKLY, 10080, True, weekly_used, 100.0 - weekly_used),
    ]
    return UsageSnapshot(acc, status, windows)


def _antigravity_snapshot(gemini_5h=0.0, gemini_w=0.0, claude_5h=0.0,
                          claude_w=0.0):
    """CLI-style Antigravity snapshot: two independent quota pools, each with
    its own weekly + 5h pair (qualified keys, per-pool gating)."""
    acc = AccountRef("antigravity", "stable_antigravity", "Antigravity",
                     "auto_default")
    windows = [
        UsageWindow(qualified_key(FIVE_HOUR, "gemini_models"), 300, True,
                    gemini_5h, 100.0 - gemini_5h, group="gemini_models",
                    group_label="Gemini models"),
        UsageWindow(qualified_key(WEEKLY, "gemini_models"), 10080, True,
                    gemini_w, 100.0 - gemini_w, group="gemini_models",
                    group_label="Gemini models"),
        UsageWindow(qualified_key(FIVE_HOUR, "claude_gpt"), 300, True,
                    claude_5h, 100.0 - claude_5h, group="claude_gpt",
                    group_label="Claude and GPT models"),
        UsageWindow(qualified_key(WEEKLY, "claude_gpt"), 10080, True,
                    claude_w, 100.0 - claude_w, group="claude_gpt",
                    group_label="Claude and GPT models"),
    ]
    return UsageSnapshot(acc, OK, windows)


def test_account_has_usage_truth_table():
    # 1. 0% in both 5h and weekly (untouched / 100% remaining) -> False
    s_zero = _make_snapshot(five_h_used=0.0, weekly_used=0.0)
    assert account_has_usage(s_zero) is False

    # 2. 0% left in both 5h and weekly (depleted / exhausted quota) -> False
    s_depleted = _make_snapshot(five_h_used=100.0, weekly_used=100.0)
    assert account_has_usage(s_depleted) is False

    # 3. 0% left in 5h, but weekly has 69% left (active usage + quota) -> True
    s_codex = _make_snapshot(five_h_used=100.0, weekly_used=31.0)
    assert account_has_usage(s_codex) is True

    # 4. > 0% in 5h only -> True
    s_5h = _make_snapshot(five_h_used=12.5, weekly_used=0.0)
    assert account_has_usage(s_5h) is True

    # 5. > 0% in weekly only -> True
    s_weekly = _make_snapshot(five_h_used=0.0, weekly_used=4.0)
    assert account_has_usage(s_weekly) is True

    # 6. Both > 0% -> True
    s_both = _make_snapshot(five_h_used=15.0, weekly_used=25.0)
    assert account_has_usage(s_both) is True

    # 7. Stale account with usage -> True
    s_stale = _make_snapshot(status=STALE, five_h_used=10.0, weekly_used=0.0)
    assert account_has_usage(s_stale) is True

    # 8. Error status -> False
    s_err = _make_snapshot(status="ERROR", five_h_used=50.0, weekly_used=50.0)
    assert account_has_usage(s_err) is False

    # 9. None snapshot -> False
    assert account_has_usage(None) is False


def test_limit_gauges_hide_zero_usage_filtering(win):
    acc_zero = AccountRef("claude", "acc_zero", "Zero Acc", "auto_default")
    acc_active = AccountRef("codex", "acc_active", "Active Acc", "auto_default")

    snap_zero = _make_snapshot("claude", five_h_used=0.0, weekly_used=0.0)
    snap_active = _make_snapshot("codex", five_h_used=20.0, weekly_used=5.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_zero, acc_active]
        win.limit_service._state.snapshots = {
            acc_zero.key: snap_zero,
            acc_active.key: snap_active,
        }

    # Default: hide_zero_usage is False -> both visible
    win.data["limit_gauges_hide_zero_usage"] = "False"
    visible = win.limit_gauges._visible_accounts()
    assert len(visible) == 2

    # Enable hide_zero_usage -> only acc_active visible
    win.data["limit_gauges_hide_zero_usage"] = "True"
    visible_filtered = win.limit_gauges._visible_accounts()
    assert len(visible_filtered) == 1
    assert visible_filtered[0].key == acc_active.key


def test_limit_overview_hide_zero_usage_filtering(win):
    from fastprompter.ui.limit_overview import LimitOverview

    acc_zero = AccountRef("claude", "acc_zero", "Zero Acc", "auto_default")
    acc_active = AccountRef("codex", "acc_active", "Active Acc", "auto_default")

    snap_zero = _make_snapshot("claude", five_h_used=0.0, weekly_used=0.0)
    snap_active = _make_snapshot("codex", five_h_used=20.0, weekly_used=5.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_zero, acc_active]
        win.limit_service._state.snapshots = {
            acc_zero.key: snap_zero,
            acc_active.key: snap_active,
        }

    overview = LimitOverview(win, win.limit_service)

    # Filter OFF -> 2 accounts
    win.data["limit_gauges_hide_zero_usage"] = "False"
    overview.refresh()
    acc_rows = [r for r in overview._rows if r[0] == "account"]
    assert len(acc_rows) == 2

    # Filter ON -> 1 account
    win.data["limit_gauges_hide_zero_usage"] = "True"
    overview.refresh()
    acc_rows = [r for r in overview._rows if r[0] == "account"]
    assert len(acc_rows) == 1
    assert acc_rows[0][1].key == acc_active.key


def test_limit_settings_dialog_toggle_sync(win):
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    # The persisted default decides the initial state (profiles store the
    # hide-zero default as True); the contract is that BOTH views mirror it
    # and stay in sync afterwards.
    initial = win.data.get("limit_gauges_hide_zero_usage", "False") == "True"

    dialog = LimitSettingsDialog(win)
    try:
        assert dialog.cb_hide_zero.isChecked() is initial
        assert dialog.cb_overview_hide_zero.isChecked() is initial

        # Toggle in Gauges tab
        dialog.cb_hide_zero.setChecked(True)
        assert win.data.get("limit_gauges_hide_zero_usage") == "True"
        assert dialog.cb_overview_hide_zero.isChecked() is True

        # Toggle in Overview tab
        dialog.cb_overview_hide_zero.setChecked(False)
        assert win.data.get("limit_gauges_hide_zero_usage") == "False"
        assert dialog.cb_hide_zero.isChecked() is False
    finally:
        dialog.close()


def test_soonest_reset_retains_accounts_hidden_by_usage_filter(win):
    acc_zero = AccountRef("claude", "acc_zero", "Zero Acc", "auto_default")
    acc_active = AccountRef("codex", "acc_active", "Active Acc", "auto_default")

    now = time.time()
    # acc_zero resets in 10 minutes, but has 0% usage
    w_zero = [
        UsageWindow(FIVE_HOUR, 300, True, 0.0, 100.0, now + 605),
    ]
    # acc_active resets in 2 hours, has 50% usage
    w_active = [
        UsageWindow(FIVE_HOUR, 300, True, 50.0, 50.0, now + 7205),
    ]

    snap_zero = UsageSnapshot(acc_zero, OK, w_zero)
    snap_active = UsageSnapshot(acc_active, OK, w_active)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_zero, acc_active]
        win.limit_service._state.snapshots = {
            acc_zero.key: snap_zero,
            acc_active.key: snap_active,
        }

    win.data["limit_gauges"] = "True"
    win._header_dense = True

    # Without filter: earliest reset is from acc_zero (10m)
    win.data["limit_gauges_hide_zero_usage"] = "False"
    win._update_limit_timer_label()
    assert "10m" in win.lbl_limit_timer.text()

    # Automatic bar filtering cannot hide a reset countdown.
    win.data["limit_gauges_hide_zero_usage"] = "True"
    win._update_limit_timer_label()
    assert "10m" in win.lbl_limit_timer.text()


def test_depleted_0pct_left_accounts_hidden(win):
    """Accounts with 0% left in both 5h and weekly (Claude / ZCode) are hidden."""
    acc_claude = AccountRef("claude", "claude_depleted", "Claude", "auto_default")
    acc_codex = AccountRef("codex", "codex_active", "Codex 1", "auto_default")

    # Claude: 100% used in both 5h and weekly -> 0% left
    snap_claude = _make_snapshot("claude", five_h_used=100.0, weekly_used=100.0)
    # Codex: 100% used in 5h (0% left), but 31% used in weekly (69% left)
    snap_codex = _make_snapshot("codex", five_h_used=100.0, weekly_used=31.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_claude, acc_codex]
        win.limit_service._state.snapshots = {
            acc_claude.key: snap_claude,
            acc_codex.key: snap_codex,
        }

    # Hide 0% usage -> Claude (0% left in both) is hidden, Codex (69% left) is
    # shown; the shipped hide-unusable preference is pinned off so this test
    # isolates the hide-zero contract from the baked profile.
    win.data["limit_gauges_hide_unusable_5h"] = "False"
    win.data["limit_gauges_hide_zero_usage"] = "True"
    visible = win.limit_gauges._visible_accounts()
    assert len(visible) == 1
    assert visible[0].key == acc_codex.key


def test_limit_settings_dialog_syncs_with_topbar_result_ready(win):
    """Dialog overview auto-refreshes when topbar limit_gauges._result_ready fires."""
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    acc = AccountRef("codex", "codex_sync", "Codex Sync", "auto_default")
    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc]
        # Initially not probed yet
        win.limit_service._state.snapshots = {}
    win.data["limit_gauges_hide_zero_usage"] = "False"
    # shipped default is pinned off: this test isolates the dialog refresh
    win.data["limit_gauges_hide_unusable_5h"] = "False"

    dialog = LimitSettingsDialog(win)
    try:
        # Overview shows "not probed yet" initially
        assert any(r[0] == "note" and "not probed yet" in str(r[1]) for r in dialog.overview._rows)

        # Now probe arrives in background and service updates state
        snap = _make_snapshot("codex", five_h_used=40.0, weekly_used=20.0)
        with win.limit_service._lock:
            win.limit_service._state.snapshots = {acc.key: snap}

        # _result_ready signal emits
        win.limit_gauges._result_ready.emit()

        # Dialog overview is now automatically updated with live quota rows!
        assert not any(r[0] == "note" and "not probed yet" in str(r[1]) for r in dialog.overview._rows)
        assert any(r[0] == "window" for r in dialog.overview._rows)
    finally:
        dialog.close()


def test_account_usable_now_truth_table():
    """The "show only accounts usable right now" rule: a 0% 5h window makes
    the account unusable even while the weekly pool sits full."""
    # 5h exhausted (0% left), weekly full (100% left) -> NOT usable now
    s = _make_snapshot(five_h_used=100.0, weekly_used=0.0)
    assert account_usable_now(s) is False

    # both windows have quota -> usable
    s = _make_snapshot(five_h_used=30.0, weekly_used=50.0)
    assert account_usable_now(s) is True

    # weekly exhausted gates the 5h (the app's own gating) -> not usable
    s = _make_snapshot(five_h_used=30.0, weekly_used=100.0)
    assert account_usable_now(s) is False

    # both dead / both full
    assert account_usable_now(_make_snapshot(
        five_h_used=100.0, weekly_used=100.0)) is False
    assert account_usable_now(_make_snapshot(
        five_h_used=0.0, weekly_used=0.0)) is True

    # no 5h window at all (Codex Free: one 30-day pool) -> judged by it
    acc = AccountRef("codex", "stable_codex_free", "Codex Free",
                     "auto_default")
    s = UsageSnapshot(acc, OK, [UsageWindow(MONTHLY, 43200, True, 10.0, 90.0)])
    assert account_usable_now(s) is True
    s = UsageSnapshot(acc, OK, [UsageWindow(MONTHLY, 43200, True, 100.0, 0.0)])
    assert account_usable_now(s) is False

    # None / error status -> never usable
    assert account_usable_now(None) is False
    assert account_usable_now(_make_snapshot(status="ERROR")) is False

    # stale but with 5h quota -> still usable now
    assert account_usable_now(
        _make_snapshot(status=STALE, five_h_used=10.0)) is True

    # Antigravity: Gemini pool fully dead, Claude/GPT 5h alive -> usable
    s = _antigravity_snapshot(gemini_5h=100.0, gemini_w=100.0,
                              claude_5h=40.0, claude_w=60.0)
    assert account_usable_now(s) is True
    # Antigravity: every pool dead -> not usable now
    s = _antigravity_snapshot(gemini_5h=100.0, gemini_w=100.0,
                              claude_5h=100.0, claude_w=100.0)
    assert account_usable_now(s) is False


def test_display_windows_drops_dead_pools():
    """Hide 0/0: a pool whose windows are all spent disappears; a pool
    with any live window keeps every window."""
    s = _antigravity_snapshot(gemini_5h=100.0, gemini_w=100.0,
                              claude_5h=40.0, claude_w=60.0)
    shown = display_windows(s.windows)
    assert len(shown) == 2
    assert all("gemini" not in w.key for w in shown)
    assert all("claude_gpt" in w.key for w in shown)

    # one live window (weekly at 80%) keeps the whole Gemini pool
    s2 = _antigravity_snapshot(gemini_5h=100.0, gemini_w=80.0,
                               claude_5h=40.0, claude_w=60.0)
    assert len(display_windows(s2.windows)) == 2

    # single-pool accounts (no group) are never touched here
    s3 = _make_snapshot(five_h_used=100.0, weekly_used=0.0)
    assert len(display_windows(s3.windows)) == 2


def test_limit_gauges_hide_unusable_5h_filtering(win):
    acc_unusable = AccountRef("claude", "acc_no5h", "No 5h", "auto_default")
    acc_usable = AccountRef("codex", "acc_ok5h", "OK 5h", "auto_default")

    # 5h 0% left, weekly 100% left -> the account cannot do work right now
    snap_unusable = _make_snapshot("claude", five_h_used=100.0, weekly_used=0.0)
    snap_usable = _make_snapshot("codex", five_h_used=20.0, weekly_used=5.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_unusable, acc_usable]
        win.limit_service._state.snapshots = {
            acc_unusable.key: snap_unusable,
            acc_usable.key: snap_usable,
        }

    win.data["limit_gauges_hide_unusable_5h"] = "False"
    assert len(win.limit_gauges._visible_accounts()) == 2

    win.data["limit_gauges_hide_unusable_5h"] = "True"
    visible = win.limit_gauges._visible_accounts()
    assert len(visible) == 1
    assert visible[0].key == acc_usable.key


def test_limit_overview_hide_unusable_filtering(win):
    from fastprompter.ui.limit_overview import LimitOverview

    acc_unusable = AccountRef("claude", "acc_no5h", "No 5h", "auto_default")
    acc_usable = AccountRef("codex", "acc_ok5h", "OK 5h", "auto_default")
    snap_unusable = _make_snapshot("claude", five_h_used=100.0, weekly_used=0.0)
    snap_usable = _make_snapshot("codex", five_h_used=20.0, weekly_used=5.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_unusable, acc_usable]
        win.limit_service._state.snapshots = {
            acc_unusable.key: snap_unusable,
            acc_usable.key: snap_usable,
        }

    overview = LimitOverview(win, win.limit_service)
    win.data["limit_gauges_hide_unusable_5h"] = "False"
    overview.refresh()
    assert len([r for r in overview._rows if r[0] == "account"]) == 2

    win.data["limit_gauges_hide_unusable_5h"] = "True"
    overview.refresh()
    acc_rows = [r for r in overview._rows if r[0] == "account"]
    assert len(acc_rows) == 1
    assert acc_rows[0][1].key == acc_usable.key


def test_gauge_cluster_drops_dead_pool_windows(win):
    from fastprompter.ui.limit_gauges import _cluster_windows

    s = _antigravity_snapshot(gemini_5h=100.0, gemini_w=100.0,
                              claude_5h=40.0, claude_w=60.0)
    all_w = _cluster_windows(s, filter_dead_pools=False)
    assert len([w for w in all_w if w is not None]) == 4

    filtered = _cluster_windows(s, filter_dead_pools=True)
    live = [w for w in filtered if w is not None]
    assert len(live) == 2
    assert all("gemini" not in w.key for w in live)


def test_limit_overview_hides_dead_antigravity_pool_rows(win):
    from fastprompter.ui.limit_overview import LimitOverview

    acc = AccountRef("antigravity", "acc_ag", "Antigravity", "auto_default")
    snap = _antigravity_snapshot(gemini_5h=100.0, gemini_w=100.0,
                                 claude_5h=40.0, claude_w=60.0)
    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc]
        win.limit_service._state.snapshots = {acc.key: snap}

    overview = LimitOverview(win, win.limit_service)
    win.data["limit_gauges_hide_unusable_5h"] = "False"
    overview.refresh()
    win_rows = [r for r in overview._rows if r[0] == "window"]
    assert len(win_rows) == 4

    win.data["limit_gauges_hide_unusable_5h"] = "True"
    overview.refresh()
    win_rows = [r for r in overview._rows if r[0] == "window"]
    assert len(win_rows) == 2
    for _kind, w, _shot in win_rows:
        assert "gemini" not in w.key


def test_limit_settings_dialog_toggle_sync_unusable(win):
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    # pin the shipped preference off so the toggle starts from a known state
    win.data["limit_gauges_hide_unusable_5h"] = "False"
    dialog = LimitSettingsDialog(win)
    try:
        assert dialog.cb_hide_unusable.isChecked() is False
        assert dialog.cb_overview_hide_unusable.isChecked() is False

        dialog.cb_hide_unusable.setChecked(True)
        assert win.data.get("limit_gauges_hide_unusable_5h") == "True"
        assert dialog.cb_overview_hide_unusable.isChecked() is True

        dialog.cb_overview_hide_unusable.setChecked(False)
        assert win.data.get("limit_gauges_hide_unusable_5h") == "False"
        assert dialog.cb_hide_unusable.isChecked() is False
    finally:
        dialog.close()


def test_soonest_reset_retains_unusable_5h(win):
    acc_no5h = AccountRef("claude", "acc_no5h", "No 5h", "auto_default")
    acc_ok = AccountRef("codex", "acc_ok5h", "OK 5h", "auto_default")

    now = time.time()
    # 5h exhausted, weekly full; the 5h resets in 10 minutes
    w_no5h = [
        UsageWindow(FIVE_HOUR, 300, True, 100.0, 0.0, now + 605),
        UsageWindow(WEEKLY, 10080, True, 0.0, 100.0, now + 9999999),
    ]
    # 5h alive at 50%, resets in 2 hours
    w_ok = [
        UsageWindow(FIVE_HOUR, 300, True, 50.0, 50.0, now + 7205),
    ]

    snap_no5h = UsageSnapshot(acc_no5h, OK, w_no5h)
    snap_ok = UsageSnapshot(acc_ok, OK, w_ok)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_no5h, acc_ok]
        win.limit_service._state.snapshots = {
            acc_no5h.key: snap_no5h,
            acc_ok.key: snap_ok,
        }

    win.data["limit_gauges"] = "True"
    win._header_dense = True

    # Without the filter: the soonest reset belongs to the unusable account
    win.data["limit_gauges_hide_unusable_5h"] = "False"
    win._update_limit_timer_label()
    assert "10m" in win.lbl_limit_timer.text()

    # Hiding unusable gauges must retain the reset we are waiting for.
    win.data["limit_gauges_hide_unusable_5h"] = "True"
    win._update_limit_timer_label()
    assert "10m" in win.lbl_limit_timer.text()


def test_hidden_accounts_with_banked_resets_are_announced(win):
    """A hidden account still owns its reset credits — say so, or they rot.

    Both ways of disappearing count: filtered out by the 0%-usage rule (a
    depleted Codex is exactly the account whose banked reset matters most), and
    unticked by hand in the account list.
    """
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog

    acc_zero = AccountRef("codex", "codex_zero", "Codex Zero", "auto_default")
    acc_unticked = AccountRef("codex", "codex_off", "Codex Off", "auto_default")
    acc_visible = AccountRef("claude", "claude_on", "Claude On", "auto_default")

    snap_zero = _make_snapshot("codex", five_h_used=100.0, weekly_used=100.0)
    snap_zero = dataclasses.replace(snap_zero, account=acc_zero,
                                    banked_resets=2)
    snap_unticked = _make_snapshot("codex", five_h_used=80.0, weekly_used=10.0)
    snap_unticked = dataclasses.replace(snap_unticked, account=acc_unticked,
                                        banked_resets=1)
    snap_visible = _make_snapshot("claude", five_h_used=50.0, weekly_used=5.0)
    snap_visible = dataclasses.replace(snap_visible, account=acc_visible,
                                       banked_resets=3)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_zero, acc_unticked,
                                             acc_visible]
        win.limit_service._state.snapshots = {
            acc_zero.key: snap_zero,
            acc_unticked.key: snap_unticked,
            acc_visible.key: snap_visible,
        }
    win.data["limit_gauges_hide_zero_usage"] = "True"
    win.data["limit_gauges_hidden_accounts"] = [acc_unticked.key]

    dialog = LimitSettingsDialog(win)
    try:
        dialog._refresh_overview_status()
        text = dialog.lbl_hidden_banked.text()
        assert dialog.lbl_hidden_banked.isVisibleTo(dialog)
        assert "Codex Zero (2 banked resets)" in text
        assert "Codex Off (1 banked reset)" in text
        assert "Claude On" not in text

        # The visible account's credits are already on screen, and its 3 are
        # counted by the activation button, not by this warning.
        assert "banked reset" in dialog.btn_activate_reset.text()

        # No hidden credits left -> the warning disappears instead of lying.
        with win.limit_service._lock:
            win.limit_service._state.snapshots[acc_zero.key] = \
                dataclasses.replace(snap_zero, banked_resets=0)
            win.limit_service._state.snapshots[acc_unticked.key] = \
                dataclasses.replace(snap_unticked, banked_resets=None)
        dialog._refresh_overview_status()
        assert not dialog.lbl_hidden_banked.isVisibleTo(dialog)
    finally:
        dialog.close()


def test_limit_gauges_shift_hover_ignores_all_filters(win, monkeypatch):
    """When Shift is held during hover on LimitGauges, all accounts are shown ignoring filters."""
    acc_hidden = AccountRef("codex", "codex_off", "Codex Off", "auto_default")
    acc_zero = AccountRef("gemini", "gemini_zero", "Gemini Zero", "auto_default")
    acc_active = AccountRef("claude", "claude_on", "Claude On", "auto_default")

    snap_hidden = _make_snapshot("codex", five_h_used=80.0, weekly_used=10.0)
    snap_zero = _make_snapshot("gemini", five_h_used=0.0, weekly_used=0.0)
    snap_active = _make_snapshot("claude", five_h_used=50.0, weekly_used=5.0)

    with win.limit_service._lock:
        win.limit_service._state.accounts = [acc_hidden, acc_zero, acc_active]
        win.limit_service._state.snapshots = {
            acc_hidden.key: snap_hidden,
            acc_zero.key: snap_zero,
            acc_active.key: snap_active,
        }
    win.data["limit_gauges_hide_zero_usage"] = "True"
    win.data["limit_gauges_hidden_accounts"] = [acc_hidden.key]

    # Without Shift: hidden and zero are filtered out of active table
    html_normal = win.limit_gauges._build_tooltip(ignore_filters=False)
    assert f">{acc_active.display_name}</b>" in html_normal
    assert f">{acc_hidden.display_name}</b>" not in html_normal
    assert f">{acc_zero.display_name}</b>" not in html_normal
    assert "Hidden:" in html_normal
    assert "(all accounts — Shift held)" not in html_normal

    # With Shift: ignore_filters=True shows ALL accounts in active table
    html_shift = win.limit_gauges._build_tooltip(ignore_filters=True)
    assert f">{acc_active.display_name}</b>" in html_shift
    assert f">{acc_hidden.display_name}</b>" in html_shift
    assert f">{acc_zero.display_name}</b>" in html_shift
    assert "Hidden:" not in html_shift
    assert "(all accounts — Shift held)" in html_shift

    # Also test via monkeypatched keyboardModifiers
    from PyQt6.QtCore import Qt
    monkeypatch.setattr(QApplication, "keyboardModifiers",
                        lambda: Qt.KeyboardModifier.ShiftModifier)
    assert win.limit_gauges._shift_held() is True
    html_auto_shift = win.limit_gauges._build_tooltip()
    assert f">{acc_hidden.display_name}</b>" in html_auto_shift
    assert f">{acc_zero.display_name}</b>" in html_auto_shift
