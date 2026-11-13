"""Asset-free tests for the portable port-case evidence index."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nexuslib.portcases import CASES, load_cases, main, source_url, validate


class PortCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = load_cases(CASES)[0]

    def bad(self, change, expected):
        value = deepcopy(self.good)
        change(value)
        self.assertTrue(any(expected in problem for problem in validate(value)),
                        validate(value))

    def test_committed_case_is_valid(self):
        self.assertEqual([], validate(self.good))
        self.assertEqual(0, main(["check"]))

    def test_evidence_is_immutable_source_link(self):
        path = self.good["milestones"][0]["evidence"][0]
        url = source_url(self.good, path)
        self.assertIn("/blob/" + self.good["source"]["commit"] + "/", url)
        self.assertNotIn("/blob/main/", url)

    def test_moving_commit_rejected(self):
        self.bad(lambda c: c["source"].update(commit="main"), "full lowercase Git SHA")

    def test_unbacked_milestone_rejected(self):
        self.bad(lambda c: c["milestones"][0].update(evidence=[]), "at least one")

    def test_traversal_rejected(self):
        self.bad(lambda c: c["lessons"][0].update(evidence=["docs/../private/key.md"]),
                 "unsafe")

    def test_duplicate_claim_ids_rejected(self):
        self.bad(lambda c: c["lessons"][0].update(id=c["milestones"][0]["id"]),
                 "duplicated")

    def test_hypotheses_cannot_be_verified_milestones(self):
        self.bad(lambda c: c["milestones"][0].update(status="hypothesis"),
                 "not a milestone")

    def test_unknown_scope_rejected(self):
        self.bad(lambda c: c["lessons"][0].update(scope="universal"), ".scope")

    def test_case_loader_does_not_fetch_or_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "case.json"
            case = deepcopy(self.good)
            case["lessons"][0]["finding"] = "$(touch /tmp/nexus-must-not-execute)"
            path.write_text(json.dumps(case), encoding="utf-8")
            loaded = load_cases(Path(folder))
            self.assertEqual(case["lessons"][0]["finding"],
                             loaded[0]["lessons"][0]["finding"])

    def test_invalid_json_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "case.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "case.json"):
                load_cases(Path(folder))


if __name__ == "__main__":
    unittest.main()
