"""Regenerate src/fastprompter/core/typecheck_ui_vocab.py.

PERF-006: the runtime ``ui_vocabulary()`` used to import EVERY shipped
i18n language module on first typo-check use (defeating localization
laziness; ~10 MiB retained RSS). These translations are static build
inputs, so the vocabulary is generated ahead of time instead.

Run from the repo root:  python tools/gen_typecheck_ui_vocab.py

The output module holds a single frozenset literal of every Latin-script
word extracted from all shipped language packs under the SAME extraction
rules the runtime fallback uses ([A-Za-z]{2,} over translation values,
ASCII-alpha only, lowercased).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "src" / "fastprompter" / "core" / "i18n"
OUT = ROOT / "src" / "fastprompter" / "core" / "typecheck_ui_vocab.py"

_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def extract_words() -> set[str]:
    """Every Latin word from every shipped TRANSLATIONS dict.

    The language list comes from ``i18n.available_codes()`` itself so the
    generated vocabulary can never drift from what the runtime fallback
    would extract (codes are not all two letters: DED, EST, FRA, ...)."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    try:
        from fastprompter.core import i18n as _i18n
        codes = [c for c in _i18n.available_codes()]
    finally:
        sys.path.pop(0)
    words: set[str] = set()
    for code in codes:
        if code == "EN":
            continue
        path = I18N_DIR / f"{code.lower()}.py"
        namespace: dict[str, object] = {}
        try:
            exec(path.read_text(encoding="utf-8"), namespace)
        except Exception as exc:
            raise SystemExit(f"cannot load {path}: {exc}")
        translations = namespace.get("TRANSLATIONS")
        if not isinstance(translations, dict):
            continue
        for value in translations.values():
            if not isinstance(value, str):
                continue
            for m in _WORD_RE.finditer(value):
                w = m.group(0).lower()
                if w.isascii() and w.isalpha():
                    words.add(w)
    return words


def render(words: set[str]) -> str:
    lines = [
        '"""GENERATED — do not edit by hand.',
        "",
        "Shipped-UI Latin vocabulary for the typecheck dictionary,",
        "extracted from every fastprompter.core.i18n language pack.",
        "Regenerate with:  python tools/gen_typecheck_ui_vocab.py",
        "",
        'Source contract: tools/gen_typecheck_ui_vocab.py::extract_words',
        '"""',
        "",
        "WORDS = frozenset((",
    ]
    for w in sorted(words):
        lines.append(f"    {w!r},")
    lines.append("))")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    words = extract_words()
    OUT.write_text(render(words), encoding="utf-8")
    print(f"wrote {len(words)} words -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
