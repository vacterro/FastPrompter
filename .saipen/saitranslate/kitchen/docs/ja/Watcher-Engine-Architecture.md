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

エンジンは、次の 4 つの明示的な状態を持つ有限状態マシンとして動作します。

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

CDP (`cdp.py`) は、Chromium のリモート デバッグ ポート (`--remote-debugging-port=<port>`) に接続することで、直接的で信頼性の高い自動化を提供します。

### CDP Operations & Verification
* **Discovery (`discover()`)**: Queries `http://127.0.0.1:<port>/json/list` to retrieve active page targets.
* **WebSocket JSON-RPC**: Establishes a WebSocket transport to send `Runtime.evaluate`, `Input.dispatchKeyEvent`, or `DOM` manipulation commands.
* **Read-Back Verification**: To prevent silent input failure, `cdp.py` inserts text into the prompt field, reads back the field value via DOM query, and only sends the Submit command (`Enter`) once text presence is verified.
* **Non-Blocking Timeouts**: All socket operations use short default timeouts (3.0 seconds) to ensure Qt UI responsiveness.

---

## 3. Win32 Hooks & Target Probes (`win32.py`, `probes.py`)

Electron 以外のターゲット アプリケーションの場合、FastPrompter は Win32 OS プローブを使用します。
* **フォアグラウンド ウィンドウ プローブ**: `GetForegroundWindow()` をチェックし、設定されたターゲット正規表現パターンに対してウィンドウ タイトルを検証します。
* **キャレットとフォーカス プローブ**: キャレットの位置とフォーカスの状態を監視して、ターゲットの入力フィールドがアクティブな場合にのみプロンプト挿入が行われるようにします。
* **結合プローブ マトリックス (`combine()`)**: 複数のプローブの状態 (`is_target_active`、`is_target_busy`、`is_blocked`) を単一の決定的なブール値の結果に集約します。

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

暴走したプロンプト ループやターゲット LLM API へのスパム行為を防ぐために、Watcher Engine は厳密なレート制限パラメーターを強制します。

|パラメータ |デフォルト値 |目的 |
|---|---|---|
| `settle_ms` | `2500ミリ秒` |ターゲットがアイドル状態になってから次のプロンプトを送信するまでに必要な静かな期間。 |
| `min_gap_ms` | `4000ミリ秒` |連続した送信間の最小遅延を強制します。 |
| `max_sends` | `25 アイテム` |自動解除する前に、単一の武装セッションで送信されるプロンプトの最大数。 |
| `max_failures` | `3 失敗` |エラー理由でエンジンを解除するまでの連続失敗しきい値。 |
| `パニック()` |緊急停止 |エンジンを即座に解除し、すべての保留中/実行中の送信インテントをキャンセルします。 |

---
*FastPrompter Wiki — [SAIPEN プロトコル](SAIPEN-プロトコル) で構築 | [GitHub リポジトリ](https://github.com/vacterro/FastPrompter)*