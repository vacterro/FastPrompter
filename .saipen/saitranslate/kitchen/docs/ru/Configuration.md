# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings are stored in the SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

| Настройка ключа | Тип | По умолчанию | Описание |
|---|---|---|---|
| `тема` | строка | `"По умолчанию"` | Активная визуальная тема («По умолчанию», «Янтарный», «OLED», «Win95», «Роза», «Пользовательский») |
| `размер_шрифта` | целое число | `11` | Размер шрифта основного редактора в пунктах |
| `ui_scale` | плавать | `"1.0"` | Общий коэффициент масштабирования пользовательского интерфейса (от 0,5 до 1,5) |
| `button_scale` | плавать | `"1.0"` | Множитель размера кнопок бункера и панели инструментов |
| `global_hotkey` | строка | `"Alt+X"` | Основная горячая клавиша для отображения/скрытия окна приложения |
| `pie_menu_hotkey` | строка | `"Shift+Alt+X"` | Горячая клавиша для вызова кругового меню |
| `lock_window_hotkey` | строка | `"Alt+S"` | Горячая клавиша для переключения блокировки положения окна |
| `always_on_top_hotkey` | строка | `"Alt+E"` | Горячая клавиша для переключения режима окна Always-On-Top |
| `close_on_focus_loss` | логическое | `"Правда"` | Автоматически скрывать окно при потере фокуса |
| `ctrl_c_closes` | логическое | `"Правда"` | Закрыть/скрыть окно после нажатия `Ctrl+C` в режиме фрагмента |
| `sound_ui` | логическое | `"Ложь"` | Включить звуковые эффекты при нажатии кнопок пользовательского интерфейса |
| `звуковая_пишущая машинка` | логическое | `"Ложь"` | Включить звуковые эффекты клавиш пишущей машинки |
| `sound_volume` | целое число | `"5"` | Уровень громкости звука (от 0 до 10) |
| `portable_backup_enabled` | логическое | `"Правда"` | Автоматическое создание файла базы данных `.bak` при запуске |
| `язык` | строка | `"RU"` | Язык интерфейса (`EN`, `RU`, `UK`, `DE`, `FR`, `ES`, `IT`, `PT`, `NL`, `PL`, `SV`, `DA`, `FI`, `NO`, `JA`, `ZH`, `KO`, `TH`, `VI`, `AR`, `HE`, `ET`, `DED`) |
| `sidebar_right` | логическое | `"Ложь"` | Разместите боковую панель бункера в правой части редактора |
| `code_auto_gutter` | логическое | `"Ложь"` | Автоматически отображать номера строк в блоках кода редактора |
| `cats_order` | Список JSON | `["Код","Текст","Разное"]` | Индивидуальный порядок вкладок категорий проектов |

---

## File System & Storage Directory Structure

FastPrompter хранит все пользовательские данные в автономном каталоге `data/` рядом с исполняемым файлом, обеспечивая 100% переносимость выполнения.

```
data/
├── fastprompter.db             # Main SQLite database (Default profile)
├── fastprompter.db.bak         # Startup backup SQLite database
├── fastprompter_p2.db          # Profile 2 SQLite database
├── silo_files/                 # File Container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 attachment directory
│   │   └── 1/                  # Silo slot 1 attachment directory
│   └── Text/
├── _trash/                     # Soft-deleted silos and files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash archive
└── custom_theme.json           # User-defined custom color palette (if enabled)
```

---

## Custom Themes & Color Editing
When `theme` is set to `"Custom"`, FastPrompter reads color preferences from `custom_theme.json` or state overrides.

### Supported Theme Color Tokens
- `bg_main`: Primary window and panel background color
- `bg_editor`: Editor canvas background color
- `fg_text`: Primary text color
- `border`: Window border and divider line color
- `accent`: Active selection, focus ring, and pin highlight color
- `header_bg`: Header bar and title background color
