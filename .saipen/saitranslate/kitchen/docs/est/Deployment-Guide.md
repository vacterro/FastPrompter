# FastPrompter ehitamise ja väljalaske juhend

## Ülevaade

Ühefaililine kaasaskantav EXE (`FastPrompter.exe`). Pole installerit, pole administraatoriõigusi, pole Pythoni käituskeskkonda. Kogu olek `data/` kaustas binaari kõrval.

---

## Eeltingimused

- **Python** 3.11+
- **uv** (paketihaldur) või pip
- **Nuitka** >= 4.1.2
- **C-kompilaator** — Nuitka laadib automaatselt, kui puudub
- **UPX** (valikuline, 50-60% suuruse vähendamine)
- **Git** Windowsile GitHubi tunnustega

---

## 1. Kompileerimine (`tools/build.py`)

```bash
uv run python tools/build.py
```

### Sammud
1. Kontrolli Nuitka >= 4.1.2 installimist (autoinstall, kui puudub)
2. Tuvasta UPX PATH-is (lisab `--plugin-enable=upx`, kui leitud)
3. Süsti `src/` PYTHONPATH-i puhta moodulijälje jaoks
4. Kompileeri `FastPrompter.pyw` (GUI sisenemispunkt, ilma konsoolita)
5. Väljund: `build/FastPrompter.exe`

### Peamised lipud
```python
cmd = [
    sys.executable,
    "-m", "nuitka",
    "FastPrompter.pyw",
]
if upx_bin:
    cmd.append("--plugin-enable=upx")
    cmd.append(f"--upx-binary={upx_bin}")
```

Väljund EXE ~15-28MB sõltuvalt UPX-ist.

---

## 2. Avaldamine (`tools/release.py`)

```bash
uv run python tools/release.py [release_notes.md]
```

### Sammud
1. Kontrolli, et `build/FastPrompter.exe` on olemas
2. Loe versioon `pyproject.toml`-ist (silt = `v<version>`)
3. Eralda GitHubi token Windows Credential Managerist (`git credential fill`)
4. Kontrolli sildi olemasolu GitHub API kaudu
   - Ei → loo uus väljalase
   - Jah → uuenda väljalaske märkmeid
5. Laadi `build/FastPrompter.exe` üles väljalaske varana (kustutab vana esmalt)

---

## 3. Ühe-kliki skriptid

### deploy.cmd / deploy.ps1
Commit + push kõigi projektimuudatuste jaoks:
- Stage kõik (`git add -A`)
- Ajatempliga commit (`deploy: YYYY-MM-DD HH:mm`)
- Pull rebase (`git pull --rebase --autostash origin main`)
- Force push konfliktide korral (`git push --force-with-lease origin main`)

### release.cmd
Ehitus + avaldamine ühe klõpsuga:
```
uv run python tools\build.py || pause
uv run python tools\release.py %*
```

---

## Tõrkeotsing

| Probleem | Põhjus | Lahendus |
|---|---|---|
| `ImportError: No module named fastprompter` | Nuitka ei jälginud src/ | Veendu, et PYTHONPATH sisaldab src/ (build.py teeb seda) |
| `No GitHub credential found` | Git-token pole Credential Manageris | Käivita üks kord käsitsi `git push` tokeni salvestamiseks |
| Suur EXE (>60MB) | UPX pole PATH-is | Installi UPX saidilt https://upx.github.io/ |
| Rebase konflikt deploy-l | Kaugrepo redigeeritud otse GitHubis | Force-with-lease push (deploy.ps1 teeb seda automaatselt) |
