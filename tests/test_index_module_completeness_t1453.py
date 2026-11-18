"""T-1453 (SRC-147) — the git index must be a tree that can import itself.

T-1453: `src/fastprompter/main.py`, `ui/editor.py`, `ui/markdown_highlighter.py`
and `core/rich_preview.py` were staged while importing
`fastprompter.core.interval_schedule` and `fastprompter.core.link_tokens`, and
neither module was in the index or in HEAD. `git checkout-index -a` produced a
tree whose own `main.py` raised ModuleNotFoundError, so any commit from that
index would have shipped a broken build.

The control reads the STAGED text (`git show :<path>`), never the working tree,
because the working tree is what made the defect invisible: the two modules
were present on disk the whole time.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "src/"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True,
        capture_output=True,
    ).stdout.decode("utf-8", errors="replace")


def _indexed_files() -> set[str]:
    return set(_git("ls-files", "-z").split("\0")) - {""}


def _imported_modules(text: str) -> set[str]:
    """Every dotted `fastprompter.*` module the staged source names."""
    mods: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("fastprompter"):
                mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fastprompter"):
                    mods.add(alias.name)
    return mods


def _module_path(module: str) -> list[str]:
    base = SRC + module.replace(".", "/")
    return [f"{base}.py", f"{base}/__init__.py"]


def _is_indexed(module: str, indexed: set[str]) -> bool:
    """A module is present as a file, a package ``__init__``, or -- for the
    implicit namespace packages this tree uses (``fastprompter.core`` and
    ``fastprompter.ui`` carry no ``__init__.py``) -- as a directory that
    already holds at least one indexed file."""
    if any(candidate in indexed for candidate in _module_path(module)):
        return True
    prefix = SRC + module.replace(".", "/") + "/"
    return any(p.startswith(prefix) for p in indexed)


def test_index_contains_every_module_its_own_sources_import():
    indexed = _indexed_files()
    indexed_src = sorted(p for p in indexed if p.startswith(SRC))

    offenders: list[str] = []
    for path in indexed_src:
        staged = _git("show", f":{path}")
        if not staged:
            continue
        try:
            mods = _imported_modules(staged)
        except SyntaxError:  # a data file staged under src/, not a module
            continue
        for module in mods:
            if not _is_indexed(module, indexed):
                offenders.append(f"{path} imports {module}, which the index lacks")

    assert not offenders, "\n".join(offenders)


def test_the_two_modules_that_were_missing_are_indexed():
    """The named defect, asserted directly so a future index rewrite cannot
    re-drop them behind the general control's back."""
    indexed = _indexed_files()
    for module in ("fastprompter.core.interval_schedule",
                   "fastprompter.core.link_tokens"):
        assert _is_indexed(module, indexed), (
            f"{module} is imported by staged sources but absent from the index"
        )


def test_indexed_tree_imports_its_own_package(tmp_path):
    """End to end: materialize the index and import the package out of it."""
    prefix = tmp_path / "index_tree"
    prefix.mkdir()
    _git("checkout-index", "-a", f"--prefix={prefix}{'/'}")

    script = (
        "import fastprompter.core.interval_schedule, "
        "fastprompter.core.link_tokens, fastprompter.core.rich_preview, "
        "fastprompter.main\nprint('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONPATH": str(prefix / "src")},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("ok")
