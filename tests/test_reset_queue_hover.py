"""Append A — the soonest-reset hover must show the complete chronological
reset queue, derived from ONE canonical candidate list.

Every fixture here is synthetic: fake providers, fabricated epochs.
"""

import os
import re
import sys
import time

import pytest
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QApplication.instance() or QApplication(sys.argv)

from _qt_retire import retire

import fastprompter.core.state as state_mod
from fastprompter.core.usage_limits.model import (
    FIVE_HOUR,
    OK,
    WEEKLY,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
    qualified_key,
    reset_candidates,
    soonest_reset,
)
from fastprompter.main import FastPrompter


def _snap(provider="claude", stable="s1", name="Claude", status=OK,
          windows=()):
    acc = AccountRef(provider, stable, name, "auto_default")
    return UsageSnapshot(acc, status, list(windows))


def _win(key=FIVE_HOUR, epoch=None, available=True, gated_by=None,
         group="", group_label=""):
    return UsageWindow(key, 300, available, 10.0, 90.0,
                       resets_at_epoch=epoch, gated_by=gated_by,
                       group=group, group_label=group_label)


BASE = time.time() + 10 * 3600


def _fresh(minutes):
    return BASE + minutes * 60


# ---------------------------------------------------------------------------
# canonical candidate list
# ---------------------------------------------------------------------------

def test_candidates_sorted_chronologically_across_providers():
    snaps = {
        "codex:s1": _snap("codex", "s1", "Codex",
                          windows=[_win(epoch=_fresh(200))]),
        "claude:s1": _snap("claude", "s1", "Claude",
                           windows=[_win(epoch=_fresh(42)),
                                    _win(WEEKLY, epoch=_fresh(3000))]),
        "antigravity:s1": _snap("antigravity", "s1", "Antigravity",
                                windows=[_win(epoch=_fresh(124))]),
    }
    cands = reset_candidates(snaps)
    epochs = [c.resets_at_epoch for c in cands]
    assert epochs == sorted(epochs)
    assert len(cands) == 4                      # EVERY window competes
    assert cands[0].provider_id == "claude"     # soonest first


def test_candidates_retain_identity_for_rendering():
    snaps = {"claude:s1": _snap("claude", "s1", "Claude",
                                windows=[_win(epoch=_fresh(10))])}
    (cand,) = reset_candidates(snaps)
    assert cand.account_key == "claude:s1"
    assert cand.provider_id == "claude"
    assert cand.account.display_name == "Claude"
    assert isinstance(cand.window, UsageWindow)


def test_gated_and_unavailable_windows_excluded():
    snaps = {
        "claude:s1": _snap("claude", "s1", windows=[
            _win(epoch=_fresh(1), gated_by=WEEKLY),   # gated: longer sibling owns the wait
            _win(FIVE_HOUR, epoch=None),              # no reset time
            _win(FIVE_HOUR, epoch=-5.0),              # invalid epoch
            _win(WEEKLY, available=False, epoch=_fresh(2)),
            _win(WEEKLY, epoch=_fresh(500)),          # the one real candidate
        ]),
    }
    cands = reset_candidates(snaps)
    assert [c.window.key for c in cands] == [WEEKLY]
    assert cands[0].resets_at_epoch == _fresh(500)


def test_hidden_account_excluded_from_queue():
    snaps = {
        "claude:s1": _snap("claude", "s1", windows=[_win(epoch=_fresh(10))]),
        "codex:s1": _snap("codex", "s1", windows=[_win(epoch=_fresh(20))]),
    }
    cands = reset_candidates(snaps, hidden_keys={"claude:s1"})
    assert [c.provider_id for c in cands] == ["codex"]


def test_hide_zero_and_hide_unusable_do_not_alter_queue():
    """The reset queue intentionally takes no display-filter arguments: the
    exhausted account is exactly the reset the user is waiting for."""
    import inspect
    sig = inspect.signature(reset_candidates)
    assert set(sig.parameters) == {"snapshots", "hidden_keys"}


def test_antigravity_grouped_windows_all_present_and_distinguishable():
    snaps = {
        "antigravity:s1": _snap("antigravity", "s1", "Antigravity", windows=[
            _win(qualified_key(FIVE_HOUR, "gemini_models"),
                 epoch=_fresh(60), group="gemini_models",
                 group_label="Gemini models"),
            _win(qualified_key(WEEKLY, "claude_gpt"),
                 epoch=_fresh(4000), group="claude_gpt",
                 group_label="Claude and GPT models"),
        ]),
    }
    cands = reset_candidates(snaps)
    assert len(cands) == 2
    assert cands[0].window.group_label == "Gemini models"
    assert cands[1].window.group_label == "Claude and GPT models"


def test_duplicate_provider_accounts_stay_distinguishable():
    snaps = {
        "claude:aaa": _snap("claude", "aaa", "Work Claude",
                            windows=[_win(epoch=_fresh(10))]),
        "claude:bbb": _snap("claude", "bbb", "Home Claude",
                            windows=[_win(epoch=_fresh(20))]),
    }
    cands = reset_candidates(snaps)
    names = {c.account.display_name for c in cands}
    assert names == {"Work Claude", "Home Claude"}


def test_soonest_reset_equals_first_candidate():
    snaps = {
        "claude:s1": _snap("claude", "s1", windows=[_win(epoch=_fresh(10))]),
        "codex:s1": _snap("codex", "s1", windows=[_win(epoch=_fresh(20))]),
    }
    provider, epoch = soonest_reset(snaps)
    cands = reset_candidates(snaps)
    assert provider == cands[0].provider_id
    assert epoch == cands[0].resets_at_epoch


def test_soonest_reset_empty_when_no_valid_candidates():
    snaps = {"claude:s1": _snap("claude", "s1", windows=[
        _win(FIVE_HOUR, epoch=None)])}
    assert soonest_reset(snaps) == (None, None)
    assert reset_candidates(snaps) == []


# ---------------------------------------------------------------------------
# hover queue (T-1279: rendered into the LimitHoverCard, not a native tooltip)
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
    w.data["limit_gauges"] = "True"
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
    # T-1286: receiver-scoped retirement; a bare deleteLater() is never
    # delivered without an event loop and the backlog stalled timer_fire.
    retire(w)


def _queue_html(win) -> str:
    """The hover-queue payload the card renders (T-1279).

    The native tooltip is now a short summary only; the queue itself lives in
    the card, so these assertions read the same HTML the card receives.
    """
    return getattr(win, "_reset_queue_html", "") or ""


def _install_snapshots(w, snaps):
    from fastprompter.core.usage_limits.service import ServiceState
    w.limit_service._state = ServiceState(
        accounts=list(snaps.values()), snapshots=dict(snaps))


def test_tooltip_lists_every_candidate_in_order(win):
    snaps = {
        "claude:s1": _snap("claude", "s1", "Claude",
                           windows=[_win(epoch=_fresh(42)),
                                    _win(WEEKLY, epoch=_fresh(4400))]),
        "codex:s1": _snap("codex", "s1", "Codex",
                          windows=[_win(epoch=_fresh(78))]),
    }
    _install_snapshots(win, snaps)
    win._update_limit_timer_label()
    lbl = win.lbl_limit_timer
    assert lbl.text().startswith("↻")
    tip = _queue_html(win)
    assert "Next resets" in tip
    import re as _re
    # Each row begins with a numeric "N." cell; count them instead of
    # splitting on <br> (the payload is a table now, not <br>-joined lines).
    body = _re.findall(r">\d+\.</td>", tip)
    assert len(body) == 3                 # ALL candidates, not just the first
    assert "Claude" in tip and "Codex" in tip and "Weekly" in tip


def test_tooltip_group_label_included_for_pools(win):
    snaps = {
        "antigravity:s1": _snap("antigravity", "s1", "Antigravity", windows=[
            _win(qualified_key(FIVE_HOUR, "gemini_models"), epoch=_fresh(60),
                 group="gemini_models", group_label="Gemini models"),
        ]),
    }
    _install_snapshots(win, snaps)
    win._update_limit_timer_label()
    assert "Gemini models" in _queue_html(win)


def test_tooltip_names_duplicate_accounts_separately(win):
    snaps = {
        "claude:aaa": _snap("claude", "aaa", "Work Claude",
                            windows=[_win(epoch=_fresh(10))]),
        "claude:bbb": _snap("claude", "bbb", "Home Claude",
                            windows=[_win(epoch=_fresh(20))]),
    }
    _install_snapshots(win, snaps)
    win._update_limit_timer_label()
    tip = _queue_html(win)
    assert "Work Claude" in tip and "Home Claude" in tip


def test_tooltip_empty_state_when_no_resets(win):
    _install_snapshots(win, {
        "claude:s1": _snap("claude", "s1", windows=[_win(FIVE_HOUR, epoch=None)])})
    win._update_limit_timer_label()
    assert "No upcoming AI limit resets" in win.lbl_limit_timer.toolTip()
    assert _queue_html(win) == ""


def test_tooltip_rows_carry_minutes(win):
    """Even multi-day waits keep a minute field, matching the ↻ label."""
    snaps = {
        "claude:s1": _snap("claude", "s1", windows=[
            _win(epoch=_fresh(3 * 1440 + 42))]),
    }
    _install_snapshots(win, snaps)
    win._update_limit_timer_label()
    tip = _queue_html(win)
    assert "3d" in tip
    assert re.search(r"\d+h \d+m", tip)   # minute field kept on multi-day waits


def test_tooltip_rows_colored_per_vendor(win):
    """Each vendor's row carries its own resolved reset colour.

    The canonical resolver is the authority: the shipped profile may carry
    per-role overrides (baked limit_colors), so the assertion reads the same
    colour the row renders with instead of pinning the provider default.
    """
    from fastprompter.core.usage_limits.model import PROVIDER_RESET_COLORS
    from fastprompter.ui.limit_colors import reset_color
    snaps = {
        "claude:s1": _snap("claude", "s1", windows=[_win(epoch=_fresh(60))]),
        "codex:s1": _snap("codex", "s1", "Codex", windows=[_win(epoch=_fresh(120))]),
    }
    _install_snapshots(win, snaps)
    win._update_limit_timer_label()
    tip = _queue_html(win)
    claude_color = reset_color(win, "claude") or PROVIDER_RESET_COLORS["claude"]
    codex_color = reset_color(win, "codex") or PROVIDER_RESET_COLORS["codex"]
    assert f"color:{claude_color}" in tip and "Claude" in tip
    assert f"color:{codex_color}" in tip and "Codex" in tip
