# FastPrompter モジュール構成

## コードベースマップ (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # エントリポイント、QMainWindow、ミックスイン調整
├── __init__.py                 # パッケージマーカー
│
├── core/                       # バックエンドロジック、状態、サブシステム
│   ├── config.py               # テーマカラー抽出、トレイアイコン生成
│   ├── ctrlw.py                # Ctrl+W / Alt+W 区切り挿入エンジン
│   ├── default_profile.py      # 出荷時デフォルトマップ、state.reset_data() にマージ
│   ├── duration.py             # 時間パーシング、人間可読な期間書式
│   ├── hashtags.py             # ハッシュタグ抽出 + サイロ横断インデックス
│   ├── header.py               # Ctrl+E ヘッダー書式コア
│   ├── hotkey_filter.py        # VK ディスパッチ用 Win32 WH_KEYBOARD_LL フック
│   ├── hotkeys.py              # pynput グローバルホットキーリスナースレッド
│   ├── ipc_server.py           # QLocalServer シングルインスタンス IPC
│   ├── limits.py               # エージェントリセット制限スキャナー + タイマー作成
│   ├── logging.py              # ロガー設定、ローテーションファイルハンドラー
│   ├── pomodoro.py             # Pomodoro 状態機械 (作業/休憩)
│   ├── sound_manager.py        # オーディオ再生 (クリック、タイプライター、アラーム)
│   ├── state.py                # SQLite DB インターフェース + 状態管理
│   ├── timers.py               # カウントダウンタイマーモデル、期限検出
│   ├── translations.py         # i18n パッケージへのレガシープロキシ (33 ロケール)
│   │
│   ├── i18n/                   # 33 ロケールリソースパック
│   │   ├── __init__.py, _compat.py, _container.py, _context.py, _engine.py
│   │   ├── en.py, ru.py, est.py, ja.py, ded.py, ... (33 ロケールモジュール)
│   │   └── flags/              # 国旗レンダラー
│   │
│   └── watcher/                # 自動化 + プロンプト排出エンジン
│       ├── __init__.py
│       ├── adapter.py          # 抽象プローブアダプターインターフェース
│       ├── cdp.py              # Chrome DevTools Protocol ドライバー
│       ├── engine.py           # Watcher 実行ループ + 状態機械
│       ├── limit_scan.py       # クロスエージェント制限スキャナー
│       ├── probes.py           # マルチプローブ状態コンビネーター
│       ├── queue.py            # キューモデル (QueueItem、SendIntent、ピン留め)
│       ├── sender.py           # 出力ディスパッチ (CDP / Win32 キー注入)
│       ├── skills.py           # スキル定義 + プロンプトラッパー
│       └── win32.py            # ネイティブ Win32 ウィンドウ + コントロールプローブ
│
├── ui/                         # PyQt6 UI コンポーネント + ミックスイン
│   ├── analog_clock.py         # カスタム描画アナログ時計ウィジェット
│   ├── backup_dialog.py        # DB エクスポート/インポート + バックアップスナップショットダイアログ
│   ├── ctrlw_settings.py       # Ctrl+W/Alt+W テンプレート設定 UI
│   ├── cursor_theme.py         # レトロカーソルテーマオーバーレイマネージャー
│   ├── drop_overlay.py         # ドラッグ & ドロップ 4 オプションターゲットオーバーレイ
│   ├── edit_guard.py           # 読み取り専用編集ロックガードラッパー
│   ├── editor.py               # VaultTextEdit: コードブロック、ガター、折りたたみ
│   ├── fancy_zones.py          # 画面スナップゾーンオーバーレイピッカー
│   ├── file_container.py       # サイロアセットファイルドロワー + テンプレート
│   ├── flags.py                # ベクター/ラスターフラグレンダラー
│   ├── flow_layout.py          # 動的 heightForWidth ラッピングレイアウト
│   ├── formatting_mixin.py     # マークダウン書式ショートカット
│   ├── hashtag_dialog.py       # タグ検索 + サイロフィルターオーバーレイ
│   ├── header_format_dialog.py # 日時タイムスタンプ書式ダイアログ
│   ├── help_dialog.py          # キーボードショートカット + 対話型ガイド
│   ├── hotkey_mixin.py         # メインウィンドウ用ホットキーバインドミックスイン
│   ├── layout_shortcuts.py     # 物理 VK ショートカットマッピング (レイアウト非依存)
│   ├── markdown_highlighter.py # ライブマークダウン用 QSyntaxHighlighter
│   ├── pie_menu.py             # QuickListWidget 放射状コンテキストメニュー
│   ├── queue_panel.py          # Watcher キューダイアログ
│   ├── resizers.py             # ウィンドウリサイズハンドルコントロール
│   ├── scaling_mixin.py        # UI DPI + フォントスケーリングミックスイン
│   ├── search_mixin.py         # 複数語 AND 検索フィルター
│   ├── send_selection_mixin.py # watcher 経由で選択範囲を送信
│   ├── settings.py             # 設定ダイアログ (テーマ、ホットキー、サウンド)
│   ├── silo_kanban.py          # マークダウンかんばんボード (T-630)
│   ├── silo_settings_dialog.py # サイロごとの設定 (色、プロジェクトリンク)
│   ├── silo_table.py           # マークダウンテーブルビルダー (T-630)
│   ├── kanban_widget.py        # かんばんボード表示ウィジェット (silo_kanban バックエンド)
│   ├── table_widget.py         # テーブル表示ウィジェット (silo_table バックエンド)
│   ├── silo_region.py          # サイロリスト領域: ドラッグ、ギャップ、複数選択
│   ├── snippet_ops_mixin.py    # サイロ操作 (ゴミ箱、移動、複製、クリア)
│   ├── snippet_panel.py        # サイロツリー + F1-F10 スニペットボタン
│   ├── theme_mixin.py          # ビンテージテーマスタイリング + QSS ジェネレーター
│   ├── timer_dialog.py         # Pomodoro + アラームタイマー設定ダイアログ
│   ├── timer_toast.py          # 浮遊通知トーストウィジェット
│   ├── toolbar_reorder.py      # ドラッグ & ドロップツールバーボタン並べ替え
│   ├── trash_dialog.py         # ゴミ箱 + 復元ダイアログ
│   ├── tray_mixin.py           # システムトレイアイコン + コンテキストメニュー
│   ├── watcher_dialog.py       # Watcher 設定 + スクリプトマネージャー UI
│   ├── watcher_mixin.py        # Watcher エンジンウィンドウ統合
│   ├── window_mixin.py         # フレームレス移動、スナップ、ボーダーレスコントロール
│   ├── window_presets_dialog.py # ユーザー定義ウィンドウ位置プリセット
│   └── zen_desktop.py          # 3 段階 Zen/ソロデスクトップ掃引 (Ctrl+D)
│
├── theme/                      # テーマプリセット
│   └── themes.py               # 9 つの内蔵カラーテーマ + カスタムエンジン
│
└── utils/                      # 低レベルヘルパー
    ├── fonts.py                # システムフォントローダー、フォールバック解決、no-AA
    ├── paths.py                # ポータブルパス解決 (exe + ユーザーデータ)
    ├── portable_backup.py      # ポータブル ZIP バックアップビルダー
    └── textfit.py              # 動的テキスト切り詰め + ラベルフィッティング
```

## サブシステムの責任

| パッケージ | 責任 |
|---|---|
| `core.state` | SQLite WAL 永続化、状態同期、アンドゥスタック、カテゴリ別エイリアスストア |
| `core.hotkey*` | グローバルホットキーリスナー + Win32 VK フィルター、レイアウト非依存ディスパッチ |
| `core.watcher` | プロンプトキュー、CDP/Win32 自動化、スキルラッパー、制限スキャナー |
| `core.i18n` | 33 ロケール翻訳パック + translations.py からのプロキシ委譲 |
| `core.ctrlw` | 区切りテンプレートエンジン (Ctrl+W / Alt+W) |
| `core.timers` | タイマーモデル、期限検出、シリアライゼーション |
| `core.pomodoro` | 作業/休憩状態機械、フォーカスタイマー |
| `ui.editor` | VaultTextEdit — 折りたたみ、ガター、チェックボックス、ヒートマップ、マージンマーク、マークアップ非表示 |
| `ui.snippet_panel` | サイロツリー、階層、カテゴリタブ、F1-F10 スロット、サイドバーギャップ、複数選択 |
| `ui.silo_kanban` | プレーンテキストかんばんボード (Alt+矢印でカード移動、Enter で新行) |
| `ui.silo_table` | プレーンテキストテーブルエディタ (Tab でセル移動、Enter で新行) |
| `ui.file_container` | サイロごとのフォルダドロワー、アセットプレビュー、テンプレート |
| `ui.theme_mixin` | 9 つの内蔵テーマ + カスタムカラーエンジン + QSS ジェネレーター |
| `ui.kanban_widget` | かんばんボード表示ウィジェット (silo_kanban バックエンド) |
| `ui.table_widget` | テーブル表示ウィジェット (silo_table バックエンド) |
| `ui.silo_region` | サイロリスト領域: ドラッグ、ギャップ、複数選択 |
| `ui.fancy_zones` | 7 レイアウトプリセットの視覚ゾーンピッカー |
| `ui.window_presets_dialog` | ユーザー保存のウィンドウジオメトリプリセット (Ctrl+Q ページ) |
| `ui.zen_desktop` | 3 段階 Ctrl+D: Zen、ソロ (他を最小化)、戻る |
| `ui.toolbar_reorder` | ドラッグ & ドロップツールバーボタンカスタマイズ |
| `ui.flow_layout` | コンパクト設定パネル用のレスポンシブラッピングレイアウト |
| `ui.edit_guard` | begin/endEditBlock ガード — 終了していない編集によるフリーズを防止 |
| `utils.fonts` | フォント解決、ビットマップフォントインストール、no-AA フォールバック |
| `utils.paths` | ポータブル実行 — レジストリなし、AppData 依存なし |

## モジュール数まとめ

- **core/**: 16 モジュール + i18n/ (33 ロケール + インフラ 5 ファイル = 38) + watcher/ (10 モジュール)
- **ui/**: 44 モジュール
- **theme/**: 1 モジュール
- **utils/**: 4 モジュール
- **合計**: `src/fastprompter/` 配下に `.py` ファイル 115 個 (`main.py` + `__init__.py` を含む)
