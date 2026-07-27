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

Mootor töötab lõpliku olekuga masinana, millel on neli selget olekut:

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

CDP (`cdp.py`) pakub otsest ja usaldusväärset automatiseerimist, luues ühenduse Chromiumi kaugsilumispordiga (`--remote-debugging-port=<port>`).

### CDP Operations & Verification
* **Discovery (`discover()`)**: Queries `http://127.0.0.1:<port>/json/list` to retrieve active page targets.
* **WebSocket JSON-RPC**: Establishes a WebSocket transport to send `Runtime.evaluate`, `Input.dispatchKeyEvent`, or `DOM` manipulation commands.
* **Read-Back Verification**: To prevent silent input failure, `cdp.py` inserts text into the prompt field, reads back the field value via DOM query, and only sends the Submit command (`Enter`) once text presence is verified.
* **Non-Blocking Timeouts**: All socket operations use short default timeouts (3.0 seconds) to ensure Qt UI responsiveness.

---

## 3. Win32 Hooks & Target Probes (`win32.py`, `probes.py`)

Mitte-elektroni sihtrakenduste jaoks kasutab FastPrompter Win32 OS-i sonde:
* **Eesplaan Window Probe**: kontrollib 'GetForegroundWindow()' ja kontrollib akna pealkirja konfigureeritud sihtmärgi regex-mustrite suhtes.
* **Caret & Focus Probe**: jälgib tähise asukohta ja fookuse olekut, et tagada kiire süstimine ainult siis, kui sihtmärgi sisendväljad on aktiivsed.
* **Kombineeritud proovimaatriks (combine())**: koondab mitme sondi olekud ("on_target_active", "on_target_busy", "on_blocked") üheks deterministlikuks tõeväärtuslikuks tulemuseks.

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

Vältimaks jooksvaid viipasilmuseid või rämpsposti saatmist siht-LLM API-de kaudu, rakendab Watcher Engine ranged kiirust piiravad parameetrid.

| Parameeter | Vaikeväärtus | Eesmärk |
|---|---|---|
| `settle_ms` | "2500 ms" | Vaikne kestus on vajalik pärast seda, kui sihtmärk muutub enne järgmise viipa saatmist jõudeolekuks. |
| "min_gap_ms" | "4000 ms" | Sunnitud minimaalne viivitus järjestikuste saatmiste vahel. |
| "max_sends" | "25 kirjet" | Maksimaalne viipade arv, mis saadetakse ühe valveseansi jooksul enne automaatset desarmeerimist. |
| "max_failures" | `3 tõrget` | Järjestikuse rikke lävi enne mootori valve mahavõtmist vea põhjusega. |
| `paanika()` | Hädapeatus | Demonteerib mootori koheselt ja tühistab kõik ootel/lennu ajal saatmise kavatsused. |

---
*FastPrompter Wiki – ehitatud [SAIPEN-protokolli] (SAIPEN-protokolli) abil | [GitHubi hoidla](https://github.com/vacterro/FastPrompter)*