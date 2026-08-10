"""The wiki cheatsheet must not drift from what the code actually binds.

The Keyboard-Shortcuts-and-Cheatsheet.md table is the user's reference for
what every hotkey does. It drifted once already: T-776 shipped a wiki that
said "Hide on Click-Out is gone" while the feature (and its Alt+A binding)
was back in the code. Nobody noticed because nothing compared the two.

This test extracts every hotkey token from the cheatsheet table and checks
it is findable in the source -- as a QShortcut sequence, an add_shortcut /
add_fixed default, a hotkey_mixin global default, an editor keyPressEvent
branch, or a help/i18n string that documents it. A renamed or removed
binding that nobody updated the sheet for fails here, instead of shipping.

Deliberately not a strict set equality: the sheet documents ranges
(F1-F10), mouse gestures (Ctrl+MiddleButton), native Qt keys (Tab, Esc,
Ctrl+Return) and editor-internal keys that are never registered through
one central table, so a row is either an exact code token or a normalized
variant of one.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHEATSHEET = ROOT / "docs/wiki/Keyboard-Shortcuts-and-Cheatsheet.md"
SRC = ROOT / "src"

# Glyphs the sheet uses where Qt/code writes ASCII key names.
_ARROW_GLYPHS = {
    "←": "Left",
    "→": "Right",
    "↑": "Up",
    "↓": "Down",
}

# Hotkeys that are real but have no literal token in src/ -- native Qt
# editing keys, mouse gestures and layout keys that Qt itself dispatches.
_ALLOWED_MISSING = {
    "Ctrl+Return",      # editor.py keyPressEvent: Key_Return toggle checkboxes
    "Ctrl+Enter",
    "Alt+Backspace",    # editor word-delete
    "Ctrl+MiddleButton",
    "Alt+MiddleButton",
    "MiddleButton",
    "Ctrl+Click on bullet",
    "Ctrl+Shift+drag",
    "Tab",
    "Shift+Tab",
    "Delete",           # editor.py: Key_Delete trash prompt
    "F2",               # file container rename
    "Ctrl+Plus/Minus",
}


def _normalize(token: str) -> str:
    """Turn one cheatsheet token into something grep-able in the code."""
    token = token.replace("\\`", "`")          # markdown-escaped backtick
    for glyph, name in _ARROW_GLYPHS.items():
        token = token.replace(glyph, name)
    return token.strip()


def _code_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))


def _cheatsheet_tokens() -> list[str]:
    tokens = []
    for line in CHEATSHEET.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4:
            continue
        hotkey = cells[2]
        if hotkey in ("Hotkey", "---"):
            continue
        # grab every **...** emphasis span; each is a hotkey or hotkey part
        spans = [s.strip() for s in hotkey.split("**") if s.strip()]
        for span in spans:
            # split alternates and ranges: "Ctrl+Y / Ctrl+Shift+Z",
            # "Alt+← / Alt+→", "F1**:**F10" already split by the ** pass
            for part in re_split(span):
                if part.startswith("("):
                    continue   # "(double)" style annotation, not a hotkey
                tokens.append(part)
    return tokens


def re_split(span: str):
    import re
    # "Alt+← / Alt+→" -> two; "Ctrl+Shift+1**:**9" handled by ** split
    return [p.strip() for p in re.split(r"\s*/\s*", span) if p.strip()]


def _is_findable(token: str, code: str) -> bool:
    n = _normalize(token)
    if n in _ALLOWED_MISSING:
        return True
    if n in code:
        return True
    # combined arrow names from "Alt+←→" -> "Alt+LeftRight"; the editor
    # binds each direction separately (Alt+Left, Alt+Right, ...)
    import re
    m = re.match(r"^(.*\+)(LeftRight|UpDown)$", n)
    if m:
        base = m.group(1)
        combo = m.group(2)
        parts = re.split(r"Right|Down", combo)
        first = parts[0]
        second = combo[len(first):]
        if (base + first) in code and (base + second) in code:
            return True
    # range like "Ctrl+1" or "F10": the sheet documents "Ctrl+1**:**Ctrl+0"
    # and "F1**:**F10"; accept when the base prefix exists with a digit in
    # code (e.g. "Ctrl+Shift+Numpad{i+1}", "Key_1".."Key_0", "silo_0_hotkey")
    m = re.match(r"^(.*?)(\d+)$", n)
    if m:
        base = m.group(1)
        if re.search(re.escape(base) + r"\d", code):
            return True
        if re.search(re.escape(base) + r"[i{]", code):   # f-string loop
            return True
    return False


def test_cheatsheet_rows_are_in_the_code():
    code = _code_text()
    tokens = _cheatsheet_tokens()
    assert tokens, "cheatsheet should have hotkey rows"
    missing = [(t, _normalize(t)) for t in tokens if not _is_findable(t, code)]
    assert not missing, (
        "cheatsheet hotkeys missing from src/: "
        + ", ".join(f"{raw} ({norm})" for raw, norm in missing[:10])
    )


@pytest.mark.parametrize("stale", ["Ctrl+ZZZ", "Alt+Nonexistent"])
def test_deliberately_stale_row_fails(stale):
    code = _code_text()
    assert not _is_findable(stale, code), f"{stale} should not be findable"
