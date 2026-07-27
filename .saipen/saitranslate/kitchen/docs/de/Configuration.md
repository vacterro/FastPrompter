# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings are stored in the SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

| Einstellungsschlüssel | Geben Sie | ein Standard | Beschreibung |
|---|---|---|---|
| „Thema“ | Zeichenfolge | `"Standard"` | Aktives visuelles Design („Standard“, „Amber“, „OLED“, „Win95“, „Rose“, „Benutzerdefiniert“) |
| `font_size` | Ganzzahl | `11` | Schriftgröße des primären Editors in Punkt |
| `ui_scale` | schweben | „1,0“ | Gesamt-UI-Skalierungsfaktor (0,5 bis 1,5) |
| `button_scale` | schweben | „1,0“ | Größenmultiplikator für Silo- und Symbolleistenschaltflächen |
| `global_hotkey` | Zeichenfolge | `"Alt+X"` | Primärer Hotkey zum Ein-/Ausblenden des Anwendungsfensters |
| `pie_menu_hotkey` | Zeichenfolge | `"Umschalt+Alt+X"` | Hotkey zum Auslösen des Radialkuchenmenüs |
| `lock_window_hotkey` | Zeichenfolge | `"Alt+S"` | Hotkey zum Umschalten der Fensterpositionssperre |
| `always_on_top_hotkey` | Zeichenfolge | `"Alt+E"` | Hotkey zum Umschalten des Always-On-Top-Fenstermodus |
| `close_on_focus_loss` | boolescher Wert | `"Wahr"` | Fenster automatisch ausblenden, wenn der Fokus verloren geht |
| `ctrl_c_closes` | boolescher Wert | `"Wahr"` | Fenster schließen/ausblenden, nachdem im Snippet-Modus „Strg+C“ gedrückt wurde |
| `sound_ui` | boolescher Wert | „Falsch“ | Klicken Sie auf die Soundeffekte der UI-Schaltfläche |
| `sound_typewriter` | boolescher Wert | „Falsch“ | Schreibmaschinentasten-Soundeffekte aktivieren |
| `sound_volume` | Ganzzahl | „5“ | Lautstärkepegel (0 bis 10) |
| `portable_backup_enabled` | boolescher Wert | `"Wahr"` | Automatische Erstellung der Datenbankdatei „.bak“ beim Start |
| „Sprache“ | Zeichenfolge | `"DE"` | Schnittstellensprache („EN“, „RU“, „UK“, „DE“, „FR“, „ES“, „IT“, „PT“, „NL“, „PL“, „SV“, „DA“, „FI“, „NO“, „JA“, „ZH“, „KO“, „TH“, „VI“, „AR“, „HE“, „ET“, `DED`) |
| `sidebar_right` | boolescher Wert | „Falsch“ | Positionieren Sie die Silo-Seitenleiste auf der rechten Seite des Editors |
| `code_auto_gutter` | boolescher Wert | „Falsch“ | Zeilennummern in Editor-Codeblöcken automatisch anzeigen |
| `cats_order` | JSON-Liste | `["Code","Text","Sonstiges"]` | Benutzerdefinierte Reihenfolge der Projektkategorie-Registerkarten |

---

## File System & Storage Directory Structure

FastPrompter speichert alle Benutzerdaten in einem eigenständigen „data/“-Verzeichnis neben der ausführbaren Datei und gewährleistet so eine 100 % portable Ausführung.

```
data/
├── fastprompter.db             # Main SQLite database (Default profile)
├── fastprompter.db.bak         # Startup backup SQLite database
├── fastprompter_p2.db          # Profile 2 SQLite database
├── silo_files/                 # File Container attachments
│   ├── Code/                   # Category folder
│   │   ├── 0/                  # Silo slot 0 attachment directory
│   │   └── 1/                  # Silo slot 1 attachment directory
│   └── Text/
├── _trash/                     # Soft-deleted silos and files
│   └── 2026-07-22_153022_Silo0/# Timestamped trash archive
└── custom_theme.json           # User-defined custom color palette (if enabled)
```

---

## Custom Themes & Color Editing
When `theme` is set to `"Custom"`, FastPrompter reads color preferences from `custom_theme.json` or state overrides.

### Supported Theme Color Tokens
- `bg_main`: Primary window and panel background color
- `bg_editor`: Editor canvas background color
- `fg_text`: Primary text color
- `border`: Window border and divider line color
- `accent`: Active selection, focus ring, and pin highlight color
- `header_bg`: Header bar and title background color
