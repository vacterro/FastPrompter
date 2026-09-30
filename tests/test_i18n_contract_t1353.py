"""The translation contract is the gate every locale pack must satisfy.

Each test below names a defect that reached a shipped locale pack before
T-1353: a renamed `{state}` placeholder, a shortcut key name localised into a
key the user's keyboard does not have, a dropped `&` mnemonic, an English
fallback counted as "translated". If the contract ever loosens, these turn
red and the gate stops catching the thing it was written for.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import i18n_contract  # noqa: E402
import i18n_verified  # noqa: E402
from validate_saitranslate import _TODO_MARKER  # noqa: E402

import fastprompter.core.i18n as i18n  # noqa: E402


def _check(key: str, english: str, translated: str, lang: str = "en") -> list[str]:
    return i18n_contract.violations(key, english, translated, lang)


class TestPlaceholders:
    def test_renamed_state_token_is_rejected(self):
        # Shipped defect: ru rendered '**__{text}__** ({time})' with the token
        # names translated, so the header renderer substituted nothing.
        bad = _check(
            '**__{text}__** ({time})',
            '**__{text}__** ({time})',
            '**__ {текст} __** ({време})',
        )
        assert any("placeholder set changed" in b for b in bad)

    def test_hindi_token_names_stay_latin(self):
        bad = _check(
            "Settings &rarr; Header Fmt: {text}, {time}, {state} "
            "(Morning/Day/Evening/Night)",
            "Settings &rarr; Header Fmt: {text}, {time}, {state} "
            "(Morning/Day/Evening/Night)",
            "सेटिंग्स {पाठ}, {समय}, {राज्य}",
        )
        assert any("placeholder set changed" in b for b in bad)

    def test_prose_around_a_preserved_token_is_fine(self):
        ok = _check(
            "How Ctrl+E rewrites the line.\n{text} is the line's own words.",
            "How Ctrl+E rewrites the line.\n{text} is the line's own words.",
            "Kuidas Ctrl+E rida ümber kirjutab.\n{text} on rea enda sõnad.",
        )
        assert ok == []

    def test_html_entity_is_not_a_placeholder(self):
        assert i18n_contract.placeholders("a &rarr; b {v}") == {"v": 1}


class TestPrintfVsProse:
    def test_english_percent_prose_is_not_a_printf_spec(self):
        # "100% reduces it" must not read as a %r conversion.
        ok = _check(
            "Rules use effective toolbar width: UI scaling above 100% reduces it.",
            "Rules use effective toolbar width: UI scaling above 100% reduces it.",
            "Reeglid kasutavad tööriistariba laiust: üle 100% skaleerimine vähendab seda.",
        )
        assert ok == []

    def test_real_printf_spec_must_survive(self):
        bad = _check(
            "Baked %d settings into DEFAULT_PROFILE.\n\nRoundtrip verified: %s",
            "Baked %d settings into DEFAULT_PROFILE.\n\nRoundtrip verified: %s",
            "Baked %d settings into DEFAULT_PROFILE.",
        )
        assert any("printf spec changed" in b for b in bad)


class TestAccelerators:
    def test_qt_escaped_ampersand_must_survive(self):
        # "Data && Appearance" renders a literal ampersand. Writing a single
        # '&' makes Qt underline the next letter: Data <u>A</u>ppearance.
        bad = _check(
            "Data && Appearance",
            "Data && Appearance",
            "Daten & Erscheinungsbild",
        )
        assert any("&&" in b for b in bad)

    def test_qt_escape_preserved_is_fine(self):
        assert _check(
            "Data && Appearance",
            "Data && Appearance",
            "Daten && Erscheinungsbild",
        ) == []

    def test_single_ampersand_may_become_the_local_conjunction(self):
        # Where a mnemonic belongs is a linguistic decision, not a contract
        # rule: German keeps one, Estonian uses "ja". Both are correct.
        assert _check(
            "Save & Apply",
            "Save & Apply",
            "Salvesta ja rakenda",
        ) == []
        assert _check(
            "Save & Apply",
            "Save & Apply",
            "Speichern & Übernehmen",
        ) == []

    def test_html_entity_does_not_count_as_mnemonic(self):
        assert i18n_contract.mnemonics("Settings &rarr; Header") == 0
        assert i18n_contract.mnemonics("&File") == 1


class TestSourceFragments:
    def test_swallowed_python_expression_is_exempt(self):
        # tr("MUTED" if muted else "SOUND ON") makes the collector emit the
        # whole expression. tr() sees the EVALUATED value at runtime, so this
        # key never resolves and must never be "translated".
        key = 'MUTED" if muted else "SOUND ON'
        assert i18n_contract.is_source_fragment(key)
        assert _check(key, key, key) == []

    def test_the_real_keys_are_not_exempt(self):
        # MUTED and SOUND ON ARE looked up, standalone. They are real UI text,
        # so the contract must judge them like any other value -- it no longer
        # flags them for being in English, because that is i18n_verified's job.
        assert not i18n_contract.is_source_fragment("MUTED")
        assert not i18n_contract.is_source_fragment("SOUND ON")
        assert _check("MUTED", "MUTED", "MUTED") == []
        assert _check("MUTED", "MUTED", "Vaikistatud") == []

    def test_empty_and_blank_are_still_rejected(self):
        # Identity moved out of the contract, emptiness did not.
        assert any("empty value" in b for b in _check("Timer", "Timer", ""))


class TestChordRows:
    def test_lost_modifier_is_rejected(self):
        # A modifier is printed in Latin on every keyboard in every country,
        # so dropping one is unambiguously a defect the gate can catch.
        bad = _check(
            "Copying with Ctrl+C also hides the window",
            "Copying with Ctrl+C also hides the window",
            "复制时使用 C 也会隐藏窗口",
        )
        assert any("modifier key count changed" in b for b in bad)

    def test_a_native_keycap_counts_as_the_modifier(self):
        # German prints Strg and Umschalt on the physical key, Spanish Mayús,
        # French Maj, Italian Maiusc, Swedish Skift. A pack that writes the
        # modifier the way its own keyboard does is RIGHT, and the first version
        # of this rule rejected 70 correct keys across those five packs.
        for lang, keycap in (("de", "Strg+Shift"), ("de", "Ctrl+Umschalt"),
                             ("spa", "Ctrl+Mayús"), ("fra", "Ctrl+Maj"),
                             ("it", "Ctrl+Maiusc"), ("sv", "Ctrl+Skift")):
            assert not [
                b
                for b in _check("Copy Path\tCtrl+Shift+C", "Copy Path\tCtrl+Shift+C",
                                "Kopieren\t" + keycap, lang)
                if "modifier key count changed" in b
            ], (lang, keycap)

    def test_a_keycap_is_scoped_to_its_own_language(self):
        # Skift is the Swedish keycap and the Danish word for "change". A global
        # alias map -- the second wrong version -- made "Skift mappe" (change
        # folder) count as a Shift keypress in a Danish pack.
        assert i18n_contract.modifier_tokens("Skift mappe", "sv") == {"Shift": 1}
        assert i18n_contract.modifier_tokens("Skift mappe", "da") == {}

    def test_a_modifier_name_that_is_also_a_word_is_not_a_key(self):
        # Danish "Alt" is "all", Norwegian "Alt" is "all", Turkish "Alt" is
        # "lower". Each of these shipped and each was rejected as a phantom
        # modifier until the rule learned the word.
        assert not [
            b for b in _check("Everything was rolled back.", "Everything was rolled back.",
                              "Alt blev rullet tilbage.", "da")
            if "modifier" in b
        ]
        assert not [
            b for b in _check("Underline", "Underline", "Alt çizgi", "tur")
            if "modifier" in b
        ]
        # The same word next to a '+' is the key in every language.
        assert i18n_contract.modifier_tokens("Karta nach unten\tAlt+Down", "de")["Alt"] == 1

    def test_a_transliterated_keycap_is_still_rejected(self):
        # Russian prints Alt on the key, not "Альт"; Estonian prints Shift, not
        # "Tõstuklahv". Transliterating the modifier is a real loss, so these
        # must keep failing.
        for bogus in ("Альт+W", "Tõstuklahv+napsautus", "Vaihto+napsautus"):
            assert any(
                "modifier key count changed" in b
                for b in _check("Alt+W…", "Alt+W…", bogus)
            ) or any(
                "modifier key count changed" in b
                for b in _check("Shift+Click", "Shift+Click", bogus)
            ), bogus

    def test_turkish_lower_reaches_no_phantom_alt(self):
        # "Altta" (lower) and "Altı çizili" (underlined) are ordinary Turkish
        # words. The first regex bounded on [A-Za-z] only, so the dotless i in
        # "Altı" -- U+0131 -- did not close the match and the gate demanded a
        # phantom Alt key in a sentence about underlines.
        assert not [
            b for b in _check("Underline ({})", "Underline ({})", "Altı çizili ({})", "tur")
            if "modifier" in b
        ]

    def test_modifier_survives_a_translated_separator(self):
        # zh has no '+' chord separator. The modifier is what matters, and it
        # is there. This is the shape that made the old chord-token rule
        # unusable: it reported Ctrl missing because there was no plus sign.
        ok = _check(
            "Ctrl+drag to move this gap. Double-click to rename.",
            "Ctrl+drag to move this gap. Double-click to rename.",
            "按住 Ctrl 拖动可移动此间隙。双击可重命名。",
        )
        assert ok == []

    def test_modifier_survives_a_moved_chord(self):
        # ko moved the chord to the front of the sentence. Also fine.
        ok = _check(
            "Add a 'Presets' page to the Ctrl+Q picker",
            "Add a 'Presets' page to the Ctrl+Q picker",
            "Ctrl+Q 선택 도구에 페이지를 추가합니다",
        )
        assert ok == []

    def test_localized_key_name_is_not_checked(self):
        # Known limitation, asserted so it cannot be forgotten silently.
        # "Alt+Rechts" is wrong on a German keyboard but "Ctrl+Mayus" is RIGHT
        # on a Spanish one, where Mayus is what the keycap says. Distinguishing
        # them needs a per-language key-name table this contract does not have.
        # The residual risk is asserted here so it cannot be forgotten silently.
        ok = _check(
            "Move card right\tAlt+Right",
            "Move card right\tAlt+Right",
            "Karte nach rechts verschieben\tAlt+Rechts",
        )
        assert ok == []

    def test_prose_containing_a_plus_is_not_a_chord(self):
        # "1-0 applies" and "Ctrl+drag" must not be read as chord cells.
        ok = _check(
            "Saves, Del removes, 1-0 applies",
            "Saves, Del removes, 1-0 applies",
            "保存，Del 删除，1-0 应用",
        )
        assert ok == []

    def test_lost_tab_separator_is_rejected(self):
        bad = _check(
            "Queue This Line\tAlt+C",
            "Queue This Line\tAlt+C",
            "Diese Zeile in die Warteschlange stellen Alt+C",
        )
        assert any("tab count changed" in b for b in bad)

    def test_english_key_name_with_translated_label_is_fine(self):
        ok = _check(
            "Move card right\tAlt+Right",
            "Move card right\tAlt+Right",
            "Karte nach rechts verschieben\tAlt+Right",
        )
        assert ok == []


class TestStructureAndContent:
    def test_newline_count_must_preserve(self):
        bad = _check(
            "a\nb",
            "a\nb",
            "a\nb\nc",
        )
        assert any("newline count changed" in b for b in bad)

    def test_empty_value_is_rejected(self):
        assert _check("Account", "Account", "  ")

    def test_value_equal_to_key_is_a_content_question(self):
        # Identity moved to i18n_verified, which knows French `Date` from
        # Arabic `Auto`. The contract must NOT flag "Account" == "Account":
        # that verdict is made per language, and it is made in one place.
        assert _check("Account", "Account", "Account") == []
        assert not i18n_verified.blank("ar", "Auto")
        assert i18n_verified.blank("fra", "Date")

    def test_clean_translation_passes(self):
        assert _check("Account", "Account", "Konto") == []

class TestWhatCountsAsUntranslated:
    """The gate's other half: is this value still English, and is that wrong?

    These are the rules that replaced "value == key". That test reported 953
    gaps in 32 locales and almost none of them were real: the key IS the English
    source, so it flagged the Bold button, the filename preset.json and the
    header markup template. A gate that cries wolf on 953 correct values is a
    gate nobody reads, which is the condition the ticket was opened against.
    """

    def test_an_english_fallback_is_a_gap(self):
        # The case the ticket exists for. No review, no excuse, not scaffolding.
        assert not i18n_verified.blank("de", "Delete from this silo?")

    def test_a_reviewed_identical_is_not_a_gap(self):
        # French `Date`, `Mode` and `Volume` are French words spelled the same.
        # No regex can know that; a reviewer can, and the verdict is recorded once.
        assert i18n_verified.blank("fra", "Date")

    def test_the_same_value_is_not_excused_in_every_language(self):
        # `Auto` is a French word and not an Arabic one. The allowlist is
        # per language precisely so this cannot drift into a blanket exemption.
        assert i18n_verified.blank("fra", "Auto")
        assert not i18n_verified.blank("ar", "Auto")

    def test_a_token_that_is_the_same_everywhere_is_not_a_gap(self):
        for lang in ("ar", "de", "ru", "zh"):
            assert i18n_verified.blank(lang, "B"), lang
            assert i18n_verified.blank(lang, "RGB"), lang
            assert i18n_verified.blank(lang, "Problip"), lang

    def test_scaffolding_with_no_word_in_it_is_not_a_gap(self):
        for lang in ("ar", "de", "ru"):
            assert i18n_verified.blank(lang, "{} — {}"), lang
            assert i18n_verified.blank(lang, "\U0001f4c1{}"), lang
            assert i18n_verified.blank(lang, "preset.json"), lang

    def test_a_chord_is_not_scaffolding(self):
        # "Alt+W…" is letters. The key names are words, and whether a pack may
        # write "Alt+Rechts" is a review question, not a structural one -- so
        # the structural test must let it through to the reviewer.
        assert i18n_verified.has_word_to_translate("Alt+W…")
        assert i18n_verified.has_word_to_translate("Copy	Ctrl+C")
        # Whether a given language may then KEEP it is the allowlist's business.
        assert i18n_verified.blank("de", "Alt+W…")
        assert not i18n_verified.blank("de", "W")

    def test_a_fragment_key_is_excused_only_when_the_key_is_given(self):
        # The collector sliced this out of tr("MUTED" if muted else "SOUND ON").
        # Nothing looks it up at runtime, so the gate must not demand a
        # translation for it -- but only when it is told it is a fragment key.
        fragment = 'MUTED" if muted else "SOUND ON'
        assert i18n_verified.blank("de", fragment, key=fragment)
        assert not i18n_verified.blank("de", fragment)

    def test_a_value_with_surrounding_whitespace_is_never_excused(self):
        # Padding hides a broken render. A leading space before a toolbar glyph
        # is a layout bug, not a translation.
        assert not i18n_verified.blank("de", " B")

    def test_a_curated_value_that_was_translated_is_a_defect(self):
        # The other direction, and the one that would have caught the Italic
        # button shipping as SAYA (id), TÔI (vi), jeg (sv), minä (fi), К (ru).
        import i18n_identical_audit

        assert i18n_identical_audit.is_curated_neutral("I")
        assert not i18n_identical_audit.is_curated_neutral("OK")
        assert not i18n_identical_audit.is_curated_neutral("Bold")


class TestMachineMarkers:
    """A translation-work marker that reached a shipped value.

    30 packs shipped `TODO(ar): Baked %d settings into DEFAULT_PROFILE...` for
    two full rounds. Nothing objected, because the marker made the value DIFFER
    from the English master -- which is exactly the test that decides whether a
    key counts as translated. A value can be neither English nor a translation.
    """

    def test_a_leading_marker_is_caught(self):
        for lang in ("ar", "bg", "zh", "ded"):
            value = f"TODO({lang}): Set Defaults from Current"
            assert _TODO_MARKER.match(value), value

    def test_the_spanish_word_todo_is_not_a_marker(self):
        # "todo" is the ordinary Spanish word for "all". Anchoring is what keeps
        # the rule from rejecting DETENER TODO EL SONIDO.
        assert not _TODO_MARKER.match("DETENER TODO EL SONIDO")
        assert not _TODO_MARKER.match("■ DETENER TODO EL SONIDO")

    def test_the_marker_only_counts_at_the_start(self):
        assert not _TODO_MARKER.match("Set Defaults TODO(xx): from Current")

    def test_a_marker_is_not_an_excuse_in_blank(self):
        # Even if a locale were reviewed for the underlying English string, the
        # marked value is a different string and must not inherit the verdict.
        template = ("Set Defaults from Current edits repository source and is "
                    "available in\nsource development builds only. The packaged "
                    "build cannot change\nrepository defaults.")
        assert i18n_verified.blank("ar", template)
        assert not i18n_verified.blank("ar", f"TODO(ar): {template}")


class TestLiveLanguageSwitching:
    """set_language used to assign a function local, not the module global.

    The bytecode was the tell: co_names held ('_current_lang_lock', 'upper')
    and never '_current_lang', because the assignment compiled to STORE_FAST.
    Every probe that read the module global afterwards saw EN, and tr() served
    English for every language no matter what the UI had selected. Nothing
    asserted on the round trip, so it shipped.
    """

    def test_set_language_moves_the_module_global(self):
        from fastprompter.core.i18n import _engine as engine

        engine.set_language("de")
        assert engine.get_language() == "DE"
        engine.set_language("EN")
        assert engine.get_language() == "EN"

    def test_the_assignment_is_a_global_not_a_local(self):
        from fastprompter.core.i18n import _engine as engine

        assert "_current_lang" in engine.set_language.__code__.co_names

    def test_tr_follows_the_switch_without_an_explicit_lang(self):
        i18n.ensure_initialized()
        i18n.ensure_loaded("de")
        from fastprompter.core.i18n import _engine as engine

        try:
            engine.set_language("de")
            assert engine.tr("LOG") == "PROTOKOLL"
            engine.set_language("en")
            assert engine.tr("LOG") == "LOG"
        finally:
            engine.set_language("EN")
