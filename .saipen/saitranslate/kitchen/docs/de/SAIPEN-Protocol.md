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

1. **SPAWN**: Der übergeordnete Agent initialisiert das Unterverzeichnis „subs/<name>/“ mit den Standardeinstellungen „STATE.md“, „BOARD.md“, „LOG.md“ und „kitchen/OUTBOX.md“. Registriert den Agenten in „subs/MANIFEST.md“.
2. **ARBEIT**: SubSaipen liest die Quelldateien des Hauptprojekts im schreibgeschützten Modus, führt Analysen oder Dokumenterstellungen durch und aktualisiert seine lokalen „BOARD.md“ und „STATE.md“.
3. **SIGNAL**: SubSaipen gibt Entwurfsartefakte in „kitchen/“ aus und schreibt die Übergabezusammenfassung in „kitchen/OUTBOX.md“ mit dem Status „ready“.
4. **WAIT_ACK**: SubSaipen unterbricht die Ausführung und wartet auf die Bestätigung durch die Eltern.
5. **ACK_RECEIVED**: Der Hauptagent liest „OUTBOX.md“, integriert Artefakte oder stellt Tickets aus und schreibt ACK in „OUTBOX.md“ oder „_shared/inbox.md“.
6. **REINIGUNG**: SubSaipen schließt den Lebenszyklus ab oder geht zur nächsten Welle über.

---

## 3. OUTBOX Hand-off Format Specification

Die Datei „kitchen/OUTBOX.md“ dient als strenger Vertrag zwischen subSaipens und dem Hauptagenten:

```markdown
# subSaipen <agent_name> Outbox

**Status**: „bereit“ | „Entwurf“ | „blockiert“.
**Aktualisiert**: 22.07.2026T22:54:00Z

## Summary of Output Artifacts
Detailed overview of generated drafts and findings.

1. **Artefaktname („Pfad/zu/Artefakt“)**
   - Ziel / Zweck
   - Zusammenfassung der Erkenntnisse oder Inhalte
   - „kritisch“: wahr | falsch
   - „main_project_refs“: [Liste der Hauptprojektdateien, auf die verwiesen wird]

## Next Recommended Actions for Main Agent
- Action items or ticket suggestions for the main workspace BOARD.
```

---

## 4. SubSaipen Conflict Resolution & Safety Rules

1. **Schreibgeschützter Schutz des Hauptarbeitsbereichs**: SubSaipen-Agenten ist es strengstens untersagt, Dateien außerhalb von „subs/<agent_name>/“ zu bearbeiten.
2. **Unabhängiger Speicher**: Jeder SubSaipen verwaltet seine eigenen „STATE.md“, „BOARD.md“ und „LOG.md“.
3. **Keine direkte Mutation zwischen Subagenten**: SubSaipens ändern niemals gegenseitig die Verzeichnisse. Die Kommunikation erfolgt ausschließlich über „OUTBOX.md“ und „_shared/inbox.md“.
4. **Schlichtung durch den Hauptagenten**: Wenn zwei Subsaipens widersprüchliche Änderungen vorschlagen, legt der Hauptagent die Prioritäten anhand der Hierarchie fest:
   - **Fehlerbehebung (`saihunt`)** > **Dokumentation (`saiwiki`)** > **Refactoring** > **Neue Funktion**.