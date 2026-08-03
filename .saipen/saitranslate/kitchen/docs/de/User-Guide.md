# FastPrompter Benutzerhandbuch

## Übersicht

Hochgeschwindigkeits-Tastatur-Scratchpad + Prompt-Workbench. Alt+X ruft am Cursor auf. Schreiben. Schließen (Esc). Null manuelles Speichern — SQLite synchronisiert alle 10 s.

---

## Schlüsselkonzepte

### 1. Aufruf (Alt+X)

Globaler Hotkey. Fenster erscheint am Mauszeiger. Esc schließt. Alle Tastatureingaben werden über den Auto-Save-Timer (10-s-Tick) + Sync-Flush beim Schließen auf Disk gespült.

Doppel-Tap Alt+X schaltet Immer-im-Vordergrund um. Shift+Alt+X öffnet das Pie-Menü (Theme/Skalierung/Werkzeuge).

### 2. Projekte (Tabs)

Benannte Projekt-Tabs im Header. Rechtsklick: Erstellen, Umbenennen, Löschen. Bis zu 100 Projekte. Umschalten per Klick oder Nummernbox-Modus (Einstellungen → Fenster → Layout → Nummernboxen pro Reihe). Jedes Projekt hält 100 Silos + 10 Snippets.

### 3. Silos

Unabhängige Markdown-Canvas-Slots. 100 pro Projekt. Automatisch nummeriert 00-99.

**Navigation:**
- Ctrl+1..Ctrl+0 — zu Silo 1-10 springen
- Alt+↑/↓ — Silos durchlaufen
- Ctrl+N — neues leeres Silo (fügt unten an)
- Rechtsklick NEW — unten anfügen

**Aktionen pro Silo (Hover):**
- 📌 **Pin** — Silo oben in der Liste sperren (über Ungepinnten sortiert)
- ✅ **Haken** — als erledigt markieren (visueller Indikator)
- 🎨 **Farbbox** — Farb-Highlight pro Silo (in Einstellungen umschaltbar)
- 📁 **Datei-Container** — Asset-Schublade für dieses Silo öffnen
- 📁 **Ordner-Link** — Silo mit externem Projektordner/-Programm verknüpfen
- **Mittelklick** — in den Papierkorb senden

**Hierarchie:** Silo auf ein anderes ziehen, um es als Kind zu verschachteln. Max. Tiefe 2 (1 → 1.1 → 1.1.1). Shift+Ziehen tauscht. Faltpfeil (▾/▸) am Elternteil blendet Kinder aus.

**Aktualitäts-Heatmap:** Kürzlich bearbeitete Silos erhalten warme Hintergrundtönung. Konfigurierbar über Einstellungen → Silos.

### 4. Seitenleisten-Lücken

Benutzerdefinierte Abstandsbalken in der Silo-Liste. Helfen, Silos in Gruppen zu organisieren. Ctrl+Ziehen einer Lücke parkt sie woanders hin. Einstellungen → Silos → Lückenhöhe steuert die Dicke.

### 5. Mehrfachauswahl-Silos

- Shift+Klick — Bereichsauswahl
- Ctrl+Klick — Auswahl umschalten
- Rechtsklick auf Auswahl — Batch Speichern, Löschen, Leeren (löscht zuerst hohe Indizes, um Slot-Shift-Probleme zu vermeiden)

### 6. Snippet-Makros (F1-F10)

10 Schnelleinfüge-Slots pro Projekt. Gebunden an F1-F10 oder Ctrl+Shift+1-9.

- Ctrl+S — Snippet-Manager öffnen (Name + Inhalt bearbeiten)
- Rechtsklick auf F-Button — inline umbenennen
- Unterstützt Variablen-Platzhalter für Prompt-Templates

### 7. Markdown-Editor

**VaultTextEdit** — erweitertes QPlainTextEdit.

**Funktionen:**
- Live-Syntax-Highlighting — Überschriften, fett, kursiv, Links, Code-Fences, Checkboxen, Blockquotes
- Zeilen-Gutter — Nummern + Faltpfeile (▾)
- Abschnittsfaltung — Klick auf ▾ klappt Überschriften ein
- Code-Fence-Kopier-Button — Fence hoveren, Kopier-Icon klicken
- Checkbox-Klick — Klick auf `- [ ]` schaltet auf `- [x]` um
- Einklappbare Bilder — `![alt](url)` als kompakte Pillen-Button (150px). Ctrl+Klick öffnet, Ctrl-R-Klick öffnet Ordner. Doppelklick auf die Pill benennt Datei und Link zusammen um
- Smart-Paste — bereinigt Tabellen-/Listen-/Code-Formatierung

**Formatierungs-Shortcuts:**
- Ctrl+B/I/U/T — fett/kursiv/unterstrichen/durchgestrichen
- Ctrl+Return — Checkbox umschalten
- Ctrl+E — Header einfügen (konfigurierbar: Regel, Aufzählung, Zeitstempel, Ausrichtung)
- Ctrl+W — Trenner `---` mit Smart-Zeilensplit einfügen (entfernt doppelte Aufzählung)
- Alt+W — Trenner nach oben + Aufzählung darüber einfügen
- Ctrl+Shift+Q — Blockquote umschalten
- Ctrl+Klick auf Aufzählung — `-` / `•` umschalten
- Ctrl+Mitteltaste — Zeile unter Cursor löschen (Smart-Reflow: nummerierte Listen nummerieren neu)
- Alt+Z — Zeilennummern umschalten
- Alt+Backspace — Wort löschen

### 8. Hide-Markup-Modus (T-603)

Umschalten in Einstellungen → Editor → Hide Markup. Blendet **fett**, *kursiv*, ~~durchgestrichen~~ und `Code`-Marker aus, damit der Text sauber liest. Der Caret-Block behält seine Marker, damit Bearbeiten möglich bleibt. Rendert nur die 2 Blöcke um die Caret-Bewegung neu.

### 9. Kanban-Board

Kanban einfügen erstellt ein Markdown-Kanban-Board (reiner Text, überlebt Speichern/DB-Roundtrip).

- Alt+↑/↓ — Karte innerhalb der Spalte hoch/runter
- Alt+←/→ — Karte in benachbarte Spalte
- Enter auf leerer Board-Zeile — neue Kartenzeile
- Alt+Klick — Checkbox auf Karte abhaken

### 10. Tabellen-Builder

Tabelle einfügen erstellt eine Markdown-Tabelle. Tab/Shift+Tab durchläuft Zellen. Tab an letzter Zelle wächst eine neue Zeile. Enter fügt Zeile hinzu (kein Zellen-Split).

### 11. Datei-Container

Jedes Silo erhält `data/silo_files/<projekt>/<slot_idx>/` auf Disk.

- Dateien auf das Schubladen-Overlay ziehen → in Silo-Ordner kopieren
- Drop-Overlay (4 Optionen): Text einfügen, Link einfügen, In Dateien kopieren, Verknüpfung
- Templates: IN/OUT, Assets, Drafts, Benutzerdefiniert
- Bildvorschau + mit Standard-App öffnen
- Ctrl+Klick 📁 — Silo-Text als .md exportieren

### 12. Watcher-Engine (Alt+C)

Prompt-Ableitung + Auto-Senden an Ziel-App.

- Alt+C — aktuelle Zeile unter dem Caret in Queue (blockverankert)
- Alt+Shift+C — Queue-Master-Dialog (Queues prüfen/sortieren/leeren)
- Scharfschalten: Ziel-App (CDP für Electron, Win32 für nativ), Skill/Prompt-Wrapper
- Rate-Limits: settle=2,5 s, min gap=4 s, max. 25 Sendungen pro Sitzung
- Skills: `/review`, `/refactor`, benutzerdefinierte Prompt-Templates

Siehe [Watcher-Engine-Architektur](Watcher-Engine-Architecture) für Details.

### 13. Hashtag-System

`#tag` im Silo-Text wird für Siloübergreifende Suche indiziert. Alt+Shift+T öffnet den Hashtag-Dialog — nach Tag suchen, alle passenden Silos sehen, per Klick springen.

### 14. Timer & Pomodoro

**Countdown-Timer:** Über Ctrl+Shift+T oder Timer-Button setzen. Konfigurierbar: Name, Dauer, Sound, Lautstärke, Farb-Dringlichkeit. Timer-Toast-Benachrichtigung mit Schlummern (Win95-3D-Bevles).

**Pomodoro:** Arbeits-/Pausen-Zustandsmaschine. Konfigurierbare Intervalle. Tray-Benachrichtigung + Sound bei Phasenende. Timer-Label neben der Uhr zeigt Restzeit + Dringlichkeitsfarbe.

### 15. Zen-Modus (Ctrl+D)

3-stufiger Zyklus:
1. **Zen** — Seitenleiste, Snippet-Leiste, Datei-Container, Statusleiste, Rahmen ausblenden. Nur Editor sichtbar.
2. **Solo** — alle anderen Desktop-Fenster minimieren. Editor bleibt.
3. **Zurück** — Desktop + normales Layout wiederherstellen.

### 16. Fenster-Snap (Ctrl+Q)

Durchlaufen: Oben-Links, Oben-Rechts, Unten-Links, Unten-Rechts, Mitte, Voll, Cursor-Position. FancyZone-Overlay zeigt 7 visuelle Zonen beim Klick. Fenster-Presets-Seite speichert bis zu 10 benutzerdefinierte Geometrien (als Bildschirmfraktionen — überleben Monitorwechsel).

### 17. Finder & Archiv

- **Silo archivieren** — fertiges Silo ins Archiv verschieben (Text behalten, aus aktiver Liste entfernen)
- **Archiv-Tab** — archivierte Silos pro Projekt durchsuchen
- **Papierkorb-Dialog** — weich gelöschte Silos und Dateien durchsuchen/wiederherstellen
- **Silo-Sync auf Disk** (T-591) — Einweg-.md-Export in externen Ordner pro Projekt

### 18. Nummernbox-Modus (T-607)

Einstellungen → Fenster → Layout → Nummernboxen pro Reihe. Ersetzt Projekt-Combo durch nummerierte Buttons. Rechtsklick für Hinzufügen/Umbenennen/Löschen. Rad schaltet weiter. Projekt-Cap 100.

### 19. Toolbar-Anpassung

Einstellungen → Toolbar anpassen. Buttons zum Sortieren ziehen. Sichtbare Lücken-Widgets zeigen, wo ein Button landet. Reset stellt die Standardreihenfolge wieder her.

### 20. Overflow-Menü

Wenn Header < 700px: ausgeblendete Buttons in »-Popup gesammelt. Jede Aktion bleibt erreichbar — Formatierung, Navigation, Silo-Operationen, Werkzeuge.

### 21. Editor-Maus & Zeilen-Drag

**Ctrl+Shift+Ziehen** — Zeile unter dem Zeiger (oder den ganzen markierten Block) zum Ablageindikator bewegen. Rich-Formatierung überlebt den Weg — Fett, Kontrollkästchen und Bild-Pills wandern als Dokumentfragment, nicht als Klartext.

**Alt+Mitteltaste** — ausgewählte Zeilen in Aufzählungen verwandeln. **Mitteltaste** — Zeilenzustand zyklisch: normal → markiert+durchgestrichen → unmarkiert. **Ctrl+Mitteltaste** — ganze Zeile mit Smart-List-Reflow löschen.

**Doppelklick auf Bild-Pill** — Datei auf Platte und Markdown-Link zusammen umbenennen, ein Undo-Schritt.

### 22. Backup

**Ebenen:**
1. SQLite-WAL — crashsichere Schreibvorgänge (synchronous=NORMAL)
2. .bak — beim Start + alle 60 s (vollständiges SQLite-Backup in .bak-Datei)
3. Täglicher Markdown-Spiegel — `~/Documents/.fastprompter/` (Silos pro Projekt + Archiv + Snippets)
4. Portables ZIP — manuelles Backup über den Backup-Dialog
