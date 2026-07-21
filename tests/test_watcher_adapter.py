"""Tests for fastprompter.core.watcher.adapter.

The config is the extension point — a new agent is a block of TOML, not a
patch. So the thing under test is mostly resilience: a typo in one entry must
cost that entry and nothing else.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.adapter import (  # noqa: E402
    DEFAULT_LIMITS,
    Adapter,
    describe,
    load_adapters,
    parse_adapters,
    usable_adapters,
)
from fastprompter.core.watcher.probes import IDLE, Probe, _OptionalProbe  # noqa: E402


def _shipped_example():
    """The example config, as an installed copy would see it.

    Deliberately NOT skipped when absent. It started life under .saipen,
    which is gitignored, so these tests silently skipped in every clean
    checkout - guarding the shipped defaults exactly nowhere. Missing is now
    a failure, because missing is the bug.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "src", "fastprompter",
                        "core", "watcher", "adapters.example.toml")
    assert os.path.isfile(path), (
        "the example config must ship beside the code, not in an ignored dir")
    return path


GOOD = """
[[agent]]
name = "claude-code"
settle_ms = 2500
submit = "enter"
skill_format = "/{skill} {text}"

  [[agent.probe]]
  kind = "file"
  glob = "~/.claude/projects/{project}/*.jsonl"
  quiet_ms = 2000

[[agent]]
name = "freebuff"

  [[agent.probe]]
  kind = "sqlite"
  path = "{project}/.freebuff/state.db"

[limits]
min_gap_ms = 6000
"""


class Always(Probe):
    """A probe that is readable and never changes, so it settles to idle."""

    kind = "always"

    def _read(self):
        return "unchanging"


# ----------------------------------------------------------------- parsing

def test_a_good_config_yields_its_agents():
    adapters, limits, errors = parse_adapters(GOOD, project="proj")
    assert [a.name for a in adapters] == ["claude-code", "freebuff"]
    assert errors == []
    assert limits["min_gap_ms"] == 6000


def test_untouched_limits_keep_their_defaults():
    _adapters, limits, _errors = parse_adapters(GOOD)
    assert limits["max_sends"] == DEFAULT_LIMITS["max_sends"]
    assert limits["dry_run_new"] is True


def test_the_defaults_do_not_interrupt_the_user():
    """These two are the whole reason the feature is worth having."""
    assert DEFAULT_LIMITS["confirm_first"] is False
    assert DEFAULT_LIMITS["allow_focus_steal"] is False


def test_the_project_placeholder_is_filled_in():
    adapters, _limits, _errors = parse_adapters(GOOD, project="myproj")
    assert "myproj" in adapters[0].probes[0].pattern
    assert "{project}" not in adapters[1].probes[0].path


def test_an_empty_config_is_not_an_error():
    adapters, limits, errors = parse_adapters("")
    assert adapters == [] and errors == []
    assert limits == DEFAULT_LIMITS


# ------------------------------------------------------- error containment

def test_a_broken_entry_does_not_cost_the_others():
    """The point of config-driven agents is that a typo in one is survivable."""
    adapters, _limits, errors = parse_adapters("""
[[agent]]
name = ""

[[agent]]
name = "survivor"
  [[agent.probe]]
  kind = "file"
  glob = "x"
""")
    assert [a.name for a in adapters] == ["survivor"]
    assert len(errors) == 1 and "name" in errors[0]


def test_unparsable_toml_reports_instead_of_raising():
    adapters, limits, errors = parse_adapters("[[agent]\nname = ")
    assert adapters == []
    assert limits == DEFAULT_LIMITS
    assert errors and "parse" in errors[0]


def test_a_bad_probe_disables_only_its_own_agent():
    adapters, _limits, errors = parse_adapters("""
[[agent]]
name = "half-broken"
  [[agent.probe]]
  kind = "nonsense"
""")
    ok, reason = adapters[0].supported()
    assert ok is False
    assert "known probe kind" in reason
    assert errors == [], "an unknown probe kind is the adapter's problem, not the file's"


def test_a_bad_blocker_pattern_disables_the_adapter_not_the_app():
    adapter = Adapter("x", probes=[Always()], blocker_pattern="(unclosed")
    ok, reason = adapter.supported()
    assert ok is False and "blocker_pattern" in reason


def test_an_unknown_limit_is_reported_and_ignored():
    _adapters, limits, errors = parse_adapters("[limits]\nmin_gap_ms = 1\nfoo = 2")
    assert limits["min_gap_ms"] == 1
    assert "foo" not in limits
    assert errors and "foo" in errors[0]


def test_a_nonsense_settle_falls_back_instead_of_crashing():
    assert Adapter("x", settle_ms="soon").settle_ms == 2500
    assert Adapter("x", settle_ms=-5).settle_ms == 0


# --------------------------------------------------------------- readiness

def test_an_adapter_with_no_probes_is_not_usable():
    """It knows nothing about the agent, and knowing nothing must never be
    what lets a prompt out."""
    ok, reason = Adapter("blind").supported()
    assert ok is False
    assert "no probes" in reason


def test_a_missing_dependency_is_named_not_hidden():
    adapter = Adapter("needs-psutil",
                      probes=[_OptionalProbe("process", "psutil")])
    ok, reason = adapter.supported()
    assert ok is False
    assert "psutil" in reason


def test_asking_whether_it_is_ready_does_not_disturb_the_quiet_window():
    """The trap this replaced: readiness answered by poll(0.0) stamped
    _changed_at in the past, so the next real poll read as idle at once and
    would have fired a prompt into a working agent."""
    probe = Always(quiet_ms=5000)
    adapter = Adapter("x", probes=[probe])

    adapter.supported()
    adapter.supported()

    assert probe._changed_at is None, "readiness must not stamp the clock"
    # first real poll: the token is new, so it is busy and starts settling
    assert probe.poll(1000.0)[0] != IDLE
    assert probe.poll(1002.0)[0] != IDLE, "still inside the 5s window"
    assert probe.poll(1006.0)[0] == IDLE


def test_a_probe_that_raises_on_readiness_is_treated_as_unusable():
    class Rude(Probe):
        kind = "rude"

        def supported(self):
            raise RuntimeError("boom")

        def _read(self):
            return "x"

    ok, reason = Adapter("x", probes=[Rude()]).supported()
    assert ok is False and "boom" in reason


def test_usable_filters_out_the_disabled_and_the_broken():
    ready = Adapter("ready", probes=[Always()])
    off = Adapter("off", probes=[Always()], enabled=False)
    broken = Adapter("broken")
    assert [a.name for a in usable_adapters([ready, off, broken])] == ["ready"]


def test_describe_explains_every_refusal():
    """'My agent is not in the list' must be answerable without opening the
    config."""
    rows = describe([
        Adapter("ready", probes=[Always()]),
        Adapter("off", probes=[Always()], enabled=False),
        Adapter("blind"),
    ])
    assert rows[0] == ("ready", True, "ready")
    assert rows[1][1] is False and "disabled" in rows[1][2]
    assert rows[2][1] is False and "no probes" in rows[2][2]


# ---------------------------------------------------------------- blocking

def test_a_permission_prompt_blocks_the_send():
    """A prompt waiting for the user is silent, so the probes call it idle.
    This is the override that stops a queued line landing on one."""
    adapter = Adapter("x", blocker_pattern=r"(?i)do you want to proceed")
    assert adapter.blocked("Do you want to proceed? (y/n)") is True
    assert adapter.blocked("all done") is False


def test_no_pattern_blocks_nothing():
    assert Adapter("x").blocked("Do you want to proceed?") is False
    assert Adapter("x", blocker_pattern="never").blocked("") is False


# ----------------------------------------------------------------- skills

def test_an_agent_without_a_skill_format_says_so():
    """Absent means the agent has no skills — an item carrying one is
    skipped rather than sent silently stripped of it."""
    adapters, _limits, _errors = parse_adapters(
        '[[agent]]\nname = "plain"\n')
    assert adapters[0].skill_format is None


def test_the_skill_format_is_per_agent():
    adapters, _limits, _errors = parse_adapters(GOOD)
    assert adapters[0].skill_format == "/{skill} {text}"


# ------------------------------------------------------------------ files

def test_loading_falls_back_to_the_shipped_example(tmp_path):
    example = tmp_path / "adapters.example.toml"
    example.write_text(GOOD, encoding="utf-8")
    adapters, _limits, errors = load_adapters(
        path=str(tmp_path / "absent.toml"), fallback=str(example))
    assert [a.name for a in adapters] == ["claude-code", "freebuff"]
    assert errors == []


def test_the_users_file_wins_over_the_example(tmp_path):
    (tmp_path / "mine.toml").write_text(
        '[[agent]]\nname = "mine"\n', encoding="utf-8")
    (tmp_path / "example.toml").write_text(GOOD, encoding="utf-8")
    adapters, _limits, _errors = load_adapters(
        path=str(tmp_path / "mine.toml"),
        fallback=str(tmp_path / "example.toml"))
    assert [a.name for a in adapters] == ["mine"]


def test_no_config_at_all_is_reported_not_crashed():
    adapters, limits, errors = load_adapters(path=None, fallback=None)
    assert adapters == []
    assert limits == DEFAULT_LIMITS
    assert errors == ["no adapters.toml found"]


def test_the_shipped_example_actually_parses():
    """It is the file every user copies. A broken one teaches broken syntax."""
    example = _shipped_example()
    with open(example, encoding="utf-8") as fh:
        adapters, _limits, errors = parse_adapters(fh.read(), project="proj")
    assert errors == [], f"the shipped example does not parse cleanly: {errors}"
    assert adapters, "the example should describe at least one agent"


def test_the_shipped_example_does_not_interrupt_the_user():
    """Config that ships with confirm_first on would undo the silent default
    for everyone who copies it."""
    example = _shipped_example()
    with open(example, encoding="utf-8") as fh:
        _adapters, limits, _errors = parse_adapters(fh.read())
    assert limits["confirm_first"] is False
    assert limits["allow_focus_steal"] is False
