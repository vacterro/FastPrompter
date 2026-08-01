# FastPrompter アーキテクチャ概要

## 概要

ポータブルなスクラッチパッド兼プロンプトワークベンチ。Python 3.11+、PyQt6。SQLite WAL 永続化。インストール不要の Nuitka EXE。Alt+X グローバルホットキーで召喚、書き、閉じる — 状態は即時永続化。

## 高レベル図

```
+------------------------------------------------------------------+
|                        FastPrompter UI (PyQt6)                   |
|  +------------------+  +--------------------+  +---------------+  |
|  | SnippetPanel     |  | VaultTextEdit      |  | QueuePanel    |  |
|  | (F1-F10 Silos)   |  | (Markdown + Mixins)|  | (Watcher Q)   |  |
|  +------------------+  +--------------------+  +---------------+  |
+----------------------------+-------------------------------------+
                             | events / state sync
                             v
+------------------------------------------------------------------+
|                    FastPrompterState (core)                       |
|  SQLite WAL DB — silos, snippets, settings, themes, queues       |
|  In-memory cache + undo stack + per-silo state (cursor/scroll)   |
+------------------------------------------------------------------+
      |         |          |          |            |
      v         v          v          v            v
+--------+ +---------+ +--------+ +---------+ +-----------+
|Hotkeys | | IPC     | | Sound  | | Watcher | | File      |
|(pynput)| |(QLocal) | |Manager | |Engine   | | Container |
+--------+ +---------+ +--------+ +---------+ +-----------+
```

## コアサブシステム

### 1. アプリケーションライフサイクル (`main.py`)

エントリポイント。QApplication 初期化、シングルインスタンス IPC チェック (QLocalServer)、DB 接続、グローバル例外フック、UI ウィンドウ構築、システムトレイ、ホットキー登録。全ミックスインが FastPrompter (QMainWindow) に合成される:

- FormattingMixin — マークダウンショートカット (太字、斜体、リスト、コード)
- HotkeyMixin — ショートカットバインドインターフェース
- ScalingMixin — DPI/フォントスケーリング
- SearchMixin — 複数語 AND 検索
- SendSelectionMixin — watcher 経由でテキスト送信
- SnippetOpsMixin — サイロ操作 (ゴミ箱、複製、並べ替え、クリア)
- ThemeMixin — アプリスタイルシート、6 つのレトロ Win95 テーマ + カスタム
- TrayMixin — システムトレイアイコン + メニュー
- WatcherMixin — watcher エンジン統合
- WindowMixin — フレームレスウィンドウ、スナップ、ボーダーレス

### 2. IPC シングルインスタンス (`core/ipc_server.py`)

名前付きパイプ `FastPrompter_Server_V15` 上の QLocalServer。2 番目のインスタンスが SHOW コマンドを送信 → 既存インスタンスがウィンドウを前面に。認証は `%TEMP%/fastprompter_ipc.token` の UUID トークン。クラッシュ時の無言の no-op はなし (server.removeServer が古いソケット名を回収)。

### 3. 状態とストレージ (`core/state.py`)

SQLite DB (`data/local_data_v15.db`) + WAL + synchronous=NORMAL。主要テーブル: `presets` (スニペット)、`settings` (k/v)、`temp_presets_v2` (サイロテキスト)、`archive_temp_presets_v2` (アーカイブ済みサイロ)。

起動時に自動バックアップ (DB 全体コピーを `.bak` に)。60 秒ごとのスロットル式増分バックアップ。カテゴリ別データストア: `silo_colors_all`、`pinned_silos_all`、`silo_ticked_all`、`silo_children_all`、`silo_gaps_all`、`silo_project_paths_all` など。すべてアクティブカテゴリのフラットキー (`temp_presets`) にエイリアス。

### 4. ホットキーシステム (`core/hotkeys.py`, `core/hotkey_filter.py`)

2 層: (1) 召喚/緊急終了用の pynput グローバルリスナースレッド; (2) ウィンドウ内バインディング用の PyQt6 QShortcut。`HotkeyFilter` (Win32 WH_KEYBOARD_LL) が物理 VK コードをインターセプト — レイアウト非依存。QWERTY、JCUKEN、AZERTY、QWERTZ で動作。

### 5. エディタエンジン (`ui/editor.py`)

VaultTextEdit は QPlainTextEdit を拡張。機能:
- MarkdownHighlighter — ライブ構文 (見出し、太字、斜体、コードフェンス、チェックボックス、リンク、画像)
- ラインガター — 行番号、折りたたみ矢印 (▾)、コードフェンスコピーボタン
- セクション折りたたみ — ヘッダーブロックのクリックで折りたたみ
- 折りたたみ可能画像 — `![alt](url)` を 150px のクリック可能ピルとして描画
- ドロップオーバーレイ — 4 オプションのドロップターゲット (テキスト挿入、リンク挿入、ファイルコピー、ショートカット)
- マージンマーク — 行レベルのピン、チェック、キューアンカー、ヒートマップ
- マークアップ非表示モード — `**bold**` → `bold` の切替 (T-603)

### 6. サイロシステム (`ui/snippet_panel.py`)

プロジェクトタブごとに最大 100 サイロ。機能:
- ピン (📌) — 先頭に固定
- チェック (✅) — 完了マーカー
- 階層 — 別のサイロにドラッグしてネスト (最大深さ 2)
- 新しさヒートマップ — 最近編集したものに暖色
- サイドバーギャップ — ユーザー定義スペーサー (Ctrl+ドラッグで移動)
- 複数選択 — Shift=範囲、Ctrl=トグル、一括操作
- ファイルコンテナ — サイロごとのディスクフォルダ (`data/silo_files/<cat>/<idx>/`)
- かんばん (Alt+矢印でカード移動) + テーブルビルダー (Tab でセル移動) — T-630

### 7. Watcher エンジン (`core/watcher/`)

プロンプト排出 + ターゲット自動化。有限状態機械: DISARMED → ARMED → WATCHING → SENDING。Chrome CDP (Electron アプリ) + Win32 ウィンドウプローブ。ターゲットごとのキューピン留め。レート制限: settle_ms=2500、min_gap_ms=4000、max_sends=25、max_failures=3。

### 8. ウィンドウ管理 (`ui/window_mixin.py`, `ui/zen_desktop.py`)

フレームレスウィンドウ、Win95 ダークゴールドの美観。Ctrl+Q でスナップ位置を循環 (7 ゾーン + FancyZone ピッカー + ユーザープリセット)。3 段階 Ctrl+D: 禅 (最小エディタ)、ソロ (他ウィンドウ最小化)、戻る。極細モード (<700px) ではオーバーフローメニュー (») が非表示ボタンを収集。ヘッダー密度ティアは自動調整 (dense <1280px、ultra <700px)。

### 9. タイマーと Pomodoro (`core/timers.py`, `core/pomodoro.py`)

カウントダウンタイマー、色分けされた緊急度、スヌーズ、トースト通知 (Win95 3D ベベル)。Pomodoro 作業/休憩状態機械。

### 10. バックアップとリカバリ

多層: (1) SQLite WAL — クラッシュセーフな書き込み; (2) 起動時 + 60 秒ごとの `.bak`; (3) 毎日の Markdown ミラーを `~/Documents/.fastprompter/` に (プロジェクトごとのサイロ + スニペット + アーカイブ); (4) ポータブルバックアップ ZIP ビルダー。
