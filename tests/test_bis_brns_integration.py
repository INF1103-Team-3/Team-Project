"""Regression checks for the BIS to BRNS request boundary."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

from BRNS import config as brns_config
from BRNS import data_manager as brns_data
from BRNS import io_manager as brns_io
from BRNS import logic_manager as brns_logic
from BRNS import main as brns_main
import main as bis_main
from sources.profile_schema import empty_preferences


def request():
    return {
        "origin": {
            "query": "pasir ris mall", "label": "Pasir Ris Mall",
            "latitude": 1.372, "longitude": 103.95,
        },
        "mode": "walk", "max_distance_km": 2.0,
        "cuisine": "malay", "budget_per_person": 10.0,
        "other_preferences": ["spicy food"],
        "dietary_requirements": ["halal"],
        "disliked_cuisines": [],
    }


class IntegrationTests(unittest.TestCase):
    def test_request_boundary(self):
        valid = request()
        self.assertEqual(brns_io.accept_bis_json(valid), valid)
        for change in (
            {"mode": "fly"}, {"max_distance_km": True},
            {"budget_per_person": None}, {"other_preferences": None},
            {"userID": "must not cross the boundary"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                brns_io.accept_bis_json(dict(valid, **change))

    def test_live_request_uses_confirmed_origin_and_unofficial_halal(self):
        candidate = {
            "name": "Malay Place", "address": "Pasir Ris",
            "lat": 1.373, "lng": 103.951,
            "cuisines": ["malay"], "dietary_requirements": ["halal"],
            "avg_price": 8.0, "walk_meters": 1200,
            "walk_source": "route",
        }
        with (
            patch.object(brns_config, "USE_LIVE_GOOGLE", True),
            patch.object(brns_config, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(brns_data, "load_restaurants", return_value=[]),
            patch.object(brns_data, "build_candidates", return_value=[candidate]) as build,
            patch.object(brns_data, "geocode_location",
                         side_effect=AssertionError("regeocoded")),
            patch.object(brns_data, "save_history", return_value=True) as history,
        ):
            results = brns_main.search(request())
        self.assertEqual(build.call_args.args[0], (1.372, 103.95))
        self.assertEqual(len(results["alternatives"]), 1)
        self.assertEqual(results["alternatives"][0]["restaurant"]["halal_status"],
                         "unofficial")
        self.assertFalse(results["matches"])
        self.assertNotIn("userID", history.call_args.args[0])

    def test_estimated_travel_and_both_dietary_are_unverified(self):
        wants = dict(request(), dietary_requirements=["halal", "vegetarian"])
        candidate = {
            "name": "Test", "cuisines": ["malay"],
            "dietary_requirements": ["halal"], "avg_price": 8.0,
            "walk_meters": 800, "walk_source": "estimate",
        }
        results = brns_logic.rank_restaurants([candidate], wants)
        reasons = results["alternatives"][0]["reasons"]
        self.assertTrue(any("vegetarian" in reason for reason in reasons))
        self.assertTrue(any("travel distance" in reason for reason in reasons))
        self.assertFalse(results["matches"])

    def test_route_distance_and_disliked_cuisine(self):
        wants = dict(request(), dietary_requirements=[], other_preferences=[])
        candidate = {
            "name": "Malay Place", "cuisines": ["malay"],
            "dietary_requirements": [], "avg_price": 8.0,
            "walk_meters": 1800, "walk_source": "route",
        }
        self.assertEqual(len(brns_logic.rank_restaurants(
            [candidate], wants)["matches"]), 1)
        too_far = dict(candidate, walk_meters=2300)
        self.assertEqual(len(brns_logic.rank_restaurants(
            [too_far], wants)["alternatives"]), 1)
        disliked = dict(wants, disliked_cuisines=["malay"])
        self.assertEqual(brns_logic.rank_restaurants(
            [candidate], disliked)["hidden"], 1)

    def test_offline_fallback_remains_available(self):
        with (
            patch.object(brns_config, "USE_LIVE_GOOGLE", False),
            patch.object(brns_data, "save_history", return_value=True),
            patch.object(brns_data, "fetch_by_profile_text",
                         side_effect=AssertionError("Places called")),
        ):
            results = brns_main.search(request())
        self.assertTrue(results["alternatives"])
        self.assertFalse(results["matches"])
        self.assertTrue(all(
            item["restaurant"].get("walk_meters") is None
            and "certification" not in item["restaurant"]
            for item in results["alternatives"]
        ))

    def test_cancelled_bis_search_does_not_mark_completion(self):
        profile = empty_preferences()
        profile.update(
            location=["pasir ris"], max_distance_km=2,
            max_travel_time_minutes=40, budget_per_person=10,
            dietary_requirements=[], liked_cuisines=["malay"],
            disliked_cuisines=[], other_preferences=[],
        )
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search", return_value=None),
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False}, automatic=True)
        state.assert_not_called()
        search.assert_not_called()

    def test_bis_test_mode_skips_brns_and_live_mode_marks_completion(self):
        profile = empty_preferences()
        profile.update(
            location=["pasir ris"], max_distance_km=2,
            max_travel_time_minutes=40, budget_per_person=10,
            dietary_requirements=["halal"], liked_cuisines=["malay"],
            disliked_cuisines=[], other_preferences=[],
        )
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        state = {}
        result = {"matches": [], "alternatives": [], "hidden": 0}
        with (
            patch.object(bis_main.data_manager, "get_state",
                         side_effect=lambda section, user_id: state.get(user_id)),
            patch.object(bis_main.data_manager, "set_state",
                         side_effect=lambda section, user_id, value:
                         state.__setitem__(user_id, value)),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=request()),
            patch.object(bis_main.io_manager, "display_search_summary"),
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search",
                         return_value=result) as search,
        ):
            bis_main.run_search(session, {"ai_bypass": True}, automatic=True)
            self.assertEqual(search.call_count, 0)
            state.clear()
            bis_main.run_search(session, {"ai_bypass": False}, automatic=True)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(state["test"], {"completed": True})
            bis_main.run_search(session, {"ai_bypass": False}, automatic=True)
            self.assertEqual(search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
