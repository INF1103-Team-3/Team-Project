"""Regression checks for the BIS to BRNS request boundary."""

import json
import sys
import tempfile
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
from shared import debug_log as shared_log
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


def collected():
    return {"request": request(), "today_request": "I want spicy food"}


def recommendation(*ids):
    return [{"id": index, "reason_codes": []} for index in ids]


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        provider = patch.object(brns_ai, "has_configured_provider",
                                return_value=True)
        provider.start()
        self.addCleanup(provider.stop)
        saved_preferences = patch.object(
            bis_main.data_manager, "save_preferences",
            side_effect=lambda user_id, preferences, config: {
                "userID": user_id, "preferences": preferences})
        self.saved_preferences = saved_preferences.start()
        self.addCleanup(saved_preferences.stop)

    def test_search_menu_typo_requires_confirmation(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input", side_effect=["yesy", "yes"]),
            patch.object(bis_io.ai_manager, "interpret_search_choice",
                         return_value="yes") as interpret,
        ):
            self.assertTrue(bis_io.ask_yes_no(
                "Is this your current location?", {"ai_bypass": False}))
        interpret.assert_called_once()

        with (
            patch.object(bis_io, "read_input", side_effect=["qalk", "yes"]),
            patch.object(bis_io.ai_manager, "interpret_search_choice",
                         return_value="walk"),
        ):
            self.assertEqual(bis_io.ask_search_mode({"ai_bypass": False}),
                             "walk")

        with (
            patch.object(bis_io, "read_input",
                         side_effect=["qalk", "no", "drive"]),
            patch.object(bis_io.ai_manager, "interpret_search_choice",
                         return_value="walk"),
        ):
            self.assertEqual(bis_io.ask_search_mode({"ai_bypass": False}),
                             "drive")

    def test_search_menu_ai_only_accepts_allowed_choices(self):
        from BIS import ai_manager as bis_ai

        config = {"ai_bypass": False, "openrouter_model": "test-model"}
        with patch.object(bis_ai, "_call_openrouter",
                          return_value='{"choice":"fly"}'):
            self.assertIsNone(bis_ai.interpret_search_choice(
                "qalk", ("walk", "drive"), config))
        with patch.object(bis_ai, "_call_openrouter") as call:
            self.assertIsNone(bis_ai.interpret_search_choice(
                "qalk", ("walk", "drive"), {"ai_bypass": True}))
        call.assert_not_called()

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

    def test_search_collection_uses_one_optional_wish_question(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile.update(dietary_requirements=["halal"],
                       disliked_cuisines=["western"])
        user = {"preferences": profile}
        with (
            patch.object(bis_io, "ask_search_location",
                         return_value=request()["origin"]),
            patch.object(bis_io, "ask_search_mode", return_value="walk"),
            patch.object(bis_io, "ask_search_distance", return_value=2),
            patch.object(bis_io, "ask_search_cuisine", return_value="malay"),
            patch.object(bis_io, "ask_search_budget", return_value=10),
            patch.object(bis_io, "ask_search_wishes",
                         return_value={"selected": [], "text": "quiet place"}),
        ):
            result = bis_io.collect_search(user, {"ai_bypass": False})
        self.assertEqual(result["today_request"], "quiet place")
        self.assertEqual(result["request"]["other_preferences"], [])
        self.assertEqual(result["request"]["dietary_requirements"], ["halal"])
        with patch.object(bis_io, "read_input", return_value=""):
            self.assertEqual(bis_io.ask_search_wishes(profile, {}),
                             {"selected": [], "text": ""})

    def test_special_request_validation_and_reuse(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile["other_preferences"] = ["spicy food", "hawker center"]
        offline = {"ai_bypass": True}
        with patch.object(bis_io, "read_input", return_value="2, 1"):
            self.assertEqual(bis_io.ask_search_wishes(profile, offline), {
                "selected": ["hawker center", "spicy food"], "text": ""})
        with patch.object(bis_io, "read_input", return_value="chicken rice"):
            self.assertEqual(bis_io.ask_search_wishes(profile, offline), {
                "selected": [], "text": "chicken rice"})
        with (
            patch.object(bis_io, "read_input",
                         side_effect=["你好", ""]),
            patch.object(bis_io, "display_message") as message,
        ):
            self.assertEqual(bis_io.ask_search_wishes(profile, offline), {
                "selected": [], "text": ""})
        self.assertIn("English letters", str(message.call_args.args[0]))

    def test_new_special_request_is_reviewed_and_confirmed_before_search_ai(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input", return_value="chikcen rice"),
            patch.object(bis_io.ai_manager, "review_special_request",
                         return_value="chicken rice") as review,
            patch.object(bis_io, "ask_yes_no", return_value=True) as confirm,
        ):
            wishes = bis_io.ask_search_wishes(
                empty_preferences(), {"ai_bypass": False})
        self.assertEqual(wishes, {"selected": [], "text": "chicken rice"})
        review.assert_called_once()
        confirm.assert_called_once()

        with (
            patch.object(bis_io, "read_input",
                         side_effect=["chikcen rice", ""]),
            patch.object(bis_io.ai_manager, "review_special_request",
                         return_value="chicken rice"),
            patch.object(bis_io, "ask_yes_no", return_value=False),
        ):
            self.assertEqual(bis_io.ask_search_wishes(
                empty_preferences(), {"ai_bypass": False}),
                {"selected": [], "text": ""})

    def test_special_request_ai_review_rejects_changed_ok_response(self):
        from BIS import ai_manager as bis_ai

        with patch.object(bis_ai, "_call_openrouter",
                          return_value='{"status":"ok","text":"new wish"}'):
            with self.assertRaisesRegex(RuntimeError, "Could not check"):
                bis_ai.review_special_request(
                    "chicken rice", {"openrouter_model": "test"})

    def test_special_request_waits_for_ai_wording_review(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input",
                         side_effect=["chikcen rice", ""]),
            patch.object(bis_io.ai_manager, "review_special_request",
                         side_effect=RuntimeError("AI unavailable")),
            patch.object(bis_io, "display_message") as message,
        ):
            wishes = bis_io.ask_search_wishes(
                empty_preferences(), {"ai_bypass": False})
        self.assertEqual(wishes, {"selected": [], "text": ""})
        self.assertIn("Could not check the wording", message.call_args.args[0])

    def test_search_clarification_confirms_ai_wording_correction(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input", return_value="chikcen rice"),
            patch.object(bis_io.ai_manager, "review_special_request",
                         return_value="chicken rice") as review,
            patch.object(bis_io, "ask_yes_no", return_value=True) as confirm,
        ):
            result = bis_io.ask_search_clarification({"ai_bypass": False})
        self.assertEqual(result, "chicken rice")
        review.assert_called_once()
        confirm.assert_called_once()

    def test_confirmed_new_request_is_saved_for_next_search(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile["other_preferences"] = ["spicy food"]
        session = {"user": {"userID": "test", "preferences": profile}}
        bis_main.remember_search_wishes(
            session, "Chicken rice", {})
        self.saved_preferences.assert_called_once()
        self.assertEqual(session["user"]["preferences"]["other_preferences"],
                         ["spicy food", "chicken rice"])
        with patch.object(bis_io, "read_input", return_value="2"):
            self.assertEqual(bis_io.ask_search_wishes(
                session["user"]["preferences"], {"ai_bypass": True}),
                {"selected": ["chicken rice"], "text": ""})

    def test_new_request_reaches_brns_when_search_ai_omits_it(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile}}
        choices = dict(request(), other_preferences=[])
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value={"request": choices,
                                       "today_request": "chicken rice"}),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.io_manager, "display_message") as message,
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=choices),
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search",
                         return_value={"matches": [], "alternatives": [],
                                       "hidden": 0}) as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        self.assertIsNotNone(search.call_args, message.call_args_list)
        self.assertEqual(json.loads(search.call_args.args[0])[
            "other_preferences"], ["chicken rice"])
        self.assertEqual(session["user"]["preferences"][
            "other_preferences"], ["chicken rice"])

    def test_brns_requires_ai_before_places_and_does_not_save_on_ai_failure(self):
        with (
            patch.object(brns_ai, "has_configured_provider",
                         return_value=False),
            patch.object(brns_io, "find_candidates") as find,
        ):
            with self.assertRaisesRegex(RuntimeError, "configured AI provider"):
                brns_main.search(request())
        find.assert_not_called()
        with (
            patch.object(brns_config, "USE_LIVE_GOOGLE", True),
            patch.object(brns_config, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(brns_io, "find_candidates",
                         return_value=[{"name": "Candidate"}]),
            patch.object(brns_ai, "recommend_candidates", return_value=None),
            patch.object(brns_data, "save_search_results") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "could not recommend"):
                brns_main.search(request())
        save.assert_not_called()

    def test_brns_drops_unsupported_ai_reason_and_keeps_search(self):
        candidate = {"name": "Candidate", "cuisines": ["malay"],
                     "avg_price": 8, "walk_meters": 1000,
                     "walk_source": "route", "rating": 3.1}
        with (
            tempfile.TemporaryDirectory() as log_dir,
            patch.object(shared_log, "LOG_FILE",
                         Path(log_dir) / "bitefinder.log"),
        ):
            results = brns_logic.rank_restaurants(
                [candidate], request(),
                [{"id": 0, "reason_codes": ["well_rated"]}])
            details = shared_log.LOG_FILE.read_text(encoding="utf-8")
        self.assertEqual(len(results["alternatives"]), 1)
        self.assertNotIn("rated at least 4 out of 5",
                         results["alternatives"][0]["reasons"])
        self.assertIn('"candidate_id":0', details)
        self.assertIn('"candidate_name":"Candidate"', details)
        self.assertIn('"rejected_reason_code":"well_rated"', details)
        self.assertIn('"candidate_rating":3.1', details)
        results = brns_logic.rank_restaurants(
            [candidate], dict(request(), dietary_requirements=[]),
            [{"id": 0, "reason_codes": ["within_budget"]}])
        self.assertIn("average price is within your budget",
                      results["matches"][0]["reasons"])
        unknown_price = dict(candidate, avg_price=None, price_start=1)
        results = brns_logic.rank_restaurants(
            [unknown_price], dict(request(), dietary_requirements=[]),
            [{"id": 0, "reason_codes": ["within_budget"]}])
        self.assertNotIn("average price is within your budget",
                         results["alternatives"][0]["reasons"])

    def test_shared_log_omits_provider_body_and_request_details(self):
        with (
            tempfile.TemporaryDirectory() as log_dir,
            patch.object(shared_log, "LOG_FILE",
                         Path(log_dir) / "bitefinder.log"),
            patch.object(brns_config, "MODEL_CHAIN",
                         [{"provider": "openrouter", "model": "test"}]),
            patch.object(brns_config, "OPENROUTER_API_KEY", "test-key"),
            patch.object(brns_ai, "_call_openrouter",
                         return_value=(False, "HTTP 403: secret-response")),
        ):
            self.assertIsNone(brns_ai.recommend_candidates(
                request(), [{"name": "Candidate"}]))
            brns_places._log_api_error(
                "places_search", ValueError("raw-location-and-key"))
            contents = shared_log.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("HTTP 403", contents)
        self.assertIn("ValueError", contents)
        for secret in ("secret-response", "raw-location-and-key",
                       "pasir ris mall", "test-key"):
            self.assertNotIn(secret, contents)

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
                         return_value=recommendation(0)) as recommend,
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
            return recommendation(0)

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
            tempfile.TemporaryDirectory() as log_dir,
            patch.object(shared_log, "LOG_FILE",
                         Path(log_dir) / "bitefinder.log"),
            patch.object(brns_config, "MODEL_CHAIN",
                         [{"provider": "openrouter", "model": "test"}]),
            patch.object(brns_config, "OPENROUTER_API_KEY", "test-key"),
            patch.object(brns_ai, "_call_openrouter",
                         return_value=(True, '{"recommendations":['
                                      '{"id":1,"reason_codes":[]},'
                                      '{"id":0,"reason_codes":[]}]}')),
        ):
            self.assertEqual(brns_ai.recommend_candidates(
                request(), candidates), recommendation(1, 0))
            details = shared_log.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("Candidate facts sent to model", details)
        self.assertIn('"id":1,"reason_codes":[]', details)
        self.assertNotIn("pasir ris mall", details)
        with (
            patch.object(brns_config, "MODEL_CHAIN",
                         [{"provider": "openrouter", "model": "test"}]),
            patch.object(brns_config, "OPENROUTER_API_KEY", "test-key"),
            patch.object(brns_ai, "_call_openrouter",
                         return_value=(True, '{"recommendations":['
                                      '{"id":2,"reason_codes":[]}]}')),
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
        results = brns_logic.rank_restaurants(
            [first, second], wants, recommendation(1, 0))
        self.assertEqual([item["restaurant"]["name"]
                          for item in results["matches"]],
                         ["Second", "First"])
        rejected = dict(first, cuisines=["chinese"])
        wants["disliked_cuisines"] = ["chinese"]
        results = brns_logic.rank_restaurants(
            [rejected, second], wants, recommendation(0, 1))
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
            patch.object(brns_ai, "recommend_candidates",
                         side_effect=lambda req, candidates:
                         recommendation(*range(len(candidates)))),
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

    def test_bis_ai_failure_or_rejected_interpretation_stays_retryable(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         side_effect=RuntimeError("AI unavailable")),
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        state.assert_not_called()
        search.assert_not_called()

        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=None),
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        state.assert_not_called()
        search.assert_not_called()

        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=request()),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=False),
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        state.assert_not_called()
        search.assert_not_called()

        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=request()),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.brns_main, "search",
                         side_effect=RuntimeError("BRNS AI unavailable")),
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        state.assert_not_called()

    def test_bis_conflict_prompts_for_clarification_before_handoff(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "ask_search_clarification",
                         return_value="spicy food") as clarify,
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         side_effect=[dict(request(), mode="drive"),
                                      request()]) as interpret,
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search",
                         return_value={"matches": [], "alternatives": [],
                                       "hidden": 0}) as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        clarify.assert_called_once()
        self.assertEqual(interpret.call_count, 2)
        search.assert_called_once()

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
                         return_value=collected()),
            patch.object(bis_main.io_manager, "display_search_summary"),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=request()) as interpret,
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
                         return_value={"request": invalid,
                                       "today_request": "spicy food"}),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=invalid),
            patch.object(bis_main.io_manager, "display_message") as message,
            patch.object(bis_main.brns_main, "search") as search,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        search.assert_not_called()
        self.assertIn("walk or drive", str(message.call_args.args[0]))

    def test_bis_ai_can_add_wishes_but_cannot_change_confirmed_choices(self):
        from BIS import logic_manager as bis_logic

        valid = request()
        with self.assertRaisesRegex(ValueError, "conflicts with a confirmed"):
            bis_logic.validate_search_request(
                valid, dict(valid, budget_per_person=30))
        with self.assertRaisesRegex(ValueError, "removed a selected"):
            bis_logic.validate_search_request(
                valid, dict(valid, other_preferences=[]))
        result = bis_logic.validate_search_request(
            valid, dict(valid, other_preferences=["spicy food", "quiet cafe"]))
        self.assertEqual(result["other_preferences"],
                         ["spicy food", "quiet cafe"])

    def test_bis_ai_receives_only_search_choices_and_free_text(self):
        reply = json.dumps(dict(request(), other_preferences=[
            "spicy food", "quiet cafe"]))
        with patch.object(bis_main.ai_manager, "_call_openrouter",
                          return_value=reply) as call:
            proposed = bis_main.ai_manager.interpret_search_request(
                request(), "quiet cafe", {"openrouter_model": "test"})
        self.assertEqual(proposed["other_preferences"],
                         ["spicy food", "quiet cafe"])
        sent = json.loads(call.call_args.args[0]["messages"][1]["content"])
        self.assertEqual(set(sent), {"confirmed_choices", "today_request"})
        self.assertNotIn("userID", sent["confirmed_choices"])

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
            return collected()

        def interpret(confirmed, today_request, config):
            events.append("AI")
            self.assertEqual(today_request, "I want spicy food")
            return request()

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
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.brns_io, "show_results"),
            patch.object(bis_main.brns_main, "search", side_effect=search),
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        self.assertEqual(events, ["IO", "AI", "Logic", "Data", "BRNS"])

    def test_end_to_end_handoff_requires_both_ai_results(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        candidate = {"name": "Malay Place", "cuisines": ["malay"],
                     "avg_price": 8.0, "walk_meters": 900,
                     "walk_source": "route"}
        interpreted = dict(request(), other_preferences=[
            "spicy food", "quiet place"])
        with (
            tempfile.TemporaryDirectory() as log_dir,
            patch.object(shared_log, "LOG_FILE",
                         Path(log_dir) / "bitefinder.log"),
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.io_manager, "display_message"),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=interpreted),
            patch.object(brns_config, "USE_LIVE_GOOGLE", True),
            patch.object(brns_config, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(brns_io, "find_candidates",
                         return_value=[candidate]) as find,
            patch.object(brns_ai, "recommend_candidates",
                         return_value=[{"id": 0, "reason_codes": [
                             "cuisine_match", "within_budget"]}]) as recommend,
            patch.object(brns_data, "save_search_results",
                         return_value=True) as save,
            patch.object(brns_io, "show_results"),
        ):
            bis_main.run_search(session, {"ai_bypass": False})
            lines = shared_log.LOG_FILE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(find.call_args.args[0]["other_preferences"],
                         ["spicy food", "quiet place"])
        self.assertEqual(recommend.call_args.args[1], [candidate])
        save.assert_called_once()
        state.assert_called_once_with("search", "test", {"completed": True})
        self.assertTrue(any("BIS.main.run_search" in line for line in lines))
        self.assertTrue(any("BRNS.main.search" in line for line in lines))
        self.assertEqual(len({line.split(" | ")[2] for line in lines}), 1)
        self.assertNotIn("pasir ris mall", "\n".join(lines).lower())
        self.assertNotIn("quiet place", "\n".join(lines).lower())
        self.assertNotIn("test-key", "\n".join(lines))

    def test_bis_search_continues_and_logs_unsupported_ai_reason(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile},
                   "field": None, "location_action": "add"}
        candidate = {"name": "Candidate", "cuisines": ["malay"],
                     "avg_price": 8, "walk_meters": 1000,
                     "walk_source": "route", "rating": 3.1}
        with (
            tempfile.TemporaryDirectory() as log_dir,
            patch.object(shared_log, "LOG_FILE",
                         Path(log_dir) / "bitefinder.log"),
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state") as state,
            patch.object(bis_main.io_manager, "collect_search",
                         return_value=collected()),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.io_manager, "display_message") as message,
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=request()),
            patch.object(brns_config, "USE_LIVE_GOOGLE", True),
            patch.object(brns_config, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(brns_io, "find_candidates",
                         return_value=[candidate]),
            patch.object(brns_ai, "recommend_candidates",
                         return_value=[{"id": 0,
                                        "reason_codes": ["well_rated"]}]),
            patch.object(brns_data, "save_search_results") as save,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
            lines = shared_log.LOG_FILE.read_text(encoding="utf-8")
        state.assert_called_once_with("search", "test", {"completed": True})
        save.assert_called_once()
        self.assertNotIn("unsupported by restaurant facts",
                         str(message.call_args.args[0]))
        trace = next(line.split(" | ")[2] for line in lines.splitlines()
                     if "BIS.main.run_search | Search started." in line)
        self.assertIn(f" | {trace} | BRNS.logic_manager.rank_restaurants | ",
                      lines)
        self.assertIn('"rejected_reason_code":"well_rated"', lines)
        self.assertIn('"candidate_rating":3.1', lines)


if __name__ == "__main__":
    unittest.main()
