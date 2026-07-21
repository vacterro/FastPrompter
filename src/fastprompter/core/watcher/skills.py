"""Skills: the token prepended to a queued prompt.

Discovered from the skill folders an agent already reads, then curated by
hand — because discovery only sees what is installed locally. On this
machine that is two skills; the longer palettes people actually use come
from a tool's own registry, which nothing here can enumerate. So a rescan
may ADD entries and may never remove a curated one.

The skill is stored beside the prompt and composed at send time (see
queue.QueueItem.compose), so changing it is never a retype.

Qt-free: discovery and merging are the parts worth testing without a GUI.
"""

from __future__ import annotations

import glob
import os

# Where agents keep skills: one folder per skill, each with a SKILL.md whose
# frontmatter carries `name` and `description`. Verified 21.07.
DEFAULT_PATHS = (
    "~/.claude/skills/*/SKILL.md",
    "{project}/.claude/skills/*/SKILL.md",
)


class Skill:
    """One chip: what to invoke, and what to say about it."""

    __slots__ = ("name", "description", "source")

    def __init__(self, name, description="", source="discovered"):
        self.name = (name or "").lstrip("/").strip()
        self.description = (description or "").strip()
        self.source = source        # "discovered" | "manual"

    def __eq__(self, other):
        return isinstance(other, Skill) and other.name == self.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"Skill({self.name!r}, {self.source})"

    def to_dict(self):
        return {"name": self.name,
                "description": self.description,
                "source": self.source}

    @classmethod
    def from_dict(cls, d):
        if isinstance(d, str):
            return cls(d, source="manual") if d.strip() else None
        if not isinstance(d, dict):
            return None
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        return cls(name, d.get("description", ""), d.get("source", "manual"))


def parse_frontmatter(text):
    """`name` and `description` out of a SKILL.md header.

    Deliberately not a YAML parser: the frontmatter here is two flat keys,
    and `description` is routinely a folded block spanning several indented
    lines. Pulling in a parser for that would be a dependency for nothing.
    """
    if not isinstance(text, str) or not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    body = text[3:end]

    out = {}
    key = None
    for raw in body.splitlines():
        if not raw.strip():
            continue
        if raw[:1] not in (" ", "\t") and ":" in raw:
            key, _, value = raw.partition(":")
            key = key.strip()
            value = value.strip()
            # `description: >` opens a folded block; the value is what follows
            out[key] = "" if value in (">", "|", ">-", "|-") else value
        elif key:
            out[key] = (out.get(key, "") + " " + raw.strip()).strip()
    return out


def discover(paths=None, project=None):
    """Every skill found on disk, in name order."""
    # `None` means "use the defaults"; an EMPTY list means "scan nothing".
    # `paths or DEFAULT_PATHS` conflated the two and quietly scanned the real
    # ~/.claude/skills when a caller asked for no scan at all.
    if paths is None:
        paths = DEFAULT_PATHS
    found = {}
    for pattern in paths:
        pattern = pattern.replace("{project}", project or "")
        if "{project}" in pattern or (project is None and "{project}" in pattern):
            continue
        expanded = os.path.expanduser(os.path.expandvars(pattern))
        for path in glob.glob(expanded):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    head = fh.read(4096)
            except OSError:
                continue          # unreadable file: skip it, not the scan
            meta = parse_frontmatter(head)
            name = meta.get("name") or os.path.basename(os.path.dirname(path))
            if not name:
                continue
            skill = Skill(name, meta.get("description", ""), "discovered")
            found.setdefault(skill.name, skill)
    return [found[k] for k in sorted(found)]


def merge(discovered, extra=(), hidden=()):
    """The palette: what was found, plus what was added, minus what was hidden.

    Discovery may add and may never remove: a chip typed in by hand refers to
    a skill this machine cannot see, and dropping it on the next scan would
    delete the user's own work.
    """
    hidden_names = {(h or "").lstrip("/").strip() for h in (hidden or ())}
    palette = []
    seen = set()

    for skill in list(extra or ()) + list(discovered or ()):
        if isinstance(skill, str):
            skill = Skill(skill, source="manual")
        if skill is None or not skill.name:
            continue
        if skill.name in seen or skill.name in hidden_names:
            continue
        seen.add(skill.name)
        palette.append(skill)
    return palette


def load_palette(data, project=None, paths=None):
    """The palette from stored settings, rescanned.

    `extra` holds hand-added chips and `hidden` the ones dismissed; both
    survive a rescan, which is the whole point of keeping them separately.
    """
    extra = [Skill.from_dict(e) for e in (data.get("watcher_skills_extra") or [])]
    extra = [e for e in extra if e is not None]
    hidden = data.get("watcher_skills_hidden") or []
    return merge(discover(paths, project), extra, hidden)


def save_palette(data, palette):
    """Persist only what a rescan cannot reproduce."""
    data["watcher_skills_extra"] = [
        s.to_dict() for s in palette if s.source == "manual"]
    return data


def usable(skill_name, skill_format):
    """Can this target invoke that skill?

    A target with no `skill_format` has no skills at all. Its chips are
    hidden rather than greyed, and an item already carrying a skill is
    skipped with a reason instead of being sent stripped — a prompt without
    its skill is a different request from the one that was queued.
    """
    if not skill_name:
        return True               # a plain prompt goes anywhere
    return bool(skill_format)
