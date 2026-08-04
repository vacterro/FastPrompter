# FastPrompter Configuration & Settings

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
| `sidebar_right` | bool | True | Sidebar on right side |
| `show_token_count` | bool | False | Token estimate (pill count) (T-614) |
| `sync_mode` | string | Off | One-way silo sync to disk: Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Enable Ctrl+Q window presets page (T-608) |
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
| `portable_backup_enabled` | bool | True | Auto .bak on startup |
| `watcher_skill` | string | (empty) | Default skill for watcher queue items |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Category tab order + names |
| `hidden_categories` | JSON list | [] | Hidden categories (visible in project manager) |
| `timers` | JSON | [] | Saved countdown definitions |
| `productivity_timer` | JSON | — | Pomodoro timer state |
| `watcher_queues` | JSON | `{}` | Per-silo prompt queues |
| `toolbar_order` | string | (empty) | Custom toolbar button order tokens |
| `window_presets` | JSON | [] | User-saved window geometry presets |
| `silo_gap_height` | int | 12 | Sidebar gap spacer height in px |
| `silo_ticks_enabled` | bool | True | Show tick buttons on silos |
| `silo_tabs_mode` | string | `sidebar` | Silo layout: `sidebar` (left column) or `tabs` (horizontal bar above editor) (T-718) |
| `toolbar_position` | string | `top` | Toolbar placement: `top` (above editor) or `bottom` (below splitter) (T-719) |
| `silo_view_state_all` | JSON dict | `{}` | Per-silo cursor/scroll/fold state |

## File System Layout

```
data/
├── local_data_v15.db           # Main SQLite DB (profile 1)
├── local_data_v15.db.bak       # Throttled backup (60s min interval)
├── local_data_v15.db-wal       # WAL write-ahead log
├── local_data_v15.db-shm       # WAL shared memory
├── local_data_v15_p2.db        # Profile 2 DB
├── silo_files/                 # File container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 files
│   │   └── 1/                  # Silo slot 1 files
│   └── Text/
├── _trash/                     # Soft-deleted silos + files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash entry
└── custom_theme.json           # User-defined color palette
```

**Daily mirror:** `%USERPROFILE%/Documents/.fastprompter/` — timestamps, per-project silos/archive/snippets as flat .md

**Undo store:** `data/data_undo_stack.json` + `data/data_redo_stack.json` (auto-compacted, 20MB cap)

## Custom Themes

`data/custom_theme.json` loaded when theme = Custom.

**Color tokens:** `bg_main`, `bg_surface`, `bg_editor`, `fg_text`, `fg_accent`, `text_primary`, `text_accent`, `border`, `selection`, `header_bg`, `accent`, `button_bg`, etc.

Apply via Settings → Theme or Mini Settings (Alt+`). Instant hot-reload, no restart.
