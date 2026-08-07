# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 07.08.26 22:26 -> docs/wiki, 2-file payload)
- **producer**: saiwiki
- **source_head**: `21d4ad2` (HEAD after qq prepare; source tree byte-identical to 8ad58aa, the qq base)
- **source_tree_fingerprint**: `ba571ad5241f4dbbba152f74421d6cf72d60fb8a` (HEAD tree)
- **role_revision**: `sha256:54a42475a124ab0f27e83d600a284a9cc54d9668029c4828cfc48512b031df13` (saiwiki charter)
- **generated**: 2026-08-08 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 8ad58aa. 14 pages are byte-identical to the previous payload; **2 pages carry drift from v0.8.28..v0.8.30**:

| Page | Drift found | Fix |
|---|---|---|
| `User-Guide.md` | §23 Sound & Hotkey Sounds described the v0.8.26 pictograms but not the v0.8.28..30 churn: v0.8.28 gave every event its own rainbow hue (golden-angle rotation), v0.8.29 reverted it — icons are the theme's own colour, distinction now by GLYPH SHAPE (13 new pictograms split the confusable pairs), v0.8.30 made zebra rows never white (theme table sheet sets alternate-background-color blended from table bg toward theme text colour) | Updated the v0.8.26 pictogram sentence to the v0.8.28..30 state |
| `UI-Components.md` | Sound Settings dialog row said "painted pictogram + zebra-striped, no grid" without the v0.8.28..30 details; Header/grid theming (T-737) bullet lacked the v0.8.30 alternate-background-color addition | Updated the Sound Settings row + extended the T-737 bullet |

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `User-Guide.md`
2. `UI-Components.md`

## verified

- `docs/wiki/` pages diffed against these kitchen copies: only the 2 above differ, each differing for a documented v0.8.28..30 source change (T-765 rainbow experiment -> T-766 revert to theme family + glyph-shape distinction -> T-767 alternate-background-color in the shared theme table sheet).
- Module-Structure re-counted: still 118 `.py` files — no update needed.
- Watcher-Engine-Architecture and Configuration re-checked: no v0.8.28..30 source change touches them — no update.
- No source file was touched by this prepare (kitchen-only edits).

## instructions

1. Copy the 2 payload files over `docs/wiki/` (preserving names).
2. Commit + push the wiki sync via the normal collect + SHIP gates (`qqq`).
3. Optionally re-run the GitHub-wiki mirror push with `kitchen/sync_wiki.py` after the collect lands.
