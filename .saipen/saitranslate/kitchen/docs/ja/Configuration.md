# FastPrompter 設定

## DB スキーマ

SQLite DB: `data/local_data_v15.db` (プロファイル 1) または `data/local_data_v15_p<ID>.db` (プロファイル 2 以降)。ポータブル `data/` ディレクトリは EXE の隣。exe ディレクトリが書き込み不可の場合は `%LOCALAPPDATA%/FastPrompter/` にフォールバック。

**テーブル:**
- `settings` — キーと値のテキストペア (すべてのアプリ設定)
- `presets` — スニペット保存 (カテゴリ、スロット、名前、内容、last_edited)
- `temp_presets_v2` — カテゴリ別サイロテキスト内容
- `archive_temp_presets_v2` — カテゴリ別アーカイブ済みサイロ内容

設定は `settings` テーブルのキーと値のペアに保存。INI ファイルなし。適用時にすべてホットリロード。

## 設定キー

| キー | 型 | デフォルト | 説明 |
|---|---|---|---|
| **テーマと表示** | | | |
| `theme` | string | `Golden Default` | テーマ: Default、Golden Vintage、Golden Default、Vintage Dark、Vintage Classic、Dark 2 (OLED)、Dracula、Nord、Solarized Dark、Custom |
| `font_family` | string | `Verdana` | エディタフォント (インストール済みなら `_m1` ビットマップ版に自動解決) |
| `font_size` | int | 18 | エディタフォントサイズ (pt) |
| `ui_scale` | float | 0.5 | UI スケーリング (0.5〜1.5) |
| `button_scale` | float | 0.5 | サイロ + ツールバーボタンサイズ倍率 |
| `custom_cursors` | bool | True | レトロカーソルテーマオーバーレイ |
| `code_monospace` | bool | False | コードブロックの等幅フォント (False = エディタフォント) |
| `code_auto_gutter` | bool | False | コードブロックの自動行番号 |
| `hr_visual_line` | bool | True | `---` をテキストではなく水平線として描画 |
| `live_preview_conceal` | bool | True | `**`、`*`、`~~`、`` ` `` マーカーをライブプレビューで隠す |
| **ホットキー** | | | |
| `global_hotkey` | string | `Alt+X` | グローバル召喚ホットキー |
| `pie_menu_hotkey` | string | `Shift+Alt+X` | パイメニューホットキー |
| `lock_window_hotkey` | string | `Alt+E` | ウィンドウロック切替 |
| `always_on_top_hotkey` | string | `Alt+S` | 常に最前面切替 |
| **動作** | | | |
| `close_on_focus_loss` | bool | True | フォーカス喪失で自動非表示 |
| `always_on_top` | bool | False | 起動時に常に最前面 |
| `normal_window` | bool | False | 通常のウィンドウモード (フレームレスでない) |
| `tray_visible` | bool | True | システムトレイアイコン表示 |
| `auto_bullet` | bool | True | ダッシュを自動で箇条書きに変換 |
| `ctrl_e_center` | bool | True | Ctrl+E ヘッダーを中央揃え |
| `customize_toolbar` | bool | False | ツールバー並べ替えモード |
| `snippets_hidden` | bool | True | スニペットパネル非表示 |
| `sidebar_right` | bool | True | サイドバーを右側に |
| `show_token_count` | bool | False | トークン推定 (ピル数) (T-614) |
| `sync_mode` | string | Off | サイロのディスク同期 (一方向): Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Ctrl+Q ウィンドウプリセットページ有効化 (T-608) |
| **サウンド** | | | |
| `sound_enabled` | bool | True | サウンドのマスター切替 |
| `sound_ui` | bool | True | UI クリック効果音 |
| `sound_typewriter` | bool | False | タイプライターキー音 |
| `sound_volume` | int (0-10) | 1 | マスター音量 |
| **時計と日付** | | | |
| `date_seconds` | bool | True | 時計に秒を表示 |
| `date_daypart` | bool | True | 朝/昼/夕/夜ラベル表示 |
| `date_text_month` | bool | True | テキスト月 (Jan/Feb) を使用 |
| `date_ampm` | bool | False | 12 時間制 AM/PM 形式 |
| `date_emoji` | bool | False | 絵文字の時刻帯 (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | ヘッダーに日付表示 |
| **カーソル** | | | |
| `cursor_blink_ms` | int | 1000 | カーソル点滅速度 ms (0 = 点滅なし、T-606) |
| **タイマー** | | | |
| `timer_show_minutes` | bool | True | タイマー表示に分フィールドを保持 (T-613) |
| **ウィンドウレイアウト** | | | |
| `numbox_per_row` | int | 10 | グリッドの 1 行あたりの数字ボックス数 (T-612) |
| `numbox_btn_size` | int | 24 | 数字ボックスボタンサイズ px (T-612) |
| **その他** | | | |
| `language` | string | EN | UI 言語 (33 ロケール) |
| `hover_line_color` | string | `#0059ff` | 行ハイライト色 (auto = テーマアクセント) |
| `portable_backup_enabled` | bool | True | 起動時の自動 .bak |
| `watcher_skill` | string | (empty) | watcher キューのデフォルトスキル |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | カテゴリタブ順 + 名前 |
| `hidden_categories` | JSON list | [] | 非表示カテゴリ (プロジェクトマネージャーで表示可能) |
| `timers` | JSON | [] | 保存されたカウントダウン定義 |
| `productivity_timer` | JSON | — | Pomodoro タイマー状態 |
| `watcher_queues` | JSON | `{}` | サイロごとのプロンプトキュー |
| `toolbar_order` | string | (empty) | カスタムツールバーボタン順トークン |
| `window_presets` | JSON | [] | ユーザー保存のウィンドウジオメトリプリセット |
| `silo_gap_height` | int | 12 | サイドバーギャップスペーサー高さ px |
| `silo_ticks_enabled` | bool | True | サイロにチェックボタン表示 |
| `silo_view_state_all` | JSON dict | `{}` | サイロごとのカーソル/スクロール/折りたたみ状態 |

## ファイルシステムレイアウト

```
data/
├── local_data_v15.db           # メイン SQLite DB (プロファイル 1)
├── local_data_v15.db.bak       # スロットル式バックアップ (60 秒最小間隔)
├── local_data_v15.db-wal       # WAL 書き込み先ログ
├── local_data_v15.db-shm       # WAL 共有メモリ
├── local_data_v15_p2.db        # プロファイル 2 DB
├── silo_files/                 # ファイルコンテナ添付
│   ├── Code/                   # カテゴリフォルダ
│   │   ├── 0/                  # サイロスロット 0 のファイル
│   │   └── 1/                  # サイロスロット 1 のファイル
│   └── Text/
├── _trash/                     # ソフト削除されたサイロ + ファイル
│   └── 2026-07-22_153022_Silo0/# タイムスタンプ付きゴミ箱エントリ
└── custom_theme.json           # ユーザー定義カラーパレット
```

**毎日ミラー:** `%USERPROFILE%/Documents/.fastprompter/` — タイムスタンプ、プロジェクトごとのサイロ/アーカイブ/スニペットをフラットな .md で

**アンドゥストア:** `data/data_undo_stack.json` + `data/data_redo_stack.json` (自動圧縮、20MB 上限)

## カスタムテーマ

テーマ = Custom のときに `data/custom_theme.json` を読み込み。

**カラートークン:** `bg_main`、`bg_surface`、`bg_editor`、`fg_text`、`fg_accent`、`text_primary`、`text_accent`、`border`、`selection`、`header_bg`、`accent`、`button_bg` など。

設定 → テーマ、またはミニ設定 (Alt+`) で適用。即時ホットリロード、再起動不要。
