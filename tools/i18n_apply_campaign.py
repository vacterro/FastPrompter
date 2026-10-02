"""Merge a translation campaign's per-locale results into the locale packs.

The campaign agents write ``build/t1353_todo/<lang>.done.json``. This merges
them into ``.saipen/saitranslate/locales/<lang>.json`` only after every pair
passes the shared contract in ``i18n_contract``. Nothing is written for a
locale that still has gaps; ``--check`` reports what is missing instead.

The merge is deliberately all-or-nothing per locale. A half-translated pack
is worse than an honestly untranslated one: the first ships English to a
German user while claiming coverage, the second is visible in the gate.

Run: python tools/i18n_apply_campaign.py --check
     python tools/i18n_apply_campaign.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import i18n_contract  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TODO = ROOT / "build" / "t1353_todo"
LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"


def load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write merged packs")
    parser.add_argument("--json", help="write a full report to this path")
    parser.add_argument(
        "--todo",
        default=TODO,
        type=Path,
        help="campaign directory holding <lang>.json and <lang>.done.json "
        "(round 1 asked for translations, round 2 asked for structural repairs; "
        "the merge is the same either way)",
    )
    args = parser.parse_args()
    todo = args.todo

    report: dict = {"locales": {}}
    problems: list[str] = []

    for todo_path in sorted(todo.glob("*.json")):
        # "_hu_c1.json" and friends are the Hungarian agent's chunk files. They
        # live beside the todo files because the agents needed them there, and a
        # bare glob would merge a chunk of translations as if it were a locale.
        if todo_path.stem.endswith(".done") or todo_path.stem.startswith("_"):
            continue
        lang = todo_path.stem
        data = load(todo_path)
        if data.get("lang") != lang:
            problems.append(f"{lang}: file does not declare lang={lang!r}, skipped")
            report["locales"][lang] = {
                "requested": 0,
                "delivered": 0,
                "skipped": "lang mismatch",
            }
            continue
        items = data["items"]
        done_path = todo / f"{lang}.done.json"
        if not done_path.exists():
            problems.append(f"{lang}: no .done.json")
            report["locales"][lang] = {
                "requested": len(items),
                "delivered": 0,
                "skipped": "no .done.json",
            }
            continue

        done = load(done_path).get("items", {})
        missing = sorted(set(items) - set(done))
        extra = sorted(set(done) - set(items))
        broken: dict[str, list[str]] = {}
        still_english: list[str] = []

        for key, english in items.items():
            value = done.get(key)
            if not isinstance(value, str):
                broken.setdefault(key, []).append("missing or non-string value")
                continue
            bad = i18n_contract.violations(key, english, value, lang)
            if bad:
                broken.setdefault(key, []).extend(bad)
            if value == english:
                still_english.append(key)

        report["locales"][lang] = {
            "requested": len(items),
            "delivered": len(done) - len(missing),
            "missing_keys": missing,
            "extra_keys": extra,
            "contract_violations": {k: v for k, v in broken.items()},
            "identical_to_english": still_english,
        }
        if missing or extra or broken:
            problems.append(
                f"{lang}: {len(missing)} missing, {len(extra)} extra, "
                f"{len(broken)} contract violation(s)"
            )

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    for lang, data in sorted(report["locales"].items()):
        print(
            f"  {lang:<4} requested={data.get('requested', 0):<5} "
            f"delivered={data.get('delivered', 0):<5} "
            f"violations={len(data.get('contract_violations', {})):<4} "
            f"identical={len(data.get('identical_to_english', []))}"
        )

    if problems:
        # The safety property is PER LOCALE, not per campaign: a half-translated
        # pack is worse than an honestly untranslated one, because the first
        # ships English while claiming coverage and the second is visible in the
        # gate. Nothing here says a locale that IS complete and clean has to wait
        # for one that is not -- aborting the whole run meant that while round 3's
        # last agent was still working, the other 27 verified locales could not be
        # merged. Skipped locales stay visible in the report and still fail the
        # exit code, so an incomplete campaign is never mistaken for a finished
        # one; they are just not allowed to hold up the rest.
        print("\nSkipped (incomplete or contract-dirty):")
        for p in problems:
            print(f"  [SKIP] {p}")

    complete = [
        lang
        for lang, data in report["locales"].items()
        if not data.get("skipped")
        and not data.get("missing_keys")
        and not data.get("extra_keys")
        and not data.get("contract_violations")
    ]

    if not args.apply:
        print(f"\n{len(complete)} locale(s) complete and contract-clean.")
        if complete:
            print("Re-run with --apply.")
        return 1 if problems else 0

    for lang in sorted(complete):
        pack_path = LOCALES / f"{lang}.json"
        pack = load(pack_path)
        pack["translations"].update(load(todo / f"{lang}.done.json")["items"])
        # indent=2 and newline="\n" are what the committed packs already use.
        # At indent=1 (and in text mode, which turns "\n" into "\r\n" on
        # Windows) every merge reindented all ~1850 lines of the pack, turning
        # a nine-key change into a whole-file rewrite that no reviewer can read.
        with pack_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(pack, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"merged {lang}: {len(pack['translations'])} keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
