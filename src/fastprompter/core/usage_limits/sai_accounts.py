"""SAI Accounts — the OPTIONAL shared account control plane.

SAI Accounts is federation, not captivity. This module is the whole integration
and it is allowed to answer *nothing*: with the plane absent, stopped, broken or
uninstalled, every function here returns an empty result and FastPrompter behaves
exactly as it did before this file existed. Nothing here writes, publishes or
exports — an account only ever reaches the shared registry through an explicit
action the operator takes elsewhere.

Three shapes, one rule each:

* **STANDALONE** — no plane. ``list_accounts`` is empty, nothing is merged, every
  account keeps its own reader. This is the GitHub-user path and it is the
  default, not a fallback.
* **FEDERATED** — plane present. Shared accounts the registry holds and this
  provider does not already know appear as extra cards, automatically.
* **HYBRID** — both. A shared account and a local account merge into ONE card
  only when their provider identity locator proves they are the same identity.
  A display name is never evidence; two accounts called "Claude 1" that live in
  different config directories are two accounts.

The plane owns the identity (canonical ``account_id``), the provider, the
execution context, the global lifecycle state and the canonical alias. The
application keeps owning what is local to it: meter order, local visibility,
compact layout, which windows it draws.

ponytail: the plane is a registry first and a broker second, so it can honestly
say ``provider_does_not_support_quota`` for a provider it does not yet read. Such
an account is read locally when — and only when — its locator is a real local
path this application can read itself. Upgrade path: when the plane gains a
broker for that provider, the same call returns windows and the fallback is
simply never taken.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import time

from fastprompter.core.usage_limits.model import (
    AccountRef,
    UsageSnapshot,
    canonical_path,
    stable_id_for,
    stable_id_for_value,
)

# Where the control plane installs itself. Absent everywhere else, which is the
# point: a machine that never installed it takes the STANDALONE path.
CANONICAL_INSTALL = os.path.join("C:\\", "ProgramData", "SAI", "Accounts", "bin")
ENV_OVERRIDE = "SAI_ACCOUNTS_EXE"

# Bound, like every other child this application spawns. The plane is a local
# CLI: a read that has not answered by now is a plane that is not there.
LIST_DEADLINE_S = 4.0
USAGE_TIMEOUT_CAP_S = 30.0

# One vocabulary for "this is where the account's identity lives". Ordered by
# how strong the evidence is, strongest first. profile_locator is a real path
# and therefore directly comparable to this application's own discovery;
# windows_user is an account name; windows_sid is deliberately never projected
# by the public list, but if a future plane version does expose it, it is the
# strongest locator of all.
_LOCATOR_FIELDS = ("profile_locator", "windows_user", "windows_sid", "context_label")

# Test seams. Both are monkeypatched by the federation suite; nothing else in
# the application may set them.
TestEngine: callable | None = None
TestRun: callable | None = None


@dataclasses.dataclass(frozen=True)
class SharedAccount:
    """One account the shared registry owns, as the public list projection."""

    account_id: str          # canonical, plane-owned identity
    provider_id: str
    display_name: str
    compact_label: str
    backend: str             # windows_user / profile_directory
    locator: str             # stable provider identity locator, may be ""
    operational_state: str
    hidden: bool


def engine_path() -> str:
    """Resolve the plane's CLI, or return "" when it is not installed.

    Resolution order: the explicit override, then the canonical install, then
    whatever is on PATH. Every branch may legitimately produce "".
    """
    if TestEngine is not None:
        return TestEngine() or ""
    override = os.environ.get(ENV_OVERRIDE, "")
    if override and os.path.isfile(override):
        return override
    installed = os.path.join(CANONICAL_INSTALL, "sai-accounts.exe")
    if os.path.isfile(installed):
        return installed
    return shutil.which("sai-accounts") or ""


def _run(argv: list[str], deadline: float) -> dict:
    """Spawn the plane once, bounded. Returns the ``run_cli`` shape.

    Never raises and never blocks past the deadline: an absent, failing or
    wedged plane is an ordinary answer here, not an exception the caller has to
    guard.
    """
    if TestRun is not None:
        return TestRun(argv, deadline)
    from fastprompter.core.usage_limits.cli_tools import run_cli
    exe = engine_path()
    if not exe:
        return {"error": "plane_absent"}
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        return {"error": "deadline_exceeded"}
    return run_cli([exe, *argv], deadline)


def _json_object(text: str) -> dict:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def locator_of(entry: dict) -> str:
    """The account's stable identity locator, strongest evidence available."""
    meta = entry.get("provider_metadata")
    if isinstance(meta, dict):
        for field in _LOCATOR_FIELDS:
            value = meta.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for field in _LOCATOR_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def identity_key(provider_id: str, locator: str) -> str:
    """Case- and space-insensitive merge key. Empty means "unprovable".

    An empty locator must never produce a key: two accounts with no comparable
    identity are not the same account, and a key built from "" would collapse
    every locator-less account into one.
    """
    provider = (provider_id or "").strip().lower()
    value = (locator or "").strip().lower()
    if not provider or not value:
        return ""
    if provider == "claude" or provider == "codex":
        # A config directory is a path: compare it as one, the way this
        # application's own discovery already compares it.
        value = canonical_path(value).lower()
    elif provider == "antigravity":
        normalized = value.replace("/", "\\")
        if "\\users\\" in normalized:
            parts = normalized.split("\\")
            try:
                u_idx = [p.lower() for p in parts].index("users")
                if u_idx + 1 < len(parts):
                    value = parts[u_idx + 1].strip().lower()
            except ValueError:
                pass
        elif "\\" in normalized or "/" in normalized:
            value = canonical_path(value).lower()
    return f"{provider}|{value}"


@dataclasses.dataclass(frozen=True)
class SharedListing:
    """One read of the plane, split by what this consumer must do with it.

    ``accounts`` is what may be drawn; ``suppressed`` is the identity keys of
    the accounts the plane has taken off the board. They are two answers to the
    SAME question, which is why they come from one pass over one list call.
    """

    accounts: list[SharedAccount]       # enabled + unhidden, for display
    suppressed: frozenset[str]          # identity keys the plane withdrew


def withdrawn_by_plane(entry: dict) -> bool:
    """True when the plane's own global state keeps this account off the board.

    One predicate, two uses. An account it answers true for is never drawn as a
    shared card, AND a local card proven to be the same identity is suppressed —
    the same account must not come back through the consumer's own discovery
    just because the consumer already had it. LOCAL visibility is a different
    axis and is never read from or written to the registry here.
    """
    if entry.get("hidden") is True:
        return True
    state = entry.get("operational_state")
    state = state if isinstance(state, str) and state else "ENABLED"
    return state != "ENABLED"


def read_registry(provider_ids: set[str] | list[str],
                  deadline: float | None = None) -> SharedListing:
    """Read the plane once and split its accounts into drawn and suppressed."""
    exe = engine_path()
    if not exe:
        return SharedListing([], frozenset())
    if deadline is None:
        deadline = time.monotonic() + LIST_DEADLINE_S
    # --all so an ARCHIVED account is still projected. Without it the plane
    # drops archived accounts from the payload entirely, and a withdrawal this
    # consumer cannot see is a withdrawal it cannot honour.
    result = _run(["list", "--all"], deadline)
    if not result.get("ok"):
        return SharedListing([], frozenset())
    payload = _json_object(result.get("stdout", ""))
    entries = payload.get("accounts")
    if not isinstance(entries, list):
        return SharedListing([], frozenset())
    wanted = {p.lower() for p in provider_ids}
    found: list[SharedAccount] = []
    suppressed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        account_id = entry.get("account_id")
        provider = entry.get("provider_id")
        if not isinstance(account_id, str) or not account_id:
            continue
        if not isinstance(provider, str) or provider.lower() not in wanted:
            continue
        locator = locator_of(entry)
        state = entry.get("operational_state")
        state = state if isinstance(state, str) and state else "ENABLED"
        if withdrawn_by_plane(entry):
            # An unprovable identity suppresses nothing: it would suppress
            # every account that also has no locator, which is a different one.
            key = identity_key(provider, locator)
            if key:
                suppressed.add(key)
            continue
        found.append(SharedAccount(
            account_id=account_id.strip(),
            provider_id=provider.strip(),
            display_name=str(entry.get("display_name") or account_id),
            compact_label=str(entry.get("compact_label") or ""),
            backend=str(entry.get("execution_backend") or ""),
            locator=locator,
            operational_state=state,
            hidden=False,
        ))
    return SharedListing(found, frozenset(suppressed))


def list_accounts(provider_ids: set[str] | list[str], deadline: float | None = None
                  ) -> list[SharedAccount]:
    """Every enabled, unhidden shared account for these providers."""
    return read_registry(provider_ids, deadline).accounts


def augment(local: list[AccountRef], provider_ids: set[str] | list[str],
            shared: list[SharedAccount] | None = None,
            deadline: float | None = None,
            suppressed: set[str] | frozenset[str] | None = None) -> list[AccountRef]:
    """Fold unclaimed shared accounts into an already-discovered account list.

    The local list is the answer, never a draft: every account this application
    found keeps its slot, its stable id and its own reader. A shared account
    joins only when no local account already claims its identity locator.

    The one exception is deliberate and is the plane's call, not this
    application's: an account whose identity is PROVEN here and withdrawn there
    is dropped. It is the same physical account, so honouring a global hide only
    on the shared half would let every account this application already knew
    survive the very hide the operator asked for.
    """
    accounts = list(local)
    known = {p.lower() for p in provider_ids}
    if shared is None:
        # Query by the APPLICATION's roster, not by what it happens to have
        # discovered. A machine whose local discovery found nothing is exactly
        # the machine that needs the shared registry to say something.
        listing = read_registry(provider_ids, deadline)
        shared, suppressed = listing.accounts, listing.suppressed
    withdrawn = frozenset(suppressed or ())
    if withdrawn:
        accounts = [a for a in accounts
                    if identity_key(a.provider_id,
                                    a.metadata.get("identity_locator") or a.source_path)
                    not in withdrawn]
    claimed: set[str] = set()
    for account in accounts:
        key = identity_key(account.provider_id, account.metadata.get("identity_locator")
                           or account.source_path)
        if key:
            claimed.add(key)
    for entry in shared:
        if entry.provider_id.lower() not in known:
            # A shared account for a provider this application does not
            # implement cannot be drawn, let alone probed. Offering a card
            # that can only ever be empty would be worse than silence.
            continue
        key = identity_key(entry.provider_id, entry.locator)
        if key and key in claimed:
            continue
        if key:
            claimed.add(key)
        accounts.append(_account_ref(entry))
    return accounts


def _account_ref(entry: SharedAccount) -> AccountRef:
    """The shared account as this application's own account shape.

    A profile-directory account keeps the path identity so it merges with — and
    reads exactly like — a locally discovered one. An account the plane
    identifies some other way gets a value identity, because an opaque vendor id
    must never be run through the path normalizer.
    """
    locator = entry.locator or entry.account_id
    if entry.backend == "profile_directory" and locator:
        stable_id = stable_id_for(entry.provider_id, locator)
    else:
        stable_id = stable_id_for_value(entry.provider_id, locator)
    return AccountRef(
        provider_id=entry.provider_id,
        stable_id=stable_id,
        display_name=entry.display_name,
        source_kind="shared",
        source_path=canonical_path(locator) if entry.backend == "profile_directory" else "",
        enabled=True,
        metadata={
            "origin": "shared",
            "shared_account_id": entry.account_id,
            "identity_locator": locator,
            "execution_backend": entry.backend,
            "canonical_label": entry.display_name,
            # The plane owns the short badge as much as it owns the identity.
            # Dropping it here made the consumer invent an ordinal out of the
            # display name ("CL1", "CL2"), which is an account number the plane
            # never assigned and that changes when the roster is reordered.
            "compact_label": entry.compact_label,
        },
    )


def is_shared(account: AccountRef) -> bool:
    return (account.metadata or {}).get("origin") == "shared"


def current_windows_user() -> str:
    """The Windows user this process runs as, lowercased."""
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip().lower()


def local_read_is_context_safe(account: AccountRef) -> bool:
    """Whether the LOCAL reader may speak for this account.

    A local provider reader opens the credential store of whoever runs this
    process. That is honest for a profile-directory account, which is a path
    this application opens itself, and for a shared account that already IS the
    current user. It is a lie for a shared account owned by a different Windows
    user: the reading would come from the operator's own Antigravity session and
    be filed under another account's name, which is one provider identity
    masquerading as two.

    An owner that cannot be determined is refused, because "unprovable" must
    never resolve to "probably fine".
    """
    meta = account.metadata or {}
    if not is_shared(account):
        return True
    backend = str(meta.get("execution_backend") or "").strip().lower()
    if backend == "profile_directory":
        return True
    owner = str(meta.get("windows_user") or "").strip().lower()
    if not owner:
        return False
    return owner == current_windows_user()


def _identity_from_plane(payload: dict) -> dict:
    """The plane's own provider identity claim, normalized for a snapshot.

    The plane reads the credential store of the account's OWN Windows user, so
    this is the authoritative answer for a shared account. Absent, unverified or
    empty means the plane proved nothing, and the caller keeps an unresolved
    identity rather than borrowing the current user's.
    """
    from fastprompter.core.usage_limits import identity as _identity
    # The plane publishes it under `credential`, beside the other facts it read
    # from that account's own credential store. Top level is accepted too so a
    # flatter plane revision stays readable.
    credential = payload.get("credential")
    raw = credential.get("provider_identity") if isinstance(credential, dict) else None
    if not isinstance(raw, dict):
        raw = payload.get("provider_identity")
    if not isinstance(raw, dict):
        return {}
    fingerprint = raw.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return {}
    if raw.get("verified") is not True:
        return {}
    return _identity.describe(fingerprint.strip().lower(),
                              str(raw.get("source") or "sai-accounts"))


def _windows_from_plane(windows: object, source: str) -> list:
    """Translate the plane's window list into this application's windows.

    The two vocabularies are kept apart deliberately: the plane speaks in
    ``remaining_fraction``, this application in percent used. The conversion is
    one function so the two dialects cannot drift into two parsers.
    """
    from fastprompter.core.usage_limits.model import UsageWindow
    out = []
    if not isinstance(windows, list):
        return out
    aliases = {"5h": "five_hour", "weekly": "weekly", "weekly_per_model": "weekly",
               "monthly": "monthly"}
    durations = {"five_hour": 300, "weekly": 10080, "monthly": 43200}
    for item in windows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("window") or item.get("pool") or "").strip().lower()
        key = aliases.get(name, name or "five_hour")
        fraction = item.get("remaining_fraction")
        used = None
        if isinstance(fraction, (int, float)):
            used = max(0.0, min(100.0, (1.0 - float(fraction)) * 100.0))
        resets_at = item.get("reset_time")
        epoch = None
        if isinstance(resets_at, str) and resets_at:
            try:
                import datetime as _dt
                epoch = _dt.datetime.fromisoformat(
                    resets_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, OSError):
                epoch = None
        out.append(UsageWindow(
            key=key, duration_minutes=durations.get(key), available=True,
            used_percent=used,
            remaining_percent=None if used is None else 100.0 - used,
            resets_at_epoch=epoch, source=source,
        ))
    return out


def probe_shared(account: AccountRef, deadline: float,
                 local_probe: callable | None = None) -> UsageSnapshot:
    """Read one shared account through the plane.

    Three outcomes, and the difference between them matters:

    * the plane answered with windows — those are the reading;
    * the plane answered that it does not read this provider, or that the
      account is offline or unauthenticated — an honest statement about one
      account, parsed and reported as itself;
    * the plane did not answer at all — a shared source that went away. The
      account is reported unavailable with that reason. It is NEVER quietly
      re-read through a path that belongs to some other account, which would
      show the wrong numbers under the right name.
    """
    from fastprompter.core.usage_limits.model import AUTH_REQUIRED, OK, UNAVAILABLE
    account_id = str((account.metadata or {}).get("shared_account_id") or "")
    if not account_id:
        return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                             error_code="shared_identity_missing",
                             error_summary="shared account has no canonical id")
    result = _run(["usage", account_id], deadline)
    # Read the payload BEFORE the exit code. A plane that cannot read an
    # account answers with a typed envelope AND a nonzero exit — that is a
    # known state about one account, not an outage. Only an absent payload
    # means the plane itself did not answer.
    payload = _json_object(result.get("stdout", ""))
    if not payload:
        return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                             error_code="shared_source_offline",
                             error_summary="SAI Accounts did not answer")

    identity = _identity_from_plane(payload)
    windows = _windows_from_plane(payload.get("windows"), "sai-accounts-usage")
    if windows:
        return UsageSnapshot(account=account, status=OK, windows=windows,
                             fetched_at=time.time(),
                             provider_metadata={
                                 "source_session": "sai-accounts",
                                 "observed_at": time.time(),
                                 **identity,
                             })

    auth_state = str(payload.get("auth_state") or "")
    if auth_state == "AUTH_REQUIRED":
        return UsageSnapshot(account=account, status=AUTH_REQUIRED, windows=[],
                             error_code="auth_required",
                             error_summary="not authenticated",
                             provider_metadata=identity)

    skipped = str(payload.get("skipped_reason") or "")
    context_state = str(payload.get("context_state") or "")
    if skipped == "provider_does_not_support_quota" and local_probe is not None:
        # The plane has no broker for this provider and says so. It makes no
        # claim about the reading, so the account keeps the reader it always
        # had — this is the standalone path, not a degraded one.
        #
        # But only when that reader can actually speak for THIS account. A
        # reader running under the current user cannot answer for an account
        # owned by another Windows user, and returning its numbers anyway is
        # how one provider identity gets filed under two account names.
        if not local_read_is_context_safe(account):
            return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                                 error_code="shared_context_unsafe",
                                 error_summary=(
                                     "this account runs as another Windows user; "
                                     "reading it locally would report the current "
                                     "user's Antigravity session"),
                                 provider_metadata=identity)
        try:
            return local_probe(account, deadline)
        except Exception:
            return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                                 error_code="shared_local_read_failed",
                                 error_summary="local read failed for a shared account",
                                 provider_metadata=identity)
    if skipped or context_state in ("OFFLINE", "UNKNOWN"):
        summary = ("account context is offline" if context_state == "OFFLINE"
                   else f"SAI Accounts: {skipped or 'no reading'}")
        return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                             error_code="shared_source_stale",
                             error_summary=summary)
    return UsageSnapshot(account=account, status=UNAVAILABLE, windows=[],
                         error_code="shared_source_empty",
                         error_summary="SAI Accounts returned no usable reading")
