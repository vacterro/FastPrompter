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

1. **SPAWN**: Родительский агент инициализирует подкаталог `subs/<name>/` со значениями по умолчанию `STATE.md`, `BOARD.md`, `LOG.md` и `kitchen/OUTBOX.md`. Регистрирует агент в `subs/MANIFEST.md`.
2. **РАБОТА**: SubSaipen читает основные исходные файлы проекта в режиме только для чтения, выполняет анализ или составление документов, а также обновляет свои локальные файлы `BOARD.md` и `STATE.md`.
3. **СИГНАЛ**: SubSaipen выводит черновые артефакты в `kitchen/` и записывает сводку передачи в `kitchen/OUTBOX.md` со статусом `ready`.
4. **WAIT_ACK**: SubSaipen приостанавливает выполнение в ожидании родительского подтверждения.
5. **ACK_RECEIVED**: Главный агент читает `OUTBOX.md`, интегрирует артефакты или выдает билеты и записывает ACK в `OUTBOX.md` или `_shared/inbox.md`.
6. **ЧИСТОТА**: SubSaipen завершает жизненный цикл или переходит к следующей волне.

---

## 3. OUTBOX Hand-off Format Specification

Файл «kitchen/OUTBOX.md» служит строгим контрактом между subSaipens и главным агентом:

```markdown
# subSaipen <agent_name> Outbox

**Статус**: `готов` | `черновик` | `заблокировано`
**Обновлено**: 22 июля 2026 г.T22:54:00Z.

## Summary of Output Artifacts
Detailed overview of generated drafts and findings.

1. **Имя артефакта («путь/к/артефакту»)**
   - Цель/Цель
   - Краткое изложение выводов или содержания
   - `критический`: правда | ложный
   - `main_project_refs`: [список основных файлов проекта, на которые имеются ссылки]

## Next Recommended Actions for Main Agent
- Action items or ticket suggestions for the main workspace BOARD.
```

---

## 4. SubSaipen Conflict Resolution & Safety Rules

1. **Защита основной рабочей области только для чтения**: агентам SubSaipen строго запрещено редактировать файлы за пределами `subs/<agent_name>/`.
2. **Независимая память**: каждый subSaipen поддерживает свои собственные `STATE.md`, `BOARD.md` и `LOG.md`.
3. **Нет прямой межсубагентной мутации**: SubSaipens никогда не изменяет каталоги друг друга. Связь осуществляется исключительно через OUTBOX.md и _shared/inbox.md.
4. **Арбитраж главного агента**: если два субсайпена предлагают конфликтующие модификации, главный агент определяет приоритеты, используя иерархию:
   - **Исправление ошибок (`saihunt`)** > **Документация (`saiwiki`)** > **Рефакторинг** > **Новая функция**.