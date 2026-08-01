# FastPrompter Build- & Release-Anleitung

## Übersicht

Einzeldatei-portables EXE (`FastPrompter.exe`). Kein Installer, keine Admin-Rechte, keine Python-Runtime nötig. Der gesamte Zustand in `data/` neben dem Binary.

---

## Voraussetzungen

- **Python** 3.11+
- **uv** (Paketmanager) oder pip
- **Nuitka** >= 4.1.2
- **C-Compiler** — Nuitka lädt ihn automatisch herunter, wenn fehlend
- **UPX** (optional, 50-60 % Größenreduzierung)
- **Git für Windows** mit GitHub-Anmeldedaten

---

## 1. Kompilieren (`tools/build.py`)

```bash
uv run python tools/build.py
```

### Schritte
1. Prüfen, dass Nuitka >= 4.1.2 installiert ist (auto-installiert, wenn fehlend)
2. UPX im PATH erkennen (fügt `--plugin-enable=upx` hinzu, falls gefunden)
3. `src/` in PYTHONPATH injizieren für sauberen Modul-Trace
4. `FastPrompter.pyw` kompilieren (GUI-Einstieg, keine Konsole)
5. Ausgabe: `build/FastPrompter.exe`

### Wichtige Flags
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

Ausgabe-EXE ~15-28 MB je nach UPX.

---

## 2. Veröffentlichen (`tools/release.py`)

```bash
uv run python tools/release.py [release_notes.md]
```

### Schritte
1. Prüfen, dass `build/FastPrompter.exe` existiert
2. Version aus `pyproject.toml` lesen (Tag = `v<version>`)
3. GitHub-Token aus dem Windows Credential Manager holen (`git credential fill`)
4. Prüfen, ob der Tag über die GitHub-API existiert
   - Nein → neues Release erstellen
   - Ja → Release-Notizen aktualisieren
5. `build/FastPrompter.exe` als Release-Asset hochladen (löscht zuerst das alte)

---

## 3. One-Click-Skripte

### deploy.cmd / deploy.ps1
Alle Projektänderungen committen + pushen:
- Alles stagen (`git add -A`)
- Zeitgestempelter Commit (`deploy: YYYY-MM-DD HH:mm`)
- Pull-Rebase (`git pull --rebase --autostash origin main`)
- Force-Push bei Konflikten (`git push --force-with-lease origin main`)

### release.cmd
Build + Veröffentlichung mit einem Klick:
```
uv run python tools\build.py || pause
uv run python tools\release.py %*
```

---

## Fehlerbehebung

| Problem | Ursache | Fix |
|---|---|---|
| `ImportError: No module named fastprompter` | Nuitka hat src/ nicht getracet | Sicherstellen, dass PYTHONPATH src/ enthält (build.py macht das) |
| `No GitHub credential found` | Git-Token nicht im Credential Manager | Einmal `git push` manuell ausführen, um Token zu speichern |
| Großes EXE (>60MB) | UPX nicht im PATH | UPX von https://upx.github.io/ installieren |
| Rebase-Konflikt beim Deploy | Remote direkt auf GitHub bearbeitet | Force-with-lease-Push (deploy.ps1 macht das automatisch) |
