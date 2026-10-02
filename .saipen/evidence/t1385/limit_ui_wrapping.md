# T-1385 — the Limit UI was painting raw English, and T-1379 said it was fixed

## What the ticket was

T-1379 claimed the Limit UI was fully translated. It was not. The audit that
justified T-1379's closure classified a string as markup and therefore exempt
from review with:

```
is_markup(): r"<[/a-zA-Z]|\bstyle\s*=|\bcolor\s*:\s*#|font-weight|..."
```

Every string in the hover card sits inside `<span style='...'>` or
`<div style='...'>`. The regex matched the *tag*, the audit then concluded the
whole string was markup, and the entire hover card was excluded from the
wrapping pass. The painted captions in `limit_overview.py` and the whole
Colours tab of the settings dialog were caught the same way.

The rule the audit actually needed is narrower: **markup in a translatable
position still has translatable text inside it; only the tag itself has to
stay raw.** Every fix below follows that split — `<b>`, `style='...'`, `·`,
`★`, hex colours stay raw, and the words between them go through `tr()`.

## Source changes — 4 files, 44 keys

| file | what was unwrapped |
|---|---|
| `ui/limit_gauges.py` | the whole hover card: `_snapshot_age` freshness stamps, the `Resets` section heading, five empty-account states, `[stale]`, the banked-reset pill, "Reset time passed…", two "no readable quota window" rows, the Freebuff wallet line, the model-prices line, `unavailable`, `Hidden: …`, the "+N more selected accounts" overflow line, the Ctrl+Click hint, and both context-menu actions |
| `ui/limit_overview.py` | the QPainter captions: the banked-reset title suffix, the `stale` badge, `{n}% left` / `{n}% used`, all four `_reset_text()` forms, `unknown source`, and the offer-title fallback |
| `ui/limit_settings_dialog.py` | all 17 `limit_colors.ROLES` labels and tooltips (wrapped at the call site — `limit_colors.py` is untouched), the 9 notification-symbol and 7 colour-preset combo labels, both `Custom ({col})` twins, `{n} seconds`, the status-caption parts, the hidden-banked label, the copy hint, `Notification event`, both `Configuration error:` sites, the auto-troubleshoot failure body, and the auto-heal status |
| `core/usage_limits/model.py` | the two **upstream producers** the audit flagged: `format_offer_expiry()` and `reserve_advice()` |

### Two defects fixed, not just wrapped

**IMP-002 — the English "s" was pasted onto a translated noun.**
`tr("Activate reset ({n} reset{s})").format(n=…, s="s" or "")` rendered
**сбросs** in Russian, and the same broken shape in every language that does
not plural by suffix. The count is now carried by a whole translated word, the
same pattern the codebase already used at `limit_gauges.py:401`:

```python
res_word = tr("reset") if banked_total == 1 else tr("resets")
btn.setText(tr("Activate reset ({n} {res_word})").format(
    n=banked_total, res_word=res_word))
```

This retired `Activate reset ({n} reset{s})` and `Open Usage ({n} reset{s})`
and introduced their `{res_word}` forms.

**IMP-004 — English word-stripping.** `limit_gauges.py:1024` does
`pool.replace(" and ", " & ").replace(" models", "")` on
`b.group_label`. **Deliberately NOT changed**, and the reason matters:
`group_label` is vendor API data. Its producers are `_pool_label()` in
`_codex_probe.py` and `antigravity.py:161`, and neither routes it through
`tr()` — it is the provider's own English string, so stripping its English is
correct. Translating it would be inventing a term the vendor never supplied.
The fragility is real but it is a data-cleaning concern about vendor strings,
not a translation gap, and it belongs in its own ticket.

### `model.py` now imports `tr` — a layering change, deliberately

`model.py` is the provider-neutral domain model and had **no** i18n import
anywhere in `core/`. `format_offer_expiry` is nevertheless a display
formatter — its docstring is written in terms of the strings it produces — and
its output is painted into the hover card. There is no call site to wrap
instead: the string is finished by the time the UI sees it.

The import was measured, not assumed: `from fastprompter.core.translations
import tr` costs **16 ms** and `tr` degrades to returning the key when the
i18n engine has not been initialised, so importing it from a test that never
touches the UI is safe. `format_offer_expiry` was checked against its own old
output for all five branches — `expired`, `expires in 10m`, `expires in 1h
56m`, `expires in 2h 30m`, `expires Sun 11:15` — and every one is
byte-identical to the pre-change rendering.

## The campaign

41 genuinely new keys × 32 locales = **1 408 pairs**, run as 8 agents at
4 locales each. Every agent was given the locale's own existing pack as the
authoritative vocabulary source and told to reuse the words already in it.

**Key count:** `en.json` 1803 → **1842** (+41 new, −2 retired). All 33 packs
at 1842 English / 1844 locale keys after the merge and cleanup.

**One contract violation found and fixed.** The Norwegian agent rendered
`5t/0 %-filter`, and `i18n_contract._PRINTF` read `%-f` as a printf
conversion — the hyphen is a valid left-justify flag and `f` is a valid type.
The English `0% filter` does not trip it only because the space after `%`
breaks the match. Reworded to `(skjult filter for 5t/0 %)`, which ends the
string at `%`. This is the scanner working correctly; the fix belonged in the
translation, not in the gate.

**Two values are byte-identical to English in all 32 locales, on purpose:**
`[{n} {res_word}]` and `{name} ({n} {res_word})`. They are pure placeholder
scaffolding — two substituted values and a bracket pair, with no lexeme in any
language. `i18n_verified.blank()` already excuses them without an allowlist
entry. Any word added to translate them would be invented.

**Three allowlist verdicts recorded** (`tools/i18n_verified_identical.json`):
`Resets` stays `Resets` in **de**, **nl** and **pt**. Each of those packs
already uses the untranslated loanword in the countdown rows sitting directly
beneath this heading (`Nächste Resets`, `Volgende resets`, `resets agora`);
translating the heading alone would make one tooltip panel speak two
languages. That is a human verdict per language, which is what the allowlist
is for.

## Two pack defects the campaign surfaced, one fixed and one not

A campaign agent reported that the **ded** pack's `stale` entry was the
German word `veraltet` — a German word leaking into the Russian joke pack —
and that its `[stale]` value was therefore inconsistent. **Checked before
believing it, and the claim was false**: `ded` has `stale` → `протухло` and
`[stale]` → `[протухло]`, which are consistent. No change. Had this been taken
on the agent's word, the pack would have been "fixed" into a regression.

The same agent's **nl** claim was true, and worse than reported. The pack
translates "reset" two ways: **54** entries use the untranslated loanword
(`Volgende resets`, `reset over {mins}m`, `Reset activeren`) and exactly
**three** use `herinstelling` — and those three are `reset`, `resets` and
`resets {when}`, which is precisely what `{res_word}` and `_reset_text()` read.

```python
trans["reset"]        = "reset"          # was "herinstelling"
trans["resets"]       = "resets"         # was "herinstellingen"
trans["resets {when}"] = "resets {when}"  # was "herinstellingen {when}"
```

Before this change the same panel already mixed the two words, but the surface
was two call sites. This ticket multiplies the call sites, so the three
entries were brought onto the pack's own dominant form — not a new word, the
one 54 other entries already use. All three now match the English master byte
for byte by design, so all three carry an `nl` allowlist verdict.

## Verification

```
python tools/validate_saitranslate.py
  Total Source Keys Scanned : 1292 (+91 dynamic)
  Missing from en.json       : 0
  Target Locales Present     : 33 / 33
  33/33 locales at 100.0% coverage
  STATUS: VALIDATION PASSED with 1 warning(s) - no structural errors
```

The one warning is the pre-existing 550-key
`not static tr() first-args` notice, unchanged from T-1384.

```
python -m ruff check <the 4 changed files>
  All checks passed!
```
8 `F541` *f-string without any placeholders* errors were introduced by the
edit — the `f` prefix on strings that stopped being f-strings once a template
was split around a `tr()` call — and auto-fixed. The repo-wide count of 132
is the untouched pre-existing baseline.

```
python -m pytest -q          (SERIAL -- never parallel on Windows)
  1 failed, 4330 passed, 16 skipped
  FAILED tests_smoke/test_app_smoke.py::test_no_cyrillic_in_codebase
    AssertionError: Cyrillic characters found:
      ['src/fastprompter/ui/limit_settings_dialog.py:478']
```

**The project's own guard caught a violation I introduced.** The comment
explaining the `reset{s}` fix quoted the broken output as its example — and
that example was `"сбросs"`, which is Cyrillic text in a source file. The
`test_no_cyrillic_in_codebase` rule exists precisely so no Cyrillic literal
can reach a file that Qt or a terminal will render, and the comment I wrote to
document a translation bug reintroduced exactly what it forbids. The comment
now describes the failure without reproducing it:

```python
# English "s" onto a translated template: that glued a Latin "s"
# to a Cyrillic or inflected noun, which is wrong in every language
# that does not plural by suffix.
```

Re-run of the single test: `1 passed in 0.31s`. Full suite re-run against the
final tree (after the Cyrillic fix, the `nl` pack fix, `inject_translations`
and the vocabulary regeneration):

```
python -m pytest -q --no-header -p no:cacheprovider > V:/_TEMP_/t1385_pytest.log
  5252 passed, 23 skipped in 1543.95s (0:25:43)
```

One methodology note, because it nearly produced a false green. The first
final-tree run piped through `| tail -8`, so the log held only the last eight
lines and the reported `exit code 0` was **`tail`'s**, not pytest's — and
those eight lines were a teardown traceback, not a summary. A run whose exit
code belongs to the last stage of a pipe is not a run whose result was read.
The final run writes to a file and the summary above is pytest's own.

## Not done, and why

* **No native-reviewer sign-off.** 1 408 machine translations across 32
  languages are not the same as 32 native reviewers. Every agent reported its
  own uncertainties and they are recorded in the campaign messages, not
  suppressed: Czech `aktualizováno před {days} dny` is right for 2–4 and wrong
  for 5+; Bulgarian, Russian, Polish, Slovak and Hungarian all need a counted
  noun whose case/gender flips at 1, which a bare integer token cannot express;
  `{label} available via reserve` is coined in every language because no pack
  had a prior word for a Codex reserved-quota pool. These are recorded as
  known ceilings, not as finished work.
* **`typecheck_words.py` left at HEAD.** `tools/gen_typecheck_words.py`
  regenerates it from a fixed doc allowlist; running it drops 35 real English
  words (`actual`, `standard`, `steps`, `calls`, `boundaries`). That is a
  spellchecker regression, no test covers the file, and regenerating it is not
  part of this ticket. `typecheck_ui_vocab.py` **was** regenerated
  (`wrote 32798 words`) because it derives from the pack values and a test
  does cover it.
* **The 550-key warning is untouched.** Every one of those keys reaches `tr()`
  through a variable or a format-template. Wrapping them is the same
  argument-shape problem documented in T-1384, where scanning for literal
  arguments destroyed 555 keys.
* **No push.** No push authorization was given, so nothing was pushed.
