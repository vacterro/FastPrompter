# FastPrompter kasutusjuhend

## Ülevaade

Ülikiire klaviatuuripõhine märkmik + promptide töölaud. Alt+X kutsub kursori juurde. Kirjuta. Sule (Esc). Null käsitsi salvestamist — SQLite sünkroonib iga 10 s.

---

## Peamised mõisted

### 1. Kutsumine (Alt+X)

Globaalne klõbustik. Aken ilmub hiirekursori juurde. Esc sulgeb. Kõik klahvivajutused jõuavad kettale autosalvestuse taimeri (10 s tick) + sulgemise sünkroonimise kaudu.

Topelt-tap Alt+X lülitab always-on-top. Shift+Alt+X avab pie-menüü (teema/skaala/tööriistad).

### 2. Projektid (Vahekaardid)

Nimega projekti vahekaardid päises. Paremklõps: Loo, Nimeta ümber, Kustuta. Kuni 100 projekti. Vahetamine klõpsuga või numbrikasti režiimiga (Seaded → Aken → Paigutus → Numbrikastid reas). Iga projekt hoiab 100 silot + 10 snippetit.

### 3. Silod

Sõltumatud markdown-lõuendi kohad. 100 projekti kohta. Autonumereeritud 00-99.

**Navigatsioon:**
- Ctrl+1..Ctrl+0 — hüppa silole 1-10
- Alt+↑/↓ — liigu silodel
- Ctrl+N — uus tühi silo (lisatakse alla)
- Paremklõps NEW — lisa alla

**Silo-põhised toimingud (hover):**
- 📌 **Pinn** — lukustab silo loendi üles (sorteeritud kinnitamata üles)
- ✅ **Linnuke** — märgib lõpetatuks (visuaalne indikaator)
- 🎨 **Värvikast** — silo-põhine värviesiletõst (lülitus Seadetes)
- 📁 **Failikonteiner** — ava selle silo varasahtel
- 📁 **Kaustalink** — seob silo väliste projektikausta/käivitatavaga
- **Keskmine klõps** — saada prügikasti

**Hierarhia:** Lohista silo teisele pesastamiseks lapsena. Max sügavus 2 (1 → 1.1 → 1.1.1). Shift+lohistamine vahetab. Voltmisnool (▾/▸) vanemal peidab lapsed.

**Värskuse soojuskaart:** Hiljuti redigeeritud silod saavad sooja taustatooni. Kohandatav läbi Seaded → Silos.

### 4. Külgriba vahed

Kasutaja määratud eraldusribad siloloendis. Aitavad silosid gruppidesse organiseerida. Ctrl+lohistage vahet mujale ümberpaigutamiseks. Seaded → Silos → Gap height juhib paksust.

### 5. Mitmevalik silod

- Shift+klõps — vahemiku valik
- Ctrl+klõps — valiku lülitus
- Paremklõps valikul — partii Salvesta, Kustuta, Tühjenda (kustutab kõrgema indeksiga esmalt, vältimaks kohavahetusprobleeme)

### 6. Snippeti makrod (F1-F10)

10 kiir-sisestuse kohta projekti kohta. Seotud F1-F10 või Ctrl+Shift+1-9-ga.

- Ctrl+S — ava Snippet Manager (nimede + sisu muutmine)
- Paremklõps F-nupul — ümbernimetamine inline
- Toetab muutujate placeholdereid prompti mallide jaoks

### 7. Markdown-redaktor

**VaultTextEdit** — laiendatud QPlainTextEdit.

**Võimalused:**
- Reaalajas süntaksi esiletõst — päised, paks, kaldkiri, lingid, koodiaiad, märkeruudud, tsitaadid
- Reagutter — numbrid + voltimisnooled (▾)
- Sektsiooni voltimine — klõps ▾-l voltib päised kokku
- Koodiaia kopeerimisnupp — hover aiast, klõps kopeerimisikoonil
- Märkeruudu klõps — klõps `- [ ]`-l lülitab `- [x]`-iks
- Kokkuvolditavad pildid — `![alt](url)` renderdub kompaktse pillina (150px). Ctrl+klõps avab, Ctrl+paremklõps avab kausta
- Nutikas asetamine — tabelid/loendid/kood asetuvad puhtamalt

**Vormindamise klõbustikud:**
- Ctrl+B/I/U/T — paks/kaldkiri/allajoonimine/läbikriipsutus
- Ctrl+Return — märkeruudu lülitus
- Ctrl+E — päise sisestamine (kohandatav: reegel, täpp, ajatempel, joondus)
- Ctrl+W — eraldaja `---` sisestamine nutika reajaotusega (eemaldab duplikaat-täpi)
- Alt+W — eraldaja üles + täpp ülespoole
- Ctrl+Shift+Q — tsitaadi lülitus
- Ctrl+Klõps täpil — lülitus `-` / `•`
- Ctrl+KeskmineNupp — kustuta rida kursori all (nutikas ümbervool: nummerdatud loendid numereeritakse ümber)
- Alt+Z — reanumbrite lülitus
- Alt+Backspace — sõna kustutamine

### 8. Märgistuse peitmise režiim (T-603)

Lülitus Seadetes → Redaktor → Hide Markup. Peidab **paks**, *kaldkiri*, ~~läbikriipsutatud~~ ja `kood` märgid, et tekst loetaks puhtalt. Kursoriplokk hoiab oma märke, et redigeerimine jääks võimalikuks. Värvib ümber ainult 2 plokki kursori liikumise ümber.

### 9. Kanban-tahvel

Insert Kanban loob markdown-kanban-tahvli (puhas tekst, peab vastu save/db round-tripile).

- Alt+↑/↓ — liiguta kaarti üles/alla veerus
- Alt+←/→ — liiguta kaarti naaber-veerdu
- Enter tühjal tahvlireal — uus kaardirida
- Alt+klõps — märkeruudu lülitus kaardil

### 10. Tabeliehitaja

Insert Table loob markdown-tabeli. Tab/Shift+Tab liiguvad lahtrites. Tab viimaselt lahtrilt kasvatab uue rea. Enter lisab rea (mitte lahter lõhustub).

### 11. Failikonteiner

Iga silo saab `data/silo_files/<project>/<slot_idx>/` kettale.

- Lohista failid sahtli overlayle → kopeeri silo kausta
- Drop-overlay (4 valikut): Sisesta tekst, Sisesta link, Kopeeri failidesse, Otsetee
- Mallid: IN/OUT, Assets, Drafts, Kohandatud
- Pildi eelvaade + avamine vaikerakendusega
- Ctrl+klõps 📁 — silo teksti eksport .md-failina

### 12. Watcheri mootor (Alt+C)

Promptide äravool + automaatne saatmine sihtrakendusse.

- Alt+C — praegune rida kursori all järjekorda (bloki-ankurdatud)
- Alt+Shift+C — Queue Master dialoog (järjekordade vaatamine/ümberjärjestamine/tühjendamine)
- Armeerimine: sihtrakendus (CDP Electroni jaoks, Win32 natiivsete jaoks), oskus/prompti ümbris
- Kiiruspiirid: settle=2.5s, min gap=4s, max 25 saatmist seansi kohta
- Oskused: `/review`, `/refactor`, kohandatud prompti mallid

Vaata [Watcheri mootori arhitektuuri](Watcher-Engine-Architecture) täpsemalt.

### 13. Hashtagi süsteem

`#tag` silo tekstis indekseeritakse silode-üleseks otsinguks. Alt+Shift+T avab Hashtag Dialoogi — otsi sildi järgi, vaata kõiki sobivaid silosid, klõpsa hüppamiseks.

### 14. Taimerid ja Pomodoro

**Taimerid:** seadistamine läbi Ctrl+Shift+T või taimerinupu. Kohandatav nimi, kestus, heli, helitugevus, värvi kiireloomulisus. Taimeri toast-teade edasilükkamisega (Win95 3D kaldservad).

**Pomodoro:** töö/pausi olekumasin. Kohandatavad intervallid. Salve teade + heli faasilõpul. Taimeri silt kella kõrval näitab järelejäänud aega + kiireloomulisuse värvi.

### 15. Zen-režiim (Ctrl+D)

3-astmeline tsükkel:
1. **Zen** — peida külgriba, snippeti riba, failikonteiner, olekuriba, raami ääred. Nähtav ainult redaktor.
2. **Solo** — minimeeri kõik teised töölaua aknad. Redaktor jääb.
3. **Tagasi** — taasta töölaud + tavaline paigutus.

### 16. Akna haakimine (Ctrl+Q)

Tsükkel: Üles-Vasak, Üles-Parem, All-Vasak, All-Parem, Keskel, Täis, Kursori asend. FancyZone overlay näitab 7 visuaalset tsooni klõpsul. Akna preseedi leht salvestab kuni 10 kasutaja geomeetriat (ekraani murdosadena — peavad vastu monitorivahetusele).

### 17. Otsimine ja arhiiv

- **Arhiivi silo** — liiguta lõpetatud silo arhiivi (hoiab teksti, eemaldab aktiivsest loendist)
- **Arhiivi vahekaart** — arhiveeritud silode sirvimine projekti kaupa
- **Prügikasti dialoog** — pehme kustutatud silode ja failide sirvimine/taastamine
- **Silo sünkroonimine kettale** (T-591) — ühesuunaline .md eksport väliskausta projekti kohta

### 18. Numbrikasti režiim (T-607)

Seaded → Aken → Paigutus → Numbrikastid reas. Asendab projektide kombokasti nummerdatud nuppudega. Paremklõps lisamiseks/ümbernimetamiseks/kustutamiseks. Ratas ikka vahetab. Projektide piir 100.

### 19. Tööriistariba kohandamine

Seaded → Customize Toolbar. Lohista nuppe ümberjärjestamiseks. Nähtavad vahevidinad näitavad, kuhu nupp maandub. Reset taastab vaikimisi järjestuse.

### 20. Ülevoolumenüü

Kui päis < 700px: peidetud nupud kogutakse » popup-i. Iga toiming jääb kättesaadavaks — vormindamine, navigatsioon, silo toimingud, tööriistad.

### 21. SAIPENi integratsioon

Ctrl+Shift+C avab SAIPEN-vaataja (STATE/BOARD/LOG `.saipen/`-ist). Tööriistariba nupud kiireks juurdepääsuks, kui projektikaustas on `.saipen/`.

### 22. Varukoopia

**Kihid:**
1. SQLite WAL — krahhikindlad kirjutused (synchronous=NORMAL)
2. .bak — käivitumisel + iga 60 s (täielik SQLite varukoopia .bak-faili)
3. Igapäevane markdown-peegel — `~/Documents/.fastprompter/` (silos projekti kohta + arhiiv + snippetid)
4. Kaasaskantav ZIP — käsitsi varukoopia Backup-dialoogi kaudu
