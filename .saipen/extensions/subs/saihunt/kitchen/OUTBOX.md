# OUTBOX

## HUNT-013: crew SC-2 sweep @ df90eb8 (31.08.26) - v0.8.66 release
- **status:** ready
- **summary:** Current-source six-signal sweep at HEAD df90eb8 (v0.8.66 with Wave-6 persistence closure T-1166/T-1168, Alt+F drawer T-1167, launcher re-exec T-1161). All six signals clean: unit suite green (1748 passed 1 skipped), zero TODO/FIXME/HACK in persistence scope, no unverified commits (all commits attributed to tickets/ships), no new silent-failure or symmetry candidates in the shipped delta, no orphan files, no failing tests.
- **main_project_refs:** [src/fastprompter/core/state.py, src/fastprompter/main.py, tests/test_wave6_coordinator.py, tests/test_launcher_reliability.py]
- **critical:** false
- **severity:** P3
- **producer:** saihunt
- **source_head:** df90eb866ee193e562a1df378e7b5af4b1f6ea0d
- **source_tree_fingerprint:** git-delta-v1:9539ecf0ffaca2181d8abd735f691aa9f67422bdc1f6a6ab3c86db43066a1248
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** all six HUNT signals at df90eb8: tests, commit verification, stale markers, silent failure, symmetry, orphan artifacts
- **payload:** []
- **verified:** PASS -- pytest tests/ 1748 passed 1 skipped; rg TODO/FIXME/HACK src/fastprompter/core/state.py + main.py clean; git tree carries only attributable .saipen state + user 1.md; concurrency seam repeated 50x clean; compileall PASS
- **instructions:** Evidence for SC-2 at df90eb8. No defect signals; no patch required. Core may proceed to SC-3.

## HUNT-012: crew SC-2 sweep @ 40a0213 (27.08.26) — pie-menu insert fix
- **status:** reviewed
- **summary:** Current-source six-signal sweep at HEAD 40a0213 (pie-menu Shift+F15 direct-insert fix + OUTBOX grammar repairs). All six signals clean: unit suite green, zero TODO/FIXME/HACK in src, no unverified commits, no new silent-failure or symmetry candidates, no orphan files, no failing tests.
- **main_project_refs:** [src/fastprompter/main.py]
- **critical:** false
- **severity:** P3
- **producer:** saihunt
- **source_head:** 40a021365f3641d52924ef2e3bb415aee1ee6d98
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** all six HUNT signals at 40a0213: tests, commit verification, stale markers, silent failure, symmetry, orphan artifacts
- **payload:** []
- **verified:** PASS -- pytest tests/ 1657 passed 1 skipped; rg TODO/FIXME/HACK src clean; git tree clean (only runtime .saipen/cache state); except-pass sites pre-audited T-1030 unchanged
- **instructions:** Evidence for SC-2 at 40a0213. No defect signals; no patch required. Core may proceed to SC-3.

## HUNT-007: crew SC-2 re-sweep @ 3232878 (23.08.26)
- **status:** reviewed
- **summary:** Re-sweep after source mutation (f3801af→3232878: T-1043 theme token compliance + T-1041 Cyrillic test exemption). Delta audited — theme QSS + test exemptions only, no new defect signals. All six signals still clean at the new HEAD: unit 1511 green, zero TODO/FIXME/HACK in src, no orphan files, no unverified commits, no new silent-failure or symmetry candidates beyond the already-fixed ones.
- **critical:** false
- **producer:** saihunt
- **source_head:** 32328787efe6596b8ca6de774a791d786815fa1e
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** 6 signals x delta audit of 3232878 vs f3801af
- **payload:** none
- **verified:** PASS -- delta commits enumerated (3232878 = themes.py QSS + test_app_smoke exemptions); pytest tests/ 1511 pass 1 skip; rg sweep clean
- **instructions:** Evidence for SC-2 at 3232878. Prior finding T-1043/T-1041 shipped; no new work required.

## HUNT-008: broken root test artifact blocks default collection
- **status:** reviewed
- **summary:** The repository-root `test_timers_patch.py` is syntactically invalid, so default pytest collection cannot complete when the root test pattern includes it.
- **main_project_refs:** [test_timers_patch.py:32]
- **critical:** true
- **severity:** P1
- **producer:** saihunt
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** failing-test signal (bounded compile/collection probe); commit verification; TODO/FIXME/HACK scan; silent-failure scan; save/load and start/stop symmetry spot-check; orphan-artifact scan
- **payload:** []
- **verified:** PASS -- `python -m py_compile test_timers_patch.py` reproduces `SyntaxError` at line 32; the focused current-feature suite reached 76% before the headless app-smoke process stopped responding and was terminated; `pytest --collect-only tests tests_smoke` collects the declared suites but does not validate the extra root file.
- **instructions:** saitest must independently reproduce the root-file collection failure; Core should either remove the accidental root artifact or repair/move it into a valid test; rerun default `pytest -q` afterward.
- **details:**
  The file ends mid-comment/code (`ame = str(...) and description = str(...)`) at line 32. This is not a product-path failure, but it makes a normal repository-wide pytest invocation fail before tests can run if root discovery is enabled. Verdict: **REPRODUCED**.

## HUNT-009: unreferenced root patch scripts
- **status:** reviewed
- **summary:** Eighteen root-level `patch*.py` scripts have zero repository references and look like abandoned one-off mutation tooling.
- **main_project_refs:** [patch.py, patch_board.py, patch_links.py, patch_main_reading_links.py, patch_paths_tests.py, patch_t1013.py, patch_test_links.py, patch_themes.py, patch_timer_dialog.py, patch_timer_dialog_tests.py, patch_timer_dialog_tests2.py, patch_timer_dialog_tests3.py, patch_timer_dialog_tests4.py, patch_timer_dialog_tests5.py, patch_timers_from_dict.py, patch_timers_limit.py, patch_timers_todict.py]
- **critical:** false
- **severity:** P2
- **producer:** saihunt
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** dead-code/orphan signal; repository reference search; no mutation performed
- **payload:** []
- **verified:** PASS -- each listed filename has zero `rg` references outside itself and is not tracked by Git; no script was executed.
- **instructions:** Core should decide whether these are recoverable user work artifacts; if not, archive/remove them through an explicit cleanup ticket, then rerun the orphan scan.
- **details:**
  The scripts are outside `src/`, are ignored/untracked, and are not imported, documented, or invoked by project tooling. Because they may contain recoverable patch history, this is a report only. Verdict: **REPRODUCED**.

## HUNT-011: post-patch current-source sweep
- **status:** stale
- **legacy:** true
- **summary:** Current source re-sweep confirms collection and settings UI are fixed; only the previously observed unreferenced ignored patch scripts remain as a cleanup candidate.
- **main_project_refs:** [src/fastprompter/main.py:7145, test_timers_patch.py, patch.py, patch_board.py, patch_links.py, patch_main_reading_links.py, patch_paths_tests.py, patch_t1013.py, patch_test_links.py, patch_themes.py, patch_timer_dialog.py, patch_timer_dialog_tests.py, patch_timer_dialog_tests2.py, patch_timer_dialog_tests3.py, patch_timer_dialog_tests4.py, patch_timer_dialog_tests5.py, patch_timers_from_dict.py, patch_timers_limit.py, patch_timers_todict.py]
- **critical:** false
- **severity:** P2
- **producer:** saihunt
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:b9a0dd789d38af44dab2d83936761ef9d22e14d08449950b4815f6140cbcd576
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** all six HUNT signals after UI/root-test fixes; default collection; focused settings/theme regression; orphan reference scan
- **payload:** []
- **verified:** PASS -- AST parse and `pytest -q test_timers_patch.py` -> `1 passed`; default `pytest -q --collect-only` -> `2536 tests collected` with no collection error; focused UI/theme suite -> `47 passed`; 18 ignored root `patch*.py` scripts still have zero repository references and are untracked. Verdict: collection **NOT_REPRODUCED**; stale marker **NOT_REPRODUCED**; silent failure **NOT_REPRODUCED**; symmetry gap **NOT_REPRODUCED**; orphan artifact **REPRODUCED**.
- **instructions:** Core may collect this cleanup hypothesis; do not delete the ignored scripts without explicit artifact disposition. No further product patch required from HUNT.
- **details:**
  This package is a fresh source-bound recheck after T-1053. The root test artifact now parses and runs; the Editor settings geometry passes. The remaining orphan signal is intentionally non-destructive and preserves possible recovery history. Verdict: **REPRODUCED** only for the orphan-artifact signal; all other signals **NOT_REPRODUCED**.

## HUNT-010: remaining signals did not produce a new confirmed defect
- **status:** reviewed
- **summary:** The other four HUNT signals produced no additional new finding in this bounded pass.
- **main_project_refs:** [src/fastprompter/core/project_sync.py, src/fastprompter/core/typecheck.py, src/fastprompter/core/timers.py]
- **critical:** false
- **severity:** P2
- **producer:** saihunt
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:4edb04181cb07e0946afd06fbe711166fa9dcc403e56b52e9be3844f0a71b0a5
- **coverage:** commit verification; stale marker scan; silent-failure scan; symmetry spot-check; current feature regression tests
- **payload:** []
- **verified:** PASS -- current source identity stable; no new tracked TODO/FIXME/HACK in product code; exception handlers are non-empty or intentional cleanup paths; focused typecheck/sync/timer tests had passed in the preceding hardening run. Verdicts: commit verification **NOT_REPRODUCED**; stale marker **NOT_REPRODUCED**; silent failure **NOT_REPRODUCED**; symmetry gap **NOT_REPRODUCED**.
- **instructions:** no integration; keep HUNT-008 and HUNT-009 as the actionable findings and let downstream roles validate them.
- **details:**
  Existing broad exception handling and preset TODO text were inspected as intentional behavior or documentation/test fixtures, not ticketed as defects without a reproducible failure. Verdict: **NOT_REPRODUCED**.
