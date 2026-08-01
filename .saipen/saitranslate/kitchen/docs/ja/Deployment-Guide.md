# FastPrompter ビルド & リリースガイド

## 概要

単一ファイルのポータブル EXE (`FastPrompter.exe`)。インストーラー不要、管理者権限不要、Python ランタイム不要。すべての状態はバイナリの隣の `data/` に。

---

## 前提条件

- **Python** 3.11+
- **uv** (パッケージマネージャー) または pip
- **Nuitka** >= 4.1.2
- **C コンパイラ** — なければ Nuitka が自動ダウンロード
- **UPX** (任意、50-60% サイズ削減)
- **Git for Windows** + GitHub 認証情報

---

## 1. コンパイル (`tools/build.py`)

```bash
uv run python tools/build.py
```

### 手順
1. Nuitka >= 4.1.2 のインストールを確認 (なければ自動インストール)
2. PATH 内の UPX を検出 (あれば `--plugin-enable=upx` を追加)
3. クリーンなモジュールトレースのため `src/` を PYTHONPATH に注入
4. `FastPrompter.pyw` をコンパイル (GUI エントリ、コンソールなし)
5. 出力: `build/FastPrompter.exe`

### 主要フラグ
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

出力 EXE は UPX の有無で約 15〜28MB。

---

## 2. 公開 (`tools/release.py`)

```bash
uv run python tools/release.py [release_notes.md]
```

### 手順
1. `build/FastPrompter.exe` の存在を確認
2. `pyproject.toml` からバージョンを読む (タグ = `v<version>`)
3. Windows Credential Manager から GitHub トークンを取得 (`git credential fill`)
4. GitHub API でタグの存在を確認
   - なし → 新規リリース作成
   - あり → リリースノート更新
5. `build/FastPrompter.exe` をリリースアセットとしてアップロード (古いものは先に削除)

---

## 3. ワンクリックスクリプト

### deploy.cmd / deploy.ps1
すべてのプロジェクト変更をコミット + プッシュ:
- すべてステージ (`git add -A`)
- タイムスタンプ付きコミット (`deploy: YYYY-MM-DD HH:mm`)
- プルリベース (`git pull --rebase --autostash origin main`)
- 競合時はフォースプッシュ (`git push --force-with-lease origin main`)

### release.cmd
ビルド + 公開をワンクリックで:
```
uv run python tools\build.py || pause
uv run python tools\release.py %*
```

---

## トラブルシューティング

| 問題 | 原因 | 修正 |
|---|---|---|
| `ImportError: No module named fastprompter` | Nuitka が src/ をトレースしなかった | PYTHONPATH に src/ が含まれることを確認 (build.py が行う) |
| `No GitHub credential found` | Git トークンが Credential Manager にない | 一度手動で `git push` してトークンを保存 |
| 巨大な EXE (>60MB) | PATH に UPX がない | https://upx.github.io/ から UPX をインストール |
| デプロイ時のリベース競合 | GitHub 上でリモートが直接編集された | Force-with-lease プッシュ (deploy.ps1 が自動実行) |
