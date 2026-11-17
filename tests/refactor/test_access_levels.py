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
        from types import SimpleNamespace

        try:
            import mongomock

            client = mongomock.MongoClient()
        except ImportError:
            docs = {}

            class _FakeCollection:
                def insert_one(self, doc):
                    docs[doc["_id"]] = dict(doc)

                def find_one(self, query):
                    doc = docs.get(query.get("_id"))
                    return dict(doc) if isinstance(doc, dict) else None

            class _FakeClient:
                def __getitem__(self, _name):
                    return SimpleNamespace(records=_FakeCollection())

                def close(self):
                    return None

            client = _FakeClient()

        from BIS.classes.data.stores.mongo.mongo_connection import (
            MongoConnection,
        )

        connection = MongoConnection(client=client, database="visibility_test")
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

    def test_brc_serialization_releases_lock_after_failure(self):
        from threading import Event, Thread
        from BRC.classes.io.http.server.brc_http_handler import (
            BRCRequestHandler,
        )

        with self.assertRaisesRegex(ValueError, "check failed"):
            with BRCRequestHandler.serialized_checks():
                raise ValueError("check failed")
        acquired = Event()

        def check_again():
            with BRCRequestHandler.serialized_checks():
                acquired.set()

        worker = Thread(target=check_again, daemon=True)
        worker.start()
        self.assertTrue(acquired.wait(timeout=2))
        worker.join(timeout=2)
        self.assertFalse(hasattr(BRCRequestHandler, "_run_lock"))

    def test_brc_client_factory_preserves_provider_fallback(self):
        from unittest.mock import patch
        from BRC import ai_manager

        settings = {
            "providers": [
                {"provider": "gemini", "model": "first"},
                {"provider": "groq", "model": "second"},
            ],
            "timeout_seconds": 12,
            "chain_timeout_seconds": 45,
        }
        with (
            patch.object(
                ai_manager, "_call_gemini", side_effect=RuntimeError("offline")
            ) as gemini,
            patch.object(
                ai_manager,
                "_call_chat_completions",
                return_value='{"ok":true}',
            ) as chat,
        ):
            client = ai_manager.create_client(settings)
            self.assertEqual(client.call_api("sample"), '{"ok":true}')
            gemini.assert_called_once_with("sample", settings, "first")
            self.assertEqual(
                chat.call_args.args[:4], ("sample", settings, "groq", "second")
            )

    def test_seen_matcher_public_contract_keeps_its_index_private(self):
        from BRNS.classes.logic.evaluation.previous_restaurant_matcher import (
            PreviousRestaurantMatcher,
        )

        previous = [
            {
                "google_place_id": " id-1 ",
                "name": " Café ",
                "address": " 1 Road ",
            }
        ]
        matcher = PreviousRestaurantMatcher(previous)
        previous.clear()
        self.assertFalse(matcher.is_empty)
        self.assertTrue(matcher.matches({"google_place_id": "id-1"}))
        self.assertTrue(matcher.matches({"name": "CAFÉ", "address": "1 road"}))
        self.assertFalse(
            matcher.matches({"name": "Café", "address": "2 Road"})
        )
        self.assertFalse(PreviousRestaurantMatcher().matches({"name": "Café"}))
        for field in ("place_ids", "name_address_keys", "_clean_field"):
            self.assertFalse(hasattr(matcher, field))

    def test_nearby_status_distinguishes_empty_success_and_context_failures(
        self,
    ):  # noqa: E501
        from contextvars import copy_context
        from unittest.mock import patch
        import requests
        from BRNS import io_manager

        places = io_manager.places_gateway()
        origin = (1.3, 103.8)
        empty_response = type(
            "EmptyResponse",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"places": []},
            },
        )()
        with patch.object(requests, "post", return_value=empty_response):
            self.assertEqual(places.fetch_nearby_restaurants(origin, {}), [])
        self.assertFalse(places.last_call_failed())

        def fail_in_separate_context():
            with patch.object(
                requests,
                "post",
                side_effect=requests.RequestException("offline"),
            ):
                self.assertEqual(
                    places.fetch_nearby_restaurants(origin, {}), []
                )
            return places.last_call_failed()

        self.assertTrue(copy_context().run(fail_in_separate_context))
        self.assertFalse(places.last_call_failed())

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
