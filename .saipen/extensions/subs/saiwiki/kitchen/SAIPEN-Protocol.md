# SAIPEN Protocol v7 & SubSaipen Architecture

## Overview

SAIPEN (v7) — lightweight structured protocol for persistent AI agent task tracking, state management, event logging, and multi-agent delegation. Zero context-drift across long sessions via machine-readable files in `.saipen/`.

---

## 1. Core Protocol

### Memory Structure (`.saipen/`)

```
.saipen/
├── STATE.md         # Phase, task, blocker, agent params
├── BOARD.md         # Kanban: DOING/TODO/DONE/BLOCKED
├── LOG.md           # Append-only work log (RFC § 1.2)
├── KNOWLEDGE/       # Subsystem reference cards
├── kitchen/         # Scratchpads, intermediate outputs
├── snapshots/       # Timestamped STATE/BOARD/LOG backups
└── recovery/        # Wipe recovery archives
```

### STATE.md Schema (YAML frontmatter)

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

### Phase Machine

1. **SCOUT** — inspect codebase, check deps, read logs
2. **PLAN** — create tickets on BOARD.md, design
3. **BUILD** — implement code/config/docs
4. **VERIFY** — run tests, linters, manual checks
5. **REVIEW** — diff review, LOG entry
6. **DONE** — all tickets complete
7. **BLOCKED** — stuck, blocker field explains why

### Event Log (LOG.md)

```
- 2026-07-30T12:00:00Z [E-001] [T-057] [agent: main] RUN: fix -> PASS
```

### Key Rules
- One agent writes `.saipen/` at a time (RFC § 1.4)
- Dirty tree is NORMAL — attribute before acting, never revert/commit another agent's uncommitted work (RFC § 1.5)
- Checkpoint order: LOG → BOARD → STATE (crash-safe asymmetry, RFC § 1.5)
- Ticket format: `T-###` only (RFC § 1.2)

---

## 2. SubSaipen Architecture

Isolated read-only sub-agents. Output only inside `.saipen/extensions/subs/<name>/`.

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/
            ├── MANIFEST.md         # Active sub list
            ├── PROTOCOL.md         # Full sub protocol
            ├── _shared/inbox.md    # Cross-agent inbox
            ├── TEMPLATE/           # Bootstrap template
            ├── saiwiki/            # Wiki generator (phase DONE)
            └── saihunt/            # Bug hunter (phase DONE)
```

### Lifecycle
1. **SPAWN** — `saipen sub spawn <name>` copies TEMPLATE, adds to MANIFEST
2. **WORK** — reads main project (read-only), produces artifacts in own kitchen/
3. **SIGNAL** — OUTBOX.md entry with `status: ready`
4. **COLLECT** — main agent runs `saipen sub collect`, creates T-### tickets for critical findings

### OUTBOX Format

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

### Ticket ID Namespace

| Prefix | Owner |
|---|---|
| `SYS-` | Cross-cutting / protocol |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (fixer) |
| `<NAME>-` | Any other sub |

Sub IDs never go directly on main BOARD.md — always normal `T-###` with original in description.

### Commands

| Command | Action |
|---|---|
| `saipen sub list` | Show active subs + phase (WARNING on BLOCKED) |
| `saipen sub spawn <name>` | Create new subagent |
| `saipen sub collect` | Process all OUTBOX entries |
| `saipen sub clean <name>` | Remove subagent (refuses if uncollected findings) |
| `saipen sub status <name>` | Peek at OUTBOX without collecting |
| `<name>` (bare) | Role-adopt shortcut — becomes that subagent |
| `saipen sub pause <name>` | Freeze subagent (BLOCKED) without destroying state |
| `saipen sub resume <name>` | Unfreeze subagent |

### Fixer-Type Sub (saipython)

Goes further — OUTBOX carries a **tested patch** as unified diff. Work done in own `kitchen/pen/` sandbox (copy of target file). Verified via project's own test harness before marking `ready`. Never writes to main tree.

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

*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repo](https://github.com/vacterro/FastPrompter)*
