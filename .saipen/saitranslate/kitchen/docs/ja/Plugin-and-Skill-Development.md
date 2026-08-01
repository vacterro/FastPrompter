# プラグイン、スキル & 拡張開発ガイド

## 1. カスタムスキル (`core/watcher/skills.py`)

スキルは watcher 経由でアイテムを送信するときに適用されるプロンプトラッパー。

### 定義

```python
# Skill entry dict
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review this code:\n\n{text}",
    "description": "Standard code review prompt wrapper"
}
```

### テンプレート変数
- `{text}` — キューされたアイテムテキスト
- `{timestamp}` — 現在時刻
- `{project}` — アクティブプロジェクト名

### 適用
設定 → Watcher → デフォルトスキルで設定。Queue Master ダイアログでアイテムごとに上書き。

## 2. SAIPEN サブエージェント

サブエージェントは `.saipen/extensions/subs/<name>/` に存在 (プロジェクトルートの `subs/` ではない)。

```
.saipen/extensions/subs/
├── MANIFEST.md          # アクティブサブリスト
├── PROTOCOL.md          # ルール
├── TEMPLATE/            # ブートストラップテンプレート
├── saiwiki/             # wiki ドキュメント生成サブエージェント
├── saihunt/             # バグハンターサブエージェント
└── _shared/inbox.md     # クロスエージェント通信
```

### ハンドオフ (OUTBOX.md)

```
# OUTBOX

## WIKI-001: Description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line finding
- **critical:** true | false
- **details:** full description
```

`critical: true` → メインエージェントが即座に T-### チケットを作成。
`critical: false` → 次の計画ラウンドのために `_shared/inbox.md` にキュー。

**コマンド:**
- `saipen sub spawn <name>` — TEMPLATE から新しいサブエージェントを作成
- `saipen sub collect` — すべての OUTBOX エントリを収集
- `saipen sub list` — アクティブなサブエージェント + フェーズを表示
- `saipen sub clean <name>` — 完了したサブエージェントを削除

## 3. カスタムテーマ

ファイル: `data/custom_theme.json`。テーマ = Custom のときに読み込み。

### スキーマ

```json
{
  "theme_name": "My Theme",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_editor": "#1b1b1b",
    "fg_text": "#d4d4d4",
    "fg_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78",
    "header_bg": "#252526",
    "button_bg": "#2d2d30",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422"
  }
}
```

**適用:** 設定 → テーマ → Custom。即時ホットリロード、再起動不要。

## 4. カーソルテーマ (`ui/cursor_theme.py`)

カスタムマウスカーソルセット。レトロコンピューティング風。

**関数:**
- `capture_current_scheme()` — 実行中の Windows カーソルセットをプログラムにコピー
- `load_bundle()` — インストール済みカーソルセットを返す
- `install_to_system(paths)` — Windows のデフォルトカーソルスキームとして設定
- `build_cursor_map()` — カーソルシェイプマップを再構築

**切替:** 設定 → カーソル → カスタムカーソルを有効化。初回有効化時に現在の Windows セットを自動キャプチャ。

## 5. Watcher エンジンの拡張性

| モジュール | 拡張ポイント |
|---|---|
| `adapter.py` | カスタムターゲット検出用の ProbeAdapter を実装 |
| `cdp.py` | Electron アプリ用のカスタム CDP コマンド |
| `win32.py` | Win32 ウィンドウプローブのカスタマイズ |
| `skills.py` | カスタムプロンプトスキルテンプレートを追加 |
| `limit_scan.py` | カスタムクロスエージェント制限スキャナー |
| `sender.py` | カスタムテキスト注入戦略 |

## 6. サイロのディスク同期 (T-591)

一方向のサイロ → ファイルシステムエクスポート。設定 → 同期モード: Off / Silo (フラット) / Hierarchy (ネスト)。保存時に `<root>/<category>/<NN_slug>.md` を書き込み。読み戻しなし、削除なし。変更のないテキストはスキップ。
