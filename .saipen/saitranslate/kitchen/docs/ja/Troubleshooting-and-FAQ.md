# FastPrompter トラブルシューティング & FAQ

## 1. GUI / Qt の問題

### アプリが起動しない / 空白ウィンドウ

**原因:**
- 古い IPC ロック — 前のインスタンスがソケットを開いたままクラッシュ
- オフスクリーンのウィンドウ座標 — ウィンドウが保存された場所のモニターが切断された
- 高 DPI / スケーリングのアーティファクト

**修正:**
- `%TEMP%\fastprompter_ipc.token` または `%TEMP%\fastprompter.lock` を削除
- Ctrl+Q を 2 回押して画面中央にスナップを循環
- `--reset-pos` フラグで起動
- UI スケールを調整: 設定または Ctrl+Plus/Minus

### キリル文字 / 非 QWERTY ホットキーが動作しない

レイアウト非依存の VK ディスパッチがこれを処理。それでも失敗する場合:
1. 設定を開く (Alt+`)
2. 物理キー検出を使用して失敗するホットキーを再バインド
3. Windows セキュリティで pynput グローバルフックに権限があることを確認

## 2. クラッシュログ

| ファイル | パス | 目的 |
|---|---|---|
| アプリログ | `%TEMP%\fastprompter.log` | ローテーション式、最大 1MB、バックアップ 2 つ |
| クラッシュログ | `%TEMP%\fastprompter_crash.log` | sys.excepthook トレースバック |
| テストログ | `%TEMP%\fastprompter-tests.log` | Pytest セッションログ |

表示:
```
powershell:
Get-Content "$env:TEMP\fastprompter_crash.log" -Tail 50

cmd:
type %TEMP%\fastprompter_crash.log
```

問題を報告するときは両方のログを添付。

## 3. プロセス整理

**症状:** Alt+X が何もしない。2 回目の起動で「別のインスタンスが実行中」と表示。

**修正:**
```
cmd:
taskkill /F /IM FastPrompter.exe
taskkill /F /IM pythonw.exe

powershell:
Stop-Process -Name FastPrompter -Force
Stop-Process -Name pythonw -Force
```

## 4. DB ロック / 破損

DB ファイル: `data/local_data_v15.db` (+wal、+shm)

### 「database is locked」
1. すべての FastPrompter プロセスを強制終了 (§3 参照)
2. data/ フォルダの権限を確認 (書き込み可能である必要がある)
3. -wal と -shm ファイルを削除 (SQLite が .db から再構築)

### 「database disk image is malformed」
1. **自動バックアップ:** `.db.bak` を `.db` にリネーム
2. **Markdown ミラー:** `~/Documents/.fastprompter/` から復元 (フラット .md ファイル)
3. **SQLite CLI 修復:**
```
sqlite3 local_data_v15.db ".recover" > dump.sql
sqlite3 repaired.db < dump.sql
copy repaired.db local_data_v15.db
```

## 5. ホットキー競合

**症状:** 「グローバルホットキー Alt+X のバインドに失敗」

**原因:** 別のアプリが同じホットキーを登録している (GeForce Experience、PowerToys、Discord、AutoHotkey など)

**修正:**
- 設定で FastPrompter の召喚ホットキーを変更 (Alt+`)
- または競合するアプリを再バインド
- 代替として Alt+Z、Ctrl+Alt+P、F12 を試す

## 6. FAQ

### Q1: データはクラウドに保存される?
**いいえ。** 100% ローカルオフライン。テレメトリゼロ、リモートコールゼロ。

### Q2: バックアップ方法は?
`data/` フォルダをコピー。または `~/Documents/.fastprompter/` をコピー。またはバックアップダイアログを使用。

### Q3: USB からポータブルで使える?
**はい。** `FastPrompter.exe` + `data/` フォルダを任意のドライブに一緒に置く。レジストリなし、AppData なし。

### Q4: ファクトリーリセットは?
`data/local_data_v15.db` を削除。次回起動時にアプリがスキーマを新規作成。

### Q5: 実行に Python が必要?
**いいえ。** Nuitka コンパイル済みのスタンドアロン EXE。Python ランタイム不要。
