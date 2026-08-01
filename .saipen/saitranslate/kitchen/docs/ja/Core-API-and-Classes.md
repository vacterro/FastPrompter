# FastPrompter コア API とクラスリファレンス

## コアクラス (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

スレッドセーフな SQLite データモデル。中央状態ハブ — すべてのサイロ、スニペット、設定、テーマ、キューがここを通る。

**メソッド:**
- `__init__(profile_id=1)` — SQLite 接続を開き、WAL モード、キャッシュされた設定を読み込み
- `init_db()` — スキーマを作成/アップグレード (presets、settings、temp_presets_v2、archive_temp_presets_v2)、起動時 .bak バックアップを実行
- `switch_profile(new_profile_id)` — 現在の DB を閉じ、パスを切り替え、再読み込み
- `save_data_to_db(text, ui_settings, force)` — アトミックなダーティ状態フラッシュ
- `mark_dirty()` — 保存が必要な状態としてフラグ (自動保存タイマー経由で非同期)
- `reset_data()` — メモリ内デフォルトを再初期化

**データモデル:** 単一の `self.data` 辞書。カテゴリ別ストアはエイリアス: `temp_presets` → `temp_presets_all[active_cat]`、`silo_colors` → `silo_colors_all[active_cat]` など。すべての `_all` キーは初回アクセス時に自動マイグレーション。

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

システム全体のホットキー用のスレッド化された pynput キーボードリスナー。

**メソッド:**
- `start()` — pynput リスナースレッドを生成
- `stop()` — リスナーを停止
- `update_hotkeys(hk_dict)` — ホットキーマップを再登録

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32 WH_KEYBOARD_LL フック。物理 VK コードをインターセプト — レイアウト非依存。クロスレイアウト動作 (QWERTY/JCUKEN/AZERTY)。layout_shortcuts.py ディスパッチに使用。

---

### `IpcServer` (`core/ipc_server.py`)

名前付きパイプ `FastPrompter_Server_V15` 上の QLocalServer。UUID トークン認証は `%TEMP%/fastprompter_ipc.token`。

**メソッド:**
- `setup()` — リッスン開始 (removeServer で古いソケット名を回収)
- `close()` — サーバー停止
- `_handle_command()` — 2 番目のインスタンスからの SHOW コマンドを処理

**ヘルパー:**
- `try_connect_to_server()` — 実行中インスタンスをプローブ (QLocalSocket または None を返す)

---

### `SoundManager` (`core/sound_manager.py`)

UI クリック、タイプライターキー、タイマーアラーム用の WAV 再生。

**メソッド:**
- `play_ui_click()`、`play_tick_sound()`、`play_typewriter()`、`play_sound(name)` — オーディオをディスパッチ
- 音量は `sound_volume` 設定 (0-10) で制御

---

### `PomodoroEngine` (`core/pomodoro.py`)

設定可能な間隔を持つ作業/休憩状態機械。

**定数:** `PHASE_WORK`、`PHASE_BREAK`

**メソッド:**
- `start_work()`、`start_break()`、`pause()`、`reset()` — ライフサイクル
- `tick(elapsed)` — タイマーを進め、フェーズ遷移を生成
- `describe()` — 人間可読な状態文字列
- `from_dict(data)` / `to_dict()` — JSON シリアライゼーション

---

### `Timer` と `TimerManager` (`core/timers.py`)

汎用カウントダウンタイマー。色分けされた緊急度、発火時のサウンド、スヌーズ。

**Timer 属性:** `name`、`description`、`target` (datetime)、`sound`、`volume`、`color_mode`、`color`

**メソッド:**
- `remaining()` — ターゲットまでの秒数
- `snooze(minutes)` — ターゲットを前方に押す
- `display_color()` — 緊急度カラー (緑/黄/赤)
- `collect_due(timers)` — 期限切れタイマーリストを返す
- `next_due(timers)` — 最も近いタイマー
- `save_timers(data)` / `load_timers(data)` — シリアライゼーション

---

### `DurationParser` (`core/duration.py`)

人間可読な期間パーシング。

- `parse_duration(text)` — "2h 30m" → 秒
- `format_remaining(seconds, short=False, minutes=False)` — "2h 30m" → "2h" または "4d 11h 05m"
- `format_duration(seconds)` — 完全なフォーマット文字列

---

### `HashtagIndex` (`core/hashtags.py`)

サイロ横断ハッシュタグ抽出 + 検索。

- `extract_tags(text)` — `#tag` 文字列のセットを返す
- `index_silo(cat, slot, text)` — タグ → サイロインデックス
- `search(tag)` — カテゴリ横断でタグを含むすべてのサイロ

---

### `DividerEngine` (`core/ctrlw.py`)

Ctrl+W / Alt+W テンプレート挿入。

- `insert_divider(editor, template, upward)` — 水平線を挿入、分割時に重複する箇条書きを除去
- `simulate(editor, upward)` — 挿入位置をプレビュー

---

### `HeaderFormatter` (`core/header.py`)

Ctrl+E ヘッダー挿入。設定可能: ルーラー行、ギャップ、箇条書き、配置、タイムスタンプ。

- `format_header(editor, config)` — 現在の行をヘッダーとしてフォーマット

---

### Watcher エンジンモジュール (`core/watcher/`)

| モジュール | 役割 |
|---|---|
| `engine.py` | 有限状態機械: DISARMED → ARMED → WATCHING → SENDING |
| `cdp.py` | Chrome CDP アタッチ + 評価 + 読み戻し検証 (Electron アプリ) |
| `win32.py` | Win32 ウィンドウプローブ — フォアグラウンド、キャレット、フォーカス検出 |
| `probes.py` | マルチプローブ状態コンビネーター + 結合マトリクス |
| `queue.py` | QueueItem、SendIntent、ピン留め、キューごとのキー、永続化 |
| `sender.py` | CDP + Win32 キーストローク注入と読み戻し検証 |
| `skills.py` | プロンプトスキルラッパー — プレフィックス/テンプレート変換 |
| `adapter.py` | 抽象プローブアダプターインターフェース |
| `limit_scan.py` | クロスエージェント制限スキャナー + 自動タイマー作成 |

---

## UI コンポーネント (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow。ミックスイン構成 (宣言順):
1. FormattingMixin — マークダウン書式ショートカット
2. HotkeyMixin — ホットキーバインドインターフェース
3. ScalingMixin — DPI/フォントスケーリング
4. SearchMixin — サイロ上の検索バー
5. SendSelectionMixin — watcher 経由でテキスト送信
6. SnippetOpsMixin — サイロ操作 (ゴミ箱、複製、並べ替え)
7. ThemeMixin — アプリスタイルシート、ビンテージプリセット
8. TrayMixin — システムトレイアイコン + メニュー
9. WatcherMixin — watcher エンジン統合
10. WindowMixin — フレームレスウィンドウ + スナップ

**主要プロパティ:** `_font_size`、`_font_family`、`_ui_scale`、`_button_scale`、`_sidebar_right`、`_always_on_top`、`_normal_window`

**主要メソッド:**
- `init_ui()` — ウィンドウ、ヘッダーツールバー、スプリッター、エディタ、サイドバー、ステータスバーを構築
- `setup_single_instance_server()` — IPC 初期化
- `register_all_hotkeys()` — pynput + PyQt ショートカットをバインド
- `apply_font()` / `apply_theme()` — フォント/テーマ変更をカスケード
- `place_window()` — 保存されたジオメトリを復元またはデフォルトスナップを適用
- `_switch_to_slot(slot, initial)` — サイロをエディタに読み込み、カーソル状態を保存
- `capture_silo_state()` / `restore_silo_state()` — サイロごとのカーソル/スクロール/折りたたみ/ヒート永続化

---

### `VaultTextEdit` (`ui/editor.py`)

拡張された QPlainTextEdit。マークダウン編集キャンバス。

**機能:**
- MarkdownHighlighter — ライブ構文カラーリング
- LineNumberArea — ガター: 行番号 + 折りたたみ矢印 (▾) + マージンマーク
- `fold_header(block_num)` / `unfold_header(block_num)` — セクション折りたたみ
- `queue_current_line()` — watcher アイテムをブロックにアンカー
- `set_queue_anchor(block, id)` — キューの行アンカリング
- `collect_line_marks()` / `apply_line_marks()` — 行ごとのマージンマーク永続化
- `collect_line_heat()` / `apply_line_heat()` — 新しさヒートマップ
- `block_for_queue_item(id)` — キューアンカーでブロックを検索
- `toggle_checkbox()` — `- [ ]` ↔ `- [x]`
- `toggle_hide_markup(checked)` — ** * ~~ ` マーカーを隠す (T-603)
- 画像ピル — `![alt](url)` → 150px のクリック可能ボタン

---

### `SnippetPanel` (ui/snippet_panel.py)

サイドバーのサイロリスト + F1-F10 ボタン。

**クラス:**
- `SnippetWidget` — サイドバーパネル: カテゴリタブ + サイロリスト
- `DraggableSiloButton` — 個々のサイロボタン (ピン、チェック、色、ファイルアイコン、ドラッグ)
- `WheelPager` — サイロリスト用のスクロール同期ページャー
- `DropVerticalWidget` — 階層ネスト用のドロップゾーン

**機能:**
- タブごとに最大 100 サイロ
- ピン、チェック、新しさヒートマップ、階層 (ドラッグでネスト)
- サイドバーギャップ — ユーザー定義スペーサーバー (Ctrl+ドラッグで移動)
- 複数選択 — Shift=範囲、Ctrl=トグル、一括削除/保存/クリア
- 数字ボックスモード — 番号付きボタン行としてのプロジェクト切り替え (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

サイロごとのファイルドロワー。エディタの下に開く。

- `load_files(cat, slot)` — フォルダ内容を読み取り
- `add_files(paths)` — 外部ファイルをサイロフォルダにコピー
- `apply_template(name)` — フォルダ構造を作成 (IN/OUT/DOCS/Assets/Drafts)
- 画像プレビュー、リンクモード、ドラッグ & ドロップ
- サイロバックアップ — Ctrl+クリック 📁 でサイロテキストをエクスポート

---

### `SiloTable` (`ui/silo_table.py`)

プレーンテキストのマークダウンテーブルビルダー。Qt テーブルなし — プレーンマークダウンで動作。

- Tab/Shift+Tab: セルを移動; 最後のセルで Tab → 新しい行
- Enter: 新しい行 (分割しない)
- セル編集はインラインマークダウン経由

---

### `SiloKanban` (`ui/silo_kanban.py`)

プレーンテキストのマークダウンかんばんボード。カードはマークダウンリスト項目。

- Alt+↑/↓: カードを上下に移動
- Alt+←/→: カードを隣接カラムに移動
- 空のボード行で Enter: 新しいカード
- チェックボックスをクリック: 完了トグル

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)

視覚的な画面ゾーンピッカー。7 レイアウトプリセット (TL、TR、BL、BR、Center、Full、Cursor)。ゾーンをクリックしてスナップ。

---

### `SaipenViewerDialog` (`ui/saipen_dialog.py`)

`.saipen/` の STATE、BOARD、LOG ファイル用の読み取り専用ビューアー。

- Ctrl+Shift+C またはツールバーで開く
- プロジェクトパスの `.saipen/` を自動検出
- ライブ更新ボタン

---

### `WindowPresetsDialog` (`ui/window_presets_dialog.py`)

ユーザー定義のウィンドウ位置プリセット。画面の分数として最大 10 の保存済みジオメトリ。

- 現在のジオメトリを保存、名前変更、並べ替え、再キャプチャ
- Ctrl+Q ピッカーページから適用
- モニターごとの分数保存 (モニター変更後も生存)

---

### `TimerToast` (`ui/timer_toast.py`)

タイマーアラーム用の浮遊通知トースト。Win95 3D ベベル、テーマカラー、スヌーズボタン。

### `ToolbarReorder` (`ui/toolbar_reorder.py`)

ドラッグ & ドロップのツールバーカスタマイズ。表示可能なギャップウィジェット。リセットボタン。

### オーバーフローメニュー (`main.py`)

ヘッダーが < 700px のとき: 非表示ボタンは » ポップアップに収集。すべての書式、ナビゲーション、ツールに引き続き到達可能。

### `EditGuard` (`ui/edit_guard.py`)

コンテキストマネージャー: `with edit_block(widget): ...` が begin/endEditBlock をラップ。終了していない編集操作による Qt フリーズを防止。
