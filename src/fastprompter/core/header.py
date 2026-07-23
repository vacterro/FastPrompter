"""Ctrl+E (header) — the text half, with no Qt in it.

Same shape as core/ctrlw.py and for the same reason: the settings page and
the editor must build the header from one function, or the preview goes on
promising a layout the editor stopped producing.

What Ctrl+E used to hardcode, and now reads from settings:
  the --- rule under the title  (was: always)
  the gap under the rule        (was: always two empty lines)
  the bullet left ready below   (was: always "• ")
  the alignment                 (was: a centre on/off flag)
  the timestamp on repeats      (was: first header in the silo only)
"""

CURSOR = "│"

ALIGNMENTS = ("left", "center", "right", "justify")

DEFAULTS = {
    "ctrl_e_format": "{text} ({time})",
    "ctrl_e_rule": "True",
    "ctrl_e_gap_after": "2",
    "ctrl_e_bullet": "True",
    "ctrl_e_bullet_char": "•",
    # Below the caret: room to keep writing, then an optional closing rule.
    "ctrl_e_gap_below": "0",
    "ctrl_e_rule_below": "False",
    "ctrl_e_gap_bottom": "0",
    "ctrl_e_align": "left",
    # Per-role alignment. Empty means "same as the title", which is what
    # keeps a settings file written before this existed behaving as it did.
    "ctrl_e_align_rule": "",
    "ctrl_e_align_bullet": "left",
    "ctrl_e_stamp_every": "False",
}

# Which lines of the block can be aligned on their own, in block order.
ALIGNABLE_ROLES = ("title", "rule", "bullet")

# The sample the preview presses Ctrl+E on.
SAMPLE_TITLE = "Design notes"
SAMPLE_TAIL = "an existing thought"


def read_settings(data):
    """Pull the Ctrl+E settings out of the app's data dict, defaults filled.

    ``ctrl_e_center`` is the old boolean flag. It is read only when no
    explicit alignment has been stored, so an upgrade keeps the centring the
    user already had instead of silently straightening it out.
    """
    def _s(key):
        v = data.get(key, DEFAULTS[key])
        return DEFAULTS[key] if v is None else str(v)

    align = str(data.get("ctrl_e_align", "") or "")
    if align not in ALIGNMENTS:
        align = "center" if str(data.get("ctrl_e_center", "False")) == "True" else "left"
    def _count(key, default):
        try:
            return max(0, min(6, int(_s(key))))
        except (TypeError, ValueError):
            return default

    gap = _count("ctrl_e_gap_after", 2)
    bullet_char = _s("ctrl_e_bullet_char")
    def _role_align(key):
        # "" is meaningful: it means "follow the title", so an unset value
        # cannot be defaulted to a direction here
        v = str(data.get(key, DEFAULTS[key]) or "")
        return v if v in ALIGNMENTS else ""

    return {
        "align_rule": _role_align("ctrl_e_align_rule"),
        "align_bullet": _role_align("ctrl_e_align_bullet"),
        "format": _s("ctrl_e_format") or DEFAULTS["ctrl_e_format"],
        "rule": _s("ctrl_e_rule") == "True",
        "gap_after": gap,
        "gap_below": _count("ctrl_e_gap_below", 0),
        "rule_below": _s("ctrl_e_rule_below") == "True",
        "gap_bottom": _count("ctrl_e_gap_bottom", 0),
        "bullet": _s("ctrl_e_bullet") == "True",
        "bullet_char": bullet_char if bullet_char.strip() else "•",
        "align": align,
        "stamp_every": _s("ctrl_e_stamp_every") == "True",
    }


def header_line(template, text, time_str, state):
    """The title line itself, always a level-1 header.

    Ctrl+E lines start with "# " because the editor's highlighter is what
    makes them bold and gold; a template that already opens with it is left
    alone rather than given a second one.
    """
    line = (template.replace("{text}", text)
            .replace("{time}", time_str)
            .replace("{state}", state))
    return line if line.startswith("# ") else f"# {line}"


def build_block(cfg, title_line):
    """Every line Ctrl+E leaves behind, title first.

    Returned as a list so the caller decides how to splice it in; the caret
    belongs on the last line when a bullet was asked for, and on the title
    otherwise (there is nothing below worth landing on).
    """
    return [line for line, _role in build_block_roles(cfg, title_line)]


def build_block_roles(cfg, title_line):
    """The same lines, each paired with what it is: title / rule / gap /
    bullet.

    Alignment is chosen per role - the user asked to say which lines are
    centred and which stay left - so the writer needs to know which block is
    which without re-parsing the text it just wrote.
    """
    out = [(title_line, "title")]
    if cfg["rule"]:
        out.append(("---", "rule"))
    out.extend([("", "gap")] * cfg["gap_after"])
    if cfg["bullet"]:
        out.append((cfg["bullet_char"] + " ", "bullet"))
    # Everything below the caret: room to keep writing, and an optional
    # closing rule that shuts the section off from whatever follows.
    out.extend([("", "gap")] * cfg["gap_below"])
    if cfg["rule_below"]:
        out.append(("---", "rule"))
        out.extend([("", "gap")] * cfg["gap_bottom"])
    return out


def align_of(cfg, role):
    """The alignment stored for one role, falling back to the title's.

    A gap line is never aligned: it holds no text, and giving it an
    alignment only leaks that alignment into whatever gets typed there.
    """
    if role == "gap":
        return "left"
    return cfg.get(f"align_{role}") or cfg["align"]


def caret_line(cfg):
    """Index into build_block's list where the caret ends up.

    The bullet is no longer the last line — anything configured below it
    (gap, closing rule) comes after — so this finds the bullet rather than
    assuming the end of the list.
    """
    if not cfg["bullet"]:
        return 0
    for i, (_line, role) in enumerate(build_block_roles(cfg, "x")):
        if role == "bullet":
            return i
    return 0


def simulate(cfg, title=SAMPLE_TITLE, tail=SAMPLE_TAIL, time_str="23.07 - 14:05",
             state="Day"):
    """(before, after) preview text for the settings page, caret included."""
    before = title + CURSOR + ("\n" + tail if tail else "")
    lines = build_block(cfg, header_line(cfg["format"], title, time_str, state))
    idx = caret_line(cfg)
    lines = list(lines)
    lines[idx] = lines[idx] + CURSOR
    if tail:
        lines.append(tail)
    return before, "\n".join(lines)


def render_preview(text):
    """Blank lines drawn as dots — the gap is the thing being chosen."""
    return "\n".join(line if line.strip() else "·" for line in text.split("\n"))
