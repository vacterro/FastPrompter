# FastPrompter moodulite struktuur

## Koodibaasi kaart (`src/fastprompter/`)

```
src/fastprompter/
├── main.py                     # Sisenemispunkt, QMainWindow, mixini orkestreerimine
├── __init__.py                 # Paketi marker
│
├── core/                       # Taustloogika, olek, alamsüsteemid
│   ├── config.py               # Teema värvi eraldajad, salve ikoonide generaatorid
│   ├── ctrlw.py                # Ctrl+W / Alt+W eraldaja sisestuse mootor
│   ├── default_profile.py      # Tarnevaikimuste kaart, liidetud state.reset_data()
│   ├── duration.py             # Aja parsimine, inimloetav kestuse vorming
│   ├── hashtags.py             # Hashtagi väljavõtt + silode-ülene indekseerimine
│   ├── header.py               # Ctrl+E päise vormindamise tuum
│   ├── hotkey_filter.py        # Win32 WH_KEYBOARD_LL konks VK-edastuseks
│   ├── hotkeys.py              # pynput globaalse klõbustiku kuulajalõim
│   ├── ipc_server.py           # QLocalServer single-instance IPC
│   ├── limits.py               # Agendi lähtestuslimiidi skanner + taimeri loomine
│   ├── logging.py              # Loggeri seadistus, rotatsioonifaili haldur
│   ├── pomodoro.py             # Pomodoro olekumasin (töö/paus)
│   ├── sound_manager.py        # Heli esitus (klõpsud, kirjutusmasin, häired)
│   ├── state.py                # SQLite DB liides + oleku haldus
│   ├── timers.py               # Taimeri mudel, tähtaja tuvastus
│   ├── translations.py         # Pärand-proksi → i18n pakett (33 lokaalit)
│   │
│   ├── i18n/                   # 33-lokaline ressursipakett
│   │   ├── __init__.py, _compat.py, _container.py, _context.py, _engine.py
│   │   ├── en.py, ru.py, est.py, ja.py, ded.py, ... (33 lokaalimoodulit)
│   │   └── flags/              # Riigilippude renderdajad
│   │
│   └── watcher/                # Automatiseerimise + promptide äravoolu mootor
│       ├── __init__.py
│       ├── adapter.py          # Abstraktne prooviadapteri liides
│       ├── cdp.py              # Chrome DevTools Protocol draiver
│       ├── engine.py           # Watcheri käivitustsükkel + olekumasin
│       ├── limit_scan.py       # Agentide-ülene limiidiskanner
│       ├── probes.py           # Mitme proovi oleku kombinaatorid
│       ├── queue.py            # Järjekorra mudel (QueueItem, SendIntent, kinnitamine)
│       ├── sender.py           # Väljundi edastus (CDP / Win32 klahvisüstimine)
│       ├── skills.py           # Oskuste definitsioonid + prompti ümbrised
│       └── win32.py            # Natiiivne Win32 akna + juhtelemendi proov
│
├── ui/                         # PyQt6 UI komponendid + mixinid
│   ├── analog_clock.py         # Kohandatult joonistatud analoogkella vidin
│   ├── backup_dialog.py        # DB eksport/import + varukoopia hetktõmmise dialoog
│   ├── ctrlw_settings.py       # Ctrl+W/Alt+W malli konfiguratsiooni UI
│   ├── cursor_theme.py         # Retro kursori teema overlay haldur
│   ├── drop_overlay.py         # Lohista-sisesta 4-valikuline sihtmärk-overlay
│   ├── edit_guard.py           # Kirjutuskaitse lukuhalduri ümbris
│   ├── editor.py               # VaultTextEdit: koodiplokid, gutter, voltimine
│   ├── fancy_zones.py          # Ekraani haakimistsooni overlay valija
│   ├── file_container.py       # Silo varafaili sahtel + mallid
│   ├── flags.py                # Vektor/raster riigilippude renderdaja
│   ├── flow_layout.py          # Dünaamiline heightForWidth mähkimispaigutus
│   ├── formatting_mixin.py     # Markdowni vormindamise klõbustikud
│   ├── hashtag_dialog.py       # Sildiotsingu + silo filtri overlay
│   ├── header_format_dialog.py # Kuupäeva/aja ajatempli vormingu dialoog
│   ├── help_dialog.py          # Klõbustikud + interaktiivne juhend
│   ├── hotkey_mixin.py         # Klõbustike sidumise mixin peamisele aknale
│   ├── layout_shortcuts.py     # Füüsilise VK klõbustiku kaardistus (paigutusest sõltumatu)
│   ├── markdown_highlighter.py # QSyntaxHighlighter reaalajas markdowni jaoks
│   ├── pie_menu.py             # QuickListWidget radiaalne kontekstimenüü
│   ├── queue_panel.py          # Watcheri järjekorra dialoog
│   ├── resizers.py             # Akna suuruse muutmise käepidemete juhtimine
│   ├── scaling_mixin.py        # UI DPI + fondi skaleerimise mixin
│   ├── search_mixin.py         # Mitmesõnaline AND-otsingufilter
│   ├── send_selection_mixin.py # Valiku saatmine watcheri kaudu
│   ├── settings.py             # Eelistuste dialoog (teemad, klõbustikud, helid)
│   ├── silo_kanban.py          # Markdowni kanban-tahvel (T-630)
│   ├── silo_settings_dialog.py # Silo-põhine konfiguratsioon (värv, projektilingid)
│   ├── silo_table.py           # Markdowni tabeliehitaja (T-630)
│   ├── kanban_widget.py        # Kanban-tahvli vaatevidin (silo_kanban taust)
│   ├── table_widget.py         # Tabeli vaatevidin (silo_table taust)
│   ├── silo_region.py          # Silo loendi piirkond: lohistamine, lüngad, multivalik
│   ├── snippet_ops_mixin.py    # Silo toimingud (prügikast, liigutus, duplikaat, tühjendus)
│   ├── snippet_panel.py        # Silo puu + F1-F10 snippetide nupud
│   ├── theme_mixin.py          # Vintage teema stiliseerimine + QSS generaator
│   ├── timer_dialog.py         # Pomodoro + häiretäimeri seadistamise dialoog
│   ├── timer_toast.py          # Ujuv teavitustoast vidin
│   ├── toolbar_reorder.py      # Lohista-sisesta tööriistariba nupu ümberjärjestus
│   ├── trash_dialog.py         # Prügikast + taastamise dialoog
│   ├── tray_mixin.py           # Süsteemisalve ikoon + kontekstimenüü
│   ├── watcher_dialog.py       # Watcheri konfiguratsioon + skriptihalduri UI
│   ├── watcher_mixin.py        # Watcheri mootori akna integratsioon
│   ├── window_mixin.py         # Raamita liigutus, haakimine, borderless
│   ├── window_presets_dialog.py # Kasutaja määratud aknaasendi preseendid
│   └── zen_desktop.py          # 3-astmeline Zen/Solo töölauapühkimine (Ctrl+D)
│
├── theme/                      # Teemapreseendid
│   └── themes.py               # 9 sisseehitatud värviteemat + kohandatud mootor
│
└── utils/                      # Madalatasemelised abivahendid
    ├── fonts.py                # Süsteemifondi laadija, fallback-resolver, no-AA
    ├── paths.py                # Kaasaskantav tee resolver (exe + kasutaja andmed)
    ├── portable_backup.py      # Kaasaskantava ZIP-varukoopia ehitaja
    └── textfit.py              # Dünaamiline teksti kärpimine + sildi sobitamine
```

## Alamsüsteemide vastutus

| Pakett | Vastutus |
|---|---|
| `core.state` | SQLite WAL püsivus, oleku sünkroonimine, undo-stack, kategooria-põhised alias-hoidlad |
| `core.hotkey*` | Globaalne klõbustike kuulaja + Win32 VK-filter, paigutusest sõltumatu edastus |
| `core.watcher` | Promptide järjekord, CDP/Win32 automatiseerimine, oskuste ümbrised, limiidiskanner |
| `core.i18n` | 33-lokaline tõlkepakett + proksi delegaat translations.py-st |
| `core.ctrlw` | Eraldaja malli mootor (Ctrl+W / Alt+W) |
| `core.timers` | Taimeri mudel, tähtaja tuvastus, serialiseerimine |
| `core.pomodoro` | Töö/pausi olekumasin, fookusetaimer |
| `ui.editor` | VaultTextEdit — voltimine, gutter, märkeruudud, soojuskaart, marginaalimärgid, märgistuse peitmine |
| `ui.snippet_panel` | Silo puu, hierarhia, kategooria vahekaardid, F1-F10 kohad, külgriba vahed, mitmevalik |
| `ui.silo_kanban` | Puhtalt-tekstiline kanban-tahvel (Alt+nooleklahvid liigutavad kaarte, Enter uus rida) |
| `ui.silo_table` | Puhtalt-tekstiline tabeliredaktor (Tab lahtrite läbikäimine, Enter uus rida) |
| `ui.file_container` | Silo-põhine kaustasahtel, varade eelvaade, mallid |
| `ui.theme_mixin` | 9 sisseehitatud teemat + kohandatud värvimootor + QSS generaator |
| `ui.kanban_widget` | Kanban-tahvli vaatevidin (silo_kanban taust) |
| `ui.table_widget` | Tabeli vaatevidin (silo_table taust) |
| `ui.silo_region` | Silo loendi piirkond: lohistamine, lüngad, multivalik |
| `ui.fancy_zones` | Visuaalne tsoonivalija 7 paigutuse preseendiga |
| `ui.window_presets_dialog` | Kasutaja salvestatud akna geomeetria preseendid (Ctrl+Q leht) |
| `ui.zen_desktop` | 3-astmeline Ctrl+D: Zen, Solo (teiste minimeerimine), tagasi |
| `ui.toolbar_reorder` | Lohista-sisesta tööriistariba nuppude kohandamine |
| `ui.flow_layout` | Reageeriv mähkimispaigutus kompaktsetele seadete paneelidele |
| `ui.edit_guard` | begin/endEditBlock hoidja — takistab külmutamist lõpetamata muudatustest |
| `utils.fonts` | Fondi lahendus, bitmap-fondi install, no-AA fallback |
| `utils.paths` | Kaasaskantav käivitamine — ilma registri ja AppData sõltuvuseta |

## Moodulite arvu kokkuvõte

- **core/**: 16 moodulit + i18n/ (33 lokaalit + 5 infrafaili = 38) + watcher/ (10 moodulit)
- **ui/**: 44 moodulit
- **theme/**: 1 moodul
- **utils/**: 4 moodulit
- **Kokku**: 115 `.py`-faili all `src/fastprompter/` (kaasa arvatud `main.py` + `__init__.py`)
