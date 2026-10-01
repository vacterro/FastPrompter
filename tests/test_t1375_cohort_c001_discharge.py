"""T-1375 -- C-001's publication record must survive the next edit.

The cohort's frozen per-member hashes were recorded at cohort time and describe
no tree that exists. They are deliberately NOT refreshed: they are the published
record of what the cohort claimed, and rewriting them to match whatever the
worktree happens to hold today would manufacture provenance. What must stay
true is the publication identity and the containment it asserts -- all twelve
scoped paths carried by tag v0.8.69, byte-identical to the tree at that tag.

`cohort ship C-001` is never run to produce this state. It refuses STALE_PLAN
permanently (the frozen plan disagrees with every scoped path) and the only
verb that could satisfy it is a re-freeze, which the engine does not have.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"C:/Users/vac34/.agents/skills/saipen/tools")
from saipen_engine import closure  # noqa: E402

SAIPEN = r"C:/Users/vac34/AppData/Local/saipen/scheduled-source/bin/saipen.cmd"
TAG = "v0.8.69"
TAG_COMMIT = "a655fdd0e145f5239be03a327a0a225b53256329"
# 2 of the 12 recorded hashes never correspond to any committed blob; the other
# 2 are superseded by later commits. Recorded as a constant so that a change
# here has to be a deliberate edit with a reason, not a silent drift.
EXPECTED_RECORDED_DRIFT = [
    "src/fastprompter/main.py",
    "src/fastprompter/ui/editor.py",
    "tests/test_clipboard_interop_t1269.py",
    "tests/test_editor_paste_live_t1269.py",
]


def _registry() -> dict:
    raw = (ROOT / ".saipen/kitchen/cohort_registry.json").read_bytes()
    return json.loads(raw.decode("utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def test_c001_carries_its_real_publication_identity():
    c = _registry()["cohorts"]["C-001"]
    assert c["publication_status"] == "shipped", c["publication_status"]
    assert c["release_op_id"] == "ship-t1351-0869", c["release_op_id"]
    assert c["version"] == "0.8.69", c["version"]
    assert c["tag"] == TAG, c["tag"]
    assert c["commit"] == TAG_COMMIT, c["commit"]
    # The identity must be a real published tag, not a string that parses.
    assert _git("rev-list", "-n", "1", TAG).stdout.decode().strip() == TAG_COMMIT


def test_both_cohorts_are_terminal_published():
    statuses = {cid: c["publication_status"] for cid, c in _registry()["cohorts"].items()}
    assert statuses == {"C-001": "shipped", "C-069": "shipped"}, statuses


@pytest.mark.skipif(not Path(SAIPEN).is_file(), reason="saipen launcher not present")
def test_a_second_ship_is_a_refusal_not_a_second_publication():
    done = subprocess.run(
        [SAIPEN, "cohort", "ship", "C-001"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    combined = done.stdout + done.stderr
    assert done.returncode != 0, combined
    assert "already published" in combined, combined


def test_the_published_tag_carries_every_scoped_path():
    c = _registry()["cohorts"]["C-001"]
    live = ROOT
    missing, differing, drifted = [], [], []
    for rel in c["scope"]:
        tagged = _git("show", f"{TAG}:{rel}").stdout
        if not tagged:
            missing.append(rel)
            continue
        if (live / rel).read_bytes() != tagged:
            differing.append(rel)
        if not closure.member_hash_matches(tagged, c["members"]["T-1269"]["paths"][rel]):
            drifted.append(rel)

    assert missing == [], missing
    assert differing == [], differing
    # Containment is the claim; the frozen hashes are the historical record and
    # are expected to disagree for four paths.
    assert drifted == EXPECTED_RECORDED_DRIFT, drifted
