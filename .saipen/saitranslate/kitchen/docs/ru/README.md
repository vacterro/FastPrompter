# FastPrompter Wiki

FastPrompter — сверхбыстрый клавиатурный блокнот + рабочая среда для промптов под Windows. Python 3.11+, PyQt6. Персистентность через SQLite WAL. Автономный EXE, собранный Nuitka.

> **Alt+X** вызывает блокнот на 100 ячеек под курсором мыши. Ноль установки, ноль облака, ноль телеметрии. Всё состояние мгновенно сохраняется в локальную БД.

---

## Индекс технической документации

### Основная архитектура
- **[Обзор архитектуры](Architecture-Overview)** — проектирование системы, IPC single-instance, SQLite WAL, синхронизация состояния, подсистемы
- **[Структура модулей](Module-Structure)** — дерево `src/fastprompter/`, зоны ответственности файлов, карта core/ui/utils/watcher
- **[Core API и классы](Core-API-and-Classes)** — FastPrompterState, HotkeyManager, IPCServer, SoundManager, PomodoroEngine, UI-виджеты
- **[Движок Watcher](Watcher-Engine-Architecture)** — подключение CDP, Win32-хуки, инъекция очереди, конечный автомат, лимиты скорости

### Интерфейс и данные
- **[Конфигурация](Configuration)** — схема БД (local_data_v15.db), ключи настроек, движок кастомных тем, зеркала резервных копий
- **[UI-компоненты](UI-Components)** — схема раскладки, разбор панелей (Editor, Silos, Queue, Files, Kanban, Table)
- **[Горячие клавиши](Keyboard-Shortcuts-and-Cheatsheet)** — полный справочник: глобальные, окно, форматирование, watcher, silo, сниппеты

### Руководства и расширяемость
- **[Руководство пользователя](User-Guide)** — рабочие процессы, управление silo, макросы сниппетов, файловые контейнеры, zen-режим, Pomodoro-таймер, скрытие разметки, kanban/table
- **[Устранение неполадок и FAQ](Troubleshooting-and-FAQ)** — логи падений (%TEMP%\\fastprompter_crash.log), очистка процессов, ремонт БД, конфликты горячих клавиш
- **[Разработка плагинов и навыков](Plugin-and-Skill-Development)** — кастомные навыки (skills.py), субагенты SAIPEN, кастомные темы, темы курсоров

### Автоматизация и протокол
- **[Протокол SAIPEN](SAIPEN-Protocol)** — спецификация v7: цикл конечного автомата, журналирование событий, read-only архитектура subSaipen, протокол передачи OUTBOX
- **[Руководство по сборке](Deployment-Guide)** — компиляция Nuitka (tools/build.py), релиз на GitHub (tools/release.py), скрипты в один клик

---

## Проект

- **Репозиторий**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Стек**: Python 3.11+, PyQt6, SQLite WAL, Nuitka ≥4.1.2, pynput
- **Лицензия**: MIT

---

*Собрано с [Протоколом SAIPEN](SAIPEN-Protocol) | [GitHub](https://github.com/vacterro/FastPrompter)*
