# FastPrompter System Architecture Overview

## Overview
FastPrompter is a portable scratchpad and snippet manager built with Python 3.11+ and PyQt6. It provides instant floating access (`Alt+X`), multi-project tabs, tab-aware silos (up to 100 per tab), global/local hotkeys, markdown editing with live syntax highlighting and section folding, custom themes, sound effects, file container attachments per silo, Pomodoro timer, Watcher integration, and SAIPEN tracking viewer.

## High-Level Architecture Diagram
```
+-----------------------------------------------------------------------------------+
|                                  FastPrompter UI                                  |
|  +---------------------+  +--------------------------+  +----------------------+  |
|  |    SnippetPanel     |  |       EditorPanel        |  |     QueuePanel       |  |
|  |  (F1-F10 Snippets)  |  | (MarkdownEditor + Mixins)|  |   (Watcher Queue)    |  |
|  +---------------------+  +--------------------------+  +----------------------+  |
+-----------------------------------------+-----------------------------------------+
                                          | Events / State Sync
                                          v
+-----------------------------------------------------------------------------------+
|                             FastPrompterState (Core)                              |
|  - SQLite Storage (WAL mode, automatic backup)                                     |
|  - In-memory cache: silos, snippets, settings, theme, hotkeys                      |
+-----------------------------------------+-----------------------------------------+
                                          | Systems Management
     +-------------------+----------------+------------------+------------------+
     v                   v                v                  v                  v
+----------+     +---------------+  +-----------+    +---------------+  +---------------+
| Hotkeys  |     |  IPC Server   |  |   Sound   |    |    Watcher    |  |  File Container|
| (pynput) |     |  (Single Inst)|  |  Manager  |    | Engine/Probes |  | & Trash Mgt   |
+----------+     +---------------+  +-----------+    +---------------+  +---------------+
```

## System Subsystems

### 1. Application Core & Lifecycle
- **Entry Point (`main.py` / `main_entry`)**: Initializes QApplication, SingleInstance IPC check, database connection, global exception hooks, UI window construction, and system tray integration.
- **IPC Server (`core/ipc_server.py`)**: Listens on a local socket to enforce single-instance behavior and accept external commands (toggle window, paste text).

### 2. State & Storage Layer (`core/state.py`)
- **SQLite Database**: Operates with `PRAGMA journal_mode=WAL` and `synchronous=NORMAL` for speed and transactional stability. Automatic database backup `.bak` is maintained on startup.
- **Tab-aware Silos (`temp_presets_v2`)**: Up to 100 scratch silos per project tab with color tints, pinning, ticking, folder links, and hierarchy (parent-child relationships).
- **Snippets (`presets`)**: Up to 10 reusable text snippets per project tab triggered via `F1`-`F10`.
- **Settings Store (`settings`)**: Key-value store for app configuration, geometry, hotkeys, theme preferences, and flags.

### 3. Editor & Formatting Engine
- **Markdown Highlighter (`ui/markdown_highlighter.py`)**: Real-time syntax highlighting for headings, list markers, code fences, blockquotes, bold/italic formatting, and checkboxes.
- **Code Block Folding & Line Gutter**: Custom QPlainTextEdit extensions supporting line numbers, fold toggles (`▾`), fence copy buttons, and header section collapses.
- **Drop Overlay (`ui/drop_overlay.py`)**: Smart drop target offering 4 drop actions: insert text, insert markdown link, copy file to Silo File Container, or create shortcut.

### 4. Hotkey System (`core/hotkeys.py`, `core/hotkey_filter.py`)
- **Global Listener**: Uses `pynput` keyboard listener to capture global triggers (e.g. `Alt+X`) even when unfocused.
- **Native Windows Filter (`hotkey_filter.py`)**: Win32 API hook (`WM_HOTKEY`) handling background key events with fallbacks to avoid key clashes.

### 5. File Container & Trash Management
- **File Container (`ui/file_container.py`)**: Per-silo disk storage directory located inside `data/silo_files/<tab>/<silo_idx>/`. Supports image preview, link mode, drag-and-drop, and custom folder templates.
- **Trash Manager**: Soft-deletion system storing deleted silos and attached files in `_trash/` with timestamped folders and undo capabilities (`Ctrl+Z`).

### 6. SAIPEN & External Watcher Subsystem (`core/watcher/`, `ui/saipen_dialog.py`)
- **SAIPEN Tracking**: Integrates with `.saipen` project roots to present live STATE, BOARD, and LOG data in dedicated dialogs.
- **Watcher Engine**: Background automation probe system supporting Chrome CDP, Win32 window monitoring, and automated input queues.
