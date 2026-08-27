# OUTBOX

## TEST-004: crew SC-3 re-reproduction @ 40a0213 (27.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (40a0213: pie-menu Shift+F15 direct-insert fix). No new hypotheses from HUNT-012 (all six signals NOT_REPRODUCED). Prior verdicts stand: instance_lock.py:143 and duration.py:137 NOT_REPRODUCED (contract-correct). Unit suite green at new HEAD.
- **critical:** false
- **severity:** P2
- **producer:** saitest
- **source_head:** 40a021365f3641d52924ef2e3bb415aee1ee6d98
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:801fbfdc4be680d87b18cd21e6246d83fad5b474ebd7fe82efa83918cecf2f08
- **coverage:** delta audit 40a0213 vs 9d0331c; full unit suite; prior hypotheses re-checked at new HEAD
- **payload:** []
- **verified:** PASS -- pytest tests/ 1657 passed 1 skipped at 40a0213; no new hypotheses to reproduce
- **instructions:** Evidence for SC-3 at 40a0213. No new hypotheses; no fixer targets.

## TEST-002: crew SC-3 re-reproduction @ 3232878 (23.08.26)
- **status:** reviewed
- **summary:** Re-certification after source mutation (f3801af→3232878). Delta = theme QSS + Cyrillic test exemptions (T-1043/T-1041) — no new hypotheses to reproduce. Prior verdicts stand: instance_lock.py:143 and duration.py:137 NOT_REPRODUCED (contract-correct), Cyrillic test exemption gap fixed by PY-001.
- **critical:** false
- **severity:** P2
- **producer:** saitest
- **source_head:** 32328787efe6596b8ca6de774a791d786815fa1e
- **source_tree_fingerprint:** git-delta-v1:c66baf69a8306f3b95dfc7badb5f72b088f8de8408e933efadc4d149721a1195
- **role_revision:** sha256:801fbfdc4be680d87b18cd21e6246d83fad5b474ebd7fe82efa83918cecf2f08
- **coverage:** delta audit 3232878 vs f3801af; prior HUNT-006 hypotheses re-checked against new HEAD
- **payload:** none
- **verified:** PASS -- unit suite 1511 pass 1 skip at 3232878; theme tests 55 pass; Cyrillic test 1 pass (exemption applied)
- **instructions:** Evidence for SC-3 at 3232878. No new hypotheses.

## TEST-003: reproduce current HUNT-008 and HUNT-009
- **status:** reviewed
- **summary:** Current-source adversarial run reproduces the root test collection failure and confirms the orphan patch-script set.
- **main_project_refs:** [test_timers_patch.py:1, test_timers_patch.py:32, patch.py, patch_board.py, patch_links.py, patch_main_reading_links.py, patch_paths_tests.py, patch_t1013.py, patch_test_links.py, patch_themes.py, patch_timer_dialog.py, patch_timer_dialog_tests.py, patch_timer_dialog_tests2.py, patch_timer_dialog_tests3.py, patch_timer_dialog_tests4.py, patch_timer_dialog_tests5.py, patch_timers_from_dict.py, patch_timers_limit.py, patch_timers_todict.py]
- **critical:** true
- **severity:** P1
- **producer:** saitest
- **source_head:** 3d0d79ed11b3e257892440ce3994a4bbbfa86cef
- **source_tree_fingerprint:** git-delta-v1:4466d0c339b905ec3c36047da9f344f9c21402a32cf01eef911803b2bc29b381
- **role_revision:** sha256:801fbfdc4be680d87b18cd21e6246d83fad5b474ebd7fe82efa83918cecf2f08
- **coverage:** input-abuse syntax parsing; environment/default pytest discovery; dead-artifact reference checks; no main-tree mutation
- **payload:** []
- **verified:** PASS -- Scenario A `python -c "import ast; from pathlib import Path; ast.parse(Path('test_timers_patch.py').read_text(encoding='utf-8'), filename='test_timers_patch.py')"` -> `SyntaxError: invalid non-printable character U+FEFF` at line 1. Scenario B `pytest -q --collect-only` -> `ERROR collecting test_timers_patch.py`, `SyntaxError` at line 32, `2535 tests collected, 1 error`. Scenario C checked each of 18 `patch*.py` names with repository-wide `rg` plus `git ls-files`: all `refs=0`, all `tracked=False`, no script executed. Verdicts: HUNT-008 **REPRODUCED**; HUNT-009 **REPRODUCED**.
- **instructions:** Core should route HUNT-008 to the fixer/cleanup owner, repair or explicitly archive the root artifact, then rerun default pytest; separately decide whether the 18 ignored patch scripts are recoverable before any deletion.
- **details:**
  Minimal reproduction needs only the root file and default pytest discovery; no application code path is involved. The AST probe exposes the BOM, while pytest reports the later malformed line after its source decoding. The orphan result is observational and safe: no file was changed or executed. Both scenarios end **REPRODUCED**.
