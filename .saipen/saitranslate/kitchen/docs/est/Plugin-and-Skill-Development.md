# Plugin-, oskuste ja laienduste arendamise juhend

## 1. Kohandatud oskused (`core/watcher/skills.py`)

Oskused on prompti ümbrised, mida rakendatakse, kui üksused saadetakse watcheri kaudu.

### Definitsioon

```python
# Oskuse kirje dict
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review this code:\n\n{text}",
    "description": "Standard code review prompt wrapper"
}
```

### Malli muutujad
- `{text}` — järjekorras oleva üksuse tekst
- `{timestamp}` — praegune aeg
- `{project}` — aktiivse projekti nimi

### Rakendamine
Määra vaikimisi oskus Seaded → Watcher → Default Skill kaudu. Tühista üksuseti Queue Master dialoogis.

## 2. SAIPENi alamagendid

Alamagendid elavad `.saipen/extensions/subs/<name>/` (mitte projekti juurkaustas `subs/`).

```
.saipen/extensions/subs/
├── MANIFEST.md          # aktiivsete alamsüsteemide loend
├── PROTOCOL.md          # reeglid
├── TEMPLATE/            # bootstrap-mall
├── saiwiki/             # wiki-dokumendi generaatori alamagent
├── saihunt/             # veaotsija alamagent
└── _shared/inbox.md     # agentide-ülene side
```

### Üleandmine (OUTBOX.md)

```
# OUTBOX

## WIKI-001: Kirjeldus
- **status:** ready | draft | blocked | reviewed
- **summary:** üherealine leid
- **critical:** true | false
- **details:** täielik kirjeldus
```

`critical: true` → peamine agent loob kohe T-### pileti.
`critical: false` → järjekorda `_shared/inbox.md`-i järgmiseks planeerimisringiks.

**Käsud:**
- `saipen sub spawn <name>` — loo uus alamagent TEMPLATE-ist
- `saipen sub collect` — kogu kõik OUTBOX-i kanded
- `saipen sub list` — näita aktiivseid alamagente + faasi
- `saipen sub clean <name>` — eemalda lõpetatud alamagent

## 3. Kohandatud teemad

Fail: `data/custom_theme.json`. Laetakse, kui teema = Custom.

### Skeem

```json
{
  "theme_name": "My Theme",
  "colors": {
    "bg_main": "#1e1e1e",
    "bg_editor": "#1b1b1b",
    "fg_text": "#d4d4d4",
    "fg_accent": "#e6b422",
    "border": "#3c3c3c",
    "selection": "#264f78",
    "header_bg": "#252526",
    "button_bg": "#2d2d30",
    "text_primary": "#d4d4d4",
    "text_accent": "#e6b422"
  }
}
```

**Rakendamine:** Seaded → Teema → Custom. Hetkeline hot-reload, ilma taaskäivitamiseta.

## 4. Kursori teemad (`ui/cursor_theme.py`)

Kohandatud hiirekursori komplektid. Retro-arvestuse tunne.

**Funktsioonid:**
- `capture_current_scheme()` — kopeeri elav Windowsi kursori komplekt programmi
- `load_bundle()` — tagasta installitud kursori komplekt
- `install_to_system(paths)` — määra Windowsi vaikimisi kursori skeemiks
- `build_cursor_map()` — ehita kursori kujude kaart uuesti

**Lülitus:** Seaded → Kursorid → Enable custom cursors. Esimesel sisselülitamisel püütakse automaatselt praegune Windowsi komplekt.

## 5. Watcheri mootori laiendatavus

| Moodul | Laienduspunkt |
|---|---|
| `adapter.py` | Rakenda ProbeAdapter kohandatud sihtmärgi tuvastamiseks |
| `cdp.py` | Kohandatud CDP-käsud Electroni rakendustele |
| `win32.py` | Win32 aknaproovi kohandamine |
| `skills.py` | Lisa kohandatud prompt-oskuse malle |
| `limit_scan.py` | Kohandatud agentide-ülene limiidiskanner |
| `sender.py` | Kohandatud teksti süstimise strateegiad |

## 6. Silo sünkroonimine kettale (T-591)

Ühesuunaline silo → failisüsteemi eksport. Seaded → Sync mode: Off / Silo (lame) / Hierarchy (pesastatud). Kirjutab `<root>/<category>/<NN_slug>.md` salvestamisel. Ei loe kunagi tagasi, ei kustuta kunagi. Jätab muutmata teksti vahele.
