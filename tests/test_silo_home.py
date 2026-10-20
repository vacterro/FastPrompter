""""Remember Silo Scroll Position" (silo_remember_scroll) T-1459.

Replaces the old, inverted "Silos at Start" (silo_home) switch. With the new
switch ON (shipped default) a silo reopens exactly where it was left; with it
OFF every silo opens at the top. A missing or stale saved entry also opens at
the top — the old flag's fallback jumped to the END instead, which is the bug
this ticket fixes.

Behavioral controls need a real, full FastPrompter; tearing one down crashes
the offscreen Qt platform inside pytest, so they run in a short subprocess.
The one-shot legacy migration is a plain unit test.
"""

import os
import subprocess
import sys

_SCRIPT = r"""
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from fastprompter.main import FastPrompter

app = QApplication.instance() or QApplication([])

LONG = "\n".join("line %d %s" % (i, "x" * 40) for i in range(200))
LONG2 = "\n".join("other %d %s" % (i, "y" * 40) for i in range(200))

win = FastPrompter()
win.show()
win.resize(800, 600)
app.processEvents()

win.data["temp_presets"][:] = [LONG, LONG2, "", "", "", "", "", "", "", ""]
win.silo_docs[:] = []

problems = []
# _switch_to_slot only CAPTURES the outgoing silo when initial is falsy, so the
# very first open passes initial=True and every switch after it must not.
_first = [True]


def pos():
    return win.text_area.textCursor().position()


def sb():
    return win.text_area.verticalScrollBar().value()


def switch(idx, remember):
    win.data["silo_remember_scroll"] = "True" if remember else "False"
    win._switch_to_slot(idx, initial=_first[0])
    _first[0] = False
    app.processEvents()


def put(p):
    c = win.text_area.textCursor()
    c.setPosition(p)
    win.text_area.setTextCursor(c)
    app.processEvents()


def scroll_to(v):
    win.text_area.verticalScrollBar().setValue(v)
    app.processEvents()


# --- ON: A -> B -> A restores each silo's own caret independently ----------
switch(0, True)
put(500)
switch(1, True)
put(120)
switch(0, True)
if pos() != 500:
    problems.append("on-a-not-restored:%d" % pos())
switch(1, True)
if pos() != 120:
    problems.append("on-b-not-restored:%d" % pos())

# --- ON: a caret at offset 0 is a REAL saved state, not "unset" (repair A)-
# The old guard treated pos==0/anchor==0 as nothing saved and let the caller
# jump to the END. Put the caret at the top, leave, and come back.
switch(0, True)
put(0)
switch(1, True)
switch(0, True)
if pos() != 0:
    problems.append("on-top-caret-not-kept:%d" % pos())

# --- repair A oracle: the captured entry (offset 0 + fingerprint) restores -
switch(1, True)              # leave slot 0 -> capture_silo_state(0)
switch(0, True)              # back on slot 0: text_area holds LONG again
cat = win.get_current_category() or ""
entry = (win.data.get("silo_view_state_all", {}).get(cat) or {}).get("s0")
if not isinstance(entry, dict):
    problems.append("no-entry-captured")
else:
    if entry.get("pos") != 0 or entry.get("anchor") != 0:
        problems.append("capture-not-at-zero:%r/%r"
                        % (entry.get("pos"), entry.get("anchor")))
    if "text_len" not in entry or "text_crc" not in entry:
        problems.append("entry-has-no-fingerprint")
    elif win.restore_silo_state(0, False) is not True:
        problems.append("zero-offset-entry-rejected")
if pos() != 0:
    problems.append("oracle-caret-lost:%d" % pos())

# --- REAL GUI: verticalScrollBar().value() is captured and restored --------
# The cursor offset alone does not prove the viewport moved: set the scroll
# bar directly (NOT the caret, whose setTextCursor re-scrolls it into view)
# and require the exact value back.
switch(0, True)
scroll_to(0)
put(0)
scroll_to(400)               # viewport well down the document, caret at top
if sb() < 300:
    problems.append("scroll-not-applied:%d" % sb())
switch(1, True)              # leave slot 0 -> capture @scroll=400
switch(0, True)              # back on slot 0
if sb() < 300:
    problems.append("scroll-not-restored:%d" % sb())
if pos() != 0:
    problems.append("scroll-caret-moved:%d" % pos())

# --- REAL GUI: cursor at zero with viewport substantially scrolled ---------
# (the scroll value must be the authority, not a cursor-derived offset)
if sb() < 300 or pos() != 0:
    problems.append("cursor0-scrolled-broken:%d/%d" % (sb(), pos()))

# --- REAL GUI: viewport CONTENT is the scrolled region, not the top --------
# cursorForPosition(0,0) is the first block the viewport actually shows.
top_block = win.text_area.cursorForPosition(
    win.text_area.viewport().rect().topLeft()).blockNumber()
if top_block < 5:
    problems.append("viewport-content-at-top:%d" % top_block)

# --- OFF: every silo opens at the top (scroll AND caret) -------------------
switch(0, False)
put(700)
scroll_to(500)
switch(1, False)
if pos() != 0:
    problems.append("off-not-top:%d" % pos())
if sb() > 50:
    problems.append("off-not-top-scroll:%d" % sb())
switch(0, False)
if pos() != 0:
    problems.append("off-not-top-a:%d" % pos())
if sb() > 50:
    problems.append("off-not-top-scroll-a:%d" % sb())

# --- no saved state: opens at the top, never the end -----------------------
win.data.pop("silo_view_state_all", None)
win.data["temp_presets"][3] = LONG     # real content: an END fallback would show
switch(3, True)
if pos() != 0:
    problems.append("no-state-not-top:%d" % pos())
if sb() > 50:
    problems.append("no-state-not-top-scroll:%d" % sb())

# --- switching never mutates the document text -----------------------------
if win.data["temp_presets"][0] != LONG:
    problems.append("document-mutated")

# --- a stale entry (text changed under it) is rejected, not clamped --------
switch(0, True)              # land on slot 0
put(400)
switch(1, True)              # leave slot 0 -> capture @400 WITH a fingerprint
switch(0, True)              # back on slot 0, restore succeeds against LONG
win.text_area.insertPlainText("EDITED")   # text changed: offsets no longer apply
if win.restore_silo_state(0, False) is not False:
    problems.append("stale-fingerprint-accepted")

if problems:
    print("FAIL " + " ".join(problems))
    sys.stdout.flush()
    os._exit(1)
print("OK")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""


# Archive silos and rapid switching get their own script: the archive domain
# uses a different preset list and the same view-state map, so both paths must
# prove the scrollbar value survives, not just the caret offset.
_SCRIPT_ARCHIVE = r"""
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from fastprompter.main import FastPrompter

app = QApplication.instance() or QApplication([])

LONG = "\n".join("line %d %s" % (i, "x" * 40) for i in range(200))
LONG2 = "\n".join("other %d %s" % (i, "y" * 40) for i in range(200))

win = FastPrompter()
win.show()
win.resize(800, 600)
app.processEvents()

win.data["temp_presets"][:] = [LONG, LONG2, "", "", "", "", "", "", "", ""]
win.silo_docs[:] = []
win.data["archive_temp_presets"][:] = [LONG, LONG2]
win.archive_docs[:] = [None, None]

problems = []
_first = [True]


def pos():
    return win.text_area.textCursor().position()


def sb():
    return win.text_area.verticalScrollBar().value()


def switch(idx, remember, archive=False):
    win.data["silo_remember_scroll"] = "True" if remember else "False"
    win._switch_to_slot(idx, initial=_first[0], is_archive=archive)
    _first[0] = False
    app.processEvents()


def scroll_to(v):
    win.text_area.verticalScrollBar().setValue(v)
    app.processEvents()


# Archive silo scroll is remembered across a round trip to a normal silo.
switch(0, True, archive=True)
scroll_to(300)
if sb() < 200:
    problems.append("archive-scroll-not-applied:%d" % sb())
switch(0, True)                       # leave archive -> normal slot 0
if sb() > 50:
    problems.append("normal-after-archive-not-top:%d" % sb())
switch(0, True, archive=True)         # back to archive
if sb() < 200:
    problems.append("archive-scroll-not-restored:%d" % sb())

# Two archive silos keep independent scroll offsets.
switch(1, True, archive=True)
scroll_to(150)
switch(0, True, archive=True)
if sb() < 200:
    problems.append("archive0-lost:%d" % sb())
switch(1, True, archive=True)
if sb() < 100:
    problems.append("archive1-lost:%d" % sb())

# Rapid switching with pending Qt events: the newest restore must win.
for _ in range(6):
    switch(0, True)
    scroll_to(450)
    switch(1, True)
    scroll_to(100)
    if sb() > 200:
        problems.append("rapid-slot1-stale:%d" % sb())
    switch(0, True)
    if sb() < 300:
        problems.append("rapid-slot0-stale:%d" % sb())
app.processEvents()

if problems:
    print("FAIL " + " ".join(problems))
    sys.stdout.flush()
    os._exit(1)
print("OK")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""



def test_remember_scroll_contract():
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env, capture_output=True, text=True,
        cwd=os.path.dirname(__file__),
    )
    assert proc.returncode == 0, (
        f"remember-scroll contract failed: {proc.stdout} {proc.stderr}")
    assert "OK" in proc.stdout


def test_remember_scroll_archive_and_rapid_switching():
    """T-1462: archive silos and rapid switching must restore the viewport.

    The pre-existing script only asserted textCursor().position(), which is
    not the viewport: a caret at 0 with the document scrolled 400 px reads as
    "position 0" both when the scroll was remembered and when it was lost.
    verticalScrollBar().value() is the evidence.
    """
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "../src"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT_ARCHIVE],
        env=env, capture_output=True, text=True,
        cwd=os.path.dirname(__file__),
    )
    assert proc.returncode == 0, (
        f"archive/rapid scroll contract failed: {proc.stdout} {proc.stderr}")
    assert "OK" in proc.stdout


def test_migration_inverts_legacy_silo_home():
    from fastprompter.core.default_profile import migrate_silo_scroll_settings

    # "Silos at Start" ON meant never remember -> the new switch is OFF.
    d = {"silo_home": "True"}
    assert migrate_silo_scroll_settings(d) is True
    assert d["silo_remember_scroll"] == "False"
    assert "silo_home" not in d
    assert d["silo_remember_scroll_migrated"] == "True"

    # OFF (memory won) -> the new switch is ON.
    d = {"silo_home": "False"}
    migrate_silo_scroll_settings(d)
    assert d["silo_remember_scroll"] == "True"

    # A profile with neither key keeps the shipped default and is marked.
    d = {}
    migrate_silo_scroll_settings(d)
    assert d.get("silo_remember_scroll", "True") == "True"
    assert d["silo_remember_scroll_migrated"] == "True"

    # Idempotent: a later explicit choice is never inverted again.
    d = {"silo_remember_scroll": "False", "silo_remember_scroll_migrated": "True"}
    assert migrate_silo_scroll_settings(d) is False
    assert d["silo_remember_scroll"] == "False"

    # No legacy key: an existing explicit value is never clobbered.
    d = {"silo_remember_scroll": "False"}
    assert migrate_silo_scroll_settings(d) is True
    assert d["silo_remember_scroll"] == "False"
