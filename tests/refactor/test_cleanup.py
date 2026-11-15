"""Offline behavior contracts for the incremental SOLID cleanup."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "BIS")]

from BIS.classes.logic.chat.chat_filter_policy import ChatFilterPolicy
from BRNS import io_manager
from BRNS.classes.data.stores.json.json_recommendation_store import (
    JsonRecommendationStore,
)


class CleanupContractTests(unittest.TestCase):
    def test_bis_ai_uses_injected_chat_capability_without_module_callback(self):
        from types import SimpleNamespace
        from BIS.classes.ai.ai_manager import AIManager

        interpreter = SimpleNamespace(
            interpret_chat_turn=lambda *_args: {"intent": "search"},
            review_profile_wishes=lambda *_args: ["quiet"],
        )
        ai = AIManager(None, None, None, None, interpreter=interpreter)
        with patch("BIS.ai_manager.interpret_chat_turn",
                   side_effect=AssertionError("reverse dependency")):
            self.assertEqual(ai.chat_turn("hi", {}, [], {}, {}),
                             {"intent": "search"})
        self.assertEqual(ai.review_profile_wishes(["quiet"], {}), ["quiet"])

    def test_brns_provider_availability_extends_through_registry(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from BRNS.classes.ai.ai_manager import AIManager
        from BRNS.classes.ai.fallback.ai_provider_factory_registry import (
            AIProviderFactoryRegistry,
        )

        registry = AIProviderFactoryRegistry()
        registry.register("fixture", lambda _model: object(),
                          enabled=lambda settings: settings.enabled)
        config = SimpleNamespace(
            MODEL_CHAIN=[{"provider": "fixture", "model": "sample"}],
            enabled=True,
        )
        manager = AIManager(config, None, nullcontext, None, registry)
        self.assertTrue(manager.has_configured_provider())
        config.enabled = False
        self.assertFalse(manager.has_configured_provider())

    def test_profile_authorization_is_shared_by_cli_and_web_logic(self):
        from BIS.classes.logic.logic_manager import LogicManager
        from BIS.sources.profile_schema import empty_preferences

        logic = LogicManager()
        user = {"userID": "fixture", "email": "test@example.com",
                "email_verified": False, "username": "Tester",
                "preferences": empty_preferences()}
        with self.assertRaisesRegex(ValueError, "Verify your email"):
            logic.prepare_preferences_save(
                user, user["preferences"], {"smtp_bypass": False})
        with self.assertRaisesRegex(PermissionError, "Verify your email"):
            logic.prepare_profile_save(user, {}, smtp_bypass=False)
        self.assertEqual(logic.prepare_preferences_save(
            user, user["preferences"], {"smtp_bypass": True}),
            user["preferences"])

    def test_discovery_plan_preserves_fallback_sequence_without_http(self):
        plan = io_manager.discovery_policy().profile_searches({
            "mode": "walk", "max_distance_km": 2,
            "cuisine": "japanese", "budget_per_person": 50,
            "other_preferences": [],
        })
        args, options = next(plan)
        self.assertEqual(args[0], "japanese food")
        self.assertEqual(options["price_levels"],
                         ["PRICE_LEVEL_MODERATE", "PRICE_LEVEL_EXPENSIVE"])
        args, options = plan.send(([], True))
        self.assertEqual(args[0], "japanese restaurants")
        args, options = plan.send([])
        self.assertEqual(args[0], "japanese food")
        self.assertIsNone(options["price_levels"])
        with self.assertRaises(StopIteration) as finished:
            plan.send([])
        self.assertEqual(finished.exception.value, [])

    def test_corrupt_history_is_retained_and_save_reports_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            original = '[{"search": "previous"},'
            path.write_text(original)
            store = JsonRecommendationStore(path.parent / "places.json", path)
            with self.assertRaisesRegex(RuntimeError, "retained"):
                store.save_history({"search": "new"})
            self.assertEqual(path.read_text(), original)

    def test_wrong_restaurant_schema_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "places.json"
            path.write_text('{}')
            store = JsonRecommendationStore(path, path.parent / "history.json")
            with self.assertRaisesRegex(RuntimeError, "JSON list"):
                store.save_restaurants([])
            self.assertEqual(path.read_text(), '{}')

    def test_atomic_replace_failure_retains_history_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            original = '[{"search": "previous"}]\n'
            path.write_text(original)
            store = JsonRecommendationStore(path.parent / "places.json", path)
            with patch(
                    "BRNS.classes.data.stores.contracts.base_json_store."
                    "os.replace", side_effect=OSError("fixture failure")):
                self.assertFalse(store.save_history({"search": "new"}))
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_chat_filters_keep_time_precedence_and_normalize_lists(self):
        result = ChatFilterPolicy.normalize_filters({
            "locations": ["bugis", "bugis"],
            "mode": "walk",
            "max_travel_minutes": 20,
            "max_distance_km": 2,
            "budget_per_person": 25,
            "dietary_requirements": ["HALAL", "halal"],
        })
        self.assertEqual(result["locations"], ["Bugis"])
        self.assertEqual(result["max_travel_minutes"], 20)
        self.assertIsNone(result["max_distance_km"])
        self.assertEqual(result["dietary_requirements"], ["halal"])

    def test_chat_explicit_dietary_removal_wins_over_ai(self):
        deterministic = {
            "intent": "search",
            "updates": {
                "dietary_action": "remove",
                "dietary_requirements": ["halal"],
            },
        }
        ai = {
            "intent": "search",
            "updates": {
                "dietary_action": "add",
                "dietary_requirements": ["halal"],
                "disliked_cuisines": ["halal", "chinese"],
            },
        }
        result = ChatFilterPolicy.reconcile_ai_updates(
            deterministic, ai, {})
        self.assertEqual(result["updates"]["dietary_action"], "remove")
        self.assertEqual(result["updates"]["disliked_cuisines"], ["chinese"])
        self.assertEqual(ai["updates"]["dietary_action"], "add")

    def test_discovery_preserves_zone_quota_and_order(self):
        places = [
            {"name": f"{zone}{index}", "lat": latitude, "lng": 103.8}
            for zone, latitude in (("Near", 1.31), ("Mid", 1.35),
                                   ("Outer", 1.38))
            for index in range(10)
        ]
        result = io_manager._sample_zone_slice(
            places, (1.3, 103.8), 10000, 20)
        expected = ([f"Near{i}" for i in range(7)]
                    + [f"Mid{i}" for i in range(7)]
                    + [f"Outer{i}" for i in range(6)])
        self.assertEqual([row["name"] for row in result], expected)

    def test_json_history_appends_in_order_across_store_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store = JsonRecommendationStore(
                path / "restaurants.json", path / "history.json")
            self.assertTrue(store.save_history({"search": 1}))
            reloaded = JsonRecommendationStore(
                path / "restaurants.json", path / "history.json")
            self.assertTrue(reloaded.save_history({"search": 2}))
            self.assertEqual(
                json.loads((path / "history.json").read_text()),
                [{"search": 1}, {"search": 2}],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
