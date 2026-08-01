# FastPrompter Wiki

FastPrompter — ultraschnelles, tastaturgesteuertes Scratchpad + Prompt-Workbench für Windows. Python 3.11+, PyQt6. SQLite-WAL-Persistenz. Nuitka-gebautes, eigenständiges EXE.

> **Alt+X** ruft ein 100-Slots-Scratchpad am Mauszeiger auf. Null Installation, null Cloud, null Telemetrie. Der gesamte Zustand wird sofort in der lokalen DB gespeichert.

---

## Technischer Dokumentationsindex

### Kernarchitektur
- **[Architekturübersicht](Architecture-Overview)** — Systemdesign, IPC-Single-Instance, SQLite-WAL, Zustandssync, Subsysteme
- **[Modulstruktur](Module-Structure)** — `src/fastprompter/`-Baum, Dateiverantwortlichkeiten, core/ui/utils/watcher-Karte
- **[Core API & Klassen](Core-API-and-Classes)** — FastPrompterState, HotkeyManager, IPCServer, SoundManager, PomodoroEngine, UI-Widgets
- **[Watcher-Engine](Watcher-Engine-Architecture)** — CDP-Attach, Win32-Hooks, Queue-Injection, Zustandsmaschine, Rate-Limits

### Schnittstelle & Daten
- **[Konfiguration](Configuration)** — DB-Schema (local_data_v15.db), Einstellungsschlüssel, Custom-Theme-Engine, Backup-Spiegel
- **[UI-Komponenten](UI-Components)** — Layout-Diagramm, Panel-Aufschlüsselung (Editor, Silos, Queue, Dateien, Kanban, Tabelle)
- **[Tastenkombinationen](Keyboard-Shortcuts-and-Cheatsheet)** — vollständige Referenz: global, Fenster, Formatierung, Watcher, Silo, Snippet

### Anleitungen & Erweiterbarkeit
- **[Benutzerhandbuch](User-Guide)** — Workflows, Silo-Verwaltung, Snippet-Makros, Datei-Container, Zen-Modus, Pomodoro-Timer, Hide-Markup, Kanban/Tabelle
- **[Fehlerbehebung & FAQ](Troubleshooting-and-FAQ)** — Absturzprotokolle (%TEMP%\fastprompter_crash.log), Prozessbereinigung, DB-Reparatur, Hotkey-Konflikte
- **[Plugin- & Skill-Entwicklung](Plugin-and-Skill-Development)** — benutzerdefinierte Skills (skills.py), SAIPEN-Subagenten, Custom Themes, Cursor-Themes

### Automatisierung & Protokoll
- **[SAIPEN-Protokoll](SAIPEN-Protocol)** — v7-Protokollspezifikation: Zustandsmaschinen-Schleife, Ereignisprotokollierung, SubSaipen-Read-Only-Architektur, OUTBOX-Übergabe
- **[Deployment-Anleitung](Deployment-Guide)** — Nuitka-Kompilierung (tools/build.py), GitHub-Release (tools/release.py), One-Click-Skripte

---

## Projektinformationen & Links
- **Repository**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Tech-Stack**: Python 3.11+, PyQt6, SQLite (WAL-Modus), Nuitka 4.1+, pynput
- **Lizenz**: MIT

---

*FastPrompter Wiki — Erstellt mit [SAIPEN-Protokoll](SAIPEN-Protocol) | [GitHub-Repository](https://github.com/vacterro/FastPrompter)*
