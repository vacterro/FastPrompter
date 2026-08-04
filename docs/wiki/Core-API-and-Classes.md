# FastPrompter Core API & Class Reference

## Core Classes (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

Thread-safe SQLite data model. Central state hub — all silos, snippets, settings, theme, queues go through this.

**Methods:**
- `__init__(profile_id=1)` — open SQLite conn, WAL mode, load cached settings
- `init_db()` — create/upgrade schema (presets, settings, temp_presets_v2, archive_temp_presets_v2), run startup .bak backup
- `switch_profile(new_profile_id)` — close current DB, switch path, reload
- `save_data_to_db(text, ui_settings, force)` — atomic dirty-state flush
- `mark_dirty()` — flag state as needing a save (async via auto-save timer)
- `reset_data()` — reinit in-memory defaults

**Data model:** Single `self.data` dict. Per-category stores aliased: `temp_presets` → `temp_presets_all[active_cat]`, `silo_colors` → `silo_colors_all[active_cat]`, etc. All `_all` keys auto-migrate on first access.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

Threaded pynput keyboard listener for system-wide hotkeys.

**Methods:**
- `start()` — spawn pynput listener thread
- `stop()` — halt listener
- `update_hotkeys(hk_dict)` — re-register hotkey map

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32 WH_KEYBOARD_LL hook. Intercepts physical VK codes — layout-independent. Works cross-layout (QWERTY/JCUKEN/AZERTY). Used for layout_shortcuts.py dispatch.

---

### `IpcServer` (`core/ipc_server.py`)

QLocalServer on named pipe `FastPrompter_Server_V15`. UUID token auth via `%TEMP%/fastprompter_ipc.token`.

**Methods:**
- `setup()` — start listening (recovers stale socket names with removeServer)
- `close()` — stop server
- `_handle_command()` — process SHOW command from second instance

**Helper:**
- `try_connect_to_server()` — probe running instance (returns QLocalSocket or None)

---

### `SoundManager` (`core/sound_manager.py`)

WAV playback for UI clicks, typewriter keys, timer alarms.

**Methods:**
- `play(name)`, `play_click()`, `play_tick()` — dispatch audio by event
- Volume controlled by `sound_volume` setting (0-10); winsound path scaled via `scale_wav_bytes()` / `scaled_wav_path()`
- `sound_ui` / `sound_typewriter` / per-event flags gate playback

---

### `PomodoroEngine` (`core/pomodoro.py`)

Work/break state machine with configurable intervals.

**Constants:** `PHASE_WORK`, `PHASE_BREAK`

**Methods:**
- `start_work()`, `start_break()`, `pause()`, `reset()` — lifecycle
- `tick(elapsed)` — advance timer, yield phase transitions
- `describe()` — human-readable state string
- `from_dict(data)` / `to_dict()` — JSON serialization

---

### `Timer` & `TimerManager` (`core/timers.py`)

Generic countdown timer. Color-coded urgency, sound on fire, snooze.

**Timer attributes:** `name`, `description`, `target` (datetime), `sound`, `volume`, `color_mode`, `color`

**Methods:**
- `remaining()` — seconds until target
- `snooze(minutes)` — push target forward
- `display_color()` — urgency color (green/yellow/red)
- `collect_due(timers)` — return due timer list
- `next_due(timers)` — soonest timer
- `save_timers(data)` / `load_timers(data)` — serialization

---

### `DurationParser` (`core/duration.py`)

Human-readable duration parsing.

- `parse_duration(text)` — "2h 30m" → seconds
- `format_remaining(seconds, short=False, minutes=False)` — "2h 30m" → "2h" or "4d 11h 05m"
- `format_duration(seconds)` — full format string

---

### `HashtagIndex` (`core/hashtags.py`)

Cross-silo hashtag extraction + search.

- `extract_tags(text)` — return set of `#tag` strings
- `index_silo(cat, slot, text)` — tag → silo index
- `search(tag)` — all silos containing tag across categories

---

### `DividerEngine` (`core/ctrlw.py`)

Ctrl+W / Alt+W template insertion.

- `insert_divider(editor, template, upward)` — insert horizontal rule, strip duplicate bullets on split
- `simulate(editor, upward)` — preview insert position

---

### `HeaderFormatter` (`core/header.py`)

Ctrl+E header insertion. Configurable: rule line, gap, bullet, alignment, timestamp stamp.

- `format_header(editor, config)` — format current line as header

---

### `Watcher Engine Modules` (`core/watcher/`)

| Module | Role |
|---|---|
| `engine.py` | Finite state machine: DISARMED → ARMED → WATCHING → SENDING |
| `cdp.py` | Chrome CDP attach + evaluate + read-back verification (Electron apps) |
| `win32.py` | Win32 window probe — foreground, caret, focus detection |
| `probes.py` | Multi-probe state combinators + combined matrix |
| `queue.py` | QueueItem, SendIntent, pinning, per-queue key, persistence |
| `sender.py` | CDP + Win32 keystroke injection with read-back verification |
| `skills.py` | Prompt skill wrappers — prefix/template transforms |
| `adapter.py` | Abstract probe adapter interface |
| `limit_scan.py` | Cross-agent limit scanner + auto-timer creation |

---

## UI Components (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow. Mixin composition (declaration order):
1. FormattingMixin — markdown formatting shortcuts
2. HotkeyMixin — hotkey binding interface
3. ScalingMixin — DPI/font scaling
4. SearchMixin — search bar over silos
5. SendSelectionMixin — send text via watcher
6. SnippetOpsMixin — silo ops (trash, duplicate, reorder)
7. ThemeMixin — app stylesheet, vintage presets
8. TrayMixin — system tray icon + menu
9. WatcherMixin — watcher engine integration
10. WindowMixin — frameless window + snapping

**Key properties:** `_font_size`, `_font_family`, `_ui_scale`, `_button_scale`, `_sidebar_right`, `_always_on_top`, `_normal_window`

**Key methods:**
- `init_ui()` — build window, header toolbar, splitter, editor, sidebar, status bar
- `setup_single_instance_server()` — IPC init
- `register_all_hotkeys()` — bind pynput + PyQt shortcuts
- `apply_font()` / `apply_theme()` — cascade font/theme changes
- `place_window()` — restore saved geometry or apply default snap
- `_switch_to_slot(slot, initial)` — load silo into editor, save cursor state
- `capture_silo_state()` / `restore_silo_state()` — per-silo cursor/scroll/fold/heat persistence

---

### `VaultTextEdit` (`ui/editor.py`)

Extended QPlainTextEdit. Markdown editing canvas.

**Features:**
- MarkdownHighlighter — live syntax coloring
- LineNumberArea — gutter: line numbers + fold arrows (▾) + margin marks
- `fold_header(block_num)` / `unfold_header(block_num)` — section collapse
- `queue_current_line()` — anchor watcher item to block
- `set_queue_anchor(block, id)` — queue line anchoring
- `collect_line_marks()` / `apply_line_marks()` — per-line margin mark persistence
- `collect_line_heat()` / `apply_line_heat()` — recency heatmap
- `block_for_queue_item(id)` — find block by queue anchor
- `toggle_checkbox()` — `- [ ]` ↔ `- [x]`
- `toggle_hide_markup(checked)` — conceal ** * ~~ ` markers (T-603)
- Image pills — `![alt](url)` → 150px clickable button

---

### `SnippetPanel` (ui/snippet_panel.py)

Sidebar silo list + F1-F10 buttons.

**Classes:**
- `SnippetWidget` — sidebar panel: category tabs + silo list
- `DraggableSiloButton` — individual silo button (pin, tick, color, file icon, drag)
- `WheelPager` — scroll-synced pager for silo list
- `DropVerticalWidget` — drop zone for hierarchy nesting

**Features:**
- Up to 100 silos per tab
- Pins, ticks, recency heatmap, hierarchy (drag to nest)
- Sidebar gaps — user-defined spacer bars (Ctrl+drag to move)
- Multi-select — Shift=range, Ctrl=toggle, batch delete/save/clear
- Number-box mode — project switcher as numbered button row (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

Per-silo file drawer. Opens below editor.

- `load_files(cat, slot)` — read folder contents
- `add_files(paths)` — copy external files into silo folder
- `apply_template(name)` — create folder structure (IN/OUT/DOCS/Assets/Drafts)
- Image preview, link mode, drag-and-drop
- Silo backup — Ctrl+click 📁 exports silo text

---

### `SiloTable` (`ui/silo_table.py`)

Pure-text markdown table builder. No Qt tables — works on plain markdown.

- Tab/Shift+Tab: walk cells; Tab off last → new row
- Enter: new row (not split)
- Cell editing via inline markdown

---

### `SiloKanban` (`ui/silo_kanban.py`)

Pure-text markdown kanban board. Cards are markdown list items.

- Alt+↑/↓: move card up/down
- Alt+←/→: move card to adjacent column
- Enter on empty board line: new card
- Click checkbox: toggle done

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)

Visual screen zone picker. 7 layout presets (TL, TR, BL, BR, Center, Full, Cursor). Click zone to snap.

---

### `WindowPresetsDialog` (`ui/window_presets_dialog.py`)

User-defined window position presets. Up to 10 saved geometries as screen fractions.

- Save current geometry, rename, reorder, re-capture
- Apply from Ctrl+Q picker page
- Per-monitor fraction saves (survives monitor change)

---

### `TimerToast` (`ui/timer_toast.py`)

Floating notification toast for timer alarms. Win95 3D bevels, theme colors, snooze button.

### `ToolbarReorder` (`ui/toolbar_reorder.py`)

Drag-and-drop toolbar customization. Visible gap widgets. Reset button.

### `Overflow Menu` (`main.py`)

When header < 700px: hidden buttons collected in » popup. Every formatting, navigation, tool still reachable.

### `EditGuard` (`ui/edit_guard.py`)

Context manager: `with edit_block(widget): ...` wraps begin/endEditBlock. Prevents Qt freeze from unterminated editing operations.
