## DOING

## TODO
- [ ] T-016 MANUAL-VERIFY leftovers: container drag-out to Explorer, v0.4.0 EXE first launch, image preview no rescale on panel resize | verify: user confirms | ui

## DONE
- [x] T-012 File container symmetry: archive/delete/retitle silo orphans its folder silently; no file-count hint on buttons; archived silos can't reach their files | files: src/fastprompter/ui/file_container.py, main.py, snippet_panel.py | verify: pytest tests_smoke/ -q | ui
- [x] T-013 Dead imports + import order (ruff: datetime editor.py:4, QMimeData main.py:14, logger formatting_mixin.py:13, I001 editor.py) | verify: uv run ruff check src/ -> 0 errors
- [x] T-014 Silent catches in state.py settings parse (82, 110, 315: except-pass can eat corrupted DB rows) -> log warnings instead | files: src/fastprompter/core/state.py | verify: pytest tests/ -q
- [x] T-015 Perf: _fence_is_opener rescans doc from start inside paint loop -> O(n^2) with many fences; reuse highlighter CODE_BIT state | files: src/fastprompter/ui/editor.py | verify: pytest tests_smoke/ -q | perf
- [x] T-001 Double Line toggler (verified: smoke PASS, conf: high)
- [x] T-002 Divider -> \n\n---\n\n\n bullet (verified: smoke PASS, conf: high)
- [x] T-003 Code block detect + monospace + auto gutter (verified: smoke PASS, conf: high)
- [x] T-004 Bold # titles toggle (verified: smoke PASS, conf: high)
- [x] T-005 Date rectangle top-right (verified: test_date_rectangle_formats_and_toggles PASS, conf: high)
- [x] T-006 Backup to N:\__SAVE_N\_SOFT\_FastPrompter (verified: 85 files robocopy, conf: high)
- [x] T-007 Inline copy button on code blocks (verified: test_code_block_copy_button PASS, conf: high)
- [x] T-008 Divider spacing spins 0-6/1-6 (verified: test_divider_spacing_configurable PASS, conf: high)
- [x] T-009 Antigravity work verified: date clock hh:mm:ss + ss toggle, right-click auto-bullet, pinned gap toggle (verified: 58 smoke PASS, conf: high)
- [x] T-010 File container per silo: file_container.py panel, drop/drag/preview/export, folder per title slug, hover 📁 + header 📁, help updated (verified: 3 smoke tests PASS, conf: high — drag-out/os.startfile MANUAL-VERIFY)
- [x] T-011 REVIEW + ship v0.4.0 (verified: release URL live, EXE 26.5 MB uploaded, conf: high)
