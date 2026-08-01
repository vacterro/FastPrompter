# Руководство по разработке плагинов, навыков и расширений

## 1. Кастомные навыки (`core/watcher/skills.py`)

Навыки — обёртки промптов, применяемые при отправке элементов через watcher.

### Определение

```python
# Словарь записи навыка
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review this code:\n\n{text}",
    "description": "Standard code review prompt wrapper"
}
```

### Переменные шаблона
- `{text}` — текст поставленного в очередь элемента
- `{timestamp}` — текущее время
- `{project}` — имя активного проекта

### Применение
Задайте навык по умолчанию в Настройках → Watcher → Default Skill. Переопределите на элемент в диалоге Queue Master.

## 2. Субагенты SAIPEN

Субагенты живут в `.saipen/extensions/subs/<name>/` (не в корневом `subs/` проекта).

```
.saipen/extensions/subs/
├── MANIFEST.md          # активный список подсистем
├── PROTOCOL.md          # правила
├── TEMPLATE/            # шаблон бутстрапа
├── saiwiki/             # субагент-генератор вики
├── saihunt/             # субагент-охотник за багами
└── _shared/inbox.md     # меж-агентная коммуникация
```

### Передача (OUTBOX.md)

```
# OUTBOX

## WIKI-001: Описание
- **status:** ready | draft | blocked | reviewed
- **summary:** однострочное описание находки
- **critical:** true | false
- **details:** полное описание
```

`critical: true` → главный агент немедленно создаёт тикет T-###.
`critical: false` → ставится в очередь `_shared/inbox.md` для следующего раунда планирования.

**Команды:**
- `saipen sub spawn <name>` — создать нового субагента из TEMPLATE
- `saipen sub collect` — собрать все записи OUTBOX
- `saipen sub list` — показать активных субагентов + фазу
- `saipen sub clean <name>` — удалить завершённого субагента

## 3. Кастомные темы

Файл: `data/custom_theme.json`. Загружается, когда тема = Custom.

### Схема

```json
{
  "theme_name": "My Theme",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_editor": "#1b1b1b",
    "fg_text": "#d4d4d4",
    "fg_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78",
    "header_bg": "#252526",
    "button_bg": "#2d2d30",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422"
  }
}
```

**Применение:** Настройки → Тема → Custom. Мгновенный хот-релоад, без перезапуска.

## 4. Темы курсоров (`ui/cursor_theme.py`)

Кастомные наборы курсоров мыши. Ретро-ощущение вычислительной техники.

**Функции:**
- `capture_current_scheme()` — скопировать живой набор курсоров Windows в программу
- `load_bundle()` — вернуть установленный набор курсоров
- `install_to_system(paths)` — установить как схему курсоров Windows по умолчанию
- `build_cursor_map()` — пересобрать карту форм курсоров

**Переключение:** Настройки → Курсоры → Enable custom cursors. При первом включении автоматически захватывается текущий набор Windows.

## 5. Расширяемость движка Watcher

| Модуль | Точка расширения |
|---|---|
| `adapter.py` | Реализуйте ProbeAdapter для кастомного определения цели |
| `cdp.py` | Кастомные CDP-команды для Electron-приложений |
| `win32.py` | Кастомизация Win32-пробы окна |
| `skills.py` | Добавьте кастомные шаблоны навыков промптов |
| `limit_scan.py` | Кастомный кросс-агентный сканер лимитов |
| `sender.py` | Кастомные стратегии инъекции текста |

## 6. Синхронизация silo на диск (T-591)

Односторонний экспорт silo → файловая система. Настройки → Sync mode: Off / Silo (плоский) / Hierarchy (вложенный). Пишет `<root>/<category>/<NN_slug>.md` при сохранении. Никогда не читает обратно, никогда не удаляет. Пропускает неизменённый текст.
