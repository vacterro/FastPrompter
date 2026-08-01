# FastPrompter Wiki

FastPrompter — ülikiire klaviatuuripõhine märkmik + promptide töölaud Windowsile. Python 3.11+, PyQt6. SQLite WAL püsimälu. Nuitka ehitatud iseseisev EXE.

> **Alt+X** kutsub 100-kohalise märkmiku kursori juurde. Null installi, null pilve, null telemeetriat. Kogu olek sünkroonub hetkega kohalikku andmebaasi.

---

## Tehnilise dokumentatsiooni indeks

### Põhiarhitektuur
- **[Arhitektuuri ülevaade](Architecture-Overview)** — süsteemi kujundus, IPC single-instance, SQLite WAL, oleku sünkroonimine, alamsüsteemid
- **[Moodulite struktuur](Module-Structure)** — `src/fastprompter/` puu, failide vastutus, core/ui/utils/watcher kaart
- **[Core API ja klassid](Core-API-and-Classes)** — FastPrompterState, HotkeyManager, IPCServer, SoundManager, PomodoroEngine, UI vidinad
- **[Watcheri mootor](Watcher-Engine-Architecture)** — CDP ühendus, Win32 konksud, järjekorra süstimine, olekumasin, kiiruspiirid

### Liides ja andmed
- **[Konfiguratsioon](Configuration)** — andmebaasi skeem (local_data_v15.db), seadete võtmed, kohandatud teemade mootor, varukoopiapeeglid
- **[UI komponendid](UI-Components)** — paigutuse skeem, paneelide jaotus (Editor, Silos, Queue, Files, Kanban, Table)
- **[Klõbustikud](Keyboard-Shortcuts-and-Cheatsheet)** — täielik teatmik: globaalsed, aken, vormindamine, watcher, silo, snippetid

### Juhendid ja laiendatavus
- **[Kasutusjuhend](User-Guide)** — töövoogud, silo haldus, snippetide makrod, failikonteinerid, zen-režiim, Pomodoro taimer, märgistuse peitmine, kanban/table
- **[Tõrkeotsing ja KKK](Troubleshooting-and-FAQ)** — krahilogid (%TEMP%\\fastprompter_crash.log), protsesside puhastus, andmebaasi parandus, klõbustike konfliktid
- **[Plugin- ja oskuste arendus](Plugin-and-Skill-Development)** — kohandatud oskused (skills.py), SAIPEN alamagendid, kohandatud teemad, kursori teemad

### Automatiseerimine ja protokoll
- **[SAIPEN protokoll](SAIPEN-Protocol)** — v7 spetsifikatsioon: olekumasina tsükkel, sündmuste logimine, subSaipen read-only arhitektuur, OUTBOX üleandmisprotokoll
- **[Ehitamise juhend](Deployment-Guide)** — Nuitka kompileerimine (tools/build.py), GitHub väljalase (tools/release.py), ühe-kliki skriptid

---

## Projekt

- **Hoidla**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **Pinu**: Python 3.11+, PyQt6, SQLite WAL, Nuitka ≥4.1.2, pynput
- **Litsents**: MIT

---

*Ehitatud [SAIPEN protokolliga](SAIPEN-Protocol) | [GitHub](https://github.com/vacterro/FastPrompter)*
