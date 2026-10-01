"""Every tr() key the Limit UI emits must resolve in the English pack.

tr() falls back to the key itself, so a missing key is invisible at runtime
and in every locale: the UI paints English and the gate stays green. This
is the only place that notice happens, so it is asserted here.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from fastprompter.core.i18n import en

UI = pathlib.Path("src/fastprompter/ui")
LIMIT_UI_FILES = [
    "limit_overview.py",
    "limit_gauges.py",
    "limit_settings_dialog.py",
    "limit_hover_card.py",
    "limit_account_selector.py",
]


def _tr_keys(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "tr" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


@pytest.mark.parametrize("name", LIMIT_UI_FILES)
def test_limit_ui_imports_tr(name: str) -> None:
    """A file that wraps a literal must import tr; one that wraps none must not.

    limit_hover_card.py paints a single QLabel whose HTML its caller builds, so
    it has no literal of its own. Importing tr() there would be an unused
    import and a claim the file does not make.
    """
    source = (UI / name).read_text(encoding="utf-8")
    wraps = bool(_tr_keys(UI / name))
    imports = "from fastprompter.core.translations import tr" in source
    assert imports == wraps, (
        f"{name}: wraps {wraps} tr() key(s) but imports tr() = {imports}"
    )


@pytest.mark.parametrize("name", LIMIT_UI_FILES)
def test_limit_ui_tr_keys_resolve_in_english(name: str) -> None:
    missing = sorted(k for k in _tr_keys(UI / name) if k not in en.TRANSLATIONS)
    assert not missing, f"{name}: {len(missing)} tr() key(s) absent from en.py: {missing}"


def test_limit_ui_actually_wraps_something() -> None:
    """Guard against the scan silently matching nothing after a refactor."""
    total = sum(len(_tr_keys(UI / name)) for name in LIMIT_UI_FILES)
    assert total >= 100, f"only {total} tr() keys found across the Limit UI"
