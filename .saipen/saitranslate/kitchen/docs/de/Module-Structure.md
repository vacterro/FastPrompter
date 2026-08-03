# FastPrompter Modulstruktur

## Codebase-Karte (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # Einstiegspunkt, QMainWindow, Mixin-Orchestrierung
├── __init__.py                 # Paket-Marker
│
├── core/                       # Backend-Logik, Zustand, Subsysteme
│   ├── config.py               # Theme-Farbextraktoren, Tray-Icon-Generatoren
│   ├── ctrlw.py                # Ctrl+W / Alt+W-Trenner-Einfüge-Engine
│   ├── duration.py             # Zeit-Parsing, menschenlesbare Dauerformatierung
│   ├── hashtags.py             # Hashtag-Extraktion + Siloübergreifende Indizierung
│   ├── header.py               # Ctrl+E-Header-Formatierungs-Kern
│   ├── hotkey_filter.py        # Win32-WH_KEYBOARD_LL-Hook für VK-Dispatch
│   ├── hotkeys.py              # pynput-globaler Hotkey-Listener-Thread
│   ├── ipc_server.py           # QLocalServer-Single-Instance-IPC
│   ├── limits.py               # Agent-Reset-Limit-Scanner + Timer-Erstellung
│   ├── logging.py              # Logger-Setup, rotierender Datei-Handler
│   ├── pomodoro.py             # Pomodoro-Zustandsmaschine (Arbeit/Pause)
│   ├── sound_manager.py        # Audio-Wiedergabe (Klicks, Schreibmaschine, Alarme)
│   ├── state.py                # SQLite-DB-Schnittstelle + Zustandsverwaltung
│   ├── timers.py               # Countdown-Timer-Modell, Fälligkeitserkennung
│   ├── translations.py         # Legacy-Proxy → i18n-Paket (33 Lokale)
│   │
│   ├── i18n/                   # 33-Lokale-Ressourcenpaket
│   │   ├── __init__.py, _compat.py, _container.py, _context.py, _engine.py
│   │   ├── en.py, ru.py, est.py, ja.py, ded.py, ... (33 Lokalmodule)
│   │   └── flags/              # Länderflaggen-Renderer
│   │
│   └── watcher/                # Automatisierungs- + Prompt-Ableitungs-Engine
│       ├── __init__.py
│       ├── adapter.py          # Abstrakte Probe-Adapter-Schnittstelle
│       ├── cdp.py              # Chrome-DevTools-Protocol-Treiber
│       ├── engine.py           # Watcher-Ausführungsschleife + Zustandsmaschine
│       ├── limit_scan.py       # Cross-Agent-Limit-Scanner
│       ├── probes.py           # Multi-Probe-Zustandskombinatoren
│       ├── queue.py            # Queue-Modell (QueueItem, SendIntent, Pinning)
│       ├── sender.py           # Ausgabe-Dispatch (CDP / Win32-Tasteingabe)
│       ├── skills.py           # Skill-Definitionen + Prompt-Wrapper
│       └── win32.py            # Natives Win32-Fenster- + Steuerungs-Probe
│
├── ui/                         # PyQt6-UI-Komponenten + Mixins
│   ├── analog_clock.py         # Benutzerdefiniertes Analog-Uhr-Widget
│   ├── backup_dialog.py        # DB-Export/Import + Backup-Snapshot-Dialog
│   ├── ctrlw_settings.py       # Ctrl+W/Alt+W-Template-Konfigurations-UI
│   ├── cursor_theme.py         # Retro-Cursor-Theme-Overlay-Manager
│   ├── drop_overlay.py         # Drag-and-Drop-4-Optionen-Target-Overlay
│   ├── edit_guard.py           # Read-only-Edit-Lock-Guard-Wrapper
│   ├── editor.py               # VaultTextEdit: Codeblöcke, Gutter, Faltung
│   ├── fancy_zones.py          # Bildschirm-Snap-Zonen-Overlay-Picker
│   ├── file_container.py       # Silo-Asset-Datei-Schublade + Templates
│   ├── flags.py                # Vektor/Raster-Länderflaggen-Renderer
│   ├── flow_layout.py          # Dynamisches heightForWidth-Wrapping-Layout
│   ├── formatting_mixin.py     # Markdown-Formatierungs-Shortcuts
│   ├── hashtag_dialog.py       # Tag-Suche + Silo-Filter-Overlay
│   ├── header_format_dialog.py # Datums-/Zeitstempel-Formatdialog
│   ├── help_dialog.py          # Tastenkombinationen + interaktive Anleitung
│   ├── hotkey_mixin.py         # Hotkey-Bindungs-Mixin für Hauptfenster
│   ├── layout_shortcuts.py     # Physische-VK-Shortcut-Zuordnung (layoutunabh.)
│   ├── markdown_highlighter.py # QSyntaxHighlighter für Live-Markdown
│   ├── pie_menu.py             # QuickListWidget-radiales Kontextmenü
│   ├── queue_panel.py          # Watcher-Queue-Dialog
│   ├── resizers.py             # Fenster-Größenänderungs-Handles
│   ├── scaling_mixin.py        # UI-DPI- + Schrift-Skalierungs-Mixin
│   ├── search_mixin.py         # Mehrwort-UND-Suchfilter
│   ├── send_selection_mixin.py # Auswahl über Watcher senden
│   ├── settings.py             # Präferenzen-Dialog (Themes, Hotkeys, Sounds)
│   ├── silo_kanban.py          # Markdown-Kanban-Board (T-630)
│   ├── silo_settings_dialog.py # Pro-Silo-Konfiguration (Farbe, Projektlinks)
│   ├── silo_table.py           # Markdown-Tabellen-Builder (T-630)
│   ├── kanban_widget.py        # Kanban-Board-Ansichts-Widget (silo_kanban-Backend)
│   ├── table_widget.py         # Tabellen-Ansichts-Widget (silo_table-Backend)
│   ├── silo_region.py          # Silo-Listenbereich: Drag, Lücken, Mehrfachauswahl
│   ├── snippet_ops_mixin.py    # Silo-Operationen (Papierkorb, Verschieben, Duplizieren, Leeren)
│   ├── snippet_panel.py        # Silo-Baum + F1-F10-Snippet-Buttons
│   ├── theme_mixin.py          # Vintage-Theme-Styling + QSS-Generator
│   ├── timer_dialog.py         # Pomodoro- + Alarm-Timer-Setup-Dialog
│   ├── timer_toast.py          # Schwebendes Benachrichtigungs-Toast-Widget
│   ├── toolbar_reorder.py      # Drag-and-Drop-Toolbar-Button-Sortierung
│   ├── trash_dialog.py         # Papierkorb + Wiederherstellungs-Dialog
│   ├── tray_mixin.py           # Systray-Icon + Kontextmenü
│   ├── watcher_dialog.py       # Watcher-Konfiguration + Skript-Manager-UI
│   ├── watcher_mixin.py        # Watcher-Engine-Fenster-Integration
│   ├── window_mixin.py         # Rahmenlose Bewegung, Snap, randlose Steuerung
│   ├── window_presets_dialog.py # Benutzerdefinierte Fensterpositions-Presets
│   └── zen_desktop.py          # 3-stufiger Zen/Solo-Desktop-Sweep (Ctrl+D)
│
├── theme/                      # Theme-Presets
│   └── themes.py               # 6 Retro-Win95-Farbthemen-Definitionen
│
└── utils/                      # Low-Level-Helfer
    ├── fonts.py                # System-Font-Loader, Fallback-Auflösung, no-AA
    ├── paths.py                # Portabler Pfadauflöser (exe + Benutzerdaten)
    ├── portable_backup.py      # Portabler-ZIP-Backup-Builder
    └── textfit.py              # Dynamische Textkürzung + Label-Fitting
```

## Subsystem-Verantwortlichkeiten

| Paket | Verantwortung |
|---|---|
| `core.state` | SQLite-WAL-Persistenz, Zustandssync, Undo-Stack, kategoriebezogene Aliased-Stores |
| `core.hotkey*` | Globaler Hotkey-Listener + Win32-VK-Filter, layoutunabhängiger Dispatch |
| `core.watcher` | Prompt-Queue, CDP/Win32-Automatisierung, Skill-Wrapper, Limit-Scanner |
| `core.i18n` | 33-Lokale-Übersetzungspaket + Proxy-Delegation von translations.py |
| `core.ctrlw` | Trenner-Template-Engine (Ctrl+W / Alt+W) |
| `core.timers` | Timer-Modell, Fälligkeitserkennung, Serialisierung |
| `core.pomodoro` | Arbeits-/Pausen-Zustandsmaschine, Fokus-Timer |
| `ui.editor` | VaultTextEdit — Faltung, Gutter, Checkboxen, Heatmap, Randmarkierungen, Hide-Markup |
| `ui.snippet_panel` | Silo-Baum, Hierarchie, Kategorie-Tabs, F1-F10-Slots, Seitenleisten-Lücken, Mehrfachauswahl |
| `ui.silo_kanban` | Reintext-Kanban-Board (Alt+Pfeile bewegen Karten, Enter neue Zeile) |
| `ui.silo_table` | Reintext-Tabellen-Editor (Tab durchläuft Zellen, Enter neue Zeile) |
| `ui.file_container` | Pro-Silo-Ordner-Schublade, Asset-Vorschau, Templates |
| `ui.theme_mixin` | 6 Retro-Win95-Themes + Custom-Farb-Engine + QSS-Generator |
| `ui.kanban_widget` | Kanban-Board-Ansichts-Widget (silo_kanban-Backend) |
| `ui.table_widget` | Tabellen-Ansichts-Widget (silo_table-Backend) |
| `ui.silo_region` | Silo-Listenbereich: Drag, Lücken, Mehrfachauswahl |
| `ui.fancy_zones` | Visueller Zonen-Picker mit 7 Layout-Presets |
| `ui.window_presets_dialog` | Benutzerdefinierte Fenstergeometrie-Presets (Ctrl+Q-Seite) |
| `ui.zen_desktop` | 3-stufiges Ctrl+D: Zen, Solo (andere minimieren), zurück |
| `ui.toolbar_reorder` | Drag-and-Drop-Toolbar-Button-Anpassung |
| `ui.flow_layout` | Responsives Wrapping-Layout für kompakte Einstellungs-Panels |
| `ui.edit_guard` | begin/endEditBlock-Guard — verhindert Freeze durch nicht beendete Edits |
| `utils.fonts` | Schriftauflösung, Bitmap-Font-Installation, no-AA-Fallback |
| `utils.paths` | Portabler Betrieb — keine Registry, keine AppData-Abhängigkeit |

## Modulzählung-Zusammenfassung

- **core/**: 15 Module + i18n/ (33 Lokale + 5 Infra-Dateien = 38) + watcher/ (10 Module)
- **ui/**: 44 Module
- **theme/**: 1 Modul
- **utils/**: 4 Module
- **Gesamt**: 112 `.py`-Dateien unter `src/fastprompter/` (einschließlich `main.py` + `__init__.py`)
