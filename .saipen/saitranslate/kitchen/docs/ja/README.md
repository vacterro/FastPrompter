# FastPrompter Wiki

FastPrompter — Windows 向けの超高速キーボード駆動スクラッチパッド兼プロンプトワークベンチ。Python 3.11+、PyQt6。SQLite WAL 永続化。Nuitka 製の自己完結型 EXE。

> **Alt+X** でマウスカーソル位置に 100 スロットのスクラッチパッドを召喚。インストールゼロ、クラウドゼロ、テレメトリゼロ。すべての状態はローカル DB に即時永続化。

---

## 技術ドキュメント目次

### コアアーキテクチャ
- **[アーキテクチャ概要](Architecture-Overview)** — システム設計、IPC シングルインスタンス、SQLite WAL、状態同期、サブシステム
- **[モジュール構成](Module-Structure)** — `src/fastprompter/` ツリー、ファイル役割、core/ui/utils/watcher マップ
- **[コア API とクラス](Core-API-and-Classes)** — FastPrompterState、HotkeyManager、IPCServer、SoundManager、PomodoroEngine、UI ウィジェット
- **[Watcher エンジン](Watcher-Engine-Architecture)** — CDP アタッチ、Win32 フック、キュー注入、状態機械、レート制限

### インターフェースとデータ
- **[設定](Configuration)** — DB スキーマ (local_data_v15.db)、設定キー、カスタムテーマエンジン、バックアップミラー
- **[UI コンポーネント](UI-Components)** — レイアウト図、パネル内訳（エディタ、サイロ、キュー、ファイル、かんばん、テーブル）
- **[キーボードショートカット](Keyboard-Shortcuts-and-Cheatsheet)** — 完全リファレンス：グローバル、ウィンドウ、書式、watcher、サイロ、スニペット

### ガイドと拡張
- **[ユーザーガイド](User-Guide)** — ワークフロー、サイロ管理、スニペットマクロ、ファイルコンテナ、禅モード、Pomodoro タイマー、マークアップ非表示、かんばん/テーブル
- **[トラブルシューティングと FAQ](Troubleshooting-and-FAQ)** — クラッシュログ (%TEMP%\fastprompter_crash.log)、プロセス整理、DB 修復、ホットキー競合
- **[プラグインとスキル開発](Plugin-and-Skill-Development)** — カスタムスキル (skills.py)、SAIPEN サブエージェント、カスタムテーマ、カーソルテーマ

### 自動化とプロトコル
- **[SAIPEN プロトコル](SAIPEN-Protocol)** — v7 プロトコル仕様：状態機械ループ、イベントログ、subSaipen 読み取り専用アーキテクチャ、OUTBOX ハンドオフ
- **[デプロイガイド](Deployment-Guide)** — Nuitka コンパイル (tools/build.py)、GitHub リリース (tools/release.py)、ワンクリックスクリプト

---

## プロジェクト情報とリンク
- **リポジトリ**: [vacterro/FastPrompter](https://github.com/vacterro/FastPrompter)
- **技術スタック**: Python 3.11+、PyQt6、SQLite (WAL モード)、Nuitka 4.1+、pynput
- **ライセンス**: MIT

---

*FastPrompter Wiki — [SAIPEN プロトコル](SAIPEN-Protocol) で構築 | [GitHub リポジトリ](https://github.com/vacterro/FastPrompter)*
