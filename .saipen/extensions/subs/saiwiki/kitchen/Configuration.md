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
| `theme` | string | `Golden Default` | 15 built-in themes: 9 classic (Default, Golden Vintage, Golden Default, Vintage Dark, Vintage Classic, Dark 2 (OLED), Dracula, Nord, Solarized Dark) + 6 Wintage palettes ported from the ProBlipAndroid reference (Dark Golden (Win95), Claude Code, Antigravity, K-Lite (MPC-HC), FreeBuff, CodeNomad), or Custom |
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
| `tray_click_activates` | bool | True | Tray double-click always brings window to focus; False = toggle hide/show (T-1082) |
| `close_on_focus_loss` | bool | True | Auto-hide on focus loss |
| `always_on_top` | bool | False | Start with always-on-top |
| `normal_window` | bool | False | Normal windowed mode (not frameless) |
| `tray_visible` | bool | True | Show system tray icon |
| `auto_bullet` | bool | True | Auto-convert dashes to bullets |
| `date_seconds` | bool | True | Show seconds in clock |
| `date_daypart` | bool | True | Show morning/day/evening/night label |
| `date_text_month` | bool | True | Use text month (Jan/Feb) |
| `date_ampm` | bool | False | 12h AM/PM format |
| `date_emoji` | bool | False | Emoji daypart (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | Show date in header |
| `cursor_blink_ms` | int | 1000 | Cursor blink speed ms (0 = no blink, T-606) |
| `timer_show_minutes` | bool | True | Keep minute field in timer display (T-613) |
| `ui_scale` | float | 0.5 | UI scaling (0.5 to 1.5) |
| `button_scale` | float | 0.5 | Silo + toolbar button size multiplier |
| `custom_cursors` | bool | True | Retro cursor theme overlay |
| `numbox_per_row` | int | 10 | Number boxes per row in grid (T-612) |
| `numbox_btn_size` | int | 24 | Number box button size px (T-612) |
| `silo_gap_height` | int | 12 | Sidebar gap spacer height in px |
| `silo_ticks_enabled` | bool | True | Show tick buttons on silos |
| `silo_tabs_mode` | string | `sidebar` | Silo layout: `sidebar` (left column) or `tabs` (horizontal bar above editor) (T-718) |
| `toolbar_position` | string | `top` | Toolbar placement: `top` (above editor) or `bottom` (below splitter) (T-719) |
| `word_wrap` | bool | True | Wrap long lines in the editor |
| `zebra_stripes` | bool | False | Zebra stripes for table rows |
| `show_line_numbers` | bool | True | Show line numbers in the gutter (Alt+Z) |
| `bold_hash_titles` | bool | True | Bold the sidebar title of silos and snippets whose text starts with `#` (T-739) |
| `sidebar_right` | bool | True | Sidebar on right side |
| `show_token_count` | bool | False | Token estimate (pill count) (T-614) |
| `sync_mode` | string | Off | One-way silo sync to disk: Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Enable Ctrl+Q window presets page (T-608) |
| `window_presets_capture_state` | bool | True | Ctrl+Q presets capture full app state (theme, font, scale, toolbar, zen, sidebar); off = geometry only (T-728) |
| `image_paste_style` | string | `pill` | Pasted image markup: `pill` (clickable chip), `link` (markdown link), `path` (raw path) (T-724) |
| `line_heat` | bool | True | Recency heatmap on recently edited silos |
| `line_heat_strength` | int | 0 | Heatmap tint strength |
| `line_heat_palette` | JSON | [] | Heatmap palette override |
| `line_marks` | bool | True | Line-level margin marks (pins, ticks, queue anchors) |
| `hover_line` | bool | True | Highlight line under cursor |
| `hover_line_color` | string | `#0059ff` | Line highlight color (auto = theme accent) |
| `hover_line_opacity` | int | 60 | Line highlight opacity 0-255 |
| `paste_mode` | string | Plain | Smart paste mode |
| `preview_mode` | string | None | Live preview mode |
| `fkey_action` | string | paste | F1-F10 behavior |
| `snippet_arrows` | bool | False | Arrow keys walk snippets |
| `trash_vision` | bool | True | Show trash folder in silo list |
| `tab_overflow_mode` | string | scroll | Tab overflow behavior |
| `numbox_tabs` | bool | False | Number boxes as tabs |
| `two_sided_buttons` | bool | False | Two-sided toolbar buttons |
| `lock_to_cursor` | bool | False | Window appears at cursor |
| `header_position` | string | top | Header position |
| `text_align` | string | left | Editor text alignment |
| `quote_italic` | bool | True | Blockquote italic styling |
| `divider_lines_after` | int | 1 | Divider lines after Ctrl+W |
| `altw_blanks_before`/`after` | int | 0/1 | Alt+W blank line counts |
| `altw_s1..s6_*` | mixed | — | Alt+W divider template rows |
| `ctrlw_blanks_before`/`after` | int | 0/1 | Ctrl+W blank line counts |
| `ctrlw_s1..s6_*` | mixed | — | Ctrl+W divider template rows |
| `ctrlw_split_behavior` | string | — | Ctrl+W smart split behavior |
| `ctrl_e_*` | mixed | — | Ctrl+E header format (template, bullet, rule, alignment, stamp) |
| `cs_style` | string | — | Clipboard paste style |
| `custom_colors` | JSON dict | {} | Custom theme color tokens |
| `saved_sound_mappings` | JSON dict | {} | Per-event sound file mappings |
| `sound_events` | JSON dict | {} | Per-event sound flags |
| `sound_hotkey_on_by_default` | bool | True | Generic hotkey sound ships ON (T-742) |
| `silo_0_hotkey` … `silo_4_hotkey` | string | — | Per-silo summon hotkeys |
| `snippet_0_hotkey` … `snippet_9_hotkey` | string | — | Per-snippet summon hotkeys |
| `hk_bold`/`hk_italic`/… | string | — | Configurable formatting shortcut keys |
| `toggle_sidebar_hotkey` | string | Alt+D | Sidebar toggle hotkey |
| `hide_on_clickout_hotkey` | string | Alt+A | Hide-on-click-out hotkey |
| `global_hotkey_alt` | string | `F15` | Secondary global summon hotkey |
| `pie_menu_hotkey_alt` | string | — | Secondary pie menu hotkey |
| `hide_shortkeys` | bool | False | Hide hotkey hints in UI |
| `token_mode`/`token_weight` | string/int | — | Token estimate mode + weight |
| `search_visible` | bool | False | Search bar visible on start |
| `settings_width` | int | — | Settings dialog width |
| `silo_pinned_gap` | int | — | Gap above pinned silos |
| `silo_home` | int | 0 | Default silo on start |
| `last_save_format` | string | `txt` | Remembered export filter (T-1084) |
| `saved_sidebar_size`/`splitter_sizes*` | JSON | — | Persisted window layout state |
| `silo_view_state_all` | JSON dict | `{}` | Per-silo cursor/scroll/fold state |
| `category_file_dirs` | JSON dict | `{}` | Logical category → physical folder mapping |
| **Sound** | | | |
| `sound_ui` | bool | True | UI click sound effects |
| `sound_typewriter` | bool | True | Typewriter key sounds |
| `sound_volume` | float 0.0–1.0 | 0.09 | Master sound volume (baked profile; legacy 0–10 ints still parsed, scaled ÷10) |
| `sound_events` | JSON dict | 69 events | Per-event `enabled`/`file`/`volume`/`gain_db`/`mode` overrides; self-healed on every start against the shipped library |
| `audio_global_playback_mode` | string | `overlay` | AudioHub global mode: `overlay` / `stack` / `replace` (T-1238-G) |
| `snippets_hidden` | bool | True | Snippet panel starts hidden |
| **AI limits (Freebuff + notifications)** | | | |
| `limit_freebuff_enabled` | bool | True | Freebuff provider poll toggle (T-1243) |
| `limit_freebuff_state` | JSON | (empty) | Freebuff provider session state cache |
| `limit_gauges_hide_zero_usage` | bool | False | Hide gauges whose usage reads zero |
| `limit_notif_color` | string | (empty) | Limit-notification toast accent color override |
| `limit_notif_duration_sec` | int | 8 | Limit-notification toast display seconds |
| `limit_notif_symbol` | string | `↻` | Limit-notification symbol |
| `click` default mapping | — | `tick_on.wav` | The generic `click` event maps to `tick_on.wav` in the baked profile (was `button1.wav`); silo/save/delete also re-pinned to `tick_on.wav` |
| **Auto Level / device-rate rendering (T-1242)** | | | |
| `audio_render` + Auto Level | — | on | Every transient cue is pre-rendered to the output device's own rate with a band-limited polyphase resampler (`core/audio_render.py`, `RENDER_VERSION` invalidates the cache); per-event `gain_db` and the loudness analysis in `core/audio_level.py` level loud effects toward the UI reference |

Restored in v0.8.32 (removed in v0.8.24, back with the launch grace and own-window click-out guards): `close_on_focus_loss` / "Hide on Click-Out" is read again — hides the window on focus loss unless the launch grace (2s) or the app's own undocked windows still hold it. `tray_click_activates`: when True (default) a double-click on the tray icon always brings the window to focus; when False it toggles hide/show like the hotkey.

Retired in T-1183: the watcher `[limits]` block (`min_gap_ms`, `max_sends`, `dry_run_new`, `blocker_pattern`) and its `adapters.toml` no longer exist; the loader deletes leftover `watcher_*` settings rows on start.

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
| **Interval Notifications (24h Schedule)** | | | |
| `interval_notifs` | JSON list | 4 defaults | Time-of-day scheduled reminders with clock-aligned or elapsed firing, per-rule sound/volume/notification, and configurable active hours (morning/noon/day/night presets). Default rules live in `core/state.py` (`volume: 1.0`, `show_in_top_bar: False`); `sound_volume` ships as 1 (0-10) in the baked profile (T-1089) |
| **Sound Quick Bar** | | | |
| `sound_quick_bar` | JSON list | 10 entries | Favorite sound shortcuts for quick-pick in Timer Dialog (click to select, right-click to store current sound) |
| **Temp Timer** | | | |
| `temp_timer_settings` | JSON dict | defaults | Temporary timer configuration: increment minutes, delete-after-fire, sound mode (single/random pool), color mode (temperature), sound rules for pool mode |

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
