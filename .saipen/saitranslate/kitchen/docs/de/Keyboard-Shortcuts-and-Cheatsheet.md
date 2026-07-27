# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions—from summoning the window to line formatting, queue management, silo navigation, and macro pasting—have dedicated keyboard shortcuts.

---

## Quick Reference Table

| Kategorie | Hotkey | Aktion | Umfang / Kontext |
|---|---|---|---|
| **Global** | **Alt+X** | FastPrompter-Fenster beschwören/ausblenden | Systemweit (jede App) |
| **Beobachter** | **Alt+C** | Tippüberwachung / Status anzeigen umschalten | Hauptfenster |
| **Beobachter** | **Alt+Umschalt+C** | Warteschlangenmaster-Dialogfeld öffnen | Hauptfenster |
| **Fenster** | **Strg+D** | Zen-Fokus-Modus umschalten (Panels/Chrom ausblenden) | Hauptfenster |
| **Fenster** | **Strg+Q** | Fangposition wechseln (Oben links, Oben rechts, Mitte, Cursor) | Hauptfenster |
| **Fenster** | **Alt+S** | Fenstersperre umschalten (Stiftgröße und -position) | Hauptfenster |
| **Fenster** | **Alt+E** | Angehefteten Status „Always-on-Top“ umschalten | Hauptfenster |
| **Fenster** | **Alt+D** | Sichtbarkeit der Seitenleiste umschalten | Hauptfenster |
| **Fenster** | **Alt+A** | Verhalten beim Ausblenden beim Klicken umschalten | Hauptfenster |
| **Fenster** | **Alt+`** | Öffnen Sie das Mini-Einstellungen-Overlay | Hauptfenster |
| **Fenster** | **Strg+Alt+Umschalt+Q** | Notfall erzwingen Sie das Beenden von FastPrompter | Systemweit |
| **Navigation** | **Strg+1** .. **Strg+0** | Springe direkt zu Silo 1 bis 10 | Bewerbung |
| **Navigation** | **Alt+Up** / **Alt+Down** | Vorwärts/rückwärts durch aktive Silos gehen | Bewerbung |
| **Navigation** | **Strg+N** | Neues leeres Silo erstellen | Bewerbung |
| **Navigation** | **Strg+F** | Öffnen Sie die Suchleiste „Suchen“ | Herausgeber |
| **Navigation** | **Strg+H** | Öffnen Sie die Such- und Ersetzungsleiste „Ersetzen“ | Herausgeber |
| **Navigation** | **Strg+Umschalt+S** | Aktiven Silo-Text in Datei exportieren | Bewerbung |
| **Formatierung** | **Strg+E** | Zeile als H1-Header mit Zeitstempel formatieren | Herausgeber |
| **Formatierung** | **Strg+Eingabetaste** | Aktivieren Sie das Kontrollkästchen „- [ ]“ / „- [x]“ in der aktuellen Zeile | Herausgeber |
| **Formatierung** | **Strg+W** | Fügen Sie die horizontale Trennlinie „---“ mit Abstand ein | Herausgeber |
| **Formatierung** | **Alt+W** | Fügen Sie die Trennlinie „---“ und das neue Aufzählungszeichen „-“ | ein Herausgeber |
| **Formatierung** | **Strg+B** | **Fettgedruckter** Text (`**Text**`) umschalten | Herausgeber |
| **Formatierung** | **Strg+I** | *Kursiv*-Text umschalten („*text*`) | Herausgeber |
| **Formatierung** | **Strg+U** | Toggle <u>Text unterstreichen</u> (`<u>text</u>`) | Herausgeber |
| **Formatierung** | **Strg+T** | Toggle ~~Durchgestrichener~~ Text (`~~text~~`) | Herausgeber |
| **Formatierung** | **Strg+Umschalt+Q** | Toggle Blockquote-Block (`> text`) | Herausgeber |
| **Formatierung** | **Alt+Z** | Zeilennummern im Randbereich des Editors umschalten | Herausgeber |
| **Formatierung** | **Alt+Rücktaste** | Vorheriges Wort löschen | Herausgeber |
| **Formatierung** | **Strg+Z** | Intelligente Bearbeitungsaktion rückgängig machen | Herausgeber |
| **Ausschnitte** | **F1** .. **F10** | Fügen Sie Snippet 1 bis 10 in den Editor ein | Bewerbung |
| **Ausschnitte** | **Strg+Umschalt+1** .. **9** | Snippet 1 bis 9 einfügen (Alternative) | Bewerbung |
| **Ausschnitte** | **Strg+S** | Snippet-Manager öffnen / Aktives Snippet speichern | Bewerbung |
| **Anhänge** | **F2** | Ausgewählte Anhangdatei umbenennen | Dateicontainer-Panel |
| **Anhänge** | **Löschen** | Ausgewählte Anhangdatei in den Papierkorb löschen | Dateicontainer-Panel |
| **Allgemein** | **Esc** | FastPrompter-Fenster ausblenden / Aktives Overlay schließen | System / Lokal |

---

## Detailed Category Breakdown

### 1. Global & Window Management
- **Alt+X (Global Summon)**: Instantly brings FastPrompter to the foreground at your current mouse cursor coordinates. Pressing `Alt+X` again hides the window back to system tray.
- **Ctrl+D (Zen Mode)**: Hides sidebar, snippet bar, file container, status bar, and window framing for distraction-free writing.
- **Ctrl+Q (Corner Snap)**: Rotates window placement across predefined screen regions: Top-Left -> Top-Right -> Bottom-Left -> Bottom-Right -> Center -> Cursor Position.
- **Alt+S & Alt+E**: Lock window geometry to prevent accidental dragging (`Alt+S`) and pin window above all other desktop windows (`Alt+E`).

### 2. Typing Watcher & CDP Automation
- **Alt+C**: Toggles the automated typing watcher engine on/off. When armed, watches target application focus.
- **Alt+Shift+C**: Opens the Queue Master dialog to inspect, reorder, clear, or inject items into the active watcher drainage queue.

### 3. Markdown Formatting Shortcuts
- **Ctrl+E**: Converts current line into `# HH:MM - Heading`.
- **Ctrl+Return**: Converts regular text into `- [ ] text` or toggles `- [ ]` <-> `- [x]`.
- **Ctrl+W / Alt+W**: Inserts markdown dividers `---`. `Alt+W` automatically starts a new bullet point on the following line.
- **Ctrl+B / Ctrl+I / Ctrl+U / Ctrl+T**: Inline formatting for bold, italic, underline, and strikethrough.

### 4. Silo & Tab Navigation
- **Ctrl+1 .. Ctrl+0**: Instantly switches editor tab to Silo slot 1 through 10.
- **Alt+Up / Alt+Down**: Step through active silos sequentially without mouse interaction.
- **Ctrl+N**: Creates a new numbered scratch silo in the active project tab.

### 5. Snippet Macro Slots (`F1`-`F10`)
- **F1 .. F10**: Pastes pre-configured snippet templates directly at the editor cursor location.
- **Ctrl+Shift+1 .. 9**: Secondary hotkey binding for devices without dedicated function keys (e.g. compact keyboards).

---

## Physical Virtual Key (VK) Layout Fallbacks
FastPrompter features physical keyboard key mapping via `LayoutIndependentShortcuts`. Shortcuts continue to work reliably regardless of whether the active Windows keyboard layout is set to English (QWERTY), Russian (JCUKEN), German (QWERTZ), or French (AZERTY).

---
*FastPrompter-Wiki – erstellt mit [SAIPEN-Protokoll](SAIPEN-Protokoll) | [GitHub-Repository](https://github.com/vacterro/FastPrompter)*