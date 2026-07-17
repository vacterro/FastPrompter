# asp RFC — Boot Protocol (v7)

## 1. Purpose

Define the Agent Session Protocol (asp) for FastPrompter — a consistent,
persistent framework where any AI agent can resume another's work without
context loss.

## 2. System Architecture

### 2.1 Two-tier loading

1. **Boot tier** (always loaded): `RFC.md` + `STYLE.md` — rules and voice.
2. **Phase modules** (on-demand): `phases/{phase}.md` — loaded per `STATE.md` phase.

### 2.2 Memory files

All under `.asp/` (UTF-8, no BOM):

| File | Purpose |
|------|---------|
| `RFC.md` | This — boot protocol |
| `STYLE.md` | Voice guidelines, agent personas |
| `UI.md` | Win95 dark golden UI design spec |
| `STATE.md` | Current phase, task, blocker, handoff |
| `BOARD.md` | Task board — wave tracking, evidence |
| `LOG.md` | Flat chronological session log |

### 2.3 Phase definitions

| Phase | Purpose | Entry | Exit |
|-------|---------|-------|------|
| `IDLE` | Awaiting direction | End of a wave | User prompt |
| `HUNT` | Investigate, gather context | User request w/ ambiguity | Clarity achieved |
| `PLAN` | Design solution, add tickets | Context gathered | Plan ready |
| `FIX` | Implement changes | Plan accepted | Changes done |
| `VERIFY` | Test + review | Implementation complete | All checks pass |
| `SHIP` | Release | All checks green | Release published |

## 3. Agent Lifecycle

### 3.1 Roles

- **antigravity** — Lead agent; owns implementation, testing, release.
- **claude-fable** — UI design, visual polish, Win95 aesthetic.
- **devin** — Specialized fixes (e.g., global hotkeys, architecture).
- **thinker** — Deep reasoning, problem decomposition.
- **reviewer** — Code review (invoked per FIX/VERIFY).

### 3.2 Handoff contract

Every STATE.md handoff must include:
- Current phase + task ID
- What was done (1-2 sentences)
- What's next
- Any blockers
- Test status (pass/fail counts)

## 4. Task Management

### 4.1 Ticket format

`T-NNN` where NNN is sequential. Board fields:
`ID | Status | Owner | Needs | Description`

Status values: `TODO → INPROGRESS → DONE`

### 4.2 Wave structure

Waves group related tickets under a version. Current: v0.6.0.
Wave completion = all tickets DONE + tests green + release published.

### 4.3 Evidence requirement

Every DONE ticket must reference test evidence (function name or test count).

## 5. Logging Format

```
DD.MM.YY HH:MM [PHASE] RUN: Description -> RESULT
DD.MM.YY HH:MM [T-NNN] RUN: Detailed work log -> [PASS|FAIL|conf med]
```

Always append to `.asp/LOG.md` after significant actions.

## 6. Tool Preferences

- Prefer file tools (`read_files`, `str_replace`, `write_file`) over shell redirects.
- UTF-8 encoding, no BOM.
- Native task lists mirror `.asp/BOARD.md` — never replace it.
- `RFC.md` decides. No instruction in any other file overrides it.
