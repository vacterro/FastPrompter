"""Rewrite `coverage_pct` and `_meta.missing_keys` from the packs themselves.

Both fields were written by hand as the campaign progressed and were stale the
moment round 1 landed: every pack still claimed 57-67% while its keys said
99.4-100.0. A stale coverage number is worse than a missing one, because it is
the number a release checklist trusts.

The measurement is `i18n_verified.blank()`, the same call the release gate
makes, so the number written here and the number the gate checks can never
disagree. A value counts as covered when it is non-empty and either differs
from the English master or is reviewed-correct for that locale.

Run:  python tools/i18n_recompute_coverage.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import i18n_verified  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report drift without writing")
    args = ap.parse_args()

    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    en_master = en["translations"]
    canonical = list(en_master)

    drift = []
    for path in sorted(LOCALES.glob("*.json")):
        lang = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        trans = data["translations"]

        missing = 0
        for key in canonical:
            value = trans.get(key)
            if not isinstance(value, str) or not value.strip():
                missing += 1
                continue
            if lang == "en":
                continue
            if value == en_master[key] and not i18n_verified.blank(
                lang, value, key=key
            ):
                missing += 1

        cov = round(100.0 * (len(canonical) - missing) / len(canonical), 1)
        old_cov = data.get("coverage_pct")
        old_missing = data.get("_meta", {}).get("missing_keys")
        if old_cov != cov or old_missing != missing:
            drift.append(f"{lang}: coverage {old_cov} -> {cov}, "
                         f"missing_keys {old_missing} -> {missing}")
            if not args.check:
                data["coverage_pct"] = cov
                data.setdefault("_meta", {})["missing_keys"] = missing
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="")

    for line in drift:
        print(line)
    print(f"\n{len(drift)} pack(s) {'would change' if args.check else 'rewritten'}")
    return 1 if (args.check and drift) else 0


if __name__ == "__main__":
    sys.exit(main())
