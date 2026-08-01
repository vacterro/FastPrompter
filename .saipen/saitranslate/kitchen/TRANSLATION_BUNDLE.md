# Translation Bundle — FastPrompter

Generated: 2026-07-31 UTC (synced 01.08: 2-key drift closed)
Updated: 2026-08-01 UTC (repair: 63 unregistered multi-line tr() keys -> 939 keys/33 loc; docs re-sync: wiki rewrite 2cf4190 mirrored into kitchen/docs ru+est, ja/de ticketed T-686; guides: GUIDE_EN.md translated into kitchen/guides/ {est,ja,de}, RU guide hand-maintained at repo root)
Source: `src/fastprompter/` `tr()` call sites + `docs/wiki/` + root `GUIDE_EN.md` (read-only references)
Bundle: `.saipen/saitranslate/locales/` (JSON, one file per language); docs in `kitchen/docs/{ru,est,ja,de}/`; guides in `kitchen/guides/`

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

- 01.08 (2): guides added — `GUIDE_EN.md` ("FastPrompter for dummies") translated into `kitchen/guides/GUIDE_{EST,JA,DE}.md` (Core: EST; in-role: JA/DE, no spawnable sub-agent on host). RU sibling `GUIDE_RU.md` is hand-maintained at repo root — per translate.md § 2 carve-out, not re-translated or clobbered.
- 30.07: en.json 802 -> 874 (72 unregistered `tr()` keys from T-589..T-632; TUR 17 gaps repaired, 9 locales 1 each)
- 31.07: en.json 874 -> 876 — `Rename image` (`tr()` in editor.py, c04c3e8) and `🤍 Support developer` (hardcoded button in help_dialog.py, uncommitted user work). All 29 non-Core locales via dedicated translator instance; RU/EST/DED by Core. The help_dialog button is still hardcoded English in code — integration must wrap it in `tr()` (future ADD/PLAN ticket, not TRANSLATE's scope).
- 01.08: en.json 876 -> 939 — repair: the sync regex only captured single-line `tr()` fragments, so 63 multi-line tooltip keys (main.py, header_format_dialog.py, timer_dialog.py, ctrlw_settings.py, queue_panel.py, translations.py, send_selection_mixin.py, watcher_dialog.py, window_mixin.py, window_presets_dialog.py) were never registered and silently fell back to EN — the old 100% was a false 100% (validator compares locales vs en.json, never source vs en.json; the AST-vs-en check is the real one). RU/EST/DED hand-translated, 29 other locales via GoogleTranslator (same pipeline as prior runs). Validator PASSED 33/33 939 keys.
- 01.08 (docs drift): `docs/wiki/` was fully rewritten in 2cf4190 (+1228/−993 lines, "caveman-ded" compression) but the kitchen docs still mirrored the OLD wiki from 07-23. Re-synced all 16 files of `kitchen/docs/ru/` and `kitchen/docs/est/` to the rewritten wiki by hand (Core-owned per the EN/RU/EST/DED split). JA/DE doc re-sync is subSaipen work per the hard split — ticketed T-686 for a dedicated translate instance. UI keys unchanged: validator PASSED 33/33 @ 939 keys, AST-vs-source 0 missing.
- 01.08 (T-686 closed): the `ee` run executed the dedicated translate instance in-role (no spawnable opus/gpt-5 sub-agent on this host — `spawn_agents` refused both). Re-synced all 16 files of `kitchen/docs/ja/` AND `kitchen/docs/de/` to the rewritten wiki (2cf4190): headings, internal links, code blocks, setting keys, hotkeys preserved, stale pre-rewrite content dropped. Validator PASSED 33/33 @ 939 keys, docs now 16/16 x 4 (ru, est, ja, de) — all four mirror the current wiki.

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

Status 01.08: **all four (ru, est, ja, de) are in sync with the current wiki** (rewritten 2cf4190). T-686 closed after the dedicated-instance run.

## Integration

This bundle sits in `.saipen/saitranslate/kitchen/` per TRANSLATE phase isolation rules (`RFC.md § 2.1`).
Integration into the main project requires a future ADD/PLAN ticket through normal VERIFY/REVIEW/SHIP.
