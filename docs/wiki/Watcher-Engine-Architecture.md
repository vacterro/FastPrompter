# Watcher Engine Architecture & CDP Automation Guide

## Overview
The **Watcher Engine** (`src/fastprompter/core/watcher/`) is FastPrompter's automated prompt drainage and target interaction subsystem. It allows FastPrompter to safely queue prompts, monitor target application states (such as Electron-based LLM clients, Web UI browsers, or IDEs), and automatically send prompts when the target becomes idle.

---

## High-Level Watcher Architecture

```
+-----------------------------------------------------------------------------------+
|                                 Watcher Engine                                    |
|                                 (`engine.py`)                                     |
|  +--------------------+    +--------------------+    +-------------------------+  |
|  |   State Machine    | -> |   Probes & Hooks   | -> |     SendIntent Generator |  |
|  | DISARMED->ARMED->  |    | (Win32 & CDP State)|    |   (Item + Skill Format) |  |
|  | WATCHING->SENDING  |    +--------------------+    +-------------------------+  |
|  +--------------------+                                           |               |
+-------------------------------------------------------------------|---------------|
                                                                    v
+-----------------------------------------------------------------------------------+
|                                  Sender & Queue                                   |
|  +--------------------------------+       +------------------------------------+  |
|  |     Queue (`queue.py`)         |       |      Sender (`sender.py`)          |  |
|  | - Pinned queue_key per target  |       | - Chrome DevTools Protocol (CDP)   |  |
|  | - FIFO Item backlog            |       | - Win32 Keystroke Injection        |  |
|  +--------------------------------+       +------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 1. Engine State Machine (`engine.py`)

The Engine operates as a finite state machine with four explicit states:

```
[ DISARMED ] <--- (error / panic / max sends reached)
     |
     | arm(target, queue_key)
     v
  [ ARMED ] ----> (agent seen busy) ----> [ WATCHING ]
     ^                                          |
     |                                          | (agent idle + settle_ms elapsed)
     +------------- (send completed) <---- [ SENDING ]
```

### State Definitions
1. **DISARMED**: Engine is inactive. No probes are polled and no queue items are processed.
2. **ARMED**: Engine is bound to a specific target window/socket and a pinned `queue_key`. Waiting to detect initial target activity.
3. **WATCHING**: Target application has been observed in a busy state (e.g. LLM generating response). Watcher is waiting for the target to become idle and settle.
4. **SENDING**: A `SendIntent` has been dispatched to `Sender`. Watcher is awaiting confirmation of text injection and submission.

---

## 2. Chrome DevTools Protocol (CDP) Attachment (`cdp.py`)

### Why CDP Instead of Win32 Messages?
Electron-based desktop applications (VS Code, Claude Desktop, ChatGPT App, Obsidian) process input through Chromium's internal IPC rather than standard Windows OS message queues (`WM_CHAR`, `PostMessageW`). Posting Win32 messages to Electron windows often results in dropped characters or ignored input.

CDP (`cdp.py`) provides direct, reliable automation by connecting to Chromium's remote debugging port (`--remote-debugging-port=<port>`).

### CDP Operations & Verification
* **Discovery (`discover()`)**: Queries `http://127.0.0.1:<port>/json/list` to retrieve active page targets.
* **WebSocket JSON-RPC**: Establishes a WebSocket transport to send `Runtime.evaluate`, `Input.dispatchKeyEvent`, or `DOM` manipulation commands.
* **Read-Back Verification**: To prevent silent input failure, `cdp.py` inserts text into the prompt field, reads back the field value via DOM query, and only sends the Submit command (`Enter`) once text presence is verified.
* **Non-Blocking Timeouts**: All socket operations use short default timeouts (3.0 seconds) to ensure Qt UI responsiveness.

---

## 3. Win32 Hooks & Target Probes (`win32.py`, `probes.py`)

For non-Electron target applications, FastPrompter uses Win32 OS probes:
* **Foreground Window Probe**: Checks `GetForegroundWindow()` and verifies window title against configured target regex patterns.
* **Caret & Focus Probe**: Monitors caret location and focus state to ensure prompt injection occurs only when target input fields are active.
* **Combined Probe Matrix (`combine()`)**: Aggregates multi-probe states (`is_target_active`, `is_target_busy`, `is_blocked`) into a single deterministic boolean result.

---

## 4. Queue Management & Item Lifecycle (`queue.py`)

### Queue Pinning
When the engine is armed (`arm(target, queue_key)`), the `queue_key` is pinned. This ensures that even if the user switches active project tabs or silos in FastPrompter, the watcher continues draining the exact queue for which it was armed.

### Queue Item Lifecycle
1. **Pending**: Item added to queue backlog.
2. **In-Flight (`SendIntent`)**: Item encapsulated into `SendIntent(item_id, text, queue_key, skill)`.
3. **Sent / Completed**: Confirmed by sender, removed from queue.
4. **Failed / Retried**: Increments `consecutive_failures`. Retried up to `max_failures` (default: 3).

---

## 5. Safety Guards & Rate Limiting

To prevent runaway prompt loops or spamming target LLM APIs, the Watcher Engine enforces strict rate limiting parameters:

| Parameter | Default Value | Purpose |
|---|---|---|
| `settle_ms` | `2500 ms` | Quiet duration required after target becomes idle before sending next prompt. |
| `min_gap_ms` | `4000 ms` | Enforced minimum delay between consecutive sends. |
| `max_sends` | `25 items` | Maximum number of prompts sent in a single armed session before auto-disarming. |
| `max_failures` | `3 failures` | Consecutive failure threshold before disarming engine with error reason. |
| `panic()` | Emergency Stop | Instantly disarms engine and cancels all pending/in-flight send intents. |

---
*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
