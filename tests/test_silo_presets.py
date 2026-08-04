"""T-715: silo templates come from .md files, not from code."""

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_preset_cache():
    """The loader caches; a test that points it at a temp folder must not
    leave the whole session looking at that folder."""
    yield
    from fastprompter.core import silo_presets
    silo_presets._CACHE = None


def test_the_shipped_set_is_there():
    from fastprompter.core.silo_presets import load_presets
    got = load_presets(force=True)
    assert len(got) >= 10, f"only {len(got)} templates shipped"
    labels = [name for name, _ in got]
    for wanted in ("TODO", "thoughts", "Bullet list", "Checklist"):
        assert wanted in labels, f"{wanted} missing from {labels}"
    assert all(text.strip() for _, text in got), "a template with no text is useless"


def test_bullet_list_really_has_ten_items():
    from fastprompter.core.silo_presets import load_presets
    text = dict(load_presets(force=True))["Bullet list"]
    assert text.count("\u2022") == 10, text


def test_a_dropped_in_file_appears_without_a_code_change(tmp_path, monkeypatch):
    """The whole point of files over a Python list."""
    from fastprompter.core import silo_presets

    folder = tmp_path / "presets"
    folder.mkdir()
    (folder / "42_My own.md").write_text("mine\n", encoding="utf-8")
    monkeypatch.setattr(silo_presets, "presets_dir", lambda: str(folder))
    got = silo_presets.load_presets(force=True)
    assert got == [("My own", "mine\n")]
    silo_presets.load_presets(force=True)   # leave the cache pointing at the real set


def test_label_strips_the_ordering_prefix():
    from fastprompter.core.silo_presets import label_for
    assert label_for("03_Bullet list.md") == "Bullet list"
    assert label_for("10_Table.md") == "Table"
    assert label_for("plain.md") == "plain"


def test_a_missing_folder_is_empty_not_an_exception(monkeypatch):
    from fastprompter.core import silo_presets
    monkeypatch.setattr(silo_presets, "presets_dir", lambda: os.path.join("nope", "nowhere"))
    assert silo_presets.load_presets(force=True) == []
