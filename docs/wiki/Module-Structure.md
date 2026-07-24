# FastPrompter Module Structure

## Codebase Map (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # Main entry, QMainWindow, event loop, mixin orchestration
├── core/                       # Backend logic, state management, subsystems
│   ├── config.py               # Theme color extractors & tray icon generators
│   ├── ctrlw.py                # Ctrl+W / Alt+W divider insertion engine
│   ├── duration.py             # Time parsing & human-readable duration formatters
│   ├── hashtags.py             # Hashtag extraction and indexing utilities
│   ├── header.py               # Ctrl+E header formatting core logic
│   ├── hotkey_filter.py        # Windows native hook filter for global hotkey processing
│   ├── hotkeys.py              # Pynput-based global hotkey manager thread
│   ├── ipc_server.py           # Single-instance IPC socket server & listener
│   ├── limits.py               # Agent reset-limit scanner and timer creation
│   ├── logging.py              # Logger setup and file output handler
│   ├── pomodoro.py             # Pomodoro timer engine, work/break state machine
│   ├── sound_manager.py        # Audio playback (clicks, typewriter sounds, alarms)
│   ├── state.py                # SQLite DB interface & state management model
│   ├── timers.py               # Timer manager for countdowns, alarms, notifications
│   ├── translations.py         # Legacy translation proxy → i18n package
│   ├── i18n/                   # 22-language resource pack + flag assets
│   └── watcher/                # Automation & prompt-drainage engine
│       ├── adapter.py          # Abstract probe adapter interface
│       ├── cdp.py              # Chrome DevTools Protocol probe driver
│       ├── engine.py           # Watcher execution loop and rule evaluator
│       ├── limit_scan.py       # Agent reset-limit scanner (cross-agent)
│       ├── probes.py           # Probe state combinators and matrix logic
│       ├── queue.py            # Async action queue for watcher operations
│       ├── sender.py           # Output dispatcher (CDP / Win32 key injection)
│       ├── skills.py           # Skill definitions and prompt wrappers
│       └── win32.py            # Native Windows API window & control probe
├── ui/                         # PyQt6 User Interface components & mixins
│   ├── analog_clock.py         # Custom painted analog clock widget
│   ├── backup_dialog.py        # Export/import database & text backup dialog
│   ├── ctrlw_settings.py       # Ctrl+W/Alt+W template configuration UI
│   ├── cursor_theme.py         # Retro mouse cursor theme overlay manager
│   ├── drop_overlay.py         # Interactive drag-and-drop target overlay widget
│   ├── edit_guard.py           # Read-only edit lock guard wrapper
│   ├── editor.py               # Main Markdown editor, code block renderer, line gutter
│   ├── fancy_zones.py          # Fancy Zone screen-snap overlay picker
│   ├── file_container.py       # Silo asset file drawer and template manager
│   ├── flags.py                # Vector/raster country flag renderer for language selector
│   ├── flow_layout.py          # Dynamic reflowing layout for settings tag/button bars
│   ├── formatting_mixin.py     # Markdown formatting shortcuts (bold, list, code)
│   ├── hashtag_dialog.py       # Tag search and silo filter overlay
│   ├── header_format_dialog.py # Date/time timestamp format customization dialog
│   ├── help_dialog.py          # Keyboard shortcuts & interactive user guide
│   ├── hotkey_mixin.py         # Hotkey binding interface mixin for main window
│   ├── layout_shortcuts.py     # Layout-independent physical VK shortcut mapping
│   ├── markdown_highlighter.py # QSyntaxHighlighter for live Markdown syntax styling
│   ├── pie_menu.py             # Radial contextual pie menu widget
│   ├── queue_panel.py          # Watcher task queue panel/dialog
│   ├── resizers.py             # Custom window resize handle controls
│   ├── saipen_dialog.py        # SAIPEN project viewer (STATE, BOARD, LOG)
│   ├── scaling_mixin.py        # UI DPI & global font scaling mixin
│   ├── search_mixin.py         # Smart multi-word AND search filter logic
│   ├── send_selection_mixin.py # Send selected text to target via watcher
│   ├── settings.py             # Preferences dialog (themes, hotkeys, sounds, flags)
│   ├── silo_settings_dialog.py # Per-silo config (custom colors, project links)
│   ├── snippet_ops_mixin.py    # Silo operations (trash, move, duplicate, clear)
│   ├── snippet_panel.py        # Silo tree view & F1-F10 snippet buttons panel
│   ├── theme_mixin.py          # Vintage theme styling & stylesheet generator
│   ├── timer_dialog.py         # Pomodoro & alarm timer settings dialog
│   ├── timer_toast.py          # Floating notification toast for timer alarms
│   ├── toolbar_reorder.py      # Drag-and-drop toolbar button reordering
│   ├── trash_dialog.py         # Trash bin management & restore dialog
│   ├── tray_mixin.py           # System tray icon, context menu & quick actions
│   ├── watcher_dialog.py       # Watcher configuration and script manager UI
│   ├── watcher_mixin.py        # Main window integration for Watcher engine
│   └── window_mixin.py         # Frameless window moving, snapping, borderless controls
├── theme/                      # Theme presets
│   └── themes.py               # 6 retro Win95 theme color definitions
└── utils/                      # Low-level helper utilities
    ├── fonts.py                # System font loader, fallback resolver, no_aa helper
    ├── paths.py                # Portable path resolver for executable & user data
    ├── portable_backup.py      # Portable zip backup archive builder
    └── textfit.py              # Dynamic text truncation & label fitting helpers
```

## Subsystem Functional Responsibilities

| Package / Module | Primary Responsibility |
|---|---|
| `core.state` | SQLite WAL persistence, state sync, undo stack |
| `core.hotkeys` | Global hotkey listener & dispatch |
| `core.watcher` | Prompt queue, CDP/Win32 automation, skill wrappers |
| `core.i18n` | 22-language translation pack with proxy delegation |
| `core.ctrlw` | Divider template engine (Ctrl+W / Alt+W) |
| `core.timers` | Countdown timer model, due detection, persistence |
| `ui.editor` | Extended QPlainTextEdit with folding, gutter, checkboxes, heat |
| `ui.snippet_panel` | Silo tree, hierarchy, category tabs, F1-F10 slots |
| `ui.file_container` | Per-silo folder drawer, asset preview, templates |
| `ui.theme_mixin` | 6 retro Win95 themes, custom color engine, QSS generator |
| `ui.saipen_dialog` | SAIPEN project tracking viewer (.saipen integration) |
| `ui.fancy_zones` | Visual zone picker with 7 layout presets |
| `ui.flow_layout` | Responsive heightForWidth layout for compact panels |
| `ui.toolbar_reorder` | Drag-and-drop toolbar button customization |
| `utils.fonts` | Font resolution, bitmap font install, non-AA strategy |
| `utils.paths` | Portable execution (no registry/AppData dependencies) |
