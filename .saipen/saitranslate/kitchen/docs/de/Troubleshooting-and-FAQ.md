# FastPrompter Fehlerbehebung & FAQ

## 1. GUI / Qt-Probleme

### App startet nicht / leeres Fenster

**Ursachen:**
- Veraltete IPC-Sperre — vorherige Instanz mit offenem Socket abgestürzt
- Offscreen-Fensterkoordinaten — Monitor getrennt, während das Fenster dort gespeichert war
- High-DPI / Skalierungs-Artefakte

**Fix:**
- `%TEMP%\fastprompter_ipc.token` oder `%TEMP%\fastprompter.lock` löschen
- Ctrl+Q zweimal drücken, um Snap zur Bildschirmmitte zu durchlaufen
- Mit `--reset-pos`-Flag starten
- UI-Skalierung anpassen: Einstellungen oder Ctrl+Plus/Minus

### Kyrillische / Nicht-QWERTY-Hotkeys schlagen fehl

Layoutunabhängiger VK-Dispatch behandelt das. Falls es immer noch fehlschlägt:
1. Einstellungen öffnen (Alt+`)
2. Fehlgeschlagenen Hotkey mit physischer Tastenerkennung neu binden
3. Sicherstellen, dass der pynput-globale Hook in der Windows-Sicherheit Berechtigungen hat

## 2. Absturzprotokolle

| Datei | Pfad | Zweck |
|---|---|---|
| App-Protokoll | `%TEMP%\fastprompter.log` | Rotierend, max. 1 MB, 2 Backups |
| Absturzprotokoll | `%TEMP%\fastprompter_crash.log` | sys.excepthook-Tracebacks |
| Testprotokoll | `%TEMP%\fastprompter-tests.log` | Pytest-Sitzungsprotokoll |

Anzeigen:
```
powershell:
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50

cmd:
type %TEMP%\fastprompter_crash.log
```

Beide Protokolle beim Melden von Problemen anhängen.

## 3. Prozessbereinigung

**Symptom:** Alt+X tut nichts. Zweiter Start sagt "Eine andere Instanz läuft".

**Fix:**
```
cmd:
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe

powershell:
Stop-Process -Name FastPrompter -Force
Stop-Process -Name pythonw -Force
```

## 4. DB-Sperre / -Korruption

DB-Dateien: `data/local_data_v15.db` (+wal, +shm)

### "database is locked"
1. Alle FastPrompter-Prozesse beenden (siehe §3)
2. Berechtigungen des data/-Ordners prüfen (muss beschreibbar sein)
3. -wal- und -shm-Dateien löschen (SQLite baut aus .db neu auf)

### "database disk image is malformed"
1. **Auto-Backup:** `.db.bak` → `.db` umbenennen
2. **Markdown-Spiegel:** aus `~/Documents/.fastprompter/` wiederherstellen (flache .md-Dateien)
3. **SQLite-CLI-Reparatur:**
```
sqlite3 local_data_v15.db ".recover" > dump.sql
sqlite3 repaired.db < dump.sql
copy repaired.db local_data_v15.db
```

## 5. Hotkey-Konflikte

**Symptom:** "Global hotkey Alt+X binding failed"

**Ursache:** Eine andere App hat denselben Hotkey registriert (GeForce Experience, PowerToys, Discord, AutoHotkey usw.)

**Fix:**
- Aufruf-Hotkey von FastPrompter in den Einstellungen ändern (Alt+`)
- Oder die konkurrierende App neu binden
- Alternativen probieren: Alt+Z, Ctrl+Alt+P oder F12

## 6. FAQ

### Q1: Werden Daten in der Cloud gespeichert?
**Nein.** 100 % lokal offline. Null Telemetrie, null Remote-Aufrufe.

### Q2: Wie sichern?
`data/`-Ordner kopieren. Oder `~/Documents/.fastprompter/` kopieren. Oder den Backup-Dialog verwenden.

### Q3: Von USB portabel?
**Ja.** `FastPrompter.exe` + `data/`-Ordner zusammen auf jedem Laufwerk behalten. Keine Registry, kein AppData.

### Q4: Werksreset?
`data/local_data_v15.db` löschen. Die App erstellt beim nächsten Start ein frisches Schema.

### Q5: Ist Python zum Ausführen nötig?
**Nein.** Nuitka-kompiliertes eigenständiges EXE. Keine Python-Runtime nötig.
