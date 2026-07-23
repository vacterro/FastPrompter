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
    "ctrl_e_align": "left",
    "ctrl_e_stamp_every": "False",
}

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
    try:
        gap = max(0, min(6, int(_s("ctrl_e_gap_after"))))
    except (TypeError, ValueError):
        gap = 2
    bullet_char = _s("ctrl_e_bullet_char")
    return {
        "format": _s("ctrl_e_format") or DEFAULTS["ctrl_e_format"],
        "rule": _s("ctrl_e_rule") == "True",
        "gap_after": gap,
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
    lines = [title_line]
    if cfg["rule"]:
        lines.append("---")
    lines.extend([""] * cfg["gap_after"])
    if cfg["bullet"]:
        lines.append(cfg["bullet_char"] + " ")
    return lines


def caret_line(cfg):
    """Index into build_block's list where the caret ends up."""
    return len(build_block(cfg, "x")) - 1 if cfg["bullet"] else 0


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
