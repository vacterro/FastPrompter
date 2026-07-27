# FastPrompter Configuration & Settings Reference

## Database Settings Schema
Settings are stored in the SQLite database (`data/fastprompter.db` or `data/fastprompter_p<ID>.db`) within the `settings` table as key-value text pairs.

### Settings Keys Reference

| Seadistusklahv | Tüüp | Vaikimisi | Kirjeldus |
|---|---|---|---|
| `teema` | string | `"Vaikimisi"` | Aktiivne visuaalne teema (`"Vaikimisi"`, `"Amber"`, "OLED"`, "Win95"`, "Rose"`, `"Kohandatud"`) |
| `fondi_suurus` | täisarv | "11" | Peamise redaktori fondi suurus punktides |
| "ui_scale" | ujuk | "1,0" | Kasutajaliidese üldine skaleerimistegur (0,5–1,5) |
| "nupu_skaala" | ujuk | "1,0" | Silo ja tööriistariba nupu suuruse kordaja |
| `global_hotkey` | string | `"Alt+X"` | Peamine kiirklahv rakenduse akna kuvamiseks/peitmiseks |
| `piruka_menüü_kiireklahv` | string | `"Tõstuklahv+Alt+X"` | Kiirklahv radiaalse piruka menüü käivitamiseks |
| `lock_window_hotkey` | string | `"Alt+S"` | Kiirklahv akna asendi lukustuse lülitamiseks |
| `alati_ülaosas_hotkey` | string | `"Alt+E"` | Kiirklahv Alati üleval aknarežiimi lülitamiseks |
| `kinni_keskendumise_kaotusele' | tõeväärtus | `"Tõsi"` | Peida aken automaatselt, kui fookus kaob |
| `ctrl_c_closes` | tõeväärtus | `"Tõsi"` | Sulgege/peida aken pärast klahvikombinatsiooni Ctrl+C vajutamist lõigurežiimis |
| `heli_ui` | tõeväärtus | `"Vale"` | Luba kasutajaliidese nupu klõpsamise heliefektid |
| `heli_kirjutusmasin` | tõeväärtus | `"Vale"` | Luba kirjutusmasina klahvide heliefektid |
| "heli_helitugevus" | täisarv | "5" | Helitugevuse tase (0 kuni 10) |
| `portable_backup_enabled` | tõeväärtus | `"Tõsi"` | Andmebaasifaili `.bak` automaatne loomine käivitamisel |
| `keel` | string | "ET" | Liidese keel ("EN", "RU", "UK", "DE", "FR", "ES", "IT", "PT", "NL", "PL", "SV", "DA", "FI", "NO", "JA", "ZH", "KO", "TH", "HEAR, " "DED") |
| `külgriba_parempoolne` | tõeväärtus | `"Vale"` | Asetage silo külgriba redaktori paremasse serva |
| `kood_auto_rennid` | tõeväärtus | `"Vale"` | Reanumbrite automaatne kuvamine redaktori koodiplokkides |
| `kasside_tellimus` | JSON-loend | `["Kood","Tekst","Mitu"]` | Projektikategooria vahekaartide kohandatud järjekord |

---

## File System & Storage Directory Structure

FastPrompter salvestab kõik kasutajaandmed käivitatava faili kõrval olevasse iseseisvasse kataloogi "data/", tagades 100% kaasaskantava täitmise.

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
