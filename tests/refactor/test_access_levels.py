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
    def test_configured_collaborators_are_readable_but_not_replaceable(self):
        from types import SimpleNamespace
        from BIS.classes.ai.ai_manager import AIManager
        from BIS.classes.logic.logic_manager import LogicManager
        from BIS.classes.services.web.web_runtime import WebRuntime

        interpreter, policy, io = object(), object(), object()
        manager = AIManager(None, None, None, None, interpreter=interpreter)
        logic = LogicManager(chat_filters=policy)
        closed = []
        runtime = WebRuntime(
            io, SimpleNamespace(close=lambda: closed.append(True))
        )
        for owner, name, expected in (
            (manager, "interpreter", interpreter),
            (logic, "chat_filters", policy),
            (runtime, "io", io),
        ):
            with self.subTest(member=name):
                self.assertIs(getattr(owner, name), expected)
                with self.assertRaises(AttributeError):
                    setattr(owner, name, object())
                self.assertIs(getattr(owner, name), expected)
        runtime.close()
        self.assertEqual(closed, [True])

    def test_mongo_operations_do_not_require_a_public_database_handle(self):
        import mongomock
        from BIS.classes.data.stores.mongo.mongo_connection import (
            MongoConnection,
        )

        connection = MongoConnection(
            client=mongomock.MongoClient(), database="visibility_test"
        )
        self.addCleanup(connection.close)
        with self.assertRaises(AttributeError):
            getattr(connection, "db")
        connection.execute(
            lambda db: db.records.insert_one({"_id": "fixture"})
        )
        row = connection.execute(
            lambda db: db.records.find_one({"_id": "fixture"})
        )
        self.assertEqual(row, {"_id": "fixture"})

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
