# FastPrompter Core API & Class Reference

## Core Classes (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)
Central thread-safe data model managing application state, SQLite persistence, and profile config.

**Key Methods**:
- `__init__(profile_id=1)`: Opens SQLite connection, WAL mode, loads cached settings.
- `init_db()`: Creates schema (`presets`, `settings`, `temp_presets_v2`, `archive_temp_presets_v2`), runs migrations, startup `.bak`.
- `switch_profile(new_profile_id)`: Closes current DB, switches path, resets cache.
- `save_to_db(force=False)`: Atomically commits dirty state.
- `get_silo_text(cat, slot_idx)`: Returns silo content.
- `set_silo_text(cat, slot_idx, text)`: Sets silo content, marks dirty.
- `get_preset_content(cat, slot_idx)`: Gets snippet template (F1-F10).
- `set_preset_content(cat, slot_idx, name, content)`: Updates snippet.
- `toggle_silo_pinned(cat, slot_idx)`: Toggles pin state.
- `toggle_silo_ticked(cat, slot_idx)`: Toggles tick/done state.
- `set_silo_parent(cat, child_idx, parent_idx)`: Sets child-parent nesting.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)
Threaded `pynput.keyboard.Listener` for system-wide hotkeys.

**Key Methods**:
- `start()`: Spawns listener thread.
- `stop()`: Halts listener.
- `update_hotkeys(hk_dict)`: Updates active hotkey map.

---

### `HotkeyFilter` (`core/hotkey_filter.py`)
Windows native event filter for physical VK code detection (layout-independent dispatch).

---

### `IPCServer` & `IPCClient` (`core/ipc_server.py`)
Local socket IPC for single-instance enforcement and external commands.

**Key Methods**:
- `start_server()`: Listens on port `49152 + profile_id`.
- `send_command(cmd)`: Sends command to running instance.

---

### `SoundManager` (`core/sound_manager.py`)
Audio playback for UI clicks, typewriter keys, timer alarms.

**Key Methods**:
- `play_ui_click()`, `play_typewriter()`, `play_sound(name)`.

---

### `PomodoroEngine` (`core/pomodoro.py`)
Pomodoro state machine (work/break intervals).

**Key Methods**:
- `start_work()`, `start_break()`, `pause()`, `reset()`.
- `from_dict(d)`: Deserialize from stored dict.
- `to_dict()`: Serialize.

---

### `Timer` & `TimerManager` (`core/timers.py`)
Generic countdown timer model with sound, color, snooze.

**Key Methods**:
- `remaining()`: Seconds until target.
- `snooze(minutes)`: Push target forward.
- `display_color()`: Color code by urgency.
- `collect_due(timers)`: Returns list of due timers.
- `next_due(timers)`: Soonest timer.
- `save_timers(timers)` / `load_timers(data)`: Serialization.

---

### `DurationParser` (`core/duration.py`)
Human-readable duration parsing and formatting.

- `parse_duration(text)`: "2h 30m" → seconds.
- `format_remaining(seconds, short=False)`: "2h 30m" or "2h".
- `format_duration(seconds)`: Full format.

---

### `HashtagIndex` (`core/hashtags.py`)
Cross-silo hashtag extraction and search.

- `extract_tags(text)`: Returns set of `#tag` strings.
- `index_silo(cat, slot, text)`: Tags → silo map.
- `search(tag)`: All silos containing tag.

---

### `DividerEngine` (`core/ctrlw.py`)
Ctrl+W/Alt+W template engine.

- `insert_divider(editor, template, upward)`: Insert divider with formatting.
- `simulate(editor, upward)`: Preview insertion position.

---

### `HeaderFormatter` (`core/header.py`)
Ctrl+E header core logic.

- `format_header(editor, config)`: Insert header with rule/gap/timestamp/bullet.

---

### `Watcher Engine` (`core/watcher/`)
Prompt drainage and target automation subsystem.

| Module | Responsibility |
|---|---|
| `engine.py` | Finite state machine (DISARMED→ARMED→WATCHING→SENDING) |
| `cdp.py` | Chrome DevTools Protocol attachment & automation |
| `win32.py` | Win32 window probe (foreground, caret, focus) |
| `probes.py` | Multi-probe state combinators |
| `queue.py` | Queue model (`QueueItem`, `SendIntent`), pinning, persistence |
| `sender.py` | CDP/keystroke text injection |
| `skills.py` | Prompt skill wrappers (prefix/template) |
| `adapter.py` | Abstract probe adapter interface |
| `limit_scan.py` | Cross-agent limit scanner for timer creation |

---

## UI Components & Mixins (`src/fastprompter/ui/`)

### `FastPrompterWindow` (`main.py`)
Main QMainWindow orchestrating all panels, mixins, and header bar.

**Inherited Mixins** (in declaration order):
- `FormattingMixin`: Markdown editing shortcuts
- `HotkeyMixin`: Hotkey binding interface
- `ScalingMixin`: DPI/font scaling
- `SearchMixin`: Search bar over silos/snippets
- `SendSelectionMixin`: Send text via watcher
- `SnippetOpsMixin`: Silo ops (trash, duplicate, reorder)
- `ThemeMixin`: Application styling, vintage presets
- `TrayMixin`: System tray icon and menu
- `WatcherMixin`: Watcher integration
- `WindowMixin`: Frameless window moving/snapping

---

### `MarkdownEditor` (`ui/editor.py`)
Extended `QPlainTextEdit` — primary editing canvas.

**Key Features**:
- `MarkdownHighlighter`: Custom QSyntaxHighlighter for live syntax.
- `LineNumberArea`: Line numbers + fold indicators (`▾`).
- `fold_header(block_num)` / `unfold_header(block_num)`: Section collapse.
- `insert_timestamp_header()`: Ctrl+E logic.
- `collect_line_marks()` / `collect_line_heat()`: Per-line margin marks + heat data.
- `set_queue_anchor(block, item_id)`: Watcher queue line anchoring.
- Code fence gutter, collapsible images, checkbox click handlers.

---

### `SnippetPanel` (`ui/snippet_panel.py`)
Sidebar — category tabs, silo list, F1-F10 buttons.

**Key Features**:
- `update_silo_list()`: Silo items with pins, ticks, tints, nesting.
- `on_silo_clicked(index)`: Select silo → load into editor.
- Hierarchy drag-and-drop with parent/child nesting.
- Recency heatmap tinting.

---

### `FileContainerWidget` (`ui/file_container.py`)
Per-silo asset drawer.

- `load_files(cat, slot_idx)`: Read folder contents.
- `add_files(paths)`: Copy external files.
- `apply_template(name)`: Create folder structure (IN/OUT/DOCS).

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)
Visual screen-zone picker with 7 layout presets.

---

### `FlowLayout` (`ui/flow_layout.py`)
Responsive heightForWidth layout for compact Settings panels.

---

### `SaipenViewerDialog` (`ui/saipen_dialog.py`)
Dedicated viewer for `.saipen` STATE, BOARD, LOG files.

---

### `ToolbarReorder` (`ui/toolbar_reorder.py`)
Drag-and-drop toolbar button customization with visual gap indicators.

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
