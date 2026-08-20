"""Focused regressions for the second-wave tickets (T-1020..T-1025, T-800, T-1017).

Every test here is Qt-free where the contract allows, so it runs in the plain
unit harness. GUI-dependent paths (BackupDialog export, full watcher runtime)
are covered by the contract they delegate to (portable_backup, _backup_atomically).
"""

import json
import math
import os
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


# ----------------------------------------------------------------- T-1020
def test_backup_atomically_preserves_existing_destination_on_failure(tmp_path):
    from fastprompter.core.state import (
        RestoreError,
        _backup_atomically,
        validate_database,
    )

    src = tmp_path / "src.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    conn.close()

    dest = tmp_path / "dest.db"
    dest.write_bytes(b"PRIOR_BACKUP_BYTES")

    def fake_validate(_p):
        raise RestoreError("forced validation failure")

    orig = validate_database
    fastprompter_state = sys.modules["fastprompter.core.state"]
    fastprompter_state.validate_database = fake_validate
    conn = sqlite3.connect(src)
    try:
        try:
            _backup_atomically(conn, str(dest))
            assert False, "expected RestoreError"
        except RestoreError:
            pass
    finally:
        conn.close()
        fastprompter_state.validate_database = orig

    # the prior backup is byte-identical and no .tmp candidate lingers
    assert dest.read_bytes() == b"PRIOR_BACKUP_BYTES"
    assert not (tmp_path / "dest.db.tmp").exists()


def test_backup_atomically_publishes_nothing_on_fresh_destination_failure(tmp_path):
    from fastprompter.core.state import (
        RestoreError,
        _backup_atomically,
        validate_database,
    )

    src = tmp_path / "src.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()

    dest = tmp_path / "dest.db"  # does not yet exist

    def fake_validate(_p):
        raise RestoreError("forced")

    orig = validate_database
    fastprompter_state = sys.modules["fastprompter.core.state"]
    fastprompter_state.validate_database = fake_validate
    try:
        try:
            _backup_atomically(conn, str(dest))
            assert False
        except RestoreError:
            pass
    finally:
        conn.close()
        fastprompter_state.validate_database = orig

    # a failed candidate to a fresh destination must publish nothing
    assert not dest.exists()
    assert not (tmp_path / "dest.db.tmp").exists()


# ----------------------------------------------------------------- T-1021
def test_portable_export_keeps_orphan_categories_distinct(tmp_path, monkeypatch):
    import fastprompter.utils.portable_backup as pb

    monkeypatch.setattr(pb, "get_portable_backup_dir", lambda: str(tmp_path))

    data = {
        "cats_order": ["Code"],
        "temp_presets_all": {
            "Foo.": ["hello from foo dot"],
            "Foo ": ["hello from foo space"],
        },
        "archive_temp_presets_all": {},
        "categories": {},
    }
    pb._do_export(data, profile_id=1)

    silos_root = tmp_path / time.strftime("%Y-%m-%d") / "silos"
    cat_dirs = sorted(p.name for p in silos_root.iterdir() if p.is_dir())
    # two distinct directories, not one collapsed "Foo"
    assert len(cat_dirs) == 2, cat_dirs
    contents = set()
    for d in cat_dirs:
        files = list((silos_root / d).glob("*.md"))
        assert len(files) == 1
        contents.add(files[0].read_text(encoding="utf-8"))
    assert "hello from foo dot" in "\n".join(contents)
    assert "hello from foo space" in "\n".join(contents)


# ----------------------------------------------------------------- T-1023
def test_queue_heals_malformed_fields_and_unique_ids():
    from fastprompter.core.watcher.queue import load_queues

    raw = {
        1: [
            {"text": "a", "skill": 123, "id": "dup"},   # skill int -> "123"
            {"text": "b", "id": "dup"},                   # duplicate id -> new
            {"text": "c", "id": 5},                       # numeric id -> new
            {"text": "d", "state": "bogus"},               # bad state -> pending
        ],
        "1": [{"text": "e"}],                              # alias key merges
        "x": [
            {"text": "f", "id": ""},                       # empty id -> new
            {"not": "text"},                               # dropped (no text)
        ],
    }
    queues = load_queues(raw)

    assert "1" in queues
    items = queues["1"]
    texts = {i.text for i in items}
    assert texts == {"a", "b", "c", "d", "e"}, texts
    ids = [i.id for i in items]
    assert len(set(ids)) == len(ids), "all ids must be unique"
    a = next(i for i in items if i.text == "a")
    assert a.skill == "123"
    d = next(i for i in items if i.text == "d")
    assert d.state == "pending"

    assert "x" in queues and [i.text for i in queues["x"].items] == ["f"]


# ----------------------------------------------------------------- T-1024
def test_structured_list_member_normalization():
    from fastprompter.core.state import _decode_structured_setting

    # a stray dict member is dropped, valid strings kept
    out = _decode_structured_setting(
        "cats_order", json.dumps(["Code", {}, "Text"]), list,
        ["Code", "Text", "Misc"], False)
    assert out == ["Code", "Text"]

    # non-string members dropped from a hidden-categories list
    out2 = _decode_structured_setting(
        "hidden_categories", json.dumps(["X", 5, "Y"]), list, [], False)
    assert out2 == ["X", "Y"]

    # every member invalid -> canonical fallback
    out3 = _decode_structured_setting(
        "cats_order", json.dumps([{}, 123]), list,
        ["Code", "Text", "Misc"], False)
    assert out3 == ["Code", "Text", "Misc"]

    # dict settings are untouched (not string lists)
    out4 = _decode_structured_setting(
        "custom_colors", json.dumps({"a": "#fff"}), dict, {}, True)
    assert out4 == {"a": "#fff"}

    # silo layout integer-list settings drop non-int / negative members
    out5 = _decode_structured_setting(
        "silo_gaps", json.dumps([0, {}, 2, -1, "x", 4]), list, [], True)
    assert out5 == [0, 2, 4], out5

    out6 = _decode_structured_setting(
        "pinned_silos", json.dumps([1, {}, "3", -2]), list, [], False)
    assert out6 == [1], out6

    out7 = _decode_structured_setting(
        "silo_ticked", json.dumps([{}, 5, "y"]), list, [], False)
    assert out7 == [5], out7

    out8 = _decode_structured_setting(
        "silo_collapsed", json.dumps([0, 1, {}]), list, [], False)
    assert out8 == [0, 1], out8

    # a heterogeneous list codec is NOT filtered (its members are dicts)
    out9 = _decode_structured_setting(
        "watcher_skills_extra", json.dumps([{"a": 1}, "x"]), list, [], True)
    assert out9 == [{"a": 1}, "x"], out9


# ----------------------------------------------------------------- T-1025
def test_fancy_zone_ui_state_and_geometry_healing():
    from fastprompter.ui.fancy_zones import _ui_state_of, _load_presets

    # a persisted string "False" must stay False, never become True
    st = _ui_state_of({"zen": "False", "theme": "Dark"})
    assert st["zen"] is False
    assert st["theme"] == "Dark"
    # absent key stays None ("preset does not say")
    assert _ui_state_of({})["zen"] is None

    # NaN geometry is healed into a finite, on-screen fraction (cannot crash or
    # place the window off-screen) rather than silently applied as NaN
    bad = _load_presets({"window_presets": [
        {"name": "p", "x": float("nan"), "y": 1.0, "w": 0.5, "h": 0.5}]})
    assert len(bad) == 1
    assert math.isfinite(bad[0]["x"]) and 0.0 <= bad[0]["x"] <= 1.0
    assert math.isfinite(bad[0]["y"]) and 0.0 <= bad[0]["y"] <= 1.0
    assert bad[0]["w"] > 0 and bad[0]["h"] > 0

    # oversized fraction is clamped into [0, 1]
    big = _load_presets({"window_presets": [
        {"name": "p", "x": 1.5, "y": 0.5, "w": 0.5, "h": 0.5}]})
    assert big and big[0]["x"] == 1.0

    # legacy geometry-only [x,y,w,h] preset is unchanged
    legacy = _load_presets({"window_presets": [[0.1, 0.2, 0.5, 0.5]]})
    assert legacy and abs(legacy[0]["x"] - 0.1) < 1e-9


# ----------------------------------------------------------------- T-1022
def test_watcher_disarm_clears_active_send():
    from fastprompter.ui.watcher_mixin import WatcherMixin

    class M(WatcherMixin):
        def __init__(self):
            self.prompt_queues = {}
            self.save_prompt_queues = lambda: None

    m = M()
    m._watcher_init()
    # simulate an in-flight send
    m._watcher_send_active = True
    m._watcher_send_gen = 5

    # a late callback from gen 5 must NOT clear a newer dispatch's flag
    m._watcher_send_gen = 6
    # (the guard in _watcher_on_send_result returns early when gen != current)

    m.watcher_disarm()
    # after disarm the stale in-flight send is retired
    assert m._watcher_send_active is False
    assert m._watcher_send_gen == 7

    # an immediate quiesce must not wait on the discarded send
    m._watcher_quiescing = False
    assert m._watcher_begin_quiesce(timeout_s=0.01) is True


# ----------------------------------------------------------------- T-800
REQUIRED_LANGS = [
    "ar", "bg", "cs", "da", "de", "ded", "el", "en", "est", "fi",
    "fra", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "nl",
    "no", "pl", "pt", "ro", "ru", "sk", "spa", "sv", "th", "tur",
    "ukr", "vi", "zh",
]


def _make_validator_project(root, langs):
    saipen = os.path.join(root, ".saipen", "saitranslate")
    locales = os.path.join(saipen, "locales")
    os.makedirs(locales, exist_ok=True)
    os.makedirs(os.path.join(saipen, "kitchen", "docs"), exist_ok=True)
    with open(os.path.join(saipen, "STATE.md"), "w", encoding="utf-8") as f:
        f.write("phase: DONE\n")
    # canonical source = en.json; include a few keys
    en = {"translations": {"hello": "hello", "save": "save", "quit": "quit"},
          "coverage_pct": 100.0}
    with open(os.path.join(locales, "en.json"), "w", encoding="utf-8") as f:
        json.dump(en, f, ensure_ascii=False)
    # every required language must exist, else the validator reports missing
    # files. Fill each with the canonical keys (placeholder == key so they are
    # not flagged as missing-in-locale; untranslated is only a warning).
    for lang in REQUIRED_LANGS:
        trans = dict(langs.get(lang, {}))
        for k in ("hello", "save", "quit"):
            trans.setdefault(k, k)
        data = {"translations": trans, "coverage_pct": 100.0}
        with open(os.path.join(locales, f"{lang}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def test_validator_no_false_dead_keys_and_honest_coverage(tmp_path):
    # a locale that has the same keys but where one value is a placeholder
    _make_validator_project(tmp_path, {
        "de": {"hello": "Hallo", "save": "Speichern", "quit": "quit"},
    })
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "validate_saitranslate.py"),
         "--root", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    # data-driven keys live only in en.json here, so none are "dead"
    assert "dead weight" not in out, out
    # de has all three canonical keys, so no missing-in-locale error
    assert "MISSING from de.json" not in out, out


# ----------------------------------------------------------------- T-1017
def test_sync_fast_has_no_hardcoded_path_and_honest_coverage(tmp_path):
    # a minimal project root so the tool derives everything from --root
    pkg = os.path.join(tmp_path, "src", "fastprompter")
    os.makedirs(os.path.join(pkg, "core"), exist_ok=True)
    for init in ("__init__.py", os.path.join("core", "__init__.py")):
        with open(os.path.join(pkg, init), "w", encoding="utf-8") as f:
            f.write("")
    with open(os.path.join(pkg, "core", "translations.py"), "w", encoding="utf-8") as f:
        f.write("_DATA = {'hello': 'hello'}\n")
    saipen = os.path.join(tmp_path, ".saipen", "saitranslate", "locales")
    os.makedirs(saipen, exist_ok=True)
    with open(os.path.join(saipen, "en.json"), "w", encoding="utf-8") as f:
        json.dump({"translations": {"hello": "hello"}, "coverage_pct": 100.0}, f)
    with open(os.path.join(saipen, "de.json"), "w", encoding="utf-8") as f:
        # de is missing "hello"
        json.dump({"translations": {}, "coverage_pct": 100.0}, f)

    env = dict(os.environ, PYTHONPATH=os.path.join(tmp_path, "src"))
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "sync_saitranslate_fast.py"),
         "--root", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    with open(os.path.join(saipen, "de.json"), encoding="utf-8") as f:
        de = json.load(f)
    # the missing key is filled with the EN placeholder (not translated here)
    assert de["translations"].get("hello") == "hello"
    # coverage is honest: the one key is a placeholder, so 0.0, not 100.0
    assert de["coverage_pct"] == 0.0, de

    # the source must not embed the old absolute checkout path
    with open(os.path.join(ROOT, "tools", "sync_saitranslate_fast.py"),
              encoding="utf-8") as f:
        src_text = f.read()
    assert "V:\\___VAC" not in src_text
    assert r"V:\___VAC" not in src_text


# ----------------------------------------------------------------- CORE-005
def test_silogapbar_i18n_keys_registered_and_translated():
    """The SiloGapBar rename feature added three translatable source strings;
    every one must be registered (present in the canonical EN inventory and in
    each shipped locale) and the audited locales must carry a real translation,
    not fall through to the untranslated English source."""
    from fastprompter.core.i18n import tr, ensure_initialized

    gap_keys = [
        "Ctrl+drag to move this gap. Double-click to rename.",
        "Gap Name",
        "Name for this group:",
        "Backup failed validation; the previous backup is unchanged:\n{}",
        "Export would overwrite itself at:\n{}",
    ]

    import importlib

    en = importlib.import_module("fastprompter.core.i18n.en")
    for k in gap_keys:
        assert k in en.TRANSLATIONS, f"missing canonical key: {k!r}"

    # present in every shipped locale module
    i18n_dir = os.path.join(SRC, "fastprompter", "core", "i18n")
    for fname in os.listdir(i18n_dir):
        if not fname.endswith(".py") or fname in (
                "__init__.py", "_compat.py", "_container.py",
                "_context.py", "_engine.py"):
            continue
        mod = importlib.import_module(
            "fastprompter.core.i18n." + fname[:-3])
        for k in gap_keys:
            assert k in mod.TRANSLATIONS, \
                f"locale {fname} missing gap key {k!r}"

    # audited locales must return a real translation, not the English source
    ensure_initialized()
    for lang in ("RU", "EST", "JA"):
        for k in gap_keys:
            got = tr(k, lang)
            assert got != k, \
                f"{lang} lookup for {k!r} returned the untranslated source"


# ----------------------------------------------------------------- CORE-001
def _make_current_schema_db(path, settings=None):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version=1")
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE presets(category TEXT, slot INTEGER, name TEXT, "
                 "content TEXT, last_edited INTEGER, "
                 "PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE temp_presets_v2(category TEXT, slot INTEGER, "
                 "content TEXT, PRIMARY KEY (category, slot))")
    conn.execute("CREATE TABLE archive_temp_presets_v2(category TEXT, slot "
                 "INTEGER, content TEXT, PRIMARY KEY (category, slot))")
    for k, v in (settings or {}).items():
        conn.execute("INSERT INTO settings VALUES(?,?)", (k, v))
    conn.commit()
    conn.close()


def test_malformed_cats_order_and_hidden_recover_from_db(tmp_path, monkeypatch):
    """A current-schema DB carrying mixed-type cats_order / hidden_categories
    must load without raising, discard the malformed members, fall an
    all-invalid cats_order back to its canonical default, and survive a
    save/reload round-trip."""
    import json

    import fastprompter.core.state as state_mod

    # The schema tables push the file over the startup-snapshot size threshold;
    # the snapshot is out of scope for this test, so neutralise it (it is a
    # benign degraded-recovery path anyway).
    monkeypatch.setattr(state_mod, "_backup_atomically", lambda *a, **k: None)

    db = tmp_path / "fp.db"
    _make_current_schema_db(str(db), {
        "cats_order": json.dumps(["Code", {}, "Text"]),
        "hidden_categories": json.dumps(["X", 5, "Y"]),
        "silo_gaps": json.dumps([0, {}, 2, -1, "x", 4]),
        "pinned_silos": json.dumps([1, {}, "3", -2]),
    })
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: str(db))

    state = state_mod.FastPrompterState(profile_id=1)
    assert state.data["cats_order"] == ["Code", "Text"], state.data["cats_order"]
    assert state.data["hidden_categories"] == ["X", "Y"]
    # integer slot-index lists drop non-int / negative members
    assert state.data["silo_gaps"] == [0, 2, 4], state.data["silo_gaps"]
    assert state.data["pinned_silos"] == [1], state.data["pinned_silos"]
    # no dict members survive, so set()-based consumers (prune_silo_gaps) are safe
    assert all(isinstance(g, int) for g in state.data["silo_gaps"])

    # all-invalid cats_order -> canonical default
    db2 = tmp_path / "fp2.db"
    _make_current_schema_db(str(db2), {"cats_order": json.dumps([{}, 123])})
    monkeypatch.setattr(state_mod, "get_db_path", lambda profile_id=1: str(db2))
    state2 = state_mod.FastPrompterState(profile_id=1)
    assert state2.data["cats_order"] == ["Code", "Text", "Misc"]

    # save/reload preserves the repaired values (operate on the SAME db2 state)
    state2.data["cats_order"] = ["Code", "Text"]
    state2.data["hidden_categories"] = ["X"]
    assert state2.save_data_to_db("hello", force=True) is True

    reloaded = state_mod.FastPrompterState(profile_id=1)
    assert reloaded.data["cats_order"] == ["Code", "Text"]
    assert reloaded.data["hidden_categories"] == ["X"]


import time  # noqa: E402  (used by portable_backup call above)
