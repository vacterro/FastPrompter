## DOING
- [ ] T-019 Day-part word in date clock (Morning/Day/Evening/Night after time) | files: main.py | verify: pytest tests_smoke/ -q | ui

## TODO
- [ ] T-020 Header button (Ctrl+E action) in toolbar button bar | files: main.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-023 File count on header 📁 btn + rich hover tooltip (per-ext counts, sizes) on all 📁 buttons | files: main.py, snippet_panel.py, file_container.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-022 File panel view modes: Icons/List/Details cycle like Explorer, persisted | files: file_container.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-026 Clipboard -> file button in container (text clipboard saved as .txt) | files: file_container.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-025 File links in container: import-as-link (.lnk via WScript.Shell), open resolves target | files: file_container.py | verify: pytest tests_smoke/ -q + MANUAL | ui
- [ ] T-024 Drop text-based file on editor -> ask: insert as text / add to silo files | files: editor.py, main.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-027 Configurable files root: setting + folder picker, _files_root reads data[files_root] | files: main.py, snippet_ops_mixin.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-021 Collapsible code blocks + # headers (fold via block.setVisible; spike first — QTextEdit layout may ignore hidden blocks) | files: editor.py, markdown_highlighter.py | verify: pytest tests_smoke/ -q | ui
- [ ] T-028 REVIEW wave + ship v0.5.0 | verify: release URL live | needs: T-019 T-020 T-022 T-023 T-024 T-026 T-027

## DONE (this wave)
- [x] T-017 Regression pass prior features (verified: 462 smoke + 461 unit PASS, conf: high)
- [x] T-018 Backup to N:\__SAVE_N\_SOFT\_FastPrompter (verified: robocopy exit 1 = copied, conf: high)

## DONE (archive)
- [x] T-001..T-011 v0.4.0 wave — see LOG/tags
- [x] T-012 Container symmetry + P0 trash-not-delete fix (verified: test_clear_silo_moves_files_to_trash_not_delete PASS, conf: high)
- [x] T-013 Ruff clean 0 errors (verified: ruff check PASS, conf: high)
- [x] T-014 state.py catches log warnings (verified: grep + tests, conf: high)
- [x] T-015 _fence_is_opener O(1) via CODE_BIT (verified: smoke PASS, conf: high)
- [x] T-016 folded into T-028 manual checklist
