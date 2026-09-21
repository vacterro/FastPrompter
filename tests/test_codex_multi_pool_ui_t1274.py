"""T-1274 UI surface: two proven pools render independently and a reserve that
outlives ordinary capacity is stated as a recommendation.

The data-level contract is proven in ``test_codex_multi_pool_t1274.py``; this
file proves the WIDGET consumes it — a pool heading is drawn per pool, and the
"usable only" filter keeps an account alive on its reserve.
"""

from __future__ import annotations

import os
import time

import pytest

# Before ANY PyQt6 import: a module that lets Qt bind the native Windows
# platform plugin first makes the next real QApplication abort (0xC0000409).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastprompter.core.usage_limits.model import (  # noqa: E402
    FIVE_HOUR,
    OK,
    WEEKLY,
    UsageSnapshot,
    UsageWindow,
    qualified_key,
)
from fastprompter.core.usage_limits.model import AccountRef as AR  # noqa: E402

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from fastprompter.ui.limit_overview import LimitOverview  # noqa: E402

LUNA_POOL = "base_model_inference"
LUNA_SLUG = "gpt-5.6-luna"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _State:
    def __init__(self, accounts, snapshots):
        self.accounts = list(accounts)
        self.snapshots = dict(snapshots)
        self.status = "IDLE"


class _Service:
    def __init__(self, state):
        self._state = state

    @property
    def state_copy(self):
        return self._state


class _Win(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = {"limit_gauges": "True", **data}


def _account(sid="codex-a"):
    return AR(provider_id="codex", stable_id=sid, display_name="Codex 1",
              source_kind="test")


def _snapshot(account, codex_weekly, luna_weekly, slug=LUNA_SLUG):
    now = time.time()
    return UsageSnapshot(account=account, status=OK, fetched_at=now, windows=[
        UsageWindow(qualified_key(WEEKLY, "codex"), 10080, True,
                    100.0 - codex_weekly, codex_weekly, now + 86400,
                    group="codex", group_label="Codex"),
        UsageWindow(qualified_key(WEEKLY, LUNA_POOL), 10080, True,
                    100.0 - luna_weekly, luna_weekly, now + 172800,
                    group=LUNA_POOL, group_label="GPT Reserve",
                    model_slug=slug),
        UsageWindow(qualified_key(FIVE_HOUR, "codex"), 300, True,
                    100.0 - codex_weekly, codex_weekly, now + 3600,
                    group="codex", group_label="Codex"),
    ])


def _build(qapp, snapshot, **data):
    account = snapshot.account
    return LimitOverview(_Win(**data),
                         _Service(_State([account], {account.key: snapshot})))


def test_both_pool_headings_are_drawn(qapp):
    """Every pool heading is drawn exactly ONCE.

    Two pools with same-duration windows used to interleave after the sort,
    so the heading for the first pool was emitted again below the second —
    the "one limit reported twice" illusion the pool heading exists to kill.
    """
    snap = _snapshot(_account(), codex_weekly=50, luna_weekly=80)
    view = _build(qapp, snap)
    try:
        pools = [p for kind, p, _ in view._rows if kind == "pool"]
        assert pools == ["Codex", "GPT Reserve"]
    finally:
        view.deleteLater()


def test_reserve_is_recommended_when_ordinary_capacity_is_spent(qapp):
    snap = _snapshot(_account(), codex_weekly=0, luna_weekly=100)
    view = _build(qapp, snap)
    try:
        advice = [p for kind, p, _ in view._rows if kind == "advice"]
        assert advice == ["Luna available via reserve"]
    finally:
        view.deleteLater()


def test_no_recommendation_while_ordinary_capacity_remains(qapp):
    snap = _snapshot(_account(), codex_weekly=40, luna_weekly=100)
    view = _build(qapp, snap)
    try:
        assert [p for kind, p, _ in view._rows if kind == "advice"] == []
    finally:
        view.deleteLater()


def test_luna_account_stays_visible_under_usable_only(qapp):
    """Ordinary quota 0, reserve > 0: still useful for Luna, so not hidden."""
    snap = _snapshot(_account(), codex_weekly=0, luna_weekly=100)
    view = _build(qapp, snap, limit_gauges_hide_unusable_5h="True")
    try:
        shown = [a for a in view._accounts()]
        assert [a.key for a in shown] == [snap.account.key]
    finally:
        view.deleteLater()


def test_unknown_reserve_is_not_recommended(qapp):
    snap = _snapshot(_account(), codex_weekly=0, luna_weekly=100, slug="")
    view = _build(qapp, snap)
    try:
        assert [p for kind, p, _ in view._rows if kind == "advice"] == []
    finally:
        view.deleteLater()
