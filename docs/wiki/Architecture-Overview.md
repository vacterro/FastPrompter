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

SQLite DB (`data/local_data_v15.db`) with WAL + synchronous=NORMAL. Key tables: `presets` (snippets), `settings` (k/v), `temp_presets_v2` (silo text), `archive_temp_presets_v2` (archived silos). State uses granular domain dirty-tracking (`settings`, `snippets`, `temp`, `arc`) to bypass expensive full-set DB diffs on high-frequency view/text edits.

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

**v0.8.43 audit hardening (T-1019):** the queue an armed run drains is now pinned to its owning `(category, slot)`, so a project/silo switch mid-session can no longer feed a different silo's backlog. Physical sends are tracked per dispatch, so a stale (slow) completion can't clear the quiesce barrier early. Glob/stat/SQLite probe sampling runs on a dedicated worker thread (`_WatcherProbeWorker`), keeping tens-of-milliseconds file and database I/O out of the GUI timer callback while preserving conservative BUSY semantics.

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

**v0.8.43–v0.8.45 audit hardening:** the portable Markdown snapshot captures an *immutable* copy of state at request time rather than the live mutable dict, so the generation dispatched after a save is exactly the committed state that requested it — never uncommitted future edits. While a profile's backup job is active, repeated eligible saves only record that a newer state is wanted and coalesce; the newest state is exported on the next eligible run (PERF-008 / CORE-002 / CORE-003). The filesystem probe negative cache is bounded (≤500 entries) and swept on read, so repeated absent-path lookups don't churn or grow without limit (PERF-004). The snapshot carries the exact content generation (`content_gen`) of the state it was captured from (W2-008).

### 11. Typecheck / Typo Checker (`core/typecheck.py`)

A dictionary-based, non-recursive typo checker for silo text. Single linear scan per pass — a word is visited exactly once, no re-entrancy conflicts with the editor's own highlighting passes. Stays smart instead of noisy: skips code fences, inline code, URLs, e-mails, hashtags, @mentions, hex colours, and any word glued to an identifier character (`foo.bar`, `snake_case`, `camelCase`, `#tag`). Acronyms and mixed-case identifiers are never flagged. Contractions are checked in contracted form with de-contracted fallback. Only flags words in scripts the dictionary covers (Latin/English ~10k words + UI vocabulary of every app language); stays silent for Cyrillic, CJK, etc. — flagging what you cannot judge is the "dumb" behaviour this module avoids. The user dictionary (`typo_user_words` setting) extends the pool; suggestions come from difflib over the whole pool. The module is Qt-free for unit-testability.

### 12. Sync-Project (`core/project_sync.py`)

Folder↔silo two-way sync. A Sync-Project binds a project tab to a folder; every text file that passes the include/exclude filters becomes a silo (slot 0..N-1 in file-name order; extra files become new silos up to the 100-silo cap). Two-way and live: app edits are pushed to the file (debounced, and on every DB save), external file changes are applied back into the silo unless the silo holds unsaved app-side text (the app side wins while it is being typed). Exclude patterns match the file name (fnmatch-style) or any path component (substring). Pure logic (Qt-free) — the UI wiring (QFileSystemWatcher, debounce timers) lives in `main.py`.

### 13. Per-Silo File Links

Each silo can have an associated two-way file link target (`silo_links` / `silo_links_all` settings). The link loads the file into the silo and keeps both sides synchronized live; unlinking stops the exchange while preserving the silo. This complements the Sync-Project feature: while Sync-Project auto-binds a whole folder, per-silo links let the user manually pin a single file to a single silo.

### 14. Passed-Event Alert

Timer silos whose countdown has elapsed (passed) are highlighted with a configurable color (`passed_event_color`), making it visually obvious which deadlines have passed at a glance. Toggled via `passed_alert_enabled`.

### 15. Interval Notifications (`main.py` + `ui/timer_dialog.py`)

24h clock-aligned or elapsed-time scheduled reminders. Rules are stored in the `interval_notifs` setting (JSON list). Each rule defines a name, interval in minutes, sound reference, volume, active hours (start/end minute of day), and firing mode (`clock` = aligned to minute-of-day, `elapsed` = interval since last fire). Only the highest-priority rule fires per tick when multiple collide. Default presets: Morning (07:00–11:00), Noon (12:00), Day & Evening (13:00–21:00), Night (22:00–06:00), all at 60-min intervals and 1.0 volume. Rule defaults live in `core/state.py`; W2-005 added the per-rule **Show in top bar** toggle with its next-occurrence countdown beside the clock.

### 16. Periodic Backup (`core/state.py`)

Off-critical-path `.bak` refresh on a daemon thread (PERF-001). Coalesced per profile: at most one job in flight, a request arriving mid-job marks pending and the finishing job drains it. Each job opens its own short-lived source connection — the caller's live connection is never shared across threads. Publication goes through the existing atomic temp-swap + validate-before-swap path, so the previous good `.bak` survives any failure.
