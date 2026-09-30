"""The documented locked setup must satisfy the build's compiler gate."""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _accepted_compiler():
    tree = ast.parse((ROOT / "tools/build.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_NUITKA_PIN"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Build tool must declare the accepted compiler")


def test_build_extra_pins_the_accepted_compiler():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert f"nuitka=={_accepted_compiler()}" in project["project"]["optional-dependencies"]["build"]


def test_locked_setup_resolves_the_accepted_compiler():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    compilers = [package for package in lock["package"] if package["name"] == "nuitka"]
    assert len(compilers) == 1
    assert compilers[0]["version"] == _accepted_compiler()
