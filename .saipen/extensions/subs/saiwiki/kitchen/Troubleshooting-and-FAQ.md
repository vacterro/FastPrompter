# FastPrompter Troubleshooting & FAQ

## 1. GUI / Qt Issues

### App won't start / blank window

**Causes:**
- Stale IPC lock — previous instance crashed with socket open
- Offscreen window coords — monitor disconnected while window was saved there
- High DPI / scaling artifacts

**Fix:**
- Delete `%TEMP%\fastprompter_ipc.token` or `%TEMP%\fastprompter.lock`
- Ctrl+Q twice to cycle snap to screen center
- Launch with `--reset-pos` flag
- Adjust UI scale: Settings or Ctrl+Plus/Minus

### Cyrillic / non-QWERTY hotkeys fail

Layout-independent VK dispatch handles this. If still fails:
1. Open Settings (Alt+`)
2. Re-bind failing hotkey using physical key detection
3. Check no other application has registered the same global hotkey

## 2. Crash Logs

| File | Path | Purpose |
|---|---|---|
| App log | `%TEMP%\fastprompter.log` | Rotating, max 1MB, 2 backups |
| Crash log | `%TEMP%\fastprompter_crash.log` | sys.excepthook tracebacks |
| Test log | `%TEMP%\fastprompter-tests.log` | Pytest session log |

View:
```
powershell:
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50

cmd:
type %TEMP%\fastprompter_crash.log
```

Attach both logs when filing issues.

## 3. Process Cleanup

**Symptom:** Alt+X does nothing. Second launch says "Another instance running".

**Fix:**
```
cmd:
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe

powershell:
Stop-Process -Name FastPrompter -Force
Stop-Process -Name pythonw -Force
```

## 4. DB Locking / Corruption

DB files: `data/local_data_v15.db` (+wal, +shm)

### "database is locked"
1. Kill all FastPrompter processes (see §3)
2. Check data/ folder permissions (must be writable)
3. Delete -wal and -shm files (SQLite rebuilds from .db)

### "database disk image is malformed"
1. **Auto backup:** rename `.db.bak` → `.db`
2. **Markdown mirror:** recover from `~/Documents/.fastprompter/` (flat .md files)
3. **SQLite CLI repair:**
```
sqlite3 local_data_v15.db ".recover" > dump.sql
sqlite3 repaired.db < dump.sql
copy repaired.db local_data_v15.db
```

## 5. Hotkey Conflicts

**Symptom:** "Global hotkey Alt+X binding failed"

**Cause:** Another app registered same hotkey (GeForce Experience, PowerToys, Discord, AutoHotkey, etc.)

**Fix:**
- Change FastPrompter's summon hotkey in Settings (Alt+`)
- Or rebind the conflicting app
- Try Alt+Z, Ctrl+Alt+P, or F12 as alternative

## 6. FAQ

### Q1: Data stored in cloud?
**No.** 100% local offline. Zero telemetry, zero remote calls.

### Q2: How to backup?
Copy `data/` folder. Or copy `~/Documents/.fastprompter/`. Or use Backup dialog.

### Q3: Portable from USB?
**Yes.** Keep `FastPrompter.exe` + `data/` folder together on any drive. No registry, no AppData.

### Q4: Factory reset?
Delete `data/local_data_v15.db`. App recreates schema fresh on next launch.

### Q5: Python required to run?
**No.** Nuitka-compiled standalone EXE. No Python runtime needed.
