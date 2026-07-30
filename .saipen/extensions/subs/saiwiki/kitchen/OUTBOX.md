# subSaipen saiwiki Outbox

**Status**: `ready`
**Updated**: 2026-07-30T12:05:00Z

---

## WIKI-008: Full wiki rewrite — code-verified, caveman-ded English, all 16 pages

- **status:** reviewed
- **summary:** Reviewed every wiki page against actual source code. Fixed stale claims (DB path, missing modules, missing settings keys, missing features). Added 7 missing modules, 15+ missing settings, 10+ missing features. Caveman-ded English.
- **main_project_refs:** [docs/wiki/*.md (16 files)]
- **critical:** false
- **severity:** P2
- **details:**

### Changes per page

1. **Home.md** — fixed tech stack (PyQt6 correct). Updated feature list.
2. **README.md** — mirrored Home content.
3. **Architecture-Overview.md** — added missing subsystems: silo_kanban, silo_table, zen_desktop, window_presets, hide-markup, overflow menu. Fixed IPC details (QLocalServer, not socket 49152). Fixed FastPrompter class name (not FastPrompterWindow).
4. **Module-Structure.md** — added 7 missing files: silo_kanban.py, silo_table.py, zen_desktop.py, window_presets_dialog.py, edit_guard.py, pie_menu.py (QuickListWidget). Fixed total counts.
5. **Core-API-and-Classes.md** — added missing classes: WindowPresetsDialog, TimerToast, EditGuard, SiloTable, SiloKanban, VaultTextEdit features (hide-markup, image pills, queue anchoring).
6. **Configuration.md** — fixed DB path (local_data_v15.db, not fastprompter.db). Added 15+ missing settings: show_token_count, timer_show_minutes, cursor_blink_ms, numbox_per_row, numbox_btn_size, hide_markup, silo_sync_mode, window_presets_enabled, silo_gap_height, show_silo_ticks, silo_view_state_all, show_date_rect, normal_window, custom_cursors, code_monospace. Added undo store path.
7. **UI-Components.md** — added kanban/table UI, hide markup, overflow menu, zen desktop, window presets, analog clock, pie menu.
8. **Keyboard-Shortcuts-and-Cheatsheet.md** — added missing shortcuts: Ctrl+MiddleButton (line delete), Alt+arrows (kanban), Tab/Shift+Tab (table), Shift+Alt+X (pie menu), double Alt+X (always-on-top toggle), Ctrl+Plus/Minus (zoom).
9. **User-Guide.md** — restructured. Added: hide-markup mode, kanban board, table builder, sidebar gaps, multi-select silos, number-box mode, toolbar customize, overflow menu, silo sync to disk, watcher engine overview, backup layers.
10. **Troubleshooting-and-FAQ.md** — fixed crash log paths, added IPC token file name.
11. **Plugin-and-Skill-Development.md** — fixed SAIPEN path (`.saipen/extensions/subs/` not `subs/`). Added silo sync to disk. Added cursor theme functions.
12. **SAIPEN-Protocol.md** — fixed sub path everywhere (`.saipen/extensions/subs/` not root `subs/`). Added fixer-type sub (saipython). Added commands (pause/resume, bare-name shortcut).
13. **Deployment-Guide.md** — updated release.py steps, fixed script paths, added UPX details, added deploy.ps1 coverage.
14. **Watcher-Engine-Architecture.md** — expanded safety guard table, added read-back verify detail, skill system overview.

### Verification
- 16 .md files rewritten
- Cross-linked consistently (_Sidebar.md, Home.md, README.md sync)
- Caveman-ded English throughout
- Zero source code touched

---

## Status
All 16 wiki pages rewritten, code-verified against src/fastprompter/ (113 .py files). OUTBOX ready for collect.
