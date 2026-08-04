# FastPrompter konfiguratsioon ja seaded

## Andmebaasi skeem

SQLite DB: `data/local_data_v15.db` (profiil 1) või `data/local_data_v15_p<ID>.db` (profiilid >1). Kaasaskantav `data/` kaust asub EXE kõrval. Tagasilangus `%LOCALAPPDATA%/FastPrompter/`, kui exe kaust ei ole kirjutatav.

**Tabelid:**
- `settings` — võti-väärtus tekstipaarid (kogu rakenduse konfiguratsioon)
- `presets` — snippetide hoidla (kategooria, koht, nimi, sisu, last_edited)
- `temp_presets_v2` — silo tekstiline sisu kategooria kaupa
- `archive_temp_presets_v2` — arhiveeritud silo sisu kategooria kaupa

Konfiguratsioon elab `settings` tabeli võti-väärtus paarides. INI-faili pole. Kõik hoot-reload rakendamisel.

## Seadete võtmed

| Võti | Tüüp | Vaikimisi | Kirjeldus |
|---|---|---|---|
| **Teema ja kuvamine** | | | |
| `theme` | string | `Golden Default` | Teema: Default, Golden Vintage, Golden Default, Vintage Dark, Vintage Classic, Dark 2 (OLED), Dracula, Nord, Solarized Dark, Custom |
| `font_family` | string | `Verdana` | Redaktori font (automaatselt `_m1` bitmap-variant, kui installitud) |
| `font_size` | int | 18 | Redaktori fondi suurus punktides |
| `ui_scale` | float | 0.5 | UI skaleerimine (0.5 kuni 1.5) |
| `button_scale` | float | 0.5 | Silo + tööriistariba nuppude suuruse kordaja |
| `custom_cursors` | bool | True | Retro kursori teema overlay |
| `code_monospace` | bool | False | Mono-tähtedega font koodiplokkides (False = redaktori font) |
| `code_auto_gutter` | bool | False | Automaatsed reanumbrid koodiplokkides |
| `hr_visual_line` | bool | True | `---` renderdamine horisontaalse joonena teksti asemel |
| `live_preview_conceal` | bool | True | Peida `**`, `*`, `~~`, `` ` `` märgid reaalajas eelvaates |
| **Klõbustikud** | | | |
| `global_hotkey` | string | `Alt+X` | Globaalne kutsumise klõbustik |
| `pie_menu_hotkey` | string | `Shift+Alt+X` | Pie-menüü klõbustik |
| `lock_window_hotkey` | string | `Alt+E` | Akna lukustuse lülitus |
| `always_on_top_hotkey` | string | `Alt+S` | Always-on-top lülitus |
| **Käitumine** | | | |
| `close_on_focus_loss` | bool | True | Automaatne peitmine fookuse kaotamisel |
| `always_on_top` | bool | False | Start always-on-top olekus |
| `normal_window` | bool | False | Tavaline aknarežiim (mitte raamita) |
| `tray_visible` | bool | True | Süsteemisalve ikooni näitamine |
| `auto_bullet` | bool | True | Kriipsude automaatne muutmine täppideks |
| `ctrl_e_center` | bool | True | Ctrl+E päiste tsentreerimine |
| `customize_toolbar` | bool | False | Tööriistariba ümberjärjestamise režiim |
| `snippets_hidden` | bool | True | Snippetide paneeli peitmine |
| `sidebar_right` | bool | True | Külgriba paremal |
| `show_token_count` | bool | False | Tokenite hinnang (pillide arv) (T-614) |
| `sync_mode` | string | Off | Ühesuunaline silo sünkroonimine kettale: Off/Silo/Hierarchy (T-591) |
| `window_presets_enabled` | bool | True | Ctrl+Q aknapreseotide lehe sisselülitamine (T-608) |
| **Heli** | | | |
| `sound_enabled` | bool | True | Heli peamine lüliti |
| `sound_ui` | bool | True | UI klõpsu heliefektid |
| `sound_typewriter` | bool | False | Kirjutusmasina klahvihelid |
| `sound_volume` | int (0-10) | 1 | Peamine helitugevus |
| **Kell ja kuupäev** | | | |
| `date_seconds` | bool | True | Sekundite kuvamine kellas |
| `date_daypart` | bool | True | Hommik/päev/õhtu/öö sildi kuvamine |
| `date_text_month` | bool | True | Tekstiline kuu (Jan/Feb) |
| `date_ampm` | bool | False | 12h AM/PM formaat |
| `date_emoji` | bool | False | Emoji kellaaeg (🌅/☀️/🌇/🌙) |
| `show_date_rect` | bool | True | Kuupäeva kuvamine päises |
| **Kursor** | | | |
| `cursor_blink_ms` | int | 1000 | Kursori vilkumise kiirus ms (0 = ei vilgu, T-606) |
| **Taimerid** | | | |
| `timer_show_minutes` | bool | True | Minutivälja hoidmine taimerikuval (T-613) |
| **Akna paigutus** | | | |
| `numbox_per_row` | int | 10 | Numbrikastid rea kohta ruudustikus (T-612) |
| `numbox_btn_size` | int | 24 | Numbrikasti nupu suurus px (T-612) |
| **Muud** | | | |
| `language` | string | EN | UI keel (33 lokaalit) |
| `hover_line_color` | string | `#0059ff` | Rea esiletõstu värv (auto = teema aktsent) |
| `portable_backup_enabled` | bool | True | Auto .bak käivitumisel |
| `watcher_skill` | string | (tühi) | Vaikimisi oskus watcheri järjekorra üksustele |
| `cats_order` | JSON list | `["Code","Text","Misc"]` | Kategooria vahekaartide järjekord + nimed |
| `hidden_categories` | JSON list | [] | Peidetud kategooriad (nähtavad projektihalduris) |
| `timers` | JSON | [] | Salvestatud taimeri määratlused |
| `productivity_timer` | JSON | — | Pomodoro taimeri olek |
| `watcher_queues` | JSON | `{}` | Silo-põhised promptide järjekorrad |
| `toolbar_order` | string | (tühi) | Kohandatud tööriistariba nuppude järjestuse tokenid |
| `window_presets` | JSON | [] | Kasutaja salvestatud akna geomeetria preseendid |
| `silo_gap_height` | int | 12 | Külgriba vahe eraldaja kõrgus px |
| `silo_ticks_enabled` | bool | True | Linnukese nuppude kuvamine silodel |
| `silo_view_state_all` | JSON dict | `{}` | Silo-põhine kursori/kerimise/voltimise olek |

## Failisüsteemi paigutus

```
data/
├── local_data_v15.db           # Peamine SQLite DB (profiil 1)
├── local_data_v15.db.bak       # Drosseldatud varukoopia (min 60 s intervall)
├── local_data_v15.db-wal       # WAL write-ahead logi
├── local_data_v15.db-shm       # WAL ühismälu
├── local_data_v15_p2.db        # Profiili 2 DB
├── silo_files/                 # Failikonteineri manused
│   ├── Code/                   # Kategooria kaust
│   │   ├── 0/                  # Silo koha 0 failid
│   │   └── 1/                  # Silo koha 1 failid
│   └── Text/
├── _trash/                     # Pehme kustutatud silod + failid
│   └── 2026-07-22_153022_Silo0/# Ajatempliga prügikasti kanne
└── custom_theme.json           # Kasutaja määratud värvipalett
```

**Igapäevane peegel:** `%USERPROFILE%/Documents/.fastprompter/` — ajatemplid, silo/arhiiv/snippetid projekti kaupa lamedate .md-failidena

**Undo-hoidla:** `data/data_undo_stack.json` + `data/data_redo_stack.json` (automaatselt tihendatud, 20MB piir)

## Kohandatud teemad

`data/custom_theme.json` laetakse, kui teema = Custom.

**Värvitokenid:** `bg_main`, `bg_surface`, `bg_editor`, `fg_text`, `fg_accent`, `text_primary`, `text_accent`, `border`, `selection`, `header_bg`, `accent`, `button_bg` jne.

Rakendamine läbi Seaded → Teema või Mini Settings (Alt+`). Hetkeline hot-reload, ilma taaskäivitamiseta.
