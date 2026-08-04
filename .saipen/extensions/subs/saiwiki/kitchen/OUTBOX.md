# OUTBOX — saiwiki prepare handoff

- **status**: ready
- **producer**: saiwiki
- **source_head**: `bac28b6`... (HEAD, post-v0.8.8) — defaults freeze wave
- **generated**: 2026-08-04 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD. 11 pages clean; **5 pages carry drift** (this wave moved the frozen `default_profile.py` defaults + one hotkey swap + 3 new core files):

| Page | Drift found | Fix |
|---|---|---|
| `Configuration.md` | default values stale vs `core/default_profile.py` (shipped defaults merged into `state.reset_data()` → or): font_size 11→18, button_scale 1.0→0.5, theme `Default`→`Golden Default`, theme list (10 names), custom_cursors False→True, code_monospace True→False; key rename `hr_line`→`hr_visual_line` (True), `hide_markup`→`live_preview_conceal` (True), `silo_sync_mode`→`sync_mode`, `show_silo_ticks`→`silo_ticks_enabled`; `always_on_top` False; lock/always hotkeys SWAPPED; sound_enabled row added + sound_volume 5→1, sound_ui True; `language` 23→33; cursor_blink_ms system→1000; date_text_month True; silo_gap_height 6→12; window_presets_enabled True; timer_show_minutes True; hover_line_color `#0059ff` | defaults + key names corrected to `default_profile.py` (evidence: file lines) |
| `Module-Structure.md` | `default_profile.py` missing from core map; theme count "6 retro Win95" → 9 built-in (those.py); total `.py` 112→115 (core 16 + watcher 10 + i18n 38 + ui 44 + theme 1 + utils 4 + main/__init__ 2) | module map entry added; counts 115; themes line fixed (also in `ui.theme_mixin` row) |
| `Keyboard-Shortcuts-and-Cheatsheet.md` | `Alt+S`/`Alt+E` swap: profile has `lock_window_hotkey`=Alt+E, `always_on_top_hotkey`=Alt+S (default_profile.py) | rows + paragraph fixed (S→pin, E→lock) |
| `Core-API-and-Classes.md` | SoundManager method names stale (`play_ui_click`/`play_tick_sound`/`play_typewriter` → now `play(name)`/`play_click()`/`play_tick()`; volume scaling via `scale_wav_bytes`/`scaled_wav_path` added for winsound path) | SoundManager section rewritten |
| `Architecture-Overview.md` | theme count "6 retro Win95" → 9 built-in | line fixed |

## payload

Exact files to apply to `docs/wiki/` (all already corrected in this kitchen):

1. `Configuration.md`
2. `Module-Structure.md`
3. `Keyboard-Shortcuts-and-Cheatsheet.md`
4. `Architecture-Overview.md`
5. `Core-API-and-Classes.md`

Copy each over its `docs/wiki/` twin, commit docs-only, then optionally push via `sync_wiki.py --push`.

## verified

- Every default rechecked against `src/fastprompter/core/default_profile.py` at HEAD (223 lines, all shipping defaults).
- Theme list = `theme/themes.py` `THEMES` dict (Default, Golden Vintage, Golden Default, Vintage Dark, Vintage Classic, Dark 2 (OLED), Dracula, Nord, Solarized Dark) + Custom.
- Module counts from `git ls-tree HEAD`: core 16, watcher 10, i18n 38 (33 lex + 5 infra), ui 44, theme 1, utils 4, main.py + __init__.py → 115 total.
- SoundManager methods verified at HEAD `core/sound_manager.py` (`play`, `play_click`, `play_tick`, `_play_winsound`, `scale_wav_bytes`, `scaled_wav_path`).
- Remaining 11 pages (Home, UI-Components, User-Guide, Deployment, Troubleshooting, Plugin-Skill, Watcher-Engine, README, _Sidebar, _Footer, SAIPEN-Protocol) byte-clean against HEAD.
- Kitchen hashes == docs/wiki after mirror (md5).

## instructions

1. `git status` must show no concurrent edits to `docs/wiki/` before applying.
2. Copy 5 payload files from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` (plain copy, names unchanged).
3. Commit as `docs: wiki re-sync — defaults freeze (font 18, scale 0.5, Golden Default), Alt+S/E swap, 9 themes, 115 py` style, no version bump.
4. Optional: `sync_wiki.py --push` to push to GitHub wiki.

## history

- T-019 (03.08) reviewed — consumed at 42347fe/bac28b6. Superseded by this run's re-sync.