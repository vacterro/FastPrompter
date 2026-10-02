# T-1390 — verify

`translations.tr()` bound no language, so the entire AI-limit surface rendered
in English no matter what the user picked.

## The defect

`core/translations.py:57` was

```python
def tr(text: str, lang: str = "EN") -> str:
    ...
    target = (lang or "EN").upper()
    if target == "EN":
        return text
```

Every UI module imports that function. An AST census over `src/`:

| | bare `tr()` | `tr(…, lang)` |
|---|---:|---:|
| `main.py` | 0 | 249 |
| `ui/limit_settings_dialog.py` | **264** | 0 |
| `ui/limit_gauges.py` | **65** | 0 |
| `ui/limit_overview.py` | **42** | 0 |
| `ui/limit_account_selector.py` | **12** | 0 |
| `core/usage_limits/model.py` | **6** | 0 |
| every other module (30 files) | 0 | 655 |
| **total** | **389** | **1324** |

The split is total: `main.py` passes `self._current_lang` at all 249 sites and
was correct; the five usage-limit modules pass nothing and were English-only.
`core/i18n/_compat.py:22` — the other `tr` — already resolved `lang or
_engine.get_language()`, which is where the discrepancy came from.

Proof (`check_pass.txt`, and the probe filed with T-1389):

```
translations.tr("spend")          -> spend
translations.tr("spend", "SV")    -> utgifter
engine.get_language()             -> SV
```

## The fix

9 lines added, 2 changed, in `core/translations.py`:

```python
def tr(text: str, lang: str | None = None) -> str:
    target = (lang or _i18n_engine.get_language() or current_lang or "EN").upper()
```

`_i18n_engine` is `core.i18n._engine`; `_engine.get_language()` is the
thread-safe accessor the compat shim already uses. The legacy `current_lang`
global is kept in the chain so a direct assignment to it still works. This is
deliberately a one-place fix rather than 389 call-site edits: `main.py` proves
the explicit-argument style is the house convention, but threading a language
through five UI modules is a far larger diff for the identical result, and
every one of those modules would still need auditing.

## What it does not change

`_engine._current_lang` initialises to `"EN"` and nothing binds a language until
the user picks one, so an unbound app behaves exactly as before. `main.py` is
untouched: it always passed an explicit `lang`, which still wins.

## The one thing that could have broken, and did not

Binding a default turns `tr()` calls at *import time* into frozen strings in
whatever language happened to be active on first import. Scanned for
(`import_time_tr_scan.txt`):

```
core/usage_limits/model.py        -> import-time bare tr(): []
ui/limit_account_selector.py      -> []
ui/limit_gauges.py                -> []
ui/limit_overview.py              -> []
ui/limit_settings_dialog.py       -> []
```

None. Every one of the 389 is inside a function body.

## Instruments

**`V:/_TEMP_/t1390_check.py` → PASS** (`check_pass.txt`). Loads the real
`limit_gauges` and `limit_settings_dialog` modules, binds Swedish, and requires
their own `tr()` to agree with `tr(key, "SV")`; then requires English when
nothing is bound, the RU legacy dictionary to still win over the pack, and an
explicit `lang` to still override.

```
active=SV  limit_gauges.tr('weekly')           -> 'veckovis'
active=SV  limit_settings_dialog.tr('window') -> 'fönster'
active=EN  tr('weekly')                       -> 'weekly'
legacy RU  tr('Exit')                         -> 'Выход'
```

**`V:/_TEMP_/t1390_negctl.py` → NEGATIVE CONTROL OK** (`negative_control.txt`).
Copies `core/` into a scratch tree, overwrites `translations.py` with the
pre-fix bytes from `HEAD`, and reruns the same probe. It trips all six keys
(`weekly`, `window`, `home`, `config folder`, `fresh`, `Session`) plus
`tr(key, None)`, and prints the signature it is disproving:

```
tr() signature at HEAD: lang default = 'EN'
```

**Full suite** (`full_suite.txt`): `4192 passed, 16 skipped in 654.21s`,
`PYTEST_RC=0` — identical to the pre-change run.

## What the suite does NOT prove, stated plainly

The suite runs with no language bound, so it exercises the unchanged default
path. It is evidence that binding a default **breaks nothing**; it is not
evidence that the newly-bound path is correct. That path is covered only by
`t1390_check.py`, which drives two of the five modules directly. The other
three — `limit_overview` (42 calls), `limit_account_selector` (12) and
`usage_limits/model` (6) — are covered by the suite in its unbound form and by
the shared `tr()` implementation, not by a per-module non-English render. A
full render sweep in a real non-English locale is not claimed.