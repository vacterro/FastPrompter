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

1. **SPAWN**: Parent agent initializes sub-directory `subs/<name>/` with default `STATE.md`, `BOARD.md`, `LOG.md`, and `kitchen/OUTBOX.md`. Registers agent in `subs/MANIFEST.md`.
2. **WORK**: SubSaipen reads main project source files in read-only mode, performs analysis or document drafting, and updates its local `BOARD.md` and `STATE.md`.
3. **SIGNAL**: SubSaipen outputs draft artifacts in `kitchen/` and writes hand-off summary into `kitchen/OUTBOX.md` with status `ready`.
4. **WAIT_ACK**: SubSaipen pauses execution awaiting parental acknowledge.
5. **ACK_RECEIVED**: Main agent reads `OUTBOX.md`, integrates artifacts or issues tickets, and writes ACK to `OUTBOX.md` or `_shared/inbox.md`.
6. **CLEAN**: SubSaipen completes lifecycle or transitions to next wave.

---

## 3. OUTBOX Hand-off Format Specification

The `kitchen/OUTBOX.md` file serves as the strict contract between subSaipens and the main agent:

```markdown
# subSaipen <agent_name> Outbox

**Status**: `ready` | `draft` | `blocked`
**Updated**: 2026-07-22T22:54:00Z

## Summary of Output Artifacts
Detailed overview of generated drafts and findings.

1. **Artifact Name (`path/to/artifact`)**
   - Target / Purpose
   - Summary of findings or content
   - `critical`: true | false
   - `main_project_refs`: [list of main project files referenced]

## Next Recommended Actions for Main Agent
- Action items or ticket suggestions for the main workspace BOARD.
```

---

## 4. SubSaipen Conflict Resolution & Safety Rules

1. **Read-Only Main Workspace Protection**: SubSaipen agents are strictly prohibited from editing files outside `subs/<agent_name>/`.
2. **Independent Memory**: Each subSaipen maintains its own `STATE.md`, `BOARD.md`, and `LOG.md`.
3. **No Direct Inter-Subagent Mutation**: SubSaipens never modify each other's directories. Communication flows exclusively through `OUTBOX.md` and `_shared/inbox.md`.
4. **Main Agent Arbitration**: If two subSaipens propose conflicting modifications, the main agent resolves priorities using the hierarchy:
   - **Bug Fix (`saihunt`)** > **Documentation (`saiwiki`)** > **Refactoring** > **New Feature**.
