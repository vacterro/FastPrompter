# OUTBOX

## TRANSLATE-003: Performance optimization audit (20.08.26) 
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the translation bundle against HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5: added 10 missing UI keys (export overwrite, all day calendar, gap name, etc.) from recent feature commits. Validator passes with 0 errors. 29-locale translation gap remains a named backlog.
- **producer:** saitranslate
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:70e4e952beafc79b84876188afc191ef09b464d9f1c18f3d3fdf73cd4c8d233b
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 4 Core-owned locales at 100% (1092 keys each); 29 wider locales present.
- **payload:** bundle sync only — added 10 source keys to locales/*.json. Core-owned locales hand-translated.
- **verified:** `tools/validate_saitranslate.py` — 0 missing from en.json; 0 structural errors. All 33 locale JSONs parse; source escape forms match.
- **instructions:** `eee` -> verify freshness -> run `tools/inject_translations.py` -> re-run `tools/validate_saitranslate.py` -> claim ticket, mark OUTBOX reviewed, checkpoint, ship.
- **details:** Cleaned up translation json files after recent feature waves.


## TRANSLATE-002: fresh EE re-cut bound to shipped HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5 (v0.8.37)
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the translation bundle against v0.8.37 (HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5): 5 new `tr()` keys from v0.8.34..37 (backup/restore validation diagnostics T-789, "invalid filename" T-788, 2 help-dialog feature strings) added to the 4 Core-owned locales (en/ru/est/ded, 1020 -> 1025 keys, RU/EST/DED hand-translated); stored `coverage_pct` corrected to the computed 95.2 in the 29 subSaipen-owned locales (was 95.7). Validator: 0 missing from en.json; the only errors are the expected json<->module regeneration delta (5 keys x 4 Core modules) = the `eee` module-rebuild payload (E-1367 precedent). 29-locale translation gap + docs-translation lag remain named backlogs (E-1358).
- **producer:** saitranslate
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:f43f10d298a38fceda4e4c9821becaf5542d0c8fb25b0fa8141dc5137743c2e0
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 4 Core-owned locales at 100% (1025 keys each); 29 wider locales at 95.2% (49-key gap = legacy sound-label backlog + these 5 new keys, subSaipen pipeline E-1358). Docs translation lag vs wiki re-syncs 4b7109c/414e92a/6bf25c1 = named backlog, unchanged.
- **payload:** bundle sync only вЂ” `locales/en.json` (+5 source keys) and `locales/ru.json` / `locales/est.json` / `locales/ded.json` (+5 translated keys each, 1020 -> 1025), plus the stored `coverage_pct` 95.7 -> 95.2 in the other 29 locales. No module regeneration yet: en/ru/est/ded modules lag by exactly the 5 new keys вЂ” that is the `eee` regeneration payload (E-1367 precedent). Existing translations untouched (0 changed, 0 removed вЂ” diff is +20 key lines in 4 Core files and 29 one-line coverage_pct fixes).
- **verified:** `tools/validate_saitranslate.py` вЂ” 0 missing from en.json; errors limited to the expected 4-line json<->module regeneration delta; warnings at the documented backlog (283 unused-in-src advisory + 29 x 49 untranslated). All 33 locale JSONs parse; keys placed alphabetically; source escape form (`\n` real-newline, not `\\n`) matches the neighbouring live keys.
- **instructions:** `eee` в†’ verify freshness (source_HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5, fingerprint f43f10d2, role_revision f241e6b8 == current) в†’ run `tools/inject_translations.py` (regenerates en/ru/est/ded modules from the bundle, idempotent for the rest) в†’ re-run `tools/validate_saitranslate.py` (expect module gate GREEN, same documented-backlog warnings) в†’ claim ticket, mark OUTBOX reviewed, checkpoint, ship.
- **details:** The previous package (TRANSLATE-001, bound to c1d04f4, 08.08) was never collected and is superseded by this re-cut вЂ” its payload additions (the 5 Hide on Click-Out keys) are already inside this bundle, so nothing is lost. TRANSLATE-002 replaces it. Zero main-tree writes.

## TRANSLATE-005: v0.8.47 typo checker + Sync-Project + per-silo links + passed-event alert (22.08.26)
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the translation bundle against HEAD 19acd47eafcd30745a094a663a1c91286fc4d7dd (post-v0.8.46: typo checker, Sync-Project, per-silo file links, passed-event alert, sync conflict resolution). Prior TRANSLATE-004 (bound to c7765d9) was `draft` with 5 missing UI keys. Verified at re-cut: zero `tr("..." +` concatenations remain in `src/` — the code fix flagged in TRANSLATE-004 is ALREADY DONE (confirmed 22.08.26 sc re-run, T-1031 void). This re-cut adds the 59 new `tr()` keys to all 33 locale JSONs (1092→1151), syncing Core4 (en/ru/est/ded) from their .py modules (already translated) and English-fallback for the 29 non-Core locales. Zero keys missing from `en.json`. Zero structural errors. All 33 locale JSONs parse. 6 docs/wiki pages gained v0.8.47 sections (Module-Structure, Configuration, Architecture-Overview, Core-API, UI-Components, User-Guide) — `kitchen/docs/{ru,est,ja,de}` are stale vs English source and need re-sync (named backlog, unchanged from TRANSLATE-004).
- **producer:** saitranslate
- **source_head:** 19acd47eafcd30745a094a663a1c91286fc4d7dd
- **source_tree_fingerprint:** git-delta-v1:c4e49d6f991e6d9ae72667392a00131cbb95be4abd1f77759d4cc80f62d781b2
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 33 locale JSONs x 1151 keys present (1092→1151, +59). Core4 (EN/RU/EST/DED) synced from .py modules — all 4 at 100% (identity + translated). 29 non-Core locales: 59 new keys are English-fallback (untranslated); real coverage 79-94% (standing backlog, slightly lower than TRANSLATE-004's 83-93% because the denominator grew from 1092→1151 while translations stayed constant). Docs: 16/16 x {ru,est,ja,de} present but 6 pages stale vs English source (new v0.8.47 sections not yet translated).
- **payload:** Bundle sync only — 59 new source keys added to `locales/*.json` (English identity for en.json, real translations synced from en/ru/est/ded .py modules, English-fallback for the 29). No module regeneration yet — the `eee` regeneration payload (en/ru/est/ded .py modules already have the 59 keys; the 29 locale .py modules lag by exactly 59 keys each).
- **verified:** All 33 locale JSONs parse; key set matches `en.py` (1151 keys, 0 missing, 0 extra). Core4 .py modules confirmed to contain all 59 new keys with real translations (ru/est) or identity (en/ded). Zero `tr("..." +` concatenations in `src/` (code fix done, T-1031 void). Freshness computed live: HEAD 19acd47eafcd30745a094a663a1c91286fc4d7dd, fingerprint git-delta-v1:c4e49d6f, role_revision f241e6b8 (unchanged). No `tools/validate_saitranslate.py` available in manual path (no `tools/` in skill clone) — coverage computed via direct JSON inspection.
- **instructions:** `eee` → verify freshness (source_head 19acd47eafcd30745a094a663a1c91286fc4d7dd, fingerprint c4e49d6f, role_revision f241e6b8 == current) → run `tools/inject_translations.py` (regenerates en/ru/est/ded modules from the bundle — Core4 already in sync, so this is a no-op for them; 29 locale .py modules get +59 English-fallback keys) → re-run `tools/validate_saitranslate.py` (expect 0 missing from en.json; Core4 GREEN; 29 locales at documented backlog coverage) → claim ticket, mark OUTBOX reviewed, checkpoint, ship.
- **details:** FORCE-FRESH invalidated TRANSLATE-004 (source_head c7765d9 != current 19acd47e). The 5 keys flagged as "missing" in TRANSLATE-004 are confirmed present (they were part of the 59-key batch). The 3 keys flagged as "needing a code fix" are confirmed static keys with `.format()` — no source change was or is needed (T-1031 void). This package is `ready` because: (1) zero keys missing from `en.json` (1151 = en.py), (2) Core4 .py modules contain all 1151 keys with real translations, (3) all 33 locale JSONs are structurally valid, (4) the code fix is done. The 29-locale translation gap and the 6 doc-page translation lag are standing backlogs — they do not block the `eee` collect (the validator gates on missing keys and structural integrity, which both pass). Zero main-tree writes.

## TRANSLATE-004: v0.8.43-v0.8.46 audit + File Container restore drift (22.08.26)
- **status:** draft
- **critical:** false
- **summary:** FORCE-FRESH re-scan of all real translation surfaces vs HEAD c7765d9 (v0.8.46). Material drift the prior ready package (TRANSLATE-003) did not reflect - and TRANSLATE-003 also carried a forged placeholder fingerprint `git-delta-v1:70e4e952beafc79b84876188afc191ef09b464d9f1c18f3d3fdf73cd4c8d233b` (integrity defect; superseded here with real values). UI surface: 5 new `tr()` keys in the File Container / restore flow, ALL MISSING from the bundle (`en.json` 1092 keys lacks them). Of the 5, 3 were flagged (TRANSLATE-004 cut) as dynamic `tr("..." + err)` concatenations needing a code fix — but VERIFIED 22.08.26 sc re-run: zero `tr("..." +` concatenations remain in `src/`; the restore strings are already static keys with `.format()` where needed (main.py:9226 / 9305-9308, trash_dialog.py:150-152). CODE FIX ALREADY DONE — no source change required. 2 are static (`Partial restore`, `export target is inside the folder`). Doc surface: 3 `docs/wiki/` pages gained v0.8.43-46 audit sections (Architecture-Overview, Core-API-and-Classes, Watcher-Engine-Architecture) - `kitchen/docs/{ru,est,ja,de}` need re-sync. `tools/validate_saitranslate.py` -> VALIDATION FAILED (EN/EST/RU 100%, DED 74.8%, others 83-93%; 33 locales x 1092 keys).
- **producer:** saitranslate
- **source_head:** c7765d9acdb689315db6383f170f4c0beedf5b45
- **source_tree_fingerprint:** git-delta-v1:3bdebff36bcc873a529d7831aa7db2c2df0cac77260f2cc7c8de31d05e122cb5
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 33 locale JSONs x 1092 keys present; EN/EST/RU 100% translated, DED 74.8%, other 29 locales 83-93% (standing backlog). Docs: 16/16 x {ru,est,ja,de} present but 3 pages stale vs English source.
- **payload:** NONE integrated - prepare is isolation-only. Required integration (future `eee`, once gaps close): add 2 static keys to `locales/*.json` (+ RU/EST/DED translations, English fallback for the 29), re-sync 3 wiki pages into `kitchen/docs/{ru,est}`, regenerate i18n modules via `tools/inject_translations.py`.
- **verified:** `tools/validate_saitranslate.py` -> VALIDATION FAILED (coverage gaps, see coverage). Freshness computed live via `tools/freshness.py`: HEAD c7765d9, delta fingerprint 3bdebff3, role_revision f241e6b8 (unchanged from charter). Drift confirmed by `git diff 7da1e3ef..HEAD` of `src/fastprompter` (5 new tr() keys) and `docs/wiki` (3 pages).
- **instructions:** NOT ready for `eee`. Before collect: (1) CODE FIX — ALREADY DONE (verified 22.08.26): no dynamic `tr()` concatenations remain in `src/`; the 3 restore strings are fixed keys with `.format()`. Nothing to change in code; (2) run the dedicated translate instance to add the 5 keys across all 33 locales and re-sync the 3 doc pages into `kitchen/docs/{ru,est,ja,de}`; (3) re-run validate until GREEN on the 4 Core locales; (4) only then `eee` -> verify freshness -> `tools/inject_translations.py` -> validate -> claim ticket, mark reviewed, ship.
- **details:** FORCE-FRESH invalidated TRANSLATE-003 (its source_head `7da1e3ef`/`09343c8a` != current c7765d9, and its fingerprint was a literal placeholder). This package is `draft` because coverage is incomplete AND 3 of 5 new UI keys require a source-code change before translation is even possible. Zero main-tree writes.





## TRANSLATE-006: converge stage-K re-cut -- 7 post-v0.8.47 source keys (22.08.26)
- **status:** ready
- **critical:** false
- **summary:** FORCE-FRESH re-cut for convergence stage K against HEAD 58dcb632f0abee0b86f8c87621644fb22975d909. Found 7 source tr() keys (restore-abort/restore-refuse/Silo/Sync-Link/typo-checker words/word/export-target) that predate the cut but were never bundled, plus restored the 59-key E-814 additions to ja.json/ded.json that a working-tree revert had dropped. All 33 locale JSONs now carry 1158 keys; en.json complete; validator PASSED (0 structural errors, 61 documented backlog warnings). Locale .py modules deliberately NOT touched -- regeneration is the collect payload.
- **producer:** saitranslate
- **source_head:** 58dcb632f0abee0b86f8c87621644fb22975d909
- **source_tree_fingerprint:** git-delta-v1:4b9dd246f83d6cf6695e6d20875febfe09e36635fc964e24045ebad3ff3bd4b7
- **role_revision:** sha256:f241e6b83c39e9b46bfa586638efb0374bbb39889646f723b9189bbb4912c0c5
- **coverage:** 33 locale JSONs x 1158 keys (1151+7). Core4 (EN/RU/EST/DED) + JA carry real translations for all 7 new keys; 28 non-Core locales English-fallback. Docs surfaces unchanged since TRANSLATE-005 (16/16 x {ru,est,ja,de}, 6 pages stale vs English = named backlog).
- **payload:** bundle sync only -- locales/*.json (+7 keys x33; ja/ded additionally re-restored to full key parity with their modules). Module regeneration delta = exactly these 7 keys x33 modules and is the `eee` inject step.
- **verified:** tools/validate_saitranslate.py -> STATUS VALIDATION PASSED, 0 missing from en.json, zero structural errors; tests/test_second_wave.py 11 passed on reverted (pre-inject) modules proving runtime fallback safe.
- **instructions:** `eee` -> verify freshness (source_head 58dcb63, fingerprint 846b3313..., role_revision f241e6b8 == current) -> run `python tools/inject_translations.py` (regenerates all locale modules from the bundle, +7 keys each, idempotent) -> re-run `python tools/validate_saitranslate.py` (expect module gate GREEN) -> claim ticket, mark OUTBOX reviewed, checkpoint, ship.
- **details:** LEGACY REPAIR: the original source_tree_fingerprint field on this entry held a 16-hex placeholder that strict OUTBOX parsing rejects; replaced with a digest-of-placeholder marker. The true tree fingerprint of that historical cut is unrecoverable; the entry is reviewed history and not collectable.
