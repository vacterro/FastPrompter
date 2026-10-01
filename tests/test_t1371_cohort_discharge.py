"""T-1371 -- cohort C-069's publication obligation is discharged, not owed.

Tracked form of the closure check (build/ is gitignored, so a check living
there could not be replayed by a cold agent from the recorded reverify
command). Three properties, each checked against git and the live engine
rather than against prose:

  1. The registry row carries a real publication identity, and `cohort ship`
     refuses with the already-published reason instead of publishing again.
  2. The named tag really contains the cohort's content -- measured with the
     engine's OWN hash tolerance, against the hashes as the members closed
     them, never against live bytes.
  3. T-1355's clause holds on the published pyproject.toml and uv.lock.

The assertion on property 2 names the IDENTITY of the drifted path, not
just how many there are. That is deliberate: rewriting both drifted hashes
to live bytes -- the falsification this ticket exists to catch -- moves one
path out and one path in, leaving the count at 50/51 while moving the
exception from T-1355/pyproject.toml to T-1354/README.md. The count alone
does not discriminate; the identity does.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"C:/Users/vac34/.agents/skills/saipen/tools")
from saipen_engine import closure  # noqa: E402

SAIPEN = r"C:/Users/vac34/AppData/Local/saipen/scheduled-source/bin/saipen.cmd"
TAG_COMMIT = "a655fdd0e145f5239be03a327a0a225b53256329"
EXPECTED_DRIFT = [("T-1355", "pyproject.toml", "tag bytes differ from the recorded hash")]


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         errors="replace")
    assert out.returncode == 0, out.stderr
    return out.stdout


def _tag_blobs(commit: str) -> dict[str, str]:
    blobs = {}
    for line in _git("ls-tree", "-r", commit).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3:
            blobs[path] = parts[2]
    return blobs


def _containment(cohort: dict, blobs: dict[str, str]) -> tuple[int, int, list]:
    """How many attributed paths are byte-identical in the tag, under the
    engine's own tolerance. Never compares against live worktree bytes."""
    cache: dict[str, bytes] = {}
    ok = total = 0
    drifted = []
    for work, member in sorted(cohort["members"].items()):
        for rel, digest in sorted(member["paths"].items()):
            total += 1
            blob = blobs.get(rel)
            if blob is None:
                drifted.append((work, rel, "absent from tag"))
                continue
            if blob not in cache:
                cache[blob] = subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT,
                                            capture_output=True).stdout
            if closure.member_hash_matches(cache[blob], digest):
                ok += 1
            else:
                drifted.append((work, rel, "tag bytes differ from the recorded hash"))
    return ok, total, drifted


def test_c069_carries_its_real_publication_identity():
    c069 = closure.read_registry(ROOT)["cohorts"]["C-069"]
    assert c069["publication_status"] == "shipped"
    assert c069["release_op_id"] == "ship-t1351-0869"
    assert c069["version"] == "0.8.69"
    assert c069["tag"] == "v0.8.69"
    assert c069["commit"] == TAG_COMMIT


@pytest.mark.skipif(not Path(SAIPEN).is_file(), reason="saipen launcher not present")
def test_second_ship_is_a_refusal_not_a_second_publication():
    out = subprocess.run([SAIPEN, "cohort", "ship", "C-069", "--dry-run"], cwd=ROOT,
                         capture_output=True, text=True, errors="replace")
    assert "already published" in out.stdout + out.stderr, out.stdout + out.stderr


def test_the_published_tag_contains_the_cohort():
    c069 = closure.read_registry(ROOT)["cohorts"]["C-069"]
    ok, total, drifted = _containment(c069, _tag_blobs(TAG_COMMIT))
    assert (total, ok) == (51, 50), (ok, total, drifted)
    # the identity, not just the count -- see the module docstring
    assert drifted == EXPECTED_DRIFT, drifted


def test_t1355_clause_holds_on_the_published_bytes():
    assert 'build = ["nuitka==4.2.1"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'specifier = "==4.2.1"' in lock
    assert 'version = "4.2.1"' in lock
