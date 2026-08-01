# Протокол SAIPEN v7 и архитектура SubSaipen

## Обзор

SAIPEN (v7) — лёгкий структурированный протокол для персистентного отслеживания задач AI-агентов, управления состоянием, журналирования событий и мульти-агентного делегирования. Ноль дрейфа контекста через длинные сессии благодаря машиночитаемым файлам в `.saipen/`.

---

## 1. Основной протокол

### Структура памяти (`.saipen/`)

```
.saipen/
├── STATE.md         # Фаза, задача, блокер, параметры агента
├── BOARD.md         # Канбан: DOING/TODO/DONE/BLOCKED
├── LOG.md           # Добавляемый только журнал работы (RFC § 1.2)
├── KNOWLEDGE/       # Справочные карточки подсистем
├── kitchen/         # Черновики, промежуточные результаты
├── snapshots/       # Бэкапы STATE/BOARD/LOG с метками времени
└── recovery/        # Архивы восстановления после очистки
```

### Схема STATE.md (YAML frontmatter)

```yaml
---
phase: SCOUT | PLAN | BUILD | VERIFY | REVIEW | DONE | BLOCKED
task: "Описание активной задачи"
next_action: "Немедленный следующий шаг"
blocker: ""  # Причина, если BLOCKED
agent: claude | main | <имя>
saipen_version: 7
saipen_home: "V:\\путь\\к\\saipen"
mode: full | read-only
requires: [filesystem, python, shell, git]
updated: 2026-07-30T12:00:00Z
---
```

### Конечный автомат фаз

1. **SCOUT** — осмотр кодовой базы, проверка зависимостей, чтение логов
2. **PLAN** — создание тикетов на BOARD.md, проектирование
3. **BUILD** — реализация кода/конфигов/документации
4. **VERIFY** — запуск тестов, линтеров, ручных проверок
5. **REVIEW** — ревью диффа, запись в LOG
6. **DONE** — все тикеты завершены
7. **BLOCKED** — застрял, поле blocker объясняет почему

### Журнал событий (LOG.md)

```
- 2026-07-30T12:00:00Z [E-001] [T-057] [agent: main] RUN: fix -> PASS
```

### Ключевые правила
- Один агент пишет в `.saipen/` одновременно (RFC § 1.4)
- Грязное дерево — НОРМАЛЬНО — атрибутируйте перед действием, никогда не откатывайте/не коммитьте незакоммиченную работу другого агента (RFC § 1.5)
- Порядок чекпоинта: LOG → BOARD → STATE (асимметрия, устойчивая к падениям, RFC § 1.5)
- Формат тикетов: только `T-###` (RFC § 1.2)

---

## 2. Архитектура SubSaipen

Изолированные read-only субагенты. Вывод только внутри `.saipen/extensions/subs/<name>/`.

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/
            ├── MANIFEST.md         # Активный список подсистем
            ├── PROTOCOL.md         # Полный суб-протокол
            ├── _shared/inbox.md    # Меж-агентный inbox
            ├── TEMPLATE/           # Шаблон бутстрапа
            ├── saiwiki/            # Генератор вики (фаза DONE)
            └── saihunt/            # Охотник за багами (фаза DONE)
```

### Жизненный цикл
1. **SPAWN** — `saipen sub spawn <name>` копирует TEMPLATE, добавляет в MANIFEST
2. **WORK** — читает главный проект (read-only), производит артефакты в своём kitchen/
3. **SIGNAL** — запись в OUTBOX.md со `status: ready`
4. **COLLECT** — главный агент запускает `saipen sub collect`, создаёт тикеты T-### для критических находок

### Формат OUTBOX

```markdown
# OUTBOX

## WIKI-001: Описание
- **status:** ready | draft | blocked | reviewed
- **summary:** однострочная находка
- **main_project_refs:** [docs/wiki/foo.md]
- **critical:** true | false
- **severity:** P0 | P1 | P2 (опционально)
- **details:** полное описание
```

### Пространство имён ID тикетов

| Префикс | Владелец |
|---|---|
| `SYS-` | Скрестный / протокол |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (фиксер) |
| `<NAME>-` | Любая другая подсистема |

Суб-ID никогда не идут напрямую на главный BOARD.md — всегда обычный `T-###` с оригиналом в описании.

### Команды

| Команда | Действие |
|---|---|
| `saipen sub list` | Показать активные подсистемы + фазу (WARNING при BLOCKED) |
| `saipen sub spawn <name>` | Создать нового субагента |
| `saipen sub collect` | Обработать все записи OUTBOX |
| `saipen sub clean <name>` | Удалить субагента (отказывает при несобранных находках) |
| `saipen sub status <name>` | Просмотр OUTBOX без сбора |
| `<name>` (голое) | Шорткат роли — стать этим субагентом |
| `saipen sub pause <name>` | Заморозить субагента (BLOCKED) без уничтожения состояния |
| `saipen sub resume <name>` | Разморозить субагента |

### Субагент-фиксер (saipython)

Идёт дальше — OUTBOX несёт **протестированный патч** как unified diff. Работа выполняется в собственном песочном `kitchen/pen/` (копия целевого файла). Верифицируется собственной тестовой системой проекта перед пометкой `ready`. Никогда не пишет в главное дерево.

```markdown
## PY-001: Описание
- **status:** ready
- **patch:**
  ```diff
  <unified diff, применяется от корня репозитория>
  ```
- **verified:** pytest PASS (N) / ruff clean / mypy clean
- **base_head:** abc1234
```

---

*FastPrompter Wiki — собрано с [Протоколом SAIPEN](SAIPEN-Protocol) | [GitHub Repo](https://github.com/vacterro/FastPrompter)*
