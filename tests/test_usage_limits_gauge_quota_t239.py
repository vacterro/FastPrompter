"""T-239: the quota hover card must not overstate capacity.

The gauge's cluster marks stay one-per-slot on purpose -- merging them would
mean rewriting the width reservation that has already broken quota display once
(``_clusters_width``). But that leaves the accounting lie standing on the
surface where an operator actually reads quota: two rows of bars for one Google
account, with nothing saying they are the same pool. This pins the wording that
qualifies the reading, and the direction it fails in.

Same shape as ``test_usage_limits_shared_badge_t239.py`` for the settings tab:
the service proves the sharing, this proves the user is told.
"""

from __future__ import annotations

from tests.test_usage_limits_gauge_layout import (
    LimitGauges,
    _account,
    _Service,
    _State,
    _Win,
)


def _card(accounts, shared, *, with_accessor=True):
    """The real hover card over a stub service reporting `shared`."""
    win = _Win()
    win.data["limit_accounts"] = [a.key for a in accounts]
    service = _Service(_State(accounts, {}))
    if with_accessor:
        service.identity_report = lambda: {"shared_with": dict(shared)}
    gauge = LimitGauges(win, service)
    return gauge._build_tooltip(ignore_filters=True)


def test_a_shared_row_names_the_peer_it_shares_quota_with(qapp):
    a = _account("antigravity", "aaa")
    b = _account("antigravity", "bbb")
    html = _card([a, b], {b.key: a.key})
    assert "Same provider account as" in html, (
        "the quota card never told the operator the rows share one pool")


def test_an_unshared_row_claims_nothing(qapp):
    a = _account("antigravity", "aaa")
    b = _account("antigravity", "bbb")
    html = _card([a, b], {})
    assert "Same provider account as" not in html, (
        "unshared rows were told they share a quota pool")


def test_a_service_without_the_accessor_claims_nothing(qapp):
    # Fail-safe direction: no identity report means no sharing claim.
    # Understating capacity is recoverable; a wrong claim teaches the operator
    # to trust a lie about their own capacity.
    a = _account("antigravity", "aaa")
    b = _account("antigravity", "bbb")
    html = _card([a, b], {}, with_accessor=False)
    assert "Same provider account as" not in html, (
        "a service with no identity report still drew a sharing claim")
