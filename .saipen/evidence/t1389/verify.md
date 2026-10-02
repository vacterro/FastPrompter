# T-1389 — verify

The five sites T-1387's whole-file prose scan flagged, plus one it structurally
could not see.

## What changed

`src/fastprompter/ui/limit_settings_dialog.py` (+29/-7):

| Site | Before | After |
|---|---|---|
| `_refresh_freebuff_status` who= | `... or "signed in"` | `... or tr("signed in")` |
| `claude_accounts_lines` origin | `origin = "default home"`, interpolated into a raw f-string | `tr("default home")` / `_home_kind_label(kind)`, and the row line keeps its f-string |
| creds | `"yes" if row["has_credentials"] else "no"` | `tr("yes")` / `tr("no")` |
| bridge | `bridge = "no"` | `tr("no")`, `tr("yes (cache present)")`, `tr("yes (no cache yet)")` |
| role | `role = "default"` inside `tr("Home ({role}): ...")` | `tr("default home")` |
| **data_state** | `state=row['data_state']` — the provider's own `fresh`/`stale`/`unavailable` token | `data = tr(row["data_state"] or "unavailable")` |

The sixth row is the one the T-1387 scan could not report. `data_state` is
produced by `claude.account_data_state()` and reaches the label as *data*, so
no source-literal scan of this file can see it. It was found by reading
`account_data_state` and following its return values.

New helper:

```python
def _home_kind_label(kind: str) -> str:
    return {"config_dir": tr("config folder"), "config_file": tr("config file"),
            "desktop_only": tr("desktop only"), "configured": tr("configured"),
            "auto_sibling": tr("auto sibling")}.get(kind, tr("home"))
```

`AccountRef.source_kind` is an identifier (`auto_sibling`, `desktop_only`) that
the settings rows painted straight into the label. An unknown kind — a
provider FastPrompter has never heard of — falls back to a word rather than
leaking, which is the same rule `_win_label` follows.

One line was deliberately **not** wrapped: the row line
`f"  {name}{badge_text} · {origin} · {path}"`. It carries no words, only three
already-translated values and their separators. Making it a key would have
earned 29 byte-identical allowlist verdicts in `tools/i18n_verified_identical.json`
and translated nothing. The inline comment says so.

## Keys

11 keys × 32 locales, through `tools/i18n_apply_campaign.py --todo ... --apply`:
`default home`, `signed in`, `yes`, `no`, `config folder`, `config file`,
`desktop only`, `configured`, `auto sibling`, `home`, `fresh`.

`fresh` was not in the first campaign and was a real miss caught by the check:
the code called `tr(row["data_state"])` and `data_state` returns `fresh`, but
no pack carried the key, so every non-English user would have read
"quota data: fresh".

Byte-identical values need a written verdict, not silence — the same rule
T-1388 was filed for. Two locales keep `no` byte-identical; `no` is the native
word in both Italian and Spanish, so `tools/i18n_verified_identical.json` gained
`it: no` and `spa: no` (1034 → 1036). No other new key is byte-identical
anywhere.

`en.json` grew 1851 → 1862 keys, `numstat 12/1` — the writer proves
`json.dumps(..., ensure_ascii=False, indent=2) + "\n"` reproduces the file
byte-for-byte before writing, or it aborts. Same discipline the T-1387 serializer
fix required. Every locale pack shows the same 12/1 shape, i.e. no whole-file
reformat.

## Instruments

**`V:/_TEMP_/t1389_check.py` → PASS** (`check_pass.txt`). Behavioural, not
lexical: it loads the real dialog module with `importlib`, drives
`_home_kind_label` over all five real `source_kind` values plus a made-up sixth,
renders the credentials line end to end in EN/SV/DE, and requires every
`data_state` token to resolve in all 32 packs.

**`V:/_TEMP_/t1389_negctl.py` → NEGATIVE CONTROL OK** (`negative_control.txt`).
Loads the pre-fix module and pre-fix `sv.json` out of `HEAD` and requires the
same assertions to FAIL there. They do, on all six raw sites, the missing
helper and all six keys.

**Targeted tests** (`targeted_tests.txt`): 87 passed — `test_i18n_contract_t1353`,
`test_i18n_key_inventory`, `test_limit_ui_tr_keys_t1379`, `test_typecheck_vocab`
(whose `test_generated_vocabulary_equals_source_extraction` is a real gate over
the regenerated word list), `test_usage_limits_claude_accounts`,
`test_master_mute_i18n_t1244`.

**Toolchain** (`toolchain.txt`): `inject_translations.py` exit 0, 1862 keys,
1861 shipped keys kept + 1 new; `gen_typecheck_ui_vocab.py` 32865 words;
`validate_saitranslate.py` "VALIDATION PASSED with 1 warning(s) - no structural
errors", 100.0% coverage.

## The suite caught one test that encoded the defect

The first full run stopped at
`tests/test_t1266_dual_claude.py::TestDetectionSummary::test_the_row_explains_where_the_account_came_from`:

```python
assert "default home" in body
assert "auto_sibling" in body      # <-- required the identifier to leak
```

That assertion did not merely tolerate the leak, it **required** it: the test
named the ticket's own bug as the expected behaviour. Updated to assert the
word (`"auto sibling"`) and, in the negative, that the raw token is gone:

```python
assert "auto sibling" in body
assert "auto_sibling" not in body
```

The test's intent — the row must say where the account came from — is
unchanged and still holds; only the representation moved from an internal
`AccountRef.source_kind` token to a readable word. File now 36 passed.

This is the second time a check of mine contradicted my own work (the first
was T-1388's false Swedish `spend` verdict). It is recorded here rather than
quietly fixed.

## The finding this check did not fail on

`lang_binding_probe.txt`:

```
translations.current_lang = SV
engine.get_language()    = SV
translations.tr("spend")          -> spend
i18n.tr("spend")                  -> utgifter
translations.tr("spend", "SV")    -> utgifter
```

`core/translations.py:57` is `def tr(text: str, lang: str = "EN")`, and
`translations.tr` returns the source unchanged for `EN`. The UI modules import
that one. `main.py` passes `self._current_lang` explicitly at every call site and
is therefore correct; `limit_gauges.py` and `limit_settings_dialog.py` call
`tr()` bare, so **every** string in those two modules renders in English no
matter what language the user picked. `core/i18n/_compat.py:22` — the other
`tr` — defaults to the active language, which is where the discrepancy comes
from.

This is not a T-1389 defect: it predates the ticket, it is not one of the six
sites, and fixing it changes every bare `tr()` call in the app at once. It is
filed as **T-1390**. The check prints it as `BINDING` on every run so it cannot
be forgotten, but does not fail on it, so T-1389 still has a clean gate.

The consequence for this ticket is stated plainly: **the work here is correct
code with correct keys, but it does not become visible to a non-English user
until T-1390 binds the language.** Wrapping the strings was the necessary first
step; it is not sufficient, and this evidence does not claim it is.