# Конфигурация и настройки FastPrompter

## Схема БД

SQLite БД: `data/local_data_v15.db` (профиль 1) или `data/local_data_v15_p<ID>.db` (профили >1). Портативная папка `data/` лежит рядом с EXE. Откат к `%LOCALAPPDATA%/FastPrompter/`, если папка exe не перезаписывается.

**Таблицы:**
- `settings` — пары ключ-значение (вся конфигурация приложения)
- `presets` — хранилище сниппетов (категория, слот, имя, содержимое, last_edited)
- `temp_presets_v2` — текстовое содержимое silo по категориям
- `archive_temp_presets_v2` — архивированное содержимое silo по категориям

Конфиг живёт в таблице `settings` как пары ключ-значение. Никаких INI-файлов. Всё хот-релоадится при применении.

## Ключи настроек

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| **Тема и отображение** | | | |
| `theme` | string | `Golden Default` | Тема: Default, Golden Vintage, Golden Default, Vintage Dark, Vintage Classic, Dark 2 (OLED), Dracula, Nord, Solarized Dark, Custom |
| `font_family` | string | `Verdana` | Шрифт редактора (авторезолв в битмап-вариант `_m1`, если установлен) |
| `font_size` | int | 18 | Размер шрифта редактора в пунктах |
| `ui_scale` | float | 0.5 | Масштаб UI (от 0.5 до 1.5) |
| `button_scale` | float | 0.5 | Множитель размера кнопок silo + тулбара |
| `custom_cursors` | bool | True | Оверлей ретро-темы курсоров |
| `code_monospace` | bool | False | Моноширинный шрифт в кодовых блоках (False = шрифт редактора) |
| `code_auto_gutter` | bool | False | Автономера строк в кодовых блоках |
| `hr_visual_line` | bool | True | Рендер `---` как горизонтальной линии вместо текста |
| `live_preview_conceal` | bool | True | Скрывать маркеры `**`, `*`, `~~`, `` ` `` в живом предпросмотре |
| **Горячие клавиши** | | | |
| `global_hotkey` | string | `Alt+X` | Глобальная горячая клавиша вызова |
| `pie_menu_hotkey` | string | `Shift+Alt+X` | Горячая клавиша pie-меню |
| `lock_window_hotkey` | string | `Alt+E` | Переключатель блокировки окна |
| `always_on_top_hotkey` | string | `Alt+S` | Переключатель always-on-top |
| **Поведение** | | | |
| `close_on_focus_loss` | bool | True | Автоскрытие при потере фокуса |
| `always_on_top` | bool | False | Старт с always-on-top |
| `normal_window` | bool | False | Обычный оконный режим (не без рамки) |
| `tray_visible` | bool | True | Показывать иконку в трее |
| `auto_bullet` | bool | True | Автоконвертация тире в буллеты |
| `ctrl_e_center` | bool | True | Центрировать заголовки Ctrl+E |
| `customize_toolbar` | bool | False | Режим переупорядочивания тулбара |
| `snippets_hidden` | bool | True | Скрыть панель сниппетов |
| `bold_hash_titles` | bool | True | Жирным шрифтом заголовок сайдбара ячеек и сниппетов, текст которых начинается с `#` (T-739) |
| `sidebar_right` | bool | True | Сайдбар справа |
| `show_token_count` | bool | False | Оценка токенов (количество пилюль) (T-614) |
| `sync_mode` | string | Off | Односторонняя синхронизация silo на диск: Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Включить страницу пресетов окна Ctrl+Q (T-608) |
| **Звук** | | | |
| `sound_enabled` | bool | True | Мастер-переключатель звука |
| `sound_ui` | bool | True | Звуки кликов UI |
| `sound_typewriter` | bool | False | Звуки клавиш пишущей машинки |
| `sound_volume` | int (0-10) | 1 | Общая громкость звука |
| **Часы и дата** | | | |
| `date_seconds` | bool | True | Показывать секунды в часах |
| `date_daypart` | bool | True | Метка утро/день/вечер/ночь |
| `date_text_month` | bool | True | Текстовый месяц (Jan/Feb) |
| `date_ampm` | bool | False | Формат 12ч AM/PM |
| `date_emoji` | bool | False | Эмодзи времени суток (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | Показывать дату в заголовке |
| **Курсор** | | | |
| `cursor_blink_ms` | int | 1000 | Скорость мигания курсора мс (0 = без мигания, T-606) |
| **Таймеры** | | | |
| `timer_show_minutes` | bool | True | Держать поле минут в отображении таймера (T-613) |
| **Раскладка окна** | | | |
| `numbox_per_row` | int | 10 | Номера-боксы в ряд в сетке (T-612) |
| `numbox_btn_size` | int | 24 | Размер кнопки номера-бокса в px (T-612) |
| **Прочее** | | | |
| `language` | string | EN | Язык UI (33 локали) |
| `hover_line_color` | string | `#0059ff` | Цвет подсветки строки (auto = акцент темы) |
| `portable_backup_enabled` | bool | True | Авто .bak при запуске |
| `watcher_skill` | string | (пусто) | Навык по умолчанию для элементов очереди watcher |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Порядок и имена вкладок категорий |
| `hidden_categories` | JSON list | [] | Скрытые категории (видны в менеджере проектов) |
| `timers` | JSON | [] | Сохранённые определения обратного отсчёта |
| `productivity_timer` | JSON | — | Состояние Pomodoro-таймера |
| `watcher_queues` | JSON | `{}` | Очереди промптов по silo |
| `toolbar_order` | string | (пусто) | Токены порядка кнопок кастомного тулбара |
| `window_presets` | JSON | [] | Сохранённые пресеты геометрии окна |
| `silo_gap_height` | int | 12 | Высота пробела-разделителя в сайдбаре, px |
| `silo_ticks_enabled` | bool | True | Показывать кнопки галочек на silo |
| `silo_view_state_all` | JSON dict | `{}` | Состояние курсора/скролла/сворачивания по silo |

## Раскладка файловой системы

```
data/
├── local_data_v15.db           # Основная SQLite БД (профиль 1)
├── local_data_v15.db.bak       # Дросселированный бэкап (мин. интервал 60 с)
├── local_data_v15.db-wal       # WAL журнал упреждающей записи
├── local_data_v15.db-shm       # WAL разделяемая память
├── local_data_v15_p2.db        # БД профиля 2
├── silo_files/                 # Вложения файловых контейнеров
│   ├── Code/                   # Папка категории
│   │   ├── 0/                  # Файлы слота silo 0
│   │   └── 1/                  # Файлы слота silo 1
│   └── Text/
├── _trash/                     # Мягко удалённые silo + файлы
│   └── 2026-07-22_153022_Silo0/# Запись корзины с меткой времени
└── custom_theme.json           # Пользовательская цветовая палитра
```

**Ежедневное зеркало:** `%USERPROFILE%/Documents/.fastprompter/` — метки времени, silo/архив/сниппеты по проектам как плоские .md

**Хранилище undo:** `data/data_undo_stack.json` + `data/data_redo_stack.json` (автокомпактируется, лимит 20MB)

## Кастомные темы

`data/custom_theme.json` загружается, когда тема = Custom.

**Цветовые токены:** `bg_main`, `bg_surface`, `bg_editor`, `fg_text`, `fg_accent`, `text_primary`, `text_accent`, `border`, `selection`, `header_bg`, `accent`, `button_bg` и т.д.

Применение через Настройки → Тема или Mini Settings (Alt+`). Мгновенный хот-релоад, без перезапуска.
