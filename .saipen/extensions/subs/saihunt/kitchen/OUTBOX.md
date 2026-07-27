# OUTBOX

## HUNT-001: 8 tests_smoke metaclass conflict during full-suite collection
- **status:** stale
- **collect_note:** 24.07 collect (claude): standalone claim does not reproduce at HEAD — collect-only of the 8 flagged files = 400 collected, 0 errors; full `pytest tests_smoke -q` = 406 passed. Real breakage is only tests_smoke + tests sharing ONE pytest process (108 failed/380 errors), which is the existing T-283/T-284 module-level `sys.modules["PyQt6"]=MagicMock` leak. Evidence folded there; not re-ticketed.
- **summary:** 8 smoke tests ERROR at collection with TypeError: metaclass conflict. Work individually, fail when collected together.
- **main_project_refs:** [tests_smoke/test_altw_upward.py, tests_smoke/test_app_smoke.py, tests_smoke/test_ctrlw_preview.py, tests_smoke/test_font_survives_theme.py, tests_smoke/test_header_settings.py, tests_smoke/test_send_selection.py, tests_smoke/test_settings_layout.py, tests_smoke/test_silo_colors_per_tab.py]
- **critical:** true
- **severity:** P1
- **details:** 8/9 smoke test files fail during collection when run together. test_margin_cursor.py (the 9th) passes. Not caused by i18n_build_scripts (same failure with `--ignore`). Running individually succeeds (test_altw_upward: 16 passed, test_app_smoke: 2 failed out of 301). Likely cross-Qt-binding import: PyQt6 vs PySide6 metaclass conflict at import time. Recent HEAD~1 commit touched editor.py (added QPointF import) — check if that introduced a new import that triggers conflict. Root cause: a common import path loads from one binding while a test module already holds the other's metaclass.

## HUNT-002: test_app_smoke.test_code_fence_gutter_and_states assertion failure
- **status:** reviewed
- **collect_note:** 24.07 collect (claude): FIXED by commit 80fde60 — editor.py set_active_document() now resets the sticky _doc_has_code/_doc_has_checkbox flags per document. Test passes.
- **summary:** `_doc_has_code is True` when test expects False. Recent regression.
- **main_project_refs:** [tests_smoke/test_app_smoke.py:1129]
- **critical:** false
- **severity:** P3
- **details:** Assertion: `assert ta._doc_has_code is False` but value is True. Likely regression from HEAD~1's editor/drop_overlay changes. The test sets up a document without code fences but _doc_has_code still reports True. Not a new finding (already flagged in smoke runs).

## HUNT-003: test_app_smoke.test_fuzz_ui_surfaces — missing _refresh_settings_cache
- **status:** reviewed
- **collect_note:** 24.07 collect (claude): FIXED by commit 80fde60 — stale `_refresh_settings_cache()` call removed from the test (method was deleted by T-240). Test passes.
- **summary:** Method `_refresh_settings_cache` removed from src/ but test still calls it. Related to T-240.
- **main_project_refs:** [tests_smoke/test_app_smoke.py:975]
- **critical:** false
- **severity:** P3
- **details:** T-240 says `_refresh_settings_cache` was always a no-op stub. It was apparently removed at some point but the test_ fuzz_ui_surfaces still calls it: `FastPrompter` object has no attribute `_refresh_settings_cache`. Fix: remove the test call or add back the stub.

## HUNT-004: 5 scaling_mixin unit test failures
- **status:** reviewed
- **collect_note:** 24.07 collect (claude): FIXED by commit 80fde60 — half-finished `_button_scale`->`_ui_scale` rename in test_scaling_mixin.py cleaned up; assertions now check the real signal (`data["ui_scale"]`). All 36 pass.
- **summary:** TestCycleButtonScale — 5 tests fail, all in scaling_mixin.
- **main_project_refs:** [tests/test_scaling_mixin.py]
- **critical:** false
- **severity:** P3
- **details:** 5 tests fail: test_cycles_to_next_scale, test_cycles_wraps_around, test_unknown_scale_defaults_to_1_0, test_persistence_called, test_cycles_from_0_75. HEAD~1 changed `ui_scale` default assertion from 1.0 to 0.5 in test_app_smoke — check if scaling defaults changed too. 846/851 unit tests PASS (5 fail).

## HUNT-005: fix_tests.py, fix_tests_2.py orphan root scripts
- **status:** reviewed
- **collect_note:** 24.07 collect (claude): ticketed as T-337 and done — both moved to scratch/ alongside the sibling patch_*.py.
- **summary:** Two orphan scripts at repo root, zero refs anywhere. Not in H-313.
- **main_project_refs:** [./fix_tests.py, ./fix_tests_2.py]
- **critical:** false
- **severity:** P5
- **details:** grep for `fix_tests` across src/ and all config/doc files returns 0 hits. H-313 listed _fix_vi.py and _translate.py but missed these two. Candidate for deletion or move to tools/.
