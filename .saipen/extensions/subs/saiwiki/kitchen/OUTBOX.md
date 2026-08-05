# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 05.08.26 by qqq -> docs/wiki 77a6206, pushed 7ea7dbb..77a6206)
- **producer**: saiwiki
- **source_head**: `1e18883` (HEAD, post-v0.8.17 checkpoint) + uncommitted T-728 working tree (window_presets_capture_state — verified against the tree as it stands; the Configuration row notes T-728)
- **generated**: 2026-08-05 (qq / `saipen prepare saiwiki`)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD 1e18883 + the uncommitted T-728 window-presets working tree. 13 pages byte-clean vs the T-021 payload; **3 pages carry drift** from the v0.8.14 → v0.8.17 wave + T-728:

| Page | Drift found | Fix |
|---|---|---|
| `Configuration.md` | `window_presets_capture_state` (bool, default `True`) missing — new with T-728 (default_profile.py:220, uncommitted) | row added after `window_presets_enabled` |
| `User-Guide.md` | §15 Timers lacked the one-click quick presets (`in 10m` / `in 1h` / `tonight` 22:00 / `tomorrow` 09:00, T-726 shipped v0.8.17); §17 Window Snap lacked the full-state capture (theme/font/scale/toolbar/zen/sidebar, T-728) | quick-preset paragraph added in §15; full-state capture + geometry-only toggle paragraph added in §17 |
| `UI-Components.md` | dialog table: Timer Dialog row lacked the quick presets; Window Presets row lacked the full-state capture toggle | both rows extended |

Source invariants re-verified at HEAD: module counts still core 17 / ui 45 / total 117 `.py` (no new modules since T-021 — T-726/T-728 edited existing `timer_dialog.py`/`fancy_zones.py`/`window_presets_dialog.py`); hotkeys unchanged (Ctrl+Y/Ctrl+Shift+Z redo already present from T-021); quick-preset labels read from `src/fastprompter/ui/timer_dialog.py:148-166` (`in 10m`/`in 1h`/`tonight`/`tomorrow`, plain English by design — no new tr() keys, E-1254); `window_presets_capture_state` read from `default_profile.py:220` + `fancy_zones.py:95` + `window_presets_dialog.py:148`.

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `Configuration.md`
2. `User-Guide.md`
3. `UI-Components.md`

Copy each over its `docs/wiki/` twin, commit docs-only, then optionally push via `sync_wiki.py --push`.

## verified

- Every new setting default cross-checked against the live code: `default_profile.py:220` (`window_presets_capture_state` → `True`), `timer_dialog.py:148-166` (4 quick buttons), `fancy_zones.py:95` (`_captures_ui_state` reads the same key).
- T-726 quick-preset tooltips read from source: "10 minutes from now", "1 hour from now", "Tonight at 22:00", "Tomorrow at 09:00".
- T-728 is **uncommitted** in the working tree (default_profile.py, fancy_zones.py, window_presets_dialog.py, tests_smoke) — the payload documents it. If collect runs before T-728 ships, the rows describe a feature that ships with the next build; no conflict, but T-728 should land first for consistency.
- Remaining 13 pages (Home, Architecture, Module-Structure, Core-API, Keyboard, Deployment, Troubleshooting, Plugin-Skill, Watcher-Engine, README, _Sidebar, _Footer, SAIPEN-Protocol) byte-clean against the T-021 payload + current source at HEAD.
- `git status --short docs/wiki/` clean — no concurrent edits to the target.

## instructions

1. `git status` must show no concurrent edits to `docs/wiki/` before applying (currently clean).
2. Copy the 3 payload files from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/` (plain copy, names unchanged).
3. Commit as `docs: wiki re-sync — timer quick presets, window preset full-state capture` style, no version bump.
4. Optional: `sync_wiki.py --push` to push to GitHub wiki.
5. T-728 uncommitted — the Configuration/User-Guide/UI-Components rows describe it; land T-728 first for consistency, or note it ships with the next build.

## history

- T-021 (04.08, 8199480) — superseded by this run. Its 6-page payload was already integrated at 67db8a8; the new sweep is a delta on top (3 pages, v0.8.14–17 + T-728).
