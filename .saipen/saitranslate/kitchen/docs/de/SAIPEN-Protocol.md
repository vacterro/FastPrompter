# SAIPEN-Protokoll v7 & SubSaipen-Architektur

## Übersicht

SAIPEN (v7) — leichtgewichtiges, strukturiertes Protokoll für persistente KI-Agenten-Aufgabenverfolgung, Zustandsverwaltung, Ereignisprotokollierung und Multi-Agenten-Delegation. Null Kontextdrift über lange Sitzungen durch maschinenlesbare Dateien in `.saipen/`.

---

## 1. Kern-Protokoll

### Speicherstruktur (`.saipen/`)

```
.saipen/
├── STATE.md         # Phase, Aufgabe, Blocker, Agent-Parameter
├── BOARD.md         # Kanban: DOING/TODO/DONE/BLOCKED
├── LOG.md           # Nur-Anhängen-Arbeitsprotokoll (RFC § 1.2)
├── KNOWLEDGE/       # Subsystem-Referenzkarten
├── kitchen/         # Notizblöcke, Zwischenausgaben
├── snapshots/       # Zeitgestempelte STATE/BOARD/LOG-Backups
└── recovery/        # Wipe-Recovery-Archive
```

### STATE.md-Schema (YAML-Frontmatter)

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

### Phasenmaschine

1. **SCOUT** — Codebase prüfen, Abhängigkeiten checken, Protokolle lesen
2. **PLAN** — Tickets auf BOARD.md erstellen, Design
3. **BUILD** — Code/Konfiguration/Dokumente implementieren
4. **VERIFY** — Tests, Linter, manuelle Checks ausführen
5. **REVIEW** — Diff-Review, LOG-Eintrag
6. **DONE** — alle Tickets abgeschlossen
7. **BLOCKED** — festgefahren, Blocker-Feld erklärt warum

### Ereignisprotokoll (LOG.md)

```
- 2026-07-30T12:00:00Z [E-001] [T-057] [agent: main] RUN: fix -> PASS
```

### Schlüsselregeln
- Ein Agent schreibt `.saipen/` zu einer Zeit (RFC § 1.4)
- Dirty Tree ist NORMAL — vor dem Handeln zuordnen, nie uncommittete Arbeit anderer Agenten zurücksetzen/committen (RFC § 1.5)
- Checkpoint-Reihenfolge: LOG → BOARD → STATE (crashsichere Asymmetrie, RFC § 1.5)
- Ticketformat: nur `T-###` (RFC § 1.2)

---

## 2. SubSaipen-Architektur

Isolierte Read-only-Subagenten. Ausgabe nur innerhalb von `.saipen/extensions/subs/<name>/`.

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/
            ├── MANIFEST.md         # Aktive Sub-Liste
            ├── PROTOCOL.md         # Volles Sub-Protokoll
            ├── _shared/inbox.md    # Cross-Agent-Inbox
            ├── TEMPLATE/           # Bootstrap-Template
            ├── saiwiki/            # Wiki-Generator (Phase DONE)
            └── saihunt/            # Bug-Jäger (Phase DONE)
```

### Lebenszyklus
1. **SPAWN** — `saipen sub spawn <name>` kopiert TEMPLATE, fügt MANIFEST hinzu
2. **WORK** — liest das Hauptprojekt (read-only), erzeugt Artefakte im eigenen kitchen/
3. **SIGNAL** — OUTBOX.md-Eintrag mit `status: ready`
4. **COLLECT** — Hauptagent führt `saipen sub collect` aus, erstellt T-###-Tickets für kritische Befunde

### OUTBOX-Format

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

### Ticket-ID-Namespace

| Präfix | Besitzer |
|---|---|
| `SYS-` | Querschnitt / Protokoll |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (Fixer) |
| `<NAME>-` | jeder andere Sub |

Sub-IDs gehen nie direkt auf das Haupt-BOARD.md — immer normale `T-###` mit Original in der Beschreibung.

### Befehle

| Befehl | Aktion |
|---|---|
| `saipen sub list` | Aktive Subs + Phase anzeigen (WARNUNG bei BLOCKED) |
| `saipen sub spawn <name>` | Neuen Subagenten erstellen |
| `saipen sub collect` | Alle OUTBOX-Einträge verarbeiten |
| `saipen sub clean <name>` | Subagenten entfernen (verweigert bei nicht eingesammelten Befunden) |
| `saipen sub status <name>` | OUTBOX ansehen ohne einzusammeln |
| `<name>` (nackt) | Rollenübernahme-Shortcut — wird zu diesem Subagenten |
| `saipen sub pause <name>` | Subagenten einfrieren (BLOCKED), ohne Zustand zu zerstören |
| `saipen sub resume <name>` | Subagenten auftauen |

### Fixer-Typ-Sub (saipython)

Geht weiter — OUTBOX trägt einen **getesteten Patch** als Unified-Diff. Arbeit in eigenem `kitchen/pen/`-Sandbox (Kopie der Zieldatei). Verifiziert über die eigene Test-Harness des Projekts, bevor `ready` markiert wird. Schreibt nie in den Haupt-Baum.

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

*FastPrompter Wiki — Erstellt mit [SAIPEN-Protokoll](SAIPEN-Protocol) | [GitHub-Repo](https://github.com/vacterro/FastPrompter)*
