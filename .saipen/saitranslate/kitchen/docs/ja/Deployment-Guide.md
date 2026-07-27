# FastPrompter Build, Packaging & Release Deployment Guide

## Overview
FastPrompter is delivered as a single-file, zero-installer portable Windows executable (`FastPrompter.exe`). It requires no admin rights, no pre-installed Python interpreter, and no registry changes. All application state is stored locally in the `data/` directory adjacent to the binary.

---

## Prerequisites & Build Environment

FastPrompter をコンパイルして公開するには、次のツールが必要です。

- **Python**: バージョン 3.11 以降。
- **パッケージ マネージャー**: [`uv`](https://github.com/astral-sh/uv) (推奨) または標準の `pip`。
- **コンパイラ**: [`Nuitka`](https://nuitka.net/) (バージョン >= 4.1.2)。
- **C コンパイラー**: C64/MSVC または MinGW64 (Nuitka は必要に応じて C コンパイラーを自動的にダウンロードします)。
- **コンプレッサー (オプション)**: `PATH` で実行可能な [`UPX`](https://upx.github.io/) バイナリ サイズを 50 ～ 60% 削減します。
- **Git**: GitHub 認証情報が設定された Windows 用 Git。

---

## 1. Nuitka Compilation Pipeline (`tools/build.py`)

スタンドアロンの実行可能ファイルは、`tools/build.py` 経由で Nuitka を使用してコンパイルされます。

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

「tools/release.py」スクリプトは、タグの作成と GitHub リリースでのバイナリ配布を自動化します。

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

オペレーターを迅速に導入できるように、FastPrompter にはルート ディレクトリに 3 つのワンクリック スクリプトが含まれています。

### A. `deploy.cmd` / `deploy.ps1` (Codebase Sync)
Double-click `deploy.cmd` to commit and push all project changes to GitHub.

- **PowerShell スクリプト (`deploy.ps1`)**:
  1. 変更されたすべてのファイルをステージングします (「git add -A」)。
  2. コミットされていない変更が存在する場合は、タイムスタンプ付きのコミット「deploy: YYYY-MM-DD HH:mm」を作成します。
  3. 「git pull --rebase --autostashorigin main」を使用してリモートの変更をプルします。
  4. ローカル状態を強制的に優先させることで競合を解決します (リベースが失敗した場合は「git Push --force-with-lease Origin main」)。
  5. 更新されたメイン ブランチを「origin main」にプッシュします。

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

|問題 |根本原因 |ソリューション |
|---|---|---|
| **`インポートエラー: ビルドされた EXE に fastprompter という名前のモジュールがありません`** | Nuitka は `src/` ディレクトリをトレースしませんでした。 | Nuitka を実行する前に、`PYTHONPATH` に `src/` が含まれていることを確認してください (`tools/build.py` によって自動的に処理されます)。 |
| **「GitHub 認証情報が見つかりません」** リリース中 | Git 資格情報ヘルパーがアクティブでないか、ユーザーが GitHub にログインしていません。 | 「git Push」を手動で 1 回実行して、トークンを Windows Credential Manager に保存します。 |
| **大きなEXEサイズ(>60MB)** | UPX バイナリがシステム PATH に見つかりませんでした。 | UPX を「https://upx.github.io/」からインストールし、「upx.exe」の場所をシステム PATH に追加します。 |
| **「deploy.cmd」中のリベースの競合** | GitHub 上で直接編集されたリモート リポジトリ。 | 「deploy.ps1」は自動的にリベースを中止し、「--force-with-lease」プッシュを実行してローカルマシンの状態を保存します。 |