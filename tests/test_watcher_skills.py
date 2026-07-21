"""Tests for fastprompter.core.watcher.skills — the skill palette."""

import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.core.watcher.skills import (  # noqa: E402
    Skill,
    discover,
    load_palette,
    merge,
    parse_frontmatter,
    save_palette,
    usable,
)


def make_skill_tree(entries):
    """A folder of skills: {name: SKILL.md text}. Returns the glob for it."""
    root = tempfile.mkdtemp()
    for name, text in entries.items():
        folder = os.path.join(root, name)
        os.makedirs(folder, exist_ok=True)
        with io.open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    return os.path.join(root, "*", "SKILL.md")


# ------------------------------------------------------------ frontmatter

def test_frontmatter_reads_name_and_description():
    meta = parse_frontmatter("---\nname: review\ndescription: Look it over\n---\n# body")
    assert meta["name"] == "review"
    assert meta["description"] == "Look it over"


def test_a_folded_description_is_joined():
    """`description: >` spans several indented lines - which is exactly how
    the real saipen skill is written."""
    text = (
        "---\n"
        "name: saipen\n"
        "description: >\n"
        "  SAIPEN (v7). Trigger on \"saipen set\",\n"
        "  and subcommands.\n"
        "---\n"
    )
    meta = parse_frontmatter(text)
    assert meta["name"] == "saipen"
    assert "Trigger on" in meta["description"]
    assert "subcommands" in meta["description"]


def test_a_file_without_frontmatter_yields_nothing():
    assert parse_frontmatter("# just a heading") == {}
    assert parse_frontmatter("") == {}
    assert parse_frontmatter(None) == {}


def test_unterminated_frontmatter_is_not_a_crash():
    assert parse_frontmatter("---\nname: x\n") == {}


# --------------------------------------------------------------- discovery

def test_discovery_finds_skills_and_sorts_them():
    pattern = make_skill_tree({
        "review": "---\nname: review\ndescription: Look it over\n---\n",
        "alpha": "---\nname: alpha\n---\n",
    })
    found = discover([pattern])
    assert [s.name for s in found] == ["alpha", "review"]
    assert found[1].description == "Look it over"
    assert all(s.source == "discovered" for s in found)


def test_the_folder_name_is_the_fallback():
    """A SKILL.md with no name is still a skill - the folder names it."""
    pattern = make_skill_tree({"fallback-name": "no frontmatter here"})
    assert [s.name for s in discover([pattern])] == ["fallback-name"]


def test_discovery_of_nothing_is_empty_not_an_error():
    assert discover([os.path.join(tempfile.mkdtemp(), "*", "SKILL.md")]) == []


def test_a_project_placeholder_without_a_project_is_skipped():
    assert discover(["{project}/.claude/skills/*/SKILL.md"]) == []


def test_a_project_placeholder_is_expanded_when_given():
    root = tempfile.mkdtemp()
    folder = os.path.join(root, ".claude", "skills", "local")
    os.makedirs(folder)
    with io.open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: local\n---\n")
    found = discover(["{project}/.claude/skills/*/SKILL.md"], project=root)
    assert [s.name for s in found] == ["local"]


# ------------------------------------------------------------------ merge

def test_hand_added_chips_come_first_and_survive():
    """Discovery may add and may never remove: a hand-typed chip names a
    skill this machine cannot see, and dropping it would delete the user's
    own work."""
    discovered = [Skill("review", source="discovered")]
    palette = merge(discovered, extra=[Skill("cavecrew", source="manual")])
    assert [s.name for s in palette] == ["cavecrew", "review"]
    assert palette[0].source == "manual"


def test_a_hidden_skill_is_left_out():
    palette = merge([Skill("a"), Skill("b")], hidden=["b"])
    assert [s.name for s in palette] == ["a"]


def test_hiding_tolerates_a_leading_slash():
    palette = merge([Skill("a")], hidden=["/a"])
    assert palette == []


def test_a_duplicate_is_listed_once_and_the_manual_one_wins():
    palette = merge([Skill("review", "found", "discovered")],
                    extra=[Skill("review", "mine", "manual")])
    assert len(palette) == 1
    assert palette[0].description == "mine"


def test_plain_strings_are_accepted_as_chips():
    palette = merge([], extra=["quick"])
    assert [s.name for s in palette] == ["quick"]
    assert palette[0].source == "manual"


def test_junk_in_extra_does_not_break_the_palette():
    palette = merge([Skill("a")], extra=[None, "", Skill("")])
    assert [s.name for s in palette] == ["a"]


# ------------------------------------------------------------ persistence

def test_only_the_hand_added_chips_are_stored():
    """A rescan reproduces the discovered ones; storing them too would let a
    stale copy outlive the skill it names."""
    data = {}
    save_palette(data, [Skill("found", source="discovered"),
                        Skill("typed", source="manual")])
    assert [e["name"] for e in data["watcher_skills_extra"]] == ["typed"]


def test_the_palette_round_trips_through_settings():
    pattern = make_skill_tree({"review": "---\nname: review\n---\n"})
    data = {}
    save_palette(data, [Skill("cavecrew", source="manual")])
    data["watcher_skills_hidden"] = []

    palette = load_palette(data, paths=[pattern])
    assert [s.name for s in palette] == ["cavecrew", "review"]


def test_a_hidden_chip_stays_hidden_after_a_rescan():
    pattern = make_skill_tree({"review": "---\nname: review\n---\n"})
    data = {"watcher_skills_hidden": ["review"]}
    assert load_palette(data, paths=[pattern]) == []


def test_corrupt_stored_chips_are_skipped():
    data = {"watcher_skills_extra": [None, 42, {"no_name": 1}, {"name": "ok"}]}
    palette = load_palette(data, paths=[])
    assert [s.name for s in palette] == ["ok"]


# ------------------------------------------------------------ usability

def test_a_plain_prompt_goes_to_any_target():
    assert usable("", None) is True
    assert usable(None, None) is True


def test_a_skill_needs_a_target_that_can_invoke_it():
    """A target with no skill_format has no skills. The item is skipped with
    a reason rather than sent stripped - a prompt without its skill is a
    different request from the one that was queued."""
    assert usable("saipen", "/{skill} {text}") is True
    assert usable("saipen", None) is False
    assert usable("saipen", "") is False


def test_a_leading_slash_is_never_stored_twice():
    """The chip may be written either way; the format supplies the slash."""
    assert Skill("/saipen").name == "saipen"
    assert Skill("saipen").name == "saipen"
