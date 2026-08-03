# FastPrompter Core API и справочник классов

## Core-классы (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

Потокобезопасная модель данных SQLite. Центральный хаб состояния — все silo, сниппеты, настройки, темы, очереди проходят через него.

**Методы:**
- `__init__(profile_id=1)` — открыть SQLite-соединение, режим WAL, загрузить кэшированные настройки
- `init_db()` — создать/обновить схему (presets, settings, temp_presets_v2, archive_temp_presets_v2), выполнить .bak-бэкап при запуске
- `switch_profile(new_profile_id)` — закрыть текущую БД, переключить путь, перезагрузить
- `save_data_to_db(text, ui_settings, force)` — атомарный сброс грязного состояния
- `mark_dirty()` — пометить состояние как требующее сохранения (асинхронно через автосохранение)
- `reset_data()` — переинициализация дефолтов в памяти

**Модель данных:** Единый `self.data` dict. Хранилища по категориям алиасятся: `temp_presets` → `temp_presets_all[active_cat]`, `silo_colors` → `silo_colors_all[active_cat]` и т.д. Все ключи `_all` авто-мигрируются при первом обращении.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

Потоковый pynput-слушатель клавиатуры для системных горячих клавиш.

**Методы:**
- `start()` — запустить поток-слушатель pynput
- `stop()` — остановить слушатель
- `update_hotkeys(hk_dict)` — перерегистрировать карту горячих клавиш

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32 WH_KEYBOARD_LL хук. Перехватывает физические VK-коды — независимо от раскладки. Работает кросс-раскладочно (QWERTY/JCUKEN/AZERTY). Используется для диспетчеризации layout_shortcuts.py.

---

### `IpcServer` (`core/ipc_server.py`)

QLocalServer на именованном канале `FastPrompter_Server_V15`. Авторизация UUID-токеном через `%TEMP%/fastprompter_ipc.token`.

**Методы:**
- `setup()` — начать прослушивание (восстанавливает устаревшие имена сокетов через removeServer)
- `close()` — остановить сервер
- `_handle_command()` — обработать команду SHOW от второго экземпляра

**Хелпер:**
- `try_connect_to_server()` — проверить запущенный экземпляр (возвращает QLocalSocket или None)

---

### `SoundManager` (`core/sound_manager.py`)

Воспроизведение WAV для кликов UI, клавиш пишущей машинки, будильников таймеров.

**Методы:**
- `play_ui_click()`, `play_tick_sound()`, `play_typewriter()`, `play_sound(name)` — диспетчеризация аудио
- Громкость управляется настройкой `sound_volume` (0-10)

---

### `PomodoroEngine` (`core/pomodoro.py`)

Конечный автомат работы/перерыва с настраиваемыми интервалами.

**Константы:** `PHASE_WORK`, `PHASE_BREAK`

**Методы:**
- `start_work()`, `start_break()`, `pause()`, `reset()` — жизненный цикл
- `tick(elapsed)` — продвинуть таймер, отдать переходы фаз
- `describe()` — человекочитаемая строка состояния
- `from_dict(data)` / `to_dict()` — JSON-сериализация

---

### `Timer` и `TimerManager` (`core/timers.py`)

Универсальный таймер обратного отсчёта. Цветовая срочность, звук при срабатывании, отложенный звонок.

**Атрибуты Timer:** `name`, `description`, `target` (datetime), `sound`, `volume`, `color_mode`, `color`

**Методы:**
- `remaining()` — секунды до цели
- `snooze(minutes)` — сдвинуть цель вперёд
- `display_color()` — цвет срочности (зелёный/жёлтый/красный)
- `collect_due(timers)` — вернуть список просроченных таймеров
- `next_due(timers)` — ближайший таймер
- `save_timers(data)` / `load_timers(data)` — сериализация

---

### `DurationParser` (`core/duration.py`)

Разбор человекочитаемой длительности.

- `parse_duration(text)` — «2h 30m» → секунды
- `format_remaining(seconds, short=False, minutes=False)` — «2h 30m» → «2h» или «4d 11h 05m»
- `format_duration(seconds)` — полная строка формата

---

### `HashtagIndex` (`core/hashtags.py`)

Кросс-silo извлечение и поиск хэштегов.

- `extract_tags(text)` — вернуть набор строк `#tag`
- `index_silo(cat, slot, text)` — тег → индекс silo
- `search(tag)` — все silo с тегом по категориям

---

### `DividerEngine` (`core/ctrlw.py`)

Вставка шаблонов Ctrl+W / Alt+W.

- `insert_divider(editor, template, upward)` — вставить горизонтальную линию, убрать дубли буллетов при разделении
- `simulate(editor, upward)` — предпросмотр позиции вставки

---

### `HeaderFormatter` (`core/header.py`)

Вставка заголовка Ctrl+E. Настраивается: линия-правило, отступ, буллет, выравнивание, метка времени.

- `format_header(editor, config)` — отформатировать текущую строку как заголовок

---

### Модули движка Watcher (`core/watcher/`)

| Модуль | Роль |
|---|---|
| `engine.py` | Конечный автомат: DISARMED → ARMED → WATCHING → SENDING |
| `cdp.py` | Подключение Chrome CDP + evaluate + верификация read-back (Electron-приложения) |
| `win32.py` | Win32-проба окна — foreground, каретка, определение фокуса |
| `probes.py` | Комбинаторы состояний мульти-проб + объединённая матрица |
| `queue.py` | QueueItem, SendIntent, закрепление, ключ очереди, персистентность |
| `sender.py` | Инъекция нажатий CDP + Win32 с верификацией read-back |
| `skills.py` | Обёртки навыков промптов — преобразования префиксов/шаблонов |
| `adapter.py` | Абстрактный интерфейс адаптера проб |
| `limit_scan.py` | Кросс-агентный сканер лимитов + автосоздание таймеров |

---

## UI-компоненты (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow. Композиция миксинов (порядок объявления):
1. FormattingMixin — шорткаты markdown-форматирования
2. HotkeyMixin — интерфейс привязки горячих клавиш
3. ScalingMixin — масштабирование DPI/шрифта
4. SearchMixin — строка поиска по silo
5. SendSelectionMixin — отправка текста через watcher
6. SnippetOpsMixin — операции с silo (корзина, дубль, порядок)
7. ThemeMixin — таблица стилей приложения, винтажные пресеты
8. TrayMixin — иконка в трее + меню
9. WatcherMixin — интеграция движка watcher
10. WindowMixin — окно без рамки + привязка

**Ключевые свойства:** `_font_size`, `_font_family`, `_ui_scale`, `_button_scale`, `_sidebar_right`, `_always_on_top`, `_normal_window`

**Ключевые методы:**
- `init_ui()` — построить окно, тулбар заголовка, сплиттер, редактор, сайдбар, статус-бар
- `setup_single_instance_server()` — инициализация IPC
- `register_all_hotkeys()` — привязать pynput + QShortcut
- `apply_font()` / `apply_theme()` — каскадное применение шрифта/темы
- `place_window()` — восстановить сохранённую геометрию или применить дефолтную привязку
- `_switch_to_slot(slot, initial)` — загрузить silo в редактор, сохранить состояние курсора
- `capture_silo_state()` / `restore_silo_state()` — персистентность курсора/скролла/сворачивания/тепла по silo

---

### `VaultTextEdit` (`ui/editor.py`)

Расширенный QPlainTextEdit. Холст markdown-редактирования.

**Возможности:**
- MarkdownHighlighter — живая подсветка синтаксиса
- LineNumberArea — гуттер: номера строк + стрелки сворачивания (▾) + заметки на полях
- `fold_header(block_num)` / `unfold_header(block_num)` — сворачивание секций
- `queue_current_line()` — закрепить элемент watcher за блоком
- `set_queue_anchor(block, id)` — якорение строки очереди
- `collect_line_marks()` / `apply_line_marks()` — персистентность заметок по строкам
- `collect_line_heat()` / `apply_line_heat()` — тепловая карта давности
- `block_for_queue_item(id)` — найти блок по якорю очереди
- `toggle_checkbox()` — `- [ ]` ↔ `- [x]`
- `toggle_hide_markup(checked)` — скрыть маркеры ** * ~~ ` (T-603)
- Пилюли изображений — `![alt](url)` → кликабельная кнопка 150px

---

### `SnippetPanel` (ui/snippet_panel.py)

Список silo в сайдбаре + кнопки F1-F10.

**Классы:**
- `SnippetWidget` — панель сайдбара: вкладки категорий + список silo
- `DraggableSiloButton` — отдельная кнопка silo (пин, галочка, цвет, иконка файла, перетаскивание)
- `WheelPager` — синхронизированный со скроллом пейджер списка silo
- `DropVerticalWidget` — зона сброса для иерархического вложения

**Возможности:**
- До 100 silo на вкладку
- Пины, галочки, тепловая карта давности, иерархия (перетаскивание для вложения)
- Пробелы сайдбара — пользовательские полосы-разделители (Ctrl+перетаскивание)
- Мультивыбор — Shift=диапазон, Ctrl=переключение, пакетные удаление/сохранение/очистка
- Режим номеров-боксов — переключатель проектов как ряд нумерованных кнопок (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

Файловый ящик silo. Открывается под редактором.

- `load_files(cat, slot)` — прочитать содержимое папки
- `add_files(paths)` — скопировать внешние файлы в папку silo
- `apply_template(name)` — создать структуру папок (IN/OUT/DOCS/Assets/Drafts)
- Превью изображений, режим ссылок, drag-and-drop
- Бэкап silo — Ctrl+клик 📁 экспортирует текст silo

---

### `SiloTable` (`ui/silo_table.py`)

Построитель чисто-текстовых markdown-таблиц. Без Qt-таблиц — работает на обычном markdown.

- Tab/Shift+Tab: обход ячеек; Tab с последней → новая строка
- Enter: новая строка (не разбиение)
- Редактирование ячеек через инлайн-markdown

---

### `SiloKanban` (`ui/silo_kanban.py`)

Чисто-текстовая markdown-канбан-доска. Карточки — элементы markdown-списка.

- Alt+↑/↓: переместить карточку вверх/вниз
- Alt+←/→: переместить карточку в соседнюю колонку
- Enter на пустой строке доски: новая карточка
- Клик по чекбоксу: переключить выполнение

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)

Визуальный выбор зон экрана. 7 пресетов раскладки (TL, TR, BL, BR, Center, Full, Cursor). Клик по зоне — привязка.

---

### `WindowPresetsDialog` (`ui/window_presets_dialog.py`)

Пользовательские пресеты позиций окна. До 10 сохранённых геометрий как долей экрана.

- Сохранить текущую геометрию, переименовать, переупорядочить, перезахватить
- Применение со страницы пикера Ctrl+Q
- Сохранение долей по мониторам (переживает смену монитора)

---

### `TimerToast` (`ui/timer_toast.py`)

Плавающее уведомление для будильников таймеров. 3D-фаски Win95, цвета темы, кнопка отложенного звонка.

### `ToolbarReorder` (`ui/toolbar_reorder.py`)

Настройка тулбара drag-and-drop. Видимые виджеты-зазоры. Кнопка сброса.

### `Overflow Menu` (`main.py`)

Когда заголовок < 700px: скрытые кнопки собираются в » popup. Любое форматирование, навигация, инструмент остаётся доступным.

### `EditGuard` (`ui/edit_guard.py`)

Контекстный менеджер: `with edit_block(widget): ...` оборачивает begin/endEditBlock. Предотвращает зависание Qt от незавершённых операций редактирования.
