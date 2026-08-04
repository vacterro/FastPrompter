# Translation Bundle — FastPrompter

Generated: 2026-07-31 UTC (synced 01.08: 2-key drift closed)
Updated: 2026-08-02 UTC (T-693 closed: 4 transform-menu keys added -> 943 keys/33 loc, wrapped in tr(), integrated + shipped v0.8.8; docs/guides unchanged)
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

All 33 locales carry the same 971 keys; coverage is COMPUTED against en.json
by `scratch/validate_saitranslate.py`, never read from the stored field.
Missing keys fall back to English at runtime via the `tr()` engine.

## Drift log

- 04.08.26 [v0.8.10–v0.8.13 + T-715] T-731 closed: 11 new `tr()` keys wrapped in `main.py`/`editor.py` across v0.8.10–13 (image-paste style ×5 from T-724, silo tab-mode ×5 from T-718, `▤ Fill from preset` from T-715) added to all 32 non-EN locales (943 -> 971). RU/EST/DED hand-translated (Core split); 29 other locales via GoogleTranslator (same pipeline as prior runs) with 72 manual fixes for pass-through labels. Existing translations untouched (0 changed, 0 removed per locale — verified by git diff). Validator PASSED 33/33 @ 971 keys, 0 missing.
- 02.08.26 [v0.8.8] T-693 closed: `✨ Transform to…`, `📄 Text`, `📊 Table`, `📋 Kanban Board` wrapped in `tr()` in main.py and added to every locale (939 -> 943). Bundle re-injected via `scratch/inject_translations.py`, shipped v0.8.8 (005d776, 99e0414). Validator 0 missing, 33/33 @ 943 keys (E-1160). No pending drift on any surface.
- 01.08.26 [v0.8.7] bundle INTEGRATED: 33 i18n modules regenerated from these JSON files via `scratch/inject_translations.py` (the one script that does it — future bundle syncs run it, never hand-write modules). 939 keys each, 100% coverage. T-693 tracks 4 hardcoded transform-menu strings (main.py) still missing from the bundle.
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

Status 04.08 (ee): all four (ru, est, ja, de) re-synced to the wiki at HEAD 8199480 (5 pages moved since 42347fe: Configuration — Golden Default/9-theme list, 18pt font, hotkey swap Alt+E/Alt+S, sound_enabled, hr_visual_line/live_preview_conceal/sync_mode/silo_ticks_enabled renames, 33 locales; Module-Structure — default_profile.py, 16 core modules, 115 total, 9 themes; Keyboard — Alt+E lock / Alt+S always-on-top; Core-API — play()/play_click()/play_tick() sound dispatch; Architecture — 9 built-in themes). T-686 closed after the dedicated-instance run; this ee run re-translated the 5 drifted pages in-role (T-688 remains open for the spawn path).

## Integration

Integrated at v0.8.8 (T-691/T-693): 33 i18n modules regenerated from these JSON files via `scratch/inject_translations.py`, support-button + transform-menu strings wrapped in `tr()`, guides copied to repo root. Bundle lives in `.saipen/saitranslate/kitchen/` per TRANSLATE phase isolation rules (`RFC.md § 2.1`); future bundle syncs re-run `scratch/inject_translations.py`, never hand-write modules.
