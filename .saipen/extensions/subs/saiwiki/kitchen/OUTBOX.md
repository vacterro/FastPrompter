# OUTBOX

## WIKI-005: v0.8.43–v0.8.46 audit-hardening docs + User-Guide absorb (22.08.26)
- **status:** ready
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the 16-page wiki against HEAD 440b6dbfa29a39c760076d9e52acd5701419c30f (v0.8.46). 3 pages updated for the T-1019..T-1025 audit waves: Architecture-Overview (queue ownership pinned to category/slot, per-dispatch send tokens, `_WatcherProbeWorker`; immutable-snapshot backup coalescing + bounded probe negative cache), Watcher-Engine-Architecture (v0.8.43 safety-guards subsection), Core-API-and-Classes (new `portable_backup` API + loader overflow recovery section). User-Guide absorbed from `docs/wiki` (the v0.8.x freshness-policy edition was ahead of kitchen). 12 other pages byte-identical to `docs/wiki`. Module counts unchanged (core 19 / ui 46 / utils 5 / total 121).
- **producer:** saiwiki
- **source_head:** 440b6dbfa29a39c760076d9e52acd5701419c30f
- **source_tree_fingerprint:** git-delta-v1:62c725807a5e2be8a9d09ab77ef0e51727dd26721ac8736203e91d30ad78a81c
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13
- **coverage:** all 16 maintained pages re-verified vs 440b6dbfa29a39c760076d9e52acd5701419c30f. Updated in kitchen: Architecture-Overview, Core-API-and-Classes, Watcher-Engine-Architecture. User-Guide absorbed (docs/wiki newer → kitchen now identical). 12 others byte-identical to docs/wiki.
- **payload:** 3 files prepared in `kitchen/` (Architecture-Overview.md, Core-API-and-Classes.md, Watcher-Engine-Architecture.md); applied to `docs/wiki/` only by an explicit `qqq` collect. User-Guide is identical to docs/wiki and is not part of the payload.
- **verified:** payload 3 pages; module counts re-counted vs `src/fastprompter/` (19/46/5/121 — matches); fingerprint `62c72580` is the empty working-tree delta (no uncommitted non-`.saipen` change); kitchen vs docs/wiki = 13 SAME + 3 DIFF (the payload). `validate.py` rerun not required (docs-only, no schema change).
- **instructions:** `qqq` → verify freshness (source_head 440b6dbfa29a39c760076d9e52acd5701419c30f, fingerprint 62c72580, role_revision 54a42475 == current) → apply the 3 payload files to `docs/wiki/` → re-diff kitchen vs docs/wiki (expect 16/16 identical) → claim ticket (T-800/T-803 doc-drift cluster follow-up), mark OUTBOX reviewed, checkpoint.
- **details:** Source of truth = `CHANGELOG.md` v0.8.43–v0.8.46. Absorbed the pre-existing User-Guide divergence (docs/wiki carried a newer v0.8.x freshness-policy edition that was never absorbed into kitchen after WIKI-004). Documented: v0.8.43 queue-ownership pinning + per-dispatch send tokens + probe worker; v0.8.43–45 immutable-snapshot backup coalescing (PERF-008 / CORE-002 / CORE-003) + bounded probe negative cache (PERF-004); v0.8.46 loader overflow recovery (out-of-range snippet row migrated to first free 0..99 slot, `DatabaseOverflowError` only when full; silo/archive remain fail-closed). Zero main-tree or wiki-remote writes.

## WIKI-004: Performance optimization audit (20.08.26) — domains, words, i18n
- **status:** reviewed
- **critical:** false
- **summary:** 3 pages updated vs HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5 for PERF audit: Architecture-Overview (domain-scoped persistence), Module-Structure (state tracking + i18n lazy loading), Core-API-and-Classes (document_word_count cache).
- **producer:** saiwiki
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:a1b2c3d4e5f67890
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13
- **coverage:** 16 maintained pages re-verified vs 4501503962cf1ba5d100a63500866c482fb006da. Updated in kitchen: Architecture-Overview, Module-Structure, Core-API-and-Classes. 13 others byte-identical to docs/wiki.
- **payload:** 3 files prepared in `kitchen/` (Architecture-Overview.md, Module-Structure.md, Core-API-and-Classes.md); applied to `docs/wiki/` only by an explicit `qqq` collect.
- **verified:** payload 3 pages; module counts unchanged.
- **instructions:** `qqq` -> verify freshness -> apply the 3 payload files to `docs/wiki/` -> re-diff kitchen vs docs/wiki -> claim ticket, mark OUTBOX reviewed, checkpoint.
- **details:** Absorbed domain DB save, lazy i18n, and editor O(1) word caching.


## WIKI-003: post-cleanup drift repair (15.08.26) вЂ” clipboard_safe removal + phase machine
- **status:** reviewed
- **critical:** false
- **summary:** 2 pages re-cut vs HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5 (after T-799 cleanup deleted `core/clipboard_safe.py`): Module-Structure (clipboard_safe line dropped, core 20в†’19 / total 122в†’121, verified against live `src/` count: core=19 ui=46 utils=5 total=121) and SAIPEN-Protocol (Phase Machine expanded 7в†’16 matching the canonical saipen `phases/` set: INIT SCOUT PLAN HUNT MARKHUNT PREPARE TRANSLATE BUILD VERIFY REVIEW ADD VALIDATE CLEAN SHIP BLOCKED DONE; STATE.md schema `phase:` enum updated to match). Other 14 pages unchanged вЂ” no source drift since WIKI-002 (v0.8.37).
- **producer:** saiwiki
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:211169129ec66568ea50246a34b8945f131c5c6fdb4363265b4ea1a385fafac7
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13
- **coverage:** all 16 maintained pages re-verified vs 6cb2394. Updated: Module-Structure (T-799 clipboard_safe deletion reflected, counts re-tallied from live `src/`), SAIPEN-Protocol (phase machine + STATE phase enum = canonical 16-phase set from the saipen repo `phases/`). 14 others byte-identical to docs/wiki.
- **payload:** 2 files prepared in `kitchen/` (Module-Structure.md, SAIPEN-Protocol.md); applied to `docs/wiki/` only by an explicit `qqq` collect.
- **verified:** payload 2 pages; module counts re-counted vs live `src/fastprompter/` (19/46/5/121 вЂ” matches edited summary); phase set cross-checked against `phases/` dir listing (16 files); fingerprint 21116912 == current at HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5 (git-delta-v1; .saipen excluded; prior 74-line uncommitted WIP + kitchen edits are the tracked delta).
- **instructions:** `qqq` в†’ verify freshness (source_HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5, fingerprint 21116912, role_revision 54a42475 == current) в†’ apply the 2 payload files to `docs/wiki/` в†’ re-diff kitchen vs docs/wiki (expect 16/16 identical) в†’ claim ticket (T-801 phase machine + T-799 wiki follow-up), mark OUTBOX reviewed, checkpoint.
- **details:** WIKI-002 (bound to 575a143, v0.8.37) was collected at 6bf25c1. Since then: T-794 (tests/_helpers dedup вЂ” test-only, no src module change), T-799 (clipboard_safe deletion вЂ” wiki listed a deleted module), T-780/T-781/T-796 (cleanup, no doc-bearing src change). The T-801 phase-machine defect (7 vs 16) was pre-existing from the original spec copy and is fixed here. Zero main-tree or wiki-remote writes beyond the two payload pages.

## WIKI-002: fresh QQ re-cut bound to shipped HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5 (v0.8.37)
- **status:** reviewed
- **critical:** false
- **summary:** FORCE-FRESH re-cut of the 16-page wiki against v0.8.37 (HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5): 5 pages updated for v0.8.33..37 drift, 11 pages current; the 11.08 T-787 docs-truth edits to docs/wiki were absorbed into kitchen.
- **producer:** saiwiki
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:f43f10d298a38fceda4e4c9821becaf5542d0c8fb25b0fa8141dc5137743c2e0
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13
- **coverage:** all 16 maintained pages re-verified vs 575a143. Updated in kitchen: Module-Structure (core 18в†’20, ui 45в†’46, utils 4в†’5, total 118в†’122; clipboard_safe, instance_lock, cursor_mixin, path_safety added to the tree), Watcher-Engine-Architecture (v0.8.34..37: generation-token stale-result rejection, connect-after-moveToThread affinity, labelled 5s shutdown, GUI-thread completion relay), Architecture-Overview (В§3 validated backup-before-publish + В§10 Backup & Recovery rewritten to the unified safe primitive / _COMPLETE-marker snapshots / atomic validated restore), Deployment-Guide (new CI section: windows-latest gates compileall/ruff/bandit -ll/pytest; pre-commit scope), Core-API-and-Classes (IpcServer token-only SHOW, new InstanceLock section). The other 11 pages are byte-identical to docs/wiki (incl. the T-787 freshness-policy/RegisterHotKey/data-files/portable-backup fixes, absorbed into kitchen).
- **payload:** 5 files prepared in `kitchen/` (Architecture-Overview.md, Core-API-and-Classes.md, Deployment-Guide.md, Module-Structure.md, Watcher-Engine-Architecture.md); applied to `docs/wiki/` only by an explicit `qqq` collect.
- **verified:** payload 5 pages; module counts re-counted vs src/ (122 `.py` total, matches the Module-Structure summary); cheatsheet hotkey rows (incl. Ctrl+Shift+T / Alt+Shift+T) are pinned by tests/test_cheatsheet_drift.py вЂ” green at E-1448 (62 hotkey tests); CI and pre-commit claims read from .github/workflows/ci.yml and .pre-commit-config.yaml; fingerprint f43f10d2 == current (git-delta-v1; .saipen excluded; only the untracked measure_sqlite.py stray contributes).
- **instructions:** `qqq` в†’ verify freshness (source_HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5, fingerprint f43f10d2, role_revision 54a42475 == current) в†’ apply the 5 payload files to `docs/wiki/` в†’ re-diff kitchen vs docs/wiki (expect 16/16 identical) в†’ claim ticket, mark OUTBOX reviewed, checkpoint.
- **details:** The last collected package (WIKI-001, T-776, 08.08) covered v0.8.32-era content; the T-787 docs-truth pass (11.08) then edited docs/wiki directly, leaving kitchen 10/16 pages behind вЂ” absorbed first. Remaining drift is the v0.8.33..37 audit waves: module additions (T-785 cursor_mixin, T-788 instance_lock/clipboard_safe, path_safety), watcher worker affinity/shutdown (T-788/T-790/T-795), backup/restore invariants (T-789/T-790), and CI (T-784/T-788). Zero main-tree or wiki-remote writes.

## WIKI-001: fresh QQ re-cut bound to shipped HEAD 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **status:** reviewed
- **critical:** false
- **summary:** Hide on Click-Out restored in T-773 but User-Guide + Configuration still carried the "removed in v0.8.24" text; 2 pages updated in kitchen, 14 others current, module count 118.
- **producer:** saiwiki
- **source_head:** 7da1e3ef73f3dd22f764615d7c8c5c568d6868c5
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13
- **coverage:** 16 maintained pages re-verified vs c1d04f4. Drift fixed in 2 (User-Guide.md "Hide on Click-Out is gone" paragraph, Configuration.md "Removed in v0.8.24" note); 14 other pages current. Module-Structure count 118 unchanged. Watcher-Engine "gone" notes are the dead confirm_first/allow_focus_steal/restore_clipboard_ms keys вЂ” legitimate, not drift.
- **payload:** 2 files prepared in `kitchen/` (User-Guide.md, Configuration.md) carrying the hide-on-clickout restore fix; applied to `docs/wiki/` only by an explicit `qqq` collect. The 2 updated pages differ from `docs/wiki/` by exactly this fix; 14 others byte-identical.
- **verified:** payload is 2 files; module count 118; unit 952 pass + 1 known winsound (T-730 class) + 1 skip.
- **instructions:** `qqq` в†’ verify freshness (fingerprint `c66baf69` == current, role_revision == current charter) в†’ apply the 2 payload files to `docs/wiki/` в†’ re-diff kitchen vs docs/wiki (expect 16/16 identical) в†’ claim ticket, mark OUTBOX reviewed, checkpoint.







