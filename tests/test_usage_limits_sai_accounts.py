"""SAI Accounts federation — the OPTIONAL control plane.

Every case is deterministic: no real engine, no real vendor, no registry write.
The plane is faked through the two seams the module exposes
(``sai_accounts.TestEngine`` / ``TestRun``), so the suite proves the CONTRACT
rather than the machine it happens to run on.

The contract in one sentence: SAI Accounts is federation, not captivity. The
application is fully usable with the plane absent, adds shared accounts when it
is present, keeps local-only accounts either way, merges only on PROVEN identity,
and survives the plane going away mid-life.

Every assertion drives the production function it names. Nothing here
re-implements the merge: a test of a copy proves the copy.
"""

from __future__ import annotations

import json
import time

import pytest

from fastprompter.core.usage_limits import sai_accounts as sai
from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot

ENGINE = r"C:\fake\sai-accounts.exe"


# ── fixtures / fakes ────────────────────────────────────────────────────────

class Plane:
    """A fake control plane. ``engine`` == "" means the plane is NOT installed."""

    def __init__(self) -> None:
        self.engine = ENGINE
        self.list_stdout = ""
        self.list_ok = True
        self.usage_stdout = ""
        self.usage_ok = True
        self.calls: list[str] = []

    def run(self, argv: list[str], deadline: float) -> dict:
        self.calls.append(" ".join(argv))
        if argv and argv[0] == "list":
            return {"ok": self.list_ok, "stdout": self.list_stdout, "error": ""}
        return {"ok": self.usage_ok, "stdout": self.usage_stdout, "error": ""}

    def answer_list(self, *accounts: dict) -> None:
        self.list_stdout = json.dumps(
            {"schema": "sai.accounts/list/1", "accounts": list(accounts),
             "status": "ok"})


def shared(account_id: str, provider: str, label: str, *, locator: str = "",
           backend: str = "windows_user", state: str = "ENABLED",
           hidden: bool = False) -> dict:
    meta: dict = {}
    if backend == "profile_directory":
        meta["profile_locator"] = locator
    elif locator:
        meta["windows_user"] = locator
    return {"account_id": account_id, "provider_id": provider,
            "display_name": label, "compact_label": label[-2:],
            "execution_backend": backend,
            "execution_context_id": "current-user",
            "operational_state": state, "hidden": hidden,
            "context_label": None, "provider_metadata": meta}


def local(provider: str, path: str, name: str = "local") -> AccountRef:
    from fastprompter.core.usage_limits.model import stable_id_for
    return AccountRef(provider_id=provider, stable_id=stable_id_for(provider, path),
                      display_name=name, source_kind="configured",
                      source_path=path, enabled=True,
                      metadata={"identity_locator": path})


def snapshot_of(callable_) -> UsageSnapshot:
    return callable_(time.monotonic() + 5)


@pytest.fixture
def plane(monkeypatch: pytest.MonkeyPatch) -> Plane:
    fake = Plane()
    monkeypatch.setattr(sai, "TestEngine", lambda: fake.engine)
    monkeypatch.setattr(sai, "TestRun", fake.run)
    # The seam must be OURS. A plane that resolves to "" makes read_registry
    # answer an empty listing, which downstream is indistinguishable from a
    # correct "the registry withdrew nothing" -- so a lost seam used to show up
    # as five plausible-looking failures in TestGlobalState and nowhere else.
    # Assert it here and the loss names itself.
    assert sai.engine_path() == ENGINE
    return fake


# The provider roster is the APPLICATION's, exactly as the service passes it.
# It is stated here rather than derived from the account list, because an empty
# account list must not mean "this application implements no providers".
IMPLEMENTED = ("claude", "codex", "antigravity", "zcode", "freebuff")


def merged(plane: Plane, accounts: list[AccountRef],
           providers: tuple[str, ...] = IMPLEMENTED) -> list[AccountRef]:
    return sai.augment(accounts, providers, deadline=time.monotonic() + 5)


def origins(accounts: list[AccountRef]) -> str:
    return ",".join(
        f"{a.provider_id}/{a.metadata.get('origin', 'local')}:{a.display_name}"
        for a in accounts)


# ── STANDALONE ──────────────────────────────────────────────────────────────

class TestStandalone:
    def test_plane_absent_resolves_to_nothing(self, plane: Plane) -> None:
        plane.engine = ""
        assert sai.engine_path() == ""

    def test_absent_plane_yields_no_shared_accounts(self, plane: Plane) -> None:
        plane.engine = ""
        assert sai.list_accounts({"claude"}) == []

    def test_absent_plane_never_spawns_a_child(self, plane: Plane) -> None:
        plane.engine = ""
        merged(plane, [local("claude", r"C:\Users\x\.claude")])
        assert plane.calls == []

    def test_local_accounts_survive_the_plane_being_absent(self, plane: Plane) -> None:
        plane.engine = ""
        mine = [local("claude", r"C:\Users\x\.claude"),
                local("codex", r"C:\Users\x\.codex")]
        assert merged(plane, mine) == mine


class TestBrokenPlane:
    """A half-installed or failing plane is never a single point of failure."""

    def test_erroring_list_leaves_the_local_result_intact(self, plane: Plane) -> None:
        plane.list_ok = False
        mine = [local("claude", r"C:\Users\x\.claude")]
        assert origins(merged(plane, mine)) == "claude/local:local"

    def test_malformed_reply_is_absorbed(self, plane: Plane) -> None:
        plane.list_stdout = "{ this is not json"
        assert sai.list_accounts({"claude"}) == []

    def test_wrong_typed_reply_is_absorbed(self, plane: Plane) -> None:
        plane.list_stdout = '{"accounts": "not-an-array"}'
        assert sai.list_accounts({"claude"}) == []

    def test_missing_stdout_is_absorbed(self, plane: Plane) -> None:
        plane.list_stdout = ""
        assert sai.list_accounts({"claude"}) == []


# ── FEDERATED ───────────────────────────────────────────────────────────────

class TestFederated:
    def test_shared_accounts_appear(self, plane: Plane) -> None:
        plane.answer_list(
            shared("antigravity:windows-user:aaa", "antigravity", "Antigravity 1",
                   locator="alice"),
            shared("antigravity:windows-user:bbb", "antigravity", "Antigravity 2",
                   locator="bob"))
        got = merged(plane, [])
        assert [a.display_name for a in got] == ["Antigravity 1", "Antigravity 2"]

    def test_identity_is_the_canonical_account_id(self, plane: Plane) -> None:
        plane.answer_list(shared("antigravity:windows-user:aaa", "antigravity",
                                 "Antigravity 1", locator="alice"))
        got = merged(plane, [])
        assert got[0].metadata["shared_account_id"] == "antigravity:windows-user:aaa"
        assert got[0].source_kind == "shared"
        assert sai.is_shared(got[0])

    def test_hidden_and_non_enabled_accounts_leave_the_surface(self, plane: Plane) -> None:
        plane.answer_list(
            shared("antigravity:windows-user:aaa", "antigravity", "Keep",
                   locator="alice"),
            shared("antigravity:windows-user:bbb", "antigravity", "Hidden",
                   locator="bob", hidden=True),
            shared("antigravity:windows-user:ccc", "antigravity", "Frozen",
                   locator="carol", state="FROZEN"),
            shared("antigravity:windows-user:ddd", "antigravity", "Archived",
                   locator="dave", state="ARCHIVED"))
        assert [a.display_name for a in merged(plane, [])] == ["Keep"]

    def test_an_account_for_an_unknown_provider_is_not_offered(
            self, plane: Plane) -> None:
        # A card that can never be drawn or probed is worse than silence.
        plane.answer_list(shared("gemini:windows-user:aaa", "gemini", "Gemini",
                                 locator="alice"))
        assert merged(plane, [local("claude", r"C:\Users\x\.claude")]) == [
            local("claude", r"C:\Users\x\.claude")]

    def test_provider_filter_is_applied(self, plane: Plane) -> None:
        plane.answer_list(
            shared("antigravity:windows-user:aaa", "antigravity", "A", locator="a"),
            shared("codex:profile-dir:bbb", "codex", "B",
                   locator=r"C:\Users\x\.codex", backend="profile_directory"))
        assert [a.provider_id for a in sai.list_accounts({"codex"})] == ["codex"]


# ── HYBRID ──────────────────────────────────────────────────────────────────

class TestHybrid:
    def test_a_proven_duplicate_is_one_account_not_two(self, plane: Plane) -> None:
        plane.answer_list(
            shared("claude:profile-dir:aaa", "claude", "Claude 1",
                   locator=r"C:\Users\x\.claude", backend="profile_directory"),
            shared("claude:profile-dir:bbb", "claude", "Claude 9",
                   locator=r"C:\Users\x\.claude-9", backend="profile_directory"))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1")]
        got = merged(plane, mine)
        assert origins(got) == "claude/local:Claude 1,claude/shared:Claude 9"

    def test_a_profile_dir_identity_matches_case_and_separators(
            self, plane: Plane) -> None:
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator="c:/users/X/.claude/",
                                 backend="profile_directory"))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1")]
        assert len(merged(plane, mine)) == 1

    def test_local_only_accounts_survive(self, plane: Plane) -> None:
        plane.answer_list(shared("claude:profile-dir:bbb", "claude", "Claude 9",
                                 locator=r"C:\Users\x\.claude-9",
                                 backend="profile_directory"))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1"),
                local("codex", r"C:\Users\x\.codex", "Codex 1")]
        got = merged(plane, mine)
        # Shared accounts are appended, never interleaved: the local roster
        # keeps its own order, and the service re-groups by provider after.
        assert origins(got) == ("claude/local:Claude 1,codex/local:Codex 1,"
                                "claude/shared:Claude 9")

    def test_local_entries_keep_their_own_stable_id(self, plane: Plane) -> None:
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Renamed",
                                 locator=r"C:\Users\x\.claude",
                                 backend="profile_directory"))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1")]
        got = merged(plane, mine)
        assert got[0].stable_id == mine[0].stable_id
        assert got[0].source_kind == "configured"

    def test_a_locally_configured_account_needs_no_shared_twin(self, plane: Plane) -> None:
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator=r"C:\Users\x\.claude",
                                 backend="profile_directory"))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1")]
        assert merged(plane, mine) == mine

    def test_a_shared_account_never_appears_twice(self, plane: Plane) -> None:
        entry = shared("claude:profile-dir:aaa", "claude", "Claude 1",
                       locator=r"C:\Users\x\.claude", backend="profile_directory")
        plane.answer_list(entry, entry)
        assert len(merged(plane, [])) == 1


# ── DUPLICATE DISCOVERY ─────────────────────────────────────────────────────

class TestDuplicateDiscovery:
    def test_same_display_name_different_identity_stays_separate(
            self, plane: Plane) -> None:
        # Two accounts both called "Claude 1", in different directories. The
        # name is not evidence.
        plane.answer_list(
            shared("claude:profile-dir:aaa", "claude", "Claude 1",
                   locator=r"C:\Users\x\.claude", backend="profile_directory"),
            shared("claude:profile-dir:bbb", "claude", "Claude 1",
                   locator=r"C:\Users\y\.claude", backend="profile_directory"))
        assert len(merged(plane, [])) == 2

    def test_unprovable_identity_is_shown_both_ways(self, plane: Plane) -> None:
        plane.answer_list(shared("claude:windows-user:zzz", "claude", "Claude 1",
                                 locator=""))
        mine = [local("claude", r"C:\Users\x\.claude", "Claude 1")]
        got = merged(plane, mine)
        assert origins(got) == "claude/local:Claude 1,claude/shared:Claude 1"

    def test_an_empty_locator_never_claims_an_empty_key(self) -> None:
        assert sai.identity_key("claude", "") == ""
        assert sai.identity_key("", "alice") == ""

    def test_different_providers_never_collide(self) -> None:
        assert sai.identity_key("claude", "alice") != sai.identity_key("codex", "alice")


# ── CENTRAL FAILURE ─────────────────────────────────────────────────────────

class TestCentralFailure:
    def _shared_account(self) -> AccountRef:
        return sai._account_ref(sai.SharedAccount(
            account_id="antigravity:windows-user:aaa", provider_id="antigravity",
            display_name="Antigravity 1", compact_label="AG1",
            backend="windows_user", locator="alice",
            operational_state="ENABLED", hidden=False))

    def test_plane_removed_mid_life_still_leaves_local_accounts_working(
            self, plane: Plane) -> None:
        plane.engine = ""
        mine = [local("claude", r"C:\Users\x\.claude")]
        assert merged(plane, mine) == mine

    def test_plane_windows_become_real_windows(self, plane: Plane) -> None:
        plane.usage_stdout = json.dumps({
            "account_id": "antigravity:windows-user:aaa",
            "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
            "usage_status": "authenticated_usage",
            "windows": [
                {"pool_index": 0, "window": "5h", "remaining_fraction": 0.25,
                 "reset_time": "2026-10-03T10:00:00Z"},
                {"pool_index": 0, "window": "weekly", "remaining_fraction": 0.5,
                 "reset_time": "2026-10-06T10:00:00Z"}]})
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5)
        assert got.status == "OK"
        assert [w.key for w in got.windows] == ["five_hour", "weekly"]
        assert got.windows[0].used_percent == pytest.approx(75.0)
        assert got.windows[0].resets_at_epoch is not None

    def test_offline_context_is_reported_not_faked(self, plane: Plane) -> None:
        plane.usage_stdout = json.dumps({
            "account_id": "antigravity:windows-user:aaa",
            "context_state": "OFFLINE", "auth_state": "UNKNOWN",
            "skipped_reason": "CONTEXT_OFFLINE"})
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5)
        assert got.status == "UNAVAILABLE"
        assert got.error_code == "shared_source_stale"
        assert "offline" in got.error_summary

    def test_auth_refusal_is_typed_not_unknown(self, plane: Plane) -> None:
        # The plane signals an unreadable account with a TYPED envelope AND a
        # nonzero exit. Reporting that as "the plane is offline" would be a
        # lie about the whole control plane, so the payload wins.
        plane.usage_ok = False
        plane.usage_stdout = json.dumps({
            "account_id": "antigravity:windows-user:aaa",
            "context_state": "ONLINE", "auth_state": "AUTH_REQUIRED",
            "usage_status": "unreadable_usage"})
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5)
        assert got.status == "AUTH_REQUIRED"
        assert got.error_code == "auth_required"

    def test_a_nonzero_exit_still_yields_a_typed_reading(self, plane: Plane) -> None:
        plane.usage_ok = False
        plane.usage_stdout = json.dumps({
            "account_id": "antigravity:windows-user:aaa",
            "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
            "usage_status": "authenticated_usage",
            "windows": [{"window": "5h", "remaining_fraction": 0.75}]})
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5)
        assert got.status == "OK"
        assert got.windows[0].used_percent == pytest.approx(25.0)

    def test_garbage_on_a_failed_call_is_still_an_outage(self, plane: Plane) -> None:
        plane.usage_ok = False
        plane.usage_stdout = "not json at all"
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5)
        assert got.status == "UNAVAILABLE"
        assert got.error_code == "shared_source_offline"

    def test_erroring_plane_is_not_the_local_read(self, plane: Plane) -> None:
        # The local probe would answer about THIS machine's session. Borrowing
        # it here would report the wrong account's numbers under this account's
        # name, so it must not be called at all.
        plane.usage_ok = False
        called: list[str] = []
        got = sai.probe_shared(self._shared_account(), time.monotonic() + 5,
                               local_probe=lambda a, d: called.append("touched"))
        assert got.status == "UNAVAILABLE"
        assert got.error_code == "shared_source_offline"
        assert called == []

    def test_recovery_when_the_plane_answers_again(self, plane: Plane) -> None:
        account = self._shared_account()
        plane.usage_ok = False
        assert sai.probe_shared(account, time.monotonic() + 5).status == "UNAVAILABLE"
        plane.usage_ok = True
        plane.usage_stdout = json.dumps({
            "account_id": account.metadata["shared_account_id"],
            "context_state": "ONLINE", "auth_state": "AUTHENTICATED",
            "windows": [{"window": "5h", "remaining_fraction": 1.0}]})
        assert sai.probe_shared(account, time.monotonic() + 5).status == "OK"

    def test_a_provider_the_plane_cannot_read_keeps_its_local_reader(
            self, plane: Plane) -> None:
        # The plane says it has no opinion. That is not an outage: the account
        # is a local config directory and reads exactly as it always has.
        plane.usage_stdout = json.dumps({
            "account_id": "claude:profile-dir:aaa",
            "quota_state": "UNKNOWN",
            "skipped_reason": "provider_does_not_support_quota"})
        account = sai._account_ref(sai.SharedAccount(
            account_id="claude:profile-dir:aaa", provider_id="claude",
            display_name="Claude 1", compact_label="CL1",
            backend="profile_directory", locator=r"C:\Users\x\.claude",
            operational_state="ENABLED", hidden=False))
        sentinel = UsageSnapshot(account=account, status="OK", windows=[])
        got = sai.probe_shared(account, time.monotonic() + 5,
                               local_probe=lambda a, d: sentinel)
        assert got is sentinel

    def test_a_shared_account_without_a_canonical_id_is_refused(
            self, plane: Plane) -> None:
        account = AccountRef(provider_id="claude", stable_id="x",
                             display_name="X", source_kind="shared",
                             metadata={"origin": "shared"})
        got = sai.probe_shared(account, time.monotonic() + 5)
        assert got.status == "UNAVAILABLE"
        assert got.error_code == "shared_identity_missing"


# ── GLOBAL hide / disable ────────────────────────────────────────────────────

class TestGlobalState:
    """The plane's global state reaches the row the consumer already had.

    A global hide that only hides the SHARED half would let every account this
    application already discovered survive the hide the operator asked for.
    Identity is still the only thing that can connect the two halves: a locator
    that cannot be proven suppresses nothing.
    """

    def test_a_globally_hidden_shared_account_is_not_drawn(self, plane: Plane) -> None:
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 9",
                                 locator=r"C:\Users\x\.claude9", hidden=True))
        assert sai.list_accounts({"claude"}) == []

    def test_a_globally_hidden_account_drops_its_proven_local_twin(
            self, plane: Plane) -> None:
        home = r"C:\Users\x\.claude"
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator=home, backend="profile_directory", hidden=True))
        assert merged(plane, [local("claude", home)]) == []

    @pytest.mark.parametrize("state", ["DISABLED", "FROZEN", "ARCHIVED"])
    def test_an_account_out_of_service_drops_its_proven_local_twin(
            self, plane: Plane, state: str) -> None:
        home = r"C:\Users\x\.claude"
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator=home, backend="profile_directory", state=state))
        assert merged(plane, [local("claude", home)]) == []

    def test_an_enabled_shared_account_leaves_its_local_twin_alone(
            self, plane: Plane) -> None:
        home = r"C:\Users\x\.claude"
        mine = [local("claude", home)]
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator=home, backend="profile_directory"))
        assert merged(plane, mine) == mine

    def test_a_withdrawal_suppresses_only_its_own_identity(
            self, plane: Plane) -> None:
        hidden_home = r"C:\Users\x\.claude"
        other_home = r"C:\Users\x\.codex"
        plane.answer_list(
            shared("claude:profile-dir:aaa", "claude", "Claude 1",
                   locator=hidden_home, backend="profile_directory", hidden=True),
            shared("codex:profile-dir:bbb", "codex", "Codex 1",
                   locator=other_home, backend="profile_directory"))
        assert origins(merged(plane, [local("claude", hidden_home),
                                      local("codex", other_home)])) == "codex/local:local"

    def test_an_unprovable_withdrawal_suppresses_nothing(self, plane: Plane) -> None:
        # No locator means "cannot prove". Suppressing on that would hide every
        # account that also has no locator, which is a different one each time.
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 9",
                                 hidden=True))
        mine = [local("claude", r"C:\Users\x\.claude")]
        assert merged(plane, mine) == mine

    def test_a_withdrawal_needs_no_second_call(self, plane: Plane) -> None:
        home = r"C:\Users\x\.claude"
        plane.answer_list(shared("claude:profile-dir:aaa", "claude", "Claude 1",
                                 locator=home, backend="profile_directory", hidden=True))
        merged(plane, [local("claude", home)])
        assert plane.calls == ["list --all"]

    def test_a_broken_plane_withdraws_nothing(self, plane: Plane) -> None:
        # An unreadable registry is not permission to delete local accounts.
        plane.list_ok = False
        mine = [local("claude", r"C:\Users\x\.claude")]
        assert merged(plane, mine) == mine

    def test_the_predicate_is_the_one_the_list_filter_uses(self) -> None:
        assert sai.withdrawn_by_plane({"hidden": True}) is True
        assert sai.withdrawn_by_plane({"operational_state": "DISABLED"}) is True
        assert sai.withdrawn_by_plane({"operational_state": ""}) is False
        assert sai.withdrawn_by_plane({}) is False


# ── read-only guarantee ─────────────────────────────────────────────────────

class TestReadOnly:
    def test_the_module_only_ever_reads(self) -> None:
        import pathlib
        source = pathlib.Path(sai.__file__).read_text(encoding="utf-8")
        for forbidden in ("open(", "write_text", "write_bytes", "mkdir",
                          "remove(", "unlink", "rmtree", "subprocess.run",
                          "urlopen", "os.environ["):
            assert forbidden not in source, f"{forbidden!r} must not appear"

    def test_an_override_pointing_at_a_missing_file_falls_through(
            self, plane: Plane, monkeypatch: pytest.MonkeyPatch) -> None:
        # A stale override is a normal configuration accident. It must not
        # become a phantom engine and it must not hide the real installation.
        monkeypatch.setattr(sai, "TestEngine", None)
        monkeypatch.setenv(sai.ENV_OVERRIDE, r"C:\nope\sai-accounts.exe")
        monkeypatch.setattr(sai.shutil, "which", lambda name: "")
        monkeypatch.setattr(sai.os.path, "isfile", lambda p: False)
        assert sai.engine_path() == ""

    def test_the_override_is_used_when_it_exists(
            self, plane: Plane, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sai, "TestEngine", None)
        monkeypatch.setenv(sai.ENV_OVERRIDE, ENGINE)
        monkeypatch.setattr(sai.os.path, "isfile", lambda p: True)
        assert sai.engine_path() == ENGINE
