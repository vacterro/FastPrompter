# OUTBOX — saiwiki prepare handoff

- **status**: reviewed (collected 06.08.26 by sc circuit stage 6 -> docs/wiki, committed 1-file payload Configuration.md)
- **producer**: saiwiki
- **source_head**: `a679f9c` (HEAD, v0.8.20, T-739/T-740 shipped)
- **generated**: 2026-08-06 (qq / `saipen prepare saiwiki`, sc circuit stage 6)

## coverage

All 16 maintained wiki pages (`docs/wiki/*.md`) re-verified against source at HEAD a679f9c. 15 pages byte-identical to the previous payload (414e92a); **1 page carries drift** from v0.8.20:

| Page | Drift found | Fix |
|---|---|---|
| `Configuration.md` | `bold_hash_titles` setting (footer checkbox "Bold # Titles") absent from the Settings Keys table — the key exists at main.py:3512/7753-7754, ships default True, and T-739 just fixed its snippet half, so it is a real user-facing key with zero documentation | row added under Behavior: `bold_hash_titles` bool True — Bold the sidebar title of silos and snippets whose text starts with `#` (T-739) |

No drift from T-740 (hover-line follow) — `hover_line_color` already documented (Configuration.md:71) and the fix changed behaviour, not a setting key. No drift from T-295 (test-only).

Source invariants re-verified at HEAD: `bold_hash_titles` checkbox `cb_bold_titles` (main.py:3508-3512), read at main.py:7753-7754 (snippets) + 7840/8413 (silos/children).

## payload

Exact files to apply to `docs/wiki/` (already corrected in this kitchen):

1. `Configuration.md` (+1 settings row)

Copy over its `docs/wiki/` twin, commit docs-only, no version bump.

## verified

- 15/16 kitchen pages byte-identical to docs/wiki, only Configuration.md differs.
- `bold_hash_titles` present in source (main.py:3508-3512, 7753-7754) and in the defaults; the wiki table previously omitted it while documenting sibling footer toggles.
- `git status --short docs/wiki/` clean pre-apply.

## instructions

1. Copy `Configuration.md` from `.saipen/extensions/subs/saiwiki/kitchen/` over `docs/wiki/Configuration.md` (done 06.08.26 19:00).
2. Translated mirrors updated in the same pass: `.saipen/saitranslate/kitchen/docs/{ru,est,ja,de}/Configuration.md` each gained the translated row (RU/EST hand, JA/DE hand by Core in-role per the T-688 fallback precedent).
3. Commit docs-only, no version bump.

## history

- T-023 (05.08, 414e92a) — superseded by this run. Its 3-page payload (T-732..T-738 surfaces) already integrated; this is the delta on top (T-739).
