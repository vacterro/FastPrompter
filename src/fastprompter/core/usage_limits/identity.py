"""Provider identity — the fact that stops one account wearing another's quota.

Two configured slots are not two capacity pools. ``Antigravity 1`` and
``Antigravity 2`` may be two Windows users, two config directories, or two
labels on ONE Google account, and only the provider can tell those apart.

The rules this module owns, once, so no caller re-derives them:

* **Identity comes from authenticated provider metadata, never from usage.**
  Equal quota is not equal identity: two distinct accounts legitimately both
  read 100%. Unequal quota does not prove distinct identity either.
* **An unproven identity is never a merge.** A fingerprint is either present and
  verified, or the account keeps a private cache entry of its own. "I don't
  know who this is" must never collapse into "therefore it's the same as
  someone I do know".
* **A fingerprint identifies an ACCOUNT, not a token.** It must survive token
  rotation, reconnect and restart, so token bytes are never the input.
* **Configured slots and unique identities are different counts.** The first is
  how many execution contexts exist; the second is how much quota actually
  exists. Capacity is the second.

ponytail: fingerprints are 16 hex chars of SHA-256 over the provider's own
subject id. There is no key registry and no rotation scheme; if a provider ever
needs to rotate its subject encoding, bump the version prefix then.
"""

from __future__ import annotations

UNRESOLVED = ""

# Metadata keys. Names are deliberately free of "token"/"credential" substrings:
# SAI Accounts' secret-shaped payload guard rejects any key containing them, and
# a fingerprint is the opposite of a secret.
KEY_FINGERPRINT = "provider_identity_fingerprint"
KEY_SOURCE = "identity_source"
KEY_VERIFIED = "identity_verified"
KEY_SAME_AS = "shares_identity_with"
KEY_CANONICAL = "identity_canonical_account"


def fingerprint_of(meta: dict | None) -> str:
    """The verified provider fingerprint in ``meta``, or ``""``.

    Only a verified fingerprint counts. An unverified value is treated as no
    answer at all, because the whole point of the field is that it was proved.
    """
    if not isinstance(meta, dict):
        return UNRESOLVED
    value = meta.get(KEY_FINGERPRINT)
    if not isinstance(value, str) or not value.strip():
        return UNRESOLVED
    if meta.get(KEY_VERIFIED) is not True:
        return UNRESOLVED
    return value.strip().lower()


def describe(fingerprint: str, source: str = "") -> dict:
    """A metadata fragment proving one provider identity."""
    return {
        KEY_FINGERPRINT: fingerprint,
        KEY_SOURCE: source,
        KEY_VERIFIED: True,
    }


def identity_changed(old_meta: dict | None, new_meta: dict | None) -> bool:
    """True when an account's provider identity provably moved.

    Both sides must be proven. An unresolved reading never counts as a switch:
    a credential that briefly fails to decrypt would otherwise look exactly
    like a different human signing in, and would throw away a good cache.
    """
    old_fp = fingerprint_of(old_meta)
    new_fp = fingerprint_of(new_meta)
    return bool(old_fp) and bool(new_fp) and old_fp != new_fp


def group_by_identity(entries) -> dict:
    """``fingerprint -> [entry, ...]`` for every entry with a proven identity.

    ``entries`` are ``(cache_key, metadata)`` pairs. Entries without a proven
    identity are omitted entirely — they appear in no group, so they can never
    be mistaken for members of one.
    """
    groups: dict[str, list] = {}
    for cache_key, meta in entries:
        fp = fingerprint_of(meta)
        if fp:
            groups.setdefault(fp, []).append(cache_key)
    return groups


def unique_identity_count(entries) -> int:
    """How many DISTINCT provider identities these entries represent.

    This is the number that capacity must be computed from. Unproven entries
    each count once: an unknown identity is still one unknown quota pool, and
    guessing it is shared would silently delete capacity the operator has.
    """
    proven = set()
    unresolved = 0
    for _cache_key, meta in entries:
        fp = fingerprint_of(meta)
        if fp:
            proven.add(fp)
        else:
            unresolved += 1
    return len(proven) + unresolved


def duplicate_report(entries) -> dict:
    """``cache_key -> canonical cache key`` for every proven shared identity.

    The first entry in roster order is the canonical one; the rest point at it.
    Only identities proven equal are linked, so a duplicate never appears by
    accident and never because two accounts happen to read the same percentage.
    """
    report: dict[str, str] = {}
    for _fp, members in group_by_identity(entries).items():
        if len(members) < 2:
            continue
        canonical = members[0]
        for member in members[1:]:
            report[member] = canonical
    return report


def cache_scope_key(provider_id: str, account_key: str, meta: dict | None) -> str:
    """The logical identity of one cached reading.

    Scoped by account ALWAYS, so two slots can never share a cache object even
    when their fingerprints match. The fingerprint rides along so that a switch
    of provider account produces a different scope and the previous entry can
    never be served for the new identity.

    An unresolved fingerprint still gets its own private scope keyed to the
    account — never merged, never dropped.
    """
    fp = fingerprint_of(meta) or UNRESOLVED
    return f"{provider_id}|{account_key}|{fp}"
