# -*- coding: utf-8 -*-
"""Generate complete Ukrainian translation file."""

import ast

def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'TRANSLATIONS':
                    if isinstance(node.value, ast.Dict):
                        result = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            key = k.value if isinstance(k, ast.Constant) else (k.s if isinstance(k, ast.Str) else None)
                            val = v.value if isinstance(v, ast.Constant) else (v.s if isinstance(v, ast.Str) else None)
                            if key is not None and val is not None:
                                result[key] = val
                        return result
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == 'TRANSLATIONS':
                if isinstance(node.value, ast.Dict):
                    result = {}
                    for k, v in zip(node.value.keys, node.value.values):
                        key = k.value if isinstance(k, ast.Constant) else (k.s if isinstance(k, ast.Str) else None)
                        val = v.value if isinstance(v, ast.Constant) else (v.s if isinstance(v, ast.Str) else None)
                        if key is not None and val is not None:
                            result[key] = val
                    return result
    return None

en_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\en.py')
ukr_d = parse_file(r'V:\___VAC\__K\__CODE\_PY\_FastPrompter\src\fastprompter\core\i18n\ukr.py')

missing_keys = [k for k in en_d if k not in ukr_d]

# Ukrainian translations for all missing keys (198 total)
new_ukr = {
    '**__{text}__** ({time})': '**__{text}__** ({time})',
    '--- APP HOTKEYS (only when window active) ---': '--- КЛАВІШІ ДОДАТКУ (лише коли вікно активне) ---',
    '--- GLOBAL HOTKEYS (work anywhere) ---': '--- ГЛОБАЛЬНІ КЛАВІШІ (працюють всюди) ---',
    '50&ndash;150% whole-UI scaling with readable minimums': '50&ndash;150% масштабування UI з читабельними мінімумами',
    'A grid of drop zones appear: insert as text, link in text, copy to silo Files, or link in silo Files': 'З\'являється сітка зон: вставити як текст, посилання в тексті, копіювати у Файли сила або посилання у Файлах сила',
    'Add .url links instead of copies': 'Додавати .url посилання замість копій',
    'Add Link to Files\u2026': 'Додати посилання у Файли\u2026',
    'Add dropped file': 'Додати перетягнутий файл',
    'All Files (*.*)': 'Усі файли (*.*)',
    'Always on Top \u2014 keep the window above all others': 'Поверх усіх вікон \u2014 тримати вікно над іншими',
    'App will restart. Proceed?': 'Додаток перезапуститься. Продовжити?',
    'Are you sure you want to delete this silo and its content?': 'Ви впевнені, що хочете видалити це сило та його вміст?',
    'Are you sure you want to delete this snippet?': 'Ви впевнені, що хочете видалити цей снипет?',
    'Auto-Bullet (Right-Click): {}\nLeft-Click: Convert selected lines between dashes and bullets.': 'Авто-буліт (Правий клік): {}\nЛівий клік: Перетворити виділені рядки між дефісами та маркерами.',
    'Auto-Bullet:': 'Авто-буліт:',
    'Backup & Export Settings': 'Резервне копіювання та експорт налаштувань',
    'Backup Database (.db)': 'Резервна копія БД (.db)',
    'Backup Full Database': 'Повна резервна копія БД',
    'Backup Silo': 'Резервне копіювання сила',
    'Bold / Italic / Underline': 'Жирний / Курсив / Підкреслений',
    'Bottom Left Zone': 'Нижня ліва зона',
    'Bottom Right Zone': 'Нижня права зона',
    'Build Template': 'Шаблон структури',
    'Build Template Folders': 'Створити папки за шаблоном',
    'Clear Formatting': 'Очистити форматування',
    'Clear all custom fonts and reset to defaults?': 'Очистити всі користувацькі шрифти та скинути до стандартних?',
    'Click sound volume (1-10)': 'Гучність звуку кліків (1-10)',
    'Clipboard \u2192 File\tCtrl+V': 'Буфер обміну \u2192 Файл\tCtrl+V',
    'Clip\u2192File\nSave the clipboard text into this folder as a .txt file': 'Буфер\u2192Файл\nЗберегти текст з буфера в цю папку як .txt файл',
    'Close search bar; press again to hide &amp; save': 'Закрити пошук; натисніть знову, щоб сховати та зберегти',
    'Collapse / expand its children': 'Згорнути / розгорнути дочірні',
    'Copy + Clear current silo': 'Копіювати + очистити поточне сило',
    'Copy Path\tCtrl+Shift+C': 'Копіювати шлях\tCtrl+Shift+C',
    'Copy that code block to the clipboard': 'Копіювати цей блок коду в буфер',
    'Create these folders in the current silo': 'Створити ці папки в поточному силі',
    'Creates an exact copy of the local_data_v15.db file containing all settings, silos, and snippets.': 'Створює точну копію local_data_v15.db з усіма налаштуваннями, сілами та снипетами.',
    'Ctrl+Alt+Shift+Q : Quit Application Completely': 'Ctrl+Alt+Shift+Q : Повний вихід з додатку',
    'Ctrl+D : Toggle Focus Mode': 'Ctrl+D : Режим фокусу',
    'Ctrl+F : Find Text': 'Ctrl+F : Знайти текст',
    'Ctrl+H : Replace Text': 'Ctrl+H : Заміна тексту',
    'Ctrl+N : New Empty Snippet': 'Ctrl+N : Новий порожній снипет',
    'Ctrl+Q : Cycle Snap Corners (move across screens)': 'Ctrl+Q : Цикл кутів (переміщення між екранами)',
    'Ctrl+S : Save Snippet': 'Ctrl+S : Зберегти снипет',
    'Ctrl+Shift+S : Export/Save Silo to File': 'Ctrl+Shift+S : Експорт/Зберегти сило у файл',
    'Ctrl+Z : Undo Text Change': 'Ctrl+Z : Скасувати зміну тексту',
    'Customize Drop Zones': 'Налаштувати зони скидання',
    'Cycle Snap Corners (move across screens)': 'Цикл кутів (переміщення між екранами)',
    'Database backed up to:\n{}': 'БД збережено в:\n{}',
    'Delete Silo': 'Видалити сило',
    'Delete Snippet': 'Видалити снипет',
    'Delete files': 'Видалити файли',
    "Delete from this silo's folder?\n\n{}\n": "Видалити з папки цього сила?\n\n{}\n",
    'Delete this snippet?': 'Видалити цей снипет?',
    'Delete\u2026\tDel': 'Видалити\u2026\tDel',
    'Drop Zones': 'Зони скидання',
    'Drop files here \u2014 copied into a plain folder you own. ': 'Кидайте файли сюди \u2014 копіюються у звичайну папку. ',
    'Drop files here \u2014 copied into a plain folder you own. Hold Alt while dropping to add links instead of copies.': 'Кидайте файли сюди \u2014 копіюються у папку. Утримуйте Alt, щоб додати посилання замість копій.',
    'Enter filename (without .txt):': 'Введіть ім\'я файлу (без .txt):',
    'Enter snippet number (1-{}):': 'Введіть номер снипета (1-{}):',
    'Error': 'Помилка',
    'Esc : Hide Window & Auto-save': 'Esc : Сховати вікно та автозберегти',
    'Expand All Folds': 'Розгорнути всі згини',
    'Export All Silos': 'Експортувати всі сіла',
    'Export All...\nCopy every file here to a folder you pick': 'Експорт...\nСкопіювати всі файли в обрану папку',
    'Export Silos & Text': 'Експорт сіл та тексту',
    'Export all Silo contents to readable text formats.': 'Експортувати всі сили у текстові формати.',
    'Export all files to\u2026': 'Експортувати всі файли в\u2026',
    'Export the current silo to a .txt/.md file': 'Експортувати поточне сило у .txt/.md файл',
    'Export to\u2026': 'Експортувати в\u2026',
    'Export/Save Silo to File': 'Експорт/Зберегти сило у файл',
    'F1 - F10 : Execute Snippet 1-10': 'F1 - F10 : Виконати снипет 1-10',
    'Failed to backup:\n{}': 'Помилка резервування:\n{}',
    'Failed to export:\n{}': 'Помилка експорту:\n{}',
    'Failed to load font: {}': 'Помилка завантаження шрифту: {}',
    'Failed to restore backup:\n{}': 'Помилка відновлення:\n{}',
    'Failed to save backup:\n{}': 'Помилка збереження резервної копії:\n{}',
    'Failed to save file:\n{}': 'Помилка збереження файлу:\n{}',
    'Files Folder...': 'Папка файлів...',
    'Files \u2014 {}': 'Файли \u2014 {}',
    'Files: drop/drag/preview assets for this silo\n\n{}': 'Файли: кидайте/перетягуйте/переглядайте\n\n{}',
    'Files\u2014asset drawer for the active silo (drop in / drag out /\npreview / export; plain folder in data/files)\n\n': 'Файли\u2014сховище активного сила (кидайте/перетягуйте/\nпереглядайте/експортуйте; папка в data/files)\n\n',
    'Find / Find &amp; Replace': 'Пошук / Пошук та заміна',
    'Fine-tune the UI scale': 'Точне налаштування масштабу UI',
    'Flip pages': 'Перегортання сторінок',
    'Fold (collapse) the section; right-click editor &rarr; Expand All Folds': 'Згорнути секцію; правий клік редактора &rarr; Розгорнути все',
    'Folder Tpl:': 'Шаблон папок:',
    'Folder template (e.g. src, docs, assets)': 'Шаблон папок (напр. src, docs, assets)',
    'Font loaded but no font families found.': 'Шрифт завантажено, але сімейства не знайдено.',
    'Format:': 'Формат:',
    'Header the line: # + bold + underline + timestamp, then jump 2 lines down onto a fresh &bull; bullet': 'Оформити рядок: # + жирний + підкреслений + час, потім на 2 рядки вниз на новий &bull; маркер',
    "How should '{}' be added?": "Як додати '{}'?",
    "Import Files...\nCopy files into this silo's folder\n(or just drop files anywhere on this window)": "Імпорт файлів...\nСкопіювати файли в папку цього сила\n(або перетягніть файли на це вікно)",
    'Import Files\u2026': 'Імпорт файлів\u2026',
    "Import Folder...\nCopy an entire folder into this silo's folder": "Імпорт папки...\nСкопіювати цілу папку в папку цього сила",
    'Import Folder\u2026': 'Імпорт папки\u2026',
    'Insert Divider Line\tCtrl+W': 'Вставити розділювач\tCtrl+W',
    'Insert a spaced --- divider and start a fresh bullet': 'Вставити --- розділювач і почати новий маркер',
    'Jump to silo 1&ndash;10': 'Перейти до сила 1&ndash;10',
    'Last Edited < 1 day': 'Редаговано < 1 дня',
    'Last Edited < 1 hr': 'Редаговано < 1 год',
    'Last Edited < 1 min': 'Редаговано < 1 хв',
    'Last Edited < 49 days': 'Редаговано < 49 днів',
    'Link to files (no copy)': 'Посилання на файли (без копії)',
    'Loaded: {}': 'Завантажено: {}',
    'Lock / unlock window size & position': 'Блокувати/розблокувати розмір та положення вікна',
    'Mark it done \u2014 the tick stays until clicked again': 'Позначити виконаним \u2014 позначка до повторного кліку',
    'Markdown Files (*.md)': 'Markdown файли (*.md)',
    'Maximum of 5 tabs/projects. Remove one first.': 'Максимум 5 вкладок/проектів. Видаліть одну.',
    'Merge files': 'Об\'єднати файли',
    'Move it to the trash (text + files land in data/files/_trash)': 'Перемістити в кошик (текст+файли в data/files/_trash)',
    'Name:': 'Ім\'я:',
    'Nest it as a child (1 level; its files can merge into the parent)': 'Вкласти як дочірнє (1 рівень; файли об\'єднаються з батьком)',
    'New Folder\tCtrl+N': 'Нова папка\tCtrl+N',
    'New empty silo at the top (max 5 blanks)': 'Нове порожнє сило зверху (макс. 5)',
    "Nuke '{}' and all snippets?": "Знищити '{}' та всі снипети?",
    'OFF': 'ВИМК',
    'ON': 'УВІМК',
    'Open\tEnter': 'Відкрити\tEnter',
    "Open Folder\nOpen this silo's folder in Explorer": "Відкрити папку\nВідкрити папку цього сила в провіднику",
    'Open with the cursor at start / end': 'Відкривати з курсором на початку/в кінці',
    'Overwrite Snippet': 'Перезаписати снипет',
    'Paste snippet 1&ndash;10 into the active app': 'Вставити снипет 1&ndash;10 в активний додаток',
    'Paste snippet 1&ndash;10 into the editor': 'Вставити снипет 1&ndash;10 в редактор',
    'Previous / next silo': 'Попереднє / наступне сило',
    'Quick List pie menu at the cursor': 'Пиріг-меню швидкого списку біля курсора',
    'Quit completely': 'Повний вихід',
    'Remove all custom fonts from the font selector?': 'Видалити всі користувацькі шрифти зі списку?',
    'Rename Snippet': 'Перейменувати снипет',
    'Rename\u2026\tF2': 'Перейменувати\u2026\tF2',
    'Reorder \u2014 dragging a child out promotes it back to top level': 'Перевпорядкування \u2014 перетягування дочірнього піднімає на верхній рівень',
    'Replace with...': 'Замінити на...',
    'Replaced {} occurrences.': 'Замінено {} входжень.',
    'SQLite next to the app; daily Markdown backups in Documents; crash log next to the EXE': 'SQLite поруч з додатком; щоденні Markdown бекапи в Documents; лог помилок біля EXE',
    'Save && Apply': 'Зберегти && Застосувати',
    'Save Clipboard': 'Зберегти буфер обміну',
    'Save Snippet': 'Зберегти снипет',
    'Save current silo as file in its own folder:': 'Зберегти сило як файл у його папці:',
    'Save text as snippet / update the edited snippet': 'Зберегти як снипет / оновити редагований',
    'Select Export Directory': 'Виберіть каталог експорту',
    'Select previous / next silo': 'Вибрати попереднє / наступне сило',
    'Settings &rarr; Header Fmt: {text}, {time}, {state} (Morning/Day/Evening/Night) \u2014 bold markers are yours to keep or drop': 'Налаштування &rarr; Формат: {text}, {time}, {state} (Ранок/День/Вечір/Ніч) \u2014 маркери можна лишити або прибрати',
    'Settings &rarr; Header Fmt: {{text}}, {{time}}, {{state}} (Morning/Day/Evening/Night) \u2014 bold markers are yours to keep or drop': 'Налаштування &rarr; Формат: {{text}}, {{time}}, {{state}} (Ранок/День/Вечір/Ніч) \u2014 маркери можна лишити або прибрати',
    'Show / hide FastPrompter from anywhere': 'Показати/сховати FastPrompter звідки завгодно',
    'Show / hide the line-number gutter\n(click the gutter to place colored margin marks)': 'Показати/сховати номери рядків\n(клікніть на поля для кольорових позначок)',
    'Show window + toggle the sidebar': 'Показати вікно + перемкнути панель',
    'Silo Gap Height': 'Висота проміжків сіл',
    'Silo successfully saved to:\n{}': 'Сило збережено в:\n{}',
    'Silos exported to:\n{}': 'Сіла експортовано в:\n{}',
    'Snap the window through screen corners': 'Прив\'язка вікна до кутів екрана',
    'Snippet #{} already exists. Overwrite?': 'Снипет #{} вже існує. Перезаписати?',
    'Snippet Number': 'Номер снипета',
    'Source View: Plain text editor\nLive Preview: Editor with live markdown highlights (default)\nReading: Read-only rendered markdown view': 'Вихідний код: Звичайний текст\nЖивий перегляд: Редактор з підсвіткою markdown\nЧитання: Лише перегляд markdown',
    'Source and destination are the same file.': 'Джерело та призначення \u2014 один файл.',
    'Splitter Handle Width': 'Ширина ручки роздільника',
    'Success': 'Успішно',
    'Swap their places': 'Поміняти місцями',
    'Switch project': 'Перемкнути проект',
    "Template for the Ctrl+E header.\n{text} \u2014 the line's text\n{time} \u2014 timestamp\n{state} \u2014 Morning / Day / Evening / Night\nMarkdown markers (** __ etc.) are yours to add or drop.": "Шаблон Ctrl+E заголовка.\n{text} \u2014 текст рядка\n{time} \u2014 час\n{state} \u2014 Ранок/День/Вечір/Ніч\nМаркдери (** __ і т.д.) можна додати або прибрати.",
    'Text Files (*.txt)': 'Текстові файли (*.txt)',
    "The nested silo owns {} file(s).\nMerge them into the parent silo's Files?\n(collisions get ' (2)' names \u2014 nothing is overwritten)": "Дочірнє сило містить {} файл(ів).\nОб'єднати з Файлами батька?\n(конфлікти отримають ' (2)' \u2014 нічого не перезаписується)",
    'Toggle Hide on Click-Out': 'Ховати при кліку ззовні',
    'Toggle [ ] checkboxes on the line / selection': 'Перемкнути [ ] прапорці на рядку/виділенні',
    'Toggle always-on-top': 'Перемкнути поверх усіх вікон',
    'Top Left Zone': 'Верхня ліва зона',
    'Top Right Zone': 'Верхня права зона',
    'Transfer to project, replace from, move to bottom&hellip;': 'Перенести в проект, замінити з, вниз&hellip;',
    'UI Gaps:': 'Проміжки UI:',
    'Undo / redo \u2014 text <i>and</i> silo actions (clear, delete, move, pin, archive, tabs)': 'Скасувати/повторити \u2014 текст <i>та</i> дії (очистка, видалення, переміщення, pin, архів, вкладки)',
    'View\nCycle view: Icons \u2192 List \u2192 Details (like Explorer)': 'Вид\nЦикл: Значки \u2192 Список \u2192 Деталі (як у провіднику)',
    'View ({})': 'Вид ({})',
    'View ({})\nCycle view: Icons \u2192 List \u2192 Details (like Explorer)': 'Вид ({})\nЦикл: Значки \u2192 Список \u2192 Деталі (як у провіднику)',
    'Zen / focus mode (hide all chrome)': 'Дзен/фокус (сховати всі елементи)',
    'Zoom the editor font': 'Масштаб шрифту редактора',
    '``` fences render monospace with syntax tints, auto line numbers and a one-click copy button on the fence line': '``` блоки моноширинно з підсвіткою, номерами рядків та кнопкою копіювання',
    'add shortcut in container': 'додати ярлик у контейнер',
    'clearing or trashing a silo writes its text to data/files/_trash/ and moves its files there; nothing is destroyed': 'очищення/видалення сила записує текст у data/files/_trash/; нічого не знищується',
    'clipboard has no text': 'буфер обміну порожній',
    'collapse code blocks and # header sections with the fold box; right-click &rarr; Expand All Folds': 'згортайте блоки коду та # заголовки; правий клік &rarr; Розгорнути все',
    'date + time with seconds, day word and an optional mini analog clock, all toggleable': 'дата+час з секундами, словом доби та опціональним годинником',
    'insert content into silo': 'вставити вміст у сило',
    'insert markdown link at cursor': 'вставити markdown посилання біля курсора',
    'live highlighting, clickable links &amp; checkboxes, auto-bullets (- + space, Enter continues), zebra stripes, line numbers': 'жива підсвітка, лінки та прапорці, авто-буліти, зебра, номери рядків',
    'named text blocks per project tab; instant paste': 'іменовані блоки тексту на вкладку; миттєва вставка',
    'one click stores the current silo or snippet': 'один клік зберігає поточне сило або снипет',
    'optional UI clicks and typewriter effect': 'опціональні звуки інтерфейсу та друкарської машинки',
    'path copied': 'шлях скопійовано',
    'per-silo asset drawer: drop ANY files in, drag them out, preview images, open, export, link (.url), save clipboard as file. Explorer-style Icons / List / Details views': 'сховище файлів сила: кидайте БУДЬ-ЯКІ файли, перетягуйте, переглядайте, експортуйте, лінкуйте. Вид: Значки/Список/Деталі',
    "store in silo's container": "зберегти в контейнері сила",
    'up to 100 auto-saved scratchpads per project; pins, recency color tints, line counters, drag to reorder': 'до 100 чернеток на проект; кріплення, кольори давності, лічильники, перетягування',
    'up to 5 tabs, each with its own silos, snippets, archive': 'до 5 вкладок, кожна зі своїми сілами, снипетами, архівом',
    '{} file(s)': '{} файл(ів)',
    '{} item(s) \u00b7 {}': '{} елемент(ів) \u00b7 {}',
    '~50 text formats load as plain text': '~50 текстових форматів як звичайний текст',
    '\U0001f4c1{}': '\U0001f4c1{}',
    '\U0001f4c4 Drop as Text': '\U0001f4c4 Вставити як текст',
    '\U0001f4dd Drop as Text': '\U0001f4dd Вставити як текст',
    '\U0001f4e5 Copy to Files \U0001f4c1': '\U0001f4e5 Копіювати у Файли \U0001f4c1',
    '\U0001f517 Link in Files \U0001f4c1': '\U0001f517 Посилання у Файлах \U0001f4c1',
}

# Verify coverage
still_missing = [k for k in missing_keys if k not in new_ukr]
with open('still_missing_final.txt', 'w', encoding='utf-8') as f:
    if still_missing:
        f.write(f"STILL MISSING ({len(still_missing)}):\n")
        for k in still_missing:
            f.write(f"  {repr(k)}\n")
    else:
        f.write("All covered!\n")

# Build complete dict
complete = dict(ukr_d)
complete.update(new_ukr)

# Verify all EN keys present
en_not_in_complete = [k for k in en_d if k not in complete]
if en_not_in_complete:
    with open('en_not_in_complete.txt', 'w', encoding='utf-8') as f:
        f.write(f"MISSING FROM COMPLETE ({len(en_not_in_complete)}):\n")
        for k in en_not_in_complete:
            f.write(f"  {repr(k)}\n")

# Sort keys case-insensitively
sorted_keys = sorted(complete.keys(), key=lambda x: x.lower())

# Write output file
lines = []
lines.append('"""Українські переклади (Ukrainian) — всі ключі."""')
lines.append('')
lines.append('from __future__ import annotations')
lines.append('')
lines.append('TRANSLATIONS: dict[str, str] = {')

for k in sorted_keys:
    v = complete[k]
    lines.append(f'    {repr(k)}: {repr(v)},')

lines.append('}')
lines.append('')

output = '\n'.join(lines)

with open('V:\\_TEMP_\\opencode\\ukr_full.py', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Written {len(complete)} keys to ukr_full.py")
print(f"EN keys: {len(en_d)}")
