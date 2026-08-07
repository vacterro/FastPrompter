# ASP Board

> NOTE 25.07: a saitranslate INIT wiped this board (35KB -> 236B) plus LOG and
> STATE at 24.07 23:50. `.saipen/` is gitignored, so there was no git fallback.
> LOG was restored from the newest backup + splice. This board was NOT fully
> rebuilt (user call — too token-expensive); the pre-wipe backlog survives only
> in `recovery/20260725T004633Z-WIPED-BOARD.md` and
> `recovery/20260721T213816Z-BOARD.md`. Pull tickets back from there on demand.

## DOING

_(empty)_
## TODO

- [ ] T-764 (P3, clean-orphan, needs confirm) `src/fastprompter/_extract.txt` is a gitignored stray extraction artifact: zero references, untracked, not mechanically regenerable -- the proof-of-recovery gate forbids deleting it outright, so it is ticketed for a human yes/no. | verify: file gone or explicitly kept with a reason | needs: none
## BLOCKED

_(empty)_
## DONE

### v0.8.29 — 07.08.26 Sound icons back in the theme family

- [x] T-766 (fix, user-reported) DONE 07.08.26 21:44 -- v0.8.28 rainbow icons reverted to the theme colour; distinction now by glyph shape (13 new pictograms split the confusable pairs); regression test pins hues to the theme family. | verify: test_sound_icons_stay_in_the_theme_family green; sound tests green; ruff clean | owner: opencode

### v0.8.28 — 07.08.26 Sound Settings per-event icons

- [x] T-765 (feat, user-asked) DONE 07.08.26 21:39 -- every sound event gets its own individually-tinted icon. _event_color walks a golden-angle hue rotation from the theme's base colour, giving all 56 events distinct hues so no two rows look alike even when they share a glyph shape. | verify: 56 events -> 56 distinct hues; dialog opens; sound smoke green; ruff clean | owner: opencode

### dd all — 07.08.26 plan wave (T-761, T-762, T-763)

- [x] T-761 (P2, dead code, flagged since T-751) DONE 07.08.26 19:43 -- the write-only focus-lock apparatus (ignore_focus_loss, _focus_lock_count, _increment/_decrement_focus_lock, 110 refs across 9 files) fully removed: helpers + init deleted, ~30 call sites dropped, file_container._modal_guard gone with its callers, refresh() unwrapped, tests updated to the new invariants. | verify: rg on the four names in src = ZERO; unit 951 pass + 1 known pre-existing winsound; 112 targeted smoke pass; ruff clean | owner: opencode
- [x] T-762 (P3, conformance) DONE 07.08.26 19:56 -- subSaipen STATE files repaired: transition_from added, next_action in legal WAIT:/RUN: form, TEMPLATE placeholder updated stamped. | verify: validator subSaipen STATE shape PASS (4 checked) | owner: opencode
- [x] T-763 (P3, conformance) DONE 07.08.26 19:56 -- saiwiki/LOG.md mixed UTF-8+UTF-16 encoding repaired to one clean UTF-8 file. | verify: validator append targets PASS (18 checked), zero null bytes | owner: opencode
