"""Shared translation contract: what a correct locale value must preserve.

Every writer and every gate in this repository uses these rules, so a
translation accepted by the campaign cannot be rejected by the release gate
for a different reason, and a translation the gate accepts cannot break the
UI it lands in.

Everything checked here is STRUCTURE and is language-independent. Whether a
value that is still in English is nevertheless correct for its language is a
different question and lives in ``i18n_verified.py``, because French ``Date``
is a French word and Arabic ``Auto`` is not.

The classes checked below are not stylistic. Each one produces a
user-visible defect when broken:

* placeholders -- ``{text}``/``{time}``/``{state}`` are substituted by the
  header renderer and by ``str.format``; renaming one shows the user a
  literal ``{текст}`` or raises ``KeyError``.
* accelerators -- ``&&`` is Qt's escaped literal ampersand. Turning it into a
  single ``&`` makes Qt read the next letter as a mnemonic and renders
  ``Data & Appearance`` as ``Data <u>A</u>ppearance``; that is a visible
  defect and the contract rejects it. A SINGLE ``&`` is a mnemonic marker:
  where it belongs is a linguistic decision (``Save & Apply`` ->
  ``Speichern & Übernehmen`` but ``Salvesta ja rakenda``), so its loss is
  reported, never blocked.
* chord rows -- a ``TAB``-separated row is a shortcut table cell; breaking
  the tab structure destroys the column layout.
* modifier keys -- ``Ctrl``/``Alt``/``Shift``/``Win`` are printed in Latin on
  every keyboard in every country, so a translation that drops one tells the
  user to press a key the sentence no longer mentions.

The rule set deliberately does NOT try to police the non-modifier key names.
``Alt+Right`` -> ``Alt+Rechts`` is wrong, but so is ``Ctrl+Shift`` ->
``Ctrl+Mayus`` on a Spanish keyboard, where ``Mayus`` is what the keycap
actually says. Telling those apart needs a per-language key-name table, and
guessing from the glyph instead produced false positives on every locale that
does not spell a chord with ``+``. ``modifier_tokens`` therefore only checks
that the Latin modifiers survive, which is language-independent; the residual
risk is asserted explicitly by ``test_localized_key_name_is_not_checked`` in
``tests/test_i18n_contract_t1353.py``.
"""

from __future__ import annotations

import re
import string
from collections import Counter

# "{name}" and the two-brace / format-spec forms alike.
_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
# A printf conversion only when NO whitespace separates '%' from the type.
# "100% reduces it" is English prose with a percent sign, not a %r spec; the
# space is the whole difference and it is why this pattern excludes it.
_PRINTF = re.compile(
    r"%(?:\([^)]*\))?[-+#0]*[\d*]*(?:\.[\d*]+)?[hlL]?([a-zA-Z%])"
)
_HTML_ENTITY = re.compile(r"&(?:[a-zA-Z]+|#\d+|#[xX][0-9a-fA-F]+);")
# The two-character sequences "\n" and "\t" as they appear in a pack file. The
# packs hold BOTH forms for sibling keys, and the two are not interchangeable at
# runtime: Qt splits a shortcut row on a real TAB only.
_LITERAL_NL = re.compile(r"\\n")
_LITERAL_TAB = re.compile(r"\\t")
_MNEMONIC = re.compile(r"&(?![a-zA-Z]+;|#)")
_ESCAPED_AMP = re.compile(r"&&")
# A collected key that starts as one string literal and runs on into code.
_FRAGMENT = re.compile(r'^[A-Z][A-Za-z ]{1,20}"\s+(if|else|and|or|not)\s')

# Modifier keys only. These stay Latin on every keyboard in every country, so
# their survival is checkable without knowing the target language.
_MODIFIERS = ("Ctrl", "Alt", "Shift", "Win", "Super", "Meta")
# The boundary is a Latin-script letter on both sides -- ASCII plus the
# Latin-1/Latin-Extended block, which is where the Turkish dotless ı, the
# Hungarian ő and the Polish ł live. Turkish "Altta" (lower) and "Altı çizili"
# (underlined) are ordinary words, and a bare [A-Za-z] could not see that ı is
# a letter. \w was the other wrong answer: it fixed Turkish and broke CJK,
# where "Ctrlキー" and "Alt를" are how the Japanese and Korean packs write the
# same thing. Latinish is the boundary that rejects "aligned" and "Windows"
# while letting a modifier sit against a katakana or a Hangul syllable.
_LATINISH = r"A-Za-z\u00C0-\u024F"
_MODIFIER_RE = re.compile(
    r"(?<![" + _LATINISH + r"])(?:" + "|".join(_MODIFIERS) + r")(?!["
    + _LATINISH + r"])"
)


def modifier_tokens(value: str, lang: str = "en") -> Counter:
    """Count the modifier keys a value mentions, in ``lang``'s own spelling.

    Word-boundary anchored, so "Windows" never counts as Win and prose such as
    "aligned" never counts as Alt. Deliberately blind to how the chord is
    spelled -- ``Ctrl+Q``, ``Ctrl Q`` and ``按住 Ctrl 拖动`` all report one
    Ctrl, because the separator is a linguistic choice like the rest.
    """
    value = _native_keycap(value, lang)
    counts = Counter(m.group() for m in _MODIFIER_RE.finditer(value))
    for word in _PROSE_WORD.get(lang, ()):
        if not counts[word]:
            continue
        for m in _word_re(word).finditer(value):
            # Only outside a chord. "Alt+Down" is the key in every language, and in
            # Turkish "Alt çizgi" (underline) is not -- but the two differ only in
            # what follows the token, so the '+' is the whole test.
            if value[m.end() : m.end() + 1] == "+" or value[m.start() - 1 : m.start()] == "+":
                continue
            counts[word] -= 1
            if counts[word] <= 0:
                del counts[word]
    return counts


def _word_re(word: str) -> re.Pattern:
    return re.compile(
        r"(?<![" + _LATINISH + r"])" + re.escape(word) + r"(?![" + _LATINISH + r"])"
    )


# Keycaps a language actually prints, mapped to the Latin modifier they stand
# for. Scoped per language on purpose: a global map was the second wrong
# version. Swedish prints Skift on the key and Danish spells "change" the same
# way, so one global entry made 5 correct Danish phrases fail.
_KEYCAP = {
    "de": {"Strg": "Ctrl", "Umschalt": "Shift"},
    "fra": {"Maj": "Shift"},
    "it": {"Maiusc": "Shift"},
    "spa": {"Mayús": "Shift", "Mayùs": "Shift"},
    "sv": {"Skift": "Shift"},
}

# Modifier names that are also ordinary words in that language, so they count
# as a keypress only inside a chord. Every entry here was found by the gate
# rejecting a correct translation:
#   da  "Alt blev rullet tilbage, ..." (alt = all/everything)
#   no  "Alt ble tilbakestilt, ..."      (alt = all/everything)
#   tur "Alt çizgi" / "Alt klasörleri"    (alt = lower, bottom)
#
# ponytail: a language can need an entry the gate has not hit yet. The failure
# is loud -- one rejected key -- not silent, so add the word when review finds one.
_PROSE_WORD = {
    "da": ("Alt",),
    "no": ("Alt",),
    "tur": ("Alt",),
}


def _native_keycap(value: str, lang: str) -> str:
    """Rewrite ``lang``'s own keycap spellings to the Latin modifier names."""
    table = _KEYCAP.get(lang)
    if not table:
        return value
    return re.sub(
        r"(?<![" + _LATINISH + r"])(" + "|".join(table) + r")(?!["
        + _LATINISH + r"])",
        lambda m: table[m.group(1)],
        value,
    )


def _placeholder_fields(value: str) -> list[str]:
    """Field names of every ``{...}`` placeholder, in order."""
    return [m.group(1) for m in _PLACEHOLDER.finditer(value) if m.group(1) is not None]


def placeholders(value: str) -> Counter:
    return Counter(_placeholder_fields(value))


def printf_specs(value: str) -> Counter:
    return Counter(m.group(1) for m in _PRINTF.finditer(value))


def mnemonics(value: str) -> int:
    """Count real ``&`` mnemonics, ignoring ``&amp;``-style entities."""
    return len(_MNEMONIC.findall(_HTML_ENTITY.sub("", value)))


def escaped_ampersands(value: str) -> int:
    """Count Qt's ``&&`` escape, which renders one literal ampersand."""
    return len(_ESCAPED_AMP.findall(value))


def chords(value: str) -> int:
    """Column separators in a shortcut row: real TAB *and* the literal ``\\t``.

    Both forms occur in these packs -- sibling keys hold one or the other --
    and Qt splits a shortcut row on a real TAB only. Counting only the real
    character let a locale convert ``Action<TAB>Ctrl+W`` into the two-character
    ``\\t`` and pass the gate while the row rendered as one run-on sentence.
    """
    return value.count("\t") + len(_LITERAL_TAB.findall(value))


def newlines(value: str) -> int:
    """Line breaks: real newline *and* the literal ``\\n``, for the same reason."""
    return value.count("\n") + len(_LITERAL_NL.findall(value))


def is_source_fragment(value: str) -> bool:
    """True when the collector sliced a Python expression, not a UI string.

    ``tr("MUTED" if muted else "SOUND ON")`` makes the collector emit the
    whole expression as a key. At runtime ``tr`` receives the EVALUATED
    result ("MUTED" or "SOUND ON"), so the fragment key never resolves and
    translating it changes nothing a user can see.
    """
    return bool(_FRAGMENT.match(value.strip()))


def violations(
    key: str, english: str, translated: str, lang: str = "en"
) -> list[str]:
    """Every contract rule ``translated`` breaks for ``key``. Empty means valid.

    ``lang`` is the locale being written. It only affects the modifier rule, and
    only in the ways a word boundary cannot know on its own: which keycap this
    language prints, and which modifier name is also an ordinary word here.
    """
    bad: list[str] = []
    if is_source_fragment(english):
        # Nothing downstream ever looks this key up; copying it verbatim is the
        # only correct answer and the extractor bug belongs to its own ticket.
        return bad
    if not translated or not translated.strip():
        bad.append("empty value")
    if placeholders(translated) != placeholders(english):
        bad.append(
            f"placeholder set changed: {sorted(placeholders(english).items())} -> "
            f"{sorted(placeholders(translated).items())}"
        )
    if printf_specs(translated) != printf_specs(english):
        bad.append(
            f"printf spec changed: {sorted(printf_specs(english).items())} -> "
            f"{sorted(printf_specs(translated).items())}"
        )
    if escaped_ampersands(translated) != escaped_ampersands(english):
        bad.append(
            f"Qt '&&' literal ampersand count changed: "
            f"{escaped_ampersands(english)} -> {escaped_ampersands(translated)} "
            f"(a single '&' here would be read as a mnemonic by Qt)"
        )
    if chords(translated) != chords(english):
        bad.append(f"tab count changed: {chords(english)} -> {chords(translated)}")
    elif modifier_tokens(translated, lang) != modifier_tokens(english, lang):
        bad.append(
            f"shortcut modifier key count changed: "
            f"{sorted(modifier_tokens(english, lang).items())} -> "
            f"{sorted(modifier_tokens(translated, lang).items())} "
            f"(a key dropped stops telling the user what to press; a key invented "
            f"invents a shortcut)"
        )
    if newlines(translated) != newlines(english):
        bad.append(f"newline count changed: {newlines(english)} -> {newlines(translated)}")
    return bad


def format_fields(value: str) -> list[str]:
    """Field names via ``string.Formatter`` (escaped braces included)."""
    try:
        return [f[1] for f in string.Formatter().parse(value) if f[1] is not None]
    except ValueError:
        return _placeholder_fields(value)
