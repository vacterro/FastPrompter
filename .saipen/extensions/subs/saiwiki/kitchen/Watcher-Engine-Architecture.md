# Watcher Engine Architecture

## Overview

Prompt drainage + target automation subsystem. Queues prompts, monitors target app state (Electron/web/any Win32 window), auto-sends when target idle.

---

## High-Level Architecture

```
+------------------------------------------------------------------+
|                        Watcher Engine (engine.py)                  |
|  +------------------+    +------------------+   +--------------+  |
|  | State Machine    | -> | Probes & Hooks   | ->| SendIntent   |  |
|  | DISARMED→ARMED→  |    | (Win32 + CDP)    |   | Generator    |  |
|  | WATCHING→SENDING |    +------------------+   +--------------+  |
|  +------------------+                                          |
+------------------------------------------------------------------+
                              v
+------------------------------------------------------------------+
|  Queue (queue.py)           |    Sender (sender.py)              |
|  - Per-target queue_key     |    - CDP Runtime.evaluate          |
|  - FIFO item backlog        |    - Win32 key injection           |
|  - Pinned queue_key on arm  |    - Read-back verify              |
+------------------------------------------------------------------+
```

---

## 1. State Machine (`engine.py`)

```
[DISARMED] ← (error/panic/max_sends)
    |
    | arm(target, queue_key)
    v
[ARMED] —→ (agent seen busy) —→ [WATCHING]
    ^                               |
    |     (send completed)          | (agent idle + settle_ms)
    +———————— <— [SENDING] ————————+
```

### States
1. **DISARMED** — inactive, no probes polling, no items processing
2. **ARMED** — bound to target window + queue_key. Waiting for target activity.
3. **WATCHING** — target observed busy (LLM generating). Waiting for idle + settle.
4. **SENDING** — SendIntent dispatched. Waiting for injection confirmation.

---

## 2. Chrome CDP (`cdp.py`)

Why CDP: Electron apps (VS Code, Claude Desktop, ChatGPT, Obsidian) don't process Win32 messages. Chromium's IPC ignores `PostMessageW` — characters drop silently.

### Operations
- `discover()` — query `http://127.0.0.1:<port>/json/list` for page targets
- WebSocket JSON-RPC connection per page
- `Runtime.evaluate` + `Input.dispatchKeyEvent` for text injection
- **Read-back verify** — insert text, read field value via DOM query, only Submit on match
- Non-blocking timeouts (3s default)

---

## 3. Win32 Probes (`win32.py`, `probes.py`)

For non-Electron target apps.

- `GetForegroundWindow()` + title regex match → target detection
- Caret + focus monitoring → injection only when input field active
- `combine()` — aggregate multi-probe states into single bool (is_target_active, is_target_busy, is_blocked)

---

## 4. Queue Model (`queue.py`)

### QueueItem
- `id` — UUID
- `text` — prompt text
- `skill` — wrapper skill name
- `line` — source line number (for live-text tracking)

### SendIntent
- `item_id`, `text`, `queue_key`, `skill` — encapsulated for sender

### Lifecycle
1. **Pending** — in backlog
2. **In-Flight** — SendIntent dispatched to sender
3. **Sent** — confirmed by sender, removed from queue
4. **Failed** — increments consecutive_failures, retry up to max_failures (3)

### Queue Pinning
On `arm(target, queue_key)`, key is pinned. Switches project/silo mid-session → watcher still drains correct queue.

---

## 5. Safety Guards

| Parameter | Default | Purpose |
|---|---|---|
| `settle_ms` | 2500 | Quiet time after target idle before sending |
| `min_gap_ms` | 4000 | Min delay between consecutive sends |
| `max_sends` | 25 | Max prompts per armed session (auto-disarm) |
| `max_failures` | 3 | Consecutive failures → disarm with error |
| `panic()` | — | Emergency stop: disarm + cancel all in-flight |

### Safety Guards — v0.8.25 notes (T-757, T-756)

- `[limits]` in `adapters.toml` — `min_gap_ms`, `max_sends`, `dry_run_new` —
  are now **applied to the engine at arm** (clamped at parse), not just stored.
  The dead `confirm_first`/`allow_focus_steal`/`restore_clipboard_ms` keys are
  gone.
- `blocker_pattern` (a permission-prompt guard) executes **only on the CDP
  transport**, which is the one that can read the target's visible text. A
  blocker declared on any other transport is flagged **inactive** in the
  dialog rather than silently pretending to work.
- A CDP adapter arms **without a window handle** — the Win32 window selector
  is disabled for it.
- Queue state machine: a queued item is anchored to its source **block**, and
  its line number is re-stamped from that anchor when the silo is left or the
  queue saved, so an inactive silo never fires at a stale line. A **detached**
  item (source line gone) revives to pending the moment the source returns,
  without opening the dialog. Moving an item to another silo's queue turns it
  into a text snapshot (line 0), so the destination never binds it to its own
  same-numbered line.

---

## 6. Skill System (`skills.py`)

Prompt wrappers applied before dispatch.

```python
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review:\n\n{text}",
}
```

Variables: `{text}`, `{timestamp}`, `{project}`.

---

## 7. Skills & Watcher Dialog

- `Alt+C` — queue current editor line (block-anchored)
- `Alt+Shift+C` — Queue Master (all silos overview)
- Set default skill in Settings
- Watcher dialog: arm/disarm, pick target, configure probes
