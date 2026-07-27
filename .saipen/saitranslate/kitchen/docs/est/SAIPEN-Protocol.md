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

1. **SPAWN**: vanemagent initsialiseerib alamkataloogi `subs/<nimi>/` vaikeväärtustega STATE.md, BOARD.md, LOG.md ja kitchen/OUTBOX.md. Registreerib agendi saidil "subs/MANIFEST.md".
2. **TÖÖ**: SubSaipen loeb kirjutuskaitstud režiimis peamisi projekti lähtefaile, analüüsib või koostab dokumente ning värskendab kohalikke faile BOARD.md ja STATE.md.
3. **SIGNAAL**: SubSaipen väljastab mustandi artefaktid kaustas "kitchen/" ja kirjutab üleandmise kokkuvõtte kausta "kitchen/OUTBOX.md" olekuga "valmis".
4. **WAIT_ACK**: SubSaipen peatab täitmise, oodates vanema kinnitust.
5. **ACK_RECEIVED**: põhiagent loeb faili OUTBOX.md, integreerib artefakte või väljastab pileteid ja kirjutab ACK-i failile OUTBOX.md või _shared/inbox.md.
6. **CLEAN**: SubSaipen lõpetab elutsükli või läheb üle järgmisele lainele.

---

## 3. OUTBOX Hand-off Format Specification

Fail "kitchen/OUTBOX.md" toimib range lepinguna subSaipensi ja põhiagendi vahel:

```markdown
# subSaipen <agent_name> Outbox

**Olek**: "valmis" | "mustand" | `blokeeritud`
**Värskendatud**: 2026-07-22T22:54:00Z

## Summary of Output Artifacts
Detailed overview of generated drafts and findings.

1. **Artefakti nimi (tee/artefaktini)**
   - Eesmärk / eesmärk
   - Leidude või sisu kokkuvõte
   - "kriitiline": tõsi | vale
   - "main_project_refs": [viidatud põhiprojektifailide loend]

## Next Recommended Actions for Main Agent
- Action items or ticket suggestions for the main workspace BOARD.
```

---

## 4. SubSaipen Conflict Resolution & Safety Rules

1. **Kirjutuskaitstud põhitööruumi kaitse**: SubSaipeni agentidel on rangelt keelatud redigeerida faile väljaspool lahtrit `subs/<agendi_nimi>/`.
2. **Sõltumatu mälu**: iga subSaipen säilitab oma oleku 'STATE.md', 'BOARD.md' ja 'LOG.md'.
3. **Otsene alaagentidevaheline mutatsioon puudub**: SubSaipenid ei muuda kunagi üksteise katalooge. Suhtlus toimub ainult OUTBOX.md ja _shared/inbox.md kaudu.
4. **Peaagendi vahekohtumenetlus**: kui kaks alam-Saipenit pakuvad vastukäivaid muudatusi, määrab põhiagent prioriteedid kindlaks hierarhiat kasutades:
   - **Veaparandus (saihunt)** > **Dokumentatsioon (saiwiki)** > **Refaktoreerimine** > **Uus funktsioon**.