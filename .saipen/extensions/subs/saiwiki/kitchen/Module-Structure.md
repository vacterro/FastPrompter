# FastPrompter Module Structure

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## Codebase Map (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # Entry point, QMainWindow, mixin orchestration
├── __init__.py                 # Package marker
│
├── core/                       # Backend logic, state, subsystems
│   ├── ambience_engine.py      # Infinite ambience layers + schedule/weather rules (T-1238-I)
│   ├── ambience_store.py       # Ambience rule persistence in audio.db, app-global (T-1238-C3.10)
│   ├── audio_hub.py            # ONE audio authority: buses, MIX/QUEUE/REPLACE, STOP ALL (T-1238-G)
│   ├── audio_level.py          # Deterministic loudness analysis for Auto Level (T-1242)
│   ├── audio_render.py         # Device-rate WAV pre-rendering: band-limited polyphase resampler (T-1242)
│   ├── config.py               # Theme color extractors, tray icon generators
│   ├── ctrlw.py                # Ctrl+W / Alt+W divider insertion engine
│   ├── default_profile.py      # Shipped defaults map, merged into state.reset_data()
│   ├── duration.py             # Time parsing, human-readable duration format
│   ├── hashtags.py             # Hashtag extraction + cross-silo indexing
│   ├── header.py               # Ctrl+E header formatting core
│   ├── hotkey_filter.py        # QAbstractNativeEventFilter: WM_HOTKEY/WM_SYSCOMMAND dispatch
│   ├── hotkeys.py              # Win32 RegisterHotKey + layout-aware VK resolution
│   ├── instance_lock.py        # Win32 named-mutex single-instance ownership (T-788; T-1247: IPC no-ACK never authorizes a kill)
│   ├── interval_presets.py     # Interval presets and duration options
│   ├── ipc_server.py           # QLocalServer single-instance IPC
│   ├── limits.py               # Agent reset-limit scanner + timer creation
│   ├── logging.py              # Logger setup, rotating file handler
│   ├── markdown_refs.py        # Markdown image and link reference extractor
│   ├── pomodoro.py             # Pomodoro state machine (work/break)
│   ├── profile_flags.py        # Runtime profile flags and mode toggles
│   ├── problip.py              # Pure Problip scheduling model: states, intervals, cue timing (T-1238-A)
│   ├── problip_store.py        # Global Problip persistence + statistics (problip.db, T-1238-A)
│   ├── project_sync.py         # Sync-Project folder↔silo two-way sync, pure logic (Qt-free)
│   ├── silo_bundle.py          # Silo bundle archive creation and manifest (T-1414, T-1416)
│   ├── silo_coverage.py        # Silo pack coverage event tracking and history store (T-1415)
│   ├── silo_index.py           # Silo structured index and search engine (T-1423)
│   ├── silo_presets.py         # .md template loader — Fill from preset (T-715)
│   ├── silo_export.py          # Drag a silo OUT to Explorer as a content-named .md (T-738)
│   ├── sound_dependencies.py   # Sound playback dependency graph + conflict resolution (T-1238-G2)
│   ├── sound_library.py        # One canonical sound-reference resolver: builtin:/user: roots (T-1238-C0)
│   ├── sound_manager.py        # Audio playback facade over AudioHub (clicks, typewriter, alarms)
│   ├── sound_presets.py        # Sound preset system + portable .fpsoundpreset/.fpsoundpack (T-1238-F)
│   ├── state.py                # SQLite DB interface + state management (WAL + synchronous=FULL)
│   ├── timers.py               # Countdown timer model, due detection
│   ├── topbar_visibility.py    # Versioned responsive top-bar policy (pure model, no Qt)
│   ├── translations.py         # Legacy proxy → i18n package (33 locales)
│   ├── typecheck.py            # Dictionary-based typo checker for silo text (non-recursive, script-aware)
│   ├── typecheck_ui_vocab.py   # GENERATED: Latin UI vocabulary from all i18n packs (typecheck dictionary)
│   ├── typecheck_words.py      # Built-in English word list for the typo checker (~10k words)
│   ├── voice_engine.py         # VOX/FVOX/G-Man voice packs + countdown scheduler (T-1238-H)
│   ├── voice_store.py          # Voice settings + pack locations in audio.db (T-1238-C3.6)
│   ├── weather.py              # Key-free Open-Meteo weather provider for ambience rules (opt-in, T-1238-C3.11)
│   ├── win_clipboard.py        # Windows clipboard GENERATION diagnostics: counters + owner PID/process name via ctypes, never clipboard text (T-1269)
│   ├── i18n/                   # 33-locale resource pack (32 languages + Дед)
│   │   ├── __init__.py, _compat.py, _container.py, _context.py, _engine.py
│   │   └── en.py, ru.py, est.py, ja.py, ded.py, ... (33 locale modules)
│   │
│   └── usage_limits/           # AI usage-limit probing (provider-neutral) — a core/ sibling, not an i18n child
│       ├── __init__.py
│       ├── claude_statusline.py # Claude status-line bridge probe
│       ├── cli_tools.py         # CLI tool discovery
│       ├── freebuff_format.py   # Freebuff quota payload decoding
│       ├── identity.py          # Provider account identity and fingerprinting (T-239)
│       ├── model.py             # Account/quota data model
│       ├── notifications.py     # Limit event → app notification routing (T-1249 reset classifier)
│       ├── sai_accounts.py      # Account multi-provider aggregation and mapping (T-239)
│       ├── service.py           # UsageLimitService: bounded probe executor, sweep generations, refresh/backoff
│       ├── troubleshooter.py    # Multi-level troubleshooting + auto-healing of limit metrics
│       └── providers/           # Per-vendor quota probes
│           ├── antigravity.py   #   Antigravity (+_antigravity_cli.py, _antigravity_brain.py)
│           ├── claude.py        #   Claude (+_claude_cli.py, _claude_desktop.py, _claude_transcripts.py)
│           ├── codex.py         #   Codex (+_codex_probe.py)
│           ├── freebuff.py      #   Freebuff (+_freebuff_http.py; T-1243, in flight)
│           └── zcode.py         #   zcode (+_zcode_http.py)
│
├── ui/                         # PyQt6 UI components + mixins
│   ├── audio_hub_pages.py      # Audio Hub inner pages: Presets, Playback, Voice, Ambience (T-1238-C3)
│   ├── ambience_controller.py  # Ambience runtime adapter: ONE eval timer, ONE fade driver, ONE fetch timer
│   ├── analog_clock.py         # Custom-painted analog clock widget
│   ├── appearance_sounds.py    # Semantic UI appearance-transition sound emitters — hidden→shown only, one owner per surface (T-1245)
│   ├── backup_dialog.py        # DB export/import + backup snapshot dialog
│   ├── button_sound.py         # App-level default click sound for every button (T-1225)
│   ├── clipboard_watch.py      # Counts QClipboard changed/dataChanged notifications — the Qt half of the paste record (T-1269)
│   ├── ctrlw_settings.py       # Ctrl+W/Alt+W template config UI
│   ├── cursor_mixin.py         # Cursor set capture/apply + system install (T-785)
│   ├── cursor_theme.py         # Retro cursor theme overlay manager
│   ├── drop_overlay.py         # Drag-and-drop 4-option target overlay
│   ├── edit_guard.py           # Read-only edit lock guard wrapper
│   ├── editor.py               # VaultTextEdit: code blocks, gutter, folding
│   ├── fancy_zones.py          # Screen-snap zone overlay picker
│   ├── file_container.py       # Silo asset file drawer + templates
│   ├── flags.py                # Vector/raster country flag renderer
│   ├── flow_layout.py          # Dynamic heightForWidth wrapping layout
│   ├── formatting_mixin.py     # Markdown formatting shortcuts + Ctrl+Shift+Q smart quote folding
│   ├── hashtag_dialog.py       # Tag search + silo filter overlay
│   ├── header_format_dialog.py # Date/time timestamp format dialog
│   ├── help_dialog.py          # Keyboard shortcuts + interactive guide
│   ├── hotkey_mixin.py         # Hotkey binding mixin for main window
│   ├── hotkey_spec.py          # Hotkey specification and key binding definitions
│   ├── image_viewer.py         # Local raster preview — decoded in Qt, never a shell association (T-1218)
│   ├── interaction_undo.py     # Visual and selection interaction undo stack
│   ├── kanban_widget.py        # Kanban board view widget (silo_kanban backend)
│   ├── layout_shortcuts.py     # Physical VK shortcut mapping (layout-indep)
│   ├── limit_account_selector.py # AI-limit account selector widget
│   ├── limit_colors.py         # AI-limit vendor tint palette
│   ├── limit_gauges.py         # Top-bar AI-limit gauge widgets (Wave 7)
│   ├── limit_hover_card.py     # App-owned hover card for AI-limit gauges (T-1242; replaces native QToolTip)
│   ├── limit_overview.py       # AI-limit overview dialog
│   ├── limit_settings_dialog.py # AI-limit settings dialog
│   ├── markdown_highlighter.py # QSyntaxHighlighter for live markdown
│   ├── pie_menu.py             # QuickListWidget radial context menu
│   ├── problip_controller.py   # Application-global Problip runtime (QObject, one per app)
│   ├── problip_custom_sounds.py # Custom Problip sounds dialog over the managed sound library (T-1242)
│   ├── problip_settings.py     # Fifth Settings tab: Problip page widgets (T-1238-C2)
│   ├── project_numbox_reorder.py # Numbered project tabs reordering widget
│   ├── qt_lifetime.py          # Qt callback helpers whose scheduling cannot extend widget lifetimes
│   ├── qt_text_coords.py       # Single UTF-16 ↔ code-point conversion boundary: formatting spans + typo-span handover (T-1269)
│   ├── reset_queue_card.py     # Reset-queue hover content: structured `# | Account | Pool | Window | Left` rich-text table (T-1279)
│   ├── resizers.py             # Window resize handle controls
│   ├── scaling_mixin.py        # UI DPI + font scaling mixin
│   ├── scroll_sound.py         # Wheel scroll sound filter
│   ├── search_mixin.py         # Multi-word AND search filter
│   ├── send_selection_mixin.py # Send selection to: child/new silo, archive, another silo
│   ├── shortcut_display.py     # Hotkey and shortcut overlay HUD display
│   ├── settings.py             # Preferences dialog (themes, hotkeys, sounds)
│   ├── settings_builder.py     # Settings tab construction + live retranslation
│   ├── silo_bundle_actions.py  # Actions and triggers for silo bundle export (T-1414)
│   ├── silo_bundle_dialog.py   # Dialog for silo bundle options and preview (T-1414)
│   ├── silo_chest.py           # Silo chest container view and drawer
│   ├── silo_kanban.py          # Markdown kanban board (T-630)
│   ├── silo_settings_dialog.py # Per-silo config (color, project links)
│   ├── silo_table.py           # Markdown table builder (T-630)
│   ├── silo_region.py          # Silo list region: drag, gaps, multi-select
│   ├── snippet_ops_mixin.py    # Silo ops (trash, move, duplicate, clear)
│   ├── snippet_panel.py        # Silo tree + F1-F10 snippet buttons
│   ├── sound_settings_dialog.py # Sound Settings dialog: event table + Audio Hub pages (Presets/Playback/Voice/Ambience)
│   ├── table_widget.py         # Table view widget (silo_table backend)
│   ├── theme_mixin.py          # Vintage theme styling + QSS generator
│   ├── timer_dialog.py         # Pomodoro + alarm timer setup dialog
│   ├── timer_toast.py          # Floating notification toast widget
│   ├── toolbar_reorder.py      # Drag-and-drop toolbar button reorder
│   ├── topbar_visibility_dialog.py # Editor for the responsive top-bar policy
│   ├── trash_dialog.py         # Trash bin + restore dialog
│   ├── tray_mixin.py           # Systray icon + context menu (incl. STOP ALL SOUND)
│   ├── typo_check_dialog.py    # Whole-project typo report dialog (right-click project tab)
│   ├── voice_controller.py     # Voice-countdown runtime: nearest known deadline, exactly-once across restarts (T-1238-C3.7)
│   ├── wheel_guard.py          # Wheel event guard
│   ├── window_mixin.py         # Frameless move, snap, borderless controls
│   ├── window_presets_dialog.py # User-defined window position presets
│   ├── windows_autostart.py    # Packaged-only HKCU Run-key autostart (T-1238-C)
│   └── zen_desktop.py          # 3-stage Zen/Solo desktop sweep (Ctrl+D)
│
├── presets/                    # .md silo templates, shipped as data dir (T-715)
│   └── 01_TODO.md ... 11_Prompt.md   # filename orders + names the menu entry
│
├── sound/                      # Shipped WAV/OGG library incl. problip/ catalog + _vault/ archive
│
├── theme/                      # Theme presets
│   └── themes.py               # 15 built-in color themes (9 classic + 6 Wintage palettes, T-1238-D) + custom engine
│
└── utils/                      # Low-level helpers
    ├── fonts.py                # System font loader, fallback resolver, no-AA
    ├── paths.py                # Portable path resolver (exe + user data)
    ├── path_safety.py          # Path containment + collision-safe name codec (T-788/T-789)
    ├── portable_backup.py      # Daily Markdown snapshot exporter (silos/snippets/archive)
    └── textfit.py              # Dynamic text truncation + label fitting
```

## Subsystem Responsibilities

| Package | Responsibility |
|---|---|
| `core.state` | SQLite WAL persistence (synchronous=FULL), domain-scoped dirty tracking, state sync, durable undo/redo stack, per-category aliased stores |
| `core.hotkey*` | Win32 RegisterHotKey + native event filter, layout-independent dispatch |
| `core.audio_hub` | One audio authority: six buses (UI/ALERT/VOICE/PROBLIP/AMBIENCE/PREVIEW), Overlay/Stack/Replace modes, bounded queues, STOP ALL (T-1238-G) |
| `core.sound_manager` | Facade: named-event policy engine, default mappings, AudioHub wiring, STOP ALL SOUND |
| `core.sound_presets` | Preset definitions (audio.db), factory presets, portable import/export with asset-safety checks (T-1238-F) |
| `core.voice_engine` | VOX/FVOX/G-Man pack composition + nearest-target countdown announcements (T-1238-H) |
| `core.ambience_engine` | Infinite ambience layers, schedule/weather rules, opt-in weather provider (T-1238-I) |
| `core.problip` + `problip_store` | Problip cue scheduler + global persistence/stats (problip.db, T-1238-A) |
| `core.i18n` | 33-locale translation pack + proxy delegation from translations.py (with lazy loading) |
| `core.usage_limits` | Provider-neutral AI-quota probing: bounded executor, sweep generations, auto-healing troubleshooter |
| `core.ctrlw` | Divider template engine (Ctrl+W / Alt+W) |
| `core.timers` | Timer model, due detection, serialization |
| `core.pomodoro` | Work/break state machine, focus timer |
| `core.typecheck` | Dictionary-based typo checker (non-recursive, script-aware, Qt-free for unit testing) |
| `core.project_sync` | Sync-Project: folder↔silo two-way sync, include/exclude filters, EOL detection, atomic file I/O |
| `ui.editor` | VaultTextEdit — folding, gutter, checkboxes, heatmap, margin marks, hide-markup |
| `ui.snippet_panel` | Silo tree, hierarchy, category tabs, F1-F10 slots, sidebar gaps, multi-select |
| `ui.silo_kanban` | Pure-text kanban board (Alt+arrows move cards, Enter new row) |
| `ui.silo_table` | Pure-text table editor (Tab walk cells, Enter new row) |
| `ui.file_container` | Per-silo folder drawer, asset preview, templates |
| `ui.image_viewer` | Local raster preview decoded in Qt — no shell association, no warnings (T-1218) |
| `ui.theme_mixin` | 15 built-in themes (9 classic + 6 Wintage) + custom color engine + QSS generator |
| `ui.kanban_widget` | Kanban board view widget (silo_kanban backend) |
| `ui.table_widget` | Table view widget (silo_table backend) |
| `ui.silo_region` | Silo list region: drag, gaps, multi-select |
| `ui.fancy_zones` | Visual zone picker with 7 layout presets |
| `ui.problip_custom_sounds` | Custom Problip sounds dialog over the managed sound library (T-1242) |
| `ui.limit_hover_card` | App-owned hover card for the AI-limit gauges (T-1242) |
| `ui.audio_hub_pages` | Audio Hub inner pages: Presets, Playback, Voice, Ambience (T-1238-C3) |
| `core.audio_render` | Device-rate WAV pre-rendering: band-limited polyphase resampler + cache (T-1242) |
| `core.audio_level` | Deterministic loudness analysis feeding Auto Level (T-1242) |
| `core.weather` | Key-free Open-Meteo weather provider for ambience rules, opt-in (T-1238-C3.11) |
| `core.win_clipboard` | Windows clipboard GENERATION diagnostics (ctypes `GetClipboardSequenceNumber` / `GetClipboardOwner` + owner PID/process name); reports counters and process names, never clipboard text (T-1269) |
| `ui.window_presets_dialog` | User-saved window geometry presets (Ctrl+Q page) |
| `ui.zen_desktop` | 3-stage Ctrl+D: Zen, Solo (minimise others), back |
| `ui.toolbar_reorder` | Drag-and-drop toolbar button customization |
| `ui.flow_layout` | Responsive wrapping layout for compact settings panels |
| `ui.edit_guard` | Begin/endEditBlock guard — prevents freeze from unterminated edits |
| `ui.clipboard_watch` | Counts QClipboard `changed`/`dataChanged` notifications, the Qt half of the same paste record (T-1269) |
| `ui.qt_text_coords` | The single UTF-16 ↔ code-point conversion boundary: formatting spans and the typo-span handover (T-1269) |
| `ui.appearance_sounds` | Reports ONE kind of appearance transition per user-visible surface to the sound hub (hidden → shown only, never construction/relayout/paint/re-delivery); one semantic owner per surface so one appearance never fires two sounds (T-1245) |
| `ui.reset_queue_card` | The ONE renderer for the reset-queue hover: fixed `# / Account / Pool / Window / Left` columns as rich text with stable starts and an always-present `Left`; long pools elide before `Left` can be pushed out (T-1279) |
| `ui.voice_controller` | Wires the pure countdown scheduler to deadlines the app already knows (active timers + resolved AI-limit resets); never polls a provider, schedules only future thresholds, exactly-once announcements across restarts (T-1238-C3.7) |
| `utils.fonts` | Font resolution, bitmap font install, no-AA fallback |
| `utils.paths` | Portable execution — no registry, no AppData dependency |

## Module Count Summary

- **core/**: 44 modules + i18n/ (33 locales + 5 infra files = 38) + usage_limits/ (10 + 14 provider files = 24)
- **ui/**: 75 modules
- **utils/**: 5 modules
- **theme/**: 1 module
- **top level**: main.py + __init__.py (2) + sound/problip/ catalog helpers (2)
- **Total**: 191 `.py` files under `src/fastprompter/` (+ `presets/` ships as a non-code data dir; `sound/` ships ~1295 audio assets: 525 top-level + problip catalog + `_vault/` archive of 759 (614 vox, 140 fvox, gman + cs_style))
