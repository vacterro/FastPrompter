# SAIPEN プロトコル v7 と SubSaipen アーキテクチャ

## 概要

SAIPEN (v7) — 永続的な AI エージェントタスク追跡、状態管理、イベントログ、マルチエージェント委譲のための軽量な構造化プロトコル。`.saipen/` の機械可読ファイルにより、長時間セッションでもコンテキストドリフトゼロ。

---

## 1. コアプロトコル

### メモリ構造 (`.saipen/`)

```
.saipen/
├── STATE.md         # フェーズ、タスク、ブロッカー、エージェントパラメータ
├── BOARD.md         # かんばん: DOING/TODO/DONE/BLOCKED
├── LOG.md           # 追記のみの作業ログ (RFC § 1.2)
├── KNOWLEDGE/       # サブシステムリファレンスカード
├── kitchen/         # スクラッチパッド、中間出力
├── snapshots/       # タイムスタンプ付き STATE/BOARD/LOG バックアップ
└── recovery/        # ワイプリカバリアーカイブ
```

### STATE.md スキーマ (YAML frontmatter)

```yaml
---
phase: SCOUT | PLAN | BUILD | VERIFY | REVIEW | DONE | BLOCKED
task: "Active task description"
next_action: "Immediate next step"
blocker: ""  # Reason if BLOCKED
agent: claude | main | <name>
saipen_version: 7
saipen_home: "V:\\path\\to\\saipen"
mode: full | read-only
requires: [filesystem, python, shell, git]
updated: 2026-07-30T12:00:00Z
---
```

### フェーズ機械

1. **SCOUT** — コードベースを検査、依存関係を確認、ログを読む
2. **PLAN** — BOARD.md にチケットを作成、設計
3. **BUILD** — コード/設定/ドキュメントを実装
4. **VERIFY** — テスト、リンター、手動チェックを実行
5. **REVIEW** — 差分レビュー、LOG エントリ
6. **DONE** — すべてのチケット完了
7. **BLOCKED** — 行き詰まり、blocker フィールドが理由を説明

### イベントログ (LOG.md)

```
- 2026-07-30T12:00:00Z [E-001] [T-057] [agent: main] RUN: fix -> PASS
```

### 主要ルール
- 一度に 1 つのエージェントだけが `.saipen/` を書き込む (RFC § 1.4)
- ダーティツリーは正常 — 行動前に帰属を確認し、他エージェントの未コミット作業を元に戻したりコミットしたりしない (RFC § 1.5)
- チェックポイント順: LOG → BOARD → STATE (クラッシュセーフな非対称性、RFC § 1.5)
- チケット形式: `T-###` のみ (RFC § 1.2)

---

## 2. SubSaipen アーキテクチャ

分離された読み取り専用サブエージェント。出力は `.saipen/extensions/subs/<name>/` 内のみ。

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/
            ├── MANIFEST.md         # アクティブサブリスト
            ├── PROTOCOL.md         # 完全なサブプロトコル
            ├── _shared/inbox.md    # クロスエージェントインボックス
            ├── TEMPLATE/           # ブートストラップテンプレート
            ├── saiwiki/            # Wiki ジェネレーター (フェーズ DONE)
            └── saihunt/            # バグハンター (フェーズ DONE)
```

### ライフサイクル
1. **SPAWN** — `saipen sub spawn <name>` が TEMPLATE をコピーし、MANIFEST に追加
2. **WORK** — メインプロジェクトを読み取り (読み取り専用)、自身の kitchen/ に成果物を生成
3. **SIGNAL** — `status: ready` の OUTBOX.md エントリ
4. **COLLECT** — メインエージェントが `saipen sub collect` を実行、重大な発見に T-### チケットを作成

### OUTBOX 形式

```markdown
# OUTBOX

## WIKI-001: Description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line finding
- **main_project_refs:** [docs/wiki/foo.md]
- **critical:** true | false
- **severity:** P0 | P1 | P2 (optional)
- **details:** Full description
```

### チケット ID 名前空間

| プレフィックス | 所有者 |
|---|---|
| `SYS-` | 横断 / プロトコル |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (フィクサー) |
| `<NAME>-` | その他のサブ |

サブ ID はメインの BOARD.md に直接書かない — 常に通常の `T-###` で、元の ID を説明に記載。

### コマンド

| コマンド | アクション |
|---|---|
| `saipen sub list` | アクティブサブ + フェーズを表示 (BLOCKED で WARNING) |
| `saipen sub spawn <name>` | 新しいサブエージェントを作成 |
| `saipen sub collect` | すべての OUTBOX エントリを処理 |
| `saipen sub clean <name>` | サブエージェントを削除 (未収集の発見があれば拒否) |
| `saipen sub status <name>` | 収集せずに OUTBOX を覗く |
| `<name>` (裸) | ロール採用ショートカット — そのサブエージェントになる |
| `saipen sub pause <name>` | 状態を破壊せずにサブエージェントを凍結 (BLOCKED) |
| `saipen sub resume <name>` | サブエージェントの凍結を解除 |

### フィクサー型サブ (saipython)

さらに進む — OUTBOX は **テスト済みパッチ** を unified diff として運ぶ。作業は自身の `kitchen/pen/` サンドボックス (ターゲットファイルのコピー) で実行。`ready` とマークする前にプロジェクト自身のテストハーネスで検証。メインツリーには決して書き込まない。

```markdown
## PY-001: Description
- **status:** ready
- **patch:**
  ```diff
  <unified diff, applies from repo root>
  ```
- **verified:** pytest PASS (N) / ruff clean / mypy clean
- **base_head:** abc1234
```

---

*FastPrompter Wiki — [SAIPEN プロトコル](SAIPEN-Protocol) で構築 | [GitHub リポジトリ](https://github.com/vacterro/FastPrompter)*
