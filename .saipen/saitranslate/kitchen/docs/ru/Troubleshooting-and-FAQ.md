# Устранение неполадок и FAQ FastPrompter

## 1. Проблемы GUI / Qt

### Приложение не запускается / пустое окно

**Причины:**
- Устаревший IPC-лок — предыдущий экземпляр упал с открытым сокетом
- Координаты окна вне экрана — монитор отключён, пока окно было сохранено там
- Артефакты высокого DPI / масштабирования

**Исправление:**
- Удалить `%TEMP%\fastprompter_ipc.token` или `%TEMP%\fastprompter.lock`
- Ctrl+Q дважды для цикла привязки к центру экрана
- Запуск с флагом `--reset-pos`
- Подстроить масштаб UI: Настройки или Ctrl+Plus/Minus

### Кириллические / не-QWERTY горячие клавиши не работают

Это обрабатывает VK-диспетчеризация, независимая от раскладки. Если всё ещё не работает:
1. Откройте Настройки (Alt+`)
2. Перепривяжите неработающую горячую клавишу через определение физической клавиши
3. Убедитесь, что глобальный хук pynput имеет разрешения в Безопасности Windows

## 2. Логи падений

| Файл | Путь | Назначение |
|---|---|---|
| Лог приложения | `%TEMP%\fastprompter.log` | Ротация, макс. 1MB, 2 бэкапа |
| Лог падений | `%TEMP%\fastprompter_crash.log` | Трейсбеки sys.excepthook |
| Лог тестов | `%TEMP%\fastprompter-tests.log` | Журнал сессии pytest |

Просмотр:
```
powershell:
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50

cmd:
type %TEMP%\fastprompter_crash.log
```

Прикрепляйте оба лога при заведении issues.

## 3. Очистка процессов

**Симптом:** Alt+X ничего не делает. Второй запуск говорит «Another instance running».

**Исправление:**
```
cmd:
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe

powershell:
Stop-Process -Name FastPrompter -Force
Stop-Process -Name pythonw -Force
```

## 4. Блокировка / повреждение БД

Файлы БД: `data/local_data_v15.db` (+wal, +shm)

### «database is locked»
1. Убить все процессы FastPrompter (см. §3)
2. Проверить права папки data/ (должна быть перезаписываемой)
3. Удалить файлы -wal и -shm (SQLite пересоздаёт из .db)

### «database disk image is malformed»
1. **Автобэкап:** переименовать `.db.bak` → `.db`
2. **Markdown-зеркало:** восстановить из `~/Documents/.fastprompter/` (плоские .md файлы)
3. **Ремонт через SQLite CLI:**
```
sqlite3 local_data_v15.db ".recover" > dump.sql
sqlite3 repaired.db < dump.sql
copy repaired.db local_data_v15.db
```

## 5. Конфликты горячих клавиш

**Симптом:** «Global hotkey Alt+X binding failed»

**Причина:** Другое приложение зарегистрировало ту же горячую клавишу (GeForce Experience, PowerToys, Discord, AutoHotkey и т.д.)

**Исправление:**
- Сменить горячую клавишу вызова FastPrompter в Настройках (Alt+`)
- Или перепривязать конфликтующее приложение
- Попробовать Alt+Z, Ctrl+Alt+P или F12 как альтернативу

## 6. FAQ

### В1: Данные хранятся в облаке?
**Нет.** 100% локально офлайн. Ноль телеметрии, ноль удалённых вызовов.

### В2: Как сделать бэкап?
Скопируйте папку `data/`. Или скопируйте `~/Documents/.fastprompter/`. Или используйте диалог Backup.

### В3: Портативность с USB?
**Да.** Держите `FastPrompter.exe` + папку `data/` вместе на любом диске. Без реестра, без AppData.

### В4: Сброс к заводским настройкам?
Удалите `data/local_data_v15.db`. Приложение пересоздаст схему свежей при следующем запуске.

### В5: Нужен ли Python для запуска?
**Нет.** Автономный EXE, собранный Nuitka. Python-рантайм не нужен.
