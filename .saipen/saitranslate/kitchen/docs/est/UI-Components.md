# FastPrompter UI komponentide teatmik

## Paigutuse mudel

Vintage-Win95 esteetika. Raamita, tumedakuldne, teravad kaldservad. Klaviatuuri-esimene. Päis kohandab tiheduse astmeid automaatselt (täielik → tihe <1280px → ülike <700px).

```
+------------------------------------------------------------------+
| [Tab1][Tab2]... | 🔍 | 📌🎨⚙️🕒🧠 | LN:42 | Tok:156 | DD.MM - HH:MM | ⚙ | » | [_][X] |
+--------------------------------+---------------------------------+
| SIDEBAR (silos + snippetid)    | EDITOR (VaultTextEdit)          |
| ┌──────────────────────────┐   | ┌──────┬────────────────────┐  |
| │ Silo 00  📌 ✅   📁  📁│   | │  1.  │ # Heading           │  |
| │ Silo 01       📁       │   | │  2.  │ Regular text here   │  |
| │ ─── gap ───            │   | │  3.  │ - [ ] checkbox      │  |
| │   └─ child silo  📁    │   | │  4.  │ ```python           │  |
| │ Silo 02  🎨     📁    │   | │      │ print("code")        │  |
| │ [F1][F2]...[F10]       │   | │      │ ```                 │  |
| └──────────────────────────┘   | └──────┴────────────────────┘  |
|                                | FILE CONTAINER DRAWER           |
|                                | [📁 file1] [📁 file2] [📁 IN/OUT]|
+--------------------------------+---------------------------------+
| Timer: 12:34  📊               |  Words: 240  |  Lines: 42       |
+------------------------------------------------------------------+
```

## Peamised komponendid

### 1. Päise tööriistariba

Kohandatav nuppude riba. Tokenid: kategooria vahekaardid, otsing, silo juhtimine, vormindamine, kell, reaarv, tokenite arv, seaded, salve nupud. Lohista-sisesta ümberjärjestuse režiim (Seaded → Customize Toolbar). Ülevoolumenüü ülikitsa režiimi korral.

**Tiheduse astmed:**
- **Täielik** (>1280px efektiivne): kõik nupud nähtavad
- **Tihe** (<1280px): siltide lühendamine + 18px ruudud + vahekaartide kerimine; peidetud: Clear Fmt, Line, Home/End, Underline, Strike, Copy, Vision, joondused
- **Ülike** (<700px): portree-kild; ellu jäävad ainult vahekaardid, NEW/Save, lühike kell, loendur, ⚙. » ülevoolumenüü kogub ülejäänu

### 2. Snippeti ja silo paneel (`ui/snippet_panel.py`)

**Siloloend:** kuni 100 projekti vahekaardi kohta. Võimalused:
- Pinn (📌) — kinnita üles, sorteeritud kinnitamata üles
- Linnuke (✅) — silode-ülene lõpetamise märk
- Värvikast (🎨) — silo-põhine värvitoon (lülitus Seadetes)
- Failikonteineri ikoon (📁) — avab failisahtli
- Hierarhia — lohista teisele silole pesastamiseks; Shift+lohistamine vahetab; voltimisnool (▾/▸)
- Värskuse soojuskaart — soe taustatoon hiljuti redigeeritule
- Külgriba vahed — kasutaja määratud eraldusribad; Ctrl+lohistamine ümberpaigutuseks
- Mitmevalik — Shift=vahemik, Ctrl=lülitus; partii kustutamine/salvestamine/tühjendamine

**Snippeti kohad (F1-F10):** 10 makro-sisestuse nuppu projekti vahekaardi kohta. Paremklõps nime/sisu muutmiseks. Ctrl+S või topeltklõps avab Snippet Manager dialoogi.

### 3. Markdown-redaktor (`ui/editor.py` — VaultTextEdit)

**Reagutter:** vasak serv — reanumbrid + voltimisnooled (▾) + marginaalimärgid + soojusribad.

**Süntaksi esiletõst:** `# Päised`, `**paks**`, `*kaldkiri*`, `~~läbikriipsutatud~~`, `[lingid](url)`, `` `kood` ``, ```koodiblokid```, `- [ ]` märkeruudud, `> tsitaadid`, `---` reeglid.

**Koodiaiad:** mono-tähtedega (Consolas vaikimisi) + ühe-kliki kopeerimisnupp + voltimine kokku.

**Kokkuvolditavad pildid:** `![alt](url)` → kompaktne 150px nupp. Ctrl+klõps avab, Ctrl+paremklõps avab kausta.

**Interaktiivsed märkeruudud:** klõps `- [ ]`-l lülitab `- [x]`-iks.

**Märgistuse peitmise režiim (T-603):** lülitus peidab `**`, `*`, `~~`, `` ` `` märgid → tekst loetakse renderdatuna. Kursoriplokk hoiab märke redigeerimiseks.

**Drop-overlay:** 4 valikut lohista-sisestusel: Sisesta tekst, Sisesta link, Kopeeri failidesse, Loo otsetee.

### 4. Failikonteineri sahtel (`ui/file_container.py`)

Silo-põhine kokkuvolditav sahtel. Manustatud failid, pildi pisipildid, dokumendi otseteed.

- Mallid: IN/OUT, Assets, Drafts, Kohandatud kaustastruktuur
- Lohista-sisesta failide lisamiseks
- Silo eksport: Ctrl+klõps 📁 ekspordib silo teksti .md-faili

### 5. Kanban-tahvel (`ui/silo_kanban.py`)

Puhtalt-tekstiline markdown-kanban. Alt+nooleklahvid liigutavad kaarte veergude vahel. Enter lisab rea. Märkeruudu klõps märgib kaardi. Pole Qt-tabeleid — töötab tavalisel markdownil, peab vastu salvestamisele.

### 6. Tabeliehitaja (`ui/silo_table.py`)

Puhtalt-tekstiline markdown-tabel. Tab/Shift+Tab lahtrite läbikäimine. Tab viimaselt lahtrilt kasvatab rea. Enter lisab rea. Ei lõhusta lahtrit. Töötab tavalisel teksti.

### 7. Dialoogid ja overlayd

| Dialoog | Otstarve |
|---|---|
| `Settings (Alt+`)` | Teemavalija, klõbustike ümbersidumine, heli, skaala, tööriistariba ümberjärjestus |
| `Snippet Manager (Ctrl+S)` | F1-F10 snippeti nimede + sisu redigeerimine |
| `Saipen Viewer (Ctrl+Shift+C)` | Read-only STATE/BOARD/LOG vaataja |
| `Timer Dialog (Ctrl+Shift+T)` | Pomodoro + taimeri seadistamine |
| `Queue Master (Alt+Shift+C)` | Watcheri järjekorra ülevaade silo kaupa |
| `Hashtag Dialog (Alt+Shift+T)` | Silode-ülene sildiotsing |
| `Trash Dialog` | Pehme kustutatud silode sirvimine/taastamine |
| `Backup Dialog` | DB eksport/import, varukoopia hetktõmmis |
| `Help Dialog` | Interaktiivne klõbustike teatmik |
| `Window Presets` | Akna geomeetria preseedide salvestamine/ümbernimetamine/ümberjärjestamine/liigutamine |
| `Project Manager` | Projektide näitamine/peitmine, ümberjärjestamine (▲▼) |
| `Color Config` | Kohandatud teema värvide redigeerimine |

### 8. Akna komponendid

- **FancyZoneOverlay** — visuaalne 7-tsooni valija ekraanihaakimiseks
- **AnalogClock** — kohandatult joonistatud kella vidin (päis)
- **PieMenu (Shift+Alt+X)** — radiaalne menüü: teemad, skaala, tööriistad
- **Ülevoolumenüü (»)** — peidetud nupud ülikitsas režiimis
- **Resizers** — kohandatud suurusemuutmise käepidemed (T-629 parandus: WS_CAPTION ümberarvutus)
- **ZenDesktop** — 3-astmeline Ctrl+D: Zen → Solo (kõikide minimeerimine) → tagasi
