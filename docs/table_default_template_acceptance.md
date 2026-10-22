# Table default template — Windows GUI acceptance (T-1467 / T-1468)

Physical acceptance that cannot be automated offscreen. Nothing here is claimed
as passed by a test: `tests/test_table_default_layout_t1466.py`,
`tests/test_table_dialog_defaults_t1468.py`, and `tests/test_table_default_persistence_t1468.py`
cover the engine, settings, dialog integration, and persistence layers; the 13 steps below
exist because a real window, a real mouse and a real restart are the only places they can be seen.

The template is the one authority: whatever the user saves is the shape AND the
presentation of the NEXT new table, and nothing else. A new table has genuinely
empty cells — the A/B/C labels are painted by the table header, never written
into the Markdown.

Table defaults workflow is accessible directly from any table grid (in Table silos or in
modal "Edit Table..." dialogs over text silos) via the right-click context menu:
* **Save Current Table Layout as Default**: saves current dimensions, manual widths/heights, and word-wrap.
* **Reset Table Layout to Default**: re-applies the saved template to the active table (refuses with explanation if column count mismatches).
* **Restore Factory Table Defaults**: resets template back to factory defaults without modifying the open table.

## Steps (record source / Qt / GUI / EXE result per row)

| # | Step | Expected | Source | Qt | GUI | EXE |
|---|------|----------|--------|----|-----|-----|
| 1 | In a Table grid (or modal Edit Table dialog), right-click → "Save Current Table Layout as Default" | Saved to settings, no error, dirty marked | | | | |
| 2 | Create a NEW Table silo | Saved columns, visible rows, every cell empty | | | | |
| 3 | Click any cell, type, Ctrl+Z | Undo returns the exact empty shape | | | | |
| 4 | Adjust to 12 cols, 15 rows (widths dragged by hand, word wrap ON), right-click → "Save Current Table Layout as Default" | Saved with those widths and the wrap flag | | | | |
| 5 | Create a NEW Table silo | 12 columns, 15 visible rows, dragged widths, wrap ON | | | | |
| 6 | Restart the app, create a new Table silo (or insert table in Text silo) | Opens with 12x15, same column widths and wrap ON | | | | |
| 7 | In a Text silo, insert table via toolbar "Insert Table" | Dialog opens with default rows=15 / columns=12 | | | | |
| 8 | Accept dialog, right-click table → "Edit Table..." | Modal TableEditDialog opens with 12x15 and saved widths | | | | |
| 9 | In Insert Table dialog type 20 rows / 3 columns, OK | Exactly 20x3, no snap back to 12x15 or 7x10 | | | | |
| 10 | Edit an EXISTING populated table (add a row, drag a column) | Its own shape and widths are untouched by any template save | | | | |
| 11 | In a 3-column table, right-click → "Reset Table Layout to Default" (template is 12 cols) | Refusal dialog explains shape mismatch (3 cols vs 12 cols); data intact | | | | |
| 12 | Transform-to-Table an EMPTY text silo | Seeded with the saved 12x15 shape, empty cells | | | | |
| 13 | Per-silo navigation away and back (Remember Silo Scroll ON and OFF) | Per-silo widths/heights/scroll follow the silo; template never overwrites them | | | | |

## Also confirm by eye

* Column headers read A, B, C, … and the Markdown header row stays empty
  (`|  |  |  |`), so a copy-paste into another editor carries no A-G junk.
* "Reset Table Layout to Default" resizes only the open table, after a
  confirmation; "Restore Factory Table Defaults" resets only the saved template
  and leaves the open table alone.
* In modal "Edit Table..." dialogs over text silos, all right-click table template
  actions operate cleanly without crashing.

## Result

Automated part (do not re-run by hand):
* `pytest tests/test_table_default_layout_t1466.py` → 64 passed.
* `pytest tests/test_table_dialog_defaults_t1468.py` → 12 passed.
* `pytest tests/test_table_default_persistence_t1468.py` → 5 passed.
Physical part: ______________ (operator, date __________).
