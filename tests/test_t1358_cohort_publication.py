"""Regression coverage for T-1358: cohort publication authority and member identity.

Verifies:
1. .saipen/kitchen/cohort_registry.json is trackable (not gitignored).
2. release._closure_stage_paths stages cohort_registry.json atomically with closure.
3. closure.member_hash_matches handles proven Git text normalization without binary/source drift.
4. Existing cohort records (C-001, C-069) are preserved.
5. Clean-clone resolution succeeds when cohort_registry.json is present.
"""

import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Resolve saipen_engine from installed saipen_home (or STATE.md)
SAIPEN_HOME = Path("C:/Users/vac34/.agents/skills/saipen")
SAIPEN_TOOLS = SAIPEN_HOME / "tools"
if str(SAIPEN_TOOLS) not in sys.path:
    sys.path.insert(0, str(SAIPEN_TOOLS))


def test_cohort_registry_not_gitignored():
    """Git must not ignore .saipen/kitchen/cohort_registry.json."""
    res = subprocess.run(
        ["git", "check-ignore", ".saipen/kitchen/cohort_registry.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1, (
        ".saipen/kitchen/cohort_registry.json is ignored by git: "
        f"{res.stdout.strip()}"
    )


def test_closure_stage_includes_cohort_registry():
    """_closure_stage_paths must include cohort_registry.json when it exists."""
    from saipen_engine.release import CLOSURE_FILES, _closure_stage_paths

    assert ".saipen/kitchen/cohort_registry.json" in CLOSURE_FILES
    staged = _closure_stage_paths(ROOT)
    assert ".saipen/kitchen/cohort_registry.json" in staged


def test_member_hash_matches_proven_text_normalization():
    """member_hash_matches handles Git text normalization without binary/source drift."""
    from saipen_engine import closure
    from saipen_engine.journal import hash_bytes

    assert hasattr(closure, "member_hash_matches"), "closure must export member_hash_matches"

    # Known T-1355 pyproject.toml pair from t1358_cohort_clone_audit.json
    recorded_crlf_hash = "2bf394ee164bf134"
    clean_clone_lf_hash = "3eedf7cf1da61657"

    sample_lf = b'[project]\nname = "fastprompter"\nversion = "0.8.69"\n'
    sample_crlf = b'[project]\r\nname = "fastprompter"\r\nversion = "0.8.69"\r\n'

    h_lf = hash_bytes(sample_lf)
    h_crlf = hash_bytes(sample_crlf)

    # Verbatim matches
    assert closure.member_hash_matches(sample_lf, h_lf)
    assert closure.member_hash_matches(sample_crlf, h_crlf)

    # Cross-normalization matches (Git text normalization)
    assert closure.member_hash_matches(sample_lf, h_crlf)
    assert closure.member_hash_matches(sample_crlf, h_lf)

    # Real pyproject.toml in the worktree. This assertion used to require BOTH
    # the recorded cohort hash and the clean-clone hash to match the live file,
    # which pinned the working tree to its state when T-1355 closed (08:34:13Z
    # on 30.09.26). pyproject.toml was legitimately committed afterwards
    # (a655fdd, 20:09:36+03:00 = 17:09:36Z, "freeze the reviewed 0.8.69"),
    # so the recorded hash describes a file that no longer exists. That made
    # this test a time bomb rather than a contract: T-1351/T-1375 established
    # the C-069 hashes are unrecoverable (4 of 6 match no blob in any ref), so
    # no repair can restore the old bytes.
    #
    # What is still worth asserting is that the matcher tells the two states
    # apart: the live file must match the CURRENT content, and must NOT match
    # the historical cohort hash.
    pyproject_bytes = (ROOT / "pyproject.toml").read_bytes()
    assert closure.member_hash_matches(pyproject_bytes, clean_clone_lf_hash)
    assert not closure.member_hash_matches(pyproject_bytes, recorded_crlf_hash)

    # Substantive source drift is REFUSED
    drift_text = b'[project]\nname = "fastprompter"\nversion = "0.8.70"\n'
    assert not closure.member_hash_matches(drift_text, h_lf)
    assert not closure.member_hash_matches(drift_text, h_crlf)

    # Binary data (with NUL or invalid UTF-8) is NEVER normalized
    binary_sample = b"\x00\x01\x02\r\n\x03\x04"
    h_bin = hash_bytes(binary_sample)
    assert closure.member_hash_matches(binary_sample, h_bin)
    # Altering CR/LF in binary must NOT match
    binary_altered = b"\x00\x01\x02\n\x03\x04"
    assert not closure.member_hash_matches(binary_altered, h_bin)


def test_existing_cohort_records_preserved():
    """Existing cohort records C-001 and C-069 must remain intact."""
    from saipen_engine import closure

    registry = closure.read_registry(ROOT)
    cohorts = registry.get("cohorts", {})
    assert "C-001" in cohorts
    assert "C-069" in cohorts

    c069 = cohorts["C-069"]
    members = c069.get("members", {})
    assert set(members.keys()) == {"T-1352", "T-1354", "T-1355"}

    # Exact recorded hash of pyproject.toml in T-1355 must be preserved
    t1355_paths = members["T-1355"].get("paths", {})
    assert t1355_paths.get("pyproject.toml") == "2bf394ee164bf134"


def test_cohort_member_mismatches_reports_only_genuinely_drifted_paths():
    """Every mismatch C-069 reports must be a file legitimately changed after
    the cohort member closed.

    This used to assert `mismatches == []`, which was a time bomb: it asserted
    that the working tree still equals its state when T-1354/T-1355 closed
    (08:02:05Z / 08:34:13Z on 30.09.26). Two scoped files were legitimately
    committed afterwards, and T-1351 established that 4 of C-069's 6 recorded
    hashes match no blob in any ref -- so the old bytes are unrecoverable and
    "zero mismatches" can never hold again for any repair.

    The detector's actual contract is that it FINDS drift, so assert that
    against an independent oracle -- git history, not a reimplementation of the
    hash function under test:

      (a) each reported mismatch is a file whose last commit is LATER than the
          owning member's closed_at (the drift is real history, not a bug), and
      (b) the reported set is non-empty, so the test cannot pass vacuously by
          the detector silently returning nothing.
    """
    from saipen_engine import closure

    registry = closure.read_registry(ROOT)
    c069 = registry["cohorts"]["C-069"]
    members = c069["members"]

    mismatches = closure.cohort_member_mismatches(ROOT, c069)
    assert mismatches, (
        "expected C-069 to report drifted member paths; an empty set here means "
        "either the cohort hashes were refreshed (update this test) or the "
        "detector stopped working"
    )

    for entry in mismatches:
        work, path = entry["work"], entry["path"]
        closed_at = members[work]["closed_at"]
        commit = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert commit.returncode == 0, f"git log failed for {path}: {commit.stderr}"
        last_change = commit.stdout.strip()
        assert last_change, f"{path} has no commit history but is reported as drifted"
        # Compare as INSTANTS, not as strings: git emits a numeric offset
        # ("2026-09-30T22:12:04+03:00") while the registry records Z, so a
        # lexicographic compare is wrong whenever the offsets differ -- 09:00
        # +03:00 is 06:00Z and sorts after "08:00Z" as text. This is the same
        # trap as the quota-reset contract (T-1378).
        last_instant = datetime.datetime.fromisoformat(last_change)
        closed_instant = datetime.datetime.fromisoformat(closed_at)
        assert last_instant > closed_instant, (
            f"{path} reported as drifted for {work}, but its last commit "
            f"({last_change} = {last_instant.astimezone(datetime.UTC)}) is NOT after "
            f"the member's closed_at ({closed_at} = {closed_instant.astimezone(datetime.UTC)}) "
            "-- that would be a genuine hash mismatch, not later legitimate drift"
        )


def test_fresh_clone_resolves_published_c069(tmp_path):
    """In a fresh clone with cohort_registry present, published C-069 members resolve."""
    import shutil

    from saipen_engine import closure

    # Simulate fresh clone directory structure
    clone_saipen = tmp_path / ".saipen"
    clone_kitchen = clone_saipen / "kitchen"
    clone_kitchen.mkdir(parents=True)

    # Copy BOARD.md and STATE.md
    shutil.copy(ROOT / ".saipen" / "BOARD.md", clone_saipen / "BOARD.md")
    shutil.copy(ROOT / ".saipen" / "STATE.md", clone_saipen / "STATE.md")

    # Read registry and mark C-069 published as it would be after cohort_ship
    reg = closure.read_registry(ROOT)
    reg["cohorts"]["C-069"].update(
        {
            "publication_status": "shipped",
            "release_op_id": "release-0869",
            "version": "0.8.69",
            "tag": "v0.8.69",
            "commit": "17cb7937428a875f416fc35b4f1ed6d26cd347b6",
        }
    )
    (clone_kitchen / "cohort_registry.json").write_text(
        closure.render_registry(reg), encoding="utf-8"
    )

    # Resolve all three members in the fresh clone
    for tid in ("T-1352", "T-1354", "T-1355"):
        verdict = closure.resolve_implementation_source(tmp_path, tid)
        assert verdict.ok, f"{tid} failed to resolve in fresh clone: {verdict.detail}"
        assert "published through cohort C-069" in verdict.detail
