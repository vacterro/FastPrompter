# Board

## DOING

## TODO

## DONE

## BLOCKED

## HUNT-001: 8 tests_smoke metaclass conflict during full-suite collection
- **source:** saihunt HUNT @fd33d79
- **files:** tests_smoke/test_altw_upward, test_app_smoke, test_ctrlw_preview, test_font_survives_theme, test_header_settings, test_send_selection, test_settings_layout, test_silo_colors_per_tab
- **signal:** 1 (failing tests)
- **critical:** true
- **detail:** All 8 ERROR at collection with `TypeError: metaclass conflict`. Not i18n_build_scripts (same 8 fail with --ignore=i18n_build_scripts). Running individually works — import-time conflict when collected together. Suspect: cross-Qt-binding import (PyQt6 vs PySide6 mix).

## HUNT-002: test_app_smoke.test_code_fence_gutter_and_states fails
- **files:** tests_smoke/test_app_smoke.py:1129
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** `assert ta._doc_has_code is False` — _doc_has_code is True. Likely regression from recent editor drop_overlay/pie_menu changes (HEAD~1).

## HUNT-003: test_app_smoke.test_fuzz_ui_surfaces — _refresh_settings_cache missing
- **files:** tests_smoke/test_app_smoke.py:975
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** `AttributeError: 'FastPrompter' object has no attribute '_refresh_settings_cache'`. Method zero-grep in src/ (removed). Test still calls it. Related to T-240 (already tracked as no-op stub).

## HUNT-004: 5 scaling_mixin unit tests fail
- **files:** tests/test_scaling_mixin.py (TestCycleButtonScale)
- **signal:** 1 (failing tests)
- **critical:** false
- **detail:** 5 tests: test_cycles_to_next_scale, test_cycles_wraps_around, test_unknown_scale_defaults_to_1_0, test_persistence_called, test_cycles_from_0_75. Possible link to `ui_scale` default changed 1.0→0.5 in test_app_smoke (HEAD~1).

## HUNT-005: fix_tests.py, fix_tests_2.py orphan root scripts
- **files:** ./fix_tests.py, ./fix_tests_2.py
- **signal:** 6 (dead code, zero refs)
- **critical:** false
- **detail:** Zero refs from src/ or any config/CI file. Not listed in H-313 (which lists _fix_vi.py, _translate.py etc.). Delete or move to tools/.
