"""Measure the hover card's real footprint against the reported window.

The SAIHANDOFF claim is that ordinary hover "displays numerous account/window
rows at once" and "covers a large portion of the working editor" at
1033x679.  This reports the card's measured geometry and the fraction of that
window it hides, for the account counts the handoff names.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from fastprompter.core.usage_limits.model import (  # noqa: E402
    OK,
    AccountRef,
    UsageSnapshot,
    UsageWindow,
)
from fastprompter.ui.limit_gauges import LimitGauges  # noqa: E402

WINDOW_W, WINDOW_H = 1033, 679


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

    def add_callback(self, cb):
        pass

    def schedule_auto(self, *a):
        pass

    def refresh(self):
        pass


class _Win(QWidget):
    def __init__(self, **data):
        super().__init__()
        self.data = {"limit_gauges": "True", "limit_gauges_style": "bars",
                     "limit_gauges_show_labels": "True",
                     "limit_gauges_fill": "remaining", **data}
        self._theme_cache = {"raw_colors": {}}
        self.resize(WINDOW_W, WINDOW_H)


def _snap(account):
    now = time.time()
    return UsageSnapshot(account=account, status=OK, fetched_at=now, windows=[
        UsageWindow("five_hour", 300, True, 62, 38, now + 5 * 3600),
        UsageWindow("weekly", 10080, True, 88, 12, now + 4 * 86400)])


def build(count, provider="claude"):
    accounts = [
        AccountRef(provider_id=provider, stable_id=f"a{i}",
                   display_name=f"Claude Account {i}", source_kind="test")
        for i in range(count)
    ]
    snapshots = {a.key: _snap(a) for a in accounts}
    win = _Win()
    gauge = LimitGauges(win, _Service(_State(accounts, snapshots)))
    gauge._on_data()
    return win, gauge


def main():
    app = QApplication.instance() or QApplication([])
    print(f"window {WINDOW_W}x{WINDOW_H}  "
          f"(hover share of the editor area)\n")
    print(f"{'accounts':>8} {'rows':>5} {'card w':>7} {'card h':>7} "
          f"{'% of window':>12}  view")
    for count in (1, 4, 8, 12):
        win, gauge = build(count)
        card = gauge.hover_card()
        compact = gauge._build_hover_summary()
        detail = gauge._build_tooltip()
        card.set_html(compact)
        share = 100.0 * card.width() * card.height() / (WINDOW_W * WINDOW_H)
        print(f"{count:>8} {compact.count('<tr>'):>5} {card.width():>7} "
              f"{card.height():>7} {share:>11.1f}%  compact (hover)")
        card.set_html(detail)
        share = 100.0 * card.width() * card.height() / (WINDOW_W * WINDOW_H)
        print(f"{'':>8} {detail.count('<tr>'):>5} {card.width():>7} "
              f"{card.height():>7} {share:>11.1f}%  detail (on enter)")
        card.hide_now()
        win.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()
