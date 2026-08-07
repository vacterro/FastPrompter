# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 07.08.26 21:09 -> docs/wiki, 4-file payload)
- **producer**: saiwiki
- **source_head**: `90b2ac3` (HEAD after qq prepare; source tree byte-identical to 501acd0, the qq base)
- **source_tree_fingerprint**: `393e89e9fe57ac7f567a75efa89229df331dfbd8` (HEAD tree)
- **role_revision**: saiwiki role per `extensions/subs/PROTOCOL.md` § 6 (no standalone charter file; re-record exact charter revision at next adopt — validator WARN sub-role-revision-legacy)
- **generated**: 2026-08-07 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 90b2ac3. 12 pages are byte-identical to the previous payload; **4 pages carry drift from v0.8.23..v0.8.27**:

| Page | Drift found | Fix |
|---|---|---|
| `User-Guide.md` | v0.8.26 Sound Settings now paints a pictogram per event and reads as a zebra table; v0.8.24 removed Hide on Click-Out (setting + Alt+A + hide-on-focus-loss machinery) | Updated § 23 (Sound & Hotkey Sounds) + added a "Hide on Click-Out is gone" note |
| `UI-Components.md` | Sound Settings dialog gained painted pictograms + zebra/gridless table (v0.8.26) | Updated the `Sound Settings` dialog row |
| `Watcher-Engine-Architecture.md` | v0.8.25: `[limits]` reach the engine at arm, blocker_pattern is CDP-only (visible text), CDP arms without an HWND, queue detach/revive + cross-silo-snapshot state machine | Added "Safety Guards — v0.8.25 notes" section |
| `Configuration.md` | v0.8.24 removed `close_on_focus_loss`; v0.8.25 watcher `[limits]` applied + CDP-only blocker | Added removal note + watcher limits note |

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `User-Guide.md`
2. `UI-Components.md`
3. `Watcher-Engine-Architecture.md`
4. `Configuration.md`

## verified

- `docs/wiki/` pages diffed against these kitchen copies: only the 4 above differ, each differing for a documented v0.8.23..27 source change.
- Module-Structure total re-counted: still 118 `.py` files — no update needed.
- No source file was touched by this prepare (kitchen-only edits).

## instructions

1. Copy the 4 payload files over `docs/wiki/` (preserving names).
2. Commit + push the wiki sync via the normal collect + SHIP gates (`qqq`).
3. Optionally re-run the GitHub-wiki mirror push with `kitchen/sync_wiki.py` after the collect lands.
