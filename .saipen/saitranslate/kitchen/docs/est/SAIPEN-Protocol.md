# SAIPEN-protokoll v7 ja SubSaipen-arhitektuur

## Ülevaade

SAIPEN (v7) — kerge struktureeritud protokoll püsivaks AI-agendi ülesannete jälgimiseks, oleku halduseks, sündmuste logimiseks ja mitme-agendi deleerimiseks. Null konteksti-triivi pikkade seansside jooksul masinloetavate failide kaudu `.saipen/` kaustas.

---

## 1. Põhiprotokoll

### Mälu struktuur (`.saipen/`)

```
.saipen/
├── STATE.md         # Faas, ülesanne, blokeerija, agendi parameetrid
├── BOARD.md         # Kanban: DOING/TODO/DONE/BLOCKED
├── LOG.md           # Lisanduv töölähend (RFC § 1.2)
├── KNOWLEDGE/       # Alamsüsteemide teatmekaardid
├── kitchen/         # Mustandid, vahetulemused
├── snapshots/       # Ajatempliga STATE/BOARD/LOG varukoopiad
└── recovery/        # Pühkimise taastamisarhiivid
```

### STATE.md skeem (YAML frontmatter)

```yaml
---
phase: SCOUT | PLAN | BUILD | VERIFY | REVIEW | DONE | BLOCKED
task: "Aktiivse ülesande kirjeldus"
next_action: "Vahetu järgmine samm"
blocker: ""  # Põhjus, kui BLOCKED
agent: claude | main | <nimi>
saipen_version: 7
saipen_home: "V:\\tee\\saipenile"
mode: full | read-only
requires: [filesystem, python, shell, git]
updated: 2026-07-30T12:00:00Z
---
```

### Faaside olekumasin

1. **SCOUT** — koodibaasi inspekteerimine, sõltuvuste kontroll, logide lugemine
2. **PLAN** — piletite loomine BOARD.md-s, kujundus
3. **BUILD** — koodi/konfigide/dokumentatsiooni realiseerimine
4. **VERIFY** — testide, linterite, käsitsi kontrollide käivitamine
5. **REVIEW** — diffi ülevaade, LOG-i kanne
6. **DONE** — kõik piletid lõpetatud
7. **BLOCKED** — kinni, blokeerija väli selgitab miks

### Sündmuste logi (LOG.md)

```
- 2026-07-30T12:00:00Z [E-001] [T-057] [agent: main] RUN: fix -> PASS
```

### Peamised reeglid
- Üks agent kirjutab `.saipen/`-i korraga (RFC § 1.4)
- Määrdunud puu on TAVALINE — atribuut enne tegutsemist, ära kunagi reeda/kommi teise agendi kinnitamata tööd (RFC § 1.5)
- Kontrollpunkti järjekord: LOG → BOARD → STATE (krahhikindel asümmeetria, RFC § 1.5)
- Pileti formaat: ainult `T-###` (RFC § 1.2)

---

## 2. SubSaipen-arhitektuur

Isoleeritud read-only alamagendid. Väljund ainult `.saipen/extensions/subs/<name>/` sees.

```
project-root/
└── .saipen/
    └── extensions/
        └── subs/
            ├── MANIFEST.md         # Aktiivsete alamsüsteemide loend
            ├── PROTOCOL.md         # Täielik sub-protokoll
            ├── _shared/inbox.md    # Agentide-ülene inbox
            ├── TEMPLATE/           # Bootstrap-mall
            ├── saiwiki/            # Wiki generaator (faas DONE)
            └── saihunt/            # Veaotsija (faas DONE)
```

### Elutsükkel
1. **SPAWN** — `saipen sub spawn <name>` kopeerib TEMPLATE-i, lisab MANIFEST-i
2. **WORK** — loeb peamist projekti (read-only), toodab artefakte oma kitchen/-is
3. **SIGNAL** — OUTBOX.md kanne `status: ready`
4. **COLLECT** — peamine agent käivitab `saipen sub collect`, loob T-### piletid kriitilistele leidudele

### OUTBOX-i formaat

```markdown
# OUTBOX

## WIKI-001: Kirjeldus
- **status:** ready | draft | blocked | reviewed
- **summary:** üherealine leid
- **main_project_refs:** [docs/wiki/foo.md]
- **critical:** true | false
- **severity:** P0 | P1 | P2 (valikuline)
- **details:** täielik kirjeldus
```

### Pileti ID nimeruum

| Eesliide | Omanik |
|---|---|
| `SYS-` | Läbilõikav / protokoll |
| `WIKI-` | saiwiki |
| `HUNT-` | saihunt |
| `PY-` | saipython (parandaja) |
| `<NAME>-` | Mis tahes muu alamsüsteem |

Sub-ID-sid ei panda kunagi otse peamisele BOARD.md-le — alati tavaline `T-###` originaaliga kirjelduses.

### Käsud

| Käsk | Toiming |
|---|---|
| `saipen sub list` | Näita aktiivseid alamsüsteeme + faasi (WARNING BLOCKED-i korral) |
| `saipen sub spawn <name>` | Loo uus alamagent |
| `saipen sub collect` | Töötle kõik OUTBOX-i kanded |
| `saipen sub clean <name>` | Eemalda alamagent (keeldub kogumata leidude korral) |
| `saipen sub status <name>` | Piilu OUTBOX-i ilma kogumata |
| `<name>` (üksi) | Rolli-võtmise otsetee — muutu selleks alamagendiks |
| `saipen sub pause <name>` | Külmuta alamagent (BLOCKED) ilma olekut hävitamata |
| `saipen sub resume <name>` | Sulata alamagent üles |

### Parandajatüüpi sub (saipython)

Läheb kaugemale — OUTBOX kannab **testitud paranduse** ühendatud diffina. Töö tehakse oma `kitchen/pen/` liivakastis (sihtfaili koopia). Kontrollitud projekti enda testiharjaga enne `ready` märkimist. Ei kirjuta kunagi peamisse puusse.

```markdown
## PY-001: Kirjeldus
- **status:** ready
- **patch:**
  ```diff
  <ühendatud diff, rakendub repo juurest>
  ```
- **verified:** pytest PASS (N) / ruff clean / mypy clean
- **base_head:** abc1234
```

---

*FastPrompter Wiki — ehitatud [SAIPEN-protokolliga](SAIPEN-Protocol) | [GitHub Repo](https://github.com/vacterro/FastPrompter)*
