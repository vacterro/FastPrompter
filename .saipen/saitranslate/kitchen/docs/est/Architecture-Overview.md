# FastPrompter Arhitektuuri ülevaade

## Ülevaade

Kaasaskantav märkmik + promptide töölaud. Python 3.11+, PyQt6. SQLite WAL püsimälu. Null-installi Nuitka EXE. Kutse globaalse Alt+X klõbustikuga, kirjuta, sule — olek salvestub hetkega.

## Kõrgetasemeline skeem

```
+------------------------------------------------------------------+
|                        FastPrompter UI (PyQt6)                   |
|  +------------------+  +--------------------+  +---------------+  |
|  | SnippetPanel     |  | VaultTextEdit      |  | QueuePanel    |  |
|  | (F1-F10 Silos)   |  | (Markdown + Mixins)|  | (Watcher Q)   |  |
|  +------------------+  +--------------------+  +---------------+  |
+----------------------------+-------------------------------------+
                             | sündmused / oleku sünkroonimine
                             v
+------------------------------------------------------------------+
|                    FastPrompterState (core)                       |
|  SQLite WAL DB — silos, snippetid, seaded, teemad, järjekorrad   |
|  Mälukett + undo-stack + silo-põhine olek (kurssor/kerimine)     |
+------------------------------------------------------------------+
      |         |          |          |            |
      v         v          v          v            v
+--------+ +---------+ +--------+ +---------+ +-----------+
|Hotkeys | | IPC     | | Sound  | | Watcher | | File      |
|(pynput)| |(QLocal) | |Manager | |Engine   | | Container |
+--------+ +---------+ +--------+ +---------+ +-----------+
```

## Põhialamsüsteemid

### 1. Rakenduse elutsükkel (`main.py`)

Sisenemispunkt. QApplication initsialiseerimine, single-instance IPC kontroll (QLocalServer), DB ühendus, globaalsed erandikonksud, UI akna ehitamine, süsteemisalv, klõbustike registreerimine. Kõik mixinid komponeeruvad FastPrompter (QMainWindow) peale:

- FormattingMixin — markdown-klõbustikud (paks, kaldkiri, loend, kood)
- HotkeyMixin — klõbustike sidumise liides
- ScalingMixin — DPI/fondi skaleerimine
- SearchMixin — mitmesõnaline AND-otsing
- SendSelectionMixin — teksti saatmine watcheri kaudu
- SnippetOpsMixin — silo toimingud (prügikast, duplikaat, järjestus, tühjendus)
- ThemeMixin — rakenduse stiilileht, 6 retro-Win95-teemat + kohandatud
- TrayMixin — süsteemisalve ikoon + menüü
- WatcherMixin — watcheri mootori integratsioon
- WindowMixin — raamita aken, haakimine, borderless

### 2. IPC Single-Instance (`core/ipc_server.py`)

QLocalServer nimega torul `FastPrompter_Server_V15`. Teine instants saadab SHOW-käsu → olemasolev instants toob oma akna ette. UUID-token `%TEMP%/fastprompter_ipc.token` autentimiseks. Enam ei ole vaikset no-op-i krahhi korral (server.removeServer taastab aegunud socketi nimed).

### 3. Olek ja salvestus (`core/state.py`)

SQLite DB (`data/local_data_v15.db`) koos WAL + synchronous=NORMAL. Peamised tabelid: `presets` (snippetid), `settings` (k/v), `temp_presets_v2` (silo tekst), `archive_temp_presets_v2` (arhiveeritud silod).

Automaatne varukoopia käivitumisel (täielik DB koopia `.bak`). Drosseldatud inkrementaalne varukoopia iga 60 s. Kategooria-põhised andmehoidlad: `silo_colors_all`, `pinned_silos_all`, `silo_ticked_all`, `silo_children_all`, `silo_gaps_all`, `silo_project_paths_all` jne. Kõik aliasteeritakse lamedateks võtmeteks (`temp_presets`) aktiivse kategooria jaoks.

### 4. Klõbustike süsteem (`core/hotkeys.py`, `core/hotkey_filter.py`)

Kaks kihti: (1) pynput globaalne kuulajalõim kutsumiseks/häda-väljumiseks; (2) PyQt6 QShortcut akna-siseste sidumiste jaoks. `HotkeyFilter` (Win32 WH_KEYBOARD_LL) püüab füüsilisi VK-koode — paigutusest sõltumatult. Töötab QWERTY, JCUKEN, AZERTY, QWERTZ-i peal.

### 5. Redaktori mootor (`ui/editor.py`)

VaultTextEdit laiendab QPlainTextEdit. Võimalused:
- MarkdownHighlighter — reaalajas süntaksi esiletõstmine (pealkirjad, paks, kaldkiri, koodiblokid, märkeruudud, lingid, pildid)
- Reanumbrid — numbrid, voltimisnooled (▾), koodibloki kopeerimisnupp
- Sektsiooni voltimine — klõps pealkirjal voltib bloki kokku
- Kokkuvolditavad pildid — `![alt](url)` renderdub 150px klõpsatava pillina
- Drop-overlay — 4-valikuline sihtmärk (sisesta tekst, sisesta link, kopeeri fail, otsetee)
- Marginaalimärgid — read-põhised pinid, linnukesed, järjekorra ankrud, soojuskaart
- Märgistuse peitmise režiim — `**bold**` → `bold` lülitus (T-603)

### 6. Silo süsteem (`ui/snippet_panel.py`)

Kuni 100 silo projekti vahekaardi kohta. Võimalused:
- Pinid (📌) — kinnita üles
- Linnukesed (✅) — lõpetamise märk
- Hierarhia — lohista teisele silole pesastamiseks (max sügavus 2)
- Värskuse soojuskaart — soe toon hiljuti redigeeritutel
- Külgriba vahed — kasutaja määratud eraldajad (Ctrl+lohistamine)
- Mitmevalik — Shift=vahemik, Ctrl=lülitus, partiitoimingud
- Failikonteinerid — silo-põhine ketta kaust (`data/silo_files/<cat>/<idx>/`)
- Kanban (Alt+nooleklahvid liigutavad kaarte) + tabeliehitaja (Tab lahtrite läbikäimine) — T-630

### 7. Watcheri mootor (`core/watcher/`)

Promptide äravool + sihtmärgi automatiseerimine. Lõplik olekumasin: DISARMED → ARMED → WATCHING → SENDING. Chrome CDP (Electroni rakendused) + Win32 aknaproovid. Järjekorra kinnitamine sihtmärgi külge. Kiiruspiirid: settle_ms=2500, min_gap_ms=4000, max_sends=25, max_failures=3.

### 8. Akna haldus (`ui/window_mixin.py`, `ui/zen_desktop.py`)

Raamita aken, Win95 tumedakuldne esteetika. Ctrl+Q tsükleerib haakimispositsioone (7 tsooni + FancyZone valija + kasutaja preseedid). 3-astmeline Ctrl+D: Zen (minimaalne redaktor), Solo (teiste akende minimeerimine), tagasi. Ülevoolumenüü (») kogub peidetud nupud ülikitsas režiimis (<700px). Päise tiheduse astmed kohanduvad automaatselt (tihe <1280px, ülike <700px).

### 9. Taimerid ja Pomodoro (`core/timers.py`, `core/pomodoro.py`)

Taimerid värvikooditud kiireloomulisusega, edasilükkamine, toast-teated (Win95 3D kaldservad). Pomodoro töö/pausi olekumasin.

### 10. Varukoopia ja taastamine

Mitmekihiline: (1) SQLite WAL — krahhikindlad kirjutused; (2) `.bak` käivitumisel + iga 60 s; (3) igapäevane Markdown-peegel `~/Documents/.fastprompter/` (silos + snippetid + arhiiv projekti kohta); (4) kaasaskantav ZIP-varukoopia ehitaja.
