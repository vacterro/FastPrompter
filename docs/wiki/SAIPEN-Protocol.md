# SAIPEN Protocol v7 & SubSaipen Architecture Specification

## Overview
SAIPEN (v7) is a lightweight, structured protocol for persistent AI agent task tracking, state management, event logging, and multi-agent subagent delegation. It guarantees zero context-drift across long development sessions by maintaining machine-parsable tracking files in `.saipen/` (main workspace) and `.saipen/extensions/subs/<agent_name>/` (subSaipen agents).

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
YAML frontmatter format:

```yaml
---
phase: SCOUT | PLAN | BUILD | VERIFY | REVIEW | DONE
task: "Description of active task"
next_action: "Immediate action execution step"
blocker: ""
agent: antigravity | claude | main
saipen_version: 7
saipen_home: "V:\\___VAC\\__K\\__CODE\\_AI_STUFF_AGENTIC\\_SAIPEN"
mode: full | read-only
requires: [filesystem, python, shell, git]
updated: 2026-07-24T12:00:54Z
---
```

### State Phase Machine
1. **SCOUT**: Codebase inspection, dependency check, log reading.
2. **PLAN**: Ticket creation on BOARD.md, architectural design.
3. **BUILD**: Implementation of code, config, or documentation edits.
4. **VERIFY**: Tests, linters, or manual verification.
5. **REVIEW**: Code review, diff check, logging completion to LOG.md.
6. **DONE**: All tickets executed, state reset to idle.

### Event Logging (LOG.md)
Every finished ticket or wave appends a structured log entry:
```markdown
- 2026-07-24T12:00:54Z [E-###] [T-###] [agent: main] RUN: action -> PASS
```

---

## 2. SubSaipen Architecture & Protocol

### SubSaipen Directory Map
SubSaipens are isolated sub-agents with read-only access to the main project. Output written exclusively inside their designated `.saipen/extensions/subs/<name>/` directory.

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/                    # SubSaipen container directory
            ├── MANIFEST.md          # Active subSaipen registry
            ├── PROTOCOL.md          # SubSaipen protocol specification
            ├── _shared/
            │   └── inbox.md         # Cross-agent communications inbox
            ├── TEMPLATE/            # SubSaipen bootstrap template
            │   ├── STATE.md
            │   ├── BOARD.md
            │   ├── LOG.md
            │   └── kitchen/
            │       └── OUTBOX.md
            ├── saiwiki/             # Wiki Generator subSaipen
            │   ├── STATE.md
            │   ├── BOARD.md
            │   ├── LOG.md
            │   └── kitchen/
            │       ├── OUTBOX.md
            │       └── (scratch files)
            └── saihunt/             # Bug Hunter subSaipen
                ├── STATE.md
                ├── BOARD.md
                ├── LOG.md
                └── kitchen/
                    ├── OUTBOX.md
                    └── (scratch files)
```

### SubSaipen Lifecycle
1. **SPAWN**: Parent agent initializes sub-directory from TEMPLATE, registers in MANIFEST.md.
2. **WORK**: SubSaipen reads main project (read-only), produces artifacts in its own kitchen/.
3. **SIGNAL**: Outputs hand-off summary into kitchen/OUTBOX.md with `status: ready`.
4. **COLLECT**: Main agent inspects OUTBOX.md, integrates findings (critical → immediate ticket, non-critical → _shared/inbox.md).

No ACK ceremony, no lifecycle timers — manually invoked agents.

---

## 3. OUTBOX Hand-off Format

```markdown
# OUTBOX

## WIKI-001: short description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line, what was found
- **main_project_refs:** [docs/wiki/foo.md]
- **critical:** true | false
- **details:** Full description
```

`critical: true` = bug, broken behavior, data loss, security issue.
`critical: false` = improvement, docs, refactor, cosmetic.

---

## 4. Ticket ID Namespace

| Prefix | Owner |
|---|---|
| `SYS-` | Cross-cutting / protocol-level |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (fixer) |
| `<NAME>-` | Any other subSaipen |

SubSaipen IDs (`WIKI-001`) are never written directly to the main BOARD.md — a normal `T-###` ticket is created with the original ID preserved in the description.

---

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
