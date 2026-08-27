# OUTBOX

## TRANSLATE-011: ee re-cut @ 2f31e6d (27.08.26)
- **status:** ready
- **critical:** false
- **summary:** FORCE-FRESH re-cut for ee against HEAD 2f31e6df521d04b52f1327d5ed55d654b716f65f. Delta since TRANSLATE-010 (ef017ec): 2 new i18n keys (Reminder, interval reminder) from W2-005 interval top-bar visibility. Core4 (.py): en/ru/est/ded have the 2 new keys with full translations. Non-Core29 (.py): all 33 runtime modules now at 1212 keys each, matching en.py parity (was 1158, missing 52 from TRANSLATE-010 sync). All 33 locale JSONs in .saipen/saitranslate/locales/ synced to match.
- **producer:** saitranslate
- **source_head:** 2f31e6df521d04b52f1327d5ed55d654b716f65f
- **source_tree_fingerprint:** git-delta-v1:pending
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 33/33 runtime .py modules verified; 1212 keys per locale matching en.py; structural JSON parse OK for all 33 files
- **payload:** 33 locale .py modules (src/fastprompter/core/i18n/*.py) + 33 locale JSON files (.saipen/saitranslate/locales/*.json) — all 1212 keys, parity with en.py
- **verified:** src/fastprompter/core/i18n/ compileall OK; 33/33 key parity verified; structural JSON parse OK
- **instructions:** 1. Core4 (en/ru/est/ded) .py locale files have the 2 new keys with professional translations. 2. Non-Core29 .py locale files have English placeholders for all 54 new keys (52 from TRANSLATE-010 + 2 from W2-005) — a follow-up translation pass with native speakers is recommended. 3. The locale JSONs in .saipen/saitranslate/locales/ are synced and ready for external integration. 4. Commit the updated .py files with message: chore(i18n): TRANSLATE-011 - 2 new keys for interval top-bar visibility across 33 locales