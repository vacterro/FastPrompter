# FastPrompter tõrkeotsing ja KKK

## 1. GUI / Qt probleemid

### Rakendus ei käivitu / tühi aken

**Põhjused:**
- Aegunud IPC-lukk — eelmine instants krahhis avatud socketiga
- Ekraanivälised aknakoordinaadid — monitor ühendati lahti, kui aken oli sinna salvestatud
- Kõrge DPI / skaleerimise artefaktid

**Lahendus:**
- Kustuta `%TEMP%\fastprompter_ipc.token` või `%TEMP%\fastprompter.lock`
- Ctrl+Q kaks korda tsükliks ekraanikeskme haakimiseni
- Käivita lipuga `--reset-pos`
- Kohanda UI skaalat: Seaded või Ctrl+Plus/Miinus

### Kirillitsa / mitte-QWERTY klõbustikud ei tööta

Paigutusest sõltumatu VK-edastus ajab selle ära. Kui ikka ei tööta:
1. Ava Seaded (Alt+`)
2. Seo ebaõnnestunud klõbustik ümber füüsilise klahvi tuvastusega
3. Veendu, et pynput globaalne konks omab lubasid Windowsi turves

## 2. Krahhilogid

| Fail | Tee | Otstarve |
|---|---|---|
| Rakenduse logi | `%TEMP%\fastprompter.log` | Rotatsioon, max 1MB, 2 varukoopiat |
| Krahhilogi | `%TEMP%\fastprompter_crash.log` | sys.excepthook tracebackid |
| Testide logi | `%TEMP%\fastprompter-tests.log` | Pytest seansi logi |

Vaade:
```
powershell:
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50

cmd:
type %TEMP%\fastprompter_crash.log
```

Lisa mõlemad logid, kui esitad probleemi.

## 3. Protsesside puhastamine

**Sümptom:** Alt+X ei tee midagi. Teine käivitus ütleb «Another instance running».

**Lahendus:**
```
cmd:
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe

powershell:
Stop-Process -Name FastPrompter -Force
Stop-Process -Name pythonw -Force
```

## 4. Andmebaasi lukustumine / riknemine

DB-failid: `data/local_data_v15.db` (+wal, +shm)

### «database is locked»
1. Tapa kõik FastPrompteri protsessid (vt §3)
2. Kontrolli data/ kausta õigusi (peab olema kirjutatav)
3. Kustuta -wal ja -shm failid (SQLite taastab .db-st)

### «database disk image is malformed»
1. **Autovarukoopia:** nimeta `.db.bak` → `.db`
2. **Markdown-peegel:** taasta `~/Documents/.fastprompter/`-ist (lamedad .md failid)
3. **SQLite CLI parandus:**
```
sqlite3 local_data_v15.db ".recover" > dump.sql
sqlite3 repaired.db < dump.sql
copy repaired.db local_data_v15.db
```

## 5. Klõbustike konfliktid

**Sümptom:** «Global hotkey Alt+X binding failed»

**Põhjus:** Teine rakendus registreeris sama klõbustiku (GeForce Experience, PowerToys, Discord, AutoHotkey jne.)

**Lahendus:**
- Vaheta FastPrompteri kutsumise klõbustik Seadetes (Alt+`)
- Või seo konfliktne rakendus ümber
- Proovi Alt+Z, Ctrl+Alt+P või F12 alternatiivina

## 6. KKK

### K1: Kas andmed on pilves?
**Ei.** 100% lokaalne, võrguühenduseta. Null telemeetriat, null kaugkõnesid.

### K2: Kuidas varundada?
Kopeeri `data/` kaust. Või kopeeri `~/Documents/.fastprompter/`. Või kasuta Backup-dialoogi.

### K3: Kas USB-ga kaasaskantav?
**Jah.** Hoia `FastPrompter.exe` + `data/` kaust koos suvalisel kettal. Pole registrit, pole AppDatat.

### K4: Tehase lähtestus?
Kustuta `data/local_data_v15.db`. Rakendus loob skeemi järgmisel käivitamisel uuesti.

### K5: Kas Python on käivitamiseks vajalik?
**Ei.** Nuitka kompileeritud iseseisev EXE. Pythoni käituskeskkonda pole vaja.
