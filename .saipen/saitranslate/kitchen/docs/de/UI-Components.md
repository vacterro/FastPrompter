# FastPrompter UI-Komponenten-Referenz

## Layout-Modell

Vintage-Win95-Ästhetik. Rahmenlos, dunkelgolden, scharfe Bevels. Tastatur-zuerst. Header passt Dichte-Stufen automatisch an (full → dense <1280px → ultra <700px).

```
+------------------------------------------------------------------+
| [Tab1][Tab2]... | 🔍 | 📌🎨⚙️🕒🧠 | LN:42 | Tok:156 | DD.MM - HH:MM | ⚙ | » | [_][X] |
+--------------------------------+---------------------------------+
| SIDEBAR (silos + snippets)     | EDITOR (VaultTextEdit)          |
| ┌──────────────────────────┐   | ┌──────┬────────────────────┐  |
| │ Silo 00  📌 ✅   📁  📁│   | │  1.  │ # Heading           │  |
| │ Silo 01       📁       │   | │  2.  │ Regular text here   │  |
| │ ─── gap ───            │   | │  3.  │ - [ ] checkbox      │  |
| │   └─ child silo  📁    │   | │  4.  │ ```python           │  |
| │ Silo 02  🎨     📁    │   | │      │ print("code")        │  |
| │ [F1][F2]...[F10]       │   | │      │ ```                 │  |
| └──────────────────────────┘   | └──────┴────────────────────┘  |
|                                | FILE CONTAINER DRAWER           |
|                                | [📁 file1] [📁 file2] [📁 IN/OUT]|
+--------------------------------+---------------------------------+
| Timer: 12:34  📊               |  Words: 240  |  Lines: 42       |
+------------------------------------------------------------------+
```

## Primärkomponenten

### 1. Header-Toolbar

Konfigurierbare Button-Leiste. Tokens: Kat-Tabs, Suche, Silo-Steuerung, Formatierung, Uhr, Zeilenzahl, Tokenzahl, Einstellungen, Tray-Buttons. Drag-and-Drop-Sortiermodus (Einstellungen → Toolbar anpassen). Overflow-Menü im Ultra-Schmalmodus.

**Dichte-Stufen:**
- **Full** (>1280px effektiv): alle Buttons sichtbar
- **Dense** (<1280px): Label-Kürzung + 18px-Quadrate + Tabs-Scroll; ausgeblendet: Clear Fmt, Line, Home/End, Underline, Strike, Copy, Vision, Aligns
- **Ultra** (<700px): Hochformat-Sliver; nur Tabs, NEW/Save, kurze Uhr, Zähler, ⚙ überleben. » Overflow-Menü sammelt den Rest

### 2. Snippet- & Silo-Panel (`ui/snippet_panel.py`)

**Silo-Liste:** Bis zu 100 pro Projekt-Tab. Funktionen:
- Pin (📌) — oben verankern, über Ungepinnten sortiert
- Haken (✅) — Siloübergreifender-Erledigt-Marker
- Farbbox (🎨) — Farbtönung pro Silo (in Einstellungen umschaltbar)
- Datei-Container-Icon (📁) — öffnet Datei-Schublade
- Hierarchie — auf ein anderes Silo ziehen zum Verschachteln; Shift+Ziehen tauscht; Faltpfeil (▾/▸)
- Aktualitäts-Heatmap — warme Hintergrundtönung für kürzlich bearbeitete
- Seitenleisten-Lücken — benutzerdefinierte Abstandsbalken; Ctrl+Ziehen zum Umparken
- Mehrfachauswahl — Shift=Bereich, Ctrl=Umschalten; Batch-Löschen/Speichern/Leeren

**Snippet-Slots (F1-F10):** 10 Makro-Einfüge-Buttons pro Projekt-Tab. Rechtsklick zum Bearbeiten von Name/Inhalt. Ctrl+S oder Doppelklick öffnet den Snippet-Manager-Dialog.

### 3. Markdown-Editor (`ui/editor.py` — VaultTextEdit)

**Zeilen-Gutter:** Linker Rand — Zeilennummern + Faltpfeile (▾) + Randmarkierungen + Heat-Streifen.

**Syntax-Highlighting:** `# Überschriften`, `**fett**`, `*kursiv*`, `~~durchgestrichen~~`, `[Links](url)`, `` `Code` ``, ```Codeblöcke```, `- [ ]` Checkboxen, `> Blockquotes`, `---` Regeln.

**Code-Fences:** Monospace (Consolas-Standard) + Ein-Klick-Kopier-Button + Faltung zum Einklappen.

**Einklappbare Bilder:** `![alt](url)` → kompakter 150px-Button. Ctrl+Klick öffnet, Ctrl-R-Klick öffnet Ordner. Doppelklick auf die Pill benennt Datei auf Platte und Link zusammen um (ein Undo-Schritt).

**Interaktive Checkboxen:** Klick auf `- [ ]` schaltet auf `- [x]` um.

**Hide-Markup-Modus (T-603):** Umschalten blendet `**`, `*`, `~~`, `` ` ``-Marker aus → Text liest sich wie gerendert. Caret-Block behält Marker für die Bearbeitung.

**Drop-Overlay:** 4 Optionen beim Drag-Drop: Text einfügen, Link einfügen, In Dateien kopieren, Verknüpfung erstellen.

### 4. Datei-Container-Schublade (`ui/file_container.py`)

Pro-Silo-einklappbare Schublade. Angehängte Dateien, Bild-Thumbnails, Dokumentverknüpfungen.

- Templates: IN/OUT, Assets, Drafts, benutzerdefinierte Ordnerstruktur
- Drag-Drop zum Hinzufügen von Dateien
- Silo-Export: Ctrl+Klick 📁 exportiert Silo-Text als .md

### 5. Kanban-Board (`ui/silo_kanban.py`)

Reintext-Markdown-Kanban. Alt+Pfeile bewegen Karten zwischen Spalten. Enter fügt Zeile hinzu. Checkbox-Klick hakt Karte ab. Keine Qt-Tabellen — funktioniert auf einfachem Markdown, überlebt Speichern.

### 6. Tabellen-Builder (`ui/silo_table.py`)

Reintext-Markdown-Tabelle. Tab/Shift+Tab durchläuft Zellen. Tab an letzter Zelle wächst Zeile. Enter fügt Zeile hinzu. Kein Zellen-Split. Funktioniert auf Klartext.

### 7. Dialoge & Overlays

| Dialog | Zweck |
|---|---|
| `Einstellungen (Alt+`)` | Theme-Picker, Hotkey-Neubindung, Sound, Skalierung, Toolbar-Sortierung |
| `Snippet-Manager (Ctrl+S)` | F1-F10-Snippet-Namen + -Inhalte bearbeiten |
| `Timer-Dialog (Ctrl+Shift+T)` | Pomodoro- + Countdown-Timer-Setup |
| `Queue Master (Alt+Shift+C)` | Watcher-Queue-Übersicht pro Silo |
| `Hashtag-Dialog (Alt+Shift+T)` | Siloübergreifende Tag-Suche |
| `Papierkorb-Dialog` | Weich gelöschte Silos durchsuchen/wiederherstellen |
| `Backup-Dialog` | DB-Export/Import, Backup-Snapshot |
| `Hilfe-Dialog` | Interaktive Shortcut-Referenz |
| `Fenster-Presets` | Fenstergeometrie-Presets speichern/umbenennen/sortieren/verschieben |
| `Projekt-Manager` | Projekte ein-/ausblenden, sortieren (▲▼) |
| `Farb-Konfiguration` | Custom-Theme-Farben bearbeiten |

### 8. Fensterkomponenten

- **FancyZoneOverlay** — visueller 7-Zonen-Picker für Bildschirm-Snap
- **AnalogClock** — benutzerdefiniertes Uhr-Widget (Header)
- **PieMenu (Shift+Alt+X)** — radiales Menü: Themes, Skalierung, Werkzeuge
- **Overflow-Menü (»)** — ausgeblendete Buttons im Ultra-Modus
- **Resizers** — benutzerdefinierte Größenänderungs-Handles (T-629-Fix: WS_CAPTION-Neuberechnung)
- **ZenDesktop** — 3-stufiges Ctrl+D: Zen → Solo (alle minimieren) → zurück
