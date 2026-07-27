# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions—from summoning the window to line formatting, queue management, silo navigation, and macro pasting—have dedicated keyboard shortcuts.

---

## Quick Reference Table

|カテゴリー |ホットキー |アクション |範囲/コンテキスト |
|---|---|---|---|
| **グローバル** | **Alt+X** | FastPrompter ウィンドウを呼び出す/非表示にする |システム全体 (任意のアプリ) |
| **ウォッチャー** | **Alt+C** | Typing Watcher / ステータスの表示を切り替え |メインウィンドウ |
| **ウォッチャー** | **Alt+Shift+C** |キューマスターダイアログを開く |メインウィンドウ |
| **ウィンドウ** | **Ctrl+D** | Zen フォーカス モードを切り替えます (パネル/クロムを非表示) |メインウィンドウ |
| **ウィンドウ** | **Ctrl+Q** |サイクル スナップ位置 (左上、右上、中央、カーソル) |メインウィンドウ |
| **ウィンドウ** | **Alt+S** |ウィンドウ ロックの切り替え (ピンのサイズと位置) |メインウィンドウ |
| **ウィンドウ** | **Alt+E** |常に表示される固定ステータスを切り替える |メインウィンドウ |
| **ウィンドウ** | **Alt+D** |サイドバーの表示/非表示を切り替える |メインウィンドウ |
| **ウィンドウ** | **Alt+A** |クリックアウト時の非表示動作を切り替える |メインウィンドウ |
| **ウィンドウ** | **Alt+`** |ミニ設定オーバーレイを開く |メインウィンドウ |
| **ウィンドウ** | **Ctrl+Alt+Shift+Q** |緊急強制終了 FastPrompter |システム全体 |
| **ナビゲーション** | **Ctrl+1** .. **Ctrl+0** |サイロ 1 ～ 10 に直接ジャンプ |アプリケーション |
| **ナビゲーション** | **Alt+上** / **Alt+下** |アクティブなサイロを前方または後方に歩きます |アプリケーション |
| **ナビゲーション** | **Ctrl+N** |新しい空のサイロを作成する |アプリケーション |
| **ナビゲーション** | **Ctrl+F** | [検索] 検索バーを開く |編集者 |
| **ナビゲーション** | **Ctrl+H** |置換検索と置換バーを開く |編集者 |
| **ナビゲーション** | **Ctrl+Shift+S** |アクティブなサイロ テキストをファイルにエクスポート |アプリケーション |
| **フォーマット** | **Ctrl+E** |行をタイムスタンプ付きの H1 ヘッダーとしてフォーマットする |編集者 |
| **フォーマット** | **Ctrl+Return** |現在の行の `- [ ]` / `- [x]` チェックボックスを切り替えます |編集者 |
| **フォーマット** | **Ctrl+W** |間隔をあけた「---」水平区切り線を挿入します。編集者 |
| **フォーマット** | **Alt+W** |区切り線「---」と新しい箇条書き「-」を挿入します。編集者 |
| **フォーマット** | **Ctrl+B** | **太字** テキスト (`**テキスト**`) を切り替え |編集者 |
| **フォーマット** | **Ctrl+I** | *斜体* テキスト (`*テキスト*`) を切り替えます |編集者 |
| **フォーマット** | **Ctrl+U** |テキストの <u>下線</u> を切り替えます (`<u>テキスト</u>`) |編集者 |
| **フォーマット** | **Ctrl+T** | ~~取り消し線~~テキストの切り替え (`~~テキスト~~`) |編集者 |
| **フォーマット** | **Ctrl+Shift+Q** | Blockquote ブロック (`> text`) を切り替えます |編集者 |
| **フォーマット** | **Alt+Z** |エディターのガターの行番号を切り替える |編集者 |
| **フォーマット** | **Alt+Backspace** |前の単語を削除 |編集者 |
| **フォーマット** | **Ctrl+Z** |スマートな元に戻す編集アクション |編集者 |
| **抜粋** | **F1** .. **F10** |スニペット 1 ～ 10 をエディターに貼り付けます。アプリケーション |
| **抜粋** | **Ctrl+Shift+1** .. **9** |スニペット 1 ～ 9 を貼り付けます (代替) |アプリケーション |
| **抜粋** | **Ctrl+S** |スニペット マネージャーを開く / アクティブなスニペットを保存する |アプリケーション |
| **添付ファイル** | **F2** |選択した添付ファイルの名前を変更 |ファイルコンテナパネル |
| **添付ファイル** | **削除** |選択した添付ファイルをゴミ箱に削除 |ファイルコンテナパネル |
| **一般** | **Esc** | FastPrompter ウィンドウを非表示にする / アクティブなオーバーレイを閉じる |システム / ローカル |

---

## Detailed Category Breakdown

### 1. Global & Window Management
- **Alt+X (Global Summon)**: Instantly brings FastPrompter to the foreground at your current mouse cursor coordinates. Pressing `Alt+X` again hides the window back to system tray.
- **Ctrl+D (Zen Mode)**: Hides sidebar, snippet bar, file container, status bar, and window framing for distraction-free writing.
- **Ctrl+Q (Corner Snap)**: Rotates window placement across predefined screen regions: Top-Left -> Top-Right -> Bottom-Left -> Bottom-Right -> Center -> Cursor Position.
- **Alt+S & Alt+E**: Lock window geometry to prevent accidental dragging (`Alt+S`) and pin window above all other desktop windows (`Alt+E`).

### 2. Typing Watcher & CDP Automation
- **Alt+C**: Toggles the automated typing watcher engine on/off. When armed, watches target application focus.
- **Alt+Shift+C**: Opens the Queue Master dialog to inspect, reorder, clear, or inject items into the active watcher drainage queue.

### 3. Markdown Formatting Shortcuts
- **Ctrl+E**: Converts current line into `# HH:MM - Heading`.
- **Ctrl+Return**: Converts regular text into `- [ ] text` or toggles `- [ ]` <-> `- [x]`.
- **Ctrl+W / Alt+W**: Inserts markdown dividers `---`. `Alt+W` automatically starts a new bullet point on the following line.
- **Ctrl+B / Ctrl+I / Ctrl+U / Ctrl+T**: Inline formatting for bold, italic, underline, and strikethrough.

### 4. Silo & Tab Navigation
- **Ctrl+1 .. Ctrl+0**: Instantly switches editor tab to Silo slot 1 through 10.
- **Alt+Up / Alt+Down**: Step through active silos sequentially without mouse interaction.
- **Ctrl+N**: Creates a new numbered scratch silo in the active project tab.

### 5. Snippet Macro Slots (`F1`-`F10`)
- **F1 .. F10**: Pastes pre-configured snippet templates directly at the editor cursor location.
- **Ctrl+Shift+1 .. 9**: Secondary hotkey binding for devices without dedicated function keys (e.g. compact keyboards).

---

## Physical Virtual Key (VK) Layout Fallbacks
FastPrompter features physical keyboard key mapping via `LayoutIndependentShortcuts`. Shortcuts continue to work reliably regardless of whether the active Windows keyboard layout is set to English (QWERTY), Russian (JCUKEN), German (QWERTZ), or French (AZERTY).

---
*FastPrompter Wiki — [SAIPEN プロトコル](SAIPEN-プロトコル) で構築 | [GitHub リポジトリ](https://github.com/vacterro/FastPrompter)*