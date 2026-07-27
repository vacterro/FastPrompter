# FastPrompter Keyboard Shortcuts & Cheatsheet

## Overview
FastPrompter is built for speed and 100% keyboard-driven operation. All major actions—from summoning the window to line formatting, queue management, silo navigation, and macro pasting—have dedicated keyboard shortcuts.

---

## Quick Reference Table

| Kategooria | Kiirklahv | Tegevus | Ulatus / kontekst |
|---|---|---|---|
| **Globaalne** | **Alt+X** | Kutsu/peida FastPrompteri aken | Üle kogu süsteemi (mis tahes rakendus) |
| **Vaatleja** | **Alt+C** | Lülitab sisestamise jälgija/vaate olekut | Peaaken |
| **Vaatleja** | **Alt+Tõstuklahv+C** | Ava järjekorra põhidialoog | Peaaken |
| **Aken** | **Ctrl+D** | Lülita Zen Focus Mode (peidab paneelid/kroom) | Peaaken |
| **Aken** | **Ctrl+Q** | Tsükli klõpsamise asend (ülevalt-vasak, ülevalt-parem, keskel, kursor) | Peaaken |
| **Aken** | **Alt+S** | Lülitage akna lukustus sisse (tihvti suurus ja asend) | Peaaken |
| **Aken** | **Alt+E** | Alati üleval kinnitatud olek | Peaaken |
| **Aken** | **Alt+D** | Külgriba nähtavuse lülitamine | Peaaken |
| **Aken** | **Alt+A** | Klõpsamisel peitmise käitumise sisse- ja väljalülitamine | Peaaken |
| **Aken** | **Alt+`** | Avage Mini seadete ülekate | Peaaken |
| **Aken** | **Ctrl+Alt+Shift+Q** | Erakorraline jõud FastPrompterist väljumine | Süsteemne |
| **Navigeerimine** | **Ctrl+1** .. **Ctrl+0** | Hüppa otse silo 1 kuni 10 | Taotlus |
| **Navigeerimine** | **Alt+Üles** / **Alt+Alla** | Kõndige edasi/tagasi läbi aktiivsete silode | Taotlus |
| **Navigeerimine** | **Ctrl+N** | Loo uus tühi silo | Taotlus |
| **Navigeerimine** | **Ctrl+F** | Avage Otsi otsinguriba | Toimetaja |
| **Navigeerimine** | **Ctrl+H** | Avage Asenda otsingu- ja asendusriba | Toimetaja |
| **Navigeerimine** | **Ctrl+Shift+S** | Ekspordi aktiivne silo tekst faili | Taotlus |
| **Vormindamine** | **Ctrl+E** | Vorminda rida H1 päisena koos ajatempliga | Toimetaja |
| **Vormindamine** | **Ctrl+Tagasi** | Lülitage märkeruut `- [ ]` / `- [x]` praegusel real | Toimetaja |
| **Vormindamine** | **Ctrl+W** | Sisesta vahedega `---` horisontaalne eraldusjoon | Toimetaja |
| **Vormindamine** | **Alt+W** | Sisestage eraldusjoon "---" ja uus täpp "-" | Toimetaja |
| **Vormindamine** | **Ctrl+B** | Lülita **paks** tekst (`**tekst**`) | Toimetaja |
| **Vormindamine** | **Ctrl+I** | Lülitab *kaldkirjas* teksti (`*tekst*`) | Toimetaja |
| **Vormindamine** | **Ctrl+U** | Lülitab <u>Allakriipsutatud</u> teksti (`<u>tekst</u>`) | Toimetaja |
| **Vormindamine** | **Ctrl+T** | Lülita ~~Läbikriipsutatud~~ tekst (`~~tekst~~`) | Toimetaja |
| **Vormindamine** | **Ctrl+Shift+Q** | Lülita Blockquote plokk (`> text`) | Toimetaja |
| **Vormindamine** | **Alt+Z** | Reanumbrite sisse- ja väljalülitamine redaktori rennis | Toimetaja |
| **Vormindamine** | **Alt+Tagasilükke** | Kustuta eelmine sõna | Toimetaja |
| **Vormindamine** | **Ctrl+Z** | Nutikas tagasivõtmise redigeerimistoiming | Toimetaja |
| **Lõiked** | **F1** .. **F10** | Kleepige väljavõte 1 kuni 10 redaktorisse | Taotlus |
| **Lõiked** | **Ctrl+Shift+1** .. **9** | Kleebi väljavõte 1 kuni 9 (alternatiiv) | Taotlus |
| **Lõiked** | **Ctrl+S** | Ava Snippet Manager / Salvesta aktiivne koodilõik | Taotlus |
| **Manused** | **F2** | Nimeta valitud manusfail ümber | Failikonteinerite paneel |
| **Manused** | **Kustuta** | Kustutage valitud manusefail prügikasti | Failikonteinerite paneel |
| **Üldine** | **Esc** | Peida FastPrompteri aken / sulge aktiivne ülekate | Süsteem / Kohalik |

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
*FastPrompter Wiki – ehitatud [SAIPEN-protokolli] (SAIPEN-protokolli) abil | [GitHubi hoidla](https://github.com/vacterro/FastPrompter)*