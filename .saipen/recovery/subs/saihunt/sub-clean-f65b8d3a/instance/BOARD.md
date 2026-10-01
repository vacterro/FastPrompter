## DOING

## TODO

## DONE

- [x] HUNT-014 (P1, failing-tests + orphan-artifacts) six-signal sweep @ dc9589d; delivered ready evidence in kitchen/OUTBOX.md | verify: pytest tests/test_t1358_cohort_publication.py -> 2 failed | next: saitest independent reproduction
- [x] HUNT-008 (P1, collection-blocker) reproduce root `test_timers_patch.py:32` syntax error under current source @3d0d79e; delivered ready evidence in kitchen/OUTBOX.md | verify: `python -m py_compile test_timers_patch.py` -> SyntaxError | next: saitest independent reproduction
- [x] HUNT-009 (P2, orphan-artifacts) reproduce 18 unreferenced root `patch*.py` scripts @3d0d79e; delivered ready evidence in kitchen/OUTBOX.md | verify: zero repository references, all ignored/untracked, no execution | next: Core disposition
- [x] HUNT-010 (P2, sweep-close) remaining four signals NOT_REPRODUCED in bounded pass @3d0d79e; delivered ready evidence in kitchen/OUTBOX.md | verify: source identity stable, focused feature tests previously green | next: downstream crew roles
- [x] HUNT-001 8 tests_smoke metaclass conflict during full-suite collection | reverified 01.10.26 @e5888a9: `pytest tests_smoke/{test_altw_upward,test_app_smoke,test_ctrlw_preview,test_font_survives_theme,test_header_settings,test_send_selection}.py --collect-only -q` -> 605 tests collected, no metaclass conflict
- **source:** saihunt HUNT @fd33d79
- **files:** tests_smoke/test_altw_upward, test_app_smoke, test_ctrlw_preview, test_font_survives_theme, test_header_settings, test_send_selection, test_settings_layout, test_silo_colors_per_tab
- **signal:** 1 (failing tests)
- **critical:** true
- **detail:** All 8 ERROR at collection with `TypeError: metaclass conflict`. Not i18n_build_scripts (same 8 fail with --ignore=i18n_build_scripts). Running individually works — import-time conflict when collected together. Suspect: cross-Qt-binding import (PyQt6 vs PySide6 mix).
- [x] HUNT-002 test_app_smoke.test_code_fence_gutter_and_states fails | reverified 01.10.26 @e5888a9: `pytest tests_smoke/test_app_smoke.py::test_code_fence_gutter_and_states -q` -> passed
- **files:** tests_smoke/test_app_smoke.py:1129
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** `assert ta._doc_has_code is False` — _doc_has_code is True. Likely regression from recent editor drop_overlay/pie_menu changes (HEAD~1).
- [x] HUNT-003 test_app_smoke.test_fuzz_ui_surfaces — _refresh_settings_cache missing | reverified 01.10.26 @e5888a9: `pytest tests_smoke/test_app_smoke.py::test_fuzz_ui_surfaces -q` -> passed
- **files:** tests_smoke/test_app_smoke.py:975
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** `AttributeError: 'FastPrompter' object has no attribute '_refresh_settings_cache'`. Method zero-grep in src/ (removed). Test still calls it. Related to T-240 (already tracked as no-op stub).
- [x] HUNT-004 5 scaling_mixin unit tests fail | reverified 01.10.26 @e5888a9: `pytest tests/test_scaling_mixin.py -q` -> 38 passed
- **files:** tests/test_scaling_mixin.py (TestCycleButtonScale)
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** 5 tests: test_cycles_to_next_scale, test_cycles_wraps_around, test_unknown_scale_defaults_to_1_0, test_persistence_called, test_cycles_from_0_75. Possible link to `ui_scale` default changed 1.0→0.5 in test_app_smoke (HEAD~1).
- [x] HUNT-005 fix_tests.py, fix_tests_2.py orphan root scripts | reverified 01.10.26 @e5888a9: `fix_tests.py` and `fix_tests_2.py` are absent from the repo root
- **files:** ./fix_tests.py, ./fix_tests_2.py
- **signal:** 6 (dead code, zero refs)
- **critical:** false
- **detail:** Zero refs from src/ or any config/CI file. Not listed in H-313 (which lists _fix_vi.py, _translate.py etc.). Delete or move to tools/.

## BLOCKED
