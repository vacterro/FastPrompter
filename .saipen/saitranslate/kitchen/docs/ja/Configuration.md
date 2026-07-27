# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings are stored in the SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

|設定キー |タイプ |デフォルト |説明 |
|---|---|---|---|
| `テーマ` |文字列 | `"デフォルト"` |アクティブなビジュアル テーマ (`"デフォルト"`、`"アンバー"`、`"OLED"`、`"Win95"`、`"ローズ"`、`"カスタム"`) |
| `フォントサイズ` |整数 | `11` |プライマリ エディタのフォント サイズ (ポイント単位) |
| `ui_scale` |フロート | `"1.0"` |全体的な UI スケーリング係数 (0.5 ～ 1.5) |
| `ボタンスケール` |フロート | `"1.0"` |サイロとツールバーのボタン サイズの乗数 |
| `グローバルホットキー` |文字列 | 「Alt+X」 |アプリケーション ウィンドウを表示/非表示にするためのプライマリ ホットキー |
| `パイ_メニュー_ホットキー` |文字列 | `"Shift+Alt+X"` |放射状の円メニューをトリガーするホットキー |
| `ロックウィンドウホットキー` |文字列 | 「Alt+S」 |ウィンドウ位置のロックを切り替えるホットキー |
| `always_on_top_hotkey` |文字列 | 「Alt+E」 |ホットキーで常に上部ウィンドウ モードを切り替える |
| `close_on_focus_loss` |ブール値 | 「本当です」 |フォーカスが失われたときにウィンドウを自動的に非表示にする |
| `ctrl_c_closes` |ブール値 | 「本当です」 |スニペット モードで `Ctrl+C` を押した後にウィンドウを閉じる/非表示にする |
| `サウンド_UI` |ブール値 | `"偽"` | UI ボタン​​のクリック音の効果を有効にする |
| `サウンドタイプライター` |ブール値 | `"偽"` |タイプライターキーの効果音を有効にする |
| `サウンドボリューム` |整数 | `"5"` |音量レベル (0 ～ 10) |
| `ポータブルバックアップが有効` |ブール値 | 「本当です」 |起動時に `.bak` データベース ファイルを自動作成 |
| `言語` |文字列 | `"EN"` |インターフェース言語 (`EN`、`RU`、`UK`、`DE`、`FR`、`ES`、`IT`、`PT`、`NL`、`PL`、`SV`、`DA`、`FI`、`NO`、`JA`、`ZH`、`KO`、`TH`、`VI`、`AR`、`HE`、`ET`、 `DED`) |
| `サイドバー右` |ブール値 | `"偽"` |サイロ サイドバーをエディターの右側に配置する |
| `code_auto_gutter` |ブール値 | `"偽"` |エディターのコード ブロックに行番号を自動的に表示する |
| `猫の注文` | JSON リスト | `["コード","テキスト","その他"]` |プロジェクト カテゴリ タブのカスタム順序 |

---

## File System & Storage Directory Structure

FastPrompter は、すべてのユーザー データを実行可能ファイルに隣接する自己完結型の `data/` ディレクトリに保存し、100% ポータブルな実行を保証します。

```
data/
├── fastprompter.db             # Main SQLite database (Default profile)
├── fastprompter.db.bak         # Startup backup SQLite database
├── fastprompter_p2.db          # Profile 2 SQLite database
├── silo_files/                 # File Container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 attachment directory
│   │   └── 1/                  # Silo slot 1 attachment directory
│   └── Text/
├── _trash/                     # Soft-deleted silos and files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash archive
└── custom_theme.json           # User-defined custom color palette (if enabled)
```

---

## Custom Themes & Color Editing
When `theme` is set to `"Custom"`, FastPrompter reads color preferences from `custom_theme.json` or state overrides.

### Supported Theme Color Tokens
- `bg_main`: Primary window and panel background color
- `bg_editor`: Editor canvas background color
- `fg_text`: Primary text color
- `border`: Window border and divider line color
- `accent`: Active selection, focus ring, and pin highlight color
- `header_bg`: Header bar and title background color
