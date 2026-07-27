# FastPrompter Build, Packaging & Release Deployment Guide

## Overview
FastPrompter is delivered as a single-file, zero-installer portable Windows executable (`FastPrompter.exe`). It requires no admin rights, no pre-installed Python interpreter, and no registry changes. All application state is stored locally in the `data/` directory adjacent to the binary.

---

## Prerequisites & Build Environment

Для компиляции и публикации FastPrompter необходимы следующие инструменты:

- **Python**: версия 3.11 или выше.
- **Диспетчер пакетов**: [`uv`](https://github.com/astral-sh/uv) (рекомендуется) или стандартный `pip`.
- **Компилятор**: [`Nuitka`](https://nuitka.net/) (версия >= 4.1.2).
- **Компилятор C**: C64/MSVC или MinGW64 (Nuitka автоматически загружает компилятор C при необходимости).
- **Компрессор (необязательно)**: [`UPX`](https://upx.github.io/), исполняемый в `PATH` для уменьшения размера двоичного файла на 50–60%.
- **Git**: Git для Windows с настроенными учетными данными GitHub.

---

## 1. Nuitka Compilation Pipeline (`tools/build.py`)

Автономный исполняемый файл компилируется с использованием Nuitka через «tools/build.py».

### Execution Command
```bash
uv run python tools/build.py
```

### Build Steps & Technical Mechanics
1. **Nuitka Check**: Verification that `nuitka>=4.1.2` is installed. If missing, `tools/build.py` automatically invokes `pip install nuitka>=4.1.2`.
2. **UPX Detection**: Checks for `upx` in system PATH. If available, adds `--plugin-enable=upx` and `--upx-binary=<path>` flags to shrink binary size down to ~15-25MB.
3. **`PYTHONPATH` Injection**: Adds `src/` directory to environment `PYTHONPATH` during compilation so Nuitka traces and embeds the entire `fastprompter` package cleanly.
4. **Target Script**: Compiles `FastPrompter.pyw` (GUI entry point without console popup).
5. **Output**: Generates `build/FastPrompter.exe`.

### `tools/build.py` Source Workflow
```python
# Key invocation parameters inside build.py:
cmd = [
    sys.executable,
    "-m",
    "nuitka",
    "FastPrompter.pyw",
]
if upx_bin:
    cmd.append("--plugin-enable=upx")
    cmd.append(f"--upx-binary={upx_bin}")
```

---

## 2. GitHub Release Automation (`tools/release.py`)

Скрипт «tools/release.py» автоматизирует создание тегов и распространение двоичных файлов в выпусках GitHub.

### Execution Command
```bash
uv run python tools/release.py [release_notes.md]
```

### Automation Steps
1. **EXE Verification**: Verifies `build/FastPrompter.exe` exists.
2. **Version Extraction**: Parses the exact version string from `pyproject.toml` (e.g., `version = "1.5.0"` -> tag `v1.5.0`).
3. **GitHub Credential Retrieval**: Invokes `git credential fill` using host `github.com` to safely extract the GitHub token stored in Windows Credential Manager (same token used by `git push`).
4. **Release API Dispatch**:
   - Queries GitHub API `https://api.github.com/repos/vacterro/FastPrompter/releases/tags/v<version>`.
   - If tag doesn't exist, creates a new GitHub Release.
   - If tag exists, updates release notes.
5. **Asset Upload**: Deletes old `FastPrompter.exe` release asset if present and uploads the newly compiled binary (`build/FastPrompter.exe`) via `uploads.github.com`.

---

## 3. One-Click Batch Scripts

Для быстрого развертывания оператора FastPrompter включает в себя три сценария, запускаемые одним щелчком мыши, в корневом каталоге:

### A. `deploy.cmd` / `deploy.ps1` (Codebase Sync)
Double-click `deploy.cmd` to commit and push all project changes to GitHub.

- **Скрипт PowerShell (`deploy.ps1`)**:
  1. Добавляет все измененные файлы (`git add -A`).
  2. Создает фиксированное время фиксации `deploy: ГГГГ-ММ-ДД ЧЧ:мм`, если существуют незафиксированные изменения.
  3. Извлекает удаленные изменения, используя `git pull --rebase --autostash origin main`.
  4. Разрешает конфликты, заставляя локальное состояние побеждать («git push --force-with-lease origin main», если перебазирование не удалось).
  5. Перемещает обновленную основную ветку в «origin main».

### B. `release.cmd` (Build + Release Pipeline)
Double-click `release.cmd` to run end-to-end build and deployment in one action.

```cmd
@echo off
uv run python tools\build.py || (echo BUILD FAILED & pause & exit /b 1)
uv run python tools\release.py %*
echo.
pause
```

---

## 4. Troubleshooting & Edge Cases

| Выпуск | Основная причина | Решение |
|---|---|---|
| **`Ошибка импорта: во встроенном EXE-файле нет модуля с именем fastprompter`** | Nuitka не отслеживала каталог `src/`. | Перед запуском Nuitka убедитесь, что PYTHONPATH включает в себя src/ (автоматически обрабатывается с помощью Tools/build.py). |
| **`Учетные данные GitHub не найдены`** во время выпуска | Помощник по учетным данным Git не активен или пользователь не вошел в GitHub. | Запустите git push один раз вручную, чтобы сохранить токен в диспетчере учетных данных Windows. |
| **Большой размер EXE-файла (>60 МБ)** | Двоичный файл UPX не найден в системной PATH. | Установите UPX с https://upx.github.io/ и добавьте местоположение upx.exe в системный PATH. |
| **Конфликт перебазирования во время `deploy.cmd`** | Удаленный репозиторий, редактируемый непосредственно на GitHub. | `deploy.ps1` автоматически прерывает перебазирование и выполняет отправку `--force-with-lease` для сохранения состояния локального компьютера. |