# FastPrompter Core API ja klasside teatmik

## Core klassid (`src/fastprompter/core/`)

### `FastPrompterState` (`core/state.py`)

Lõimede-kindel SQLite andmemudel. Kesksed oleku-hub — kõik silod, snippetid, seaded, teemad, järjekorrad läbivad seda.

**Meetodid:**
- `__init__(profile_id=1)` — ava SQLite ühendus, WAL-režiim, lae kettidega seaded
- `init_db()` — loo/uuenda skeem (presets, settings, temp_presets_v2, archive_temp_presets_v2), käivita .bak-varukoopia
- `switch_profile(new_profile_id)` — sule praegune DB, vaheta tee, laadi uuesti
- `save_data_to_db(text, ui_settings, force)` — aatomiine määrdunud oleku kirjutus
- `mark_dirty()` — märgi olek salvestamist vajavaks (asünkroon autosalvestus taimeri kaudu)
- `reset_data()` — taasinitsialiseeri mälu vaikimisi

**Andmemudel:** Ühtne `self.data` dict. Kategooria-põhised hoidlad aliasteerituna: `temp_presets` → `temp_presets_all[active_cat]`, `silo_colors` → `silo_colors_all[active_cat]` jne. Kõik `_all` võtmed auto-migreeruvad esimesel ligipääsul.

---

### `GlobalHotkeyManager` (`core/hotkeys.py`)

Lõimeline pynput klaviatuuri kuulaja süsteemiüleste klõbustike jaoks.

**Meetodid:**
- `start()` — käivita pynput kuulaja lõim
- `stop()` — peata kuulaja
- `update_hotkeys(hk_dict)` — registreeri klõbustike kaart uuesti

---

### `HotkeyFilter` (`core/hotkey_filter.py`)

Win32 WH_KEYBOARD_LL konks. Püüab füüsilisi VK-koode — paigutusest sõltumatult. Töötab risti-paigutusega (QWERTY/JCUKEN/AZERTY). Kasutusel layout_shortcuts.py edastuseks.

---

### `IpcServer` (`core/ipc_server.py`)

QLocalServer nimega torul `FastPrompter_Server_V15`. UUID-token autentimine `%TEMP%/fastprompter_ipc.token` kaudu.

**Meetodid:**
- `setup()` — alusta kuulamist (taastab aegunud socketi nimed removeServer abil)
- `close()` — peata server
- `_handle_command()` — töötle SHOW käsku teiselt instantsilt

**Abi:**
- `try_connect_to_server()` — kontrolli jooksvat instantsi (tagastab QLocalSocket või None)

---

### `SoundManager` (`core/sound_manager.py`)

WAV esitus UI klõpsudele, kirjutusmasina klahvidele, taimeri häiretele.

**Meetodid:**
- `play(name)`, `play_click()`, `play_tick()` — audio edastus sündmuse kaupa
- Helitugevust juhib `sound_volume` seade (0-10); winsoundi tee skaleeritakse läbi `scale_wav_bytes()` / `scaled_wav_path()`
- `sound_ui` / `sound_typewriter` / sündmusepõhised lipud juhivad esitust

---

### `PomodoroEngine` (`core/pomodoro.py`)

Töö/pausi olekumasin konfigureeritavate intervallidega.

**Konstandid:** `PHASE_WORK`, `PHASE_BREAK`

**Meetodid:**
- `start_work()`, `start_break()`, `pause()`, `reset()` — elutsükkel
- `tick(elapsed)` — edenda taimerit, anna faasisiirdeid
- `describe()` — inimesele loetav olekustring
- `from_dict(data)` / `to_dict()` — JSON serialiseerimine

---

### `Timer` ja `TimerManager` (`core/timers.py`)

Üldine taimer. Värvikooditud kiireloomulisus, heli süttimisel, edasilükkamine.

**Taimeri atribuudid:** `name`, `description`, `target` (datetime), `sound`, `volume`, `color_mode`, `color`

**Meetodid:**
- `remaining()` — sekundid sihtmärgini
- `snooze(minutes)` — lükka sihtmärki edasi
- `display_color()` — kiireloomulisuse värv (roheline/kollane/punane)
- `collect_due(timers)` — tagasta tähtaja ületanud taimerite loend
- `next_due(timers)` — lähim taimer
- `save_timers(data)` / `load_timers(data)` — serialiseerimine

---

### `DurationParser` (`core/duration.py`)

Inimloetava kestuse parsimine.

- `parse_duration(text)` — «2h 30m» → sekundid
- `format_remaining(seconds, short=False, minutes=False)` — «2h 30m» → «2h» või «4d 11h 05m»
- `format_duration(seconds)` — täisformaat string

---

### `HashtagIndex` (`core/hashtags.py`)

Silo-ülene hashtagi väljavõtt + otsing.

- `extract_tags(text)` — tagasta `#tag` stringide hulk
- `index_silo(cat, slot, text)` — silt → silo indeks
- `search(tag)` — kõik silod, mis sisaldavad silti kategooriate üleselt

---

### `DividerEngine` (`core/ctrlw.py`)

Ctrl+W / Alt+W malli sisestus.

- `insert_divider(editor, template, upward)` — sisesta horisontaaljoon, eemalda duplikaat-täpid jagamisel
- `simulate(editor, upward)` — sisestuskoha eelvaade

---

### `HeaderFormatter` (`core/header.py`)

Ctrl+E päise sisestus. Konfigureeritav: reeglijoon, vahe, täpp, joondus, ajatempel.

- `format_header(editor, config)` — vorminda praegune rida päiseks

---

### Watcheri mootori moodulid (`core/watcher/`)

| Moodul | Roll |
|---|---|
| `engine.py` | Lõplik olekumasin: DISARMED → ARMED → WATCHING → SENDING |
| `cdp.py` | Chrome CDP ühendus + evaluate + read-back kontroll (Electroni rakendused) |
| `win32.py` | Win32 aknaproov — foreground, kursor, fookuse tuvastus |
| `probes.py` | Mitme proovi oleku kombinaatorid + liitmaatriks |
| `queue.py` | QueueItem, SendIntent, kinnitamine, järjekorravõti, püsivus |
| `sender.py` | CDP + Win32 klahvisüstimine read-back kontrolliga |
| `skills.py` | Prompt-oskuste ümbrised — prefiks/mall teisendused |
| `adapter.py` | Abstraktne prooviadapteri liides |
| `limit_scan.py` | Agentide-ülene limiidiskanner + automaatne taimeri loomine |

---

## UI komponendid (`src/fastprompter/ui/`)

### `FastPrompter` (`main.py`)

QMainWindow. Mixini kompositsioon (deklaratsiooni järjekord):
1. FormattingMixin — markdown vormindamise klõbustikud
2. HotkeyMixin — klõbustike sidumise liides
3. ScalingMixin — DPI/fondi skaleerimine
4. SearchMixin — otsinguriba silode üle
5. SendSelectionMixin — teksti saatmine watcheri kaudu
6. SnippetOpsMixin — silo toimingud (prügikast, duplikaat, järjestus)
7. ThemeMixin — rakenduse stiilileht, vintage-presseendid
8. TrayMixin — süsteemisalve ikoon + menüü
9. WatcherMixin — watcheri mootori integratsioon
10. WindowMixin — raamita aken + haakimine

**Peamised omadused:** `_font_size`, `_font_family`, `_ui_scale`, `_button_scale`, `_sidebar_right`, `_always_on_top`, `_normal_window`

**Peamised meetodid:**
- `init_ui()` — ehita aken, päise tööriistariba, splitter, redaktor, külgriba, olekuriba
- `setup_single_instance_server()` — IPC initsialiseerimine
- `register_all_hotkeys()` — seo pynput + PyQt klõbustikud
- `apply_font()` / `apply_theme()` — fondi/teema kaskaadne rakendamine
- `place_window()` — taasta salvestatud geomeetria või rakenda vaikimisi haakimine
- `_switch_to_slot(slot, initial)` — laadi silo redaktorisse, salvesta kursori olek
- `capture_silo_state()` / `restore_silo_state()` — silo-põhine kursori/kerimise/voltimise/soojuse püsivus

---

### `VaultTextEdit` (`ui/editor.py`)

Laiendatud QPlainTextEdit. Markdown redigeerimise lõuend.

**Võimalused:**
- MarkdownHighlighter — reaalajas süntaksi värvimine
- LineNumberArea — gutter: reanumbrid + voltimisnooled (▾) + marginaalimärgid
- `fold_header(block_num)` / `unfold_header(block_num)` — sektsiooni kokkuvolt
- `queue_current_line()` — ankurda watcheri üksus bloki külge
- `set_queue_anchor(block, id)` — järjekorrareaga ankurdamise
- `collect_line_marks()` / `apply_line_marks()` — rea-põhise marginaalimärgi püsivus
- `collect_line_heat()` / `apply_line_heat()` — värskuse soojuskaart
- `block_for_queue_item(id)` — leia blokk järjekorra ankrutega
- `toggle_checkbox()` — `- [ ]` ↔ `- [x]`
- `toggle_hide_markup(checked)` — peida ** * ~~ ` märgid (T-603)
- Pildipillid — `![alt](url)` → 150px klõpsatav nupp

---

### `SnippetPanel` (ui/snippet_panel.py)

Külgriba siloloend + F1-F10 nupud.

**Klassid:**
- `SnippetWidget` — külgriba paneel: kategooria vahekaardid + siloloend
- `DraggableSiloButton` — üksik silo nupp (pinn, linnuke, värv, failiikoon, lohistamine)
- `WheelPager` — kerimisega sünkroniseeritud pager siloloendile
- `DropVerticalWidget` — hierarhilise pesastamise lohistusala

**Võimalused:**
- Kuni 100 silot vahekaardil
- Pinid, linnukesed, värskuse soojuskaart, hierarhia (lohista pesastamiseks)
- Külgriba vahed — kasutaja määratud eraldusribad (Ctrl+lohistamine)
- Mitmevalik — Shift=vahemik, Ctrl=lülitus, partii kustutamine/salvestamine/tühjendamine
- Numbrikasti režiim — projektivaheti nummerdatud nuppudena (T-607)

---

### `FileContainerWidget` (`ui/file_container.py`)

Silo-põhine failisahtel. Avaneb redaktori all.

- `load_files(cat, slot)` — loe kausta sisu
- `add_files(paths)` — kopeeri välised failid silo kausta
- `apply_template(name)` — loo kaustastruktuur (IN/OUT/DOCS/Assets/Drafts)
- Pildi eelvaade, lingirežiim, lohista-sisesta
- Silo varukoopia — Ctrl+klõps 📁 ekspordib silo teksti

---

### `SiloTable` (`ui/silo_table.py`)

Puhtalt-tekstiline markdown tabeliehitaja. Pole Qt-tabeleid — töötab tavalisel markdownil.

- Tab/Shift+Tab: lahtrite läbikäimine; Tab viimaselt → uus rida
- Enter: uus rida (mitte lõhenemine)
- Lahtri redigeerimine inline-markdowni kaudu

---

### `SiloKanban` (`ui/silo_kanban.py`)

Puhtalt-tekstiline markdown kanban-tahvel. Kaardid on markdowni loendielemendid.

- Alt+↑/↓: liiguta kaarti üles/alla
- Alt+←/→: liiguta kaarti naaber-veerdu
- Enter tühjal tahvlireal: uus kaart
- Märkeruudu klõps: lõpetatu lülitus

---

### `FancyZoneOverlay` (`ui/fancy_zones.py`)

Visuaalne ekraanitsooni valija. 7 paigutuse preseedi (TL, TR, BL, BR, Center, Full, Cursor). Klõpsa tsoonile haakimiseks.

---

### `WindowPresetsDialog` (`ui/window_presets_dialog.py`)

Kasutaja määratud aknaasendite preseendid. Kuni 10 salvestatud geomeetriat ekraani murdosadena.

- Salvesta praegune geomeetria, nimeta ümber, järjesta, lae uuesti
- Rakendamine Ctrl+Q valija lehelt
- Monitori-põhine murdosa salvestamine (peab vastu monitorivahetusele)

---

### `TimerToast` (`ui/timer_toast.py`)

Ujuv teavitustoast taimeri häiretele. Win95 3D kaldservad, teema värvid, edasilükkamise nupp.

### `ToolbarReorder` (`ui/toolbar_reorder.py`)

Lohista-sisesta tööriistariba kohandamine. Nähtavad vahevidinad. Lähtestusnupp.

### `Overflow Menu` (`main.py`)

Kui päis < 700px: peidetud nupud kogutakse » popup-i. Iga vormindamine, navigatsioon, tööriist jääb kättesaadavaks.

### `EditGuard` (`ui/edit_guard.py`)

Kontekstihaldur: `with edit_block(widget): ...` mähib begin/endEditBlock. Takistab Qt külmutamist lõpetamata redigeerimistoimingutest.
