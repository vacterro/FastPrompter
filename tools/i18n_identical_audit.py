"""Classify i18n keys whose English value must stay identical in every locale.

The release gate needs a defensible answer to one question: is a locale value
that equals the English one a genuine untranslated string, or is this key
inherently language-neutral (a shortcut chord, a file glob, a brand name, a
unit)? Guessing wrong either way is a bug -- too strict and the gate blocks
correct packs, too loose and it blesses 17k English fallbacks.

The rule set below is deliberately explicit. `classify_key` returns "identical"
only when the value matches a language-neutral pattern; anything it does not
recognise is treated as translatable, which is the safe direction: a real
translation being demanded is a 5-second fix, an English fallback passing the
release gate ships English to a German user forever.

Run: python tools/i18n_identical_audit.py [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / ".saipen" / "saitranslate" / "locales"

# --- language-neutral vocabulary -------------------------------------------
# Tokens that are correct verbatim in every shipped language. Each entry is
# either a plain word or a regular expression; anything matching ALL of them is
# neutral. Keeping this short and explicit is deliberate -- an over-broad entry
# here is an invisible hole in the release gate.
BRAND_TOKENS = {
    "wav", "mp3", "ogg", "flac", "url", "urls", "json", "yaml", "yml", "toml",
    "csv", "html", "css", "xml", "log", "sh", "bat", "ps1", "sql", "py", "js",
    "ts", "ini", "cfg", "md", "markdown", "txt", "zip", "utf-8", "utf8",
    "rgb", "rgba", "hsla", "http", "https", "api", "id", "uuid", "cpu", "gpu",
    "ok", "rgb", "stp", "gpt", "sse", "tls", "ssl", "png", "jpg", "jpeg",
    "webp", "gif", "svg", "ico", "exe", "dll", "ini", "rtf", "pdf", "doc",
}

# Whole values that are, by construction, not language.
_NEUTRAL_EXACT = {
    "{}", "{} — {}", "\U0001f4c1{}",
}

_NEUTRAL_PATTERNS = (
    re.compile(r"^\{[^}]*\}$"),                        # "{project}"
    re.compile(r"^[+\-]?\d+[a-z]{1,3}$"),              # "+10m", "-10m"
    re.compile(r"^[\d\s:/.,–—-]+$"),                   # "00:00", "1–10"
    re.compile(r"^[A-Za-z0-9+_]+\t[A-Za-z0-9+_]+$"),   # "Open\tEnter" shortcut rows
    re.compile(r".*\(\*[\w.*? ]+\)$"),                 # "Text Files (*.txt)" filters
    re.compile(r"^[A-Za-z0-9_]+(\\[A-Za-z0-9_.\- ]+)+$"),  # Documents\.fastprompter\
    re.compile(r"^[a-z0-9_-]+\.[a-z0-9_]+$"),          # "preset.json"
)

# Values that are the same token in every language, so any change to them is
# wrong. Kept deliberately short: a letter, a colour model, a file format, a URL
# scheme, and two names the user knows in English.
#
# What is NOT here, and why it used to be. OK, Markdown, SiloKanban and
# SiloTable are ordinary words or feature names that a language may legitimately
# render -- Arabic "OK" as نعم, Japanese "Markdown" as マークダウン, Swedish
# "Skift" as Skift. A verbatim rule over them rejects correct translations, which
# is how a gate teaches people to ignore it. Their real defect was never the
# spelling: German shipped "Abschlag" for Markdown, which is a price discount.
# That is a mistranslation, caught by review, not by a regex -- and it is fixed.
#
# The list that WAS here, and what each entry broke in a shipped pack:
#   B I U S H L C R   ru put Ж on Bold and К on Italic; id "I" -> SAYA (a
#                     Malay word), vi -> TÔI (you), sv -> jeg (I), fi -> minä
#                     (me). A single letter is not a word to translate.
#   RGB              5 packs -> "Colours" / "Värvid" / "Цвета". A colour MODEL.
#   Markdown         14 packs -> "price discount"; ja/ko/th have it right.
#   OK               ar -> نعم, which is correct, not a defect.
_CURATED_NEUTRAL = {
    # typographic toolbar glyphs (main.py formatting buttons)
    "B", "I", "U", "S", "H", "L", "C", "R",
    # format and scheme tokens
    "RGB", "WAV", "URL",
    # the product's own name and its brand
    "Problip", "FastPrompter",
    # Tab-order and snippet-row arrows. Not words: the sentences that mention
    # them ("Use ▲ ▼ to change the order of the tabs") carry their own
    # translation, so the arrow is a pictogram inside an already-translated
    # string rather than a label standing on its own.
    "▲", "▼",
    # Runtime-composed skeletons for the usage-limit reset rows. `name` and
    # `res_word` arrive already translated and are substituted at render
    # time, so the bracket-and-placeholder frame is the same in every
    # language and translating the frame would only break the substitution.
    # These four were passing the gate before this entry existed, but through
    # `has_word_to_translate` returning False -- the whole value reduces to
    # punctuation once the placeholders are stripped. That is an emergent
    # excuse nobody ever stated, which is what left 4 keys x 32 locales =
    # 128 values byte-identical everywhere with no verdict anywhere.
    "[{n} {res_word}]", "{name} ({n} {res_word})",
}


def is_curated_neutral(value: str) -> bool:
    """True for a value that must be reproduced VERBATIM, or not translated.

    Narrower than `classify_key` on purpose: that function also returns
    "neutral" for whole patterns, some of which are looser than they look --
    ``All Files (*.*)`` matches the file-filter pattern even though "All Files"
    is ordinary prose. Only the explicit list above is safe to enforce as a
    "do not touch" rule, and every entry in it has been shipped broken at least
    once.
    """
    return value.strip() in _CURATED_NEUTRAL


# Deliberately NOT neutral, and why. These were on this list once, and every
# one of them goes straight to a visible label:
#   ui/audio_hub_pages.py:1790-1795   tr('STOPPED') tr('RUNNING') tr('PAUSED')
#   ui/problip_settings.py:384        tr('STARTING')
#   main.py:13470, ui/settings_builder.py:697   tr('MUTED' if muted else ...)
# They were English in 29-32 of the 33 packs. A state badge the user reads is UI
# text; an untranslated one says "RUNNING" to a German user for the rest of the
# app's life. Named here so the removal cannot later look like an oversight.


def _has_letters(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value))


def _symbols_only(value: str) -> bool:
    """Punctuation, emoji and whitespace with no letter or digit anywhere."""
    return not any(ch.isalnum() for ch in value)


def classify_key(value: str) -> str:
    """Return 'neutral' when the English value needs no translation."""
    if value in _NEUTRAL_EXACT:
        return "neutral"
    stripped = value.strip()
    if not _has_letters(stripped):
        return "neutral"
    if _symbols_only(stripped):
        return "neutral"
    if stripped in _CURATED_NEUTRAL:
        return "neutral"
    low = stripped.lower()
    if low in BRAND_TOKENS:
        return "neutral"
    for pattern in _NEUTRAL_PATTERNS:
        if pattern.match(stripped):
            return "neutral"
    return "translatable"


def load_pack(lang: str) -> dict:
    path = LOCALES_DIR / f"{lang}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def audit() -> dict:
    en = load_pack("en")["translations"]
    neutral = {k for k, v in en.items() if classify_key(v) == "neutral"}
    langs = sorted(
        p.stem for p in LOCALES_DIR.glob("*.json") if p.stem != "en"
    )
    report = {"neutral_keys": sorted(neutral), "locales": {}}
    for lang in langs:
        pack = load_pack(lang)["translations"]
        missing = sorted(k for k in en if k not in pack)
        identical = sorted(
            k for k, v in pack.items()
            if k in en and v == en[k] and k not in neutral
        )
        report["locales"][lang] = {
            "total_keys": len(pack),
            "missing": len(missing),
            "missing_keys": missing,
            "untranslated": len(identical),
            "untranslated_keys": identical,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the full report as JSON")
    args = parser.parse_args()

    report = audit()
    total_missing = sum(v["missing"] for v in report["locales"].values())
    total_untranslated = sum(v["untranslated"] for v in report["locales"].values())

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    print(f"language-neutral EN keys : {len(report['neutral_keys'])}")
    print(f"locales audited          : {len(report['locales'])}")
    print(f"missing keys total       : {total_missing}")
    print(f"English fallbacks total  : {total_untranslated}")
    print()
    for lang, data in sorted(
        report["locales"].items(), key=lambda kv: -kv[1]["untranslated"]
    ):
        print(
            f"  {lang:<4} keys={data['total_keys']:<5}"
            f" missing={data['missing']:<4} english={data['untranslated']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
