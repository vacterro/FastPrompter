# Watcheri mootori arhitektuur

## Ülevaade

Promptide äravoolu + sihtmärgi automatiseerimise alamsüsteem. Paneb prompte järjekorda, jälgib sihtrakenduse olekut (Electron/veeb/mis tahes Win32 aken), saadab automaatselt, kui sihtmärk on vaba.

---

## Kõrgetasemeline arhitektuur

```
+------------------------------------------------------------------+
|                        Watcher Engine (engine.py)                  |
|  +------------------+    +------------------+   +--------------+  |
|  | Olekumasin       | -> | Proovid ja konksud| ->| SendIntent   |  |
|  | DISARMED→ARMED→  |    | (Win32 + CDP)    |   | Generaator   |  |
|  | WATCHING→SENDING |    +------------------+   +--------------+  |
|  +------------------+                                          |
+------------------------------------------------------------------+
                              v
+------------------------------------------------------------------+
|  Järjekord (queue.py)        |    Saatja (sender.py)             |
|  - Sihtmärgi-põhine queue_key|    - CDP Runtime.evaluate         |
|  - FIFO üksuste järjekord    |    - Win32 klahvisüstimine        |
|  - Kinnitatud queue_key      |    - Read-back kontroll           |
|    armeerimisel              |                                   |
+------------------------------------------------------------------+
```

---

## 1. Olekumasin (`engine.py`)

```
[DISARMED] ← (viga/paanika/max_sends)
    |
    | arm(target, queue_key)
    v
[ARMED] —→ (agent märgatud hõivatuna) —→ [WATCHING]
    ^                               |
    |     (saatmine lõpetatud)       | (agent vaba + settle_ms)
    +———————— <— [SENDING] ————————+
```

### Olekud
1. **DISARMED** — passiivne, proovid ei küsi, üksusi ei töödelda
2. **ARMED** — seotud sihtakna + queue_key-ga. Ootab sihtmärgi tegevust.
3. **WATCHING** — sihtmärk märgatud hõivatuna (LLM genereerib). Ootab vabadust + settle.
4. **SENDING** — SendIntent saadetud. Ootab süstimise kinnitust.

---

## 2. Chrome CDP (`cdp.py`)

Miks CDP: Electroni rakendused (VS Code, Claude Desktop, ChatGPT, Obsidian) ei töötle Win32-sõnumeid. Chromiumi IPC ignoreerib `PostMessageW` — märgid kaovad vaikselt.

### Operatsioonid
- `discover()` — päring `http://127.0.0.1:<port>/json/list` lehe-sihtmärkide jaoks
- WebSocket JSON-RPC ühendus lehe kohta
- `Runtime.evaluate` + `Input.dispatchKeyEvent` teksti süstimiseks
- **Read-back kontroll** — sisesta tekst, loe välja väärtus DOM-päringuga, Submit ainult vastavuse korral
- Mitteblokeerivad ajalõpud (3 s vaikimisi)

---

## 3. Win32 proovid (`win32.py`, `probes.py`)

Mitte-Electroni sihtrakenduste jaoks.

- `GetForegroundWindow()` + pealkirja regex-vastendus → sihtmärgi tuvastus
- Kursori + fookuse monitooring → süstimine ainult siis, kui sisestusväli on aktiivne
- `combine()` — mitme proovi oleku agregeerimine üheks bool-iks (is_target_active, is_target_busy, is_blocked)

---

## 4. Järjekorra mudel (`queue.py`)

### QueueItem
- `id` — UUID
- `text` — prompti tekst
- `skill` — ümbrisoskuse nimi
- `line` — lähterea number (reaalajas teksti jälgimiseks)

### SendIntent
- `item_id`, `text`, `queue_key`, `skill` — saatjale inkapsuleeritud

### Elutsükkel
1. **Pending** — järjekorras
2. **In-Flight** — SendIntent saadetud saatjale
3. **Sent** — saatja kinnitanud, järjekorrast eemaldatud
4. **Failed** — suurendab consecutive_failures, uuesti kuni max_failures (3)

### Järjekorra kinnitamine
`arm(target, queue_key)` korral kinnitatakse võti. Projekti/silo vahetamine seansi keskel → watcher tühjendab ikka õiget järjekorda.

---

## 5. Ohutuskaitsed

| Parameeter | Vaikimisi | Otstarve |
|---|---|---|
| `settle_ms` | 2500 | Vaikne aeg pärast sihtmärgi vabadust enne saatmist |
| `min_gap_ms` | 4000 | Min. viivitus järjestikuste saatmiste vahel |
| `max_sends` | 25 | Max prompte armeeritud seansi kohta (auto-disarm) |
| `max_failures` | 3 | Järjestikused ebaõnnestumised → disarm veaga |
| `panic()` | — | Hädasulgemine: disarm + kõigi in-flight tühistamine |

---

## 6. Oskuste süsteem (`skills.py`)

Prompti ümbrised, mida rakendatakse enne saatmist.

```python
{
    "name": "Code Review",
    "prefix": "/review",
    "template": "Review:\n\n{text}",
}
```

Muutujad: `{text}`, `{timestamp}`, `{project}`.

---

## 7. Oskused ja Watcheri dialoog

- `Alt+C` — praegune redaktori rida järjekorda (bloki-ankurdatud)
- `Alt+Shift+C` — Queue Master (kõigi silode ülevaade)
- Vaikimisi oskuse määramine Seadetes
- Watcheri dialoog: arm/disarm, sihtmärgi valik, proovide konfigureerimine
