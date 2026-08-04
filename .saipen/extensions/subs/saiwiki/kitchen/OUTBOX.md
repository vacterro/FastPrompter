# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 04.08.26 23:09 by qqq -> docs/wiki 67db8a8, pushed 8199480..67db8a8)
- **producer**: saiwiki
- **source_head**: `8199480` (HEAD, post-v0.8.13 checkpoint) — docs/wiki untouched since 205a18f (v0.8.9)
- **generated**: 2026-08-04 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 8199480 + the uncommitted T-715 SiloPresets working tree (verified against the tree as it stands; payload pages that touch T-715 note it). 10 pages byte-clean; **6 pages carry drift** from the v0.8.9 → v0.8.13 wave:

| Page | Drift found | Fix |
|---|---|---|
| `Configuration.md` | `image_paste_style` (pill/link/path, default `pill`), `silo_tabs_mode` (sidebar/tabs, default `sidebar`), `toolbar_position` (top/bottom, default `top`) missing — all shipped v0.8.11–13 (T-724, T-718, T-719), defaults read from main.py `.get()` at 3406/3424/3199 | three rows added under Behavior / Silo list |
| `Module-Structure.md` | `silo_presets.py` missing from core map (T-715, untracked); `sound_settings_dialog.py` missing from ui map (shipped since bac28b6); core 16→17, ui 44→45, total 115→117; `presets/` data dir (11 .md templates) absent | module rows + presets/ tree entry + counts corrected |
| `Keyboard-Shortcuts-and-Cheatsheet.md` | `Ctrl+Y` / `Ctrl+Shift+Z` smart redo missing (T-716 shipped it at v0.8.9; wiki table only had Ctrl+Z) | redo row added after Ctrl+Z |
| `User-Guide.md` | SiloPresets feature absent (middle-click NEW, "▤ Fill from preset", presets/ folder); image paste style setting absent; silo tabs mode + toolbar position sections absent | section 3 navigation + new section 4 (Silo Layout) + pasted-images note + Ctrl+Z/Y line; section numbers renumbered 4→23 |
| `UI-Components.md` | silo tabs mode + toolbar position absent from SnippetPanel layout; Sound Settings dialog missing from dialog table; image paste style absent | layout line + dialog row + collapsible-images note |
| `Core-API-and-Classes.md` | `SiloPresets` loader (`core/silo_presets.py`: `presets_dir`/`label_for`/`load_presets`) undocumented | new section added after HeaderFormatter |

Source invariants re-verified at HEAD: 9 built-in themes (Architecture + Module-Structure already carry it), Alt+E lock / Alt+S pin swap (already present from T-020 sweep), SoundManager API `play`/`play_click`/`play_tick` (already present), module counts from working tree (core 17, ui 45, watcher 10, i18n 38, theme 1, utils 4, main+init 2 → 117 .py).

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `Configuration.md`
2. `Module-Structure.md`
3. `Keyboard-Shortcuts-and-Cheatsheet.md`
4. `User-Guide.md`
5. `UI-Components.md`
6. `Core-API-and-Classes.md`

Copy each over its `docs/wiki/` twin, commit docs-only, then optionally push via `sync_wiki.py --push`.

## verified

- Every new setting default cross-checked against the live code: `main.py:3406` (`image_paste_style` → `pill`), `main.py:3424` (`silo_tabs_mode` → `sidebar`), `main.py:3199`/`6758` (`toolbar_position` → `top`).
- SiloPresets API read from `src/fastprompter/core/silo_presets.py` (3 functions); 11 template files listed in `src/fastprompter/presets/`; menu labels `▤ Fill from preset` + `show_new_silo_presets` found at main.py:8759/6737.
- Ctrl+Y binding verified: `_smart_redo` at main.py:6025, docstring "Ctrl+Y / Ctrl+Shift+Z".
- `sound_settings_dialog.py` present in `src/fastprompter/ui/` (shipped pre-bac28b6, was missing from the wiki map).
- Module counts from working tree `find src/fastprompter -name '*.py'` = 117 (core 17 incl. untracked silo_presets.py, ui 45, watcher 10, i18n 38, theme 1, utils 4, main+init 2).
- Remaining 10 pages (Home, Architecture, Deployment, Troubleshooting, Plugin-Skill, Watcher-Engine, README, _Sidebar, _Footer, SAIPEN-Protocol) byte-clean against source at HEAD.
- `git status --short docs/wiki/` clean — no concurrent edits to the target.

## instructions

1. `git status` must show no concurrent edits to `docs/wiki/` before applying (currently clean).
2. Copy the 6 payload files from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` (plain copy, names unchanged).
3. Commit as `docs: wiki re-sync — silo tabs, toolbar position, image paste style, SiloPresets, Ctrl+Y redo, module counts 117` style, no version bump.
4. Optional: `sync_wiki.py --push` to push to GitHub wiki.
5. T-715 is **uncommitted** in the working tree (silo_presets.py, presets/, tests) — the payload documents it. If collect runs before T-715 ships, the SiloPresets rows simply describe a feature that ships with the next build; no conflict, but the T-715 ticket should land first for consistency.

## history

- T-020 (04.08, bac28b6) — superseded by this run. Its 5-page payload was already integrated (wiki Configuration carries Golden Default/font 18/Alt+E at 205a18f); the new sweep extends it with the v0.8.9–13 wave.
