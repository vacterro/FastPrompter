# Plan: Prompt Queue Watcher for FastPrompter

**State:** ACTIVE — Phase 1 done, Phase 2 ready to implement.
**Agent-read:** yes — any AI can pick up and continue from this file.
**Scope:** Integration into FastPrompter (PyQt6 desktop app).
**Goal:** Queue prompts from editor lines, auto-send next prompt when agent finishes answering.

---

## Phase Status Summary

| Phase | Status | Files |
|-------|--------|-------|
| **1. Core Queue** | ✅ Done | `core/prompt_queue.py`, `watcher/`, `ui/prompt_queue_panel.py`, `ui/prompt_queue_indicator.py`, wiring in `main.py` |
| **2. Hotkey + Capture Polish** | 🔲 Ready | Settings dialog, multi-line, visual feedback, persistence, clear confirm |
| **3. Watcher Engine** | 🔲 Planned | `watcher/engine.py`, QProcess, completion detection, auto-send |
| **4. Agent Adapters** | 🔲 Planned | Registry + claude, freebuff-cli, opencode, codex, generic adapters |
| **5. Polish** | 🔲 Planned | Agent log panel, drag-reorder, resume across restart, edge cases |

---

## 1. Core Concept

```
[User presses Ctrl+Shift+X] → capture current editor line/selection text
                                ↓
                           [FIFO Queue: prompt_1, prompt_2, ...]
                                ↓
                        [WatcherEngine (QProcess)] monitors agent CLI
                                ↓
               Agent finished answering? → pop next prompt → send to agent
```

The watcher bridges FastPrompter (the editor UI) with external chat agent CLIs (claude, freebuff CLI, opencode, antigravity, codex, etc).

---

## 2. What Phase 1 Implemented

### 2.1 Files created

| File | What it does |
|------|-------------|
| `src/fastprompter/core/prompt_queue.py` | `PromptEntry` dataclass (text, silo_index, line_number, status, id, created_at, retries) + `QueueManager` (FIFO deque, JSON persistence via `save_to_data()`/`_load_from_data()`, change callback, remove/clear/peek) |
| `src/fastprompter/watcher/__init__.py` | Package marker |
| `src/fastprompter/watcher/adapters/__init__.py` | Package marker |
| `src/fastprompter/watcher/adapters/base.py` | `AgentAdapter` ABC: `launch()`, `send_prompt()`, `detect_completion()`, `abort()`. Static helpers: `_write_stdin()`, `_prompt_detected()`, `_terminate()` |
| `src/fastprompter/ui/prompt_queue_panel.py` | Sidebar widget: `QListWidget` of queued entries, start/stop button (stub), clear button, close button, count label, empty state |
| `src/fastprompter/ui/prompt_queue_indicator.py` | Header `QPushButton` showing `📋N` — colour-coded (grey idle, gold queued, green running, red error). Click toggles panel |

### 2.2 Wiring in main.py

- **Imports** added (lines 102-104)
- **`self.queue_manager = QueueManager(self.data)`** — init after state, loads persisted queue from data dict
- **`self.queue_indicator`** — created and added to header layout between lbl_timer and btn_pin_top (line 2115-2117)
- **`self.queue_panel`** — created and added to sidebar after silos_section (line 3090-3091, added to layout at 3209)
- **`Ctrl+Shift+X` hotkey** — registered via `add_fixed()` in `setup_global_shortcuts()` (line 6682)
- **`_queue_current_line()`** method — captures current line text (or selection if text selected), creates `PromptEntry`, appends to queue, auto-shows panel on first entry, plays tick sound (line 5245)
- **Auto-save hook** — queue state saved to data dict before general DB save in `_auto_save_tick()` (line 1699)

### 2.3 Verified

- Basic operations: append, pop, peek, clear, remove by id — all pass
- Persistence round-trip: save_to_data → _load_from_data — passes
- Code review completed — minor flags noted for Phase 2

### 2.4 Phase 1 gaps (to fix in Phase 2)

1. `PromptEntry` imported inside method body → should be module-level import
2. Panel visibility not persisted across restarts
3. Clear queue lacks confirmation dialog
4. Watcher start/stop button is a dead stub (toggles flag only)
5. No threading lock in QueueManager (safe for Qt main thread but not worker threads)
6. No dedicated test file (`tests/test_prompt_queue.py`)

---

## 3. Phase 2: Hotkey + Capture Polish

**Goal:** Refine capture UX, integrate with settings, handle edge cases.

### 3.1 Settings dialog

Add to `HotkeySettingsDialog` in `src/fastprompter/ui/settings.py`:

| Key | Default | Widget | Description |
|-----|---------|--------|-------------|
| `queue_hotkey` | `Ctrl+Shift+X` | QLineEdit | Keybind to queue current editor line |
| `queue_confirm_clear` | `True` | QCheckBox | Confirm before clearing queue |
| `queue_auto_start` | `True` | QCheckBox | Start watcher when first prompt queued |
| `queue_capture_selection` | `True` | QCheckBox | Queue selection instead of single line |

Update `_apply_tooltips()` in `hotkey_mixin.py` to show queue hotkey in shortcuts list.

### 3.2 Multi-line selection

In `_queue_current_line()`:
- If `cursor.hasSelection()` AND `queue_capture_selection == True` → use selected text (preserve newlines)
- Else → use current block text
- Add optional `is_selection: bool` field to `PromptEntry`

### 3.3 Visual feedback

- **Line flash**: brief yellow/gold background on captured line (500ms), clear via `QTimer.singleShot`
- **Indicator pulse**: temporarily force indicator to bright gold, fade after 1s
- **Sound**: already wired (`play_tick_sound()`)

### 3.4 Panel persistence

Add `panel_visible` to `prompt_queue_v1` JSON blob. On boot, if `panel_visible == True`, show panel. Connect panel's `visibilityChanged` signal to auto-save.

### 3.5 Clear confirmation

```python
def _clear_queue(self):
    if self.main_win.data.get("queue_confirm_clear", "True") == "True":
        reply = QMessageBox.question(...)
        if reply != QMessageBox.Yes: return
    self._qm.clear()
```

### 3.6 Keyboard navigation in panel

- `Up/Down` → move selection
- `Delete` → remove selected entry
- `Space` → toggle watcher start/stop

### 3.7 Files to modify

| File | Change |
|------|--------|
| `ui/settings.py` | Add queue hotkey field + option toggles |
| `core/hotkey_mixin.py` | Add queue hotkey to tooltip display |
| `main.py` | Multi-line logic, line flash, panel visibility persistence |
| `core/prompt_queue.py` | Add `is_selection` field to PromptEntry |
| `ui/prompt_queue_panel.py` | Clear confirmation, keyboard nav |
| `ui/prompt_queue_indicator.py` | Pulse animation on capture |
| `tests/test_prompt_queue.py` | New — test prompt queue operations |

---

## 4. Phase 3: Watcher Engine

**Goal:** Launch agent CLI process, feed prompts, detect completion, auto-send next.

### 4.1 WatcherEngine class

**File:** `src/fastprompter/watcher/engine.py`

```python
class WatcherEngine(QObject):
    prompt_sent = Signal(str)           # entry id
    prompt_completed = Signal(str)      # entry id
    prompt_failed = Signal(str, str)    # entry id, reason
    agent_ready = Signal()              # waiting for next prompt
    agent_crashed = Signal(str)         # error message

    def __init__(self, queue_manager: QueueManager, adapter: AgentAdapter): ...
    def start(self) -> bool: ...
    def stop(self, grace_ms=2000): ...
    def send_next(self): ...
    def abort_current(self): ...
```

### 4.2 State machine

```
IDLE → LAUNCHING → READY
                      │
            ┌─────────┤
            ▼         ▼
        SENDING    [queue empty → READY]
            │
            ▼
        WAITING (read stdout, detect completion)
            │               │
            ▼               ▼
        COMPLETED        TIMEOUT
            │               │
            ▼               ▼
        [send next]     [mark failed, send next]
```

### 4.3 Completion detection algorithm

```python
def _on_stdout_ready(self):
    data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
    self._stdout_buffer += data

    if self._adapter.detect_completion(self._process, self._stdout_buffer):
        self._on_prompt_completed()
        return

    self._silence_timer.start()  # fallback: no new data for N seconds → done
```

### 4.4 Auto-send pipeline

```
QueueManager.append(entry)
    → if engine.running and engine.state == READY:
        engine.send_next()

Prompt completed → engine.send_next()  # if queue not empty
Queue emptied → engine.state = READY   # wait for more
```

### 4.5 Error recovery

| Scenario | Action |
|----------|--------|
| Process crashes | Mark current failed, auto-restart, retry up to N times |
| Prompt times out | Mark failed, send next |
| Agent hangs (no stdout for 2x timeout) | Kill + restart process |
| User closes app mid-queue | Persist queue, prompt "resume?" on next launch |

### 4.6 Wiring to UI

```python
def _init_watcher(self):
    adapter = get_adapter(self.queue_manager.agent_type)
    self._watcher = WatcherEngine(self.queue_manager, adapter)
    self._watcher.prompt_sent.connect(...)
    self._watcher.prompt_completed.connect(...)
    self._watcher.prompt_failed.connect(...)
    self._watcher.agent_crashed.connect(...)
```

Panel start/stop button → calls `self.main_win._watcher.start()/stop()`.

### 4.7 Files

| File | Change |
|------|--------|
| `watcher/engine.py` | New — WatcherEngine (QObject with QProcess) |
| `watcher/adapters/registry.py` | New — adapter lookup by name |
| `main.py` | Init watcher, wire signals |
| `ui/prompt_queue_panel.py` | Wire start/stop to engine |

---

## 5. Phase 4: Agent Adapters

**Goal:** Concrete adapters for 5 agent CLIs, plus registry.

### 5.1 Registry

**File:** `watcher/adapters/registry.py`

```python
_ADAPTERS: dict[str, type[AgentAdapter]] = {}
def register(key: str, cls): ...
def get_adapter(key: str) -> AgentAdapter: ...
def available_adapters() -> list[tuple[str, str]]: ...
```

Each adapter file calls `register("claude", ClaudeAdapter)` at module level.

### 5.2 Adapters to create

| Adapter | File | Launch command | Completion pattern |
|---------|------|---------------|-------------------|
| Claude Code | `claude.py` | `claude` | `^[$>]\s*$` |
| Freebuff CLI | `freebuff_cli.py` | `freebuff --pipe` | `^>\s*$` |
| OpenCode | `opencode.py` | `opencode --headless` | `^❯\s*$` |
| Codex CLI | `codex.py` | `codex --non-interactive` | JSON `"done": true` |
| Generic | `generic.py` | user-configured | user regex |

### 5.3 Each adapter implements

```python
class XAdapter(AgentAdapter):
    label = "X"
    key = "x"

    def launch(self) -> QProcess: ...
    def send_prompt(self, process, text): ...
    def detect_completion(self, process, buffer) -> bool: ...
    def abort(self, process): ...
```

### 5.4 Files

| File | Change |
|------|--------|
| `watcher/adapters/registry.py` | New |
| `watcher/adapters/claude.py` | New |
| `watcher/adapters/freebuff_cli.py` | New |
| `watcher/adapters/opencode.py` | New |
| `watcher/adapters/codex.py` | New |
| `watcher/adapters/generic.py` | New |
| `watcher/adapters/__init__.py` | Import adapters to trigger registration |
| `ui/prompt_queue_panel.py` | Adapter selection dropdown |
| `tests/test_adapters.py` | New |

---

## 6. Phase 5: Polish

**Goal:** Production-ready UX.

### 6.1 Agent output log panel

**File:** `ui/prompt_queue_log.py` — read-only `QPlainTextEdit` with:
- Auto-scroll toggle
- Colour coding (prompts gold, responses silver, tool calls grey)
- Clear button
- Last N lines in memory (configurable, default 500)
- Context menu: "Save Log As…" → `.log` file

### 6.2 Drag-reorder queue

- `QListWidget.setDragDropMode(InternalMove)`
- `QueueManager.reorder(id_order: list[str])` method

### 6.3 Resume across restart

- On boot: if queue has entries, show tray notification: "N prompts still queued. Open panel to resume."
- On closeEvent: if queue non-empty, ask "Quit anyway?"

### 6.4 Edge cases

- **Rapid capture debounce** (500ms) — prevent duplicates
- **Process crash mid-response** — auto-restart, retry
- **Signal safety** — `threading.Lock` around queue mutation
- **closeEvent** for running watcher

### 6.5 Files

| File | Change |
|------|--------|
| `ui/prompt_queue_log.py` | New |
| `ui/prompt_queue_panel.py` | Drag-reorder |
| `core/prompt_queue.py` | `reorder()` method, threading lock |
| `main.py` | closeEvent handler, resume notification, debounce |
| `ui/prompt_queue_indicator.py` | Right-click menu → "Show Agent Log" |

---

## 7. Persistent Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Process type | **QProcess** | Qt event-loop native, no threading complexity |
| Agent session | **Single persistent process** | Agents maintain conversation context |
| Completion detection | **Adapter-specific prompt pattern first, silence timeout fallback** | Most reliable across agents |
| Output destination | **Optional log panel** | User decides what to keep; future: auto-insert |
| Persistence | **JSON blob in settings data dict** | No new SQLite table, piggybacks on existing save mechanism |
| Hotkey | **QShortcut (app-local), default Ctrl+Shift+X** | Avoids Win32 global hotkey conflicts |

---

## 8. File Map (complete)

```
src/fastprompter/
├── core/
│   └── prompt_queue.py             # QueueManager, PromptEntry model
├── watcher/
│   ├── __init__.py
│   ├── engine.py                   # WatcherEngine (QObject + QProcess)
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── registry.py             # adapter lookup by name
│   │   ├── base.py                 # AgentAdapter ABC
│   │   ├── claude.py
│   │   ├── freebuff_cli.py
│   │   ├── opencode.py
│   │   ├── codex.py
│   │   └── generic.py
├── ui/
│   ├── prompt_queue_panel.py       # Queue list widget (sidebar)
│   ├── prompt_queue_indicator.py   # Header badge
│   └── prompt_queue_log.py         # Agent output log panel
```

---

## 9. Risks

| Risk | Mitigation |
|------|-----------|
| Agent CLI uses ncurses/TUI | Prefer pipe-compatible modes; use `script`/`pty` wrappers |
| Agent hangs mid-response | Configurable timeout → kill + restart |
| Agent crashes | Auto-restart with retry counter |
| Alt+C conflicts with OS shortcuts | Default `Ctrl+Shift+X`, fully rebindable |
| Agent API changes | Adapter pattern isolates changes to one file |

---

## 10. Agent Implementation Notes

If you are an AI agent reading this file to implement the feature:

1. **Start with Phase 2** — it fixes Phase 1 gaps and adds settings. All files already exist except `tests/test_prompt_queue.py`.
2. **Read `main.py`** for wiring locations (search for `queue_manager`, `queue_indicator`, `queue_panel`)
3. **Read `ui/settings.py`** for the HotkeySettingsDialog pattern (add queue hotkey there)
4. **Phase 3 is the most complex** — the WatcherEngine needs careful QProcess lifecycle management
5. **Phase 4 adapters are mechanical** — one file per adapter, all follow the same pattern
6. **Phase 5 is optional UX polish** — do it last
