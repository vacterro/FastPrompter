# FastPrompter Architecture Overview

> **Freshness policy:** the README and `src/` are canonical; this page
> describes the v0.8.x codebase it was written against. Where a page and the
> code disagree, the code wins.

## Overview

Portable scratchpad + snippet workspace. Python 3.11+, PyQt6. SQLite WAL persistence. Zero-install Nuitka EXE. Summon via Alt+X global hotkey, write, close — state persists automatically.

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
|(Win32  | |(QLocal) | |Manager | |Engine   | | Container |
| Register| +---------+ +--------+ +---------+ +-----------+
|HotKey) |
+--------+
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

Auto-backup is validated backup-before-publish: a `.bak` copy is written before any publish and the throttle advances only on success, so the previous good copy survives every intermediate failure. Restore is atomic and validated (same-file guard, integrity + schema checks, future-schema fail-closed); DB migrations are versioned and transactional (v0.8.34/35). Per-category data stores: `silo_colors_all`, `pinned_silos_all`, `silo_ticked_all`, `silo_children_all`, `silo_gaps_all`, `silo_project_paths_all`, etc. All aliased to flat keys (`temp_presets`) for active category.

### 4. Hotkey System (`core/hotkeys.py`, `core/hotkey_filter.py`)

Two-layer: (1) Win32 `RegisterHotKey` via `core/hotkeys.py` for the global summon/quick-list/panic keys, dispatched from a `QAbstractNativeEventFilter` (`HotkeyFilter`, `core/hotkey_filter.py`) on `WM_HOTKEY`/`WM_SYSCOMMAND`; (2) PyQt6 `QShortcut` for window-local bindings. `core/hotkeys.py` resolves key names to virtual-key codes with `VkKeyScanW`, so physical keys work on QWERTY, JCUKEN, AZERTY, QWERTZ.

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
- File containers — per-silo disk folder (`data/files/<category-slug>/<silo-title-slug>/`, unique per slot)
- Kanban (Alt+arrows move cards) + Table builder (Tab walk cells) — T-630

### 7. Watcher Engine (`core/watcher/`)

Prompt drainage + target automation. Finite state machine: DISARMED → ARMED → WATCHING → SENDING. Chrome CDP (Electron apps) + Win32 window probes. Queue pinning per target. Rate limits: settle_ms=2500, min_gap_ms=4000, max_sends=25, max_failures=3.

### 8. Window Management (`ui/window_mixin.py`, `ui/zen_desktop.py`)

Frameless window, Win95 dark-gold aesthetic. Ctrl+Q cycles snap positions (7 zones + FancyZone picker + user presets). 3-stage Ctrl+D: Zen (minimal editor), Solo (minimise other windows), back. Overflow menu (») collects hidden buttons in ultra-narrow mode (<700px). Header density tiers auto-adjust (dense <1280px, ultra <700px).

### 9. Timer & Pomodoro (`core/timers.py`, `core/pomodoro.py`)

Countdown timers with color-coded urgency, snooze, toast notifications (Win95 3D bevels). Pomodoro work/break state machine.

### 10. Backup & Recovery

Multi-layer: (1) SQLite WAL — crash-safe writes; (2) validated `.bak`
backup-before-publish with a success-based throttle (the previous good copy
survives); (3) daily Markdown snapshot mirror to
`~/Documents/.fastprompter/` (silos + snippets + archive per project) — a
portable snapshot completes only when the `_COMPLETE` marker lands last, so
a partial export never looks finished; (4) atomic validated DB restore
(same-file guard, integrity + schema validation, atomic swap, future-schema
fail-closed). All backup writes go through the unified safe primitive
(temp sibling + atomic rename).
