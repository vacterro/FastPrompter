# SubSaipen saiwiki Board

## DOING

## TODO

## DONE
- [x] T-028 Post-v0.8.33..37 drift repair (qq 14.08): 5 wiki pages re-synced to HEAD 575a143 (v0.8.37) -- Module-Structure (core 18->20 / ui 45->46 / utils 4->5 / total 122; clipboard_safe, instance_lock, cursor_mixin, path_safety), Watcher-Engine-Architecture (v0.8.34..37: generation-token stale rejection, connect-after-moveToThread affinity, labelled 5s shutdown, GUI-thread completion relay), Architecture-Overview (validated backup-before-publish, _COMPLETE-marker snapshots, atomic validated restore), Deployment-Guide (new CI section), Core-API-and-Classes (token-only SHOW, InstanceLock). Kitchen absorbed the 11.08 T-787 docs-truth edits (10 pages). OUTBOX ready source_head 575a143, 5-file payload. Zero source modified. | verify: docs/wiki pages match kitchen copies after collect (5 files)
- [x] T-027 Post-v0.8.28..30 drift repair (qq 08.08): 2 wiki pages re-synced to HEAD 8ad58aa — User-Guide (§23 Sound & Hotkey Sounds: v0.8.28 rainbow experiment reverted in v0.8.29, icons stay in the theme family with glyph-shape distinction, 13 new pictograms split the confusable pairs; v0.8.30 zebra rows never white via alternate-background-color in the shared theme table sheet), UI-Components (Sound Settings row + T-737 header/grid bullet gained the v0.8.30 alternate-background-color). Kitchen mirrored, OUTBOX ready source_head 8ad58aa, 2-file payload. Zero source modified. | verify: docs/wiki pages match kitchen copies after collect (2 files)
- [x] T-026 Post-v0.8.23..27 drift repair (qq 07.08): 4 wiki pages re-synced to HEAD 501acd0 -- User-Guide (Sound Settings pictograms, Hide-on-Click-Out removal), UI-Components (Sound Settings row), Watcher-Engine-Architecture (limits applied, CDP-only blocker, CDP no-HWND, queue detach/revive), Configuration (close_on_focus_loss removal + watcher limits). Kitchen mirrored, OUTBOX ready source_head 501acd0, 4-file payload. Zero source modified. | verify: docs/wiki pages match kitchen copies after collect (4 files)
- [x] T-025 Post-v0.8.22 drift repair (qq 07.08): 3 wiki pages re-synced to HEAD 4f5ae12 — User-Guide (timer picks any sound T-741, hotkey generic ships ON T-742, Ctrl+Z single sound), UI-Components (timer dialog sound picker, generic hotkey ON), Core-API-and-Classes (SoundManager play_file). Kitchen mirrored. OUTBOX ready source_head 4f5ae12, 3-file payload. Zero source modified. | verify: docs/wiki pages match kitchen copies after collect (3 files)
- [x] T-023 Post-T-732..T-738 drift repair (qq 05.08, second run): 3 wiki pages re-synced to HEAD 60e3c20 + uncommitted T-734..T-738 — Module-Structure (core/silo_export.py added, core 17→18, total 117→118), User-Guide (§3 drag-OUT-to-Explorer T-738, §15 tabular Name/Time/Remaining list T-733 + clickable toast T-736, new §23 Sound & Hotkey Sounds T-735, Backup renumbered §24), UI-Components (Sound Settings hotkey events, Timer Dialog table row, header_view_qss T-737). Kitchen mirrored, OUTBOX ready source_head 60e3c20, 3-file payload. Zero source modified. | verify: docs/wiki pages match kitchen copies after collect (3 files)
- [x] T-001 Create wiki index: architecture overview
- [x] T-002 Document module structure
- [x] T-003 Document API & Core classes
- [x] T-004 Document configuration & settings
- [x] T-005 Document UI components
- [x] T-006 Document User Guide, Hotkeys & Workflows (_user_guide.md)
- [x] T-007 Document SAIPEN & SubSaipen Architecture (_saipen_guide.md)
- [x] T-008 Document Build, Packaging & Release Deployment (_deployment.md)
- [x] T-009 Assemble master Home.md and _Sidebar.md for GitHub Wiki format
- [x] T-010 Format & copy draft pages into clean GitHub Wiki structure
- [x] T-011 Cross-link validation and page footer (_Footer.md)
- [x] T-012 Create GitHub Wiki synchronization script (tools/sync_wiki.py)
- [x] T-013 Mirror completed wiki pages to main project docs/wiki/
- [x] T-014 Create Troubleshooting & FAQ page (Troubleshooting-and-FAQ.md)
- [x] T-015 Create Keyboard Shortcuts & Cheatsheet page (Keyboard-Shortcuts-and-Cheatsheet.md)
- [x] T-016 Create Watcher Engine Deep Dive (Watcher-Engine-Architecture.md)
- [x] T-017 Create Plugin, Skill & MCP Development Guide (Plugin-and-Skill-Development.md)
- [x] T-018 Update Home.md and _Sidebar.md with all new pages & mirror to docs/wiki/
- [x] T-019 Post-rewrite drift repair (qq 03.08): 5 wiki pages re-synced to HEAD 60dda3e — saipen_dialog (deleted c384711) purged from Module-Structure/Core-API/UI-Components/Keyboard/User-Guide; Ctrl+Shift+C corrected to Clear (main.py:8842); kanban_widget/table_widget/silo_region + i18n 33 locales + real module counts (112 py) added; Alt+MiddleButton/MiddleButton/Ctrl+Shift+drag/pill-rename documented (3ce4357, T-645). Kitchen re-synced to 16 wiki pages, stale _*.md drafts removed. OUTBOX status ready. | verify: docs/wiki pages match kitchen copies after collect (5 files)
- [x] T-020 Defaults-freeze drift repair (qq 04.08): 5 wiki pages re-synced to HEAD bac28b6 — Configuration defaults corrected to default_profile.py (font 18, button_scale 0.5, theme Golden Default, 10-theme list, sound_enabled/volume 1, 33 locales, hr_visual_line/live_preview_conceal/sync_mode/silo_ticks_enabled renames, cursor_blink_ms 1000, silo_gap_height 12, window_presets_enabled True); lock/always hotkeys swapped (Alt+E lock / Alt+S pin per profile); Module-Structure + default_profile.py, 9 themes, total 115 py; SoundManager API (play/play_click/play_tick, scale_wav_bytes); Architecture themes line. Kitchen mirrored. OUTBOX status ready. | verify: docs/wiki pages match kitchen copies after collect (5 files)
- [x] T-021 Post-v0.8.9 drift repair (qq 04.08): 6 wiki pages re-synced to HEAD 8199480 + uncommitted T-715 — Configuration (image_paste_style/silo_tabs_mode/toolbar_position rows), Module-Structure (silo_presets.py + sound_settings_dialog.py + presets/ dir, core 17/ui 45/117 py), Keyboard (Ctrl+Y/Ctrl+Shift+Z redo, T-716), User-Guide (SiloPresets fill-from-preset, Silo Layout tabs/toolbar, pasted-image style, renumbered), UI-Components (tabs mode, Sound Settings dialog, paste style), Core-API (SiloPresets loader). Kitchen mirrored. OUTBOX ready. | verify: docs/wiki pages match kitchen copies after collect (6 files)

## BLOCKED
