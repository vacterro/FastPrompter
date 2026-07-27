# FastPrompter Build, Packaging & Release Deployment Guide

## Overview
FastPrompter is delivered as a single-file, zero-installer portable Windows executable (`FastPrompter.exe`). It requires no admin rights, no pre-installed Python interpreter, and no registry changes. All application state is stored locally in the `data/` directory adjacent to the binary.

---

## Prerequisites & Build Environment

Zum Kompilieren und Veröffentlichen von FastPrompter sind die folgenden Tools erforderlich:

- **Python**: Version 3.11 oder höher.
- **Paketmanager**: [`uv`](https://github.com/astral-sh/uv) (empfohlen) oder Standard-`pip`.
- **Compiler**: [`Nuitka`](https://nuitka.net/) (Version >= 4.1.2).
- **C-Compiler**: C64/MSVC oder MinGW64 (Nuitka lädt bei Bedarf automatisch den C-Compiler herunter).
- **Kompressor (optional)**: [`UPX`](https://upx.github.io/) ausführbar in „PATH“ für 50–60 % Reduzierung der Binärgröße.
- **Git**: Git für Windows mit konfigurierten GitHub-Anmeldeinformationen.

---

## 1. Nuitka Compilation Pipeline (`tools/build.py`)

Die eigenständige ausführbare Datei wird mit Nuitka über „tools/build.py“ kompiliert.

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

Das Skript „tools/release.py“ automatisiert die Tag-Erstellung und Binärverteilung auf GitHub Releases.

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

Für eine schnelle Bereitstellung durch den Bediener enthält FastPrompter drei Ein-Klick-Skripte im Stammverzeichnis:

### A. `deploy.cmd` / `deploy.ps1` (Codebase Sync)
Double-click `deploy.cmd` to commit and push all project changes to GitHub.

- **PowerShell-Skript (`deploy.ps1`)**:
  1. Stellt alle geänderten Dateien bereit („git add -A“).
  2. Erstellt einen zeitgestempelten Commit „deploy: YYYY-MM-DD HH:mm“, wenn nicht festgeschriebene Änderungen vorhanden sind.
  3. Ruft Remote-Änderungen mit „git pull --rebase --autostash origin main“ ab.
  4. Löst Konflikte, indem der lokale Staat zum Sieg gezwungen wird („git push --force-with-lease origin main“, wenn die Rebase fehlschlägt).
  5. Schiebt den aktualisierten Hauptzweig nach „Origin Main“.

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

| Problem | Grundursache | Lösung |
|---|---|---|
| **`ImportError: Kein Modul namens fastprompter`** in der erstellten EXE-Datei | Nuitka hat das Verzeichnis „src/“ nicht verfolgt. | Stellen Sie sicher, dass „PYTHONPATH“ „src/“ enthält, bevor Sie Nuitka ausführen (wird automatisch von „tools/build.py“ verarbeitet). |
| **`Keine GitHub-Anmeldeinformationen gefunden`** während der Veröffentlichung | Git-Anmeldeinformationshilfe nicht aktiv oder Benutzer nicht bei GitHub angemeldet. | Führen Sie „git push“ einmal manuell aus, um das Token im Windows Credential Manager zu speichern. |
| **Große EXE-Größe (>60 MB)** | UPX-Binärdatei wurde im Systempfad nicht gefunden. | Installieren Sie UPX von „https://upx.github.io/“ und fügen Sie den Speicherort „upx.exe“ zum Systempfad hinzu. |
| **Rebase-Konflikt während „deploy.cmd“** | Direkt auf GitHub bearbeitetes Remote-Repository. | „deploy.ps1“ bricht den Rebase automatisch ab und führt einen „--force-with-lease“-Push aus, um den lokalen Maschinenstatus beizubehalten. |