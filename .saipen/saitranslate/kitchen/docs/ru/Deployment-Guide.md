# Руководство по сборке и релизу FastPrompter

## Обзор

Однофайловый портативный EXE (`FastPrompter.exe`). Без установщика, без прав администратора, без необходимости в Python-рантайме. Всё состояние в `data/` рядом с бинарником.

---

## Предпосылки

- **Python** 3.11+
- **uv** (менеджер пакетов) или pip
- **Nuitka** >= 4.1.2
- **C-компилятор** — Nuitka скачает автоматически, если отсутствует
- **UPX** (опционально, уменьшение размера на 50-60%)
- **Git** для Windows с учётными данными GitHub

---

## 1. Компиляция (`tools/build.py`)

```bash
uv run python tools/build.py
```

### Шаги
1. Проверить установку Nuitka >= 4.1.2 (автоустановка, если отсутствует)
2. Обнаружить UPX в PATH (добавляет `--plugin-enable=upx`, если найден)
3. Внедрить `src/` в PYTHONPATH для чистого трейса модулей
4. Скомпилировать `FastPrompter.pyw` (GUI-вход, без консоли)
5. Результат: `build/FastPrompter.exe`

### Ключевые флаги
```python
cmd = [
    sys.executable,
    "-m", "nuitka",
    "FastPrompter.pyw",
]
if upx_bin:
    cmd.append("--plugin-enable=upx")
    cmd.append(f"--upx-binary={upx_bin}")
```

Результат EXE ~15-28MB в зависимости от UPX.

---

## 2. Публикация (`tools/release.py`)

```bash
uv run python tools/release.py [release_notes.md]
```

### Шаги
1. Проверить, что `build/FastPrompter.exe` существует
2. Прочитать версию из `pyproject.toml` (тег = `v<version>`)
3. Извлечь GitHub-токен из Windows Credential Manager (`git credential fill`)
4. Проверить существование тега через GitHub API
   - Нет → создать новый релиз
   - Да → обновить заметки релиза
5. Загрузить `build/FastPrompter.exe` как ассет релиза (сначала удаляет старый)

---

## 3. Скрипты в один клик

### deploy.cmd / deploy.ps1
Коммит + пуш всех изменений проекта:
- Стейджить всё (`git add -A`)
- Коммит с меткой времени (`deploy: YYYY-MM-DD HH:mm`)
- Pull rebase (`git pull --rebase --autostash origin main`)
- Force push при конфликтах (`git push --force-with-lease origin main`)

### release.cmd
Сборка + публикация в один клик:
```
uv run python tools\build.py || pause
uv run python tools\release.py %*
```

---

## Устранение неполадок

| Проблема | Причина | Исправление |
|---|---|---|
| `ImportError: No module named fastprompter` | Nuitka не оттрейсил src/ | Убедиться, что PYTHONPATH включает src/ (build.py это делает) |
| `No GitHub credential found` | Git-токена нет в Credential Manager | Один раз вручную выполнить `git push` для сохранения токена |
| Большой EXE (>60MB) | UPX не найден в PATH | Установить UPX с https://upx.github.io/ |
| Конфликт rebase при deploy | Удалённый репозиторий правили прямо на GitHub | Force-with-lease push (deploy.ps1 делает это автоматически) |
