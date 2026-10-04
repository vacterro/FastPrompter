"""T-239: the shared-identity badge must actually reach the screen.

``test_usage_limits_identity_t239.py`` proves the SERVICE is right: two slots on
one Google login report one unique identity and name the canonical peer. That is
the half with no user in it. The other half is the row an operator actually
reads, and it had no test at all -- so the annotation could be deleted, or its
text misspelled, and the suite stayed green while the fix stopped being visible.

The label is also the one place dedup touches pixels, so it carries two risks
worth pinning: it must be plain text (the peer name comes from a registry on
another machine, and Qt reads ``<`` as markup) and it must name the peer, not
merely assert that one exists.
"""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from fastprompter.core.usage_limits import sai_accounts as sai
from fastprompter.ui.limit_account_selector import LimitAccountSelector


def _account(*, sid="aaa", name="Antigravity 1", compact="AG1"):
    """One Antigravity account as the registry projects it.

    ``key`` is a derived property (provider + stable_id), so the two slots are
    made distinct by their SID -- exactly how the real plane distinguishes them.
    """
    return sai._account_ref(sai.SharedAccount(
        account_id="antigravity:windows-user:" + sid,
        provider_id="antigravity", display_name=name, compact_label=compact,
        backend="windows_user", locator=sid, operational_state="ENABLED",
        hidden=False))


def _selector(accounts, shared):
    """The real widget over a stub service reporting `shared`."""
    class _Win(QWidget):
        def __init__(self):
            super().__init__()
            self.data = {}

    service = SimpleNamespace(
        state_copy=SimpleNamespace(accounts=list(accounts)),
        identity_report=lambda: {"shared_with": dict(shared)},
    )
    return LimitAccountSelector(_Win(), service)


def _badges(selector):
    """Only the SHARING annotations -- never the plain display-name rows.

    Filtering on the account's own name is the trap: an unshared row always
    renders "Antigravity 1", so a test that merely looks for that string passes
    with the badge deleted and proves nothing.
    """
    return [w.text() for w in selector.findChildren(QLabel)
            if "Same provider account" in w.text()]


def test_the_shared_row_names_the_peer_it_shares_quota_with(qapp):
    a = _account(sid="aaa", name="Antigravity 1", compact="AG1")
    b = _account(sid="bbb", name="Antigravity 2", compact="AG2")
    selector = _selector([a, b], {b.key: a.key})
    try:
        badges = _badges(selector)
        assert len(badges) == 1, f"expected exactly one sharing badge: {badges!r}"
        assert "Antigravity 1" in badges[0], (
            f"the shared row never named its peer: {badges!r}")
        assert "Antigravity 2" in badges[0], (
            f"the badge did not say which row it was: {badges!r}")
    finally:
        selector.deleteLater()


def test_an_unshared_row_makes_no_peer_claim(qapp):
    # The annotation must not fire by default. A badge on every row teaches the
    # operator to ignore it, which is worse than no badge at all.
    a = _account(sid="aaa", name="Antigravity 1", compact="AG1")
    b = _account(sid="bbb", name="Antigravity 2", compact="AG2")
    selector = _selector([a, b], {})
    try:
        assert _badges(selector) == [], (
            f"unshared rows claimed a peer: {_badges(selector)!r}")
    finally:
        selector.deleteLater()


def test_the_shared_label_is_plain_text_not_markup(qapp):
    # The peer name is a registry string from another machine; a leading "<"
    # under AutoText renders as markup and swallows the row.
    a = _account(sid="aaa", name="R&D <alice>", compact="AG1")
    b = _account(sid="bbb", name="Antigravity 2", compact="AG2")
    selector = _selector([a, b], {b.key: a.key})
    try:
        labels = [w for w in selector.findChildren(QLabel)
                  if "Same provider account" in w.text()]
        assert labels, f"the sharing badge never rendered: {_badges(selector)!r}"
        assert "R&D <alice>" in labels[0].text(), (
            f"the badge lost the peer name it must render: {labels[0].text()!r}")
        assert labels[0].textFormat() == Qt.TextFormat.PlainText
    finally:
        selector.deleteLater()


def test_a_service_without_the_accessor_never_claims_a_peer(qapp):
    # The UI degrades to "no label to draw", never to "these are shared" -- the
    # fail-safe direction. An unlabelled row understates capacity; a wrong label
    # overstates redundancy, which is the bug this ticket exists to prevent.
    a = _account(sid="aaa", name="Antigravity 1", compact="AG1")
    b = _account(sid="bbb", name="Antigravity 2", compact="AG2")

    class _Win(QWidget):
        def __init__(self):
            super().__init__()
            self.data = {}

    selector = LimitAccountSelector(
        _Win(), SimpleNamespace(state_copy=SimpleNamespace(accounts=[a, b])))
    try:
        assert _badges(selector) == [], (
            f"a service with no identity report still drew a sharing claim: {_badges(selector)!r}")
    finally:
        selector.deleteLater()
