"""T-239: the plane contract, checked against a REAL plane.

Every other T-239 test builds its own ``Plane``. That is right for RULES — a rule
should be provable without a provider — and it is blind to the one thing a rule
cannot see: whether the installed engine still speaks the shape the parser
reads.

Rename ``credential.provider_identity``, move the ``windows`` array, or let
``usage`` answer something the parser rejects, and all forty of those tests stay
green while the live panel quietly shows nothing. That is not hypothetical: the
SAITULS quota panel was unreachable code for the same reason — six readers, no
writer, and no test failed.

This file drives the PRODUCTION path — ``read_registry``, ``probe_shared`` and
``identity`` — against the installed ``sai-accounts.exe``. It skips when the
plane is absent, so a machine without one pays nothing.

What is pinned is the contract, never the operator's configuration. One Google
login behind two slots must come back as one pool; two genuinely different
logins must come back as two. The expected numbers are derived from the RAW JSON
the plane actually returned, so this test cannot agree with a broken parser by
both being wrong in the same way.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

from fastprompter.core.usage_limits import identity as ident
from fastprompter.core.usage_limits import sai_accounts as sai

DEADLINE_S = 90.0
_CACHE: dict = {}


def _engine() -> str:
    """The plane this machine would really use, or "" when there is none."""
    override = os.environ.get(sai.ENV_OVERRIDE, "")
    if override and os.path.isfile(override):
        return override
    installed = os.path.join(sai.CANONICAL_INSTALL, "sai-accounts.exe")
    if os.path.isfile(installed):
        return installed
    return ""


def _live(argv: list[str], deadline: float) -> dict:
    exe = _engine()
    try:
        r = subprocess.run([exe] + list(argv), capture_output=True,
                           text=True, timeout=max(5.0, deadline - time.monotonic()))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "stdout": "", "error": str(exc)}
    return {"ok": r.returncode == 0, "stdout": r.stdout, "error": r.stderr}


def _probed(monkeypatch: pytest.MonkeyPatch):
    """(entries, raw_usage_payloads) for every enabled Antigravity account.

    Probing costs a real `agy /usage` per account, so the result is cached for
    the module: the three checks below read the same reading, and a quota probe
    is not free to repeat.
    """
    if "result" not in _CACHE:
        monkeypatch.setattr(sai, "TestEngine", _engine)
        raw: list[dict] = []
        run = _live

        def _record(argv, deadline):
            result = run(argv, deadline)
            if argv and argv[0] == "usage":
                try:
                    raw.append(json.loads(result.get("stdout", "")))
                except ValueError:
                    pass
            return result

        monkeypatch.setattr(sai, "TestRun", _record)
        found = sai.list_accounts({"antigravity"})
        entries = []
        for shared in found:
            ref = sai._account_ref(shared)
            snap = sai.probe_shared(ref, time.monotonic() + DEADLINE_S)
            entries.append((ref.key, snap))
        _CACHE["result"] = (entries, raw)
    return _CACHE["result"]


@pytest.fixture()
def live(monkeypatch: pytest.MonkeyPatch):
    if not _engine():
        pytest.skip("no sai-accounts plane installed on this machine")
    entries, raw = _probed(monkeypatch)
    if not entries:
        pytest.skip("the installed plane reports no Antigravity accounts")
    return entries, raw


def test_a_real_usage_reply_parses_into_a_usable_snapshot(live):
    """The parser still understands what the plane actually sends."""
    entries, raw = live
    assert len(raw) == len(entries), (
        "a usage call produced no parseable payload: the plane and the parser "
        f"disagree about the reply shape ({len(raw)} payloads, {len(entries)} accounts)")
    for (key, snap), payload in zip(entries, raw):
        assert snap.status == "OK", (
            f"{key} came back {snap.status}: {snap.error_code} {snap.error_summary!r}")
        assert snap.windows, f"{key} parsed with no quota windows"
        assert payload.get("account_id"), "the raw payload carried no account id"


def test_the_identity_read_is_the_one_the_raw_reply_carried(live):
    """The fingerprint in a snapshot is the fingerprint in the JSON.

    Pinned by string equality against the raw payload, because the alternative
    failure is silent: a parser that finds nothing is indistinguishable from an
    account whose plane proved nothing, and the first one is our bug.
    """
    entries, raw = live
    for (key, snap), payload in zip(entries, raw):
        raw_fp = ""
        cred = payload.get("credential")
        if isinstance(cred, dict):
            pid = cred.get("provider_identity")
            if isinstance(pid, dict) and pid.get("verified"):
                raw_fp = str(pid.get("fingerprint") or "")
        read = ident.fingerprint_of(snap.provider_metadata)
        assert read == (raw_fp or ident.UNRESOLVED), (
            f"{key}: snapshot says {read!r}, the plane's own reply says {raw_fp!r}")


def test_dedup_count_equals_the_distinct_verified_fingerprints(live):
    """The headline invariant, counted from the raw replies.

    Expected value comes from the JSON, not from `identity`: N slots on one
    Google login must read as 1 pool, and N different logins as N. A slot the
    plane could not identify still counts as its own unknown pool — guessing it
    was shared would silently delete capacity the operator actually has.
    """
    entries, raw = live

    verified: list[str] = []
    for payload in raw:
        cred = payload.get("credential")
        pid = cred.get("provider_identity") if isinstance(cred, dict) else None
        if isinstance(pid, dict) and pid.get("verified") and pid.get("fingerprint"):
            verified.append(str(pid["fingerprint"]))
    expected = len(set(verified)) + (len(raw) - len(verified))

    got = ident.unique_identity_count(
        [(key, snap.provider_metadata) for key, snap in entries])
    assert got == expected, (
        f"{len(raw)} account(s) carrying {len(set(verified))} distinct proven "
        f"identities were counted as {got} pools, not {expected}")


def test_slots_sharing_a_proven_identity_are_reported_as_sharing(live):
    """Two raw replies with one fingerprint must not read as two capacities."""
    entries, raw = live

    def fp_of(payload: dict) -> str:
        cred = payload.get("credential")
        pid = cred.get("provider_identity") if isinstance(cred, dict) else None
        if isinstance(pid, dict) and pid.get("verified") and pid.get("fingerprint"):
            return str(pid["fingerprint"])
        return ""

    replies = [fp_of(p) for p in raw]
    report = ident.duplicate_report(
        [(key, snap.provider_metadata) for key, snap in entries])

    seen: dict[str, str] = {}
    for key, fp in zip([k for k, _ in entries], replies):
        if not fp:
            continue
        if fp in seen:
            assert report.get(key) == seen[fp], (
                f"{key} shares a proven identity with {seen[fp]} but the report "
                f"does not say so: {report!r}")
        else:
            seen[fp] = key
            assert key not in report, (
                f"{key} is the first reply for its identity but is flagged as a "
                f"duplicate of something: {report!r}")
