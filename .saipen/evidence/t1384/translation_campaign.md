# T-1384 — the translation half of T-1379

T-1379 wrapped the Limit UI in `tr()` and shipped the code. It left the other
half undone: the 32 non-English packs had never received the new keys, so every
Limit-UI string the wrapping pass introduced still rendered as its English
source. This ticket closes that.

## What was outstanding at the start

`tools/validate_saitranslate.py` on the working tree reported, per locale,
roughly 240 canonical keys absent from the pack. 241 keys x 32 locales is 7,712
strings. `en.json` held 1,809; each pack held 1,568.

The pack claimed `coverage_pct: 100.0` while the keys said 88.1. That mismatch
was pre-existing, not caused by T-1379 — proved by stashing the working tree,
re-running the tool on HEAD (88.1) and unstashing.

## The campaign

The repo already has the pipeline for this, from T-1353: a per-locale `<lang>.json`
todo, a `<lang>.done.json` of results, and `tools/i18n_apply_campaign.py` to
merge. The todos were generated from `en.json` minus each pack, then one agent
per locale filled its own file. No agent was permitted to run pytest or ruff —
32 parallel test suites on Windows is a known failure mode here.

Three contract violations came back and were fixed mechanically against
`tools/i18n_contract.py`:

| locale | violation | fix |
|---|---|---|
| he | newline count 7 -> 8 | Hebrew had put `{target}` on its own line where the English reads `Installs to: {target}` |
| hu | printf spec `[] -> [('o', 1)]` | `0%-ot` and `0 %-ot` both still parse as a `%o` spec; the sign had to go: `0 százalékot mutat` |
| ko | newline count 3 -> 2 | restored to the English shape |

## Three wrapping defects the campaign surfaced

None of these is visible to the test suite, and each one only misbehaves in a
non-English locale, so none of them could have been caught by the T-1379 gates.

1. **A Qt stylesheet inside `tr()`** — `limit_settings_dialog.py:2307`,
   `lbl.setStyleSheet(tr("color: #4caf50; font-weight: bold;"))`. A translated
   stylesheet is not a stylesheet. A scan of the whole `src/fastprompter` tree
   for `tr()`/`tr_fmt()` calls whose first argument matches a markup pattern
   found 8 hits: 7 false positives (prose that merely contains the word
   "margins" or "background") and this one.

2. **A `collections.namedtuple` field-name string inside `tr()`** —
   `limit_gauges.py:389`. Translating that string renames the tuple's
   attributes.

3. **Persisted-setting keys inside `tr()`, as QComboBox userData** — the worst
   of the three. `limit_settings_dialog.py` builds its style and fill-direction
   combos as:

   ```python
   self.cmb_style.addItem(tr('Bars'), tr('bars'))
   ...
   index = self.cmb_style.findData(
       str(self.data.get("limit_gauges_style", "bars")))
   self.cmb_style.setCurrentIndex(max(0, index))
   ```

   and `limit_gauges.py:561-578` validates the stored value against `_STYLES`
   and `("remaining", "used")`. In any non-English locale `tr('bars')` returns
   something like "Balken", `findData("bars")` returns `-1`, and
   `max(0, -1)` pins the combo to index 0 — so the user's saved gauge style and
   fill direction are silently discarded on every launch, and the app cannot
   write back a value it will accept. Unwrapped: the label is translated, the
   userData stays the stable English key.

## The prune, and the data loss it caused

Removing the five identifier keys (`account snapshot offers activate open_url`,
`bars`, `dots`, `stack`, `used`) left them as dead weight in the validator's
sight. The first script to clear them computed "live" keys by walking the AST
for `tr()`/`tr_fmt()` calls **whose first argument is a direct `ast.Constant`**
and deleted everything in `en.json` that no such call mentioned.

That is wrong, and it was wrong by a lot: **555 of the 1,808 keys** were
declared dead, including obviously live strings like
`'Bold ({})\nMake selected text bold.'` and `'Settings\nConfigure hotkeys,
theme, fonts, and UI scaling.'`. Most of the catalogue is reached through a
variable, a `.format()` chain, an f-string or an implicit concat, none of which
a bare-constant match sees. A wider scan that also handles `JoinedStr` and
attribute-call bases still leaves 538 keys unmatched, which is the real shape of
the problem: **pruning by argument-shape is unsound in this codebase and must
not be done from a scan.**

The script had already written all 33 packs when the number looked wrong.

**Recovery.** `tools/inject_translations.py` had last run against the full
1,808-key state, so the generated modules under `src/fastprompter/core/i18n/`
still held every translation the prune destroyed. 31 of the 33 were current;
`el` and `est` were merged after the last regeneration and were stale at 1,568,
but their campaign results survived in `build/t1384_todo/<lang>.done.json`. All
33 packs were rebuilt from those two sources and verified:

```
  ar: 1253 -> 1808   ... one line per locale ...
  zh: 1253 -> 1808
33 packs, key counts present: [1808]
en.json 1808; en.json == en.py dict: True
```

A pre-prune copy of the damaged state is kept at `V:/_TEMP_/t1384_damaged/`
for audit.

The correct prune is a hand-listed set of five, and that is what shipped.

## The last 110

With the 555 recovered, the validator still failed on 110 byte-identical values
across 32 locales. They split cleanly in two, and the two got opposite
treatment:

* **Must stay verbatim — 70 allowlist verdicts** added to
  `tools/i18n_verified_identical.json`. `Codex (ChatGPT / OpenAI)` and
  `D:\codex-work, E:\codex-personal` for all 32 languages (a product name and a
  pair of filesystem paths), plus `Notifications` / `Sources` / `Style` /
  `quota` in French, `quota` in Italian and Dutch — words those languages
  themselves borrow and spell identically. Forcing a different word would make
  the UI worse.

* **Real English left in — 40 values translated** across 17 packs, each one
  using wording the same pack already uses elsewhere so the two agree. The
  noun forms behind `Activate reset ({n} reset{s})` are the delicate ones: the
  singular and the plural must be the same noun in the target language or the
  two branches stop agreeing, so German gets `Zurücksetzung` /
  `Zurücksetzungen`, Dutch `herinstelling` / `herinstellingen`, Portuguese
  `redefinição` / `redefinições`.

## A generated artifact the packs feed

The first full-suite run failed exactly one test:

```
FAILED tests/test_typecheck_vocab.py::test_generated_vocabulary_equals_source_extraction
1 failed, 4191 passed, 16 skipped in 670.21s
```

`src/fastprompter/core/typecheck_ui_vocab.py` is a static build input — the set
of Latin words the typechecker treats as known, so it does not have to import 32
language packs at runtime. It is generated from the pack *values*, so changing
the packs changes the word set and the committed file goes stale. The test is
the guard for exactly that, and it did its job:

```
$ python tools/gen_typecheck_ui_vocab.py
wrote 32660 words -> src\fastprompter\core\typecheck_ui_vocab.py
```

`src/fastprompter/core/typecheck_words.py` is a *different* artifact — the
shipped English dictionary, built from README, GUIDE_EN, CHANGELOG, the wiki
and `i18n/en.py`. No failing test covers it and no i18n pack feeds it, so
regenerating it here would have been scope creep with a real cost: the current
regeneration drops 35 real English words from the dictionary (`actual`,
`standard`, `steps`, `calls`, `boundaries` …) while adding 68 that come from
project prose (`zcode`, `freebuff`, `discord`, `estonian`). A spellchecker that
stops knowing the word "standard" is a regression, so the file was reverted to
HEAD. The frequency threshold that causes this is a separate question and a
separate ticket.

## Verification

```
$ python tools/i18n_recompute_coverage.py
32 pack(s) rewritten

$ python tools/inject_translations.py
Updated en.py
Generated 32 language .py modules in i18n package.
=== INJECTION PREPARATION COMPLETE ===          exit 0

$ python tools/validate_saitranslate.py
Missing from en.json       : 0
STATUS: VALIDATION PASSED with 1 warning(s) - no structural errors

  all 33 packs: 1803 keys | 100.0% coverage

$ python tools/gen_typecheck_ui_vocab.py
wrote 32660 words -> src\fastprompter\core\typecheck_ui_vocab.py

$ python -m ruff check src/ tests/
All checks passed!

$ python -m pytest tests/ -q
4192 passed, 16 skipped in 904.82s (0:15:04)
```

The one remaining warning is informational and pre-existing: 550 `en.json` keys
are not static `tr()` first-arguments — 224 of them are data-driven (a literal
in the UI, passed through a variable) and 66 are docs/wiki or format templates.
It is the same class of blindness that made the prune script wrong, and the
validator reports it rather than acting on it, which is the correct division.

## Not done, and why

* `Activate reset ({n} reset{s})` and `Open Usage ({n} reset{s})` inject a
  literal `"s"` or `""` (`limit_settings_dialog.py:476`). Languages without
  suffix-based pluralisation render `сбросs`. Every locale followed the existing
  project precedent of leaving the counted noun Latin so both branches stay
  grammatical. A real fix is a per-language plural helper at the call site, not
  a translation change, and it is a separate ticket.
* The 550-key warning above is not closed. Closing it means a real call-graph
  analysis, not a syntactic one.
* `src/fastprompter/core/typecheck_words.py` was deliberately left at HEAD; see
  the note above for why regenerating it is not free.
* The 40 new translations were written from each pack's own existing vocabulary
  by the agent that produced them, not by a native reviewer per language. The
  contract tool guarantees structure (placeholders, newlines, printf specs); it
  does not guarantee idiom. A native review pass would be a reasonable follow-up
  and is not something this ticket can claim.
* No push was performed. No push authorization was given.
