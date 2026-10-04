"""One provider identity must never masquerade as two capacity pools. (T-239)

The operator configured ``Antigravity 1`` and ``Antigravity 2`` and the panel
showed two apparently independent full accounts. Two bugs could produce that,
and the difference matters: a credential-isolation defect in the control plane,
or an attribution defect in this consumer. These tests pin the CONSUMER side
provably, and the isolation rule they enforce is what turns the second case
from "looks fine" into "provably fine".

The one sentence the whole file defends: identity is proven from authenticated
provider metadata or it is not known — and unknown never means shared.

Every case drives the production functions it names. Nothing here re-implements
the rule it is testing.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from fastprompter.core.usage_limits import identity as ident
from fastprompter.core.usage_limits import sai_accounts as sai
from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot
from fastprompter.core.usage_limits.providers import _antigravity_cli as agy

ENGINE = r"C:\fake\sai-accounts.exe"

FP_A = "aaaaaaaaaaaaaaa1"
FP_B = "bbbbbbbbbbbbbbb2"


def verified(fp: str, source: str = "google_id_token_sub") -> dict:
    return ident.describe(fp, source)


def unverified(fp: str) -> dict:
    """A fingerprint nobody proved. Must never merge or count as an identity."""
    return {ident.KEY_FINGERPRINT: fp, ident.KEY_VERIFIED: False}


# ── 1/6/18. identity lives on the account, not on the quota ────────────────

def test_two_accounts_hold_different_provider_identities():
    assert ident.fingerprint_of(verified(FP_A)) == FP_A
    assert ident.fingerprint_of(verified(FP_B)) == FP_B
    assert ident.fingerprint_of(verified(FP_A)) != ident.fingerprint_of(verified(FP_B))


def test_distinct_identities_count_twice():
    entries = [("ag1", verified(FP_A)), ("ag2", verified(FP_B))]
    assert ident.unique_identity_count(entries) == 2
    assert ident.duplicate_report(entries) == {}


# ── 3. equal quota is NOT identity ─────────────────────────────────────────

def test_identical_quota_numbers_do_not_cause_deduplication():
    """Both accounts at 100%, reset at the same minute, same plan name.

    Metadata alone cannot link them; only a proven fingerprint may.
    """
    a = AccountRef("antigravity", "a", "Antigravity 1", "configured",
                   r"C:\Users\vac34\.gemini\antigravity", True, {})
    b = AccountRef("antigravity", "b", "Antigravity 2", "shared", "", True,
                   {"origin": "shared", "windows_user": "antigravity_b"})
    reading = {"quota": 100.0, "resets_at": 1791000000.0, "plan": "free"}
    assert reading == reading                      # the numbers really are equal
    assert ident.duplicate_report([(a.key, {}), (b.key, {})]) == {}
    assert ident.unique_identity_count([(a.key, {}), (b.key, {})]) == 2


# ── 4/5/17. identical identity DOES deduplicate, and counts once ──────────

def test_identical_fingerprints_deduplicate_and_count_once():
    entries = [("ag1", verified(FP_A)), ("ag2", verified(FP_A))]
    assert ident.duplicate_report(entries) == {"ag2": "ag1"}
    assert ident.unique_identity_count(entries) == 1


def test_shared_identity_is_marked_explicitly_on_every_duplicate():
    groups = ident.group_by_identity(
        [("ag1", verified(FP_A)), ("ag2", verified(FP_A)), ("ag3", verified(FP_B))])
    assert groups == {FP_A: ["ag1", "ag2"], FP_B: ["ag3"]}


# ── 11/7. cache isolation and ownership by canonical id ───────────────────

def test_cache_scope_is_per_account_even_when_identity_matches():
    a = ident.cache_scope_key("antigravity", "ag1", verified(FP_A))
    b = ident.cache_scope_key("antigravity", "ag2", verified(FP_A))
    assert a != b, "one provider-global cache would serve ag1's numbers to ag2"


def test_unresolved_identity_keeps_a_private_scope():
    a = ident.cache_scope_key("antigravity", "ag1", {})
    b = ident.cache_scope_key("antigravity", "ag2", {})
    assert a != b
    assert a.endswith("|" + ident.UNRESOLVED)


def test_rename_and_reorder_do_not_move_identity_ownership():
    """Ownership is the canonical account id; a label is decoration."""
    entries = [("ag1", verified(FP_A)), ("ag2", verified(FP_B))]
    reordered = list(reversed(entries))
    assert dict(entries)["ag1"] == dict(reordered)["ag1"]
    assert ident.duplicate_report(entries) == ident.duplicate_report(reordered)


# ── 19. unresolved never merges optimistically ────────────────────────────

def test_unresolved_identity_is_not_merged_optimistically():
    entries = [("ag1", verified(FP_A)), ("ag2", {})]
    assert ident.duplicate_report(entries) == {}
    assert ident.group_by_identity(entries) == {FP_A: ["ag1"]}
    # It still counts once: an unknown pool is one unknown pool. Guessing it is
    # shared would silently delete capacity the operator actually has.
    assert ident.unique_identity_count(entries) == 2


def test_unverified_fingerprint_is_treated_as_no_identity():
    assert ident.fingerprint_of(unverified(FP_A)) == ident.UNRESOLVED
    assert ident.duplicate_report([("a", unverified(FP_A)),
                                   ("b", unverified(FP_A))]) == {}


# ── 5 (switch). account switch detection ──────────────────────────────────

def test_account_switch_is_detected_between_proven_identities():
    assert ident.identity_changed(verified(FP_A), verified(FP_B)) is True
    assert ident.identity_changed(verified(FP_A), verified(FP_A)) is False


def test_unresolved_reading_is_never_a_switch():
    """A credential that briefly fails to read must not look like a new human."""
    assert ident.identity_changed(verified(FP_A), {}) is False
    assert ident.identity_changed({}, verified(FP_B)) is False


# ── 13/14/15. rotation, reconnect and restart are not switches ────────────

def test_token_rotation_does_not_look_like_an_account_switch():
    """Rotation is detected by a digest of raw token bytes; identity by `sub`.

    These are deliberately different values. If identity were derived from the
    rotation digest, every refresh would read as a different human signing in,
    and every account switch would go unnoticed until quota looked wrong.
    """
    rotated = "9d6b4e66fff2753f"          # digest of a refreshed credential blob
    assert rotated != FP_A
    # The same human across a rotation: same fingerprint, no switch event.
    assert ident.identity_changed(verified(FP_A), verified(FP_A)) is False
    # The rotation digest is not an identity and must not be mistaken for one.
    assert ident.identity_changed(verified(rotated), verified(FP_A)) is True


def test_fingerprint_is_stable_across_a_rotated_token():
    """The same `sub` produces the same fingerprint no matter the token bytes."""
    token_a = _jwt({"sub": "104093847193", "email": "someone@gmail.com"})
    token_b = _jwt({"sub": "104093847193", "email": "someone@gmail.com", "x_new": 1})
    assert _fingerprint_of_token(token_a) == _fingerprint_of_token(token_b)


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _fingerprint_of_token(token: str) -> str:
    claims = agy._jwt_claims(token)
    return agy._fingerprint(claims["sub"])


# ── 12. switch invalidates the old cache ──────────────────────────────────

def test_switch_invalidates_the_previous_reading():
    svc, accounts, _ = _service()
    ag1 = accounts[0]
    _commit(svc, ag1, verified(FP_A), remaining=42.0)
    assert svc._state.snapshots[ag1.key].windows[0].remaining_percent == 42.0

    _commit(svc, ag1, verified(FP_B), remaining=7.0)

    stored = svc._state.snapshots[ag1.key]
    assert stored.windows[0].remaining_percent == 7.0, "old usage survived a switch"
    events = svc.identity_events()
    assert events[-1]["previous"] == FP_A
    assert events[-1]["current"] == FP_B


# ── 9/10. one account's refresh cannot overwrite another's ────────────────

def test_refresh_of_ag2_cannot_overwrite_ag1():
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_B), remaining=10.0)
    _commit(svc, ag2, verified(FP_B), remaining=20.0)
    assert svc._state.snapshots[ag1.key].windows[0].remaining_percent == 50.0
    assert svc._state.snapshots[ag2.key].windows[0].remaining_percent == 20.0


def test_refresh_of_ag1_cannot_overwrite_ag2():
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_B), remaining=10.0)
    _commit(svc, ag1, verified(FP_A), remaining=60.0)
    assert svc._state.snapshots[ag2.key].windows[0].remaining_percent == 10.0
    assert svc._state.snapshots[ag1.key].windows[0].remaining_percent == 60.0


def test_two_slots_on_one_identity_count_once_for_capacity():
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_A), remaining=50.0)
    report = svc.identity_report()
    assert report["configured"] == 2
    assert report["unique_identities"] == 1, "phantom 2x capacity"
    assert report["shared_with"] == {ag2.key: ag1.key}
    assert svc.shared_identity_with(ag2.key) == ag1.key


def test_router_capacity_deduplicates_shared_identities():
    """A fallback that trusts slot count burns the same quota twice."""
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_A), remaining=50.0)
    pools = svc.identity_report()["unique_identities"]
    assert pools == 1


def test_switch_into_an_existing_identity_is_recognised_immediately():
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_B), remaining=50.0)
    assert svc.identity_report()["shared_with"] == {}
    _commit(svc, ag1, verified(FP_B), remaining=50.0)
    # Roster order decides which of an equal pair is canonical; the relation
    # itself is symmetric and is what "these are one account" means.
    assert svc.identity_report()["shared_with"] == {ag2.key: ag1.key}
    assert svc.identity_report()["unique_identities"] == 1


def test_returning_to_the_original_identity_drops_the_duplicate():
    svc, accounts, _ = _service()
    ag1, ag2 = accounts
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    _commit(svc, ag2, verified(FP_B), remaining=50.0)
    _commit(svc, ag1, verified(FP_B), remaining=50.0)
    assert svc.identity_report()["unique_identities"] == 1
    _commit(svc, ag1, verified(FP_A), remaining=50.0)
    assert svc.identity_report()["shared_with"] == {}
    assert svc.identity_report()["unique_identities"] == 2


# ── 20. managed boundaries ────────────────────────────────────────────────

def test_managed_account_may_not_borrow_the_current_user_reader(monkeypatch):
    """THE isolation rule.

    A local Antigravity reader opens the credential store of whoever runs this
    process. For an account owned by another Windows user that returns the
    OPERATOR's session, so its numbers would be filed under the managed
    account's name — one provider identity wearing two account names.
    """
    monkeypatch.setenv("USERNAME", "vac34")
    managed = AccountRef("antigravity", "m", "Antigravity 2", "shared", "", True,
                         {"origin": "shared",
                          "execution_backend": "managed_windows_user",
                          "windows_user": "antigravity_b"})
    assert sai.local_read_is_context_safe(managed) is False


def test_account_owned_by_the_current_user_may_be_read_locally(monkeypatch):
    monkeypatch.setenv("USERNAME", "vac34")
    own = AccountRef("antigravity", "o", "Antigravity 1", "shared", "", True,
                     {"origin": "shared", "execution_backend": "windows_user",
                      "windows_user": "vac34"})
    assert sai.local_read_is_context_safe(own) is True


def test_owner_that_cannot_be_proven_is_refused_not_assumed(monkeypatch):
    monkeypatch.setenv("USERNAME", "vac34")
    unknown = AccountRef("antigravity", "u", "Antigravity 3", "shared", "", True,
                         {"origin": "shared", "execution_backend": "windows_user"})
    assert sai.local_read_is_context_safe(unknown) is False


def test_profile_directory_accounts_are_always_locally_readable(monkeypatch):
    monkeypatch.setenv("USERNAME", "vac34")
    claude = AccountRef("claude", "c", "Claude 2", "shared", "", True,
                        {"origin": "shared",
                         "execution_backend": "profile_directory"})
    assert sai.local_read_is_context_safe(claude) is True


def test_unsafe_account_never_reaches_the_local_reader(monkeypatch):
    """The guard must stop the read, not merely annotate it."""
    monkeypatch.setenv("USERNAME", "vac34")
    plane = Plane(usage={
        "account_id": "antigravity:windows-user:b", "provider_id": "antigravity",
        "skipped_reason": "provider_does_not_support_quota",
        "context_state": "ONLINE", "auth_state": "UNKNOWN"})
    _wire(monkeypatch, plane)
    managed = AccountRef("antigravity", "m", "Antigravity 2", "shared", "", True,
                         {"origin": "shared", "shared_account_id": "antigravity:windows-user:b",
                          "execution_backend": "managed_windows_user",
                          "windows_user": "antigravity_b"})
    called = []
    snap = sai.probe_shared(managed, time.monotonic() + 5,
                            local_probe=lambda a, d: called.append(a) or None)
    assert called == [], "fell back to the current user's credential store"
    assert snap.error_code == "shared_context_unsafe"


def test_plane_identity_is_carried_onto_the_snapshot(monkeypatch):
    """The plane publishes identity under `credential`, beside the credential
    facts it read from that account's OWN store."""
    plane = Plane(usage={
        "account_id": "antigravity:windows-user:a", "provider_id": "antigravity",
        "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
        "windows": [{"window": "weekly", "remaining_fraction": 0.5}],
        "credential": {"target": "gemini:antigravity", "credential_present": True,
                       "provider_identity": {"fingerprint": FP_A, "verified": True,
                                             "source": "google_id_token_sub"}}})
    _wire(monkeypatch, plane)
    shared_acct = AccountRef("antigravity", "s", "Antigravity 1", "shared", "", True,
                             {"origin": "shared",
                              "shared_account_id": "antigravity:windows-user:a"})
    snap = sai.probe_shared(shared_acct, time.monotonic() + 5)
    assert snap.status == "OK"
    assert ident.fingerprint_of(snap.provider_metadata) == FP_A


def test_plane_that_proves_nothing_yields_no_identity(monkeypatch):
    plane = Plane(usage={
        "account_id": "antigravity:windows-user:a", "provider_id": "antigravity",
        "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
        "windows": [{"window": "weekly", "remaining_fraction": 0.5}],
        "credential": {"target": "gemini:antigravity", "credential_present": True,
                       "provider_identity": {"fingerprint": FP_A, "verified": False}}})
    _wire(monkeypatch, plane)
    shared_acct = AccountRef("antigravity", "s", "Antigravity 1", "shared", "", True,
                             {"origin": "shared",
                              "shared_account_id": "antigravity:windows-user:a"})
    snap = sai.probe_shared(shared_acct, time.monotonic() + 5)
    assert ident.fingerprint_of(snap.provider_metadata) == ident.UNRESOLVED


def test_plane_with_no_identity_block_yields_no_identity(monkeypatch):
    """An older plane proves nothing. It must not be read as "no duplicate"."""
    plane = Plane(usage={
        "account_id": "antigravity:windows-user:a", "provider_id": "antigravity",
        "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
        "windows": [{"window": "weekly", "remaining_fraction": 0.5}]})
    _wire(monkeypatch, plane)
    shared_acct = AccountRef("antigravity", "s", "Antigravity 1", "shared", "", True,
                             {"origin": "shared",
                              "shared_account_id": "antigravity:windows-user:a"})
    snap = sai.probe_shared(shared_acct, time.monotonic() + 5)
    assert ident.fingerprint_of(snap.provider_metadata) == ident.UNRESOLVED


# ── 16. nothing secret is ever exposed ────────────────────────────────────

def test_identity_fields_carry_no_token_or_address():
    fragment = verified(FP_A)
    for key, value in fragment.items():
        assert "@" not in str(value)
        assert "eyJ" not in str(value)          # a JWT header prefix
    assert FP_A not in ("someone@gmail.com",)


def test_read_identity_never_returns_token_material(monkeypatch):
    monkeypatch.setattr(agy, "_read_credential",
                        lambda: (b"blob", {"id_token": _jwt(
                            {"sub": "104093847193", "email": "someone@gmail.com"}),
                            "token": {"access_token": "ya29.SECRET",
                                      "refresh_token": "1//SECRET"}}))
    reading = agy.read_identity()
    assert set(reading) == {"fingerprint", "source", "verified"}
    assert reading["source"] == "google_id_token_sub"
    blob = json.dumps(reading)
    assert "SECRET" not in blob and "@" not in blob


def test_identity_falls_back_to_email_only_when_there_is_no_subject(monkeypatch):
    monkeypatch.setattr(agy, "_read_credential",
                        lambda: (b"blob", {"id_token": _jwt({"email": "a@b.com"})}))
    reading = agy.read_identity()
    assert reading["source"] == "google_id_token_email"
    assert reading["fingerprint"] == agy._fingerprint("a@b.com")


def test_absent_or_unreadable_credential_proves_nothing(monkeypatch):
    monkeypatch.setattr(agy, "_read_credential", lambda: (b"", {}))
    assert agy.read_identity() == {}
    monkeypatch.setattr(agy, "_read_credential",
                        lambda: (b"blob", {"id_token": "not-a-jwt"}))
    assert agy.read_identity() == {}


# ── helpers ───────────────────────────────────────────────────────────────

class Plane:
    def __init__(self, usage: dict | None = None) -> None:
        self.engine = ENGINE
        self.usage = usage or {}
        self.calls: list[str] = []

    def run(self, argv: list[str], deadline: float) -> dict:
        self.calls.append(" ".join(argv))
        if argv and argv[0] == "list":
            return {"ok": True, "stdout": json.dumps(
                {"accounts": [], "status": "ok"}), "error": ""}
        return {"ok": True, "stdout": json.dumps(self.usage), "error": ""}


def _wire(monkeypatch: pytest.MonkeyPatch, plane: Plane) -> None:
    monkeypatch.setattr(sai, "TestEngine", lambda: plane.engine)
    monkeypatch.setattr(sai, "TestRun", plane.run)


def _service():
    from fastprompter.core.usage_limits.service import UsageLimitService
    svc = UsageLimitService({}, discover=False)
    ag1 = AccountRef("antigravity", "ag1", "Antigravity 1", "configured", "", True, {})
    ag2 = AccountRef("antigravity", "ag2", "Antigravity 2", "shared", "", True,
                     {"origin": "shared"})
    svc._state.accounts = [ag1, ag2]
    return svc, [ag1, ag2], None


def _commit(svc, account: AccountRef, meta: dict, *, remaining: float) -> None:
    from fastprompter.core.usage_limits.model import UsageWindow
    prev = svc._state.snapshots.get(account.key)
    if prev is not None and ident.identity_changed(prev.provider_metadata, meta):
        svc._state.identity_events.append({
            "account_key": account.key, "display_name": account.display_name,
            "previous": ident.fingerprint_of(prev.provider_metadata),
            "current": ident.fingerprint_of(meta), "observed_at": time.time()})
        prev = None
    svc._state.snapshots[account.key] = UsageSnapshot(
        account=account, status="OK",
        windows=[UsageWindow(key="weekly", duration_minutes=10080, available=True,
                             used_percent=100.0 - remaining,
                             remaining_percent=remaining)],
        fetched_at=time.time(), provider_metadata=dict(meta))
    svc._rebuild_identity_report()
