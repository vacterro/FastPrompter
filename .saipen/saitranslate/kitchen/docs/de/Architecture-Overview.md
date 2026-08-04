# FastPrompter Architekturübersicht

## Übersicht

Portables Scratchpad + Prompt-Workbench. Python 3.11+, PyQt6. SQLite-WAL-Persistenz. Zero-Install-Nuitka-EXE. Über den globalen Hotkey Alt+X aufrufen, schreiben, schließen — der Zustand wird sofort gespeichert.

## Hochlevel-Diagramm

```
+------------------------------------------------------------------+
|                        FastPrompter UI (PyQt6)                   |
|  +------------------+  +--------------------+  +---------------+  |
|  | SnippetPanel     |  | VaultTextEdit      |  | QueuePanel    |  |
|  | (F1-F10 Silos)   |  | (Markdown + Mixins)|  | (Watcher Q)   |  |
|  +------------------+  +--------------------+  +---------------+  |
+----------------------------+-------------------------------------+
                             | events / state sync
                             v
+------------------------------------------------------------------+
|                    FastPrompterState (core)                       |
|  SQLite WAL DB — silos, snippets, settings, themes, queues       |
|  In-memory cache + undo stack + per-silo state (cursor/scroll)   |
+------------------------------------------------------------------+
      |         |          |          |            |
      v         v          v          v            v
+--------+ +---------+ +--------+ +---------+ +-----------+
|Hotkeys | | IPC     | | Sound  | | Watcher | | File      |
|(pynput)| |(QLocal) | |Manager | |Engine   | | Container |
+--------+ +---------+ +--------+ +---------+ +-----------+
```

## Kern-Subsysteme

### 1. Anwendungslebenszyklus (`main.py`)

Einstiegspunkt. QApplication-Init, Single-Instance-IPC-Prüfung (QLocalServer), DB-Verbindung, globale Exception-Hooks, UI-Fensterbau, System-Tray, Hotkey-Registrierung. Alle Mixins komponieren auf FastPrompter (QMainWindow):

- FormattingMixin — Markdown-Shortcuts (fett, kursiv, Liste, Code)
- HotkeyMixin — Shortcut-Bindungs-Schnittstelle
- ScalingMixin — DPI/Font-Skalierung
- SearchMixin — Mehrwort-UND-Suche
- SendSelectionMixin — Text über Watcher senden
- SnippetOpsMixin — Silo-Operationen (Papierkorb, Duplizieren, Sortieren, Leeren)
- ThemeMixin — App-Stylesheet, 9 integrierte Themes + Custom
- TrayMixin — Systray-Icon + Menü
- WatcherMixin — Watcher-Engine-Integration
- WindowMixin — rahmenloses Fenster, Snapping, randlos

### 2. IPC Single-Instance (`core/ipc_server.py`)

QLocalServer auf Named Pipe `FastPrompter_Server_V15`. Zweite Instanz sendet SHOW-Befehl → vorhandene Instanz holt ihr Fenster nach vorn. UUID-Token in `%TEMP%/fastprompter_ipc.token` zur Authentifizierung. Kein stilles No-Op mehr bei Absturz (server.removeServer räumt veraltete Socket-Namen auf).

### 3. Zustand & Speicherung (`core/state.py`)

SQLite-DB (`data/local_data_v15.db`) mit WAL + synchronous=NORMAL. Wichtige Tabellen: `presets` (Snippets), `settings` (k/v), `temp_presets_v2` (Silo-Text), `archive_temp_presets_v2` (archivierte Silos).

Auto-Backup beim Start (komplette DB-Kopie zu `.bak`). Gedrosseltes inkrementelles Backup alle 60 s. Kategoriebezogene Datenspeicher: `silo_colors_all`, `pinned_silos_all`, `silo_ticked_all`, `silo_children_all`, `silo_gaps_all`, `silo_project_paths_all` usw. Alle auf flache Schlüssel (`temp_presets`) für die aktive Kategorie aliased.

### 4. Hotkey-System (`core/hotkeys.py`, `core/hotkey_filter.py`)

Zwei Ebenen: (1) pynput-globaler Listener-Thread für Aufruf/Notfall-Beenden; (2) PyQt6-QShortcut für fensterlokale Bindungen. `HotkeyFilter` (Win32 WH_KEYBOARD_LL) fängt physische VK-Codes ab — layoutunabhängig. Funktioniert auf QWERTY, JCUKEN, AZERTY, QWERTZ.

### 5. Editor-Engine (`ui/editor.py`)

VaultTextEdit erweitert QPlainTextEdit. Funktionen:
- MarkdownHighlighter — Live-Syntax (Überschriften, fett, kursiv, Code-Fences, Checkboxen, Links, Bilder)
- Zeilengutter — Nummern, Faltpfeile (▾), Code-Fence-Kopierbutton
- Abschnittsfaltung — Klick-Collapse auf Header-Blöcken
- Einklappbare Bilder — `![alt](url)` wird als 150px-klickbare Pille gerendert
- Drop-Overlay — 4-Optionen-Drop-Target (Text einfügen, Link einfügen, Datei kopieren, Verknüpfung)
- Randmarkierungen — zeilenweise Pins, Haken, Queue-Anker, Heatmap
- Hide-Markup-Modus — `**bold**` → `bold` umschalten (T-603)

### 6. Silo-System (`ui/snippet_panel.py`)

Bis zu 100 Silos pro Projekt-Tab. Funktionen:
- Pins (📌) — oben verankern
- Haken (✅) — Abschlussmarker
- Hierarchie — auf ein anderes Silo ziehen zum Verschachteln (max. Tiefe 2)
- Aktualitäts-Heatmap — warme Färbung bei kürzlich bearbeiteten
- Seitenleisten-Lücken — benutzerdefinierte Abstandshalter (Ctrl+Ziehen zum Verschieben)
- Mehrfachauswahl — Shift=Bereich, Ctrl=Umschalten, Batch-Operationen
- Datei-Container — pro-Silo-Disk-Ordner (`data/silo_files/<cat>/<idx>/`)
- Kanban (Alt+Pfeile verschieben Karten) + Tabellen-Builder (Tab bewegt Zellen) — T-630

### 7. Watcher-Engine (`core/watcher/`)

Prompt-Ableitung + Zielautomatisierung. Endliche Zustandsmaschine: DISARMED → ARMED → WATCHING → SENDING. Chrome-CDP (Electron-Apps) + Win32-Fenster-Probes. Queue-Pinning pro Ziel. Rate-Limits: settle_ms=2500, min_gap_ms=4000, max_sends=25, max_failures=3.

### 8. Fensterverwaltung (`ui/window_mixin.py`, `ui/zen_desktop.py`)

Rahmenloses Fenster, Win95-Dunkelgold-Ästhetik. Ctrl+Q durchläuft Snap-Positionen (7 Zonen + FancyZone-Picker + Benutzer-Presets). 3-stufiges Ctrl+D: Zen (Minimal-Editor), Solo (andere Fenster minimieren), zurück. Overflow-Menü (») sammelt versteckte Buttons im Ultra-Schmalmodus (<700px). Header-Dichte-Stufen passen sich automatisch an (dense <1280px, ultra <700px).

### 9. Timer & Pomodoro (`core/timers.py`, `core/pomodoro.py`)

Countdown-Timer mit farbcodierter Dringlichkeit, Schlummern, Toast-Benachrichtigungen (Win95-3D-Bevles). Pomodoro-Arbeits-/Pausen-Zustandsmaschine.

### 10. Backup & Recovery

Mehrschichtig: (1) SQLite-WAL — crashsichere Schreibvorgänge; (2) `.bak` beim Start + alle 60 s; (3) täglicher Markdown-Spiegel nach `~/Documents/.fastprompter/` (Silos + Snippets + Archiv pro Projekt); (4) portabler Backup-ZIP-Builder.
