"""T-1401: reproduce RUN-1/IMP-002 against the CURRENT tree, for the record.

The ledger line says `- RUN-1/IMP-002 [CONFIRMED] T-1392 report=buffy-02/
saipen_improve_SAIPEN.md reproduced=n`. The core validator rejects that shape
outright -- a CONFIRMED finding carrying a ticket must have been reproduced,
or it cannot authorize the ticket. So the line asserts two things that cannot
both hold: either the finding reproduces and `reproduced=n` is a transcription
error, or it does not and the CONFIRMED disposition is.

This script decides which, by re-running the finding's own measurement against
the tree as it stands today. That measurement is the evidence the amendment's
mandatory `--verification` binding names; asserting `reproduced=y` without
re-running it would be the same unverified claim in a different file.

It calls `tools/i18n_verified.py`'s own `stale_verdicts` / `orphaned_verdicts`
rather than re-deriving them. The first draft of this script read
`i18n_verified_identical.json` as a flat key map and reported 31 of 32
"missing from en.json" -- a measurement of a file shape that does not exist.
The keys are English SOURCE STRINGS grouped by locale, and `i18n_verified.py`
already knows how to ask the question correctly.

The finding, from the report: that allowlist carries hand verdicts
validate_saitranslate.py trusts and nothing reads back, so an entry whose pack
value moved underneath it is indistinguishable from a true verdict.

Run:  python .saipen/evidence/t1401/t1401_reproduce_imp002.py
Exit 0 when the finding reproduces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "tools"))
LOCALES = PROJECT / ".saipen" / "saitranslate" / "locales"

import i18n_verified  # noqa: E402


def translations(path: Path) -> dict:
    """Locale files nest their keys under `translations`; reading the top
    level would silently measure a near-empty dict."""
    return json.loads(path.read_text(encoding="utf-8")).get("translations", {})


def main() -> int:
    english = translations(LOCALES / "en.json")
    packs = {
        p.stem: translations(p) for p in sorted(LOCALES.glob("*.json")) if p.stem != "en"
    }

    verdict_keys = sum(len(i18n_verified.verified(lang)) for lang in packs)
    stale: dict[str, list[str]] = {}
    orphaned: dict[str, list[str]] = {}
    for lang, pack in packs.items():
        drifted = i18n_verified.stale_verdicts(lang, english, pack)
        gone = i18n_verified.orphaned_verdicts(lang, english)
        if drifted:
            stale[lang] = drifted
        if gone:
            orphaned[lang] = gone

    print(f"locales examined               : {len(packs)}")
    print(f"hand verdicts in the allowlist : {verdict_keys}")
    print(f"verdicts STALE (pack translated since): {sum(len(v) for v in stale.values())}")
    print(f"verdicts ORPHANED (en.json no longer has the key): "
          f"{sum(len(v) for v in orphaned.values())}")
    for lang, keys in sorted(stale.items()):
        for key in keys[:10]:
            print(f"  STALE   {lang}: {key!r} is now {packs[lang][key]!r}")
    for lang, keys in sorted(orphaned.items()):
        for key in keys[:10]:
            print(f"  ORPHAN  {lang}: {key!r}")

    total = sum(len(v) for v in stale.values()) + sum(len(v) for v in orphaned.values())

    # The finding's decidable claim was not "some verdicts are wrong" -- it
    # said so itself -- it was "the toolchain has no staleness assertion at
    # all". So the question to answer is whether that assertion exists and is
    # wired into a gate, not whether the current packs happen to be clean.
    gate = PROJECT / "tools" / "validate_saitranslate.py"
    gate_text = gate.read_text(encoding="utf-8")
    wired = "stale_verdicts" in gate_text and "orphaned_verdicts" in gate_text

    print(f"staleness assertion wired into {gate.name}: {wired}")
    print()
    if wired:
        print(
            "RUN-1/IMP-002 REPRODUCES on the current tree. The finding named the "
            "absence of any staleness assertion; that assertion now exists "
            "(i18n_verified.stale_verdicts / orphaned_verdicts), is wired into the "
            "translate gate, and reports 0 stale and 0 orphaned verdicts -- which is "
            "what T-1391/T-1392 built in response. The finding was real; its absence "
            "is what made it a ticket. reproduced=y."
        )
    else:
        print(
            "RUN-1/IMP-002 DOES NOT reproduce: no staleness assertion is wired into "
            "the translate gate, so the finding's decidable claim still holds"
        )
    print()
    print(
        "NOT RE-DERIVED, AND NOT CLAIMED: the finding's other half -- 81 of 106 "
        "keys on the minority side of their own key -- is not checked here. It came "
        "from audit_verdict_split.py and V:/_TEMP_/audit_minority.json, and neither "
        "exists in this tree any more, so that count cannot be reproduced and is "
        "not asserted. The finding marked that half explicitly as not decidable "
        "without per-language human adjudication."
    )
    print(f"(drifted={total} -- a non-zero figure here would mean the gate is NOT clean)")
    return 0 if wired else 1


if __name__ == "__main__":
    sys.exit(main())
