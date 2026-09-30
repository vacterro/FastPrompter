"""List the keys a locale still owes a translation, as campaign input.

The release gate decides what "untranslated" means; this only writes that
decision out in the shape `i18n_apply_campaign.py` reads, so the last gap is
repaired by the same tool and the same contract as the 18,638 before it.

Run: python tools/i18n_remaining.py --out build/t1353_r3
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


def remaining(lang: str, master: dict, pack: dict) -> list[str]:
    out = []
    for key, english in master.items():
        value = pack.get(key)
        if not isinstance(value, str) or not value.strip():
            out.append(key)
        elif value == english and not i18n_verified.blank(lang, english, key=key):
            out.append(key)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    master = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["translations"]
    total = 0
    for path in sorted(LOCALES.glob("*.json")):
        lang = path.stem
        if lang == "en":
            continue
        pack = json.loads(path.read_text(encoding="utf-8"))["translations"]
        keys = remaining(lang, master, pack)
        total += len(keys)
        if not keys:
            continue
        (args.out / f"{lang}.json").write_text(
            json.dumps(
                {
                    "lang": lang,
                    "items": {k: master[k] for k in keys},
                    "current": {k: pack.get(k) for k in keys},
                },
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"  {lang:<4} {len(keys)}")
    print(f"TOTAL {total} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
