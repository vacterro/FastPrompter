"""Concurrency and serialization tests for Set Defaults from Current (T-1445).

Verifies:
1. Same process / two threads serialization with bounded wait & fresh re-read.
2. Cross-process mutual exclusion using exclusive_file_lock.
3. Lock release on success.
4. Lock release on semantic failure.
5. Lock release on syntax/structural failure.
6. Lock release on exception during replace (and temp cleanup).
7. Busy timeout raises BakeBusyError boundedly.
8. Different targets do not serialize each other.
9. Path aliases (relative, absolute, case variants) resolve to identical lock identity.
10. Existing T-1443 contract: structure, SOURCE_OWNED, roundtrip, external SHA guard, dry-run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
for p in (_REPO_ROOT, _TOOLS_DIR, _SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.set_default_from_current import (
    BakeBusyError,
    BakeConcurrentModificationError,
    BakePolicyError,
    apply_bake_plan,
    bake_lock_path,
    bake_transaction_lock,
    build_bake_plan,
    canonical_target_path,
)
from tools.write_guard import is_file_locked

_SAMPLE_TARGET = '''"""Sample default profile."""

import copy

_HEADER_VAR = 42

DEFAULT_PROFILE = {
    "language": "EN",
    "theme": "Initial Theme",
}

def helper():
    return "TAIL"
'''


@pytest.fixture
def temp_target(tmp_path):
    target = tmp_path / "default_profile.py"
    target.write_text(_SAMPLE_TARGET, encoding="utf-8")
    return str(target)


class TestBakeConcurrencyT1445:
    """Requirement 1: Same process / two threads serialization."""

    def test_same_process_two_threads_serialize_safely(self, temp_target):
        plan_a = build_bake_plan({"theme": "Theme A"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)
        plan_b = build_bake_plan({"theme": "Theme B"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)

        barrier = threading.Barrier(2)
        results = {}
        errors = {}

        def run_writer(name, plan):
            try:
                barrier.wait(timeout=3.0)
                res = apply_bake_plan(plan, target_file=temp_target, timeout=5.0)
                results[name] = res
            except Exception as exc:
                errors[name] = exc

        t1 = threading.Thread(target=run_writer, args=("A", plan_a))
        t2 = threading.Thread(target=run_writer, args=("B", plan_b))

        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        assert not t1.is_alive()
        assert not t2.is_alive()
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 2

        final_content = open(temp_target, encoding="utf-8").read()
        # Must contain one of the themes cleanly formatted
        assert "Theme A" in final_content or "Theme B" in final_content
        assert "_HEADER_VAR = 42" in final_content
        assert "def helper():" in final_content
        # Lock must be released
        assert not is_file_locked(bake_lock_path(temp_target))

    def test_cross_process_mutual_exclusion(self, temp_target):
        """Requirement 2: Cross-process mutual exclusion via exclusive_file_lock."""
        script_code = f"""
import sys, os, time
sys.path.insert(0, r"{_REPO_ROOT}")
sys.path.insert(0, r"{_TOOLS_DIR}")
from tools.set_default_from_current import bake_transaction_lock, apply_bake_plan, build_bake_plan, BakeBusyError

mode = sys.argv[1]
target = r"{temp_target}"

if mode == "holder":
    with bake_transaction_lock(target, timeout=5.0):
        print("HOLDER_ACQUIRED", flush=True)
        time.sleep(0.6)
        print("HOLDER_DONE", flush=True)

elif mode == "contender_timeout":
    # Contender with very short timeout should fail with BakeBusyError
    try:
        plan = build_bake_plan({{'theme': 'Sub Theme'}}, base_defaults={{'theme': 'Initial Theme'}}, check_assets=False)
        apply_bake_plan(plan, target_file=target, timeout=0.1)
        print("CONTENDER_UNEXPECTED_SUCCESS", flush=True)
        sys.exit(2)
    except BakeBusyError:
        print("CONTENDER_BUSY_CAUGHT", flush=True)
        sys.exit(0)

elif mode == "contender_wait":
    # Contender with ample timeout should wait and succeed
    plan = build_bake_plan({{'theme': 'Waited Theme'}}, base_defaults={{'theme': 'Initial Theme'}}, check_assets=False)
    apply_bake_plan(plan, target_file=target, timeout=5.0)
    print("CONTENDER_WAITED_SUCCESS", flush=True)
    sys.exit(0)
"""
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
            tf.write(script_code)
            runner_script = tf.name

        try:
            # 1. Start holder process
            p_holder = subprocess.Popen(
                [sys.executable, runner_script, "holder"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # Wait until holder confirms lock acquired
            line = p_holder.stdout.readline()
            assert "HOLDER_ACQUIRED" in line

            # 2. Start contender with short timeout -> must catch BakeBusyError
            p_contender = subprocess.run(
                [sys.executable, runner_script, "contender_timeout"],
                capture_output=True,
                text=True,
            )
            assert p_contender.returncode == 0
            assert "CONTENDER_BUSY_CAUGHT" in p_contender.stdout

            # Wait for holder to finish
            p_holder.wait(timeout=5.0)
            assert p_holder.returncode == 0

            # 3. Now contender_wait should succeed immediately
            p_waiter = subprocess.run(
                [sys.executable, runner_script, "contender_wait"],
                capture_output=True,
                text=True,
            )
            assert p_waiter.returncode == 0
            assert "CONTENDER_WAITED_SUCCESS" in p_waiter.stdout

            content = open(temp_target, encoding="utf-8").read()
            assert "Waited Theme" in content
        finally:
            if os.path.exists(runner_script):
                os.remove(runner_script)

    def test_lock_release_on_success(self, temp_target):
        """Requirement 3: Successful bake releases lock; subsequent bake succeeds."""
        plan1 = build_bake_plan({"theme": "Success 1"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)
        res1 = apply_bake_plan(plan1, target_file=temp_target)
        assert res1["roundtrip_equal"] is True

        lock_p = bake_lock_path(temp_target)
        assert not is_file_locked(lock_p)

        plan2 = build_bake_plan({"theme": "Success 2"}, base_defaults={"theme": "Success 1"}, check_assets=False)
        res2 = apply_bake_plan(plan2, target_file=temp_target)
        assert res2["roundtrip_equal"] is True
        assert not is_file_locked(lock_p)

        content = open(temp_target, encoding="utf-8").read()
        assert "Success 2" in content

    def test_lock_release_on_semantic_failure(self, temp_target, monkeypatch):
        """Requirement 4: Force candidate roundtrip mismatch. Target unchanged, lock released, next bake succeeds."""
        import tools.set_default_from_current as sdc

        # Monkeypatch reload to return mismatched dict
        monkeypatch.setattr(sdc, "_reload_written_module", lambda path: {"theme": "TAMPERED"})

        plan = build_bake_plan({"theme": "Wanted Theme"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)
        with pytest.raises(RuntimeError, match="does not round-trip equal"):
            apply_bake_plan(plan, target_file=temp_target)

        # Target file must be unmodified
        content = open(temp_target, encoding="utf-8").read()
        assert "Initial Theme" in content
        assert "Wanted Theme" not in content

        # Lock must be released
        lock_p = bake_lock_path(temp_target)
        assert not is_file_locked(lock_p)

        # Restore reload; next valid bake must succeed
        monkeypatch.undo()
        valid_res = apply_bake_plan(plan, target_file=temp_target)
        assert valid_res["roundtrip_equal"] is True
        assert "Wanted Theme" in open(temp_target, encoding="utf-8").read()

    def test_lock_release_on_syntax_failure(self, temp_target):
        """Requirement 5: Malformed target / syntax failure releases lock."""
        # Corrupt the target file with invalid python syntax
        with open(temp_target, "w", encoding="utf-8") as f:
            f.write("def broken syntax ::: [[[\n")

        plan = build_bake_plan({"theme": "Theme"}, check_assets=False)
        with pytest.raises((SyntaxError, BakePolicyError)):
            apply_bake_plan(plan, target_file=temp_target)

        lock_p = bake_lock_path(temp_target)
        assert not is_file_locked(lock_p)

    def test_lock_release_on_replace_exception(self, temp_target, monkeypatch):
        """Requirement 6: Exception during os.replace releases lock and cleans candidate temp."""
        plan = build_bake_plan({"theme": "Theme Replace Fail"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)

        real_replace = os.replace

        def failing_replace(src, dst):
            if os.path.abspath(dst) == os.path.abspath(temp_target):
                raise OSError("Simulated disk replacement failure")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError, match="Simulated disk replacement failure"):
            apply_bake_plan(plan, target_file=temp_target)

        # Target unchanged
        content = open(temp_target, encoding="utf-8").read()
        assert "Initial Theme" in content
        assert "Theme Replace Fail" not in content

        # Lock released
        lock_p = bake_lock_path(temp_target)
        assert not is_file_locked(lock_p)

        # No dangling candidates in directory
        target_dir = os.path.dirname(os.path.abspath(temp_target))
        dangling = [f for f in os.listdir(target_dir) if f.startswith(".default_profile_candidate_")]
        assert len(dangling) == 0

        # Un-patch and verify next bake succeeds
        monkeypatch.undo()
        res = apply_bake_plan(plan, target_file=temp_target)
        assert res["roundtrip_equal"] is True
        assert "Theme Replace Fail" in open(temp_target, encoding="utf-8").read()

    def test_busy_timeout_bounded_error(self, temp_target):
        """Requirement 7: Writer holding lock longer than timeout causes second caller to fail boundedly."""
        plan = build_bake_plan({"theme": "Contender Theme"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)

        with bake_transaction_lock(temp_target):
            # Lock is held; caller with timeout 0.1s must fail boundedly
            t0 = time.monotonic()
            with pytest.raises(BakeBusyError, match="already in progress"):
                apply_bake_plan(plan, target_file=temp_target, timeout=0.1)
            elapsed = time.monotonic() - t0
            assert elapsed < 1.0, f"Expected bounded timeout < 1.0s, took {elapsed}s"

        # After releasing, caller succeeds
        res = apply_bake_plan(plan, target_file=temp_target)
        assert res["roundtrip_equal"] is True

    def test_different_targets_do_not_block_each_other(self, tmp_path):
        """Requirement 8: Different targets do not unnecessarily serialize each other."""
        target1 = str(tmp_path / "target1.py")
        target2 = str(tmp_path / "target2.py")
        for t in (target1, target2):
            with open(t, "w", encoding="utf-8") as f:
                f.write(_SAMPLE_TARGET)

        plan = build_bake_plan({"theme": "Theme Parallel"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)

        # Hold target1 lock
        with bake_transaction_lock(target1):
            # target2 bake must succeed immediately even while target1 is locked
            t0 = time.monotonic()
            res = apply_bake_plan(plan, target_file=target2, timeout=0.5)
            elapsed = time.monotonic() - t0
            assert elapsed < 0.4
            assert res["roundtrip_equal"] is True

        assert "Theme Parallel" in open(target2, encoding="utf-8").read()

    def test_path_aliases_resolve_to_same_lock(self, temp_target):
        """Requirement 9: Normalized equivalent paths resolve to identical lock identity."""
        abs_p = os.path.abspath(temp_target)
        norm_p = os.path.normpath(temp_target)
        rel_p = os.path.relpath(temp_target)

        id_abs = canonical_target_path(abs_p)
        id_norm = canonical_target_path(norm_p)
        id_rel = canonical_target_path(rel_p)

        assert id_abs == id_norm
        assert id_abs == id_rel
        assert bake_lock_path(abs_p) == bake_lock_path(rel_p)

        if sys.platform == "win32":
            upper_p = abs_p.upper()
            lower_p = abs_p.lower()
            assert canonical_target_path(upper_p) == canonical_target_path(lower_p)
            assert bake_lock_path(upper_p) == bake_lock_path(lower_p)

            # Holding lock on uppercase alias blocks lowercase alias
            with bake_transaction_lock(upper_p):
                plan = build_bake_plan({"theme": "Alias Theme"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)
                with pytest.raises(BakeBusyError):
                    apply_bake_plan(plan, target_file=lower_p, timeout=0.1)

    def test_dry_run_is_unlocked_and_write_free(self, temp_target):
        """Requirement 10: dry_run=True is write-free and does not hold writer lock."""
        orig_content = open(temp_target, encoding="utf-8").read()

        plan = build_bake_plan({"theme": "Dry Theme"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)
        preview = apply_bake_plan(plan, target_file=temp_target, dry_run=True)

        assert preview["dry_run"] is True
        assert preview["roundtrip_equal"] is None

        # Target file untouched
        current_content = open(temp_target, encoding="utf-8").read()
        assert current_content == orig_content

        # Lock is not held
        assert not is_file_locked(bake_lock_path(temp_target))

    def test_external_concurrent_modification_rejected(self, temp_target, monkeypatch):
        """Requirement 10: Target modification by an external non-cooperative writer raises BakeConcurrentModificationError."""
        plan = build_bake_plan({"theme": "Cooperative"}, base_defaults={"theme": "Initial Theme"}, check_assets=False)

        import tools.set_default_from_current as sdc
        orig_format = sdc.format_default_profile_py

        def concurrent_tamper(profile, src):
            # External out-of-band writer modifies the target during formatting
            with open(temp_target, "a", encoding="utf-8") as f:
                f.write("\n# OUT_OF_BAND_EDIT = True\n")
            return orig_format(profile, src)

        monkeypatch.setattr(sdc, "format_default_profile_py", concurrent_tamper)

        with pytest.raises(BakeConcurrentModificationError, match="modified concurrently during bake"):
            apply_bake_plan(plan, target_file=temp_target)

        # Lock is released
        assert not is_file_locked(bake_lock_path(temp_target))
