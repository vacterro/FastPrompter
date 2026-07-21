"""Tests for fastprompter.core.watcher.probes — idle detection.

The clock is an argument everywhere, so a quiet window is tested by moving
`now` rather than by sleeping.
"""

import io
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.probes import (  # noqa: E402
    BUSY,
    IDLE,
    UNSUPPORTED,
    FileProbe,
    SqliteProbe,
    build,
    combine,
    process_probe,
    window_probe,
)


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def touch_session(folder, name="s.jsonl", lines=()):
    path = os.path.join(folder, name)
    write(path, "\n".join(json.dumps(x) for x in lines) + ("\n" if lines else ""))
    return path


# --------------------------------------------------------------- the window

def test_a_changing_file_is_busy():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "a.log")
    write(path, "one")
    probe = FileProbe(os.path.join(folder, "*.log"), quiet_ms=1000)

    assert probe.poll(0.0)[0] == BUSY, "the first read is always busy"
    write(path, "one two")
    assert probe.poll(1.0)[0] == BUSY, "it changed, so the window restarts"


def test_it_goes_idle_once_the_window_passes():
    folder = tempfile.mkdtemp()
    write(os.path.join(folder, "a.log"), "one")
    probe = FileProbe(os.path.join(folder, "*.log"), quiet_ms=1000)

    probe.poll(0.0)
    assert probe.poll(0.5)[0] == BUSY, "half a window is not enough"
    assert probe.poll(1.0)[0] == IDLE


def test_a_change_restarts_the_window():
    """A pause mid-turn must not be allowed to accumulate into idleness."""
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "a.log")
    write(path, "one")
    probe = FileProbe(os.path.join(folder, "*.log"), quiet_ms=1000)

    probe.poll(0.0)
    probe.poll(0.9)
    write(path, "one two")
    assert probe.poll(1.0)[0] == BUSY
    assert probe.poll(1.9)[0] == BUSY, "the clock restarted at the change"
    assert probe.poll(2.0)[0] == IDLE


def test_a_missing_file_is_busy_not_idle():
    """Uncertainty is not idleness: nothing to read must never release a
    prompt into an agent."""
    probe = FileProbe(os.path.join(tempfile.mkdtemp(), "*.log"), quiet_ms=0)
    state, reason = probe.poll(0.0)
    assert state == BUSY
    assert "nothing to read" in reason


def test_a_probe_that_raises_is_busy_not_fatal():
    probe = FileProbe("whatever", quiet_ms=0)
    probe._read = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    state, reason = probe.poll(0.0)
    assert state == BUSY
    assert "boom" in reason


def test_the_newest_file_is_the_one_watched():
    folder = tempfile.mkdtemp()
    old = os.path.join(folder, "old.jsonl")
    new = os.path.join(folder, "new.jsonl")
    write(old, "old")
    write(new, "new")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    probe = FileProbe(os.path.join(folder, "*.jsonl"))
    assert probe._path() == new


# ------------------------------------------------------- the tail condition

# Measured on a real 2157-line Claude Code session, 21.07. Content types are
# assistant / user / attachment / system; everything here is session
# metadata appended AFTER a turn. last-prompt and queue-operation were NOT in
# the first guess at this list - the live file found them.
CLAUDE_IGNORED = ("custom-title", "ai-title", "mode", "last-prompt",
                  "queue-operation", "summary")


def test_a_tool_pause_is_not_the_end_of_a_turn():
    """The file goes quiet while a tool runs, which looks exactly like being
    finished - this is the condition that tells them apart."""
    folder = tempfile.mkdtemp()
    touch_session(folder, lines=[
        {"type": "user"},
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "tool_use"},
    ])
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"},
                      ignore_types=CLAUDE_IGNORED)
    probe.poll(0.0)
    state, reason = probe.poll(1.0)
    assert state == BUSY
    assert "tool_use" in reason


def test_a_finished_turn_is_idle():
    folder = tempfile.mkdtemp()
    touch_session(folder, lines=[
        {"type": "user"},
        {"type": "assistant", "message": {"role": "assistant"}},
    ])
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"},
                      ignore_types=CLAUDE_IGNORED)
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == IDLE


def test_trailing_metadata_does_not_hide_the_finished_turn():
    """Measured on a real session file: the tail is often custom-title /
    ai-title / mode, so "the last line" is the wrong thing to look at."""
    folder = tempfile.mkdtemp()
    touch_session(folder, lines=[
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "custom-title", "customTitle": "x"},
        {"type": "ai-title", "aiTitle": "y"},
        {"type": "mode", "mode": "full"},
    ])
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"},
                      ignore_types=CLAUDE_IGNORED)
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == IDLE


def test_the_real_metadata_block_does_not_hide_a_finished_turn():
    """The exact tail shape seen on a live session: a finished assistant turn
    followed by four metadata lines."""
    folder = tempfile.mkdtemp()
    touch_session(folder, lines=[
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "last-prompt", "lastPrompt": "..."},
        {"type": "custom-title", "customTitle": "x"},
        {"type": "ai-title", "aiTitle": "y"},
        {"type": "mode", "mode": "full"},
        {"type": "queue-operation", "op": "add"},
    ])
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"},
                      ignore_types=CLAUDE_IGNORED)
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == IDLE


def test_a_user_turn_at_the_tail_means_the_agent_has_not_answered():
    folder = tempfile.mkdtemp()
    touch_session(folder, lines=[
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "user", "message": {"role": "user"}},
    ])
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"},
                      ignore_types=CLAUDE_IGNORED)
    probe.poll(0.0)
    state, reason = probe.poll(1.0)
    assert state == BUSY
    assert "user" in reason


def test_unparseable_tail_lines_are_stepped_over():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "s.jsonl")
    write(path, json.dumps({"type": "assistant"}) + "\n{ this is not json\n")
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"})
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == IDLE


def test_a_file_with_no_readable_entry_stays_busy():
    folder = tempfile.mkdtemp()
    write(os.path.join(folder, "s.jsonl"), "not json at all\n")
    probe = FileProbe(os.path.join(folder, "*.jsonl"), quiet_ms=0,
                      last_line_json={"type": "assistant"})
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == BUSY


# ------------------------------------------------------------------ sqlite

def test_a_written_database_is_busy_then_settles():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "desktop.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.commit()
    conn.close()

    probe = SqliteProbe(path, quiet_ms=1000)
    assert probe.poll(0.0)[0] == BUSY
    assert probe.poll(1.0)[0] == IDLE


def test_max_rowid_notices_a_new_row():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "d.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a')")
    conn.commit()

    probe = SqliteProbe(path, quiet_ms=0, watch="max_rowid", table="t")
    probe.poll(0.0)
    assert probe.poll(1.0)[0] == IDLE

    conn.execute("INSERT INTO t VALUES ('b')")
    conn.commit()
    conn.close()
    assert probe.poll(2.0)[0] == BUSY, "a new row means it is working"


def test_a_missing_database_is_busy():
    probe = SqliteProbe(os.path.join(tempfile.mkdtemp(), "gone.db"), quiet_ms=0)
    assert probe.poll(0.0)[0] == BUSY


def test_max_rowid_without_a_table_is_busy():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "d.db")
    sqlite3.connect(path).close()
    probe = SqliteProbe(path, quiet_ms=0, watch="max_rowid", table="")
    assert probe.poll(0.0)[0] == BUSY


# ------------------------------------------------------------- unsupported

def test_a_probe_without_its_dependency_says_so():
    """It must not degrade to idle: a missing package would then look like a
    finished agent, which is the one failure this design cannot have."""
    for probe in (window_probe(title_match="x"), process_probe()):
        state, reason = probe.poll(0.0)
        assert state == UNSUPPORTED
        assert "not installed" in reason
        assert state != IDLE


def test_an_unknown_kind_is_unsupported():
    state, reason = build({"kind": "telepathy"}).poll(0.0)
    assert state == UNSUPPORTED
    assert "known probe kind" in reason


def test_a_non_dict_spec_is_unsupported():
    assert build("nonsense").poll(0.0)[0] == UNSUPPORTED


# ----------------------------------------------------------------- combine

def test_all_probes_must_agree():
    folder = tempfile.mkdtemp()
    write(os.path.join(folder, "a.log"), "x")
    quiet = FileProbe(os.path.join(folder, "*.log"), quiet_ms=0)
    noisy = FileProbe(os.path.join(tempfile.mkdtemp(), "*.log"), quiet_ms=0)

    quiet.poll(0.0)
    assert combine([quiet], 1.0)[0] is True
    assert combine([quiet, noisy], 1.0)[0] is False


def test_no_probes_is_not_idle():
    """An adapter that describes no signal knows nothing about the agent,
    and knowing nothing must never be what lets a prompt out."""
    idle, reasons = combine([], 0.0)
    assert idle is False
    assert "no probes" in reasons[0]


def test_an_unsupported_probe_blocks_the_whole_adapter():
    folder = tempfile.mkdtemp()
    write(os.path.join(folder, "a.log"), "x")
    good = FileProbe(os.path.join(folder, "*.log"), quiet_ms=0)
    good.poll(0.0)
    assert combine([good, process_probe()], 1.0)[0] is False


# ------------------------------------------------------------------- build

def test_build_expands_the_project_placeholder():
    probe = build({"kind": "sqlite", "path": "{project}/.freebuff/desktop.db"},
                  project="V:/proj")
    assert probe.path == "V:/proj/.freebuff/desktop.db"


def test_build_carries_the_claude_settings_through():
    probe = build({
        "kind": "file",
        "glob": "~/.claude/projects/*/*.jsonl",
        "quiet_ms": 2000,
        "last_line_json": {"type": "assistant"},
        "ignore_types": ["custom-title", "mode"],
    })
    assert isinstance(probe, FileProbe)
    assert probe.quiet_ms == 2000
    assert probe.last_line_json == {"type": "assistant"}
    assert "mode" in probe.ignore_types
