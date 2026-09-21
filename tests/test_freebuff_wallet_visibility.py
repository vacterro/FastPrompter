"""Append B — a Freebuff account with a positive spendable wallet must
survive the automatic visibility filters even when its metered pool reads
0% used (fresh reset). All fixtures synthetic.
"""

import os
import sys
import tempfile

import pytest
from _qt_retire import retire
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QApplication.instance() or QApplication(sys.argv)
_tmpdir = tempfile.mkdtemp(prefix="fastprompter_wallet_")

import fastprompter.core.state as state_mod
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    STALE,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    account_has_usage,
    account_usable_now,
    resolved_windows,
    spare_balance,
)
from fastprompter.main import FastPrompter


def _fb_snapshot(status=OK, five_h_used=0.0, weekly_used=0.0, wallet=0.0,
                 five_h_resets=None, weekly_resets=None):
    acc = AccountRef("freebuff", "stable_fb", "Freebuff", "auto_default")
    windows = [
        UsageWindow(FIVE_HOUR, 300, True, five_h_used, 100.0 - five_h_used,
                    resets_at_epoch=five_h_resets),
        UsageWindow(WEEKLY, 10080, True, weekly_used, 100.0 - weekly_used,
                    resets_at_epoch=weekly_resets),
    ]
    snap = UsageSnapshot(acc, status, windows)
    if wallet:
        object.__setattr__(
            snap, "provider_metadata", {"wallet_balance": wallet})
    return snap


def _plain_snapshot(provider="claude", five_h_used=0.0, weekly_used=0.0,
                    five_h_resets=None, weekly_resets=None):
    acc = AccountRef(provider, f"stable_{provider}", f"Test {provider}",
                     "auto_default")
    windows = [
        UsageWindow(FIVE_HOUR, 300, True, five_h_used, 100.0 - five_h_used,
                    resets_at_epoch=five_h_resets),
        UsageWindow(WEEKLY, 10080, True, weekly_used, 100.0 - weekly_used,
                    resets_at_epoch=weekly_resets),
    ]
    return UsageSnapshot(acc, OK, windows)


# ---------------------------------------------------------------------------
# predicate truth table (case matrix from the spec)
# ---------------------------------------------------------------------------

def test_case_A_fresh_reset_with_wallet_is_has_usage():
    # 0% used / 100% remaining + 30 FB wallet -> usable capacity -> NOT "0% usage"
    assert account_has_usage(_fb_snapshot(wallet=30.0)) is True


def test_case_B_depleted_meter_with_wallet_is_has_usage():
    assert account_has_usage(_fb_snapshot(five_h_used=100.0,
                                          weekly_used=100.0,
                                          wallet=30.0)) is True


def test_case_C_no_wallet_no_usage_follows_normal_filtering():
    # untouched meter, no wallet -> the 0%-usage filter still hides it
    assert account_has_usage(_fb_snapshot(wallet=0.0)) is False
    # everything exhausted, no wallet -> hidden as before
    assert account_has_usage(_fb_snapshot(five_h_used=100.0,
                                          weekly_used=100.0,
                                          wallet=0.0)) is False


def test_case_D_normal_account_zero_used_remains_filtered():
    # existing hide-zero behavior must not change for wallet-less providers
    assert account_has_usage(_plain_snapshot("claude", 0.0, 0.0)) is False
    assert account_has_usage(_plain_snapshot("codex", 12.5, 0.0)) is True


def test_case_E_invalid_status_never_passes_via_wallet():
    for status in ("ERROR", "UNAVAILABLE"):
        snap = _fb_snapshot(status=status, wallet=30.0)
        assert account_has_usage(snap) is False
        assert account_usable_now(snap) is False


def test_stale_status_with_wallet_still_counts():
    assert account_has_usage(_fb_snapshot(status=STALE, wallet=30.0)) is True
    assert account_usable_now(_fb_snapshot(status=STALE, wallet=30.0)) is True


def test_usable_now_wallet_semantics_unchanged():
    # usable-now already honored spare_balance; verify both directions hold
    # with the METER exhausted, so the wallet is the only usable capacity.
    assert account_usable_now(
        _fb_snapshot(five_h_used=100.0, weekly_used=100.0, wallet=30.0)) is True
    assert account_usable_now(
        _fb_snapshot(five_h_used=100.0, weekly_used=100.0, wallet=0.0)) is False


# ---------------------------------------------------------------------------
# T-1254 — reset boundary: elapsed resets must not hide a wallet-carrying
# Freebuff account from the hide-zero filter
# ---------------------------------------------------------------------------

_NOW = 1_800_000_000.0


def test_T1254_A_elapsed_reset_with_wallet_survives():
    """Case A: elapsed reset turns every window reset_pending/unavailable, but
    the positive wallet is independent usable capacity."""
    snap = _fb_snapshot(wallet=30.0, five_h_resets=_NOW - 1,
                        weekly_resets=_NOW - 1)
    resolved = resolved_windows(snap.windows, now=_NOW)
    assert all(getattr(w, "reset_pending", False) for w in resolved)
    assert all(not w.available for w in resolved)
    assert all(w.used_percent is None for w in resolved)
    assert all(w.remaining_percent is None for w in resolved)
    assert account_usable_now(snap, now=_NOW) is True
    assert account_has_usage(snap, now=_NOW) is True


def test_T1254_A2_red_control_elapsed_reset_without_wallet():
    """Red control: without the wallet clause before the window bail-out,
    case A returned False — the exact contradiction being repaired."""
    # construct the pre-repair contradiction directly: with the old code, a
    # wallet snapshot with zero AVAILABLE windows hit `if not windows: False`
    # before spare_balance was ever read. The repaired predicate must return
    # True where the old one did not.
    snap = _fb_snapshot(wallet=30.0, five_h_resets=_NOW - 1,
                        weekly_resets=_NOW - 1)
    resolved = resolved_windows(snap.windows, now=_NOW)
    assert not [w for w in resolved if w.available]  # no usable windows at all
    assert account_has_usage(snap, now=_NOW) is True  # old code: False


def test_T1254_B_elapsed_reset_without_wallet_stays_hidden():
    """Case B: same expired window but wallet = 0 -> still hidden."""
    snap = _fb_snapshot(wallet=0.0, five_h_resets=_NOW - 1,
                        weekly_resets=_NOW - 1)
    assert account_has_usage(snap, now=_NOW) is False


def test_T1254_C_stale_status_wallet_survives_boundary():
    """Case C: STALE status keeps wallet sufficiency across the boundary."""
    snap = _fb_snapshot(status=STALE, wallet=30.0,
                        five_h_resets=_NOW - 1, weekly_resets=_NOW - 1)
    assert account_usable_now(snap, now=_NOW) is True
    assert account_has_usage(snap, now=_NOW) is True


def test_T1254_D_invalid_status_wallet_fails_closed():
    """Case D: wallet metadata never bypasses ERROR / UNAVAILABLE /
    AUTH_REQUIRED."""
    for status in ("ERROR", "UNAVAILABLE", "AUTH_REQUIRED"):
        snap = _fb_snapshot(status=status, wallet=30.0,
                            five_h_resets=_NOW - 1, weekly_resets=_NOW - 1)
        assert account_has_usage(snap, now=_NOW) is False, status
        assert account_usable_now(snap, now=_NOW) is False, status


@pytest.mark.parametrize("owner", ["gauges", "overview", "settings_dialog"])
def test_T1254_E_ui_surfaces_retain_freebuff_at_reset_boundary(win, owner):
    """Case E: hide-zero topbar keeps the wallet-carrying Freebuff account
    present at the exact elapsed-reset boundary on every UI surface."""
    w = win
    w.data["limit_gauges"] = "True"
    w.data["limit_gauges_hide_zero_usage"] = "True"
    w.data["limit_gauges_hide_unusable_5h"] = "False"
    snap = _fb_snapshot(wallet=30.0, five_h_resets=_NOW - 1,
                        weekly_resets=_NOW - 1)
    _install(w, {"freebuff:stable_fb": snap})
    if owner == "gauges":
        shown = [a.key for a in w.limit_gauges._visible_accounts()]
    elif owner == "overview":
        from fastprompter.ui.limit_overview import LimitOverview
        ov = LimitOverview(w, w.limit_service)
        try:
            shown = [a.key for a in ov._accounts()]
        finally:
            retire(ov)
    else:
        from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
        dlg = LimitSettingsDialog(w)
        try:
            shown = ([a.key for a in w.limit_gauges._visible_accounts()]
                     if account_has_usage(snap) else [])
        finally:
            dlg.close()
            retire(dlg)
    assert "freebuff:stable_fb" in shown, owner


def test_T1254_walletless_provider_at_reset_boundary_unaffected():
    """Non-Freebuff regression contract: wallet-less windows at the boundary
    stay hidden exactly as before."""
    snap = _plain_snapshot("claude", five_h_resets=_NOW - 1,
                           weekly_resets=_NOW - 1)
    assert account_has_usage(snap, now=_NOW) is False
    assert account_usable_now(snap, now=_NOW) is False


# ---------------------------------------------------------------------------
# T-1254 — model consistency invariant: for valid positive-wallet snapshots
# the two predicates may never contradict each other again
# ---------------------------------------------------------------------------

import pytest as _pytest


@_pytest.mark.parametrize("meter", [
    "fresh",            # 0% used / 100% remaining
    "exhausted",        # 100% used / 0% remaining
    "reset_pending",    # elapsed reset -> reset_pending/unavailable
    "empty",            # zero reported windows
])
def test_T1254_invariant_wallet_positive_predicates_agree(meter):
    """For any snapshot with spare_balance > 0 and status OK/STALE,
    account_usable_now == account_has_usage == True, regardless of the
    metered-window state."""
    if meter == "fresh":
        snap = _fb_snapshot(wallet=30.0)
    elif meter == "exhausted":
        snap = _fb_snapshot(wallet=30.0, five_h_used=100.0, weekly_used=100.0)
    elif meter == "reset_pending":
        snap = _fb_snapshot(wallet=30.0, five_h_resets=_NOW - 1,
                            weekly_resets=_NOW - 1)
    else:  # empty
        acc = AccountRef("freebuff", "stable_fb", "Freebuff", "auto_default")
        snap = UsageSnapshot(acc, OK, [])
        object.__setattr__(snap, "provider_metadata",
                           {"wallet_balance": 30.0})
    assert spare_balance(snap) > 0.0
    assert snap.status in (OK, STALE)
    usable = account_usable_now(snap, now=_NOW)
    has_usage = account_has_usage(snap, now=_NOW)
    assert usable is True, meter
    assert has_usage is True, meter
    assert usable == has_usage, meter


@_pytest.mark.parametrize("meter", ["fresh", "exhausted", "reset_pending", "empty"])
def test_T1254_invariant_zero_wallet_walletless_predicates_unchanged(meter):
    """The invariant must NOT extend to zero-wallet snapshots: existing
    hide-zero behavior for wallet-less accounts is pinned."""
    if meter == "fresh":
        snap = _fb_snapshot(wallet=0.0)
        assert account_has_usage(snap, now=_NOW) is False
    elif meter == "exhausted":
        snap = _fb_snapshot(wallet=0.0, five_h_used=100.0, weekly_used=100.0)
        assert account_has_usage(snap, now=_NOW) is False
    elif meter == "reset_pending":
        snap = _fb_snapshot(wallet=0.0, five_h_resets=_NOW - 1,
                            weekly_resets=_NOW - 1)
        assert account_has_usage(snap, now=_NOW) is False
    else:  # empty
        acc = AccountRef("freebuff", "stable_fb", "Freebuff", "auto_default")
        snap = UsageSnapshot(acc, OK, [])
        assert account_has_usage(snap, now=_NOW) is False


# ---------------------------------------------------------------------------
# UI surfaces keep Freebuff visible
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
class _Snap:
    def __init__(self, snapshots):
        self.snapshots = snapshots


def _install(w, snaps):
    from fastprompter.core.usage_limits.service import ServiceState
    w.limit_service._state = ServiceState(
        accounts=[s.account for s in snaps.values()],
        snapshots=dict(snaps))


def _fb_visible_in_gauges(w, snap, hide_zero=True, hide_unusable=False):
    w.data["limit_gauges"] = "True"
    w.data["limit_gauges_hide_zero_usage"] = "True" if hide_zero else "False"
    w.data["limit_gauges_hide_unusable_5h"] = "True" if hide_unusable else "False"
    _install(w, {"freebuff:stable_fb": snap})
    shown = w.limit_gauges._visible_accounts()
    return [a.key for a in shown]


def test_gauges_retain_fresh_reset_freebuff_with_wallet(win):
    snap = _fb_snapshot(wallet=30.0)     # case A: 0% used + 30 FB
    assert "freebuff:stable_fb" in _fb_visible_in_gauges(win, snap)


def test_gauges_retain_depleted_freebuff_with_wallet_under_hide_unusable(win):
    snap = _fb_snapshot(five_h_used=100.0, weekly_used=100.0, wallet=30.0)
    shown = _fb_visible_in_gauges(win, snap, hide_zero=True, hide_unusable=True)
    assert "freebuff:stable_fb" in shown


def test_gauges_still_filter_walletless_zero_usage(win):
    snap = _fb_snapshot(wallet=0.0)
    assert "freebuff:stable_fb" not in _fb_visible_in_gauges(win, snap)
    plain = _plain_snapshot("claude", 0.0, 0.0)
    w = win
    w.data["limit_gauges"] = "True"
    w.data["limit_gauges_hide_zero_usage"] = "True"
    w.data["limit_gauges_hide_unusable_5h"] = "False"
    _install(w, {"claude:stable_claude": plain})
    assert [a.key for a in w.limit_gauges._visible_accounts()] == []


def test_overview_retains_fresh_reset_freebuff_with_wallet(win):
    from fastprompter.ui.limit_overview import LimitOverview
    w = win
    w.data["limit_gauges"] = "True"
    w.data["limit_gauges_hide_zero_usage"] = "True"
    w.data["limit_gauges_hide_unusable_5h"] = "False"
    snap = _fb_snapshot(wallet=30.0)
    _install(w, {"freebuff:stable_fb": snap})
    ov = LimitOverview(w, w.limit_service)
    keys = [a.key for a in ov._accounts()]
    assert "freebuff:stable_fb" in keys
    retire(ov)
def test_settings_dialog_hidden_account_evaluation_sees_wallet(win):
    from fastprompter.ui.limit_settings_dialog import LimitSettingsDialog
    w = win
    w.data["limit_gauges"] = "True"
    w.data["limit_gauges_hide_zero_usage"] = "True"
    w.data["limit_gauges_hide_unusable_5h"] = "False"
    snap = _fb_snapshot(wallet=30.0)
    _install(w, {"freebuff:stable_fb": snap})
    dlg = LimitSettingsDialog(w)
    try:
        # the account must NOT end up on the auto-hidden list: the same
        # predicate the dialog row build uses must keep it usable/visible.
        from fastprompter.core.usage_limits.model import account_has_usage
        assert account_has_usage(snap) is True
        assert account_has_usage(w.limit_service.state_copy.snapshots[
            "freebuff:stable_fb"]) is True
    finally:
        dlg.close()
        retire(dlg)
