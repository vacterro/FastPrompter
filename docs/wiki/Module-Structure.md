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
│   ├── config.py               # Theme color extractors, tray icon generators
│   ├── ctrlw.py                # Ctrl+W / Alt+W divider insertion engine
│   ├── default_profile.py      # Shipped defaults map, merged into state.reset_data()
│   ├── duration.py             # Time parsing, human-readable duration format
│   ├── hashtags.py             # Hashtag extraction + cross-silo indexing
│   ├── header.py               # Ctrl+E header formatting core
│   ├── hotkey_filter.py        # QAbstractNativeEventFilter: WM_HOTKEY/WM_SYSCOMMAND dispatch
│   ├── hotkeys.py              # Win32 RegisterHotKey + layout-aware VK resolution
│   ├── instance_lock.py        # Win32 named-mutex single-instance ownership (T-788)
│   ├── ipc_server.py           # QLocalServer single-instance IPC
│   ├── limits.py               # Agent reset-limit scanner + timer creation
│   ├── logging.py              # Logger setup, rotating file handler
│   ├── pomodoro.py             # Pomodoro state machine (work/break)
│   ├── silo_presets.py         # .md template loader — Fill from preset (T-715)
│   ├── silo_export.py          # Drag a silo OUT to Explorer as a content-named .md (T-738)
│   ├── sound_manager.py        # Audio playback (clicks, typewriter, alarms)
│   ├── state.py                # SQLite DB interface + state management
│   ├── timers.py               # Countdown timer model, due detection
│   ├── translations.py         # Legacy proxy → i18n package (33 locales)
│   │
│   ├── i18n/                   # 33-locale resource pack (32 languages + Дед)
│   │   ├── __init__.py, _compat.py, _container.py, _context.py, _engine.py
│   │   ├── en.py, ru.py, est.py, ja.py, ded.py, ... (33 locale modules)
│   │   └── flags/              # Country flag renderers
│   │
│   └── watcher/                # Automation + prompt drainage engine
│       ├── __init__.py
│       ├── adapter.py          # Abstract probe adapter interface
│       ├── cdp.py              # Chrome DevTools Protocol driver
│       ├── engine.py           # Watcher execution loop + state machine
│       ├── limit_scan.py       # Cross-agent limit scanner
│       ├── probes.py           # Multi-probe state combinators
│       ├── queue.py            # Queue model (QueueItem, SendIntent, pinning)
│       ├── sender.py           # Output dispatch (CDP / Win32 key injection)
│       ├── skills.py           # Skill definitions + prompt wrappers
│       └── win32.py            # Native Win32 window + control probe
│
├── ui/                         # PyQt6 UI components + mixins
│   ├── analog_clock.py         # Custom-painted analog clock widget
│   ├── backup_dialog.py        # DB export/import + backup snapshot dialog
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
│   ├── formatting_mixin.py     # Markdown formatting shortcuts
│   ├── hashtag_dialog.py       # Tag search + silo filter overlay
│   ├── header_format_dialog.py # Date/time timestamp format dialog
│   ├── help_dialog.py          # Keyboard shortcuts + interactive guide
│   ├── hotkey_mixin.py         # Hotkey binding mixin for main window
│   ├── layout_shortcuts.py     # Physical VK shortcut mapping (layout-indep)
│   ├── markdown_highlighter.py # QSyntaxHighlighter for live markdown
│   ├── pie_menu.py             # QuickListWidget radial context menu
│   ├── queue_panel.py          # Watcher queue dialog
│   ├── resizers.py             # Window resize handle controls
│   ├── scaling_mixin.py        # UI DPI + font scaling mixin
│   ├── search_mixin.py         # Multi-word AND search filter
│   ├── send_selection_mixin.py # Send selection via watcher
│   ├── settings.py             # Preferences dialog (themes, hotkeys, sounds)
│   ├── silo_kanban.py          # Markdown kanban board (T-630)
│   ├── silo_settings_dialog.py # Per-silo config (color, project links)
│   ├── silo_table.py           # Markdown table builder (T-630)
│   ├── kanban_widget.py        # Kanban board view widget (silo_kanban backend)
│   ├── table_widget.py         # Table view widget (silo_table backend)
│   ├── silo_region.py          # Silo list region: drag, gaps, multi-select
│   ├── snippet_ops_mixin.py    # Silo ops (trash, move, duplicate, clear)
│   ├── snippet_panel.py        # Silo tree + F1-F10 snippet buttons
│   ├── sound_settings_dialog.py # Per-event sound controls (enabled/file/volume)
│   ├── theme_mixin.py          # Vintage theme styling + QSS generator
│   ├── timer_dialog.py         # Pomodoro + alarm timer setup dialog
│   ├── timer_toast.py          # Floating notification toast widget
│   ├── toolbar_reorder.py      # Drag-and-drop toolbar button reorder
│   ├── trash_dialog.py         # Trash bin + restore dialog
│   ├── tray_mixin.py           # Systray icon + context menu
│   ├── watcher_dialog.py       # Watcher config + script manager UI
│   ├── watcher_mixin.py        # Watcher engine window integration
│   ├── window_mixin.py         # Frameless move, snap, borderless controls
│   ├── window_presets_dialog.py # User-defined window position presets
│   └── zen_desktop.py          # 3-stage Zen/Solo desktop sweep (Ctrl+D)
│
├── presets/                    # .md silo templates, shipped as data dir (T-715)
│   └── 01_TODO.md ... 11_Prompt.md   # filename orders + names the menu entry
│
├── theme/                      # Theme presets
│   └── themes.py               # 9 built-in color themes + custom engine
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
| `core.state` | SQLite WAL persistence, domain-scoped dirty tracking, state sync, undo stack, per-category aliased stores |
| `core.hotkey*` | Win32 RegisterHotKey + native event filter, layout-independent dispatch |
| `core.watcher` | Prompt queue, CDP/Win32 automation, skill wrappers, limit scanner |
| `core.i18n` | 33-locale translation pack + proxy delegation from translations.py (with lazy loading) |
| `core.ctrlw` | Divider template engine (Ctrl+W / Alt+W) |
| `core.timers` | Timer model, due detection, serialization |
| `core.pomodoro` | Work/break state machine, focus timer |
| `ui.editor` | VaultTextEdit — folding, gutter, checkboxes, heatmap, margin marks, hide-markup |
| `ui.snippet_panel` | Silo tree, hierarchy, category tabs, F1-F10 slots, sidebar gaps, multi-select |
| `ui.silo_kanban` | Pure-text kanban board (Alt+arrows move cards, Enter new row) |
| `ui.silo_table` | Pure-text table editor (Tab walk cells, Enter new row) |
| `ui.file_container` | Per-silo folder drawer, asset preview, templates |
| `ui.theme_mixin` | 9 built-in themes + custom color engine + QSS generator |
| `ui.kanban_widget` | Kanban board view widget (silo_kanban backend) |
| `ui.table_widget` | Table view widget (silo_table backend) |
| `ui.silo_region` | Silo list region: drag, gaps, multi-select |
| `ui.fancy_zones` | Visual zone picker with 7 layout presets |
| `ui.window_presets_dialog` | User-saved window geometry presets (Ctrl+Q page) |
| `ui.zen_desktop` | 3-stage Ctrl+D: Zen, Solo (minimise others), back |
| `ui.toolbar_reorder` | Drag-and-drop toolbar button customization |
| `ui.flow_layout` | Responsive wrapping layout for compact settings panels |
| `ui.edit_guard` | Begin/endEditBlock guard — prevents freeze from unterminated edits |
| `utils.fonts` | Font resolution, bitmap font install, no-AA fallback |
| `utils.paths` | Portable execution — no registry, no AppData dependency |

## Module Count Summary

- **core/**: 19 modules + i18n/ (33 locales + 5 infra files = 38) + watcher/ (10 modules)
- **ui/**: 46 modules
- **utils/**: 5 modules
- **Total**: 121 `.py` files under `src/fastprompter/` (includes `main.py` + `__init__.py`; + `presets/` ships as a non-code data dir)
