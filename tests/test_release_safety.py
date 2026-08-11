"""Phase-11: the onefile release build strips assertions.

`FastPrompter.pyw` ships ``--python-flag=no_asserts``, so an ``assert`` in
production code is REMOVED from the packaged EXE. A safety check or invariant
written as ``assert`` therefore stops existing exactly where the user needs
it most. This guard fails if a new ``assert`` statement appears in production
source, forcing explicit runtime validation instead.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "fastprompter"

# These modules carry deliberate keyword-STRING/comment mentions of assert
# (markdown_highlighter's keyword list, comments). Only real statements count.
_IGNORE_PATHS = ()


def _assert_statements():
    found = []
    for path in SRC.rglob("*.py"):
        if any(part in path.parts for part in _IGNORE_PATHS):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                found.append((path, node.lineno, ast.unparse(node).strip()))
    return found


def test_no_assert_statements_in_production_code():
    """no_asserts strips them from the shipped EXE; use explicit validation."""
    found = _assert_statements()
    assert not found, (
        "production code must not use `assert`: the Nuitka onefile build "
        "runs with --python-flag=no_asserts and strips it. Convert to "
        "explicit runtime validation (if not cond: raise ...). Found: "
        + ", ".join(f"{p}:{ln} {a}" for p, ln, a in found))
