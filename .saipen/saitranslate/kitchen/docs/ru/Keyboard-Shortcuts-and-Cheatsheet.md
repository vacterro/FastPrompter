# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions—from summoning the window to line formatting, queue management, silo navigation, and macro pasting—have dedicated keyboard shortcuts.

---

## Quick Reference Table

| Категория | Горячая клавиша | Действие | Область применения/контекст |
|---|---|---|---|
| **Глобальный** | **Alt+X** | Вызвать/скрыть окно FastPrompter | Общесистемный (любое приложение) |
| **Наблюдатель** | **Alt+C** | Toggle Наблюдение за набором текста/Просмотр состояния | Главное окно |
| **Наблюдатель** | **Alt+Shift+C** | Открыть диалоговое окно мастера очереди | Главное окно |
| **Окно** | **Ctrl+D** | Переключить режим Zen Focus (скрывает панели/хром) | Главное окно |
| **Окно** | **Ctrl+Q** | Положение циклической привязки (верхний левый, верхний правый, центр, курсор) | Главное окно |
| **Окно** | **Alt+S** | Переключить блокировку окна (размер и положение штифта) | Главное окно |
| **Окно** | **Alt+E** | Переключить закрепленный статус Always-on-Top | Главное окно |
| **Окно** | **Alt+D** | Переключить видимость боковой панели | Главное окно |
| **Окно** | **Alt+A** | Toggle Поведение «Скрыть при щелчке» | Главное окно |
| **Окно** | **Alt+`** | Открыть наложение мини-настроек | Главное окно |
| **Окно** | **Ctrl+Alt+Shift+Q** | Экстренные силы покинули FastPrompter | Общесистемный |
| **Навигация** | **Ctrl+1** .. **Ctrl+0** | Прыгните прямо в бункер с 1 по 10 | Приложение |
| **Навигация** | **Alt+Вверх** / **Alt+Вниз** | Прогулка вперед/назад через активные бункеры | Приложение |
| **Навигация** | **Ctrl+N** | Создать новый пустой бункер | Приложение |
| **Навигация** | **Ctrl+F** | Открыть панель поиска | Редактор |
| **Навигация** | **Ctrl+H** | Открыть Заменить панель поиска и замены | Редактор |
| **Навигация** | **Ctrl+Shift+S** | Экспортировать активный текст бункера в файл | Приложение |
| **Форматирование** | **Ctrl+E** | Отформатировать строку как заголовок H1 с отметкой времени | Редактор |
| **Форматирование** | **Ctrl+Return** | Переключить флажок `- [ ]` / `- [x]` в текущей строке | Редактор |
| **Форматирование** | **Ctrl+W** | Вставьте горизонтальную разделительную линию через `---` | Редактор |
| **Форматирование** | **Alt+W** | Вставьте разделительную линию `---` и новый маркер `- ` | Редактор |
| **Форматирование** | **Ctrl+B** | Переключить **Жирный** текст (`**текст**`) | Редактор |
| **Форматирование** | **Ctrl+I** | Toggle *Курсив* текста (`*text*`) | Редактор |
| **Форматирование** | **Ctrl+U** | Toggle <u>Подчеркивание</u> текста (`<u>text</u>`) | Редактор |
| **Форматирование** | **Ctrl+T** | Toggle ~~Зачеркнутый~~ текст (`~~text~~`) | Редактор |
| **Форматирование** | **Ctrl+Shift+Q** | Переключить блок цитат (`> text`) | Редактор |
| **Форматирование** | **Alt+Z** | Переключить номера строк в поле редактора | Редактор |
| **Форматирование** | **Alt+Backspace** | Удалить предыдущее слово | Редактор |
| **Форматирование** | **Ctrl+Z** | Умная отмена действия редактирования | Редактор |
| **Фрагменты** | **F1** .. **F10** | Вставьте фрагмент с 1 по 10 в редактор | Приложение |
| **Фрагменты** | **Ctrl+Shift+1** .. **9** | Вставить фрагмент с 1 по 9 (альтернативный вариант) | Приложение |
| **Фрагменты** | **Ctrl+S** | Открыть диспетчер фрагментов / Сохранить активный фрагмент | Приложение |
| **Вложения** | **F2** | Переименовать выбранный файл вложения | Панель «Контейнер файлов» |
| **Вложения** | **Удалить** | Удалить выбранный вложенный файл в корзину | Панель «Контейнер файлов» |
| **Общие** | **Эск** | Скрыть окно FastPrompter / Закрыть активное наложение | Системный/Локальный |

---

## Detailed Category Breakdown

### 1. Global & Window Management
- **Alt+X (Global Summon)**: Instantly brings FastPrompter to the foreground at your current mouse cursor coordinates. Pressing `Alt+X` again hides the window back to system tray.
- **Ctrl+D (Zen Mode)**: Hides sidebar, snippet bar, file container, status bar, and window framing for distraction-free writing.
- **Ctrl+Q (Corner Snap)**: Rotates window placement across predefined screen regions: Top-Left -> Top-Right -> Bottom-Left -> Bottom-Right -> Center -> Cursor Position.
- **Alt+S & Alt+E**: Lock window geometry to prevent accidental dragging (`Alt+S`) and pin window above all other desktop windows (`Alt+E`).

### 2. Typing Watcher & CDP Automation
- **Alt+C**: Toggles the automated typing watcher engine on/off. When armed, watches target application focus.
- **Alt+Shift+C**: Opens the Queue Master dialog to inspect, reorder, clear, or inject items into the active watcher drainage queue.

### 3. Markdown Formatting Shortcuts
- **Ctrl+E**: Converts current line into `# HH:MM - Heading`.
- **Ctrl+Return**: Converts regular text into `- [ ] text` or toggles `- [ ]` <-> `- [x]`.
- **Ctrl+W / Alt+W**: Inserts markdown dividers `---`. `Alt+W` automatically starts a new bullet point on the following line.
- **Ctrl+B / Ctrl+I / Ctrl+U / Ctrl+T**: Inline formatting for bold, italic, underline, and strikethrough.

### 4. Silo & Tab Navigation
- **Ctrl+1 .. Ctrl+0**: Instantly switches editor tab to Silo slot 1 through 10.
- **Alt+Up / Alt+Down**: Step through active silos sequentially without mouse interaction.
- **Ctrl+N**: Creates a new numbered scratch silo in the active project tab.

### 5. Snippet Macro Slots (`F1`-`F10`)
- **F1 .. F10**: Pastes pre-configured snippet templates directly at the editor cursor location.
- **Ctrl+Shift+1 .. 9**: Secondary hotkey binding for devices without dedicated function keys (e.g. compact keyboards).

---

## Physical Virtual Key (VK) Layout Fallbacks
FastPrompter features physical keyboard key mapping via `LayoutIndependentShortcuts`. Shortcuts continue to work reliably regardless of whether the active Windows keyboard layout is set to English (QWERTY), Russian (JCUKEN), German (QWERTZ), or French (AZERTY).

---
*FastPrompter Wiki — создан с использованием [Протокол SAIPEN] (Протокол SAIPEN) | [Репозиторий GitHub](https://github.com/vaacterro/FastPrompter)*