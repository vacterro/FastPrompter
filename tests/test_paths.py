"""Tests for fastprompter.utils.paths — path resolution utilities."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.utils.paths import get_base_dir, get_data_dir, get_db_path, get_resource_path


class TestGetBaseDir:
    def test_returns_string(self):
        """get_base_dir should always return a non-empty string."""
        result = get_base_dir()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_absolute_path(self):
        """get_base_dir should return an absolute path."""
        result = get_base_dir()
        assert os.path.isabs(result)

    def test_contains_project_name(self):
        """The base directory should contain 'FastPrompter' or the project."""
        result = get_base_dir()
        # When running from source, it resolves to project root
        assert (
            "FastPrompter" in result
            or "fastprompter" in result.lower()
            or "_FastPrompter" in result
        )

    def test_traverses_up_from_utils(self):
        """When running from source, it should go up from utils/ to project root."""
        result = get_base_dir()
        # The function does: join(__file__, ../..) → goes up 3 levels from utils/paths.py
        # __file__ → .../utils/paths.py → .../fastprompter → .../src → project root
        assert os.path.isdir(result)


class TestGetDataDir:
    def test_returns_string(self):
        """get_data_dir should always return a non-empty string."""
        result = get_data_dir()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_absolute_path(self):
        """get_data_dir should return an absolute path."""
        result = get_data_dir()
        assert os.path.isabs(result)

    def test_ends_with_data_dirname(self):
        """The data directory should end with 'data' (portable) or 'FastPrompter' (AppData fallback)."""
        result = get_data_dir()
        assert result.endswith("data") or result.endswith("FastPrompter")

    def test_creates_directory(self, tmp_path):
        """get_data_dir should create the directory if it doesn't exist."""
        result = get_data_dir()
        assert os.path.isdir(result)


class TestGetDbPath:
    def test_default_profile(self):
        """Default profile (1) should use 'local_data_v15.db'."""
        path = get_db_path()
        assert path.endswith("local_data_v15.db")
        assert os.path.isabs(path)

    def test_custom_profile(self):
        """Profile 2 should use '_p2' suffix."""
        path = get_db_path(2)
        assert path.endswith("local_data_v15_p2.db")
        assert os.path.isabs(path)

    def test_profile_3(self):
        """Profile 3 should use '_p3' suffix."""
        path = get_db_path(3)
        assert path.endswith("local_data_v15_p3.db")

    def test_data_dir_contains_db(self):
        """The DB path should be inside the data directory."""
        db_path = get_db_path()
        data_dir = get_data_dir()
        assert db_path.startswith(data_dir)


class TestGetResourcePath:
    def test_single_component(self):
        """Join base dir with a single path component."""
        result = get_resource_path("sound", "click.wav")
        base = get_base_dir()
        assert result == os.path.join(base, "sound", "click.wav")
        assert os.path.isabs(result)

    def test_multiple_components(self):
        """Resources in the package dir (src/fastprompter/) are resolved there."""
        result = get_resource_path("theme", "themes.py")
        assert os.path.exists(result)
        assert result.endswith(os.path.join("theme", "themes.py"))

    def test_sound_dir_resolves_to_existing_files(self):
        """The sound/ resource dir must resolve to where the .wav files live."""
        result = get_resource_path("sound")
        assert os.path.isdir(result)
        assert os.path.exists(os.path.join(result, "button1.wav"))

    def test_no_components(self):
        """No args should return the base dir unchanged."""
        result = get_resource_path()
        base = get_base_dir()
        assert result == base
