"""Дед — the angry-90s-grandpa voice as a selectable UI language.

An OVERLAY on Russian: this dict only carries the strings worth saying in
дед-voice (tooltips, dialogs, menus, the roomy ones). Anything absent falls
back to normal Russian in translations.py, so the UI never half-breaks.
Tiny buttons stay short on purpose — jokes don't fit in a 40px button.

Keys must match en.py exactly; unknown keys are dropped on load.
"""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # ---- tiny buttons / labels (short, punchy) ----
    'NEW': 'НОВ',
    'Save': 'Сохрань',
    'Copy': 'Копи',
    'Clear': 'Снести',
    'Update': 'Обнови',
    'Cancel': 'Отвали',
    'Close': 'Захлопни',
    'Reset': 'Сбрось',
    'Quit': 'Свалить',
    'Rename': 'Переназвать',
    'Line': 'Линия',
    'Rpl': 'Замн',
    'Rpl All': 'Всё',
    'Replace All': 'Заменить всё',
    'Clear Fmt': 'Снять фмт',

    # ---- day words (header clock) ----
    'Morning': 'Утречко',
    'Day': 'Днём',
    'Evening': 'Вечерок',
    'Night': 'Ночка',

    # ---- placeholders ----
    'Think deeply.': 'Думай башкой, не жопой.',
    'Search...': 'Ищи давай...',
    'Find...': 'Ищи...',
    'Search snippets': 'Рыть по штампам',
    'Replace with...': 'Менять на...',
    'Name:': 'Имя:',
    'New name:': 'Новое имя:',
    'Folder name:': 'Имя папки:',
    'Enter filename (without .txt):': 'Имя файла (без .txt):',
    'Enter snippet number (1-{}):': 'Номер штампа (1-{}):',
    'No files yet': 'Пусто. Кидай сюда барахло.',
    'Paste Silo {}:': 'Вставить банку {}:',
    'Paste Snippet {}:': 'Вставить штамп {}:',

    # ---- dialog titles / confirmations ----
    'Confirm': 'Ну чё',
    'Error': 'Косяк',
    'Success': 'Готово',
    'Saved': 'Схоронил',
    'Tab Limit': 'Потолок полок',
    'Delete Silo': 'Снос банки',
    'Delete Snippet': 'Снос штампа',
    'Delete Tab': 'Снос полки',
    'Overwrite Snippet': 'Катать поверх',
    'Snippet Number': 'Номер штампа',
    'Merge files': 'Слить барахло',
    'Rename Snippet': 'Переназвать штамп',
    'Save Snippet': 'Схоронить штамп',
    'Save Silo': 'Схоронить банку',
    'Backup Silo': 'Бэкап банки',
    'Are you sure you want to delete this silo and its content?':
        'Точно снести банку со всем добром? Потом не вой.',
    'Are you sure you want to delete this snippet?': 'Штамп в утиль? Точно?',
    'Delete this snippet?': 'Штамп — в помойку?',
    'App will restart. Proceed?': 'Прога перезапустится. Погнали?',
    "Nuke '{}' and all snippets?": "Снести '{}' со всеми штампами к чертям?",
    'Maximum of 5 tabs/projects. Remove one first.':
        'Пять полок — потолок. Сначала одну снеси.',
    'Snippet #{} already exists. Overwrite?': 'Штамп #{} уже есть. Катать поверх?',
    'Source and destination are the same file.':
        'Откуда и куда — один и тот же файл, голова.',
    'Clear all custom fonts and reset to defaults?':
        'Снести все свои шрифты и вернуть как было?',
    'Remove all custom fonts from the font selector?':
        'Выкинуть все свои шрифты из списка?',
    "How should '{}' be added?": "Как '{}' пихаем?",
    "Delete from this silo's folder?\n\n{}\n": 'Снести из папки банки?\n\n{}\n',
    'Trash, not delete': 'В помойку, не в костёр',
    'Copy + Clear current silo': 'Копи + снести банку',
    'Save current silo as file in its own folder:':
        'Схоронить банку файлом в её папку:',

    # ---- status / result messages ----
    'Silo successfully saved to:\n{}': 'Банка схоронена сюда:\n{}',
    'Silos exported to:\n{}': 'Банки выгружены сюда:\n{}',
    'Database backed up to:\n{}': 'База схоронена сюда:\n{}',
    'Failed to save file:\n{}': 'Не схоронил файл, зараза:\n{}',
    'Failed to backup:\n{}': 'Бэкап обосрался:\n{}',
    'Failed to export:\n{}': 'Выгрузка обосралась:\n{}',
    'Failed to save backup:\n{}': 'Бэкап не схоронил:\n{}',
    'Failed to restore backup:\n{}': 'Не поднял бэкап:\n{}',
    'Failed to load font: {}': 'Шрифт не подцепил: {}',
    'Loaded: {}': 'Подцепил: {}',
    'Replaced {} occurrences.': 'Заменил {} штук.',
    'clipboard has no text': 'в буфере пусто, чего менять',
    'path copied': 'путь скопирован',

    # ---- header button tooltips ----
    'NEW ({})': 'Новая пустая банка ({})',
    'Save ({})': 'Схоронить/обновить штамп ({})',
    'Bold ({})\nMake selected text bold.': 'Жирный ({})\nЖирни выделенное.',
    'Italic ({})\nMake selected text italic.': 'Курсив ({})\nНакрени выделенное.',
    'Underline ({})\nMake selected text underlined.':
        'Подчерк ({})\nПодчеркни выделенное.',
    'Strikethrough (Ctrl+T)\nCross out selected text.':
        'Зачерк (Ctrl+T)\nПеречеркни к чертям.',
    'Clear Format\nRemove all explicit font styling from text.':
        'Снять формат\nОбдери всю красоту, оставь голый текст.',
    'Home (Home)': 'В начало (Home)',
    'Jump to End\nMove cursor to the bottom of the document.':
        'В конец\nГони курсор в самый низ.',
    'Copy all text (Ctrl+C)\nRight-click: Copy + Close FastPrompter':
        'Скопировать весь текст (Ctrl+C)\nПравой кнопкой: скопировать и захлопнуть',
    'Clear (Ctrl+Shift+C)': 'Снести всё (Ctrl+Shift+C)',
    'Help — every hotkey, gesture and feature (click)':
        'Помощь — все кнопки, жесты и приблуды (тыкни)',
    'Settings\nConfigure hotkeys, theme, fonts, and UI scaling.':
        'Настройки\nКлавиши, тема, шрифты, масштаб — всё тут.',
    'Current time (analog)': 'Время сейчас (со стрелками)',
    'Current Date and Time': 'Дата и время',
    'Line count of the open silo/snippet': 'Сколько строк в открытой банке',
    'Always on Top — keep the window above all others':
        'Поверх всех — окно всегда сверху, не спрячется',
    'Projects — mouse wheel switches tabs': 'Полки — колёсиком переключаешь',
    'Archive Active Snippet or Silo': 'На чердак активную банку/штамп',
    'Toggle Archives': 'Показать/спрятать чердак',
    'Open Trash': 'Открыть помойку',
    'Configure Global Hotkeys (Settings Cog)': 'Настроить глобальные клавиши',
    'Custom Theme Colors (Color Palette)': 'Свои цвета темы',
    'Load a custom .ttf/.otf font file': 'Подцепить свой шрифт .ttf/.otf',
    'Clear all custom fonts from combo (reset to defaults)':
        'Выкинуть свои шрифты, вернуть дефолт',
    'Click sound volume (1-10)': 'Громкость щелчков (1-10)',

    # ---- silo row tooltips / menu ----
    'Pin this silo to top': 'Прибить банку наверх',
    'Unpin this silo': 'Отцепить банку',
    'Pin/Unpin this silo to top': 'Прибить/отцепить банку сверху',
    'Archive this silo': 'Банку на чердак',
    'Mark this silo as done (click again to unmark)':
        'Отметить банку сделанной (тыкни ещё — снимет)',
    'Files: drop/drag/preview assets for this silo':
        'Барахло: кидай, тащи, смотри — для этой банки',
    '📌 Unpin': '📌 Отцепить',
    '📌 Pin to Top': '📌 Прибить сверху',
    '📥 Archive': '📥 На чердак',
    '📁 Files…': '📁 Барахло…',
    '💾 Save text as Snippet': '💾 В штампы его',
    '💾 Save as Snippet #…': '💾 В штамп под номером…',
    '➡ Transfer to Snippet': '➡ Спихнуть в штамп',
    '⬆ Move to Top': '⬆ Наверх',
    '⬇ Move to Bottom': '⬇ Вниз',
    '⬆ Un-nest from Parent': '⬆ Отлепить от мамки',
    '🗑 Delete': '🗑 В помойку',
    '✏ Rename': '✏ Переназвать',

    # ---- settings toggles (emoji kept, words дед) ----
    '🔊 UI Sounds': '🔊 Щелчки',
    '⌨ Typewriter': '⌨ Печатная машинка',
    '🦓 Zebra Stripes': '🦓 Зебра',
    '🔢 Line Numbers': '🔢 Номера строк',
    '🔴 Line Marks': '🔴 Метки на полях',
    '📅 Show Date Widget': '📅 Часы с датой',
    '🕒 Analog Clock': '🕒 Стрелочные часы',
    '⏱ Date Seconds': '⏱ Секунды',
    '🌞 Day Word': '🌞 Слово дня',
    '🔤 Text Month': '🔤 Месяц словом',
    '🗑 Trash Vision': '🗑 Показывать помойку',
    '✅ Silo Ticks': '✅ Галки на банках',
    '➖ Pinned Gap': '➖ Зазор у прибитых',
    '🏠 Silos at Start': '🏠 Банки на старте',
    '👁 Hide on Click-Out': '👁 Прятаться при клике мимо',
    '💾 Auto Backup (.md)': '💾 Автобэкап (.md)',
    '↩ Word Wrap': '↩ Перенос строк',
    '⇕ Double-Space Lists': '⇕ Списки через строку',
    '⌨ Hide Key Hints': '⌨ Прятать подсказки клавиш',
    '↕ Snippet Arrows': '↕ Стрелки у штампов',
    '▶ Sidebar Right': '▶ Панель справа',
    '🪟 Normal Window': '🪟 Обычное окно',
    '🔒 Lock Window': '🔒 Замок окна',
    '📌 Always on Top': '📌 Поверх всех',
    '📉 Tray Icon': '📉 Значок в трее',
    '📋 Ctrl+C Hides': '📋 Ctrl+C прячет',
    '🖱 Open at Cursor': '🖱 Вылазить у мышки',
    '🗂 Open Trash Folder': '🗂 Открыть папку помойки',
    '🧹 Clear': '🧹 Снести',
    '📋 Copy': '📋 Копи',

    # ---- settings labels / sections ----
    'Language:': 'Язык:',
    'Theme:': 'Тема:',
    'Font:': 'Шрифт:',
    'View:': 'Вид:',
    'Volume:': 'Громкость:',
    'Scale': 'Масштаб',
    'Header Fmt:': 'Формат шапки:',
    'Line gaps:': 'Зазоры линии:',
    'UI Gaps:': 'Зазоры UI:',
    'Format:': 'Формат:',
    'Rows:': 'Строк:',
    'Columns:': 'Столбцов:',
    'Window': 'Окно',
    'Editor': 'Редактор',
    'Sounds': 'Звуки',
    'Data': 'Данные',
    'Archive': 'Чердак',
    'Silos': 'Банки',
    'Snippets': 'Штампы',
    'Trash': 'Помойка',
    'Reading': 'Чтение',
}
