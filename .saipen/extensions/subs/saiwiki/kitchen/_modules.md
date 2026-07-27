# FastPrompter Module Structure

## Codebase Map (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # Main application entry point, window setup, and event loop
├── core/                       # Core backend logic, state management, and subsystems
│   ├── config.py               # Theme color extractors & tray icon generators
│   ├── duration.py             # Time parsing and human-readable duration formatters
│   ├── hashtags.py             # Hashtag extraction and indexing utilities
│   ├── hotkey_filter.py        # Windows native hook filter for global hotkey processing
│   ├── hotkeys.py              # Pynput-based global hotkey manager thread
│   ├── ipc_server.py           # Single-instance IPC socket server & client listener
│   ├── logging.py              # Application logger setup and file output handler
│   ├── pomodoro.py             # Pomodoro timer engine, work/break state machine
│   ├── sound_manager.py        # Audio playback engine (UI clicks, typewriter sounds)
│   ├── state.py                # SQLite database interface & state management model
│   ├── timers.py               # Timer manager for countdowns, alarms, and notifications
│   ├── translations.py         # Multi-language translation strings (22 languages + Дед)
│   ├── i18n/                   # Language resource files and flag assets
│   └── watcher/                # Automation & inspection engine
│       ├── adapter.py          # Abstract probe adapter interface
│       ├── cdp_probe.py        # Chrome DevTools Protocol probe driver
│       ├── engine.py           # Watcher execution loop and rule evaluator
│       ├── queue.py            # Async action queue for watcher operations
│       ├── sender.py           # Output dispatcher for automated key/text sending
│       └── win32_probe.py      # Native Windows API window & control probe
├── ui/                         # PyQt6 User Interface components & mixins
│   ├── analog_clock.py         # Custom painted analog clock widget
│   ├── backup_dialog.py        # Export/import database & text backup dialog
│   ├── cursor_theme.py         # Retro mouse cursor theme overlay manager
│   ├── drop_overlay.py         # Interactive drag-and-drop target overlay widget
│   ├── edit_guard.py           # Read-only edit lock guard widget wrapper
│   ├── editor.py               # Main Markdown editor, code block renderer, & line gutter
│   ├── fancy_zones.py          # Screen snap & window positioning utility
│   ├── file_container.py       # Silo asset file drawer and template manager widget
│   ├── flags.py                # Vector/raster country flag renderer for language selection
│   ├── flow_layout.py          # Dynamic reflowing layout for tag & button bars
│   ├── formatting_mixin.py     # Markdown editor formatting shortcuts (bold, list, code block)
│   ├── hashtag_dialog.py       # Tag search and silo filter overlay
│   ├── header_format_dialog.py # Date/time timestamp format customization dialog
│   ├── help_dialog.py          # Keyboard shortcuts & interactive user guide
│   ├── hotkey_mixin.py         # Hotkey binding interface mixin for main window
│   ├── layout_shortcuts.py     # Layout configuration & quick switch shortcuts
│   ├── markdown_highlighter.py # QSyntaxHighlighter for live Markdown syntax styling
│   ├── pie_menu.py             # Radial contextual pie menu widget
│   ├── queue_panel.py          # Watcher task queue panel
│   ├── resizers.py             # Custom window resize handle controls
│   ├── saipen_dialog.py        # SAIPEN project tracking viewer dialog (STATE, BOARD, LOG)
│   ├── scaling_mixin.py        # UI DPI & global font scaling mixin
│   ├── search_mixin.py         # Smart multi-word AND search filter logic
│   ├── settings.py             # Preferences dialog (themes, hotkeys, sounds, flags)
│   ├── silo_settings_dialog.py # Per-silo configuration (custom colors, project links)
│   ├── snippet_ops_mixin.py    # Operations on silos & snippets (trash, move, duplicate)
│   ├── snippet_panel.py        # Silo tree view & F1-F10 snippet buttons panel
│   ├── theme_mixin.py          # Vintage theme styling, stylesheet generator, & palette builder
│   ├── timer_dialog.py         # Pomodoro & alarm timer settings dialog
│   ├── timer_toast.py          # Floating notification toast widget for timer alarms
│   ├── toolbar_reorder.py      # Drag-and-drop toolbar button reordering utility
│   ├── trash_dialog.py         # Trash bin management & file restore dialog
│   ├── tray_mixin.py           # System tray icon, context menu, & quick actions
│   ├── watcher_dialog.py       # Watcher configuration and script manager UI
│   ├── watcher_mixin.py        # Main window integration mixin for Watcher engine
│   └── window_mixin.py         # Frameless window moving, snapping, & borderless controls
└── utils/                      # Low-level helper utilities
    ├── fonts.py                # System font loader & fallback resolver
    ├── paths.py                # Portable path resolver for executable & user data
    ├── portable_backup.py      # Portable zip backup archive builder
    └── textfit.py              # Dynamic text truncation & label fitting helpers
```

## Subsystem Functional Responsibilities

| Package / Module | Primary Responsibility |
|---|---|
| `core.state` | Data model, SQLite WAL persistence, state synchronization, undo stack |
| `core.hotkeys` | Pynput global hotkey listener & dispatch |
| `core.ipc_server` | Single instance enforcement & CLI IPC message receiver |
| `core.pomodoro` | Pomodoro session timer state machine & work/break interval manager |
| `core.translations` | 22-language translation dictionary & locale switching engine |
| `ui.editor` | Extended `QPlainTextEdit` with folding, line gutter, checkboxes, and line counts |
| `ui.snippet_panel` | Silo tree view, hierarchy management, category tabs, and F1-F10 snippet slots |
| `ui.file_container` | Per-silo folder drawer, asset attachment preview, and template generator |
| `ui.theme_mixin` | 6 retro Win95 themes, custom color engine, and CSS stylesheet generator |
| `ui.saipen_dialog` | Integration viewer for `.saipen` AI project tracking files |
| `utils.paths` | Ensures portable execution without touching system registries orAppData |
