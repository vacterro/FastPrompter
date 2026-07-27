# FastPrompter Build, Packaging & Release Deployment Guide

## Overview
FastPrompter is delivered as a single-file, zero-installer portable Windows executable (`FastPrompter.exe`). It requires no admin rights, no pre-installed Python interpreter, and no registry changes. All application state is stored locally in the `data/` directory adjacent to the binary.

---

## Prerequisites & Build Environment

FastPrompteri koostamiseks ja avaldamiseks on vaja järgmisi tööriistu:

- **Python**: versioon 3.11 või uuem.
- **Pakihaldur**: [`uv`](https://github.com/astral-sh/uv) (soovitatav) või standardne pip.
- **Koostaja**: [`Nuitka`](https://nuitka.net/) (versioon >= 4.1.2).
- **C-kompilaator**: C64/MSVC või MinGW64 (Nuitka laadib vajadusel automaatselt alla C-kompilaatori).
- **Kompressor (valikuline)**: [UPX](https://upx.github.io/) käivitatav lahtris PATH binaarsuuruse vähendamiseks 50–60%.
- **Git**: konfigureeritud GitHubi mandaatidega Git Windowsile.

---

## 1. Nuitka Compilation Pipeline (`tools/build.py`)

Eraldiseisev käivitatav fail kompileeritakse Nuitka abil faili "tools/build.py" kaudu.

### Execution Command
```bash
uv run python tools/build.py
```

### Build Steps & Technical Mechanics
1. **Nuitka Check**: Verification that `nuitka>=4.1.2` is installed. If missing, `tools/build.py` automatically invokes `pip install nuitka>=4.1.2`.
2. **UPX Detection**: Checks for `upx` in system PATH. If available, adds `--plugin-enable=upx` and `--upx-binary=<path>` flags to shrink binary size down to ~15-25MB.
3. **`PYTHONPATH` Injection**: Adds `src/` directory to environment `PYTHONPATH` during compilation so Nuitka traces and embeds the entire `fastprompter` package cleanly.
4. **Target Script**: Compiles `FastPrompter.pyw` (GUI entry point without console popup).
5. **Output**: Generates `build/FastPrompter.exe`.

### `tools/build.py` Source Workflow
```python
# Key invocation parameters inside build.py:
cmd = [
    sys.executable,
    "-m",
    "nuitka",
    "FastPrompter.pyw",
]
if upx_bin:
    cmd.append("--plugin-enable=upx")
    cmd.append(f"--upx-binary={upx_bin}")
```

---

## 2. GitHub Release Automation (`tools/release.py`)

Skript "tools/release.py" automatiseerib märgendi loomise ja binaarse levitamise GitHubi väljaannetes.

### Execution Command
```bash
uv run python tools/release.py [release_notes.md]
```

### Automation Steps
1. **EXE Verification**: Verifies `build/FastPrompter.exe` exists.
2. **Version Extraction**: Parses the exact version string from `pyproject.toml` (e.g., `version = "1.5.0"` -> tag `v1.5.0`).
3. **GitHub Credential Retrieval**: Invokes `git credential fill` using host `github.com` to safely extract the GitHub token stored in Windows Credential Manager (same token used by `git push`).
4. **Release API Dispatch**:
   - Queries GitHub API `https://api.github.com/repos/vacterro/FastPrompter/releases/tags/v<version>`.
   - If tag doesn't exist, creates a new GitHub Release.
   - If tag exists, updates release notes.
5. **Asset Upload**: Deletes old `FastPrompter.exe` release asset if present and uploads the newly compiled binary (`build/FastPrompter.exe`) via `uploads.github.com`.

---

## 3. One-Click Batch Scripts

Operaatori kiireks juurutamiseks sisaldab FastPrompter juurkataloogis kolme ühe klõpsuga skripti:

### A. `deploy.cmd` / `deploy.ps1` (Codebase Sync)
Double-click `deploy.cmd` to commit and push all project changes to GitHub.

- **PowerShelli skript (`deploy.ps1`)**:
  1. Etapib kõik muudetud failid (`git add -A`).
  2. Kui on olemas kinnitamata muudatused, loob ajatempliga sidumise `juurutamine: AAAA-KK-PP HH:mm.
  3. Tõmbab kaugmuudatused, kasutades käsku "git pull --rebase --autostash origin main".
  4. Lahendab konfliktid, sundides kohalikku osariiki võitma (`git push --force-with-lease origin main`, kui rebase ebaõnnestub).
  5. Tõukab värskendatud põhiharu lähtekohaks.

### B. `release.cmd` (Build + Release Pipeline)
Double-click `release.cmd` to run end-to-end build and deployment in one action.

```cmd
@echo off
uv run python tools\build.py || (echo BUILD FAILED & pause & exit /b 1)
uv run python tools\release.py %*
echo.
pause
```

---

## 4. Troubleshooting & Edge Cases

| Väljaanne | Algpõhjus | Lahendus |
|---|---|---|
| **`Impordiviga: sisseehitatud EXE-s ei ole moodulit nimega fastprompter** Nuitka ei jälginud kataloogi `src/`. | Enne Nuitka käivitamist veenduge, et 'PYTHONPATH' sisaldaks parameetrit 'src/' (seda haldab automaatselt 'tools/build.py'). |
| **„GitHubi mandaati ei leitud”** avaldamise ajal | Giti mandaadiabimees pole aktiivne või kasutaja pole GitHubisse sisse logitud. | Käivitage käsk „git push” üks kord käsitsi, et salvestada märk Windowsi mandaadihaldurisse. |
| **Suur EXE-i suurus (>60 MB)** | Süsteemis PATH ei leitud UPX-i binaarfaili. | Installige UPX saidilt https://upx.github.io/ ja lisage süsteemi PATH-i asukoht "upx.exe". |
| **Uuesti baaskonflikt faili „deploy.cmd” ajal** | Kaughoidla, mida muudeti otse GitHubis. | "deploy.ps1" katkestab automaatselt ümberbaasi ja sooritab kohaliku masina oleku säilitamiseks tõuke "--force-with-lease". |