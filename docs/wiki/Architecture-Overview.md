# FastPrompter Architecture Overview

## Overview

Portable scratchpad + prompt workbench. Python 3.11+, PyQt6. SQLite WAL persistence. Zero-install Nuitka EXE. Summon via Alt+X global hotkey, write, close — state persists instantly.

## High-Level Diagram

```
+------------------------------------------------------------------+
|                        FastPrompter UI (PyQt6)                   |
|  +------------------+  +--------------------+  +---------------+  |
|  | SnippetPanel     |  | VaultTextEdit      |  | QueuePanel    |  |
|  | (F1-F10 Silos)   |  | (Markdown + Mixins)|  | (Watcher Q)   |  |
|  +------------------+  +--------------------+  +---------------+  |
+----------------------------+-------------------------------------+
                             | events / state sync
                             v
+------------------------------------------------------------------+
|                    FastPrompterState (core)                       |
|  SQLite WAL DB — silos, snippets, settings, themes, queues       |
|  In-memory cache + undo stack + per-silo state (cursor/scroll)   |
+------------------------------------------------------------------+
      |         |          |          |            |
      v         v          v          v            v
+--------+ +---------+ +--------+ +---------+ +-----------+
|Hotkeys | | IPC     | | Sound  | | Watcher | | File      |
|(pynput)| |(QLocal) | |Manager | |Engine   | | Container |
+--------+ +---------+ +--------+ +---------+ +-----------+
```

## Core Subsystems

### 1. Application Lifecycle (`main.py`)

Entry point. QApplication init, single-instance IPC check (QLocalServer), DB connect, global exception hooks, UI window build, system tray, hotkey registration. All mixins compose onto FastPrompter (QMainWindow):

- FormattingMixin — markdown shortcuts (bold, italic, list, code)
- HotkeyMixin — shortcut binding interface
- ScalingMixin — DPI/font scaling
- SearchMixin — multi-word AND search
- SendSelectionMixin — send text via watcher
- SnippetOpsMixin — silo ops (trash, duplicate, reorder, clear)
- ThemeMixin — app stylesheet, 9 built-in themes + custom
- TrayMixin — systray icon + menu
- WatcherMixin — watcher engine integration
- WindowMixin — frameless window, snapping, borderless

### 2. IPC Single-Instance (`core/ipc_server.py`)

QLocalServer on named pipe `FastPrompter_Server_V15`. Second instance sends SHOW command → existing instance brings its window forward. UUID token in `%TEMP%/fastprompter_ipc.token` for auth. No more silent no-op on crash (server.removeServer recovers stale socket names).

### 3. State & Storage (`core/state.py`)

SQLite DB (`data/local_data_v15.db`) with WAL + synchronous=NORMAL. Key tables: `presets` (snippets), `settings` (k/v), `temp_presets_v2` (silo text), `archive_temp_presets_v2` (archived silos). 

Auto-backup on startup (full DB copy to `.bak`). Throttled incremental backup every 60s. Per-category data stores: `silo_colors_all`, `pinned_silos_all`, `silo_ticked_all`, `silo_children_all`, `silo_gaps_all`, `silo_project_paths_all`, etc. All aliased to flat keys (`temp_presets`) for active category.

### 4. Hotkey System (`core/hotkeys.py`, `core/hotkey_filter.py`)

Two-layer: (1) pynput global listener thread for summon/emergency quit; (2) PyQt6 QShortcut for window-local bindings. `HotkeyFilter` (Win32 WH_KEYBOARD_LL) intercepts physical VK codes — layout-independent. Works on QWERTY, JCUKEN, AZERTY, QWERTZ.

### 5. Editor Engine (`ui/editor.py`)

VaultTextEdit extends QPlainTextEdit. Features:
- MarkdownHighlighter — live syntax (headings, bold, italic, code fences, checkboxes, links, images)
- Line gutter — numbers, fold arrows (▾), code-fence copy button
- Section fold — click collapse on header blocks
- Collapsible images — `![alt](url)` renders as 150px clickable pill
- Drop overlay — 4-option drop target (insert text, insert link, copy file, shortcut)
- Margin marks — line-level pins, ticks, queue anchors, heatmap
- Hide markup mode — toggle `**bold**` → `bold` (T-603)

### 6. Silo System (`ui/snippet_panel.py`)

Up to 100 silos per project tab. Features:
- Pins (📌) — anchor to top
- Ticks (✅) — completion marker
- Hierarchy — drag onto another silo to nest (max depth 2)
- Recency heatmap — warm tint on recently edited
- Sidebar gaps — user-defined spacers (Ctrl+drag to move)
- Multi-select — Shift=range, Ctrl=toggle, batch ops
- File containers — per-silo disk folder (`data/silo_files/<cat>/<idx>/`)
- Kanban (Alt+arrows move cards) + Table builder (Tab walk cells) — T-630

### 7. Watcher Engine (`core/watcher/`)

Prompt drainage + target automation. Finite state machine: DISARMED → ARMED → WATCHING → SENDING. Chrome CDP (Electron apps) + Win32 window probes. Queue pinning per target. Rate limits: settle_ms=2500, min_gap_ms=4000, max_sends=25, max_failures=3.

### 8. Window Management (`ui/window_mixin.py`, `ui/zen_desktop.py`)

Frameless window, Win95 dark-gold aesthetic. Ctrl+Q cycles snap positions (7 zones + FancyZone picker + user presets). 3-stage Ctrl+D: Zen (minimal editor), Solo (minimise other windows), back. Overflow menu (») collects hidden buttons in ultra-narrow mode (<700px). Header density tiers auto-adjust (dense <1280px, ultra <700px).

### 9. Timer & Pomodoro (`core/timers.py`, `core/pomodoro.py`)

Countdown timers with color-coded urgency, snooze, toast notifications (Win95 3D bevels). Pomodoro work/break state machine.

### 10. Backup & Recovery

Multi-layer: (1) SQLite WAL — crash-safe writes; (2) `.bak` on startup + every 60s; (3) daily Markdown mirror to `~/Documents/.fastprompter/` (silos + snippets + archive per project); (4) portable backup ZIP builder.
