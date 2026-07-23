# FastPrompter Core API & Class Reference

## Core Classes (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)
Central thread-safe data model managing application state, SQLite database persistence, and profile configuration.

#### Key Methods
- `__init__(profile_id=1)`: Initializes connection to SQLite database, enables WAL mode, and loads cached settings.
- `init_db()`: Executes schema creation (`presets`, `settings`, `temp_presets_v2`, `archive_temp_presets_v2`), runs migrations, and creates a startup backup `.bak`.
- `switch_profile(new_profile_id)`: Closes current DB connection, switches database path, and resets in-memory cache.
- `save_to_db(force=False)`: Atomically commits dirty state to SQLite database.
- `get_silo_text(cat, slot_idx)`: Returns content string for specified category/tab and silo index.
- `set_silo_text(cat, slot_idx, text)`: Sets content string for specified silo slot and flags database as dirty.
- `get_preset_content(cat, slot_idx)`: Retrieves snippet template text for `F1`-`F10` buttons.
- `set_preset_content(cat, slot_idx, name, content)`: Updates snippet template name and text.
- `toggle_silo_pinned(cat, slot_idx)`: Toggles pinned state of a silo.
- `toggle_silo_ticked(cat, slot_idx)`: Toggles tick mark (done status) of a silo.
- `set_silo_parent(cat, child_idx, parent_idx)`: Sets child-parent relationship for nested silo hierarchy.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)
Threaded background manager operating `pynput.keyboard.Listener` to handle global hotkeys system-wide.

#### Key Methods
- `start()`: Spawns hotkey listener thread.
- `stop()`: Halts keyboard listener.
- `update_hotkeys(hk_dict)`: Updates active hotkey map with new key combinations.

---

### `IPCServer` & `IPCClient` (`core/ipc_server.py`)
Local socket IPC mechanism ensuring single-instance enforcement and external command control.

#### Key Methods
- `start_server()`: Starts thread listening on local port (default `49152 + profile_id`).
- `send_command(cmd)`: Static helper sending string command to running FastPrompter process.

---

### `SoundManager` (`core/sound_manager.py`)
Audio playback manager supporting sound effects for UI clicks and typewriter key presses.

#### Key Methods
- `play_ui_click()`: Plays UI action click sound.
- `play_typewriter()`: Plays typewriter keystroke sound effect.
- `set_volume(volume_percent)`: Adjusts master playback volume (0-100%).

---

### `PomodoroEngine` (`core/pomodoro.py`)
State machine managing Pomodoro focus timer sessions, break intervals, and audio alerts.

#### Key Methods
- `start_work()`: Begins work interval timer.
- `start_break()`: Begins break interval timer.
- `pause()`: Pauses running timer.
- `reset()`: Resets timer state machine.

---

## UI Components & Mixins (`src/fastprompter/ui/`)

### `FastPrompterWindow` (`main.py`)
Main application QMainWindow orchestrating all panels, mixins, and top-level menu bars.

#### Inherited Mixins
- `WindowMixin`: Window moving, snapping, borderless frame operations.
- `ThemeMixin`: Application styling, vintage preset stylesheets.
- `ScalingMixin`: High DPI scaling and dynamic font size calculation.
- `SearchMixin`: Search bar filtering over silos and snippets.
- `SnippetOpsMixin`: Silo operations (trash, duplicate, clear, reorder).
- `WatcherMixin`: Watcher probe integration and queue interaction.
- `TrayMixin`: System tray icon, notifications, and context menu.

---

### `MarkdownEditor` (`ui/editor.py`)
Extended `QPlainTextEdit` control serving as the primary text editing canvas.

#### Key Features & Methods
- `MarkdownHighlighter`: Custom `QSyntaxHighlighter` attached for live syntax coloring.
- `LineNumberArea`: Custom paint event widget drawing line numbers and fold indicators (`▾`).
- `fold_header(block_num)` / `unfold_header(block_num)`: Collapses or expands Markdown header sections (`#` to `######`).
- `insert_timestamp_header()`: `Ctrl+E` shortcut logic inserting formatted timestamp title.

---

### `SnippetPanel` (`ui/snippet_panel.py`)
Sidebar container hosting category/project tabs, silo list view, and snippet quick-paste buttons (`F1`-`F10`).

#### Key Features & Methods
- `update_silo_list()`: Re-renders silo items with pins, ticks, tint colors, and nesting indentations.
- `on_silo_clicked(index)`: Selects active silo and loads content into `MarkdownEditor`.

---

### `FileContainerWidget` (`ui/file_container.py`)
Per-silo asset manager drawer attached to the active silo.

#### Key Features & Methods
- `load_files(cat, slot_idx)`: Reads folder contents from `data/silo_files/<cat>/<slot_idx>/`.
- `add_files(paths)`: Copies external files into silo file drawer.
- `apply_template(template_name)`: Creates predefined folder tree structure (e.g. `IN/`, `OUT/`, `DOCS/`).
