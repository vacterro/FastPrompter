# SAIPEN Protocol v7 & SubSaipen Architecture Specification

## Overview
SAIPEN (v7) is a lightweight, structured protocol for persistent AI agent task tracking, state management, event logging, and multi-agent subagent delegation. It guarantees zero context-drift across long development sessions by maintaining machine-parsable tracking files in `.saipen/` (for main workspace) and `subs/<agent_name>/` (for subSaipen agents).

---

## 1. Core SAIPEN v7 Protocol Specification

### Memory Storage Structure (`.saipen/`)
```
.saipen/
├── STATE.md         # Current phase, active task, blocker, agent parameters
├── BOARD.md         # Kanban ticket board (DOING, TODO, DONE, BLOCKED)
├── LOG.md           # Immutable append-only work log history
├── KNOWLEDGE/       # Subsystem reference cards and domain context
└── kitchen/         # Temporary scratchpads and intermediate outputs
```

### State Schema (`STATE.md`)
The `STATE.md` file uses YAML frontmatter format:

```yaml
---
phase: SCOUT | PLAN | BUILD | VERIFY | REVIEW | DONE
task: "Description of active task"
next_action: "Immediate action execution step"
blocker: ""
agent: antigravity
saipen_version: 7
saipen_home: "V:\\___VAC\\__K\\__CODE\\_AI_STUFF_AGENTIC\\_SAIPEN\\saipen"
mode: full
requires: [filesystem, python, shell, git]
updated: 2026-07-22T22:54:00Z
goal_mode: true
goal_waves: 1
goal_tickets: 5
---
```

### State Phase Machine
1. **SCOUT**: Codebase inspection, dependency check, log reading.
2. **PLAN**: Ticket creation on `BOARD.md`, architectural design.
3. **BUILD**: Implementation of code, configuration, or documentation edits.
4. **VERIFY**: Execution of tests, linters, or manual verification tools.
5. **REVIEW**: Code review, diff check, logging completion to `LOG.md`.
6. **DONE**: All tickets executed, state reset to idle.

### Event Logging (`LOG.md`)
Every finished ticket or wave appends a structured log entry:

```markdown
## [2026-07-22T22:54:00Z] T-006: Document User Guide, Hotkeys & Workflows
- **Agent**: saiwiki
- **Phase**: BUILD -> REVIEW
- **Changes**: Created `_user_guide.md` in `subs/saiwiki/kitchen/`.
- **Status**: SUCCESS
```

---

## 2. SubSaipen Architecture & Protocol (`subs/`)

### SubSaipen Directory Map
SubSaipens are isolated sub-agents that run with **read-only access** to the main project codebase and write output exclusively inside their designated sub-directory under `subs/`.

```
project-root/
├── subs/                          # SubSaipen container directory
│   ├── MANIFEST.md                # Active subSaipen registry & status
│   ├── RFC_SUBSAIPEN.md           # Protocol specification
│   ├── saiwiki/                   # Wiki Generator subSaipen
│   │   ├── STATE.md
│   │   ├── BOARD.md
│   │   ├── LOG.md
│   │   └── kitchen/
│   │       ├── OUTBOX.md          # Hand-off results for main agent
│   │       └── (scratch files)
│   ├── saihunt/                   # Bug Hunter subSaipen
│   │   ├── STATE.md
│   │   ├── BOARD.md
│   │   ├── LOG.md
│   │   └── kitchen/
│   │       ├── OUTBOX.md
│   │       └── (scratch files)
│   └── _shared/                   # Cross-agent communications inbox
│       └── inbox.md
```

### SubSaipen Lifecycle State Machine

```
+-------+      +------+      +--------+      +----------+      +--------------+      +-------+
| SPAWN | ---> | WORK | ---> | SIGNAL | ---> | WAIT_ACK | ---> | ACK_RECEIVED | ---> | CLEAN |
+-------+      +------+      +--------+      +----------+      +--------------+      +-------+
```

1. **SPAWN**: 親エージェントは、サブディレクトリ `subs/<name>/` をデフォルトの `STATE.md`、`BOARD.md`、`LOG.md`、および `kitchen/OUTBOX.md` で初期化します。 `subs/MANIFEST.md` にエージェントを登録します。
2. **作業**: SubSaipen は、メイン プロジェクトのソース ファイルを読み取り専用モードで読み取り、分析またはドキュメントの作成を実行し、ローカルの `BOARD.md` と `STATE.md` を更新します。
3. **シグナル**: SubSaipen はドラフト成果物を `kitchen/` に出力し、ハンドオフの概要を `kitchen/OUTBOX.md` にステータス `ready` で書き込みます。
4. **WAIT_ACK**: SubSaipen は、親の確認を待つために実行を一時停止します。
5. **ACK_RECEIVED**: メイン エージェントは `OUTBOX.md` を読み取り、アーティファクトを統合するかチケットを発行し、ACK を `OUTBOX.md` または `_shared/inbox.md` に書き込みます。
6. **クリーン**: SubSaipen はライフサイクルを完了するか、次のウェーブに移行します。

---

## 3. OUTBOX Hand-off Format Specification

「kitchen/OUTBOX.md」ファイルは、subSaipens とメインエージェントの間の厳密な契約として機能します。

```markdown
# subSaipen <agent_name> Outbox

**ステータス**: 「準備完了」 | `草案` | 「ブロックされました」
**更新**: 2026-07-22T22:54:00Z

## Summary of Output Artifacts
Detailed overview of generated drafts and findings.

1. **アーティファクト名 (`path/to/artifact`)**
   - 対象・目的
   - 調査結果または内容の概要
   - `クリティカル`: true |偽
   - `main_project_refs`: [参照されるメインプロジェクトファイルのリスト]

## Next Recommended Actions for Main Agent
- Action items or ticket suggestions for the main workspace BOARD.
```

---

## 4. SubSaipen Conflict Resolution & Safety Rules

1. **読み取り専用のメイン ワークスペース保護**: SubSaipen エージェントが `subs/<agent_name>/` 以外のファイルを編集することは固く禁止されています。
2. **独立したメモリ**: 各 subSaipen は独自の `STATE.md`、`BOARD.md`、および `LOG.md` を維持します。
3. **サブエージェント間での直接的な突然変異はありません**: SubSaipens は、互いのディレクトリを変更することはありません。通信は `OUTBOX.md` と `_shared/inbox.md` のみを介して流れます。
4. **メイン エージェントの仲裁**: 2 つのサブサイペンが矛盾する変更を提案した場合、メイン エージェントは階層を使用して優先順位を解決します。
   - **バグ修正 (`saihunt`)** > **ドキュメント (`saiwiki`)** > **リファクタリング** > **新機能**。