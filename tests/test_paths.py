"""Tests for fastprompter.utils.paths — path resolution utilities."""

import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastprompter.utils.paths import (
    exists_within,
    get_base_dir,
    get_data_dir,
    get_db_path,
    get_resource_path,
    isdir_within,
)


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
        """A name that exists nowhere still resolves under the base dir."""
        result = get_resource_path("sound", "definitely-not-a-real-file.wav")
        base = get_base_dir()
        assert result == os.path.join(base, "sound", "definitely-not-a-real-file.wav")
        assert os.path.isabs(result)

    def test_existing_resource_prefers_the_package_dir(self):
        """sound/ lives in src/fastprompter/, not at the project root, and
        get_resource_path is what papers over that in the source layout."""
        result = get_resource_path("sound", "click_soft.wav")
        assert os.path.exists(result)
        assert result.endswith(os.path.join("sound", "click_soft.wav"))

    def test_multiple_components(self):
        """Resources in the package dir (src/fastprompter/) are resolved there."""
        result = get_resource_path("theme", "themes.py")
        assert os.path.exists(result)
        assert result.endswith(os.path.join("theme", "themes.py"))

    def test_sound_dir_resolves_to_existing_files(self):
        """The sound/ resource dir must resolve to where the .wav files live."""
        result = get_resource_path("sound")
        assert os.path.isdir(result)
        # a shipped default, so this stays honest through a library rename
        from fastprompter.core.sound_manager import _DEFAULT_SOUND_MAP
        assert os.path.exists(os.path.join(result, _DEFAULT_SOUND_MAP["click"]))

    def test_no_components(self):
        """No args should return the base dir unchanged."""
        result = get_resource_path()
        base = get_base_dir()
        assert result == base


class TestExistsWithin:
    """The paste path probes the filesystem on the GUI thread.

    os.path.exists on an unreachable UNC path took a measured 93 SECONDS here,
    which the user experiences as the app hanging on Ctrl+V. These tests pin the
    bound, not the plumbing: a probe that cannot answer must be abandoned.
    """

    def test_answers_a_real_path(self):
        assert exists_within(os.path.dirname(__file__)) is True

    def test_answers_a_missing_path(self):
        assert exists_within(os.path.join(os.path.dirname(__file__), "no-such-file-xyz")) is False

    def test_a_hanging_probe_is_abandoned_not_awaited(self):
        """A probe that never returns must cost the caller the timeout, no more."""
        import threading
        import time

        started = threading.Event()
        release = threading.Event()

        class _Hangs:
            """os.stat() resolves this through __fspath__ — and waits there.

            Not a str subclass: os.path.exists takes a str as the path itself
            and never consults the protocol, so the probe would return at once.
            """

            def __fspath__(self):
                started.set()
                release.wait(30)          # stands in for the SMB connect
                return "/definitely/not/here"

        t = time.perf_counter()
        try:
            result = exists_within(_Hangs(), timeout=0.2)
            elapsed = time.perf_counter() - t
        finally:
            release.set()

        assert started.is_set(), "the probe never ran"
        assert result is False, "a probe that did not answer must not be trusted"
        assert elapsed < 2.0, f"caller was held for {elapsed:.1f}s despite a 0.2s bound"

    def test_timeout_is_not_charged_to_ordinary_paths(self):
        """The common case must not pay the timeout — it is a bound, not a sleep."""
        import time
        t = time.perf_counter()
        for _ in range(20):
            exists_within(os.path.dirname(__file__), timeout=5.0)
        assert time.perf_counter() - t < 1.0

    def test_isdir_within_answers_a_real_directory(self):
        assert isdir_within(os.path.dirname(__file__)) is True

    def test_isdir_within_rejects_a_file(self):
        assert isdir_within(__file__) is False

    def test_isdir_within_is_bounded_too(self):
        """Same guarantee as exists_within — the files root can be a share."""
        import threading
        import time

        release = threading.Event()

        class _Hangs:
            def __fspath__(self):
                release.wait(30)
                return "/definitely/not/here"

        t = time.perf_counter()
        try:
            result = isdir_within(_Hangs(), timeout=0.2)
            elapsed = time.perf_counter() - t
        finally:
            release.set()

        assert result is False
        assert elapsed < 2.0, f"caller was held for {elapsed:.1f}s"


class TestBoundedProbePool:
    """P1-16: a dead share can never accumulate unbounded probe threads.

    exists_within/isdir_within used to spawn one daemon thread per call, so a
    dead SMB host could pile up an unlimited number of stuck stacks. The pool
    is now strictly bounded: at most _MAX_STUCK_PROBES OS calls in flight,
    one probe per path while a probe is running, and a short negative cache.
    """

    def _hanging_path(self, started, release):
        """A path object whose __fspath__ blocks until ``release`` fires."""
        class _Hangs:
            def __fspath__(self):
                started.set()
                release.wait(30)
                return "/definitely/not/here"
        return _Hangs()

    def test_100_calls_cannot_spawn_more_than_max_probes(self):
        import fastprompter.utils.paths as paths_mod

        max_probes = paths_mod._MAX_STUCK_PROBES
        assert max_probes >= 1
        with paths_mod._PROBE_LOCK:
            paths_mod._PROBE_NEGATIVE.clear()
        blockers = []
        try:
            for _ in range(100):
                started = threading.Event()
                release = threading.Event()
                blockers.append((started, release))
                paths_mod.exists_within(
                    self._hanging_path(started, release), timeout=0.05)

            started_count = sum(1 for s, _r in blockers if s.is_set())
            assert started_count <= max_probes, (
                f"{started_count} probe threads started, cap is {max_probes}")
        finally:
            for _s, release in blockers:
                release.set()

    def test_duplicate_path_does_not_spawn_duplicate_probes(self):
        import time

        import fastprompter.utils.paths as paths_mod

        with paths_mod._PROBE_LOCK:
            paths_mod._PROBE_NEGATIVE.clear()
        started = threading.Event()
        release = threading.Event()
        path = self._hanging_path(started, release)
        try:
            # first call: probe starts and hangs inside the OS call
            assert paths_mod.exists_within(path, timeout=0.6) is False
            # second call while the first is STILL running: in-flight dedupe
            t = time.perf_counter()
            assert paths_mod.exists_within(path, timeout=0.6) is False
            assert time.perf_counter() - t < 0.3, "dup probe was not refused"
            assert started.is_set()
        finally:
            release.set()

    def test_capacity_recovers_when_probes_complete(self):
        import time

        import fastprompter.utils.paths as paths_mod

        with paths_mod._PROBE_LOCK:
            paths_mod._PROBE_NEGATIVE.clear()
        blockers = []
        try:
            for _ in range(paths_mod._MAX_STUCK_PROBES + 2):
                started = threading.Event()
                release = threading.Event()
                blockers.append((started, release))
                paths_mod.exists_within(
                    self._hanging_path(started, release), timeout=0.05)
            assert sum(1 for s, _r in blockers if s.is_set()) == \
                paths_mod._MAX_STUCK_PROBES
        finally:
            for _s, release in blockers:
                release.set()
        # wait until every stuck probe actually returned and released its slot
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with paths_mod._PROBE_LOCK:
                if not paths_mod._PROBE_INFLIGHT:
                    break
            time.sleep(0.02)
        with paths_mod._PROBE_LOCK:
            assert not paths_mod._PROBE_INFLIGHT, "probe slots never released"
        # a fresh probe now answers again: capacity recovered
        assert paths_mod.exists_within(os.path.dirname(__file__), timeout=2.0) is True
import pytest
import os
import subprocess
from pathlib import Path

def test_t1017_translation_sync_path_isolation(tmp_path):
    # Simulate pointing to a temporary clone worktree but trying to write to a hardcoded host path
    # We will create a fake root at tmp_path, and run sync_saitranslate.py with --root tmp_path
    # We'll patch sync_saitranslate.py so it tries to write outside the root.
    
    script_path = Path("tools/sync_saitranslate.py").resolve()
    assert script_path.exists()
    
    # Create fake project root structure
    src_dir = tmp_path / "src" / "fastprompter"
    src_dir.mkdir(parents=True)
    
    locales_dir = tmp_path / ".saipen" / "saitranslate" / "locales"
    locales_dir.mkdir(parents=True)
    
    # We will modify the script execution environment by running it through python
    # We'll use a wrapper script that imports sync_saitranslate and tries to call ensure_inside_root on an outside path.
    
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(f'''
import sys
import os
sys.path.insert(0, "{script_path.parent.as_posix()}")
import sync_saitranslate
from pathlib import Path

# We fake the sys.argv to pass the root
sys.argv = ["sync_saitranslate.py", "--root", r"{tmp_path.as_posix()}"]
try:
    sync_saitranslate.main()
except SystemExit as e:
    sys.exit(e.code)
''', encoding="utf-8")
    
    # Running normally should succeed (it finds nothing to process, or processes the fake dir)
    res = subprocess.run(["python", str(wrapper)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    
    # Now we inject an outside path into locales_dir
    outside_dir = tmp_path.parent / "outside_locales"
    outside_dir.mkdir(exist_ok=True)
    
    wrapper2 = tmp_path / "wrapper2.py"
    wrapper2.write_text(f'''
import sys
import os
sys.path.insert(0, "{script_path.parent.as_posix()}")
import sync_saitranslate
from pathlib import Path

# Monkeypatch os.path.join so that when it computes locales_dir it returns the outside directory
original_join = os.path.join
def fake_join(*args):
    if ".saipen" in args and "saitranslate" in args and "locales" in args:
        return r"{outside_dir.as_posix()}"
    return original_join(*args)

os.path.join = fake_join

sys.argv = ["sync_saitranslate.py", "--root", r"{tmp_path.as_posix()}"]
try:
    sync_saitranslate.main()
except SystemExit as e:
    sys.exit(e.code)
''', encoding="utf-8")
    
    res2 = subprocess.run(["python", str(wrapper2)], capture_output=True, text=True)
    assert res2.returncode == 1
    assert "Security Error" in res2.stderr
    assert "resolves outside the project root" in res2.stderr

