"""T-1402 / SRC-077: two Antigravity meters on ONE machine, at the consumer edge.

The control plane owns the accounts; this application only draws and reads
them. That split is the whole risk: every invariant SRC-077 asks for can hold
in the registry and still be broken by this consumer, and the failures are
quiet. A badge that disagrees with the registry, a probe that quietly falls
back to the current user's credential store, or an auth failure on one account
that blanks its sibling all render as a plausible-looking panel.

So these cases drive the PRODUCTION path end to end — ``augment`` discovery,
``probe_shared`` per account, the shared visibility policy and the badge rule —
over a plane whose two Antigravity accounts are genuinely different Windows
users. Nothing here re-implements the rule it pins.
"""

from __future__ import annotations

import json
import time

import pytest

from fastprompter.core.usage_limits import sai_accounts as sai
from fastprompter.core.usage_limits.model import AccountRef
from fastprompter.ui.limit_account_selector import (
    default_account_label,
    ordered_accounts,
    short_account_label,
    visible_quota_accounts,
)

ENGINE = r"C:\fake\sai-accounts.exe"

A_ID = "antigravity:windows-user:aaaa"
B_ID = "antigravity:windows-user:bbbb"


def _entry(account_id: str, label: str, badge: str, user: str) -> dict:
    """One Antigravity account as the plane lists it."""
    return {
        "account_id": account_id, "provider_id": "antigravity",
        "display_name": label, "compact_label": badge,
        "execution_backend": "managed_windows_user",
        "execution_context_id": account_id,
        "operational_state": "ENABLED", "hidden": False,
        "context_label": user,
        "provider_metadata": {"windows_user": user, "managed": True},
        "windows_sid": "S-1-5-21-0-0-0-" + ("1008" if user == "b" else "1019"),
    }


class Plane:
    """A control plane whose per-account answer is whatever the test says."""

    def __init__(self, listing: list[dict], usage: dict[str, dict] | None = None):
        self.engine = ENGINE
        self.listing = listing
        self.usage = usage or {}
        self.calls: list[str] = []

    def run(self, argv: list[str], deadline: float) -> dict:
        self.calls.append(" ".join(argv))
        if argv and argv[0] == "list":
            return {"ok": True, "stdout": json.dumps(
                {"schema": "sai.accounts/list/1", "accounts": self.listing,
                 "status": "ok"}), "error": ""}
        account_id = argv[1] if len(argv) > 1 else ""
        payload = self.usage.get(account_id, {})
        return {"ok": bool(payload), "stdout": json.dumps(payload), "error": ""}


@pytest.fixture
def two_antigravity(monkeypatch: pytest.MonkeyPatch):
    """Two accounts for two different Windows users, wired into the module."""
    plane = Plane([_entry(A_ID, "Antigravity 1", "AG1", "a"),
                   _entry(B_ID, "Antigravity 2", "AG2", "b")])
    monkeypatch.setattr(sai, "TestEngine", lambda: plane.engine)
    monkeypatch.setattr(sai, "TestRun", plane.run)
    monkeypatch.setenv("USERNAME", "vac34")
    return plane


def _discovered() -> list[AccountRef]:
    return sai.augment([], ("antigravity",), deadline=time.monotonic() + 5)


def _usage_windows(remaining: float) -> dict:
    return {"windows": [{"pool_index": 0, "window": "weekly",
                         "pool_name": "Gemini Models",
                         "group_label": "Gemini Models",
                         "remaining_fraction": remaining, "disabled": False}],
            "auth_state": "AUTHENTICATED", "context_state": "ONLINE"}


# ── both accounts exist and both carry the registry's own badge ─────────────

def test_two_antigravity_accounts_are_discovered_and_drawn(two_antigravity):
    accounts = _discovered()
    assert [a.source_kind for a in accounts] == ["shared", "shared"]
    assert [a.display_name for a in accounts] == ["Antigravity 1", "Antigravity 2"]
    # Both are visible through the ONE shared policy the gauges and the
    # overview use, so "the panel shows two meters" is not a per-view claim.
    shown = visible_quota_accounts({}, _Service(accounts, {}), hide_unusable=False)
    assert [a.key for a in shown] == [a.key for a in accounts]


def test_the_badge_is_the_registrys_for_every_slot(two_antigravity):
    """The first slot is the trap: a name-derived fallback used to answer "AG"."""
    accounts = _discovered()
    assert [default_account_label(a) for a in accounts] == ["AG1", "AG2"]


def test_a_locally_discovered_first_slot_still_reads_AG1(two_antigravity):
    """The account this application finds itself must not draw differently.

    A local Antigravity account (no registry badge in its metadata) proved to
    be the plane's first account is the case that produced a bare "AG" beside
    a sibling's "AG2".
    """
    local = AccountRef(provider_id="antigravity", stable_id="local1",
                       display_name="Antigravity 1", source_kind="configured",
                       source_path=r"C:\Users\vac34\.gemini\antigravity",
                       enabled=True, metadata={"identity_locator": "vac34"})
    assert default_account_label(local) == "AG1"
    assert default_account_label(local) == default_account_label(
        _discovered()[0])


def test_a_user_alias_overrides_the_registry_badge(two_antigravity):
    """SRC-077 item 4: the operator's own alias wins over the default badge."""
    accounts = _discovered()
    first, second = accounts
    data = {"limit_gauges_account_labels": {first.key: "WORK"}}
    assert short_account_label(first, data) == "WORK"
    assert short_account_label(second, data) == "AG2"


def test_the_draw_order_survives_both_accounts(two_antigravity):
    """SRC-077 item 7: reordering one Antigravity slot keeps the other's slot."""
    accounts = _discovered()
    reverse = [accounts[1].key, accounts[0].key]
    assert [a.key for a in ordered_accounts(accounts, {
        "limit_gauges_account_order": reverse})] == reverse


# ── each account is read through its OWN context ───────────────────────────

def test_each_account_is_probed_with_its_own_canonical_id(two_antigravity):
    two_antigravity.usage = {A_ID: _usage_windows(0.5),
                             B_ID: _usage_windows(0.9)}
    snaps = [sai.probe_shared(a, time.monotonic() + 5) for a in _discovered()]
    assert [s.status for s in snaps] == ["OK", "OK"]
    assert [[round(w.remaining_percent) for w in s.windows] for s in snaps] == \
        [[50], [90]], "one account's numbers landed under the other's name"
    usage_calls = [c for c in two_antigravity.calls if c.startswith("usage")]
    assert usage_calls == [f"usage {A_ID}", f"usage {B_ID}"]


def test_one_account_auth_required_does_not_touch_its_sibling(two_antigravity):
    """Independent AUTH_REQUIRED: the failing account keeps its own verdict."""
    two_antigravity.usage = {
        A_ID: {"auth_state": "AUTH_REQUIRED", "context_state": "ONLINE",
               "windows": []},
        B_ID: _usage_windows(0.9)}
    accounts = _discovered()
    a, b = (sai.probe_shared(x, time.monotonic() + 5) for x in accounts)
    assert a.status == "AUTH_REQUIRED" and a.error_code == "auth_required"
    assert b.status == "OK" and b.windows
    # And the failed account is still drawn, so the failure stays discoverable.
    shown = visible_quota_accounts(
        {}, _Service(accounts, {accounts[0].key: a, accounts[1].key: b}),
        hide_unusable=True)
    assert [x.key for x in shown] == [accounts[0].key, accounts[1].key]


def test_one_account_offline_does_not_make_its_sibling_stale(two_antigravity):
    """Independent STALE: an offline context is one account's answer."""
    two_antigravity.usage = {
        A_ID: {"context_state": "OFFLINE", "auth_state": "AUTHENTICATED",
               "windows": []},
        B_ID: _usage_windows(0.4)}
    a, b = (sai.probe_shared(x, time.monotonic() + 5) for x in _discovered())
    assert a.status == "UNAVAILABLE" and a.error_code == "shared_source_stale"
    assert b.status == "OK", "the sibling was dragged down with it"


def test_an_account_owned_by_another_user_never_falls_back_to_this_one(
        two_antigravity, monkeypatch: pytest.MonkeyPatch):
    """SRC-077's last FastPrompter test: no global-credential fallback.

    When the plane says it cannot read a provider, the local reader is only
    allowed to answer for an account THIS user owns. Answering for the other
    user's account would file the operator's own Antigravity session under
    somebody else's name.
    """
    two_antigravity.usage = {
        A_ID: {"skipped_reason": "provider_does_not_support_quota",
               "context_state": "ONLINE", "auth_state": "UNKNOWN"},
        B_ID: _usage_windows(0.4)}
    accounts = _discovered()
    called: list[str] = []

    def local_probe(account, deadline):
        called.append(account.key)
        raise AssertionError("the local reader must not be reached at all")

    snap = sai.probe_shared(accounts[0], time.monotonic() + 5,
                            local_probe=local_probe)
    assert called == [], "the current user's credential store was consulted"
    assert snap.error_code == "shared_context_unsafe"


def test_the_two_reads_may_run_at_the_same_time(two_antigravity):
    """Parallel capability is a property of the ROUTE, not a UI claim.

    Each account is an independent process invocation keyed by its own
    canonical id, so nothing serializes them through one credential context.
    """
    import concurrent.futures

    two_antigravity.usage = {A_ID: _usage_windows(0.1),
                             B_ID: _usage_windows(0.7)}
    accounts = _discovered()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        snaps = list(pool.map(
            lambda a: sai.probe_shared(a, time.monotonic() + 10), accounts))
    assert [s.status for s in snaps] == ["OK", "OK"]
    assert sorted(round(w.remaining_percent) for s in snaps for w in s.windows) \
        == [10, 70]


class _Service:
    """The minimum of ``UsageLimitService`` the visibility policy reads."""

    def __init__(self, accounts, snapshots):
        from types import SimpleNamespace
        self.state_copy = SimpleNamespace(accounts=list(accounts),
                                          snapshots=dict(snapshots))
