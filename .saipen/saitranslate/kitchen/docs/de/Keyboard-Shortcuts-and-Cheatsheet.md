# FastPrompter Tastenkombinationen & Cheatsheet

Vollständiger tastaturgesteuerter Betrieb. Layoutunabhängiger VK-Dispatch — funktioniert auf QWERTY, JCUKEN, AZERTY, QWERTZ.

## Schnellreferenz

| Kategorie | Hotkey | Aktion | Bereich |
|---|---|---|---|
| **Global** | **Alt+X** | Fenster aufrufen / ausblenden | Systemweit |
| **Global** | **Shift+Alt+X** | Pie-Menü öffnen | Systemweit |
| **Global** | **Ctrl+Alt+Shift+Q** | Notfall-Force-Quit | Systemweit |
| **Fenster** | **Ctrl+D** | Zen/Solo/normal durchlaufen (3-stufig) | Haupt |
| **Fenster** | **Ctrl+Q** | Snap-Position / Presets durchlaufen | Haupt |
| **Fenster** | **Alt+S** | Fensterpositionssperre umschalten | Haupt |
| **Fenster** | **Alt+E** | Immer-im-Vordergrund umschalten | Haupt |
| **Fenster** | **Alt+D** | Seitenleiste umschalten | Haupt |
| **Fenster** | **Alt+A** | Hide-on-Focus-Loss umschalten | Haupt |
| **Fenster** | **Alt+`** | Mini-Einstellungen öffnen | Haupt |
| **Watcher** | **Alt+C** | Aktuelle Zeile für Watcher in Queue | Haupt |
| **Watcher** | **Alt+Shift+C** | Queue-Master-Dialog öffnen | Haupt |
| **Navigation** | **Ctrl+1**…**Ctrl+0** | Zu Silo 1–10 springen | App |
| **Navigation** | **Alt+↑** / **Alt+↓** | Silos durchlaufen | App |
| **Navigation** | **Ctrl+N** | Neues leeres Silo | App |
| **Navigation** | **Ctrl+F** | Im Silo suchen | Editor |
| **Navigation** | **Ctrl+H** | Suchen und ersetzen | Editor |
| **Navigation** | **Ctrl+Shift+S** | Aktives Silo als .md exportieren | App |
| **Formatierung** | **Ctrl+E** | Header formatieren (konfigurierbar) | Editor |
| **Formatierung** | **Ctrl+Return** | Checkbox `- [ ]` / `- [x]` umschalten | Editor |
| **Formatierung** | **Ctrl+W** | Trenner `---` einfügen (Smart-Split) | Editor |
| **Formatierung** | **Alt+W** | Trenner nach oben + Aufzählung einfügen | Editor |
| **Formatierung** | **Ctrl+B** | Fett umschalten | Editor |
| **Formatierung** | **Ctrl+I** | Kursiv umschalten | Editor |
| **Formatierung** | **Ctrl+U** | Unterstreichen umschalten | Editor |
| **Formatierung** | **Ctrl+T** | Durchgestrichen umschalten | Editor |
| **Formatierung** | **Ctrl+Shift+Q** | Blockquote umschalten | Editor |
| **Formatierung** | **Alt+Z** | Zeilennummern umschalten | Editor |
| **Formatierung** | **Alt+Backspace** | Vorheriges Wort löschen | Editor |
| **Formatierung** | **Ctrl+Z** | Smart Undo (pro Silo) | Editor |
| **Formatierung** | **Ctrl+Mitteltaste** | Zeile unter Cursor löschen (Smart-List-Reflow) | Editor |
| **Formatierung** | **Ctrl+Klick auf Aufzählung** | `-` / `•` umschalten | Editor |
| **Snippets** | **F1**…**F10** | Snippet 1–10 einfügen | App |
| **Snippets** | **Ctrl+Shift+1**…**9** | Snippet 1–9 einfügen (alternativ) | App |
| **Snippets** | **Ctrl+S** | Snippet-Manager öffnen | App |
| **SAIPEN** | **Ctrl+Shift+C** | SAIPEN-Viewer öffnen | App |
| **Timer** | **Ctrl+Shift+T** | Timer-Dialog öffnen | App |
| **Hashtags** | **Alt+Shift+T** | Hashtag-Dialog öffnen | App |
| **Anhänge** | **F2** | Datei-Container-Anhang umbenennen | Datei-Container |
| **Anhänge** | **Delete** | Anhang in Papierkorb löschen | Datei-Container |
| **Kanban** | **Alt+↑↓** | Karte hoch/runter (im Kanban-Silo) | Editor |
| **Kanban** | **Alt+←→** | Karte in linke/rechte Spalte (Kanban) | Editor |
| **Tabelle** | **Tab** | Zur nächsten Zelle (im Tabellen-Silo) | Editor |
| **Tabelle** | **Shift+Tab** | Zur vorherigen Zelle | Editor |
| **Allgemein** | **Esc** | Fenster ausblenden / Overlay schließen | System/Lokal |
| **Allgemein** | **Alt+X** (doppelt) | Immer-im-Vordergrund umschalten | Global |
| **Allgemein** | **Ctrl+Plus/Minus** | Zoom-Skalierung | App |

## Kategoriegruppen

### Global: Aufruf, Pie-Menü, Notfall
**Alt+X** — Fenster am Cursor umschalten. **Shift+Alt+X** — radiales Pie-Menü (Themes, Skalierung, Werkzeuge). **Ctrl+Alt+Shift+Q** — Prozess beenden.

### Fensterverwaltung
**Ctrl+D** — 3-stufig: Zen (nur Minimal-Editor) → Solo (alle anderen Fenster minimieren) → zurück zu normal. **Ctrl+Q** — 7 Snap-Zonen, FancyZone-Picker und Benutzer-Presets durchlaufen. **Alt+S/E/D/A** — Geometrie sperren, oben-anpinnen, Seitenleiste zeigen, Focus-Loss-Ausblenden umschalten.

### Watcher-Queue
**Alt+C** — aktuelle Zeile unter dem Caret in Queue. Blockverankert, überlebt Bearbeitungen darüber. **Alt+Shift+C** — Queue Master: Queues aller Silos prüfen/sortieren/leeren.

### Markdown-Formatierung
Alle Formatierungs-Shortcuts schalten Inline-Marker um: **Ctrl+B** → `**fett**`, Ctrl+I → `*kursiv*`, Ctrl+U → `<u>unterstrichen</u>`, Ctrl+T → `~~durchgestrichen~~`, Ctrl+Shift+Q → `> Zitat`.

**Ctrl+W** fügt `---`-Trenner + Smart-Zeilensplit ein. **Alt+W** fügt Trenner nach oben + Aufzählung über dem Cursor ein. Beide über Einstellungen → Trenner konfigurierbar.

**Ctrl+Klick auf Aufzählung** durchläuft `-` / `•`. **Ctrl+Return** schaltet `- [ ]` / `- [x]` um.

**Ctrl+E** — aktuelle Zeile als Header formatieren. Konfigurierbar: Regeltyp, Aufzählung, Zeitstempel, Ausrichtung. Anpassen unter Einstellungen → Trenner & Header.

**Ctrl+Mitteltaste** — ganze Zeile mit Smart-Reflow löschen: nummerierte Listen nummerieren neu, Aufzählungslisten schließen Lücken.

### Silo-Navigation
**Ctrl+1** bis **Ctrl+0** springen zu Silos 1-10. **Alt+↑↓** durchläuft sequenziell. **Ctrl+N** fügt unten ein leeres Silo an.

### Snippet-Makros
**F1-F10** fügen vorkonfigurierte Textvorlagen ein. Inhalte über Snippet-Manager (**Ctrl+S**) oder Rechtsklick auf F-Button binden.

### SAIPEN + Timer
**Ctrl+Shift+C** — SAIPEN-Viewer (STATE/BOARD/LOG) öffnen. **Ctrl+Shift+T** — Timer-Dialog öffnen. **Alt+Shift+T** — Hashtag-Suche öffnen.

### Kanban & Tabelle (T-630)
In einem Kanban-Silo: **Alt+Pfeile** bewegen Karten. In einem Tabellen-Silo: **Tab/Shift+Tab** durchläuft Zellen, **Enter** fügt eine Zeile hinzu.

### Layoutunabhängigkeit
Alle Shortcuts verwenden physische VK-Codes über `HotkeyFilter` + `layout_shortcuts.py`. Funktioniert unabhängig vom aktiven Tastaturlayout. Bindet nach Tastenposition, nicht nach Zeichen.
