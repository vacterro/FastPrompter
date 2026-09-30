"""Cross-pack consensus: find translations that disagree with every sibling.

The gap the previous rules could not see is not an English fallback -- that is
caught by `trans[k] == english`. It is a value that LOOKS translated and is
simply the wrong word: Romanian `Close` became `Aproapie` ("almost"), Czech
`Markdown` became `Snizeni` (a price discount), Arabic `SiloTable` became
`صومعة` (a mosque). Every mechanical heuristic that tried to catch this failed,
because a wrong word is as foreign to its language as a right one:

    - edit distance against the English flags `da Date -> Dato`, `cs Format: ->
      Formát:` -- ordinary one-edit translations -- and misses `Close` ->
      `Aproapie`, which is two edits away.
    - "value differs from English" flags all 32 languages equally.

What does work is asking the other 31 packs. The same key is translated into
~20 Latin-script languages, and if 18 of them say "colour" and one says
"sunbeam", that one is wrong -- no per-language dictionary needed, and no false
positive from a language that legitimately keeps an English loanword, because
the loanword is the CONSENSUS and is never the outlier.

The buckets are by script, because packs in different scripts can never be
expected to agree letter-for-letter: Japanese `テーブル` and Russian `таблица`
say the same thing as English `Table` without sharing a character. Within one
script bucket, values are compared by normalized token overlap, so inflection
and word order do not create false splits (`Couleurs`, `Colores`, `Värvid`
all cluster; `Colors` vs `Colours` is one).

Two limits worth stating plainly, because they are why this is a REPORT and not
a gate rule:

  1. It only speaks about the keys where the packs already mostly agree. A key
     every language mistranslates the same way is invisible here.
  2. Its output is evidence for a human verdict, not a verdict. The confirmed
     findings were adjudicated by hand into `i18n_verified_identical.json` or
     repaired in the packs; nothing was auto-rejected on the strength of a
     count alone.

Run:  python tools/i18n_outlier.py [--min-agree 0.6] [--out build/outliers.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / ".saipen" / "saitranslate" / "locales"

# Packs whose RTL/bidi or script-specific punctuation would corrupt naive
# token overlap. They are compared inside their own bucket regardless.
_LATINISH = re.compile(r"[A-Za-z\u00C0-\u024F]")
_DIGIT = re.compile(r"[0-9]")
_SPLIT = re.compile(r"[\s,;:()\[\]{}<>·|/\\—–\-–…!?¡¿،؛「」『』]+")


def script_of(value: str) -> str:
    """The dominant script of a value, as a coarse bucket name.

    Coarse on purpose: the point is to separate packs that CAN agree from packs
    that cannot, and a five-way split (latin / cyrillic / arabic / hebrew /
    indic / cjk / thai / greek) does that without pretending to be Unicode's
    script table.
    """
    counts: Counter[str] = Counter()
    for ch in value:
        if ch.isspace() or _DIGIT.match(ch):
            continue
        try:
            name = unicodedata.name(ch).split()[0]
        except ValueError:
            continue
        counts[name] += 1
    if not counts:
        return "none"
    top = counts.most_common(1)[0][1]
    # A handful of ASCII letters inside CJK is a loanword, not the script.
    if top < len(value) * 0.3:
        return "mixed"
    return top


def tokens(value: str) -> set[str]:
    """Comparable tokens: letters only, folded, placeholders and globs kept.

    `{}`, `%s`, `%d`, `*.*` and `&&` are structure, not meaning -- dropping
    them stops `Text files (…);;All files (*.*)` from splitting on the glob
    list, and dropping `Ctrl` from a chord stops every shortcut row from
    clustering by its key name rather than its label.
    """
    stripped = re.sub(r"\{[^{}]*\}|\{+\}|%[sd]|\*[\w.*]*|&&|&", " ", value)
    out = set()
    for raw in _SPLIT.split(stripped):
        tok = unicodedata.normalize("NFC", raw).casefold()
        tok = "".join(c for c in tok if c.isalpha())
        if not tok or len(tok) < 2:
            continue
        if _MODIFIER_WORDS and tok in _MODIFIER_WORDS:
            continue
        out.add(tok)
    return out


_MODIFIER_WORDS = {
    "ctrl", "alt", "shift", "ctrl", "strg", "umschalt", "maj", "maiusc",
    "mayus", "mayùs", "skift", "fn", "cmd", "meta", "control",
}


def similarity(a: set[str], b: set[str]) -> float:
    """Jaccard over tokens, 1.0 for two empty sets (both carry no words)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_packs() -> dict[str, dict[str, str]]:
    packs = {}
    for path in sorted(LOCALES.glob("*.json")):
        data = json.load(path.open(encoding="utf-8"))
        trans = data.get("translations") or {}
        packs[path.stem] = {k: v for k, v in trans.items() if isinstance(v, str)}
    return packs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-agree", type=float, default=0.6,
                    help="share of a key's bucket that must back the consensus")
    ap.add_argument("--out", default="build/outliers.json")
    args = ap.parse_args()

    packs = load_packs()
    keys: dict[str, dict[str, str]] = defaultdict(dict)
    for lang, trans in packs.items():
        if lang == "en":
            continue
        for key, value in trans.items():
            keys[key][lang] = value

    findings = []
    for key, by_lang in sorted(keys.items()):
        english = packs.get("en", {}).get(key)
        buckets: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
        for lang, value in by_lang.items():
            buckets[script_of(value)].append((lang, tokens(value)))

        for bucket, members in buckets.items():
            # A consensus needs more than one voice to be a consensus.
            if bucket in {"none", "mixed"} or len(members) < 3:
                continue
            agree = 0
            for _, toks in members:
                if not toks:
                    continue
                near = sum(
                    1 for _, other in members if similarity(toks, other) >= 0.5
                )
                if near / len(members) >= args.min_agree:
                    agree += 1
            if agree / len(members) < args.min_agree:
                continue
            for lang, toks in members:
                near = sum(
                    1 for _, other in members if similarity(toks, other) >= 0.5
                )
                if near / len(members) < args.min_agree:
                    findings.append({
                        "key": key,
                        "lang": lang,
                        "script": bucket,
                        "value": by_lang[lang],
                        "english": english,
                        "neighbours": near,
                        "bucket_size": len(members),
                    })

    findings.sort(key=lambda f: (f["bucket_size"], f["key"]))
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"outliers: {len(findings)} -> {out}")
    by_lang = Counter(f["lang"] for f in findings)
    print("  " + "  ".join(f"{k}:{v}" for k, v in by_lang.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
