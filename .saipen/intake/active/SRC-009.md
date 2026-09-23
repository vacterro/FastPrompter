Хорошо, исправь пожалуйста это и всё что с этим связано так чтобы не было
  проблем больше тоесть типо sold. Расчитываю на тебя, Астра!FASTPROMPTER  TRANSFER / SAFE IMAGE VIEWER / LINE-DRAG AUTOSCROLL /
SOUND STACKING / FILTERED-USAGE LAYOUT WAVE

ROLE

You are the implementation agent.

Work directly in the current FastPrompter repository.

Do not merely propose fixes.
Inspect, reproduce where possible, implement, add regression coverage, and leave
durable SAIPEN checkpoints.

IMPORTANT:
Do not release/build/push merely because targeted tests are green.
This wave modifies editor input, cross-project state transactions, local-file
opening and audio ownership. It requires a broader regression pass afterward.

======================================================================
0. FIRST ACTION: PERSIST THE NEW USER INTENT AS SAIPEN TICKETS
======================================================================

Before modifying product code, boot the repository SAIPEN protocol according
to AGENTS.md:

    STATE.md - BOARD.md - LOG.md
    then the authoritative SAIPEN BOOT/COMMANDS documents if not already loaded.

Do NOT hand-edit BOARD/STATE if a canonical SAIPEN operation exists.

Create durable P1 tickets for:

A. Cross-project transfer correctness and transfer-system sweep
B. Safe local image viewer without alarming shell warning
C. Whole-line drag edge autoscroll
D. Filtered AI usage compact/no-dead-gap layout

DO NOT create a duplicate sound ticket.

T-1216 already exists:
    Sound playback isolation and stray-sound sweep...

UPDATE/CHECKPOINT T-1216 with the NEWER user intent:

OLD acceptance currently says:
    identical rapid repeats coalesce

That is now too broad and conflicts with the new request.

New contract:
- deliberate repeatable actions such as Ctrl+Q are STACKABLE;
- N deliberate presses produce N sequential sound events;
- high-frequency/noise-like events such as typewriter may still explicitly
  COALESCE;
- long/exclusive alarms may reject low-priority UI sounds rather than letting
  them replay seconds later;
- one physical user action must still produce exactly ONE request, not duplicate
  requests from two hotkey routes.

Record the current user request as a source receipt if the protocol requires one,
and checkpoint the mapping of:
    requirement - ticket ID - acceptance

Do this before implementation so compaction cannot destroy the intent.

======================================================================
1. TRANSFER TO PROJECT  REPRODUCE THE CURRENT FAILURE FIRST
======================================================================

Relevant code:

    src/fastprompter/main.py

    show_temp_menu()                  16589
    transfer_silo_to_project()        17003
    _transfer_to_snippet()            17226
    move_preset_cross_category()      10925
    commit_current_text()             13095
    _flush_live_editor()              13063
    _on_text_changed()                18161
    cache_current_text()              18214
    _acquire_silo_slot()              10415

Relevant state registry:

    src/fastprompter/core/state.py
    _PER_CATEGORY_ALIASES

Existing transfer tests:

    tests_smoke/test_app_smoke.py
      test_transfer_lands_in_destination_silos_not_snippets
      test_transfer_carries_the_colour_box
      test_transfer_refuses_empty_and_same_project
      test_transfer_appends_when_destination_has_no_blank_row

    tests_smoke/test_audit_second_wave.py
      full identity transfer
      folder mapping
      sync map/root semantics
      undo-related transfer state

----------------------------------------------------------------------
1.1 VERIFIED DESIGN DEFECT: LIVE EDITOR TEXT IS NOT AUTHORITATIVE HERE
----------------------------------------------------------------------

Typing does NOT immediately update:

    data"temp_presets"active_temp_slot

_on_text_changed() starts a debounce timer:

    normal document: 800 ms
    20K chars:      1500 ms
    50K chars:      2500 ms

Only later does cache_current_text() update the underlying slot.

However:

    show_temp_menu()

decides whether Transfer actions exist by reading:

    data"temp_presets"
    data"archive_temp_presets"

And:

    transfer_silo_to_project()

also validates and copies from those same stores.

Therefore this scenario is currently unsafe:

1. Open silo A.
2. Type/change text.
3. Before the cache debounce fires, right-click it.
4. Transfer to Project B.

Possible results:
- Transfer submenu absent because the stored slot still looks empty.
- Transfer returns False because source looks empty.
- Old pre-edit content is transferred.
- Latest edit remains behind / appears lost.

This is a strong candidate for the users "Transfer to Project doesnt work".

WRITE A FAILING REGRESSION BEFORE FIXING IT.

Required tests:

A. Fresh formerly-empty silo:
   - stored slot = ""
   - live editor = "NEW LIVE TEXT"
   - debounce timer has not fired
   - opening the context menu must offer Transfer to Project
   - transfer must move exactly "NEW LIVE TEXT"

B. Edited non-empty silo:
   - stored slot = "OLD"
   - live editor = "NEW"
   - transfer immediately
   - destination must receive "NEW", never "OLD"

C. Direct API:
   Call transfer_silo_to_project() directly after an unflushed edit.
   Correctness must not depend on the context menu having been opened first.

D. Archive source:
   Same invariant for an active archive silo.

Use the existing authoritative editor flush machinery.
Do NOT invent another QTextEdit - store synchronization path.

Prefer:
    commit_current_text()
or a small owner-aware helper using:
    _editor_text_snapshot()
    _flush_live_editor()

The actual transfer function must protect itself.
Fixing only show_temp_menu() is insufficient because callers/tests/direct actions
may bypass the menu.

Avoid committing the wrong owner when:
- editing a snippet;
- source is a different non-active silo;
- source archive namespace differs from the active editor owner.

Implement an explicit helper if necessary:

    _flush_transfer_source_if_live(idx, is_archive)

It should only flush when the requested transfer source is the current live editor
owner.

----------------------------------------------------------------------
1.2 REMOVE THE SECOND, DRIFTING DESTINATION SLOT ALLOCATOR
----------------------------------------------------------------------

transfer_silo_to_project() currently defines its own private:

    _slot_free()

This duplicates the canonical insertion/capacity machinery around:

    _silo_capacity()
    _slot_has_identity()
    _slot_is_pristine()
    _acquire_silo_slot()

The duplication has already drifted.

Current transfer _slot_free() checks several stores, but it does NOT use the
complete canonical slot-state definition.

For example, canonical slot state includes things such as:

    pinned_silos
    silo_collapsed
    silo_children
    silo_gaps
    silo_gap_names
    ...

A destination row can therefore be text-empty while still carrying residual
slot metadata.

That means transfer can potentially reuse a "blank" destination slot and let the
incoming silo inherit stale state.

Do not patch _slot_free() with another five if-statements.
That merely schedules the next bug for Thursday.

Create ONE category-aware allocator/pristine predicate, e.g. conceptually:

    _category_slot_has_state(category, idx, is_archive=False)
    _acquire_silo_slot_for_category(category, is_archive=False)

It must use the canonical state registries rather than another handwritten list.

The existing _acquire_silo_slot() is active-category based, so extend/refactor
it cleanly rather than temporarily switching categories or rebinding aliases.

Required invariant:

A reusable destination slot is:

    text-empty
    AND
    free of every slot-owned state namespace relevant to that category.

No inherited:
- colour
- folder
- path
- type
- selection/tick
- pin
- collapse
- hierarchy residue
- gap/gap name
- link/sync mapping
- cursor/view state
- last-edited metadata

----------------------------------------------------------------------
1.3 DEFINE TRANSFER OWNERSHIP EXPLICITLY
----------------------------------------------------------------------

There is currently contradictory archaeology in the source.

_move_silo_identity() says positional layout such as pin/gap is not transferred.

But _SILO_INDEX_STATE comments now explicitly say:
    a gap belongs to the silo it was placed under.

Do not leave this ambiguous.

Build/document one transfer ownership contract.

At minimum:

IDENTITY THAT MUST MOVE:
- current live text
- colour
- silo type
- files-folder mapping + physical folder
- project path
- per-silo file link
- project-sync identity with existing same-root/different-root semantics
- last edited
- saved cursor/view state
- done tick where current product contract says it follows the silo

SOURCE-LOCAL STATE THAT DOES NOT MOVE:
- must be explicitly cleared from the now-empty source row
- must never remain attached to an empty slot by accident

HIERARCHY:
- do not silently transfer only half a parent/child relationship.
- A single-silo transfer across projects should not create cross-project
  parent references.
- Explicitly detach/unnest according to current product semantics.

GAPS:
Resolve this against the current T-704 invariant:
    "a gap belongs to the silo it was placed under"

If that remains the canonical product rule, move the silo gap + gap name with the
silo rather than leaving the gap on an empty source row.

If historical product intent proves otherwise, document the intentional
cross-project exception and add tests.

The critical invariants are:
- no ghost state left at source;
- no stale state inherited at destination;
- no dangling hierarchy.

----------------------------------------------------------------------
1.4 MAKE THE TRANSFER A REAL TRANSACTION
----------------------------------------------------------------------

Current code performs a physical os.rename() before the in-memory commit.

That is sensible preflight ordering, but the post-rename commit is not enclosed
in a complete rollback boundary.

The _move_silo_identity() doc claims the caller can restore on failure, but
transfer_silo_to_project() does not currently have a broad transactional rollback
around all commit steps after the physical move.

Fix this.

Desired flow:

PHASE 1  READ
- flush authoritative live source if applicable
- capture source text/state
- identify target category

PHASE 2  PREFLIGHT
- target exists
- source != destination where invalid
- acquire pristine destination slot
- verify destination capacity
- resolve folder move
- verify roots/path semantics
- calculate every metadata transformation
- capture source and destination snapshots

NO MUTATION before preflight succeeds.

PHASE 3  COMMIT
- perform physical folder move
- publish destination slot
- move identity state
- clear/detach source state
- create one undo transaction
- mark dirty
- refresh UI

PHASE 4  ROLLBACK ON ANY FAILURE
If anything after the physical move fails:
- restore source category stores
- restore destination category stores
- reverse the physical folder move when it was already published
- restore active editor/UI ownership as needed
- log the failure
- return False

User data must never end in half source / half destination state.

----------------------------------------------------------------------
1.5 SWEEP ALL TRANSFER ROUTES
----------------------------------------------------------------------

Do not fix only one menu entry.

Audit:

    transfer_silo_to_project()
    _transfer_to_snippet()
    move_preset_cross_category()
    archive - project
    snippet/category drag routes
    undo / redo of cross-project transfer

Every route must share these invariants:

- authoritative current text;
- destination preflight before source deletion;
- one capacity rule;
- no metadata contamination;
- no data loss on refusal;
- no partial physical move;
- undo/redo restores both sides.

Add tests for:

1. active unflushed source
2. empty source
3. full target
4. reusable genuinely-pristine target slot
5. blank target slot with stale metadata - MUST NOT be reused
6. physical folder move success
7. physical folder move failure
8. stale missing folder mapping
9. same project refusal
10. archive source
11. sync same-root
12. sync different-root
13. undo
14. redo
15. source/destination persistence round trip
16. transfer followed immediately by switching to destination project

======================================================================
2. LOCAL IMAGE SECURITY WARNING  REMOVE THE SCARY UX WITHOUT REMOVING
   ACTUAL SECURITY
======================================================================

Relevant code:

    src/fastprompter/ui/editor.py

    _SAFE_LINK_SCHEMES
    authorize_and_open_url()         2230

The reported dialog is generated by FastPrompter itself:

    Security Warning

    This link points to a file on your computer:
    ...
    Opening it may run a program. Are you sure you want to open it?

The current test suite explicitly requires this warning for ALL local suffixes,
including:

    .png
    .jpg-like documents
    .txt
    .pdf
    .exe
    .cmd
    ...

See:

    tests/test_clickable_links.py
    test_core003_every_local_type_requires_confirmation

The users complaint is valid for pasted screenshots.

A PNG opened in an INTERNAL image viewer should not be described as if the user
were about to execute an unknown program.

DO NOT solve this by globally deleting the local-file security gate.

That would turn:
    "dont scare me about my screenshot"
into:
    "silently shell-open .exe/.cmd/.lnk"

which is idiotic and unnecessary.

----------------------------------------------------------------------
2.1 IMPLEMENT A SAFE INTERNAL IMAGE VIEWER PATH
----------------------------------------------------------------------

Create or extract a small reusable Qt Widgets image viewer.

Possible module:

    src/fastprompter/ui/image_viewer.py

Use:
- QDialog
- QScrollArea
- QLabel/QPixmap or QImageReader
- KeepAspectRatio
- sensible minimum/default size
- fit-to-window
- optionally 100% / zoom if easy
- filename/path shown unobtrusively
- optional "Show in Explorer"

No Electron/WebView/browser.

Supported image detection should be based on a strict allowlist and preferably
QImageReader capability, not merely "the filename ends with something nice".

At least:
    png
    jpg/jpeg
    webp
    gif
    bmp

Handle SVG separately only if the chosen Qt decoding path is safe and already
supported.

When a local image target is clicked from:
- pasted image pill
- rendered image
- Live Preview link/image
- Reading view image

route it to:

    internal image viewer

NOT:
    QDesktopServices.openUrl(file://...)
NOT:
    os.startfile()

Therefore:
- no shell association is invoked;
- no executable gets launched;
- no Security Warning is needed.

----------------------------------------------------------------------
2.2 CENTRALISE LOCAL TARGET ROUTING
----------------------------------------------------------------------

Do not scatter ".png - viewer" checks around four mouse handlers.

Create one target-opening decision point, conceptually:

    open_link_target(url, parent, lang)

Rules:

HTTP/HTTPS/normal web:
    existing QDesktopServices behaviour

LOCAL SUPPORTED IMAGE:
    open internal ImageViewer
    no scary confirmation

LOCAL DIRECTORY / REVEAL:
    existing non-executing Explorer/reveal path

LOCAL ARBITRARY FILE:
    retain the existing shell-launch confirmation gate

UNSUPPORTED / BROKEN IMAGE:
    show a normal non-security error:
        "Image could not be previewed"
    offer Reveal/Open externally only through the existing guarded shell path

Do not silently fall back from broken PNG decoding to shell execution.

----------------------------------------------------------------------
2.3 UPDATE THE SECURITY REGRESSIONS
----------------------------------------------------------------------

Rewrite the current all-suffix test.

New contract:

SAFE INTERNAL IMAGE:
- no QMessageBox.warning
- no QDesktopServices.openUrl(file://...)
- internal viewer receives exact canonical local path

ARBITRARY SHELL-OPEN FILE:
- .exe/.cmd/.bat/.ps1/.lnk/.py/.msi/etc still requires approval
- declined - shell never sees it
- approved - exactly one shell open

WEB:
- bypasses local warning as before

Add Windows path cases:
    V:/___VAC/.../image.png
    C:/...
    spaces
    Unicode filename
    file:///V:/...

This directly covers the users screenshot path style.

======================================================================
3. WHOLE-LINE SHIFT/CTRL+SHIFT DRAG  EDGE AUTOSCROLL
======================================================================

Relevant implementation:

    src/fastprompter/ui/editor.py

Current whole-line drag uses:

    Ctrl + Shift + hold LMB

mousePressEvent:
    _line_drag_source_block

mouseMoveEvent:
    activates drag
    derives _line_drag_hover_block from cursorForPosition(event.pos())

mouseReleaseEvent:
    calls _move_lines(...)

There is currently NO edge autoscroll in this line-drag branch.

The existing test:

    test_line_blocking_drag_swaps_whole_lines

only moves within the already-visible viewport.

----------------------------------------------------------------------
3.1 DO NOT BREAK NORMAL TEXT SELECTION
----------------------------------------------------------------------

The user described "Shift + Click + Drag", but the current implemented whole-line
gesture is Ctrl+Shift+LMB.

Do NOT globally steal plain Shift+drag from normal text selection merely to match
the shorthand wording.

Implement autoscroll for the EXISTING whole-line drag mode.

If another existing Shift-only whole-line entry path exists, route both through
the same helper.

Normal Shift-selection must remain normal.

----------------------------------------------------------------------
3.2 IMPLEMENT TIMER-DRIVEN EDGE AUTOSCROLL
----------------------------------------------------------------------

Mouse move events alone are insufficient:
once the pointer sits at the edge, it may stop moving, but scrolling must continue.

Add a QTimer owned by VaultTextEdit.

Conceptual state:

    _line_drag_autoscroll_timer
    _line_drag_last_pos
    _line_drag_scroll_direction
    _line_drag_scroll_speed

When an ACTIVE whole-line drag enters a configurable edge zone:

TOP:
    scroll upward

BOTTOM:
    scroll downward

Recommended edge zone:
    around 2448 logical px depending on UI scale

Timer:
    3050 ms

Speed:
    at least one scroll step near the boundary;
    increase smoothly as pointer moves further into/past the edge.

Do not mutate text while scrolling.
Only update viewport position and current hover/drop target.

After every autoscroll tick:

1. move verticalScrollBar
2. clamp a probe point into the viewport
3. recompute the block under the dragged pointer
4. update _line_drag_hover_block
5. repaint the drop indicator

This lets the destination advance beyond the lines that were visible at drag
start.

----------------------------------------------------------------------
3.3 CLEAN LIFETIME
----------------------------------------------------------------------

Stop the timer on:

- mouse release
- drag cancellation
- lost mouse buttons
- editor destruction
- any route that resets _line_drag_source_block

If pointer leaves the viewport DURING an active mouse drag, continuing to scroll
is acceptable while the left button is physically still held.

Use QApplication.mouseButtons() or equivalent inside the timer to prevent a
stuck scroll if Qt misses release.

No runaway timer after the drag.

----------------------------------------------------------------------
3.4 TESTS
----------------------------------------------------------------------

Use a deliberately short viewport containing many lines.

Required:

1. drag visible line to bottom edge
   - scrollbar increases while pointer remains stationary

2. hover/drop block advances beyond initial viewport

3. release after autoscroll
   - line is moved to the newly reached destination

4. bottom - top works symmetrically

5. multi-line selected block remains one unit

6. timer stops on release

7. no line drag - no custom autoscroll

8. ordinary Shift selection is unchanged

9. no text mutation occurs until actual drop

======================================================================
4. SOUND STACKING  NEW INTENT OVERRIDES THE OLD COALESCE CONTRACT
======================================================================

Relevant file:

    src/fastprompter/core/sound_manager.py

Current architecture is inconsistent between backends.

PACKAGED / NO QSoundEffect:
    winsound
    _ws_stack deque
    _WS_STACK_MAX = 6
    rapid short sounds can stack

QSoundEffect backend:

    player = self._players"__ui__"

    if player.isPlaying():
        return

So a second deliberate request while the first sound is playing is simply
discarded.

Existing test:

    TestSameEventCoalesce.test_skip_when_still_playing

LOCKS that behaviour in.

This is directly incompatible with the new user requirement:

    Press Ctrl+Q several times
    = hear several snap sounds sequentially

The test must be changed together with the implementation.

----------------------------------------------------------------------
4.1 DO NOT JUST DELETE isPlaying()
----------------------------------------------------------------------

Calling QSoundEffect.play() repeatedly on the same player is not stacking.
It can restart/truncate playback.

Build a backend-independent semantic sound scheduler.

Each request should conceptually carry:

    event
    resolved path
    volume
    policy
    source/reason
    timestamp

Suggested policies:

STACK_SHORT
    deliberate hotkeys / discrete UI commands
    every intentional request is retained up to a bounded queue

COALESCE_HIGH_RATE
    typewriter / other naturally spammy events
    repeated events may coalesce intentionally

EXCLUSIVE_LONG
    alarm / long notification
    owns the audio channel while playing
    low-value UI sounds should usually be DROPPED rather than replayed
    several seconds later

PREVIEW
    explicit settings preview
    must not cut a running alarm
    define whether it queues briefly or is refused while exclusive audio owns
    the channel

Do not use one global:
    "same sound = coalesce"

That is what the user just rejected.

----------------------------------------------------------------------
4.2 CTRL+Q HAS TWO HOTKEY ROUTES  NORMALISE OWNERSHIP
----------------------------------------------------------------------

Current main.py:

    HOTKEY_SOUND_EVENTS"hk_snap" = "snap"

and hk_snap is NOT in HOTKEY_SOUND_SELF.

The registered shortcut path therefore gets its sound from:

    _with_hotkey_sound()

But editor.py has its own direct configurable hotkey interception:

    if matches("hk_snap", "Ctrl+Q"):
        mw.cycle_snap_corner()
        return

That route bypasses the shortcut wrapper.

cycle_snap_corner() itself currently does NOT own the "snap" sound.

Therefore sound behaviour can vary depending on focus/routing.

Fix this ownership ambiguity.

Preferred contract:

    cycle_snap_corner()

owns exactly ONE "snap" sound request because it is the logical action.

Then:
- add hk_snap to HOTKEY_SOUND_SELF;
- registered QShortcut must not add a second request;
- editor-direct route gets the same action-owned sound;
- button/direct invocation also behaves consistently if appropriate.

Required tests:

ONE Ctrl+Q:
    exactly one snap request

N deliberate Ctrl+Q presses:
    exactly N snap requests

N requests while first sound is still playing:
    all STACK_SHORT requests play sequentially, bounded by queue policy

Run this for:
- editor-focused route
- registered shortcut route

No double sound per one press.

----------------------------------------------------------------------
4.3 UNIFY QSoundEffect AND WINSOUND SEMANTICS
----------------------------------------------------------------------

The scheduler/policy must sit ABOVE the transport.

Do not have:
    dev build = coalesce
    packaged EXE = stack

Both transports must observe the same semantic queue.

For QSoundEffect:
- use playback completion / playingChanged / status events to drain queued
  requests sequentially;
or
- use another safe serial transport implementation.

For Windows winsound:
the current SND_ASYNC + estimated WAV duration + 30 ms pad is an improvement,
but the users tail/replay-tail report means it is not yet proven sufficient.

Strongly evaluate a single dedicated playback worker using synchronous:

    winsound.PlaySound(... SND_SYNC ...)

OFF the GUI thread.

Benefits:
- the worker knows when the WAV actually completed;
- next queued sound cannot start in the middle of the previous waveOut reset;
- sequential stacking is natural;
- no guessed 30 ms timing race;
- GUI remains asynchronous.

If that architecture is adopted:
- one owner thread/worker;
- bounded queue;
- clean shutdown;
- no Qt widget access from worker;
- scaled/custom WAV path resolved safely;
- explicit stop/cancel behavior for app exit.

Do not introduce an immortal worker that recreates the old interpreter-shutdown
problem.

If retaining SND_ASYNC, prove with real Windows playback that the tail bug is
actually gone.

----------------------------------------------------------------------
4.4 COMPLETE T-1216 STRAY-SOUND OWNERSHIP SWEEP
----------------------------------------------------------------------

The users unresolved report remains:

- first sound may lose the last 0.5 s;
- next sound can start with a tail from the previous sound;
- unrelated sounds sometimes appear alongside intended sounds;
- repro is intermittent.

Do not mark this fixed merely because queue unit tests pass.

Audit EVERY sound-producing route.

Search for:
    SoundManager.play
    play_sound
    play_file
    play_sound_ref
    QSoundEffect
    winsound.PlaySound
    direct player.play()

Everything should reach one central arbitration layer unless there is a documented
reason otherwise.

Add the bounded provenance ring log already required by T-1216.

For every request record:

    monotonic/wall timestamp
    logical event
    source/reason
    resolved WAV
    policy
    owner/profile/silo if meaningful
    outcome:
        PLAYED
        QUEUED
        COALESCED
        DROPPED_EXCLUSIVE
        DROPPED_QUEUE_FULL
        CANCELLED
        FAILED

Do not spam normal UI or disk every keystroke.
Use a bounded in-memory diagnostic ring, exposed through troubleshooting/log dump
when needed.

This is essential for the intermittent "random sound" report:
next time it happens, provenance must answer WHO ASKED FOR IT.

Collision regressions:

- Ctrl+Q burst
- UI click during short UI sound
- UI click during long timer alarm
- timer + interval same tick
- productivity + interval
- AI limit notification + timer
- preview while alarm plays
- typewriter burst
- profile switch with queued requests
- stale callback after silo/profile switch
- different short sounds stacked in order
- same stackable sound repeated in order

Important UX:
A click that occurred during a 10-second alarm must NOT suddenly play ten seconds
later.

Stacking is for intentional short bursts, not delayed ghosts.

======================================================================
5. FILTERED USAGE: REMOVE THE LARGE DEAD HEADER GAP
======================================================================

Relevant:

    src/fastprompter/ui/limit_gauges.py

Current code ALREADY contains a previous attempted fix:

    _update_width()
    _placeholder_width()
    _paint_all_filtered()

When:
    _visible_accounts() == 
and:
    _has_any_accounts() == True

it intentionally keeps:

    clusters = self._placeholder_width()

And the regression:

    TestAllAccountsFilteredPlaceholder
    test_keeps_placeholder_footprint_not_a_sliver

explicitly requires the widget to remain comfortably wider than the old sliver.

That contract now conflicts with the users visual feedback.

The user sees that retained footprint as a large GAP between the top-bar timers.

Do not layer another spacer/filler on top.
Change the contract.

----------------------------------------------------------------------
5.1 DESIRED ALL-FILTERED STATE
----------------------------------------------------------------------

Scenario:

- accounts exist;
- "hide 5h/0%" and/or "Only available 5h windows" filters all currently unusable
  quota displays;
- reset countdown still exists.

Desired:

    timer/status compact filtered indicator, if any reset countdown

NOT:

    timer/status large invisible/dead reserved gauge area     reset

The reset countdown must remain visible.
Filtering display eligibility must not destroy reset ownership.

This already has T-1214 regression coverage; preserve it.

----------------------------------------------------------------------
5.2 COMPACT EMPTY/FILTERED INDICATOR
----------------------------------------------------------------------

When every known account is filtered out, choose a deliberate compact state.

Preferred:
- a tiny dim neutral indicator such as a compact "0"/empty mini-cluster;
- or another visually consistent minimal mark from the existing gauge language.

It should still provide a tooltip explaining:
    all currently unusable pools are hidden by the active filter

But its width must be only the ACTUAL painted ink + normal padding.

Do NOT reserve:
    account-label gutter + full MIN_BARS cluster + normal account gap

if most of those pixels visually read as empty space.

Use QFontMetrics / actual unit widths where appropriate rather than a giant
hard-coded placeholder.

After width changes:
- setFixedWidth appropriately
- updateGeometry()
- invalidate parent layout as needed
- ensure topbar visibility coordinator re-evaluates if required

Switching:
    visible accounts - all filtered - visible accounts

must resize immediately and deterministically.

----------------------------------------------------------------------
5.3 REWRITE THE OLD TEST THAT NOW ENCODES THE WRONG UX
----------------------------------------------------------------------

Replace:

    test_keeps_placeholder_footprint_not_a_sliver

with the new invariant.

Required geometry tests:

1. all filtered widget is compact

2. it still paints visible dim ink rather than a mysterious blank strip

3. tooltip says filtered, not "no accounts selected"

4. genuinely empty service still says no accounts selected

5. reset countdown remains visible

6. gauges reserved width is approximately painted indicator bounds + padding

7. there is no large dead geometry between:
       limit_gauges
       lbl_limit_timer

Assert actual widget geometry when possible, not just text/state.

8. changing filter on/off updates width without restart or manual resize

======================================================================
6. TARGETED VERIFICATION
======================================================================

Run focused tests after each subsystem.

TRANSFER:
    existing transfer tests in:
        tests_smoke/test_app_smoke.py
        tests_smoke/test_audit_second_wave.py
    plus new live-editor/transaction/capacity regressions

LOCAL LINKS/IMAGES:
    tests/test_clickable_links.py
    screenshot paste/image tests

LINE DRAG:
    test_line_blocking_drag_swaps_whole_lines
    plus new autoscroll cases

SOUND:
    tests/test_sound_manager.py
    relevant hotkey tests
    timer/interval/productivity sound tests

USAGE:
    tests/test_usage_limits_gauge_layout.py
    tests/test_usage_limits_hide_zero.py
    reset ownership tests

Then run at minimum:

    uv run python -m compileall -q src FastPrompter.pyw
    uv run ruff check src/ tests/ tests_smoke/
    uv run pytest tests/ -q

and the relevant smoke subsets.

If the repository environment supports the full smoke suite safely, run it.

Do NOT weaken existing security/data-integrity tests merely to get green.
Update tests only where the USERS CONTRACT intentionally changed:
- safe internal images no longer need shell warning;
- deliberate stackable sounds no longer coalesce;
- all-filtered usage no longer reserves a large placeholder footprint.

======================================================================
7. WINDOWS MANUAL ACCEPTANCE
======================================================================

Some of this MUST be checked on real Windows.

TRANSFER:
1. Type into a silo.
2. Immediately, before waiting, Transfer to Project.
3. Destination contains the exact newest text.
4. Source is empty.
5. Switch destination immediately: content + colour/type/files/link intact.
6. Undo returns the complete silo.
7. Redo transfers it again.

IMAGE:
1. Paste screenshot with Ctrl+V.
2. Open it from its image link/pill.
3. Internal viewer opens immediately.
4. NO "Opening it may run a program" warning.
5. No external image app starts.
6. Clicking an .exe/.cmd local link still gets the security gate.

LINE DRAG:
1. Ctrl+Shift+drag a line downward.
2. Hold at bottom edge without moving mouse.
3. Document continues scrolling.
4. Drop many screens below.
5. Repeat upward.

SOUND:
1. Press Ctrl+Q 36 times rapidly.
2. Hear 36 complete snap sounds in sequence.
3. No clipping.
4. No previous WAV tail at the beginning of the next.
5. One Ctrl+Q produces one sound, never two.
6. Trigger long alarm, click UI during it.
7. The old click must not replay several seconds later.
8. Run mixed timer/interval/UI actions and inspect provenance log if anything
   unexpected is audible.

USAGE:
1. Enable hide 5h/0% / only-available-now filter.
2. Reach state where every displayed quota pool is filtered.
3. Header closes up cleanly.
4. No giant dead strip.
5. Small filtered-state indicator may remain.
6. Reset countdown remains fully visible.

======================================================================
8. COMPLETION STANDARD
======================================================================

Do not close the wave until:

TRANSFER
- newest live editor text can never be lost/stale;
- destination allocation uses one canonical category-aware rule;
- destination cannot inherit stale slot state;
- transfer is transactional;
- undo/redo is symmetric;
- all transfer routes were audited.

IMAGE VIEWER
- pasted/local images open internally without fake-danger warning;
- arbitrary shell-launch files remain protected.

AUTOSCROLL
- whole-line drag crosses viewport boundaries continuously in both directions;
- native Shift selection remains intact.

SOUND
- deliberate hotkey repeats stack;
- high-rate typewriter can still use explicit coalescing;
- dev and packaged backends have the same semantic contract;
- Ctrl+Q routing produces exactly one request per press;
- no tail-cut/replay-tail regression is observed;
- provenance exists for future stray sounds;
- T-1216 checkpoint reflects the NEW contract.

USAGE
- all-filtered state no longer reserves a large dead placeholder;
- compact visual state is intentional;
- reset timer survives filtering.

Finally checkpoint every ticket with:
- root cause
- files changed
- tests added
- commands and exact results
- Windows manual result where applicable
- remaining limitation, if any

If the real Windows audio soak is not yet possible:
DO NOT falsely close T-1216.
Leave the code/test stage complete and checkpoint the remaining EXE/live-audio
verification explicitly.
