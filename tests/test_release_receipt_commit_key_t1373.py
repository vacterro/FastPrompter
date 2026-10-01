"""T-1373: the release receipt and the engine that reads it.

WHAT THIS TICKET WAS WRONG ABOUT
-------------------------------
The ticket was filed as "the writer is missing the `commit` key". Measured
against the CURRENT engine that is false: `closure._is_published` accepts
EITHER spelling since T-1238, which added `or record.get("release_commit")`
with a comment naming this very writer. The closure-provenance FAIL for
`release:0.8.68` is produced only by the STALE engine copy that
`tools/validate.py` binds (see the module-level note on SAIPEN_HOME below).

So the writer change kept here is FORWARD COMPATIBILITY, not the fix: a
receipt carrying `commit` stays legible to an engine generation that predates
the T-1238 fallback. The tests below assert what is actually true rather than
the premise the ticket arrived with.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# The oracle MUST be the same engine every other engine-reading test binds.
# Python caches `saipen_engine` in sys.modules on first import, so whichever
# test imports it first silently fixes the engine for the whole session. This
# file therefore pins the skill home explicitly instead of reading SAIPEN_HOME:
# on this machine that env var points at the stale scheduled-source copy
# (98 engine modules, closure.py without cohort_member_mismatches), and
# honouring it here broke tests/test_t1358_cohort_publication.py for everyone.
SAIPEN_HOME = Path(r"C:\Users\vac34\.agents\skills\saipen")
ENGINE_TOOLS = SAIPEN_HOME / "tools"
REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (ENGINE_TOOLS / "saipen_engine" / "closure.py").is_file(),
    reason="SAIPEN engine not installed",
)


@pytest.fixture(scope="module")
def closure():
    if str(ENGINE_TOOLS) not in sys.path:
        sys.path.insert(0, str(ENGINE_TOOLS))
    from saipen_engine import closure as mod

    return mod


@pytest.fixture(scope="module")
def writer_source():
    """The writer's SOURCE, because its output cannot be produced here.

    `build_receipt` needs a built EXE, a clean tree and a tagged release, so
    the only thing testable offline is the key set the writer emits.
    """
    return (REPO_ROOT / "tools" / "release_provenance.py").read_text(encoding="utf-8")


def _receipt(**overrides):
    head = "1d7765b677fe3275cf2cf5914eb73f6b17becbcc"
    base = {
        "schema_version": 1,
        "operation": "release_receipt",
        "version": "0.8.68",
        "tag": "v0.8.68",
        "release_commit": head,
    }
    base.update(overrides)
    return base


def test_writer_emits_the_commit_key(writer_source):
    """Forward compatibility with pre-T-1238 engine generations.

    The current engine reads `release_commit` too, so this is not what clears
    today's gate -- it is what stops the receipt from going invisible again if
    an older validator ever validates this tree.
    """
    assert '"commit": head,' in writer_source, (
        "tools/release_provenance.py must write `commit` as well as "
        "`release_commit`, so receipts stay legible to engine generations "
        "that predate the T-1238 fallback"
    )


def test_writer_keeps_release_commit_for_its_own_reader(writer_source):
    """The provenance reader still checks release_commit -- dropping it would
    turn the writer change into a new breakage."""
    assert '"release_commit": head,' in writer_source
    assert 'receipt.get("release_commit")' in writer_source


def test_engine_accepts_a_receipt_this_writer_produces(closure):
    """The end-to-end claim: the writer's output shape passes the engine gate."""
    receipt = _receipt(commit=_receipt()["release_commit"])
    assert closure._is_published(receipt)
    assert closure._release_matches(receipt, "0.8.68")


def test_both_spellings_are_publication_evidence(closure):
    """The T-1238 fallback, asserted rather than assumed.

    This is the assertion the original ticket got backwards. If a future engine
    drops `or record.get("release_commit")`, THIS test goes red -- which is the
    signal that receipts written by this project became invisible again.
    """
    assert closure._is_published(_receipt()), (
        "the current engine must accept a receipt whose only commit key is "
        "`release_commit`; if this fails, T-1238's fallback was reverted"
    )
    assert closure._is_published(_receipt(commit=_receipt()["release_commit"]))


def test_the_shipped_kitchen_receipt_is_truthful_and_visible(closure):
    """The receipt on disk is real publication evidence, not a missing one.

    It names 1d7765b, which this repository carries as the commit tagged
    v0.8.68 -- so the RECORD was always truthful, and under the current engine
    it was always visible. The `release:0.8.68` closure-provenance FAIL comes
    from the stale engine `tools/validate.py` binds, not from this file.
    """
    path = REPO_ROOT / ".saipen" / "kitchen" / "release_receipt.json"
    if not path.is_file():
        pytest.skip("no kitchen release receipt on this tree")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert closure._is_published(data), (
        "the shipped receipt must be publication evidence under the current "
        "engine; if it is not, this file is the oracle and the engine moved"
    )

    commit = data["release_commit"]
    assert closure._release_matches(data, data["version"])
    # Offline proof the record is truthful: the commit it names must really be
    # the one this repository tagged. No network, no remote access.
    tagged = subprocess.run(
        ["git", "tag", "--points-at", commit],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if tagged.returncode != 0:
        pytest.skip("git unavailable")
    assert data["tag"] in tagged.stdout.split(), (
        f"the receipt names {commit}, which is not the commit tagged {data['tag']}"
    )
