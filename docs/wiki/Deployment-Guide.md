# FastPrompter Build & Release Guide

## Overview

Single-file portable EXE (`FastPrompter.exe`). No installer, no admin rights, no Python runtime needed. All state in `data/` beside binary.

---

## Prerequisites

- **Python** 3.11+
- **uv** (package manager) or pip
- **Nuitka** >= 4.1.2
- **C compiler** — Nuitka auto-downloads if missing
- **UPX** (optional, 50-60% size reduction)
- **Git** for Windows with GitHub credentials

---

## 1. Compile (`tools/build.py`)

```bash
uv run python tools/build.py
```

### Steps
1. Verify Nuitka >= 4.1.2 installed (auto-installs if missing)
2. Detect UPX in PATH (adds `--plugin-enable=upx` if found)
3. Inject `src/` into PYTHONPATH for clean module trace
4. Compile `FastPrompter.pyw` (GUI entry, no console)
5. Output: `build/FastPrompter.exe`

### Key flags
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

Output EXE ~15-28MB depending on UPX.

---

## 2. Publish (`tools/release.py`)

```bash
uv run python tools/release.py [release_notes.md]
```

### Steps
1. Verify `build/FastPrompter.exe` exists
2. Read version from `pyproject.toml` (tag = `v<version>`)
3. Extract GitHub token from Windows Credential Manager (`git credential fill`)
4. Check if tag exists via GitHub API
   - No → create new release
   - Yes → update release notes
5. Upload `build/FastPrompter.exe` as release asset (deletes old first)

---

## 3. One-Click Scripts

### deploy.cmd / deploy.ps1
Commit + push local changes:
- Stage tracked changes (`git add -u`)
- Untracked files are listed and only staged after an explicit yes (never auto-added)
- Timestamped commit (`deploy: YYYY-MM-DD HH:mm`)
- Pull rebase (`git pull --rebase --autostash origin main`)
- On conflict, ask for confirmation before force-pushing (`git push --force-with-lease` is used only after an explicit y)

### release.cmd
Build + publish in one click:
```
uv run python tools\build.py || pause
uv run python tools\release.py %*
```

---

## 4. Continuous Integration (CI)

`.github/workflows/ci.yml` runs on `windows-latest` for every push to
`main` and every pull request, executing the same gates a release must pass
(any failure blocks the job):

```powershell
uv sync --group dev
uv run python -m compileall -q src FastPrompter.pyw
uv run ruff check src/ tests/ tests_smoke/
uv run bandit -q -r src/fastprompter -ll
uv run pytest tests/ tests_smoke/ -q
```

`compileall` catches import-time syntax errors before the long test run;
Bandit gates at Medium severity and above (`-ll`), with each Medium+
finding carrying a scoped `# nosec` reason so a new real finding turns the
job red. Pre-commit runs ruff with fixes, YAML validation, merge-conflict
detection and a 500 KB added-file limit; it does not run the full CI matrix.

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `ImportError: No module named fastprompter` | Nuitka didn't trace src/ | Ensure PYTHONPATH includes src/ (build.py does this) |
| `No GitHub credential found` | Git token not in Credential Manager | Run `git push` once manually to store token |
| Large EXE (>60MB) | UPX not found in PATH | Install UPX from https://upx.github.io/ |
| Rebase conflict on deploy | Remote edited directly on GitHub | deploy.ps1 asks for confirmation before force-pushing (y/N); decline and resolve manually |
