# OUTBOX — saitranslate prepare handoff

- **status**: ready (Core-owned in-app bundle; gaps named below)
- **producer**: saitranslate
- **source_head**: `715c893` (HEAD at prepare time)
- **source_tree_fingerprint**: `7bf28a7b25a078826bacbeec008bb74e77859aae` (HEAD tree)
- **role_revision**: saitranslate role per `phases/translate.md` (no standalone charter file)
- **generated**: 2026-08-08 (ee / `saipen prepare saitranslate`)

## coverage

In-app surface re-verified against HEAD 715c893 (v0.8.30). 4 Core-owned locales now at **100%**; 29 wider locales at **95.7%** (documented sound-label backlog — subSaipen pipeline work, E-1358).

| Locale set | Keys | Coverage | State |
|---|---|---|---|
| EN / RU / EST / DED | 1015 each | 100.0% | **complete** — RU/EST/DED closed the v0.8.26 gap (missing `Picking a sound plays it…` key) and dropped 5 dead Hide-on-Click-Out orphans (dead since T-751/T-759) |
| 29 wider locales | 976 each | 95.7% | documented TRANSLATE backlog (44 sound-event labels untranslated, fall back to EN) — subSaipen work, not Core's split |

`coverage_pct` metadata repaired to honest computed values in **all 33** locale files (was stale: claimed 100.0/99300.0, real 95.7–100.0).

Translated docs (`kitchen/docs/{ru,est,ja,de}`, 16 pages each) lag the wiki v0.8.23..30 drift (RU User-Guide lacks §23 Sound & Hotkey Sounds) — named gap, dedicated docs-translation pass (RU/EST Core, JA/DE subSaipen).

## payload

Exact regeneration to apply to `src/fastprompter/core/i18n/` at collect:

1. Run `tools/inject_translations.py` — regenerates **all 33** modules from the bundle (writes ru/est/ded: +1 key, −5 orphans; en unchanged; coverage from `_meta` untouched).
2. Re-run `tools/validate_saitranslate.py` — json↔module gate goes green (the 6-key delta in ru/est/ded is exactly this regeneration).

## verified

- Bundle-side checks: EN/RU/EST/DED 1015 keys, 0 missing, 0 extra vs en.json; parity clean; `coverage_pct` honest in all 33.
- The json↔module gate currently reports the expected pending delta in ru/est/ded (5 orphans in module not in JSON + 1 new key in JSON not in module) — this is the payload above, resolved by regeneration at collect. No other locale affected.
- No source file touched by this prepare (bundle edits confined to `.saipen/saitranslate/locales/`).

## instructions

1. Run `tools/inject_translations.py` (regenerates all 33 i18n modules from the updated bundle).
2. Run `tools/validate_saitranslate.py` — expect PASS (json↔module gate green).
3. Commit + push via the normal collect + SHIP gates (`eee`).
4. The 29-locale sound-label gap and the docs-translation lag are separate named backlogs, not part of this payload.
