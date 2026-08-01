# FastPrompter Konfiguration & Einstellungen

## DB-Schema

SQLite-DB: `data/local_data_v15.db` (Profil 1) oder `data/local_data_v15_p<ID>.db` (Profile >1). Portables `data/`-Verzeichnis sitzt neben dem EXE. Fällt auf `%LOCALAPPDATA%/FastPrompter/` zurück, wenn das EXE-Verzeichnis nicht beschreibbar ist.

**Tabellen:**
- `settings` — Schlüssel-Wert-Textpaare (gesamte App-Konfiguration)
- `presets` — Snippet-Speicherung (Kategorie, Slot, Name, Inhalt, last_edited)
- `temp_presets_v2` — Silo-Textinhalt pro Kategorie
- `archive_temp_presets_v2` — archivierter Silo-Inhalt pro Kategorie

Die Konfiguration lebt in den Schlüssel-Wert-Paaren der `settings`-Tabelle. Keine INI-Datei. Alles wird beim Anwenden hot-reloaded.

## Einstellungsschlüssel

| Schlüssel | Typ | Standard | Beschreibung |
|---|---|---|---|
| **Theme & Anzeige** | | | |
| `theme` | string | `Default` | Theme: Default, Amber, OLED, Win95, Rose, Vintage Classic, Custom |
| `font_family` | string | `Verdana` | Editor-Schriftart (löst automatisch auf `_m1`-Bitmap-Variante auf, wenn installiert) |
| `font_size` | int | 11 | Editor-Schriftgröße in Punkt |
| `ui_scale` | float | 0.5 | UI-Skalierung (0.5 bis 1.5) |
| `button_scale` | float | 1.0 | Silo- + Toolbar-Button-Größenmultiplikator |
| `custom_cursors` | bool | False | Retro-Cursor-Theme-Overlay |
| `code_monospace` | bool | True | Monospace-Schrift in Codeblöcken (False = Editor-Schrift) |
| `code_auto_gutter` | bool | False | Automatische Zeilennummern in Codeblöcken |
| `hr_line` | bool | False | `---` als visuelle Linie statt Text rendern |
| `hide_markup` | bool | False | `**`, `*`, `~~`, `` ` ``-Marker verbergen (Obsidian-Stil, T-603) |
| **Hotkeys** | | | |
| `global_hotkey` | string | `Alt+X` | Globaler Aufruf-Hotkey |
| `pie_menu_hotkey` | string | `Shift+Alt+X` | Pie-Menü-Hotkey |
| `lock_window_hotkey` | string | `Alt+S` | Fenstersperre umschalten |
| `always_on_top_hotkey` | string | `Alt+E` | Immer-im-Vordergrund umschalten |
| **Verhalten** | | | |
| `close_on_focus_loss` | bool | True | Bei Fokusverlust automatisch ausblenden |
| `always_on_top` | bool | True | Mit Immer-im-Vordergrund starten |
| `normal_window` | bool | False | Normaler Fenstermodus (nicht rahmenlos) |
| `tray_visible` | bool | True | System-Tray-Icon anzeigen |
| `auto_bullet` | bool | False | Bindestriche automatisch in Aufzählungen umwandeln |
| `ctrl_e_center` | bool | False | Ctrl+E-Header zentrieren |
| `customize_toolbar` | bool | False | Toolbar-Sortiermodus |
| `snippets_hidden` | bool | False | Snippet-Panel ausblenden |
| `sidebar_right` | bool | False | Seitenleiste rechts |
| `show_token_count` | bool | False | Token-Schätzung neben Zeilenzahl (T-614) |
| `silo_sync_mode` | string | Off | Einweg-Silo-Sync auf Disk: Off/Silo/Hierarchie (T-591) |
| `window_presets_enabled` | bool | False | Ctrl+Q-Fensterpresets-Seite aktivieren (T-608) |
| **Sound** | | | |
| `sound_ui` | bool | False | UI-Klick-Soundeffekte |
| `sound_typewriter` | bool | False | Schreibmaschinen-Tastensounds |
| `sound_volume` | int (0-10) | 5 | Master-Lautstärke |
| **Uhr & Datum** | | | |
| `date_seconds` | bool | True | Sekunden in der Uhr anzeigen |
| `date_daypart` | bool | True | Morgen/Tag/Abend/Nacht-Label anzeigen |
| `date_text_month` | bool | False | Textmonat verwenden (Jan/Feb) |
| `date_ampm` | bool | False | 12h-AM/PM-Format |
| `date_emoji` | bool | False | Emoji-Tageszeit (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | Datum im Header anzeigen |
| **Cursor** | | | |
| `cursor_blink_ms` | int | system | Cursor-Blinkgeschwindigkeit ms (0 = kein Blinken, T-606) |
| **Timer** | | | |
| `timer_show_minutes` | bool | False | Minutenfeld in Timeranzeige behalten (T-613) |
| **Fensterlayout** | | | |
| `numbox_per_row` | int | 10 | Nummernboxen pro Reihe im Raster (T-612) |
| `numbox_btn_size` | int | 24 | Nummernbox-Button-Größe px (T-612) |
| **Sonstiges** | | | |
| `language` | string | EN | UI-Sprache (23 Optionen) |
| `hover_line_color` | string | auto | Zeilen-Highlight-Farbe (auto = Theme-Akzent) |
| `portable_backup_enabled` | bool | True | Automatisches .bak beim Start |
| `watcher_skill` | string | (leer) | Standard-Skill für Watcher-Queue-Elemente |
| `cats_order` | JSON-Liste | `["Code","Text","Misc"]` | Kategorie-Tab-Reihenfolge + Namen |
| `hidden_categories` | JSON-Liste | [] | Ausgeblendete Kategorien (im Projektmanager sichtbar) |
| `timers` | JSON | [] | Gespeicherte Countdown-Definitionen |
| `productivity_timer` | JSON | — | Pomodoro-Timer-Zustand |
| `watcher_queues` | JSON | `{}` | Prompt-Queues pro Silo |
| `toolbar_order` | string | (leer) | Benutzerdefinierte Toolbar-Button-Reihenfolge-Tokens |
| `window_presets` | JSON | [] | Vom Benutzer gespeicherte Fenstergeometrie-Presets |
| `silo_gap_height` | int | 6 | Seitenleisten-Lücken-Abstandshalter-Höhe in px |
| `show_silo_ticks` | bool | True | Haken-Buttons auf Silos anzeigen |
| `silo_view_state_all` | JSON-Dict | `{}` | Cursor/Scroll/Falt-Zustand pro Silo |

## Dateisystem-Layout

```
data/
├── local_data_v15.db           # Haupt-SQLite-DB (Profil 1)
├── local_data_v15.db.bak       # Gedrosseltes Backup (60-s-Minimalintervall)
├── local_data_v15.db-wal       # WAL-Write-Ahead-Log
├── local_data_v15.db-shm       # WAL-Shared-Memory
├── local_data_v15_p2.db        # Profil-2-DB
├── silo_files/                 # Datei-Container-Anhänge
│   ├── Code/                   # Kategorieordner
│   │   ├── 0/                  # Silo-Slot-0-Dateien
│   │   └── 1/                  # Silo-Slot-1-Dateien
│   └── Text/
├── _trash/                     # Weich gelöschte Silos + Dateien
│   └── 2026-07-22_153022_Silo0/# Zeitgestempelter Papierkorb-Eintrag
└── custom_theme.json           # Benutzerdefinierte Farbpalette
```

**Täglicher Spiegel:** `%USERPROFILE%/Documents/.fastprompter/` — Zeitstempel, Projekt-Silos/Archiv/Snippets als flache .md

**Undo-Speicher:** `data/data_undo_stack.json` + `data/data_redo_stack.json` (automatisch komprimiert, 20-MB-Cap)

## Custom Themes

`data/custom_theme.json` wird geladen, wenn Theme = Custom.

**Farb-Tokens:** `bg_main`, `bg_surface`, `bg_editor`, `fg_text`, `fg_accent`, `text_primary`, `text_accent`, `border`, `selection`, `header_bg`, `accent`, `button_bg` usw.

Anwenden über Einstellungen → Theme oder Mini-Einstellungen (Alt+`). Sofortiges Hot-Reload, kein Neustart.
