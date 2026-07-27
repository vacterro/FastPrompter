# FastPrompter Build, Packaging & Release Deployment Guide

## Overview
FastPrompter is delivered as a single-file, zero-installer portable Windows executable (`FastPrompter.exe`). It requires no admin rights, no pre-installed Python interpreter, and no registry changes. All application state is stored locally in the `data/` directory adjacent to the binary.

---

## Prerequisites & Build Environment

To compile and publish FastPrompter, the following tools are required:

- **Python**: Version 3.11 or higher.
- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`.
- **Compiler**: [`Nuitka`](https://nuitka.net/) (version >= 4.1.2).
- **C Compiler**: C64/MSVC or MinGW64 (Nuitka automatically downloads C compiler if needed).
- **Compressor (Optional)**: [`UPX`](https://upx.github.io/) executable in `PATH` for 50–60% binary size reduction.
- **Git**: Git for Windows with configured GitHub credentials.

---

## 1. Nuitka Compilation Pipeline (`tools/build.py`)

The standalone executable is compiled using Nuitka via `tools/build.py`.

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

The `tools/release.py` script automates tag creation and binary distribution on GitHub Releases.

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

For quick operator deployment, FastPrompter includes three one-click scripts in the root directory:

### A. `deploy.cmd` / `deploy.ps1` (Codebase Sync)
Double-click `deploy.cmd` to commit and push all project changes to GitHub.

- **PowerShell Script (`deploy.ps1`)**:
  1. Stages all changed files (`git add -A`).
  2. Creates timestamped commit `deploy: YYYY-MM-DD HH:mm` if uncommitted changes exist.
  3. Pulls remote changes using `git pull --rebase --autostash origin main`.
  4. Resolves conflicts by forcing local state to win (`git push --force-with-lease origin main` if rebase fails).
  5. Pushes updated main branch to `origin main`.

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

| Issue | Root Cause | Solution |
|---|---|---|
| **`ImportError: No module named fastprompter`** in built EXE | Nuitka did not trace `src/` directory. | Ensure `PYTHONPATH` includes `src/` before running Nuitka (handled automatically by `tools/build.py`). |
| **`No GitHub credential found`** during release | Git credential helper not active or user not logged into GitHub. | Run `git push` once manually to store token in Windows Credential Manager. |
| **Large EXE Size (>60MB)** | UPX binary was not found in system PATH. | Install UPX from `https://upx.github.io/` and add `upx.exe` location to system PATH. |
| **Rebase conflict during `deploy.cmd`** | Remote repository edited directly on GitHub. | `deploy.ps1` automatically aborts rebase and performs `--force-with-lease` push to preserve local machine state. |
