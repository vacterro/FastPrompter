# Translation Bundle — FastPrompter

Generated: 2026-07-31 UTC (synced 01.08: 2-key drift closed)
Updated: 2026-08-01 UTC (repair: 63 unregistered multi-line tr() keys -> 939 keys/33 loc)
Source: `src/fastprompter/` `tr()` call sites + `docs/wiki/` (read-only reference)
Bundle: `.saipen/saitranslate/locales/` (JSON, one file per language)

## Languages (32 + 1 bonus)

| Code | Name | Flag | Coverage |
|------|------|------|----------|
| EN | English | 🇺🇸 | 100.0% |
| RU | Russian | 🇷🇺 | 100.0% |
| EST | Estonian | 🇪🇪 | 100.0% |
| JA | Japanese | 🇯🇵 | 100.0% |
| UKR | Ukrainian | 🇺🇦 | 100.0% |
| DE | German | 🇩🇪 | 100.0% |
| FRA | French | 🇫🇷 | 100.0% |
| SPA | Spanish | 🇪🇸 | 100.0% |
| IT | Italian | 🇮🇹 | 100.0% |
| PT | Portuguese | 🇵🇹 | 100.0% |
| NL | Dutch | 🇳🇱 | 100.0% |
| PL | Polish | 🇵🇱 | 100.0% |
| SV | Swedish | 🇸🇪 | 100.0% |
| DA | Danish | 🇩🇰 | 100.0% |
| FI | Finnish | 🇫🇮 | 100.0% |
| NO | Norwegian | 🇳🇴 | 100.0% |
| ZH | Chinese | 🇨🇳 | 100.0% |
| KO | Korean | 🇰🇷 | 100.0% |
| TH | Thai | 🇹🇭 | 100.0% |
| VI | Vietnamese | 🇻🇳 | 100.0% |
| AR | Arabic | 🇦🇪 | 100.0% |
| HE | Hebrew | 🇮🇱 | 100.0% |
| BG | Bulgarian | 🇧🇬 | 100.0% |
| CS | Czech | 🇨🇿 | 100.0% |
| EL | Greek | 🇬🇷 | 100.0% |
| HI | Hindi | 🇮🇳 | 100.0% |
| HR | Croatian | 🇭🇷 | 100.0% |
| HU | Hungarian | 🇭🇺 | 100.0% |
| ID | Indonesian | 🇮🇩 | 100.0% |
| RO | Romanian | 🇷🇴 | 100.0% |
| SK | Slovak | 🇸🇰 | 100.0% |
| TUR | Turkish | 🇹🇷 | 100.0% |
| DED | Дед (Angry Grandpa) | 🇷🇺 | 100.0% |

All 33 locales carry the same 939 keys; coverage is COMPUTED against en.json
by `scratch/validate_saitranslate.py`, never read from the stored field.
Missing keys fall back to English at runtime via the `tr()` engine.

## Drift log

- 30.07: en.json 802 -> 874 (72 unregistered `tr()` keys from T-589..T-632; TUR 17 gaps repaired, 9 locales 1 each)
- 31.07: en.json 874 -> 876 — `Rename image` (`tr()` in editor.py, c04c3e8) and `🤍 Support developer` (hardcoded button in help_dialog.py, uncommitted user work). All 29 non-Core locales via dedicated translator instance; RU/EST/DED by Core. The help_dialog button is still hardcoded English in code — integration must wrap it in `tr()` (future ADD/PLAN ticket, not TRANSLATE's scope).
- 01.08: en.json 876 -> 939 — repair: the sync regex only captured single-line `tr()` fragments, so 63 multi-line tooltip keys (main.py, header_format_dialog.py, timer_dialog.py, ctrlw_settings.py, queue_panel.py, translations.py, send_selection_mixin.py, watcher_dialog.py, window_mixin.py, window_presets_dialog.py) were never registered and silently fell back to EN — the old 100% was a false 100% (validator compares locales vs en.json, never source vs en.json; the AST-vs-en check is the real one). RU/EST/DED hand-translated, 29 other locales via GoogleTranslator (same pipeline as prior runs). Validator PASSED 33/33 939 keys.

## Format

Each JSON file:
```json
{
  "_meta": { "code": "...", "name": "...", "name_native": "...", "flag": "..." },
  "coverage_pct": 100.0,
  "translations": { "EN key": "translated string" }
}
```

## Translated docs

`kitchen/docs/{ru,est,ja,de}/` — 16 markdown files each, mirroring `docs/wiki/`.

## Integration

This bundle sits in `.saipen/saitranslate/kitchen/` per TRANSLATE phase isolation rules (`RFC.md § 2.1`).
Integration into the main project requires a future ADD/PLAN ticket through normal VERIFY/REVIEW/SHIP.
