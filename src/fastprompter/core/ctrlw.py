"""Ctrl+W (Smart Line) — the text half, with no Qt in it.

The settings dialog used to draw its examples from a hand-written table of
strings. Those strings were fixed, so they went on claiming ``\\n\\n---`` after
the user had set "before" to 0, and nothing in the code could notice. The
template is built here now, by one function that both the editor and the
preview call, so a preview that lies is a preview that inserts the wrong
thing too - and the tests catch it.

``simulate`` is preview-only: it reproduces where ``insert_add_line`` puts
the template for each scenario, over plain strings instead of a
QTextDocument. Keep the two in step; the scenario tests exist to say when
they are not.
"""

CURSOR = "│"  # what stands in for the caret in a preview

# id, short title, when it fires
SCENES = [
    ("s1", "End of a line", "caret at the end of a line of text"),
    ("s2", "Empty document", "nothing above the caret"),
    ("s3", "Between two blocks", "blank line with text above and below"),
    ("s4", "Middle of a word", "caret inside text - the line is split"),
    ("s5", "Under a divider", "on an empty line with --- straight above"),
]

SCENE_TITLES = {sid: title for sid, title, _ in SCENES}
SCENE_TRIGGERS = {sid: trig for sid, _, trig in SCENES}

# What each scenario is for, one sentence. Long prose belongs in a tooltip,
# not on the surface of a dialog with six cards on it.
SCENE_HELP = {
    "s1": "Closes the current line and opens a fresh point below it.",
    "s2": "Starts an empty note off with its first point.",
    "s3": "Cuts an existing note in two without touching either half.",
    "s4": "Splits mid-sentence: the tail moves down under the new point.",
    "s5": "Fills the empty space under a rule without stacking a second one.",
}

S6_HELP = (
    "Pressing Ctrl+W while the caret sits on a --- line: remove that line, "
    "keep it and add a point underneath, or leave it alone."
)

# The document each preview starts from, caret marked. Chosen to be the
# smallest text that actually triggers that scenario.
SAMPLE = {
    "s1": "a thought" + CURSOR,
    "s2": CURSOR,
    "s3": "first note\n" + CURSOR + "\nsecond note",
    "s4": "one two" + CURSOR + " three",
    # an EMPTY line under the rule. With text on it the caret is in s1 -
    # s5 used to swallow that case and every s1 setting looked dead.
    "s5": "---\n" + CURSOR,
}


def build_template(sid, use_div, use_bul, before, after, bullet_char):
    """The exact text Ctrl+W inserts for one scenario.

    ``before``/``after`` are counts of newlines, not of blank lines: 2 before
    means one visibly empty line above the divider. s2 skips the leading
    newlines because there is nothing above to be separated from.
    """
    parts = []
    if use_div:
        if sid != "s2":
            parts.append("\n" * before)
        parts.append("---")
    # a divider dropped between two blocks still needs its trailing gap, or
    # the paragraph below ends up glued to it
    if use_bul or (use_div and sid == "s3"):
        parts.append("\n" * after)
    if use_bul:
        parts.append(bullet_char + " ")
    return "".join(parts)


def simulate(sid, use_div, use_bul, before, after, bullet_char):
    """(before_text, after_text) for the preview, caret included.

    Mirrors where ``insert_add_line`` lands the template. It is a copy of
    that placement, not the same code - the editor's version speaks
    QTextCursor - so the scenario tests pin them together.
    """
    src = SAMPLE.get(sid, CURSOR)
    template = build_template(sid, use_div, use_bul, before, after, bullet_char)
    head, _, tail = src.partition(CURSOR)

    if sid == "s3":
        # inserted at the START of the blank line; with no bullet the caret
        # moves on down to the block below
        out = head + template + tail
        if use_bul:
            return src, _place_caret(head + template, tail)
        return src, _caret_before_next_text(head + template, tail)
    if sid == "s4":
        # the tail of the line is cut and re-laid after the template
        rest = tail.split("\n", 1)[0]
        after_rest = tail[len(rest):]
        return src, head + template + CURSOR + rest + after_rest
    # s1 / s2 / s5: straight insertion at the caret
    return src, _place_caret(head + template, tail)


def _place_caret(left, right):
    return left + CURSOR + right


def _caret_before_next_text(left, right):
    """Caret at the start of the first non-blank line of ``right``."""
    lines = right.split("\n")
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return left + CURSOR
    head = "\n".join(lines[:i])
    tail = "\n".join(lines[i:])
    return left + head + ("\n" if head or i else "") + CURSOR + tail


def render_preview(text):
    """Preview text with its blank lines made countable.

    An empty line is invisible, and "2 or 3 blank lines here" is exactly what
    the user is trying to decide - so each one is drawn as a dot instead of
    nothing at all.
    """
    return "\n".join(line if line.strip() else "·" for line in text.split("\n"))
