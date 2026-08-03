# FastPrompter Core API & Klassenreferenz

## Kernklassen (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

Thread-sicheres SQLite-Datenmodell. Zentraler Zustands-Hub — alle Silos, Snippets, Einstellungen, Themes, Queues laufen darüber.

**Methoden:**
- `__init__(profile_id=1)` — SQLite-Verbindung öffnen, WAL-Modus, gecachte Einstellungen laden
- `init_db()` — Schema erstellen/aktualisieren (presets, settings, temp_presets_v2, archive_temp_presets_v2), Start-.bak-Backup ausführen
- `switch_profile(new_profile_id)` — aktuelle DB schließen, Pfad wechseln, neu laden
- `save_data_to_db(text, ui_settings, force)` — atomarer Dirty-State-Flush
- `mark_dirty()` — Zustand als speicherbedürftig markieren (async über Auto-Save-Timer)
- `reset_data()` — In-Memory-Standards neu initialisieren

**Datenmodell:** Einzelnes `self.data`-Dict. Kategoriebezogene Speicher aliased: `temp_presets` → `temp_presets_all[active_cat]`, `silo_colors` → `silo_colors_all[active_cat]` usw. Alle `_all`-Schlüssel migrieren beim ersten Zugriff automatisch.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

Threaded-pynput-Tastatur-Listener für systemweite Hotkeys.

**Methoden:**
- `start()` — pynput-Listener-Thread starten
- `stop()` — Listener anhalten
- `update_hotkeys(hk_dict)` — Hotkey-Karte neu registrieren

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32-WH_KEYBOARD_LL-Hook. Fängt physische VK-Codes ab — layoutunabhängig. Funktioniert layoutübergreifend (QWERTY/JCUKEN/AZERTY). Wird für layout_shortcuts.py-Dispatch verwendet.

---

### `IpcServer` (`core/ipc_server.py`)

QLocalServer auf Named Pipe `FastPrompter_Server_V15`. UUID-Token-Auth über `%TEMP%/fastprompter_ipc.token`.

**Methoden:**
- `setup()` — Lauschen starten (räumt veraltete Socket-Namen mit removeServer auf)
- `close()` — Server stoppen
- `_handle_command()` — SHOW-Befehl der zweiten Instanz verarbeiten

**Helfer:**
- `try_connect_to_server()` — laufende Instanz prüfen (gibt QLocalSocket oder None zurück)

---

### `SoundManager` (`core/sound_manager.py`)

WAV-Wiedergabe für UI-Klicks, Schreibmaschinentasten, Timer-Alarme.

**Methoden:**
- `play_ui_click()`, `play_tick_sound()`, `play_typewriter()`, `play_sound(name)` — Audio dispatch
- Lautstärke über `sound_volume`-Einstellung (0-10)

---

### `PomodoroEngine` (`core/pomodoro.py`)

Arbeits-/Pausen-Zustandsmaschine mit konfigurierbaren Intervallen.

**Konstanten:** `PHASE_WORK`, `PHASE_BREAK`

**Methoden:**
- `start_work()`, `start_break()`, `pause()`, `reset()` — Lebenszyklus
- `tick(elapsed)` — Timer vorrücken, Phasenübergänge erzeugen
- `describe()` — menschenlesbare Zustandszeichenkette
- `from_dict(data)` / `to_dict()` — JSON-Serialisierung

---

### `Timer` & `TimerManager` (`core/timers.py`)

Generischer Countdown-Timer. Farbcodierte Dringlichkeit, Sound bei Fälligkeit, Schlummern.

**Timer-Attribute:** `name`, `description`, `target` (datetime), `sound`, `volume`, `color_mode`, `color`

**Methoden:**
- `remaining()` — Sekunden bis Ziel
- `snooze(minutes)` — Ziel nach vorne schieben
- `display_color()` — Dringlichkeitsfarbe (grün/gelb/rot)
- `collect_due(timers)` — fällige Timer-Liste zurückgeben
- `next_due(timers)` — nächstfälliger Timer
- `save_timers(data)` / `load_timers(data)` — Serialisierung

---

### `DurationParser` (`core/duration.py`)

Menschenlesbare Dauer-Parsing.

- `parse_duration(text)` — "2h 30m" → Sekunden
- `format_remaining(seconds, short=False, minutes=False)` — "2h 30m" → "2h" oder "4d 11h 05m"
- `format_duration(seconds)` — vollständige Formatzeichenkette

---

### `HashtagIndex` (`core/hashtags.py`)

Siloübergreifende Hashtag-Extraktion + Suche.

- `extract_tags(text)` — Satz von `#tag`-Zeichenketten zurückgeben
- `index_silo(cat, slot, text)` — Tag → Silo-Index
- `search(tag)` — alle Silos mit Tag über Kategorien hinweg

---

### `DividerEngine` (`core/ctrlw.py`)

Ctrl+W / Alt+W-Template-Einfügung.

- `insert_divider(editor, template, upward)` — horizontale Linie einfügen, doppelte Aufzählungen bei Teilung entfernen
- `simulate(editor, upward)` — Einfügeposition vorschauen

---

### `HeaderFormatter` (`core/header.py`)

Ctrl+E-Header-Einfügung. Konfigurierbar: Linienregel, Lücke, Aufzählung, Ausrichtung, Zeitstempel.

- `format_header(editor, config)` — aktuelle Zeile als Header formatieren

---

### Watcher-Engine-Module (`core/watcher/`)

| Modul | Rolle |
|---|---|
| `engine.py` | Endliche Zustandsmaschine: DISARMED → ARMED → WATCHING → SENDING |
| `cdp.py` | Chrome-CDP-Attach + Auswertung + Read-back-Verifizierung (Electron-Apps) |
| `win32.py` | Win32-Fenster-Probe — Vordergrund, Caret, Fokus-Erkennung |
| `probes.py` | Multi-Probe-Zustandskombinatoren + kombinierte Matrix |
| `queue.py` | QueueItem, SendIntent, Pinning, Pro-Queue-Schlüssel, Persistenz |
| `sender.py` | CDP + Win32-Tasteneingabe mit Read-back-Verifizierung |
| `skills.py` | Prompt-Skill-Wrapper — Präfix/Template-Transformationen |
| `adapter.py` | Abstrakte Probe-Adapter-Schnittstelle |
| `limit_scan.py` | Cross-Agent-Limit-Scanner + Auto-Timer-Erstellung |

---

## UI-Komponenten (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow. Mixin-Komposition (Deklarationsreihenfolge):
1. FormattingMixin — Markdown-Formatierungs-Shortcuts
2. HotkeyMixin — Hotkey-Bindungs-Schnittstelle
3. ScalingMixin — DPI/Schrift-Skalierung
4. SearchMixin — Suchleiste über Silos
5. SendSelectionMixin — Text über Watcher senden
6. SnippetOpsMixin — Silo-Operationen (Papierkorb, Duplizieren, Sortieren)
7. ThemeMixin — App-Stylesheet, Vintage-Presets
8. TrayMixin — System-Tray-Icon + Menü
9. WatcherMixin — Watcher-Engine-Integration
10. WindowMixin — rahmenloses Fenster + Snapping

**Wichtige Eigenschaften:** `_font_size`, `_font_family`, `_ui_scale`, `_button_scale`, `_sidebar_right`, `_always_on_top`, `_normal_window`

**Wichtige Methoden:**
- `init_ui()` — Fenster, Header-Toolbar, Splitter, Editor, Seitenleiste, Statusleiste bauen
- `setup_single_instance_server()` — IPC-Init
- `register_all_hotkeys()` — pynput + PyQt-Shortcuts binden
- `apply_font()` / `apply_theme()` — Schrift/Theme-Änderungen kaskadieren
- `place_window()` — gespeicherte Geometrie wiederherstellen oder Standard-Snap anwenden
- `_switch_to_slot(slot, initial)` — Silo in Editor laden, Cursor-Zustand speichern
- `capture_silo_state()` / `restore_silo_state()` — Cursor/Scroll/Falt/Heat-Persistenz pro Silo

---

### `VaultTextEdit` (`ui/editor.py`)

Erweitertes QPlainTextEdit. Markdown-Bearbeitungs-Canvas.

**Funktionen:**
- MarkdownHighlighter — Live-Syntaxfärbung
- LineNumberArea — Gutter: Zeilennummern + Faltpfeile (▾) + Randmarkierungen
- `fold_header(block_num)` / `unfold_header(block_num)` — Abschnittsfaltung
- `queue_current_line()` — Watcher-Element am Block verankern
- `set_queue_anchor(block, id)` — Queue-Zeilen-Verankerung
- `collect_line_marks()` / `apply_line_marks()` — Persistenz der Randmarkierungen pro Zeile
- `collect_line_heat()` / `apply_line_heat()` — Aktualitäts-Heatmap
- `block_for_queue_item(id)` — Block per Queue-Anker finden
- `toggle_checkbox()` — `- [ ]` ↔ `- [x]`
- `toggle_hide_markup(checked)` — ** * ~~ `-Marker ausblenden (T-603)
- Bild-Pillen — `![alt](url)` → 150px-klickbarer Button

---

### `SnippetPanel` (ui/snippet_panel.py)

Seitenleisten-Silo-Liste + F1-F10-Buttons.

**Klassen:**
- `SnippetWidget` — Seitenleisten-Panel: Kategorie-Tabs + Silo-Liste
- `DraggableSiloButton` — einzelner Silo-Button (Pin, Haken, Farbe, Datei-Icon, Ziehen)
- `WheelPager` — scroll-synchroner Pager für Silo-Liste
- `DropVerticalWidget` — Drop-Zone für Hierarchie-Verschachtelung

**Funktionen:**
- Bis zu 100 Silos pro Tab
- Pins, Haken, Aktualitäts-Heatmap, Hierarchie (per Ziehen verschachteln)
- Seitenleisten-Lücken — benutzerdefinierte Abstandsbalken (Ctrl+Ziehen zum Verschieben)
- Mehrfachauswahl — Shift=Bereich, Ctrl=Umschalten, Batch-Löschen/Speichern/Leeren
- Nummernbox-Modus — Projektumschalter als nummerierte Button-Reihe (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

Datei-Schublade pro Silo. Öffnet unter dem Editor.

- `load_files(cat, slot)` — Ordnerinhalt lesen
- `add_files(paths)` — externe Dateien in Silo-Ordner kopieren
- `apply_template(name)` — Ordnerstruktur erstellen (IN/OUT/DOCS/Assets/Drafts)
- Bildvorschau, Link-Modus, Drag-and-Drop
- Silo-Backup — Ctrl+Klick 📁 exportiert Silo-Text

---

### `SiloTable` (`ui/silo_table.py`)

Reintext-Markdown-Tabellen-Builder. Keine Qt-Tabellen — funktioniert auf einfachem Markdown.

- Tab/Shift+Tab: Zellen durchlaufen; Tab am letzten → neue Zeile
- Enter: neue Zeile (kein Split)
- Zellenbearbeitung über Inline-Markdown

---

### `SiloKanban` (`ui/silo_kanban.py`)

Reintext-Markdown-Kanban-Board. Karten sind Markdown-Listenelemente.

- Alt+↑/↓: Karte hoch/runter bewegen
- Alt+←/→: Karte in benachbarte Spalte bewegen
- Enter auf leerer Board-Zeile: neue Karte
- Checkbox klicken: Erledigt umschalten

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)

Visueller Bildschirm-Zonen-Picker. 7 Layout-Presets (TL, TR, BL, BR, Center, Full, Cursor). Zone klicken zum Snappen.

---

### `WindowPresetsDialog` (`ui/window_presets_dialog.py`)

Benutzerdefinierte Fensterpositions-Presets. Bis zu 10 gespeicherte Geometrien als Bildschirmfraktionen.

- Aktuelle Geometrie speichern, umbenennen, sortieren, neu erfassen
- Aus Ctrl+Q-Picker-Seite anwenden
- Pro-Monitor-Fraktions-Speicherung (übersteht Monitorwechsel)

---

### `TimerToast` (`ui/timer_toast.py`)

Schwebende Benachrichtigungs-Toast für Timer-Alarme. Win95-3D-Bevles, Theme-Farben, Schlummer-Button.

### `ToolbarReorder` (`ui/toolbar_reorder.py`)

Drag-and-Drop-Toolbar-Anpassung. Sichtbare Lücken-Widgets. Reset-Button.

### Overflow-Menü (`main.py`)

Wenn Header < 700px: ausgeblendete Buttons in »-Popup gesammelt. Jede Formatierung, Navigation, jedes Tool bleibt erreichbar.

### `EditGuard` (`ui/edit_guard.py`)

Kontextmanager: `with edit_block(widget): ...` umschließt begin/endEditBlock. Verhindert Qt-Freeze durch nicht beendete Bearbeitungsoperationen.
