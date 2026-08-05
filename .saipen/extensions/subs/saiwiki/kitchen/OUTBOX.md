# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 05.08.26 by qqq -> docs/wiki 414e92a, pushed 77a6206..414e92a)
- **producer**: saiwiki
- **source_head**: `60e3c20` (HEAD, T-732/T-733/T-728) + uncommitted T-734..T-738 working tree (undo fix, hotkey sounds, toast click, header/grid theming, silo drag-out)
- **generated**: 2026-08-05 (qq / `saipen prepare saiwiki`, second run same day)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 60e3c20 + the uncommitted T-734..T-738 working tree. 13 pages byte-clean vs the T-022 payload (77a6206); **3 pages carry drift** from the wave landed after 12:20:

| Page | Drift found | Fix |
|---|---|---|
| `Module-Structure.md` | `core/silo_export.py` new with T-738 (drag silo OUT to Explorer); module counts stale (core 17 → 18, total 117 → 118) | module added to the tree + both counts corrected |
| `User-Guide.md` | §3 Silos lacked the drag-OUT-to-Explorer export (T-738); §15 Timers lacked the tabular Name/Time/Remaining list (T-733) and the clickable toast (T-736); no sound-and-hotkey-sounds section (T-735) | drag-OUT paragraph in §3, table + clickable-toast wording in §15, new §24 Sound & Hotkey Sounds, Backup renumbered §25 |
| `UI-Components.md` | Sound Settings dialog row lacked the T-735 hotkey events; Timer Dialog row lacked the tabular list (T-733); no header/grid theming note (T-737) | both dialog rows extended; header_view_qss bullet added under Window Components |

Source invariants re-verified at HEAD + working tree: module counts core 18 / ui 45 / total 118 `.py` (T-738 added `core/silo_export.py` only); timer headers `Name/Time/Remaining` at `timer_dialog.py:82-83` (T-733); toast `mousePressEvent` dismiss + `_live_toasts` + `availableGeometry` clamp at `timer_toast.py` (T-736); `_DEFAULT_OFF = {"hotkey"}`, undo/redo blip pair, `select_all`/`settings`/`help` events in `core/sound_manager.py` (T-735); `header_view_qss()` in `theme/themes.py:70` injected once in `theme_mixin.py:135` (T-737); `write_drag_file`/`drag_filename` in `core/silo_export.py`, wired at `ui/snippet_panel.py:1001-1007` (T-738).

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `Module-Structure.md`
2. `User-Guide.md`
3. `UI-Components.md`

Copy each over its `docs/wiki/` twin, commit docs-only, then optionally push via `sync_wiki.py --push`.

## verified

- Every claim cross-checked against the live source: `silo_export.py` exists with `drag_filename`/`write_drag_file`; `timer_dialog.py` uses `QTreeWidget` + `setHeaderLabels([Name, Time, Remaining])`; `timer_toast.py` has the dismiss + clamp logic; `sound_manager.py` has `_DEFAULT_OFF`/`EVENT_LABELS`/`HOTKEY_SOUND_EVENTS`; `themes.py:70` defines `header_view_qss`.
- `git status --short docs/wiki/` clean — no concurrent edits to the target.
- T-734..T-738 are **uncommitted** in the working tree (main.py, theme/themes.py, theme_mixin.py, timer_dialog.py, timer_toast.py, snippet_panel.py, core/silo_export.py + tests) — the rows describe them; no conflict, they ship with the next build.

## instructions

1. `git status` must show no concurrent edits to `docs/wiki/` before applying (currently clean).
2. Copy the 3 payload files from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` (plain copy, names unchanged).
3. Commit as `docs: wiki re-sync — silo export, timer table, hotkey sounds, toast click, header theming` style, no version bump.
4. Optional: `sync_wiki.py --push` to push to GitHub wiki.
5. T-734..T-738 uncommitted — the rows describe them; they ship with the next build.

## history

- T-022 (05.08, 77a6206) — superseded by this run. Its 3-page payload (v0.8.14–17 + T-728) was already integrated; this is the delta on top (T-732/T-733 committed + T-734..T-738 working tree).
- T-021 (04.08, 8199480) — superseded by T-022.
