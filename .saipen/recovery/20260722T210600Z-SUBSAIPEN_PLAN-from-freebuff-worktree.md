# SubSaipen System — Implementation Plan

## Overview

Система параллельных SAIPEN-агентов (subSaipen), которые работают read-only к main project, имеют полную изоляцию, и передают результаты главному агенту через OUTBOX-протокол.

## Architecture

```
project-root/
├── subs/                          # все subSaipen живут здесь
│   ├── MANIFEST.md                # активные subSaipen, статус, версия
│   ├── RFC_SUBSAIPEN.md           # протокол subSaipen (создаётся T-001)
│   ├── saiwiki/                   # subSaipen: документация/GitHub Wiki
│   │   ├── STATE.md
│   │   ├── BOARD.md
│   │   ├── LOG.md
│   │   └── kitchen/
│   │       ├── OUTBOX.md          # готовые результаты для главного агента
│   │       └── (scratch files)
│   ├── saihunt/                   # subSaipen: баг-хантер
│   │   ├── STATE.md
│   │   ├── BOARD.md
│   │   ├── LOG.md
│   │   └── kitchen/
│   │       ├── OUTBOX.md
│   │       └── (scratch files)
│   └── _shared/                   # общая зона для коммуникации
│       └── inbox.md               # главный агент кладёт сюда задачи для subSaipen
```

## Tickets (BOARD)

### T-001: Создать RFC_SUBSAIPEN.md
**needs:** none
**Phase:** PLAN → SCOUT → BUILD → VERIFY → REVIEW

Написать формальный протокол subSaipen.

**Что должно быть в документе:**

1. **Lifecycle subSaipen**
   - `SPAWN` — создать папку, STATE/BOARD/LOG/kitchen для нового subSaipen
   - `WORK` — subSaipen читает main project read-only, пишет результаты в kitchen/OUTBOX.md
   - `SIGNAL` — subSaipen кладёт сигнальный файл kitchen/OUTBOX.md
   - `COLLECT` — главный агент проверяет OUTBOX, создаёт тикеты если надо
   - `ACK` — главный агент подтверждает получение, subSaipen очищает OUTBOX
   - `CLEAN` — удаление subSaipen

2. **OUTBOX.md формат**
   ```markdown
   # OUTBOX
   
   ## T-001: Описание задачи
   - **status:** ready | draft | blocked
   - **summary:** Короткое описание что сделано
   - **main_project_refs:** [src/fastprompter/main.py, src/fastprompter/ui/editor.py]
   - **critical:** true | false
   - **details:**
     Подробное описание результата.
     Что нашёл, что предлагает, почему это важно.
   ```

3. **Handoff Protocol**
   - Главный агент вызывает `saipen sub collect` — читает все OUTBOX.md
   - Если `critical: true` — создаёт тикет немедленно, поднимает приоритет
   - Если `critical: false` — кладёт в `_shared/inbox.md` для следующего раунда
   - SubSaipen не удаляет OUTBOX пока не получит ACK

4. **Conflict Resolution**
   - Если два subSaipen предлагают изменения в одни и те же файлы — главный агент решает
   - Приоритет: bugfix > documentation > refactoring > feature
   - SubSaipen не спорят друг с другом — они только пишут в свои OUTBOX

5. **State Machine**
   ```text
   SPAWN → WORK → SIGNAL → WAIT_ACK → ACK_RECEIVED → WORK (next ticket) | CLEAN
   ```

### T-002: Создать структуру subs/ и MANIFEST.md
**needs:** T-001
**Phase:** BUILD

Создать начальную структуру папок и MANIFEST.md:

```markdown
# SubSaipen Manifest

## Active
| name | status | last_outbox | spawn_time | version |
|------|--------|-------------|------------|---------|
| saiwiki | active | 2026-07-22T12:00:00Z | 2026-07-22T10:00:00Z | 1 |
| saihunt | active | never | 2026-07-22T10:00:00Z | 1 |

## Protocol
- **version:** 1
- **ref:** subs/RFC_SUBSAIPEN.md
```

### T-003: Создать saiwiki subSaipen
**needs:** T-001, T-002
**Phase:** BUILD → VERIFY → REVIEW

**SubSaipen saiwiki — GitHub Wiki генератор.**

**Что делает:**
1. Читает main project (read-only): структуру, модули, ключевые классы
2. Создаёт план wiki-страниц: Architecture, Modules, API, Configuration
3. Для каждой страницы пишет контент в `kitchen/`
4. Кладет готовые страницы в OUTBOX.md с пометкой `ready`

**Структура subSaipen saiwiki:**
```
subs/saiwiki/
├── STATE.md          # phase, task, next_action
├── BOARD.md          # тикеты для wiki-страниц
├── LOG.md            # лог работы
└── kitchen/
    ├── OUTBOX.md     # готовые страницы для интеграции
    ├── _wiki_index.md  # план: какие страницы нужны
    ├── _architecture.md
    ├── _modules.md
    ├── _api.md
    └── _configuration.md
```

**STATE.md initial:**
```yaml
---
phase: PLAN
task: none
next_action: READ main project structure → create wiki index
blocker: none
agent: saiwiki
saipen_version: 7
mode: read-only
updated: 2026-07-22T12:00:00Z
goal_mode: true
goal_waves: 0
goal_tickets: 0
---
```

**BOARD.md initial:**
```markdown
## DOING

## TODO
- [ ] T-001 Create wiki index: architecture overview
- [ ] T-002 Document module structure
- [ ] T-003 Document API endpoints
- [ ] T-004 Document configuration options
- [ ] T-005 Document UI components

## DONE

## BLOCKED
```

### T-004: Создать saihunt subSaipen
**needs:** T-001, T-002
**Phase:** BUILD → VERIFY → REVIEW

**SubSaipen saihunt — Bug Hunter.**

**Что делает:**
1. Сканирует main project на предмет багов, утечек, ошибок
2. Проверяет: null safety, exception handling, race conditions, resource leaks, UI glitches
3. Каждую находку оформляет как тикет в BOARD.md
4. После проверки категории — кладёт результаты в OUTBOX.md

**Структура subSaipen saihunt:**
```
subs/saihunt/
├── STATE.md
├── BOARD.md
├── LOG.md
└── kitchen/
    ├── OUTBOX.md
    ├── _hunt_null.md
    ├── _hunt_exceptions.md
    ├── _hunt_race.md
    └── _hunt_ui.md
```

**STATE.md initial:**
```yaml
---
phase: PLAN
task: none
next_action: READ main project → scan for bug categories
blocker: none
agent: saihunt
saipen_version: 7
mode: read-only
updated: 2026-07-22T12:00:00Z
goal_mode: true
goal_waves: 0
goal_tickets: 0
---
```

### T-005: Добавить команду `saipen sub` в SAIPEN RFC.md
**needs:** T-001
**Phase:** BUILD → VERIFY → REVIEW

Добавить в SAIPEN RFC.md (boot protocol) новые команды:

```markdown
### SubSaipen Commands
- `saipen sub list` — читает subs/MANIFEST.md, показывает активные subSaipen
- `saipen sub spawn <name>` — создаёт новый subSaipen (структуру, STATE, BOARD)
- `saipen sub collect` — проверяет OUTBOX всех subSaipen
- `saipen sub ack <name> [T-###]` — подтверждает получение OUTBOX
- `saipen sub clean <name>` — удаляет subSaipen
```

### T-006: Интегрировать OUTBOX.Collect в главный workflow
**needs:** T-005
**Phase:** BUILD → VERIFY → REVIEW

Когда главный агент начинает новый тикет или входит в `saipen continue`, он ДОЛЖЕН:

1. Проверить `subs/MANIFEST.md` — есть ли активные subSaipen?
2. Для каждого — проверить `kitchen/OUTBOX.md`
3. Если OUTBOX не пуст — прочитать, создать тикеты на BOARD.md
4. Написать ACK в OUTBOX или `_shared/inbox.md`

## Execution Order

```
T-001 RFC_SUBSAIPEN.md
  ↓
T-002 subs/ structure + MANIFEST.md
  ↓
T-003 saiwiki subSaipen
T-004 saihunt subSaipen       (параллельно с T-003)
  ↓
T-005 saipen sub commands      (после T-001)
  ↓
T-006 OUTBOX.Collect workflow  (после T-005)
```

## Rules for the Executing Agent

1. **Ничего не редактировать в main project** — только в `subs/`
2. Создавать SAIPEN-совместимые STATE/BOARD/LOG для каждого subSaipen
3. Каждый subSaipen — полностью изолирован: свой STATE, свой BOARD, свой LOG
4. OUTBOX.md — единственный канал связи с главным агентом
5. После каждого тикета — VERIFY и REVIEW
6. Не создавать тикеты, которые не описаны в этом плане — сначала план, потом код
7. Файлы в `kitchen/` с префиксом `_` — рабочие черновики, OUTBOX — единственный официальный выход
