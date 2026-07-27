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

Двигатель работает как конечный автомат с четырьмя явными состояниями:

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

CDP (`cdp.py`) обеспечивает прямую и надежную автоматизацию путем подключения к порту удаленной отладки Chromium (`--remote-debugging-port=<port>`).

### CDP Operations & Verification
* **Discovery (`discover()`)**: Queries `http://127.0.0.1:<port>/json/list` to retrieve active page targets.
* **WebSocket JSON-RPC**: Establishes a WebSocket transport to send `Runtime.evaluate`, `Input.dispatchKeyEvent`, or `DOM` manipulation commands.
* **Read-Back Verification**: To prevent silent input failure, `cdp.py` inserts text into the prompt field, reads back the field value via DOM query, and only sends the Submit command (`Enter`) once text presence is verified.
* **Non-Blocking Timeouts**: All socket operations use short default timeouts (3.0 seconds) to ensure Qt UI responsiveness.

---

## 3. Win32 Hooks & Target Probes (`win32.py`, `probes.py`)

Для целевых приложений, отличных от Electronic, FastPrompter использует зонды ОС Win32:
* **Проверка окна переднего плана**: проверяет `GetForegroundWindow()` и сверяет заголовок окна с настроенными целевыми шаблонами регулярных выражений.
* **Caret & Focus Probe**: отслеживает расположение курсора и состояние фокуса, чтобы гарантировать, что быстрое внедрение происходит только тогда, когда целевые поля ввода активны.
* **Комбинированная матрица пробников (`combine()`)**: объединяет состояния нескольких пробников (`is_target_active`, `is_target_busy`, `is_blocked`) в один детерминированный логический результат.

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

Чтобы предотвратить неконтролируемые циклы запросов или спам-рассылку целевых API-интерфейсов LLM, Watcher Engine применяет строгие параметры ограничения скорости:

| Параметр | Значение по умолчанию | Цель |
|---|---|---|
| `settle_ms` | `2500 мс` | Продолжительность тишины, необходимая после того, как цель становится бездействующей, прежде чем отправлять следующий запрос. |
| `min_gap_ms` | `4000 мс` | Принудительная минимальная задержка между последовательными отправками. |
| `max_sends` | `25 предметов` | Максимальное количество запросов, отправленных за один сеанс постановки на охрану перед автоматическим снятием с охраны. |
| `max_failures` | `3 неудачи` | Порог последовательного отказа перед снятием двигателя с охраны по причине ошибки. |
| `паника()` | Аварийная остановка | Мгновенно выключает двигатель и отменяет все ожидающие/находящиеся в полете намерения отправки. |

---
*FastPrompter Wiki — создан с использованием [Протокол SAIPEN] (Протокол SAIPEN) | [Репозиторий GitHub](https://github.com/vaacterro/FastPrompter)*