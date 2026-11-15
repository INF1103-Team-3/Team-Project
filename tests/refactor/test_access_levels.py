"""Offline contracts for intentional public, protected and private APIs."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "BIS")]

from BRC.classes.services.workflows.contracts.base_brc_workflow import (  # noqa: E402
    BaseBRCWorkflow,
)
from BRNS.classes.logic.sorting.contracts.base_result_sorter import (  # noqa: E402
    BaseResultSorter,
)


class AccessLevelTests(unittest.TestCase):
    def test_sorter_public_api_dispatches_protected_hook(self):
        class NameSorter(BaseResultSorter):
            def _key(self, item, mode):
                return item["restaurant"]["name"]

        original = {
            "matches": [{"restaurant": {"name": name}} for name in ("Z", "A")],
            "alternatives": [],
        }
        sorted_results = NameSorter().sort(original)
        self.assertEqual(
            [row["restaurant"]["name"] for row in sorted_results["matches"]],
            ["A", "Z"],
        )
        self.assertEqual(original["matches"][0]["restaurant"]["name"], "Z")

    def test_workflow_public_api_dispatches_protected_hooks(self):
        events = []

        class RecordingWorkflow(BaseBRCWorkflow):
            def _announce(self, data, logic, report):
                events.append("io")

            def _ask_ai(self, ai):
                events.append("ai")
                return "proposal"

            def _apply_rules(self, logic, proposals):
                events.append("logic")
                return "validated " + proposals

            def _save(self, data, result, report, output):
                events.append("data")
                return result

        result = RecordingWorkflow().run(None, None, None, lambda _msg: None)
        self.assertEqual(events, ["io", "ai", "logic", "data"])
        self.assertEqual(result, "validated proposal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
