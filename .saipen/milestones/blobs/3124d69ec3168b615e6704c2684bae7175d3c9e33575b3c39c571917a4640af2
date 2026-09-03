# FastPrompter Core API & Class Reference

## Core Classes (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

Thread-safe SQLite data model. Central state hub вЂ” all silos, snippets, settings, theme, queues go through this.

**Methods:**
- `__init__(profile_id=1)` вЂ” open SQLite conn, WAL mode, load cached settings
- `init_db()` вЂ” create/upgrade schema (presets, settings, temp_presets_v2, archive_temp_presets_v2), run startup .bak backup
- `switch_profile(new_profile_id)` вЂ” close current DB, switch path, reload
- `save_data_to_db(text, ui_settings, force)` вЂ” atomic dirty-state flush
- `mark_dirty()` вЂ” flag state as needing a save (async via auto-save timer)
- `reset_data()` вЂ” reinit in-memory defaults

**Data model:** Single `self.data` dict. Per-category stores aliased: `temp_presets` в†’ `temp_presets_all[active_cat]`, `silo_colors` в†’ `silo_colors_all[active_cat]`, etc. All `_all` keys auto-migrate on first access.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

Threaded pynput keyboard listener for system-wide hotkeys.

**Methods:**
- `start()` вЂ” spawn pynput listener thread
- `stop()` вЂ” halt listener
- `update_hotkeys(hk_dict)` вЂ” re-register hotkey map

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32 WH_KEYBOARD_LL hook. Intercepts physical VK codes вЂ” layout-independent. Works cross-layout (QWERTY/JCUKEN/AZERTY). Used for layout_shortcuts.py dispatch.

---

### `IpcServer` (`core/ipc_server.py`)

QLocalServer on named pipe `FastPrompter_Server_V15`. Token-only auth via `%TEMP%/fastprompter_ipc.token` вЂ” the SHOW command is accepted only with the token; there is no unauthenticated path (T-788).

**Methods:**
- `setup()` вЂ” start listening (recovers stale socket names with removeServer)
- `close()` вЂ” stop server
- `_handle_command()` вЂ” process SHOW command from second instance

**Helper:**
- `try_connect_to_server()` вЂ” probe running instance (returns QLocalSocket or None)

---

### `InstanceLock` (`core/instance_lock.py`)

Win32 named mutex (`Local\FastPrompter_Instance_...`) вЂ” single-instance
ownership. A frozen/lost owner is detected at startup and reported with a
diagnostic; the mutex can never be taken over by a second writer, so
split-brain instances are impossible by design (T-788).

---

### `SoundManager` (`core/sound_manager.py`)

WAV playback for UI clicks, typewriter keys, timer alarms, interval notifications.

**Methods:**
- `play(name)`, `play_file(file_name)`, `play_click()`, `play_tick()` — dispatch audio by event or literal file
- `play_sound_ref(ref, level)` — play by event name or `file:path.wav` reference with explicit volume (0.0–1.0); used by interval notifications and timer pool sounds
- Volume controlled by `sound_volume` setting (0-10); winsound path scaled via `scale_wav_bytes()` / `scaled_wav_path()`
- `sound_ui` / `sound_typewriter` / per-event flags gate playback
- Case-insensitive sound matching on selection sync (v0.8.55)

---

### `PomodoroEngine` (`core/pomodoro.py`)

Work/break state machine with configurable intervals.

**Constants:** `PHASE_WORK`, `PHASE_BREAK`

**Methods:**
- `start_work()`, `start_break()`, `pause()`, `reset()` вЂ” lifecycle
- `tick(elapsed)` вЂ” advance timer, yield phase transitions
- `describe()` вЂ” human-readable state string
- `from_dict(data)` / `to_dict()` вЂ” JSON serialization

---

### `Timer` & `TimerManager` (`core/timers.py`)

Generic countdown timer. Color-coded urgency, sound on fire, snooze.

**Timer attributes:** `name`, `description`, `target` (datetime), `sound`, `volume`, `color_mode`, `color`

**Methods:**
- `remaining()` вЂ” seconds until target
- `snooze(minutes)` вЂ” push target forward
- `display_color()` вЂ” urgency color (green/yellow/red)
- `collect_due(timers)` вЂ” return due timer list
- `next_due(timers)` вЂ” soonest timer
- `save_timers(data)` / `load_timers(data)` вЂ” serialization

---

### `DurationParser` (`core/duration.py`)

Human-readable duration parsing.

- `parse_duration(text)` вЂ” "2h 30m" в†’ seconds
- `format_remaining(seconds, short=False, minutes=False)` вЂ” "2h 30m" в†’ "2h" or "4d 11h 05m"
- `format_duration(seconds)` вЂ” full format string

---

### `HashtagIndex` (`core/hashtags.py`)

Cross-silo hashtag extraction + search.

- `extract_tags(text)` вЂ” return set of `#tag` strings
- `index_silo(cat, slot, text)` вЂ” tag в†’ silo index
- `search(tag)` вЂ” all silos containing tag across categories

---

### `DividerEngine` (`core/ctrlw.py`)

Ctrl+W / Alt+W template insertion.

- `insert_divider(editor, template, upward)` вЂ” insert horizontal rule, strip duplicate bullets on split
- `simulate(editor, upward)` вЂ” preview insert position

---

### `HeaderFormatter` (`core/header.py`)

Ctrl+E header insertion. Configurable: rule line, gap, bullet, alignment, timestamp stamp.

- `format_header(editor, config)` вЂ” format current line as header

---

### `SiloPresets` (`core/silo_presets.py`)

`.md` template loader for the "Fill from preset" feature (T-715).

- `presets_dir()` вЂ” resolved path to the shipped `presets/` data dir (exe or src)
- `label_for(filename)` вЂ” `03_Bullet list.md` в†’ `Bullet list` (leading `NN_` stripped, underscores to spaces)
- `load_presets(force=False)` вЂ” ordered `[(label, text)]` list; missing/unreadable folder yields `[]`

---

### `Watcher Engine Modules` (`core/watcher/`)

| Module | Role |
|---|---|
| `engine.py` | Finite state machine: DISARMED в†’ ARMED в†’ WATCHING в†’ SENDING |
| `cdp.py` | Chrome CDP attach + evaluate + read-back verification (Electron apps) |
| `win32.py` | Win32 window probe вЂ” foreground, caret, focus detection |
| `probes.py` | Multi-probe state combinators + combined matrix |
| `queue.py` | QueueItem, SendIntent, pinning, per-queue key, persistence |
| `sender.py` | CDP + Win32 keystroke injection with read-back verification |
| `skills.py` | Prompt skill wrappers вЂ” prefix/template transforms |
| `adapter.py` | Abstract probe adapter interface |
| `limit_scan.py` | Cross-agent limit scanner + auto-timer creation |

---

## Portable Backup (`utils/portable_backup.py`)

Immutable-snapshot Markdown export with coalescing (v0.8.43–v0.8.45 audit hardening).

- `capture_snapshot(data, profile_id=1)` — deep-copy a committed state dict for export
- `run_portable_backup(data, profile_id=1)` — synchronous or async (sink) capture; coalesces when a job is already active for the profile
- `backup_finished(profile_id=1)` — async worker completion hook; retires the active marker and dispatches the newest pending snapshot when one was requested (CORE-003)
- Coalescing rule (PERF-008 / CORE-002 / CORE-003): the immutable snapshot is taken at request time, not from the live dict, and a profile already mid-backup only records that a newer state is wanted — the newest state ships on the next eligible run.

## Loader Overflow Recovery (`core/state.py`)

- Snippet slots are pure array indexes (0..99). A row written by a buggy saver at slot ≥100 is migrated transactionally into the first free 0..99 slot, preserving its data without aliasing a distinct snippet (v0.8.46, T-1025).
- `DatabaseOverflowError` is raised only when the category is genuinely full (placement would require merging).
- Silo and archive tables keep the hard fail-closed behaviour — their slots carry identity (folders, queues, colours) that a blind move would orphan.

---

### `typecheck_ui_vocab` (`core/typecheck_ui_vocab.py`)

GENERATED module — Latin UI vocabulary extracted from all 33 i18n language packs. A `frozenset` of ~19k words used by `TypecheckEngine` to avoid false positives on app-translation strings. Regenerate with `python tools/gen_typecheck_ui_vocab.py`.

---

### `TypecheckEngine` (`core/typecheck.py`)

Dictionary-based, non-recursive typo checker for silo text (Qt-free for unit testing).

**Design:** single linear scan per pass — a word is visited exactly once. No re-entrancy with the editor's highlighting passes.

**Smart filtering:** skips code fences, inline code, URLs, e-mails, hashtags, @mentions, hex colours, and identifier-glued words (`foo.bar`, `snake_case`, `camelCase`, `#tag`). Acronyms (ALL-CAPS) and mixed-case identifiers never flagged. Contractions checked in contracted form with de-contracted fallback. Only flags words in scripts the dictionary covers (Latin/English ~10k words + UI vocabulary of every app language); stays silent for Cyrillic, CJK, etc.

**Key functions:**
- `check_text(text, user_words=None)` — single-pass scan, returns list of (word, suggestions) for flagged words
- `_script_of(ch)` — rough script family: 'latin' or block name
- `suggestions(word, pool)` — difflib closest matches from the whole dictionary pool

**Settings:** `typo_check_enabled` (live underline toggle), `typo_color` (underline color), `typo_user_words` (user-added dictionary words list).

---

### `ProjectSync` (`core/project_sync.py`)

Folder↔silo two-way sync, pure logic (Qt-free). UI wiring (QFileSystemWatcher, debounce timers) lives in `main.py`.

**Semantics:** a Sync-Project binds a project tab to a folder. Every text file that passes the include/exclude filters becomes a silo (slot 0..N-1 in file-name order; extra files become new silos up to the 100-silo cap). Two-way and live: app edits are pushed to the file (debounced, on every DB save), external file changes are applied back into the silo unless it holds unsaved app-side text (app side wins while being typed).

**Key constants:**
- `DEFAULT_INCLUDE` — tuple of text file extensions (.txt, .md, .py, .js, .json, ...)
- `DEFAULT_EXCLUDE` — tuple of junk/build/VCS directory names and binary patterns

**Key functions:**
- `scan_folder(path, include, exclude, recursive, max_kb)` — sorted list of relative file paths that pass filters
- `is_text_file(path, include)` — extension match against include list
- `should_exclude(path, exclude)` — fnmatch name or path-component substring match
- `read_file_safe(path, max_kb)` — size-capped, binary-sniffed safe read
- `write_file_atomic(path, content)` — temp sibling + atomic rename
- `detect_eol(raw_bytes)` — `\r\n` (Windows) or `\n` (Unix) preservation

**Settings:** `project_sync` / `project_sync_all` (per-profile/cross-profile bindings), `project_sync_map` / `project_sync_map_all` (silo↔file slot mapping), `sync_include` / `sync_exclude` / `sync_live_watch` / `sync_max_kb` / `sync_recursive`.

---

### `TypoCheckDialog` (`ui/typo_check_dialog.py`)

Whole-project typecheck report dialog. Right-click project tab → "Check Typos in this project…". Scans every silo with the same dictionary the live underline uses, groups unknown words per silo, and lets the user add words to the dictionary from the report.

---

## UI Components (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow. Mixin composition (declaration order):
1. FormattingMixin вЂ” markdown formatting shortcuts
2. HotkeyMixin вЂ” hotkey binding interface
3. ScalingMixin вЂ” DPI/font scaling
4. SearchMixin вЂ” search bar over silos
5. SendSelectionMixin вЂ” send text via watcher
6. SnippetOpsMixin вЂ” silo ops (trash, duplicate, reorder)
7. ThemeMixin вЂ” app stylesheet, vintage presets
8. TrayMixin вЂ” system tray icon + menu
9. WatcherMixin вЂ” watcher engine integration
10. WindowMixin вЂ” frameless window + snapping

**Key properties:** `_font_size`, `_font_family`, `_ui_scale`, `_button_scale`, `_sidebar_right`, `_always_on_top`, `_normal_window`

**Key methods:**
- `init_ui()` вЂ” build window, header toolbar, splitter, editor, sidebar, status bar
- `setup_single_instance_server()` вЂ” IPC init
- `register_all_hotkeys()` вЂ” bind pynput + PyQt shortcuts
- `apply_font()` / `apply_theme()` вЂ” cascade font/theme changes
- `place_window()` вЂ” restore saved geometry or apply default snap
- `_switch_to_slot(slot, initial)` вЂ” load silo into editor, save cursor state
- `capture_silo_state()` / `restore_silo_state()` вЂ” per-silo cursor/scroll/fold/heat persistence

---

### `VaultTextEdit` (`ui/editor.py`)

Extended QPlainTextEdit. Markdown editing canvas.

**Features:**
- MarkdownHighlighter вЂ” live syntax coloring
- LineNumberArea вЂ” gutter: line numbers + fold arrows (в–ѕ) + margin marks
- `fold_header(block_num)` / `unfold_header(block_num)` вЂ” section collapse
- `queue_current_line()` вЂ” anchor watcher item to block
- `set_queue_anchor(block, id)` вЂ” queue line anchoring
- `collect_view_metadata()` — consolidated marks, heat, and folds capture
- `block_for_queue_item(id)` / `blocks_for_queue_items(ids)` вЂ” find block by queue anchor
- `document_word_count()` вЂ” O(1) cached word count
- `toggle_checkbox()` вЂ” `- [ ]` в†” `- [x]`
- `toggle_hide_markup(checked)` вЂ” conceal ** * ~~ ` markers (T-603)
- Image pills вЂ” `![alt](url)` в†’ 150px clickable button

---

### `SnippetPanel` (ui/snippet_panel.py)

Sidebar silo list + F1-F10 buttons.

**Classes:**
- `SnippetWidget` вЂ” sidebar panel: category tabs + silo list
- `DraggableSiloButton` вЂ” individual silo button (pin, tick, color, file icon, drag)
- `WheelPager` вЂ” scroll-synced pager for silo list
- `DropVerticalWidget` вЂ” drop zone for hierarchy nesting

**Features:**
- Up to 100 silos per tab
- Pins, ticks, recency heatmap, hierarchy (drag to nest)
- Sidebar gaps вЂ” user-defined spacer bars (Ctrl+drag to move)
- Multi-select вЂ” Shift=range, Ctrl=toggle, batch delete/save/clear
- Number-box mode вЂ” project switcher as numbered button row (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

Per-silo file drawer. Opens below editor.

- `load_files(cat, slot)` вЂ” read folder contents
- `add_files(paths)` вЂ” copy external files into silo folder
- `apply_template(name)` вЂ” create folder structure (IN/OUT/DOCS/Assets/Drafts)
- Image preview, link mode, drag-and-drop
- Silo backup вЂ” Ctrl+click рџ“Ѓ exports silo text

---

### `SiloTable` (`ui/silo_table.py`)

Pure-text markdown table builder. No Qt tables вЂ” works on plain markdown.

- Tab/Shift+Tab: walk cells; Tab off last в†’ new row
- Enter: new row (not split)
- Cell editing via inline markdown

---

### `SiloKanban` (`ui/silo_kanban.py`)

Pure-text markdown kanban board. Cards are markdown list items.

- Alt+в†‘/в†“: move card up/down
- Alt+в†ђ/в†’: move card to adjacent column
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

When header < 700px: hidden buttons collected in В» popup. Every formatting, navigation, tool still reachable.

### `EditGuard` (`ui/edit_guard.py`)

Context manager: `with edit_block(widget): ...` wraps begin/endEditBlock. Prevents Qt freeze from unterminated editing operations.
