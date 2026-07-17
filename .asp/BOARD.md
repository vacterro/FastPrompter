# ASP Board

## Wave v0.6.0 — gaps from the 0.5.3 master list (17.07.26 review)

| ID | Status | Owner | Needs | Description |
|---|---|---|---|---|
| T-130 | TODO | - | - | Settings UI: rethink + compact whole panel (screen 044432_24bc2c90) |
| T-131 | DONE | claude-fable | - | Move ⚙ settings btn + 📁 files btn to sidebar right group (Archive/+/-/Search), organized |
| T-132 | TODO | - | - | Snippet Append/Top/Bot arrow buttons: Settings toggle, default OFF |
| T-133 | DONE | claude-fable | - | Visual separator for snippet +/- buttons (own group in the row) |
| T-134 | TODO | - | - | Folder Template editor (refs: V:\__SAVE_V\___CONTEXTMENU\_new_project.reg, NEW_PROJ.CMD) — build templated folder trees in container |
| T-135 | TODO | - | - | ALL in-app shortcuts bindable (Ctrl+E/W/D/Q/…) + tooltips show current binds |
| T-136 | TODO | - | - | Search deep reliability pass (beyond the ghost-filter fix) |
| T-137 | TODO | - | - | README + Help refresh (hierarchy, ticks, trash, zones, │ counters); dead-code sweep |
| T-138 | TODO | - | T-130..T-137 | Backup to N: + REVIEW + ship v0.6.0 |

## DONE — verified against the master list (76 smoke + 461 unit green)
| item | evidence |
|---|---|
| Hierarchy 1-level (nest/collapse/indent/unnest/files merge) | test_silo_hierarchy_nest_collapse_promote |
| Tick ✅ on silos + Settings toggle | test_silo_tick_toggle_persists_and_remaps |
| Middle-click -> Trash; menu slimmed + icons | test_trash_silo_writes_md_and_removes_slot |
| Analog clock; header template {text}{time}{state} | smoke + settings field |
| Pin 📌 + # line-numbers buttons at line counter + separator | test_hide_on_clickout_toggle_and_header_mirrors |
| Date glyph disappearing (17 Jul fmt) | TS_STAMP_LINE_RE unified |
| Container: delete/rename dialogs, Del/F2/Enter/Ctrl+Shift+C/Ctrl+N/Ctrl+V, views, links, clip->file, counters+breakdown | tests |
| Snippet hidden after silo delete (ghost search filter) | test_delete_silo_keeps_snippets_visible |
| Theme button garble (10px metrics vs 11px QSS) | test_theme_switch_keeps_button_labels + fit test |
| Drop zones overlay; binary -> Files auto | test_drop_overlay_zones_and_routing |
| Header-change buried folder: slug ignores stamps + live rename (1 silo = 1 folder) | test_live_retitle_renames_folder_no_duplicates |
| Alt+E/S/A defaults, Alt+A new + bindable; Home/End left; Move to Top | test_move_silo_to_top_and_bottom_remap |
| Normal Window flashbang; full clock fits 960 | test_header_fits_quarter_fullhd_with_full_clock |
| 📁2 │ 177 counter separator on silo rows | this wave |
| Backup N: | robocopy 17.07 |

## Previous waves (archive)
T-001..T-007 (Antigravity asp init), T-101..T-125 (v0.5.3) — all DONE, see git log + tags v0.4.0/v0.5.0/v0.5.3.

## Out of scope note
PureRef-style free canvas with image RESIZE inside the panel — deliberately not built
(lightweight constraint); container has image preview pane + Explorer views instead.
