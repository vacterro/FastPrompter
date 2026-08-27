# OUTBOX

## TRANSLATE-010: ee re-cut @ ef017ec (26.08.26)
- **status:** stale
- **legacy:** true
- **critical:** false
- **summary:** FORCE-FRESH re-cut for ee against HEAD ef017ec4b911a078c757d14eb3b34f590c511e03. Delta since TRANSLATE-009 (3d0d79ed): 52 new i18n keys added to en.py (49 interval notification UI strings + 4 pomodoro phase-completion sounds + 1 extra). Core4 (.py): en/ru/est/ded all have the 52 new keys with full translations. Non-Core29 (JSON): 33/33 locales now have 1210 keys each (was 1158). Core4 locale translations (ru/est/ded) are professional quality. Non-Core29 locale translations for the 52 new keys are English placeholders — flagged for human review in the next translation pass. _container.py also gained ISO-2 alias support (ET/EE→EST, FR→FRA, ES→SPA, UA/UK→UKR). All 33 locale JSONs structural-verified.
- **producer:** saitranslate
- **source_head:** ef017ec4b911a078c757d14eb3b34f590c511e03
- **source_tree_fingerprint:** git-delta-v1:pending
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 33/33 locales (4 Core + 29 non-Core) verified; 1210 keys per locale matching en.py; Core4 professional translations, non-Core29 English placeholders pending review
- **payload:** 33 locale JSON files (en.json, ru.json, est.json, ded.json, ar.json ... zh.json) — all in .saipen/saitranslate/locales/
- **verified:** PASS -- en.py <-> en.json key delta = 0; non-Core29 key coverage = 100% (1210/1210); structural JSON parse OK for all 33 files
- **instructions:** 1. Replace src/fastprompter/core/i18n/*.json with the corresponding kitchen locale JSONs (or integrate via the saitranslate collect mechanism). 2. Core4 (en/ru/est/ded) JSONs should match their .py source translations. 3. Non-Core29 JSONs have English placeholders for the 52 new keys — a follow-up translation pass with native speakers is recommended. 4. Commit with message: chore(i18n): TRANSLATE-010 — 52 new keys for interval notifications + pomodoro sounds across 33 locales
- **details:**
  v0.8.55 added 49 interval notification UI strings (tabs, labels, presets, descriptions) to en.py. Core4 locales (ru/est/ded) received professional translations inline. 4 additional pomodoro phase-completion sound keys were also missing from the JSONs. Non-Core29 locales were synced to match en.py's 1210 key count but the 52 new keys carry English placeholder values. _container.py gained ISO-2 language alias support (ET/EE→EST, FR→FRA, ES→SPA, UA/UK→UKR) — no locale file changes needed for this.
