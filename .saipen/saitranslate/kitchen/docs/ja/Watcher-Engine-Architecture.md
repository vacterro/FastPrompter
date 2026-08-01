# Watcher エンジンアーキテクチャ

## 概要

プロンプト排出 + ターゲット自動化サブシステム。プロンプトをキューし、ターゲットアプリの状態 (Electron/Web/任意の Win32 ウィンドウ) を監視し、ターゲットがアイドル時に自動送信。

---

## 高レベルアーキテクチャ

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

## 1. 状態機械 (`engine.py`)

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

### 状態
1. **DISARMED** — 非アクティブ、プローブポーリングなし、アイテム処理なし
2. **ARMED** — ターゲットウィンドウ + queue_key にバインド。ターゲットのアクティビティを待機。
3. **WATCHING** — ターゲットがビジーと観測 (LLM 生成中)。アイドル + settle を待機。
4. **SENDING** — SendIntent をディスパッチ。注入確認を待機。

---

## 2. Chrome CDP (`cdp.py`)

なぜ CDP か: Electron アプリ (VS Code、Claude Desktop、ChatGPT、Obsidian) は Win32 メッセージを処理しない。Chromium の IPC は `PostMessageW` を無視 — 文字が静かにドロップされる。

### 操作
- `discover()` — `http://127.0.0.1:<port>/json/list` にページターゲットを照会
- ページごとの WebSocket JSON-RPC 接続
- テキスト注入用の `Runtime.evaluate` + `Input.dispatchKeyEvent`
- **読み戻し検証** — テキストを挿入し、DOM クエリでフィールド値を読み、一致した場合のみ Submit
- ノンブロッキングタイムアウト (デフォルト 3 秒)

---

## 3. Win32 プローブ (`win32.py`、`probes.py`)

Electron 以外のターゲットアプリ用。

- `GetForegroundWindow()` + タイトル正規表現マッチ → ターゲット検出
- キャレット + フォーカス監視 → 入力フィールドがアクティブなときのみ注入
- `combine()` — マルチプローブ状態を単一の bool に集約 (is_target_active、is_target_busy、is_blocked)

---

## 4. キューモデル (`queue.py`)

### QueueItem
- `id` — UUID
- `text` — プロンプトテキスト
- `skill` — ラッパースキル名
- `line` — ソース行番号 (ライブテキスト追跡用)

### SendIntent
- `item_id`、`text`、`queue_key`、`skill` — 送信者用にカプセル化

### ライフサイクル
1. **Pending** — バックログ内
2. **In-Flight** — SendIntent が送信者にディスパッチ済み
3. **Sent** — 送信者によって確認、キューから削除
4. **Failed** — consecutive_failures を増分、max_failures (3) まで再試行

### キューピン留め
`arm(target, queue_key)` 時にキーがピン留めされる。セッション中にプロジェクト/サイロを切り替えても、watcher は正しいキューを排出し続ける。

---

## 5. 安全ガード

| パラメータ | デフォルト | 目的 |
|---|---|---|
| `settle_ms` | 2500 | ターゲットアイドル後の送信前の静寂時間 |
| `min_gap_ms` | 4000 | 連続送信間の最小遅延 |
| `max_sends` | 25 | アーム済みセッションごとの最大プロンプト数 (自動ディスアーム) |
| `max_failures` | 3 | 連続失敗 → エラーでディスアーム |
| `panic()` | — | 緊急停止: ディスアーム + すべてのインフライトをキャンセル |

---

## 6. スキルシステム (`skills.py`)

ディスパッチ前に適用されるプロンプトラッパー。

```python
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review:\n\n{text}",
}
```

変数: `{text}`、`{timestamp}`、`{project}`。

---

## 7. スキルと Watcher ダイアログ

- `Alt+C` — 現在のエディタ行をキュー (ブロックアンカー付き)
- `Alt+Shift+C` — Queue Master (すべてのサイロ概要)
- 設定でデフォルトスキルを設定
- Watcher ダイアログ: アーム/ディスアーム、ターゲット選択、プローブ設定
