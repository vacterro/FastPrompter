# FastPrompter Troubleshooting & FAQ Guide

## Overview
This document provides solutions to common operational issues, environment setup failures, database errors, crash log diagnostics, hotkey conflicts, and process management procedures for FastPrompter on Windows.

---

## 1. GUI & PySide6 / PyQt6 Initialization Issues

### Problem: Application Fails to Start or Shows Blank Window
* **Symptom**: FastPrompter process starts but no window appears, or an unhandled Qt error is output to console.
* **Root Causes**:
  1. **Single-Instance Lock Stale Socket**: A previous instance terminated abruptly without clearing its IPC lock file.
  2. **Offscreen Window Coordinates**: The saved window position (`x`, `y`) lies outside the bounds of currently connected display monitors (e.g. after disconnecting an external monitor).
  3. **High DPI / Scaling Artifacts**: Display scaling in Windows (125%, 150%, 200%) causing Qt layout miscalculation.
* **Solutions**:
  * **Reset Window Position**: Press **Ctrl+Q** twice after summoning (`Alt+X`) to cycle snap positions to screen center, or launch FastPrompter with `--reset-pos`.
  * **Clear Lock File**: Delete `%TEMP%\fastprompter.lock` or `%TEMP%\fastprompter_single_instance.lock`.
  * **UI Scale Reset**: Adjust font scale dynamically using **Ctrl+Plus** / **Ctrl+Minus** or reset `ui_scale` in the settings menu (**Alt+`**).

### Problem: Cyrillic / Non-QWERTY Layout Hotkeys Not Triggering
* **Symptom**: Pressing `Alt+X` or `Ctrl+B` while using a Russian, German, or French keyboard layout fails to trigger actions.
* **Root Cause**: Windows sends different `QKeySequence` character codes depending on the active input language layout.
* **Solution**: FastPrompter incorporates `LayoutIndependentShortcuts` which intercepts physical Windows Virtual Key (VK) codes directly. If a custom layout is failing:
  1. Open Settings (**Alt+`**).
  2. Re-bind the failing hotkey using physical key detection mode.
  3. Ensure `pynput` global hook permissions are granted in Windows Security.

---

## 2. Crash Logs & Diagnostics

### Log File Locations
FastPrompter routes all unhandled exceptions, warning messages, and debug traces through `src/fastprompter/core/logging.py`. Log files are stored in the system temporary directory:

| Log File | Path | Purpose |
|---|---|---|
| **Application Log** | `%TEMP%\fastprompter.log` | Active session events, warnings, info logs (Rotating, max 1MB, 2 backups). |
| **Crash Log** | `%TEMP%\fastprompter_crash.log` | Detailed tracebacks of unhandled critical exceptions via `sys.excepthook`. |
| **Test Suite Log** | `%TEMP%\fastprompter-tests.log` | Temporary log isolated to Pytest execution runs. |

### Inspecting Crash Logs
To inspect crash logs using PowerShell:
```powershell
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50
```

### Reporting Bugs & Diagnostics
When filing an issue, attach the contents of `%TEMP%\fastprompter_crash.log` and `%TEMP%\fastprompter.log`.

---

## 3. Background Process Cleanup

### Problem: `pythonw.exe` or `FastPrompter.exe` Remains Hanging
* **Symptom**: Hotkey `Alt+X` does nothing, and launching FastPrompter outputs `Another instance is already running`.
* **Root Cause**: Background thread or CDP watcher socket kept the Python process alive after main window closure.
* **Solution**: Force-kill orphaned background processes using Command Prompt or PowerShell:

#### Windows Command Prompt (cmd)
```cmd
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe
```

#### Windows PowerShell
```powershell
Stop-Process -Name FastPrompter -Force -ErrorAction SilentlyContinue
Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue
```

---

## 4. Database Locking & SQLite WAL Repair

### Database Location & Files
FastPrompter stores all user silos, snippets, tabs, and settings in SQLite database `data/local_data_v15.db`. In WAL (Write-Ahead Logging) mode, two auxiliary files exist:
* `data/local_data_v15.db-wal` (Write-Ahead Log transactions)
* `data/local_data_v15.db-shm` (Shared Memory index)

### Problem: `sqlite3.OperationalError: database is locked`
* **Symptom**: Error message stating database is locked upon startup or saving notes.
* **Root Cause**: Multiple processes accessing SQLite without WAL enabled, or stale WAL locks from hard power-offs.
* **Solutions**:
  1. Kill all running FastPrompter instances (`taskkill /F /IM FastPrompter.exe`).
  2. Check file permissions on `data/local_data_v15.db`. Ensure the folder is writeable.
  3. Delete `-wal` and `-shm` temporary files (SQLite will automatically rebuild them from the main `.db` file).

### Problem: Database Corruption & Emergency Data Recovery
If SQLite reports `database disk image is malformed`:
1. **Automatic Backup Restoration**:
   FastPrompter maintains automatic startup backups: `data/local_data_v15.db.bak`.
   Replace `local_data_v15.db` with `local_data_v15.db.bak`.
2. **Markdown Mirror Recovery**:
   Every note is mirrored daily in plain text under `%USERPROFILE%\Documents\.fastprompter\`. All notes can be retrieved directly as `.md` text files from this folder.
3. **Manual Repair via SQLite CLI**:
   ```cmd
   sqlite3 local_data_v15.db ".recover" > dump.sql
   sqlite3 repaired.db < dump.sql
   copy repaired.db local_data_v15.db
   ```

---

## 5. Hotkey Conflicts & System Permissions

### Problem: `Alt+X` Fails to Register
* **Symptom**: Toast warning `Global hotkey Alt+X binding failed`.
* **Root Cause**: Another application (e.g. GeForce Experience, AMD Radeon Software, PowerToys, Discord, or AutoHotkey) has registered `Alt+X` globally with Windows `RegisterHotKey`.
* **Solutions**:
  * Identify and rebind conflicting hotkey in external software.
  * Change FastPrompter's global summon hotkey in Settings (**Alt+`**) or `custom_theme.json` / `settings` table to `Alt+Z`, `Ctrl+Alt+P`, or `F12`.

---

## 6. Frequently Asked Questions (FAQ)

### Q1: Is FastPrompter storing data in the cloud?
**No.** FastPrompter is 100% local, offline, and self-contained. No telemetry, analytics, or remote calls are made.

### Q2: How do I back up my notes and snippets?
Copy the `data/` folder (or just `data/local_data_v15.db` and `data/files/`) to your backup location. You can also back up `%USERPROFILE%\Documents\.fastprompter\`.

### Q3: Can I run FastPrompter from a USB flash drive?
**Yes.** FastPrompter operates in portable mode when placed on a portable drive. All configuration and database files remain local to the application directory.

### Q4: How do I reset FastPrompter to factory settings?
Delete `data/local_data_v15.db`. FastPrompter will recreate a fresh database schema on the next launch.

---
*FastPrompter Wiki — Built with [SAIPEN Protocol](SAIPEN-Protocol) | [GitHub Repository](https://github.com/vacterro/FastPrompter)*
