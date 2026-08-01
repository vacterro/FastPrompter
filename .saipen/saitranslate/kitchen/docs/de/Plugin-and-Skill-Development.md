# Plugin-, Skill- & Erweiterungs-Entwicklungsanleitung

## 1. Benutzerdefinierte Skills (`core/watcher/skills.py`)

Skills sind Prompt-Wrapper, die angewendet werden, wenn Elemente über den Watcher gesendet werden.

### Definition

```python
# Skill-Eintrags-Dict
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review this code:\n\n{text}",
    "description": "Standard code review prompt wrapper"
}
```

### Template-Variablen
- `{text}` — der Text des Queued-Elements
- `{timestamp}` — aktuelle Zeit
- `{project}` — aktiver Projektname

### Anwenden
Standard-Skill in Einstellungen → Watcher → Standard-Skill festlegen. Pro Element im Queue-Master-Dialog überschreiben.

## 2. SAIPEN-Subagenten

Subagenten leben in `.saipen/extensions/subs/<name>/` (nicht im Projekt-Root `subs/`).

```
.saipen/extensions/subs/
├── MANIFEST.md          # aktive Sub-Liste
├── PROTOCOL.md          # Regeln
├── TEMPLATE/            # Bootstrap-Template
├── saiwiki/             # Wiki-Dokument-Generator-Subagent
├── saihunt/             # Bug-Jäger-Subagent
└── _shared/inbox.md     # Cross-Agent-Kommunikation
```

### Übergabe (OUTBOX.md)

```
# OUTBOX

## WIKI-001: Description
- **status:** ready | draft | blocked | reviewed
- **summary:** one line finding
- **critical:** true | false
- **details:** full description
```

`critical: true` → Hauptagent erstellt sofort ein T-###-Ticket.
`critical: false` → zur nächsten Planungsrunde in `_shared/inbox.md` eingereiht.

**Befehle:**
- `saipen sub spawn <name>` — neuen Subagenten aus TEMPLATE erstellen
- `saipen sub collect` — alle OUTBOX-Einträge einsammeln
- `saipen sub list` — aktive Subagenten + Phase anzeigen
- `saipen sub clean <name>` — fertigen Subagenten entfernen

## 3. Custom Themes

Datei: `data/custom_theme.json`. Wird geladen, wenn Theme = Custom.

### Schema

```json
{
  "theme_name": "My Theme",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_editor": "#1b1b1b",
    "fg_text": "#d4d4d4",
    "fg_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78",
    "header_bg": "#252526",
    "button_bg": "#2d2d30",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422"
  }
}
```

**Anwenden:** Einstellungen → Theme → Custom. Sofortiges Hot-Reload, kein Neustart.

## 4. Cursor-Themes (`ui/cursor_theme.py`)

Benutzerdefinierte Mauszeiger-Sets. Retro-Computing-Gefühl.

**Funktionen:**
- `capture_current_scheme()` — laufendes Windows-Cursor-Set ins Programm kopieren
- `load_bundle()` — installiertes Cursor-Set zurückgeben
- `install_to_system(paths)` — als Windows-Standard-Cursorschema festlegen
- `build_cursor_map()` — Cursor-Form-Karte neu aufbauen

**Umschalten:** Einstellungen → Cursor → Benutzerdefinierte Cursor aktivieren. Beim ersten Aktivieren wird das aktuelle Windows-Set automatisch erfasst.

## 5. Watcher-Engine-Erweiterbarkeit

| Modul | Erweiterungspunkt |
|---|---|
| `adapter.py` | ProbeAdapter für benutzerdefinierte Zielerkennung implementieren |
| `cdp.py` | Benutzerdefinierte CDP-Befehle für Electron-Apps |
| `win32.py` | Win32-Fenster-Probe-Anpassung |
| `skills.py` | Benutzerdefinierte Prompt-Skill-Templates hinzufügen |
| `limit_scan.py` | Benutzerdefinierter Cross-Agent-Limit-Scanner |
| `sender.py` | Benutzerdefinierte Text-Injektionsstrategien |

## 6. Silo-Sync auf Disk (T-591)

Einweg-Silo → Dateisystem-Export. Einstellungen → Sync-Modus: Off / Silo (flach) / Hierarchie (verschachtelt). Schreibt `<root>/<category>/<NN_slug>.md` beim Speichern. Liest nie zurück, löscht nie. Überspringt unveränderten Text.
