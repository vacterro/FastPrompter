"""T-1457-C: the user's own drop-in sound folder.

``<user-data>/addon/sounds`` is the ONE place a user may drop their own WAV
files.  It is created on first run with an instructions file, it is resolved
through the same containment rules as every other sound root, and nothing in
it is ever copied, executed or deleted by the app.

The directory is derived from the application's real user-data root, so these
tests monkeypatch ``get_data_dir`` rather than assuming any repository- or
developer-specific absolute path.
"""

from __future__ import annotations

import os
import struct
import sys
import wave

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src")))

import pytest  # noqa: E402

from fastprompter.core import sound_library  # noqa: E402


def _wav(path: str, seconds: float = 0.01) -> None:
    """Write a real, playable PCM WAV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = int(8000 * seconds)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(struct.pack("<h", 0) * frames)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A private user-data root; the app's own root is never touched."""
    monkeypatch.setattr(sound_library, "get_data_dir", lambda: str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# A -- the folder itself
# ---------------------------------------------------------------------------

class TestAddonFolder:
    def test_the_folder_is_built_from_the_user_data_root(self, data_root):
        root = sound_library.addon_root()
        assert root == os.path.join(str(data_root), "addon", "sounds")
        # No repository-relative or developer-specific path may leak in.
        assert "src" + os.sep + "fastprompter" not in root

    def test_first_run_creates_the_folder_and_its_instructions(self, data_root):
        root = sound_library.ensure_addon_root()
        assert os.path.isdir(root)
        info = os.path.join(root, sound_library.ADDON_INFO_NAME)
        assert os.path.isfile(info)
        text = open(info, encoding="utf-8").read()
        assert ".wav" in text
        assert "addon:" in text
        # English, and readable without any locale pack.
        assert all(ord(ch) < 128 for ch in text)

    def test_a_second_run_is_idempotent_and_keeps_user_files(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "mine.wav"))
        info = os.path.join(root, sound_library.ADDON_INFO_NAME)
        with open(info, "a", encoding="utf-8") as fh:
            fh.write("\nmy own note\n")

        before = sorted(os.listdir(root))
        assert sound_library.ensure_addon_root() == root
        assert sorted(os.listdir(root)) == before
        assert "my own note" in open(info, encoding="utf-8").read()

    def test_a_read_only_root_is_survivable(self, data_root, monkeypatch):
        """A vanished/unwritable user-data dir must not stop the app."""
        monkeypatch.setattr(
            sound_library.os, "makedirs",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("read-only")))
        root = sound_library.ensure_addon_root()   # must not raise
        assert root == sound_library.addon_root()

    def test_an_unwritable_info_file_is_survivable(self, data_root, monkeypatch):
        def _boom(*a, **kw):
            raise OSError("read-only")

        monkeypatch.setattr("builtins.open", _boom)
        sound_library.ensure_addon_root()      # must not raise


# ---------------------------------------------------------------------------
# B -- discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_only_real_wav_files_are_offered(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "good.wav"))
        with open(os.path.join(root, "notes.txt"), "w") as fh:
            fh.write("x")
        with open(os.path.join(root, "broken.wav"), "wb") as fh:
            fh.write(b"this is not a riff file at all")
        with open(os.path.join(root, "empty.wav"), "wb") as fh:
            pass

        refs = sound_library.list_addon_sounds()
        assert refs == ["addon:good.wav"]

    def test_subfolders_are_found_and_refs_are_forward_slashed(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "sub", "deep.wav"))
        assert sound_library.list_addon_sounds() == ["addon:sub/deep.wav"]

    def test_private_names_are_skipped(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "public.wav"))
        _wav(os.path.join(root, "_scratch", "hidden.wav"))
        _wav(os.path.join(root, "_hidden.wav"))
        assert sound_library.list_addon_sounds() == ["addon:public.wav"]

    def test_a_missing_folder_is_an_empty_list_not_an_error(self, data_root):
        assert sound_library.list_addon_sounds() == []

    def test_identity_is_deterministic_and_rescan_never_duplicates(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "b.wav"))
        _wav(os.path.join(root, "a.wav"))
        first = sound_library.list_addon_sounds()
        assert first == ["addon:a.wav", "addon:b.wav"]
        for _ in range(5):
            assert sound_library.list_addon_sounds() == first
        assert len(set(first)) == len(first)

    def test_the_instructions_file_is_never_offered_as_a_sound(self, data_root):
        sound_library.ensure_addon_root()
        assert sound_library.list_addon_sounds() == []


# ---------------------------------------------------------------------------
# C -- the resolver
# ---------------------------------------------------------------------------

class TestResolution:
    def test_an_addon_ref_resolves_to_the_users_own_file(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "mine.wav"))
        assert sound_library.resolve_sound_ref("addon:mine.wav") == \
            os.path.join(root, "mine.wav")

    def test_the_managed_root_is_not_searched_for_an_addon_ref(
            self, data_root, tmp_path):
        """Identity is the namespace, not the file name: an addon ref must
        never be answered by an unrelated file in the managed library."""
        managed = tmp_path / "sound_library"
        _wav(str(managed / "mine.wav"))
        assert sound_library.resolve_sound_ref(
            "addon:mine.wav",
            addon_root_path=str(tmp_path / "addon" / "sounds")) is None

    def test_traversal_and_absolute_addon_refs_stay_rejected(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "ok.wav"))
        for ref in ("addon:../ok.wav", "addon:..\\ok.wav",
                    "addon:C:/windows/ok.wav", "addon:/etc/ok.wav",
                    "addon://server/share/ok.wav", "addon:", "addon:  "):
            assert sound_library.resolve_sound_ref(ref) is None, ref

    def test_a_non_wav_addon_ref_is_never_playable(self, data_root):
        root = sound_library.ensure_addon_root()
        with open(os.path.join(root, "evil.exe"), "wb") as fh:
            fh.write(b"MZ")
        assert sound_library.resolve_sound_ref("addon:evil.exe") is None

    def test_the_legacy_bare_form_reaches_the_addon_folder_last(self, data_root):
        """A bare ref still prefers the packaged and managed roots."""
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "legacy.wav"))
        builtin = str(data_root / "packaged")
        managed = str(data_root / "managed")
        assert sound_library.resolve_sound_ref(
            "legacy.wav", builtin_root=builtin, user_root=managed) == \
            os.path.join(root, "legacy.wav")

    def test_namespaces_are_distinguished(self):
        assert sound_library.split_ref("addon:a.wav") == ("addon", "a.wav")
        assert sound_library.is_addon_ref("addon:a.wav") is True
        assert sound_library.is_managed_ref("addon:a.wav") is False
        assert sound_library.is_addon_ref("user:a.wav") is False
        assert sound_library.make_addon_ref("sub\\a.wav") == "addon:sub/a.wav"
        assert sound_library.make_addon_ref("../a.wav") == ""


# ---------------------------------------------------------------------------
# D -- the app never owns, copies or executes what it finds
# ---------------------------------------------------------------------------

class TestOwnership:
    def test_the_managed_remove_action_cannot_delete_an_addon_file(self, data_root):
        root = sound_library.ensure_addon_root()
        path = os.path.join(root, "mine.wav")
        _wav(path)
        assert sound_library.remove_managed_sound("addon:mine.wav") is False
        assert os.path.isfile(path)

    def test_discovery_performs_no_write(self, data_root):
        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "mine.wav"))
        before = {name: os.path.getmtime(os.path.join(root, name))
                  for name in os.listdir(root)}
        sound_library.list_addon_sounds()
        after = {name: os.path.getmtime(os.path.join(root, name))
                 for name in os.listdir(root)}
        assert before == after

    def test_the_source_never_executes_anything_from_the_addon_folder(self):
        """Discovery is data-only: no import, no eval, no plugin hook."""
        import inspect

        for name in ("list_addon_sounds", "ensure_addon_root",
                     "resolve_sound_ref", "_looks_like_playable_wav"):
            source = inspect.getsource(getattr(sound_library, name))
            for banned in ("importlib", "exec(", "eval(", "subprocess",
                           "os.startfile", "runpy", "__import__"):
                assert banned not in source, f"{name} contains {banned!r}"


# ---------------------------------------------------------------------------
# E -- picker integration
# ---------------------------------------------------------------------------

class TestPickerIntegration:
    def test_the_picker_list_includes_addon_sounds_without_duplicates(
            self, data_root, monkeypatch):
        from fastprompter.ui import sound_settings_dialog as ssd

        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "mine.wav"))

        class _Mgr:
            def get_available_sounds(self):
                return ["newday.wav", "addon:mine.wav"]   # already present

            def invalidate_cache(self):
                pass

        dialog = ssd.SoundSettingsDialog.__new__(ssd.SoundSettingsDialog)
        dialog._sound_manager = _Mgr()
        names = dialog._collect_available()
        assert names.count("addon:mine.wav") == 1
        assert "newday.wav" in names

    def test_the_ambience_picker_offers_addon_sounds(self, data_root):
        import types as _types

        from fastprompter.ui import audio_hub_pages as pages

        root = sound_library.ensure_addon_root()
        _wav(os.path.join(root, "mine.wav"))

        class _Dialog:
            _available = ["newday.wav"]

        # The real method with a minimal receiver: it only reads
        # self.dialog._available plus the two library listings.
        receiver = _types.SimpleNamespace(dialog=_Dialog())
        refs = pages.AmbiencePage._sound_refs(receiver)
        assert "addon:mine.wav" in refs
        assert refs.count("addon:mine.wav") == 1
