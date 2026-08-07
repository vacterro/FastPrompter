# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 07.08.26 -> docs/wiki, 3-file payload)
- **producer**: saiwiki
- **source_head**: `4f5ae12` (HEAD, v0.8.22, T-741/T-742 shipped)
- **generated**: 2026-08-07 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 4f5ae12. 13 pages byte-identical to the previous payload; **3 pages carry drift** from v0.8.21 and v0.8.22:

| Page | Drift found | Fix |
|---|---|---|
| `User-Guide.md` | Timer alarms pick from 412 shipped sounds (T-741); Generic hotkey event ships ON by default and Ctrl+A/C/V/X sound (T-742); Ctrl+Z single sound (v0.8.21) | Updated sections 15 (Timers & Pomodoro) and 23 (Sound & Hotkey Sounds) with new capabilities and default state. |
| `UI-Components.md` | Timer dialog sound picker expanded; Sound Settings generic hotkey default changed | Updated rows for Timer Dialog and Sound Settings. |
| `Core-API-and-Classes.md` | `SoundManager` gained `play_file` method | Added `play_file(file_name)` to methods list. |

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `User-Guide.md`
2. `UI-Components.md`
3. `Core-API-and-Classes.md`

Copy over their `docs/wiki/` twins, commit docs-only, no version bump.

## verified

- 13/16 kitchen pages byte-identical to docs/wiki. 3 pages differ.
- Features verified from v0.8.22 CHANGELOG and source `core/sound_manager.py`.

## instructions

1. Copy `User-Guide.md`, `UI-Components.md`, and `Core-API-and-Classes.md` from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` equivalents.
2. Commit docs-only, no version bump.

## history

- T-024 (06.08, a679f9c) — superseded by this run. Its 1-page payload already integrated.
