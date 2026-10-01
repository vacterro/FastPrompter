# T-1352: Copy placement collision audit

The exact 0.8.69 candidate b7eac60 failed GitHub CI run 36628176551:
`1 failed, 5076 passed, 9 skipped`. A Copy control at `(48, 24, 16, 16)`
covered trailing prose at `(4, 19, 154, 13)`. The same test passed locally.

The picker protected only the target's visual row and the immediately adjacent
paragraphs. A control taller than a text row can reach another wrapped row of
the current paragraph. Concealed image markup can also create a 2px intermediate
row, so checking only the target's row height is insufficient.

The repair uses all viewport text as occupancy, retains the image pill as a
separate blocker, and validates space before/after the visible block. Layout
inspection starts at the first visible block and, within a large wrapped block,
the first visible QTextLine. It stops at the viewport bottom.

The new regression varies font size, token length and viewport width, checks
every trailing-prose fragment, and verifies that the control still identifies
the original image. With unchanged oracle bytes and command, restoring b7eac60's
editor gives `14 failed, 22 passed`; restoring the repair gives `36 passed`.
Additional regressions cover following paragraphs and bound inspection of a
1500-block document and a single paragraph with over 1000 wrapped lines.

Focused image/link/highlighter/hover verification: **219 passed**. Repository
compile, Ruff and Bandit gates passed. Full `tests/ tests_smoke/` completed:
**5099 passed, 26 skipped in 1537.26s**, exit 0. Independent review repeated
the geometry/hover regressions: **79 passed**. At each of DPI scale factors
1.25, 1.5 and 2, the row-collision/wrapped-copy/hover matrix gave **56 passed**.

The previously built EXE `76e4d1856b7a25cffb87d92e1f18f250ee43044f94a35acf6659c0d614a29d04`
passed all 13 packaged lifecycle/persistence/IPC checks after the operator
closed FastPrompter. That probe is evidence for the previous binary only; the
source repair requires a fresh exact build and probe before publication.

The wider 1.0.0 goal remains incomplete. T-1353 records missing runtime keys,
English fallback values and the RU exemption in the kitchen validator. Structural
translation validation cannot establish the requested 100% language coverage.
