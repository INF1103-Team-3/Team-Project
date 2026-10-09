"""Regression checks for the BIS to BRNS request boundary."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

from BRNS import config as brns_config
from BRNS import ai_manager as brns_ai
from BRNS import data_manager as brns_data
from BRNS import io_manager as brns_io
from BRNS import logic_manager as brns_logic
from BRNS import main as brns_main
from BRNS import places_client as brns_places
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
        self.assertEqual(brns_io.accept_bis_json(json.dumps(valid)), valid)
        with self.assertRaises(ValueError):
            brns_io.accept_bis_json("{broken json")
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
            patch.object(brns_io, "find_candidates",
                         return_value=[candidate]) as find,
            patch.object(brns_ai, "recommend_candidates",
                         return_value=[0]) as recommend,
            patch.object(brns_data, "save_search_results",
                         return_value=True) as history,
        ):
            results = brns_main.search(request())
        self.assertEqual(find.call_args.args[0]["origin"], request()["origin"])
        self.assertEqual(recommend.call_args.args[1], [candidate])
        self.assertEqual(len(results["alternatives"]), 1)
        self.assertEqual(results["alternatives"][0]["restaurant"]["halal_status"],
                         "unofficial")
        self.assertFalse(results["matches"])
        self.assertNotIn("userID", history.call_args.args[0])
        self.assertEqual(history.call_args.args[2], "live-google")

    def test_brns_manager_order_and_io_places_boundary(self):
        candidate = {
            "name": "Malay Place", "cuisines": ["malay"],
            "dietary_requirements": [], "avg_price": 8.0,
            "walk_meters": 900, "walk_source": "route",
        }
        events = []
        rank = brns_logic.rank_restaurants

        def find(search_request):
            events.append("IO")
            self.assertEqual(search_request["origin"], request()["origin"])
            return [candidate]

        def recommend(search_request, candidates):
            events.append("AI")
            self.assertEqual(candidates, [candidate])
            return [0]

        def validate(candidates, search_request, order):
            events.append("Logic")
            return rank(candidates, search_request, order)

        def store(search_request, results, source):
            events.append("Data")
            return True

        with (
            patch.object(brns_config, "USE_LIVE_GOOGLE", True),
            patch.object(brns_config, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(brns_io, "find_candidates", side_effect=find),
            patch.object(brns_ai, "recommend_candidates",
                         side_effect=recommend),
            patch.object(brns_logic, "rank_restaurants",
                         side_effect=validate),
            patch.object(brns_data, "save_search_results",
                         side_effect=store),
        ):
            brns_main.search(request())
        self.assertEqual(events, ["IO", "AI", "Logic", "Data"])

        with (
            patch.object(brns_places, "load_catalog", return_value=[]),
            patch.object(brns_places, "build_candidates",
                         return_value=[candidate]) as build,
        ):
            self.assertEqual(brns_io.find_candidates(request()), [candidate])
        self.assertEqual(build.call_args.args[0], (1.372, 103.95))
        self.assertEqual(build.call_args.args[1]["free_text"], "spicy food")

    def test_ai_only_returns_valid_candidate_ids(self):
        candidates = [{"name": "First"}, {"name": "Second"}]
        with (
            patch.object(brns_config, "MODEL_CHAIN",
                         [{"provider": "openrouter", "model": "test"}]),
            patch.object(brns_config, "OPENROUTER_API_KEY", "test-key"),
            patch.object(brns_ai, "_call_openrouter",
                         return_value=(True, '{"ordered_ids":[1,0]}')),
        ):
            self.assertEqual(brns_ai.recommend_candidates(
                request(), candidates), [1, 0])
        with (
            patch.object(brns_config, "MODEL_CHAIN",
                         [{"provider": "openrouter", "model": "test"}]),
            patch.object(brns_config, "OPENROUTER_API_KEY", "test-key"),
            patch.object(brns_ai, "_call_openrouter",
                         return_value=(True, '{"ordered_ids":[2]}')),
            patch.object(brns_ai, "_log_ai_event"),
        ):
            self.assertIsNone(brns_ai.recommend_candidates(
                request(), candidates))

    def test_logic_applies_ai_order_after_validating_candidates(self):
        wants = dict(request(), dietary_requirements=[],
                     other_preferences=[], disliked_cuisines=[])
        first = {"name": "First", "cuisines": ["malay"],
                 "dietary_requirements": [], "avg_price": 8.0,
                 "walk_meters": 900, "walk_source": "route"}
        second = dict(first, name="Second")
        results = brns_logic.rank_restaurants([first, second], wants, [1, 0])
        self.assertEqual([item["restaurant"]["name"]
                          for item in results["matches"]],
                         ["Second", "First"])
        rejected = dict(first, cuisines=["chinese"])
        wants["disliked_cuisines"] = ["chinese"]
        results = brns_logic.rank_restaurants(
            [rejected, second], wants, [0, 1])
        self.assertEqual(results["hidden"], 1)
        self.assertEqual(results["matches"][0]["restaurant"]["name"],
                         "Second")

    def test_data_stores_only_validated_search_summary(self):
        results = {"matches": [{"restaurant": {
            "name": "Approved", "certification": "unverified"}}]}
        with patch.object(brns_data, "save_history",
                          return_value=True) as save:
            brns_data.save_search_results(
                dict(request(), userID="private"), results, "live-google")
        entry = save.call_args.args[0]
        self.assertEqual(entry["top_matches"], ["Approved"])
        self.assertEqual(entry["origin"], [1.372, 103.95])
        self.assertNotIn("userID", entry)
        self.assertNotIn("certification", entry)

    def test_route_uses_io_owned_routing_client(self):
        restaurant = {"name": "Malay Place", "lat": 1.373,
                      "lng": 103.951}
        route_data = {"distance_m": 1200, "duration_min": 15,
                      "steps": ["Head north"]}
        with (
            patch.object(brns_io, "get_route",
                         return_value=route_data) as get_route,
            patch.object(brns_io, "build_maps_link",
                         return_value="https://maps.example") as link,
        ):
            result = brns_main.route_to(restaurant, request())
        self.assertEqual(get_route.call_args.args,
                         ((1.372, 103.95), (1.373, 103.951), "walk"))
        self.assertEqual(link.call_args.args, get_route.call_args.args)
        self.assertEqual(result["route"], route_data)

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
            patch.object(brns_data, "save_search_results",
                         return_value=True),
            patch.object(brns_ai, "recommend_candidates", return_value=None),
            patch.object(brns_places, "fetch_by_profile_text",
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
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value={"other_preferences": ["spicy food"]}) as interpret,
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search",
                         return_value=result) as search,
        ):
            bis_main.run_search(session, {"ai_bypass": True}, automatic=True)
            self.assertEqual(search.call_count, 0)
            interpret.assert_not_called()
            state.clear()
            bis_main.run_search(session, {"ai_bypass": False}, automatic=True)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(interpret.call_count, 1)
            self.assertEqual(json.loads(search.call_args.args[0]), request())
            self.assertEqual(state["test"], {"completed": True})
            bis_main.run_search(session, {"ai_bypass": False}, automatic=True)
            self.assertEqual(search.call_count, 1)

    def test_bis_rejects_invalid_search_before_brns_handoff(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        invalid = dict(request(), mode="fly")
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=invalid),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value={"other_preferences": ["spicy food"]}),
            patch.object(bis_main.io_manager, "display_message") as message,
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        search.assert_not_called()
        self.assertIn("walk or drive", str(message.call_args.args[0]))

    def test_bis_ai_cannot_add_search_preferences(self):
        from BIS import logic_manager as bis_logic

        valid = request()
        with self.assertRaisesRegex(ValueError, "changed your search"):
            bis_logic.validate_search_request(
                valid, {"other_preferences": ["spicy food", "sea view"]})
        ordered = dict(valid, other_preferences=["spicy food", "quiet cafe"])
        result = bis_logic.validate_search_request(
            ordered, {"other_preferences": ["quiet cafe", "spicy food"]})
        self.assertEqual(result["other_preferences"],
                         ["quiet cafe", "spicy food"])

    def test_bis_search_stages_run_in_order(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        events = []
        validator = bis_main.logic_manager.validate_search_request
        serializer = bis_main.data_manager.serialize_search_request

        def collect(user, config):
            events.append("IO")
            return request()

        def interpret(collected, config):
            events.append("AI")
            return {"other_preferences": ["spicy food"]}

        def validate(collected, interpreted):
            events.append("Logic")
            return validator(collected, interpreted)

        def serialize(validated):
            events.append("Data")
            return serializer(validated)

        def search(payload):
            events.append("BRNS")
            self.assertEqual(json.loads(payload), request())
            return {"matches": [], "alternatives": [], "hidden": 0}

        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         side_effect=collect),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         side_effect=interpret),
            patch.object(bis_main.logic_manager, "validate_search_request",
                         side_effect=validate),
            patch.object(bis_main.data_manager, "serialize_search_request",
                         side_effect=serialize),
            patch.object(bis_main.io_manager, "display_search_summary"),
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search", side_effect=search),
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        self.assertEqual(events, ["IO", "AI", "Logic", "Data", "BRNS"])


if __name__ == "__main__":
    unittest.main()
