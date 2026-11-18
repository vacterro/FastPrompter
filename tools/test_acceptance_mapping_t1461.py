"""T-1461 focused receipt: acceptance contract no longer cites retired cases.

T-1445 removed the compact-hover machinery and its four test cases.  The
project acceptance contract kept naming those dead node ids, so the mechanism
ledger refuted DOMAIN_18's behavioural and visual claims.  This adapter checks
the repaired contract on the live tree without depending on .saipen/ evidence:
every cited case must resolve to a real class and method in a real test file,
no retired case may remain, and no plane may be promoted past PARTIAL.

Self-contained unittest so the SAIPEN focused harness (which discovers only in
tools/) can mint an authentic PASS receipt for T-1461.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# The default is the live contract.  The override lets the same oracle run
# against the pre-fix content for the red control, so both sides of the pair
# are byte-identical except for the file under test.
ACCEPTANCE = Path(
    os.environ.get("T1461_ACCEPTANCE", ROOT / "docs" / "audit" / "ACCEPTANCE.json")
)

RETIRED = (
    "TestCompactToDetailTransition",
    "TestCompactHoverFootprint",
)


def _mapping():
    return json.loads(ACCEPTANCE.read_text(encoding="utf-8"))


def _case_exists(case):
    """A node id is real when its file holds the named class and method."""
    parts = case.split("::")
    if len(parts) != 3:
        return False
    path, cls, method = parts
    target = ROOT / path
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8", errors="ignore")
    return f"class {cls}" in text and f"def {method}" in text


class AcceptanceMappingRepairT1461(unittest.TestCase):
    def setUp(self):
        self.mapping = _mapping()
        self.domain = self.mapping["domains"]["DOMAIN_18_USAGE_LIMITS"]

    def test_acceptance_file_is_valid_json(self):
        self.assertIsInstance(self.mapping, dict)

    def test_no_retired_compact_hover_class_is_cited(self):
        for plane in ("behavioural", "visual"):
            for case in self.domain[plane]["cases"]:
                for dead in RETIRED:
                    self.assertNotIn(dead, case, f"{plane} cites retired {dead}: {case}")

    def test_every_cited_case_resolves_to_a_real_test(self):
        for plane in ("behavioural", "visual"):
            for case in self.domain[plane]["cases"]:
                self.assertTrue(_case_exists(case), f"dangling case id: {case}")

    def test_successor_hover_cases_are_present(self):
        behavioural = self.domain["behavioural"]["cases"]
        visual = self.domain["visual"]["cases"]
        self.assertTrue(any("TestHoverShowsTheDetailTable" in c for c in behavioural))
        self.assertTrue(any("TestNoCompactMachineryRemains" in c for c in behavioural))
        self.assertTrue(any("TestRefreshKeepsTheOpenViewCurrent" in c for c in behavioural))
        self.assertTrue(any("TestHoverShowsTheDetailTable" in c for c in visual))

    def test_no_plane_is_falsely_promoted_to_accepted(self):
        for plane in ("behavioural", "visual"):
            self.assertEqual(self.domain[plane]["status"], "PARTIAL")

    def test_observation_describes_the_reverted_detail_view(self):
        text = self.domain["behavioural"]["observation"]
        self.assertIn("full per-window detail table", text)
        self.assertNotIn("expands on pointer entry", text)

    def test_every_cited_evidence_file_exists(self):
        for plane in ("behavioural", "visual"):
            for rel in self.domain[plane]["evidence"]:
                self.assertTrue((ROOT / rel).is_file(), f"missing evidence: {rel}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
