# FastPrompter Configuration & Settings

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## DB Schema

SQLite DB: `data/local_data_v15.db` (profile 1) or `data/local_data_v15_p<ID>.db` (profiles >1). Portable `data/` dir sits beside EXE. Falls back to `%LOCALAPPDATA%/FastPrompter/` if exe dir not writable.

**Tables:**
- `settings` — key-value text pairs (all app config)
- `presets` — snippet storage (category, slot, name, content, last_edited)
- `temp_presets_v2` — silo text content per category
- `archive_temp_presets_v2` — archived silo content per category

Config lives in `settings` table key-value pairs. No INI file. All hot-reload on apply.

## Settings Keys

| Key | Type | Default | Description |
|---|---|---|---|
| **Theme & Display** | | | |
| `theme` | string | `Golden Default` | Theme: Default, Golden Vintage, Golden Default, Vintage Dark, Vintage Classic, Dark 2 (OLED), Dracula, Nord, Solarized Dark, Custom |
| `font_family` | string | `Verdana` | Editor font (auto-resolves to `_m1` bitmap variant if installed) |
| `font_size` | int | 18 | Editor font size in points |
| `ui_scale` | float | 0.5 | UI scaling (0.5 to 1.5) |
| `button_scale` | float | 0.5 | Silo + toolbar button size multiplier |
| `custom_cursors` | bool | True | Retro cursor theme overlay |
| `code_monospace` | bool | False | Monospace font in code blocks (False = editor font) |
| `code_auto_gutter` | bool | False | Auto line numbers in code blocks |
| `hr_visual_line` | bool | True | Render `---` as horizontal line instead of text |
| `live_preview_conceal` | bool | True | Hide `**`, `*`, `~~`, `` ` `` markers in live preview |
| **Hotkeys** | | | |
| `global_hotkey` | string | `Alt+X` | Global summon hotkey |
| `pie_menu_hotkey` | string | `Shift+Alt+X` | Pie menu hotkey |
| `lock_window_hotkey` | string | `Alt+E` | Window lock toggle |
| `always_on_top_hotkey` | string | `Alt+S` | Always-on-top toggle |
| **Behavior** | | | |
| `close_on_focus_loss` | bool | True | Auto-hide on focus loss |
| `always_on_top` | bool | False | Start with always-on-top |
| `normal_window` | bool | False | Normal windowed mode (not frameless) |
| `tray_visible` | bool | True | Show system tray icon |
| `auto_bullet` | bool | True | Auto-convert dashes to bullets |
| `ctrl_e_center` | bool | True | Center-align Ctrl+E headers |
| `customize_toolbar` | bool | False | Toolbar reorder mode |
| `snippets_hidden` | bool | True | Hide snippet panel |
| `bold_hash_titles` | bool | True | Bold the sidebar title of silos and snippets whose text starts with `#` (T-739) |
| `sidebar_right` | bool | True | Sidebar on right side |
| `show_token_count` | bool | False | Token estimate (pill count) (T-614) |
| `sync_mode` | string | Off | One-way silo sync to disk: Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Enable Ctrl+Q window presets page (T-608) |
| `window_presets_capture_state` | bool | True | Ctrl+Q presets capture full app state (theme, font, scale, toolbar, zen, sidebar); off = geometry only (T-728) |
| `image_paste_style` | string | `pill` | Pasted image markup: `pill` (clickable chip), `link` (markdown link), `path` (raw path) (T-724) |
| **Sound** | | | |
| `sound_enabled` | bool | True | Master sound toggle |
| `sound_ui` | bool | True | UI click sound effects |
| `sound_typewriter` | bool | False | Typewriter key sounds |
| `sound_volume` | int (0-10) | 1 | Master sound volume |
| **Clock & Date** | | | |
| `date_seconds` | bool | True | Show seconds in clock |
| `date_daypart` | bool | True | Show morning/day/evening/night label |
| `date_text_month` | bool | True | Use text month (Jan/Feb) |
| `date_ampm` | bool | False | 12h AM/PM format |
| `date_emoji` | bool | False | Emoji daypart (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | Show date in header |
| **Cursor** | | | |
| `cursor_blink_ms` | int | 1000 | Cursor blink speed ms (0 = no blink, T-606) |
| **Timers** | | | |
| `timer_show_minutes` | bool | True | Keep minute field in timer display (T-613) |
| **Window Layout** | | | |
| `numbox_per_row` | int | 10 | Number boxes per row in grid (T-612) |
| `numbox_btn_size` | int | 24 | Number box button size px (T-612) |
| **Other** | | | |
| `language` | string | EN | UI language (33 locales) |
| `hover_line_color` | string | `#0059ff` | Line highlight color (auto = theme accent) |
| `portable_backup_enabled` | bool | True | Daily Markdown snapshot mirror to `Documents\.fastprompter\` |
| `watcher_skill` | string | (empty) | Default skill for watcher queue items |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Category tab order + names |
| `hidden_categories` | JSON list | [] | Hidden categories (visible in project manager) |
| `timers` | JSON | [] | Saved countdown definitions |
| `productivity_timer` | JSON | — | Pomodoro timer state |
| `watcher_queues` | JSON | `{}` | Per-silo prompt queues |

Restored in v0.8.32 (removed in v0.8.24, back with the launch grace and own-window click-out guards): `close_on_focus_loss` / "Hide on Click-Out" is read again — hides the window on focus loss unless the launch grace (2s) or the app's own undocked windows still hold it.

**Watcher `[limits]` (applied at arm since v0.8.25, in `adapters.toml`):** `min_gap_ms`, `max_sends`, `dry_run_new`. `blocker_pattern` only works on the CDP transport (it needs the target's visible text); a blocker on any other transport is flagged inactive.

| `toolbar_order` | string | (empty) | Custom toolbar button order tokens |
| `window_presets` | JSON | [] | User-saved window geometry presets |
| `silo_gap_height` | int | 12 | Sidebar gap spacer height in px |
| `silo_ticks_enabled` | bool | True | Show tick buttons on silos |
| `silo_tabs_mode` | string | `sidebar` | Silo layout: `sidebar` (left column) or `tabs` (horizontal bar above editor) (T-718) |
| `toolbar_position` | string | `top` | Toolbar placement: `top` (above editor) or `bottom` (below splitter) (T-719) |
| `silo_view_state_all` | JSON dict | `{}` | Per-silo cursor/scroll/fold state |
| **Typecheck (Typo Checker)** | | | |
| `typo_check_enabled` | bool | False | Enable live typo underline in silo text (dictionary-based, non-recursive) |
| `typo_color` | string | `#e05555` | Underline color for flagged typo words |
| `typo_user_words` | JSON list | `[]` | User-added dictionary words (extends the built-in English pool) |
| **Sync-Project (Folder↔Silo Sync)** | | | |
| `project_sync` | JSON dict | `{}` | Per-profile sync-project bindings (project tab → folder path) |
| `project_sync_all` | JSON dict | `{}` | Cross-profile sync-project bindings |
| `project_sync_map` | JSON dict | `{}` | Per-profile silo↔file slot mapping |
| `project_sync_map_all` | JSON dict | `{}` | Cross-profile silo↔file slot mapping |
| `silo_links` | JSON dict | `{}` | Per-profile per-silo file link targets |
| `silo_links_all` | JSON dict | `{}` | Cross-profile per-silo file link targets |
| `sync_include` | string | `.txt .md .py ...` | Space-separated text file extensions to include in sync |
| `sync_exclude` | string | `node_modules, .git, ...` | Comma-separated exclude patterns (fnmatch name or path substring) |
| `sync_live_watch` | bool | True | Live-watch folder for external changes (QFileSystemWatcher) |
| `sync_max_kb` | int | 512 | Max file size in KB to sync (larger files are skipped) |
| `sync_recursive` | bool | True | Recursively scan subdirectories in the sync folder |
| **Passed-Event Alert** | | | |
| `passed_alert_enabled` | bool | True | Highlight timer silos whose countdown has elapsed (passed) |
| `passed_event_color` | string | `#e05555` | Color for passed-event silo highlight |

## File System Layout

```
data/
├── local_data_v15.db           # Main SQLite DB (profile 1)
├── local_data_v15.db.bak       # Throttled backup (60s min interval)
├── local_data_v15.db-wal       # WAL write-ahead log
├── local_data_v15.db-shm       # WAL shared memory
├── local_data_v15_undo.json    # Latest undo snapshots (reloaded on launch)
├── local_data_v15_p2.db        # Profile 2 DB
├── files/                      # File container attachments
│   ├── <category-slug>/        # Project/category folder
│   │   └── <silo-title-slug>/  # Per-silo folder (unique per slot)
│   └── _trash/                 # Soft-deleted silos + files
└── custom_theme.json           # User-defined color palette
```

**Daily mirror:** `%USERPROFILE%/Documents/.fastprompter/` — timestamps, per-project silos/archive/snippets as flat .md

**Undo store:** `<database>_undo.json` (e.g. `local_data_v15_undo.json`) — latest 10 undo snapshots, reloaded at startup.

## Custom Themes

`data/custom_theme.json` loaded when theme = Custom.

**Color tokens:** `bg_main`, `bg_surface`, `bg_editor`, `fg_text`, `fg_accent`, `text_primary`, `text_accent`, `border`, `selection`, `header_bg`, `accent`, `button_bg`, etc.

Apply via Settings → Theme or Mini Settings (Alt+`). Instant hot-reload, no restart.
