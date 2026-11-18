"""T-1437 / SRC-134: red controls R1-R20 for the personal-audio campaign.

WHY THIS FILE EXISTS
--------------------
SRC-134 asks for a fixed set of red controls (section 13). Before this file
`tests/conftest.py` set ``FASTPROMPTER_PERSONAL_AUDIO=0`` for every test in the
tree and no test ever turned it back on, so the personal-mode branch of
:func:`resolve_sound_ref` -- the override table and addon-first precedence,
which is the whole point of the campaign -- had **zero** executed coverage. A
green suite therefore said nothing about the operator's actual configuration.

Every test here builds its own throwaway roots and never touches the real
data directory, the live database or the shipped sound folder (R19, R20).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from fastprompter.core import sound_library as sl

# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

def _wav(path: Path, marker: bytes) -> Path:
    """A tiny but structurally valid RIFF/WAVE file with a unique payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = marker.ljust(64, b"\0")
    header = (b"RIFF" + (36 + len(body)).to_bytes(4, "little") + b"WAVE"
              + b"fmt " + (16).to_bytes(4, "little") + b"\1\0\1\0"
              + (8000).to_bytes(4, "little") + (16000).to_bytes(4, "little")
              + b"\2\0\20\0" + b"data" + len(body).to_bytes(4, "little"))
    path.write_bytes(header + body)
    return path


class _Roots:
    """Three disjoint sound roots: packaged / managed / addon."""

    def __init__(self, base: Path):
        self.builtin = base / "packaged"
        self.user = base / "managed"
        self.addon = base / "addon"
        for root in (self.builtin, self.user, self.addon):
            root.mkdir(parents=True, exist_ok=True)

    def resolve(self, ref: str):
        return sl.resolve_sound_ref(
            ref,
            builtin_root=str(self.builtin),
            user_root=str(self.user),
            addon_root_path=str(self.addon),
        )


@pytest.fixture
def personal_mode(monkeypatch):
    """Turn personal mode ON for one test, then restore the tree default."""
    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "1")
    sl.invalidate_personal_audio_cache()
    yield
    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "0")
    sl.invalidate_personal_audio_cache()


@pytest.fixture
def public_mode(monkeypatch):
    """Personal mode explicitly OFF: the clean public installation."""
    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "0")
    sl.invalidate_personal_audio_cache()
    yield
    sl.invalidate_personal_audio_cache()


@pytest.fixture
def personal_table(monkeypatch, tmp_path):
    """Personal mode ON, driven by a real on-disk override table.

    The env-var path deliberately ignores the table, so the override test has
    to exercise the file branch to prove the table is actually read.
    """
    cfg = tmp_path / "personal_audio.json"
    cfg.write_text(json.dumps({"personal_override": True,
                               "overrides": {"menu1.wav": "addon:orig_menu1.wav"}}),
                   encoding="utf-8")
    monkeypatch.delenv("FASTPROMPTER_PERSONAL_AUDIO", raising=False)
    monkeypatch.setattr(sl, "_personal_config_path", lambda: str(cfg))
    sl.invalidate_personal_audio_cache()
    yield
    sl.invalidate_personal_audio_cache()


# --------------------------------------------------------------------------
# R1 / R2 -- precedence
# --------------------------------------------------------------------------

def test_r1_personal_original_wins_over_a_same_named_packaged_fallback(
        tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    original = _wav(roots.addon / "menu1.wav", b"ORIGINAL-H3")
    _wav(roots.builtin / "menu1.wav", b"SYNTHETIC-CLEAN")

    assert roots.resolve("menu1.wav") == str(original)


def test_r2_absent_personal_original_falls_back_to_the_packaged_file(
        tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    fallback = _wav(roots.builtin / "menu1.wav", b"SYNTHETIC-CLEAN")

    assert roots.resolve("menu1.wav") == str(fallback)


def test_r2b_no_personal_mode_keeps_the_historical_public_precedence(
        tmp_path, public_mode):
    roots = _Roots(tmp_path)
    packaged = _wav(roots.builtin / "menu1.wav", b"SYNTHETIC-CLEAN")
    _wav(roots.addon / "menu1.wav", b"ORIGINAL-H3")

    assert roots.resolve("menu1.wav") == str(packaged)


# --------------------------------------------------------------------------
# R3 / R4 / R5 -- explicit namespaces are never reinterpreted
# --------------------------------------------------------------------------

def test_r3_user_ref_resolves_only_in_the_managed_root(tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    managed = _wav(roots.user / "mine.wav", b"MANAGED")
    _wav(roots.builtin / "mine.wav", b"PACKAGED")
    _wav(roots.addon / "mine.wav", b"ADDON")

    assert roots.resolve("user:mine.wav") == str(managed)


def test_r4_addon_ref_resolves_only_in_the_addon_root(tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    addon = _wav(roots.addon / "mine.wav", b"ADDON")
    _wav(roots.user / "mine.wav", b"MANAGED")

    assert roots.resolve("addon:mine.wav") == str(addon)


def test_r5_builtin_ref_keeps_its_namespace_even_with_a_personal_original(
        tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    packaged = _wav(roots.builtin / "menu1.wav", b"PACKAGED")
    _wav(roots.addon / "menu1.wav", b"ADDON")

    assert roots.resolve("builtin:menu1.wav") == str(packaged)


def test_r5b_explicit_addon_ref_does_not_fall_through_to_packaged(
        tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    _wav(roots.builtin / "only_packaged.wav", b"PACKAGED")

    assert roots.resolve("addon:only_packaged.wav") is None


# --------------------------------------------------------------------------
# R6 -- the private override table
# --------------------------------------------------------------------------

def test_r6_the_override_table_repoints_a_legacy_bare_ref(tmp_path, personal_table):
    roots = _Roots(tmp_path)
    original = _wav(roots.addon / "orig_menu1.wav", b"ORIGINAL-H3")
    _wav(roots.builtin / "menu1.wav", b"SYNTHETIC-CLEAN")

    assert roots.resolve("menu1.wav") == str(original)


def test_r6b_the_override_table_is_ignored_for_explicit_namespaces(
        tmp_path, personal_table):
    roots = _Roots(tmp_path)
    packaged = _wav(roots.builtin / "menu1.wav", b"PACKAGED")
    _wav(roots.addon / "orig_menu1.wav", b"ORIGINAL-H3")

    assert roots.resolve("builtin:menu1.wav") == str(packaged)


def test_r6c_an_override_that_points_nowhere_falls_back_to_the_table_free_path(
        tmp_path, monkeypatch):
    cfg = tmp_path / "personal_audio.json"
    cfg.write_text(json.dumps({"personal_override": True,
                               "overrides": {"menu1.wav": "addon:gone.wav"}}),
                   encoding="utf-8")
    monkeypatch.delenv("FASTPROMPTER_PERSONAL_AUDIO", raising=False)
    monkeypatch.setattr(sl, "_personal_config_path", lambda: str(cfg))
    sl.invalidate_personal_audio_cache()
    try:
        roots = _Roots(tmp_path)
        packaged = _wav(roots.builtin / "menu1.wav", b"PACKAGED")
        assert roots.resolve("menu1.wav") == str(packaged)
    finally:
        sl.invalidate_personal_audio_cache()


# --------------------------------------------------------------------------
# R7 / R8 -- a drive that comes and goes
# --------------------------------------------------------------------------

def test_r7_an_unavailable_personal_file_never_erases_the_stored_preference(
        tmp_path):
    # The drive holding this addon file is unplugged, so the canonical
    # resolver cannot find it anywhere. The stored choice must survive
    # verbatim and playback falls back at play time instead of persisting the
    # fallback.
    #
    # The ref has to name a file that exists in NO root, otherwise the
    # resolver finds it and the destructive branch is never reached. It also
    # has to stay a SAFE ref, because unsafe refs are still dropped.
    kept = "addon:on_the_unplugged_drive.wav"
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    data = {"sound_events": {"save": {"file": kept}}, "sound_volume": 0.09}

    from fastprompter.core.sound_manager import migrate_sound_settings
    migrate_sound_settings(data, sounds_dir=str(packaged))

    assert data["sound_events"]["save"]["file"] == kept


def test_r8_a_reconnected_drive_is_used_again_with_no_extra_write(
        tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    target = _wav(roots.addon / "OBELISK.wav", b"ORIGINAL")
    assert roots.resolve("addon:OBELISK.wav") == str(target)

    # Disappear and come back: resolution follows the filesystem, the stored
    # ref is untouched either way.
    target.unlink()
    assert roots.resolve("addon:OBELISK.wav") is None
    _wav(roots.addon / "OBELISK.wav", b"ORIGINAL")
    assert roots.resolve("addon:OBELISK.wav") == str(target)


# --------------------------------------------------------------------------
# R9 / R18 -- migration is idempotent and build-independent
# --------------------------------------------------------------------------

def test_r9_migration_is_idempotent(monkeypatch, tmp_path):
    from fastprompter.core import sound_manager

    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "1")
    sl.invalidate_personal_audio_cache()
    try:
        data = {
            "sound_events": {
                "save": {"file": "addon:ui_save.wav", "enabled": "True"},
                "save_hover": {"file": "addon:tick_on.wav"},
            },
            "sound_volume": 0.09,
        }
        sound_manager.migrate_sound_settings(data)
        first = json.loads(json.dumps(data))
        sound_manager.migrate_sound_settings(data)
        assert data == first
    finally:
        monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "0")
        sl.invalidate_personal_audio_cache()


def test_r18_migration_keeps_unknown_future_event_configurations(monkeypatch):
    from fastprompter.core import sound_manager

    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "1")
    sl.invalidate_personal_audio_cache()
    try:
        data = {"sound_events": {"event_from_the_future": {
                    "file": "addon:from_a_later_build.wav",
                    "enabled": "True",
                    "some_future_key": {"nested": 1}}},
                "sound_volume": 0.09}
        sound_manager.migrate_sound_settings(data)
        kept = data["sound_events"]["event_from_the_future"]

        # Unknown to this build, so it is carried over untouched. The gain
        # schema is allowed to add its own key; nothing the later build wrote
        # may be dropped or rewritten.
        assert kept["file"] == "addon:from_a_later_build.wav"
        assert kept["enabled"] == "True"
        assert kept["some_future_key"] == {"nested": 1}
    finally:
        monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "0")
        sl.invalidate_personal_audio_cache()


def test_r18b_a_stored_but_unsafe_ref_is_still_dropped(monkeypatch):
    from fastprompter.core import sound_manager

    monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "1")
    sl.invalidate_personal_audio_cache()
    try:
        data = {"sound_events": {"save": {"file": "../../../etc/passwd"}},
                "sound_volume": 0.09}
        sound_manager.migrate_sound_settings(data)
        assert data["sound_events"]["save"]["file"] != "../../../etc/passwd"
    finally:
        monkeypatch.setenv("FASTPROMPTER_PERSONAL_AUDIO", "0")
        sl.invalidate_personal_audio_cache()


# --------------------------------------------------------------------------
# R10 / R11 / R12 -- ambience
# --------------------------------------------------------------------------

def _ambience_store(tmp_path):
    from fastprompter.core.ambience_store import AmbienceStore

    return AmbienceStore(str(tmp_path / "audio.db"))


def test_r10_ambience_keeps_a_custom_rule_name_and_volume(tmp_path, personal_mode):
    from fastprompter.core.ambience_store import AmbienceRule

    store = _ambience_store(tmp_path)
    store.upsert_rule(AmbienceRule(
        id="amb_custom", name="Night bed", sound_ref="computalk1.wav",
        volume=0.37))
    rule = [r for r in store.load_rules() if r.id == "amb_custom"][0]

    assert rule.name == "Night bed"
    assert rule.volume == pytest.approx(0.37)


def test_r11_a_working_computalk1_is_never_repointed(tmp_path, personal_mode):
    from fastprompter.core.ambience_store import (
        DEFAULT_AMBIENCE_RULE_ID,
        AmbienceRule,
        repair_dead_default_ref,
    )

    store = _ambience_store(tmp_path)
    store.upsert_rule(AmbienceRule(
        id=DEFAULT_AMBIENCE_RULE_ID, name="Ambience",
        sound_ref="computalk1.wav", volume=0.01))

    # The operator still has the original bytes: "it works here".
    changed = repair_dead_default_ref(store, resolver=lambda ref: True)
    rule = [r for r in store.load_rules()
            if r.id == DEFAULT_AMBIENCE_RULE_ID][0]

    assert changed is False
    assert rule.sound_ref == "computalk1.wav"
    assert rule.volume == pytest.approx(0.01)


def test_r12_a_public_install_repoints_a_dead_default_to_ambient_loop(tmp_path):
    from fastprompter.core.ambience_store import (
        DEFAULT_AMBIENCE_RULE_ID,
        DEFAULT_AMBIENCE_SOUND_REF,
        AmbienceRule,
        repair_dead_default_ref,
    )

    store = _ambience_store(tmp_path)
    store.upsert_rule(AmbienceRule(
        id=DEFAULT_AMBIENCE_RULE_ID, name="Ambience",
        sound_ref="computalk1.wav", volume=0.01))

    changed = repair_dead_default_ref(store, resolver=lambda ref: False)
    rule = [r for r in store.load_rules()
            if r.id == DEFAULT_AMBIENCE_RULE_ID][0]

    assert changed is True
    assert rule.sound_ref == DEFAULT_AMBIENCE_SOUND_REF


def test_r12b_a_user_created_rule_is_never_rewritten(tmp_path):
    from fastprompter.core.ambience_store import AmbienceRule, repair_dead_default_ref

    store = _ambience_store(tmp_path)
    store.upsert_rule(AmbienceRule(
        id="amb_mine", name="Mine", sound_ref="computalk1.wav", volume=0.5))

    assert repair_dead_default_ref(store, resolver=lambda ref: False) is False
    assert [r for r in store.load_rules() if r.id == "amb_mine"][0].sound_ref == \
        "computalk1.wav"


# --------------------------------------------------------------------------
# R13 -- preview and playback agree
# --------------------------------------------------------------------------

def test_r13_preview_and_playback_resolve_to_the_same_bytes(tmp_path, personal_mode):
    roots = _Roots(tmp_path)
    original = _wav(roots.addon / "click.wav", b"ORIGINAL")
    _wav(roots.builtin / "click.wav", b"SYNTHETIC")

    preview = roots.resolve("click.wav")
    playback = roots.resolve("click.wav")

    assert preview == playback == str(original)


def test_r13b_the_picker_offers_one_entry_per_effective_file(tmp_path,
                                                             personal_mode,
                                                             monkeypatch):
    roots = _Roots(tmp_path)
    _wav(roots.addon / "menu1.wav", b"ORIGINAL")
    _wav(roots.builtin / "menu1.wav", b"SYNTHETIC")

    # Point the picker's own inventory walk at this test's roots, so the
    # dedupe rule is judged without touching the operator's real folders.
    monkeypatch.setattr(sl, "managed_root", lambda: str(roots.user))
    monkeypatch.setattr(sl, "addon_root", lambda: str(roots.addon))
    monkeypatch.setattr(sl, "packaged_root", lambda: str(roots.builtin))

    selectable = sl.list_selectable_sounds(packaged=["menu1.wav"])

    # menu1.wav is offered exactly once. The surviving spelling is the bare
    # packaged one, which is the same string a stored mapping already uses and
    # which now resolves to the personal original.
    assert selectable.count("menu1.wav") + \
        selectable.count("addon:menu1.wav") == 1
    assert roots.resolve(selectable[0]) == str(roots.addon / "menu1.wav")


# --------------------------------------------------------------------------
# R14 / R15 / R16 / R17 -- publication boundary
# --------------------------------------------------------------------------

def test_r14_the_shipped_sound_folder_matches_the_allowlist():
    import tools.verify_sound_allowlist as gate

    root = Path(__file__).resolve().parents[1]
    manifest = {name.lower() for name in gate.read_manifest(root)}
    shipped = set(gate.shipped_wavs(root))

    assert shipped == manifest


def test_r16_audio_inside_a_tracked_zip_is_detected():
    import io

    import tools.verify_sound_allowlist as gate

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("sound/armgedn.wav", b"RIFF....WAVE")
    assert gate._archive_contains_audio(buffer.getvalue()) is True


def test_r16b_nested_archives_are_scanned_recursively():
    import io

    import tools.verify_sound_allowlist as gate

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("sound/battle00.wav", b"RIFF....WAVE")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("inner.zip", inner.getvalue())

    assert gate._archive_contains_audio(outer.getvalue()) is True


def test_r16c_a_clean_archive_is_not_flagged():
    import io

    import tools.verify_sound_allowlist as gate

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("readme.txt", b"nothing audible")
    assert gate._archive_contains_audio(buffer.getvalue()) is False


def test_r17_an_ignored_private_zip_is_not_a_public_push(tmp_path):
    import subprocess

    import tools.verify_sound_allowlist as gate

    repo = tmp_path / "repo"
    (repo / "src" / "fastprompter" / "sound").mkdir(parents=True)
    (repo / ".gitignore").write_text("*.zip\n", encoding="utf-8")
    _wav(repo / "src" / "fastprompter" / "sound" / "click.wav", b"OK")
    with zipfile.ZipFile(repo / "src" / "fastprompter" / "sound.zip", "w") as zf:
        zf.writestr("sound/battle00.wav", b"RIFF....WAVE")

    for args in (["init", "-q"], ["add", "src", ".gitignore"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)

    published = gate.git_published_audio(repo)
    assert published is not None
    assert all(not p.endswith(".zip") for p in published)


# --------------------------------------------------------------------------
# R19 / R20 -- the live installation is never a fixture
# --------------------------------------------------------------------------

def test_r19_the_campaign_never_writes_the_live_database(live_data_dir):
    """The ONLY test allowed to look at the operator's live data directory.

    It takes `live_data_dir` explicitly because the session default redirects
    `get_data_dir()` to a private root (see conftest: a whole-file tree of
    tests used to write into the real `data/files`). Reading the real path has
    to be asked for at the signature, or it is not a control over the real
    install at all.
    """
    live = Path(live_data_dir) / "local_data_v15.db"
    if not live.is_file():
        pytest.skip("no live database on this installation")
    before = live.stat().st_mtime_ns, live.stat().st_size

    # Pure resolution work, the kind every UI surface performs.
    sl.resolve_sound_ref("click.wav")
    sl.personal_audio_enabled()

    after = live.stat().st_mtime_ns, live.stat().st_size
    assert after == before


def test_r20_imported_fixtures_land_in_the_managed_root_not_the_shipped_one(
        tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    packaged = tmp_path / "packaged"
    packaged.mkdir(parents=True)
    source = _wav(tmp_path / "incoming.wav", b"FIXTURE")

    monkeypatch.setattr(sl, "ensure_managed_root", lambda: str(managed))
    ref = sl.import_file(str(source))

    assert ref.startswith("user:")
    assert (managed / "imported" / "incoming.wav").is_file()
    assert list(packaged.iterdir()) == []
