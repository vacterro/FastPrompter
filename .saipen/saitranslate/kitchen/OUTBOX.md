# OUTBOX

## TRANSLATE-002: fresh EE re-cut bound to shipped HEAD 0f3c5e4 (v0.8.37)
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the translation bundle against v0.8.37 (HEAD 0f3c5e4): 5 new `tr()` keys from v0.8.34..37 (backup/restore validation diagnostics T-789, "invalid filename" T-788, 2 help-dialog feature strings) added to the 4 Core-owned locales (en/ru/est/ded, 1020 -> 1025 keys, RU/EST/DED hand-translated); stored `coverage_pct` corrected to the computed 95.2 in the 29 subSaipen-owned locales (was 95.7). Validator: 0 missing from en.json; the only errors are the expected json<->module regeneration delta (5 keys x 4 Core modules) = the `eee` module-rebuild payload (E-1367 precedent). 29-locale translation gap + docs-translation lag remain named backlogs (E-1358).
- **producer:** saitranslate
- **source_head:** 0f3c5e43752ad335ed48de4891391b080443be16
- **source_tree_fingerprint:** git-delta-v1:f43f10d298a38fceda4e4c9821becaf5542d0c8fb25b0fa8141dc5137743c2e0
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 4 Core-owned locales at 100% (1025 keys each); 29 wider locales at 95.2% (49-key gap = legacy sound-label backlog + these 5 new keys, subSaipen pipeline E-1358). Docs translation lag vs wiki re-syncs 4b7109c/414e92a/6bf25c1 = named backlog, unchanged.
- **payload:** bundle sync only — `locales/en.json` (+5 source keys) and `locales/ru.json` / `locales/est.json` / `locales/ded.json` (+5 translated keys each, 1020 -> 1025), plus the stored `coverage_pct` 95.7 -> 95.2 in the other 29 locales. No module regeneration yet: en/ru/est/ded modules lag by exactly the 5 new keys — that is the `eee` regeneration payload (E-1367 precedent). Existing translations untouched (0 changed, 0 removed — diff is +20 key lines in 4 Core files and 29 one-line coverage_pct fixes).
- **verified:** `tools/validate_saitranslate.py` — 0 missing from en.json; errors limited to the expected 4-line json<->module regeneration delta; warnings at the documented backlog (283 unused-in-src advisory + 29 x 49 untranslated). All 33 locale JSONs parse; keys placed alphabetically; source escape form (`\n` real-newline, not `\\n`) matches the neighbouring live keys.
- **instructions:** `eee` → verify freshness (source_head 0f3c5e4, fingerprint f43f10d2, role_revision f241e6b8 == current) → run `tools/inject_translations.py` (regenerates en/ru/est/ded modules from the bundle, idempotent for the rest) → re-run `tools/validate_saitranslate.py` (expect module gate GREEN, same documented-backlog warnings) → claim ticket, mark OUTBOX reviewed, checkpoint, ship.
- **details:** The previous package (TRANSLATE-001, bound to c1d04f4, 08.08) was never collected and is superseded by this re-cut — its payload additions (the 5 Hide on Click-Out keys) are already inside this bundle, so nothing is lost. TRANSLATE-002 replaces it. Zero main-tree writes.
