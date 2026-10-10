"""Regression checks for the BIS to BRNS request boundary."""

import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
from shared import geocode_cache
from shared import terminal_ui
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

    def test_color_command_persists_per_user_and_works_inside_prompt(self):
        from BIS.sources.prompts import HELP_TEXT

        self.assertIn("/color off", HELP_TEXT)
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        user = {"userID": "test", "username": "John",
                "preferences": profile}
        display_state = {}

        def get_state(section, user_id):
            return display_state.get(user_id) if section == "display" else None

        def set_state(section, user_id, value):
            self.assertEqual(section, "display")
            display_state[user_id] = value

        with (
            patch.object(bis_main.data_manager, "get_state",
                         side_effect=get_state),
            patch.object(bis_main.data_manager, "set_state",
                         side_effect=set_state),
            patch.object(bis_main, "run_search"),
            patch("builtins.input", side_effect=["/color off", "/quit"]),
        ):
            self.assertEqual(bis_main.run_session(user, {"ai_bypass": True}),
                             "exit")
        self.assertEqual(display_state["test"], {"color_enabled": False})
        self.assertTrue(terminal_ui.colors_enabled())

        loaded = []
        with (
            patch.object(bis_main.data_manager, "get_state",
                         side_effect=get_state),
            patch.object(bis_main.data_manager, "set_state",
                         side_effect=set_state),
            patch.object(bis_main, "run_search"),
            patch.object(bis_main.io_manager, "display_welcome",
                         side_effect=lambda user: loaded.append(
                             terminal_ui.colors_enabled())),
            patch("builtins.input", side_effect=["/color on", "/quit"]),
        ):
            self.assertEqual(bis_main.run_session(user, {"ai_bypass": True}),
                             "exit")
        self.assertEqual(loaded, [False])
        self.assertIsNone(display_state["test"])
        self.assertTrue(terminal_ui.colors_enabled())

    def test_alternatives_are_offered_before_display_and_route(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile}}
        restaurant = {"name": "Nearby Cafe", "address": "Pasir Ris",
                      "lat": 1.37, "lng": 103.95}
        results = {"matches": [], "alternatives": [{
            "restaurant": restaurant, "reasons": ["! exceeds budget"]}],
            "mode": "walk", "requested_dietary": []}
        actions = ["done", "alternatives", "more", "route", "done"]
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value={"request": request(), "today_request": ""}),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         return_value=request()),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.brns_main, "search", return_value=results),
            patch.object(bis_main.io_manager, "display_message") as message,
            patch.object(bis_main.io_manager, "choose_results_action",
                         side_effect=actions) as choose,
            patch.object(bis_main.brns_io, "show_no_matches") as no_matches,
            patch.object(bis_main.io_manager, "choose_route_result",
                         return_value=1),
            patch.object(bis_main.brns_io, "show_results") as show,
            patch.object(bis_main.brns_io, "show_result_list") as listed,
            patch.object(bis_main.brns_main, "route_to",
                         return_value={"name": "Nearby Cafe", "route": None,
                                       "link": "map", "mode": "walk"}) as route,
            patch.object(bis_main.brns_io, "show_route"),
        ):
            bis_main.run_search(session, {"ai_bypass": False})
            no_matches.assert_called_once_with(results)
            choose.assert_called_once_with(0, alternatives_hidden=True)
            show.assert_not_called()
            listed.assert_not_called()
            route.assert_not_called()

            choose.reset_mock()
            bis_main.run_search(session, {"ai_bypass": False})
            self.assertEqual(no_matches.call_count, 2)
            listed.assert_called_once_with(results)
            show.assert_called_once_with(
                results, announce_no_matches=False)
            route.assert_called_once_with(restaurant, request())

    def test_no_match_can_refine_budget_then_view_multiple_routes(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["malay"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile}}
        restaurant = {"name": "Nearby Cafe", "lat": 1.37, "lng": 103.95,
                      "walk_meters": 850}
        empty = {"matches": [], "alternatives": [], "mode": "walk"}
        found = {"matches": [{"restaurant": restaurant, "reasons": []}],
                 "alternatives": [], "mode": "walk"}
        refined = dict(request(), budget_per_person=20.0)
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value={"request": request(),
                                       "today_request": ""}),
            patch.object(bis_main.io_manager, "confirm_search_request",
                         return_value=True),
            patch.object(bis_main.io_manager, "choose_results_action",
                         side_effect=["again", "route", "route", "done"]),
            patch.object(bis_main.io_manager, "choose_route_result",
                         side_effect=[1, 1]),
            patch.object(bis_main.io_manager, "read_input",
                         side_effect=["budget", "20"]),
            patch.object(bis_main.ai_manager, "interpret_search_request",
                         side_effect=[request(), refined]) as interpret,
            patch.object(bis_main.brns_main, "search",
                         side_effect=[empty, found]) as search,
            patch.object(bis_main.brns_main, "route_to",
                         return_value={"name": "Nearby Cafe", "route": None,
                                       "link": "map", "mode": "walk"}) as route,
            patch.object(bis_main.brns_io, "show_result_list") as listed,
            patch.object(bis_main.brns_io, "show_route") as shown_route,
        ):
            bis_main.run_search(session, {"ai_bypass": False})
        self.assertEqual(search.call_count, 2)
        self.assertEqual(json.loads(search.call_args.args[0])[
            "budget_per_person"], 20.0)
        self.assertEqual(interpret.call_count, 2)
        self.assertEqual(listed.call_count, 1)
        self.assertEqual(route.call_count, 2)
        self.assertEqual(shown_route.call_count, 2)

    def test_numbered_results_actions_and_blank_enter(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input",
                         side_effect=["1", "2", "3", "1", "2", "3", "4",
                                      "", "2"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(bis_io.choose_results_action(
                0, alternatives_hidden=True), "alternatives")
            self.assertEqual(bis_io.choose_results_action(
                0, alternatives_hidden=True), "again")
            self.assertEqual(bis_io.choose_results_action(
                0, alternatives_hidden=True), "done")
            self.assertEqual(bis_io.choose_results_action(2), "route")
            self.assertEqual(bis_io.choose_results_action(2), "more")
            self.assertEqual(bis_io.choose_results_action(2), "again")
            self.assertEqual(bis_io.choose_results_action(2), "done")
            self.assertEqual(bis_io.choose_results_action(2), "done")
            self.assertEqual(bis_io.choose_route_result(2), 2)

    def test_search_summary_shows_dietary_and_disliked_cuisines(self):
        from BIS import io_manager as bis_io

        cases = (
            ([], "None"),
            (["halal"], "Halal"),
            (["vegetarian"], "Vegetarian"),
            (["halal", "vegetarian"], "Halal, Vegetarian"),
        )
        for choices, expected in cases:
            with self.subTest(choices=choices):
                wanted = dict(request(), dietary_requirements=choices,
                              disliked_cuisines=["chinese"])
                output = io.StringIO()
                with redirect_stdout(output):
                    bis_io.display_search_summary(wanted)
                shown = output.getvalue()
                self.assertIn("Specific cuisine today: Malay", shown)
                self.assertIn(f"Dietary Restrictions: {expected}", shown)
                self.assertIn("Disliked cuisines: Chinese", shown)

    def test_search_summary_capitalizes_values_without_changing_request(self):
        from BIS import io_manager as bis_io

        wanted = dict(request(), origin=dict(request()["origin"],
                                              label="punggol"),
                      cuisine="none", dietary_requirements=[],
                      disliked_cuisines=["mexican", "thai"],
                      other_preferences=["spicy food"])
        output = io.StringIO()
        with redirect_stdout(output):
            bis_io.display_search_summary(wanted)
        shown = output.getvalue()
        self.assertIn("From: Punggol", shown)
        self.assertIn("Travel: Walk up to", shown)
        self.assertIn("Specific cuisine today: None", shown)
        self.assertIn("Dietary Restrictions: None", shown)
        self.assertIn("Disliked cuisines: Mexican, Thai", shown)
        self.assertIn("Other preferences: Spicy food", shown)
        self.assertEqual(wanted["origin"]["label"], "punggol")
        self.assertEqual(wanted["cuisine"], "none")

    def test_result_cards_separate_matches_alternatives_and_cautions(self):
        match = {"restaurant": {"name": "Rice House", "address": "Market",
                                 "cuisines": ["chinese"], "avg_price": 8,
                                 "walk_meters": 500},
                 "reasons": ["matches selected cuisine",
                             "average price is within your budget",
                             "rated at least 4 out of 5"]}
        alternative = {"restaurant": {"name": "Noodle House",
                                       "address": "Main Road",
                                       "cuisines": ["chinese"],
                                       "price_start": 12,
                                       "halal_status": "unofficial"},
                       "reasons": ["! above your budget"]}
        output = io.StringIO()
        with redirect_stdout(output):
            brns_io.show_results({"matches": [match],
                                  "alternatives": [alternative],
                                  "mode": "walk", "requested_dietary": ["halal"]})
        shown = output.getvalue()
        self.assertIn("Matches (1)", shown)
        self.assertIn("Alternatives (1)", shown)
        self.assertIn("  1. Rice House", shown)
        self.assertIn("  2. Noodle House", shown)
        self.assertIn("Highlights:\n       • Matches selected cuisine", shown)
        self.assertIn("• Average price is within your budget", shown)
        self.assertIn("• Rated at least 4 out of 5", shown)
        self.assertIn("Things to check:\n       • Above your budget", shown)
        self.assertEqual(shown.count("Highlights:"), 1)
        self.assertEqual(shown.count("Things to check:"), 1)
        self.assertIn("Halal: Unofficial indication; not checked", shown)
        self.assertNotIn("! above", shown)
        output = io.StringIO()
        with redirect_stdout(output):
            brns_io.show_result_list({
                "matches": [match], "alternatives": [alternative],
                "mode": "walk"})
        compact = output.getvalue()
        self.assertIn("1. Rice House · 0.50 km by walk", compact)
        self.assertIn("2. Noodle House · distance unavailable", compact)

    def test_no_match_message_explains_top_alternative(self):
        results = {"matches": [], "alternatives": [{
            "restaurant": {"name": "Far Cafe"},
            "reasons": ["! route exceeds your distance limit",
                        "! some prices may fit; full budget unverified"]}]}
        output = io.StringIO()
        with redirect_stdout(output):
            brns_io.show_no_matches(results)
        shown = output.getvalue()
        self.assertIn("No fully verified matches", shown)
        self.assertIn("route exceeds your distance limit", shown)
        self.assertIn("full budget unverified", shown)

    def test_unofficial_halal_is_a_single_caution_not_a_positive_reason(self):
        candidate = {"name": "R&J Cosy Corner", "cuisines": [],
                     "halal_hint": True, "price_start": 10,
                     "walk_meters": 3910, "walk_source": "route",
                     "rating": 4.2}
        wanted = dict(request(), max_distance_km=5,
                      dietary_requirements=["halal", "vegetarian"])
        result = brns_logic.rank_restaurants(
            [candidate], wanted,
            [{"id": 0, "reason_codes": ["well_rated", "halal_hint_unofficial"]}])
        reasons = result["alternatives"][0]["reasons"]
        self.assertEqual(reasons.count("! Halal (unofficial; not checked)"), 1)
        self.assertNotIn("Halal (unofficial; not checked)", reasons)
        output = io.StringIO()
        with redirect_stdout(output):
            brns_io.show_results(result)
        shown = output.getvalue()
        self.assertEqual(shown.count("Halal:"), 1)
        self.assertEqual(shown.count("cuisine unavailable"), 0)
        self.assertIn("Cuisine: Unavailable", shown)
        self.assertIn("• Vegetarian options unverified", shown)
        self.assertIn("• Rated at least 4 out of 5", shown)

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
        with (
            patch.object(bis_ai, "_call_openrouter",
                         return_value='{"choice":"fly"}'),
            patch.object(bis_ai, "MODEL_CHAIN", []),
        ):
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

    def test_search_accepts_no_cuisine_without_cuisine_penalty(self):
        from BIS import io_manager as bis_io
        from BIS import logic_manager as bis_logic

        with patch.object(bis_io, "read_input", return_value="none"):
            self.assertEqual(bis_io.ask_search_cuisine(empty_preferences()),
                             "none")
        no_cuisine = dict(request(), cuisine="none")
        self.assertEqual(bis_logic.validate_search_request(no_cuisine)[
            "cuisine"], "none")
        self.assertEqual(brns_io.accept_bis_json(no_cuisine)["cuisine"],
                         "none")
        candidate = {"cuisines": ["malay"], "dietary_requirements": [],
                     "halal_status": "unverified", "avg_price": 8,
                     "walk_meters": 500, "walk_source": "route"}
        no_cuisine["dietary_requirements"] = []
        outcome, _, reasons = brns_logic.decide_outcome(candidate, no_cuisine)
        self.assertEqual(outcome, "match")
        self.assertFalse(any("cuisine" in reason for reason in reasons))

    def test_help_inside_a_prompt_preserves_the_prompt(self):
        from BIS import io_manager as bis_io

        with (
            patch("builtins.input", side_effect=["/help search", "none"]),
            patch.object(bis_io, "display_help") as help_message,
        ):
            self.assertEqual(bis_io.read_input("Cuisine: "), "none")
        help_message.assert_called_once_with("search")

    def test_search_location_accepts_postal_and_coordinates_directly(self):
        from BIS import io_manager as bis_io

        for raw, latitude, longitude in (
                ("40197", 1.392471, 103.903706),
                ("540197", 1.392471, 103.903706),
                ("1.392471,103.903706", 1.392471, 103.903706)):
            with (
                self.subTest(raw=raw),
                patch.object(bis_io, "read_input", return_value=raw),
                patch.object(bis_io.data_manager, "lookup_cached_location",
                             return_value=None),
                patch.object(bis_io.ai_manager, "interpret_location") as ai,
                patch.object(bis_io.data_manager, "resolve_location",
                             return_value={"query": raw, "label": raw,
                                           "latitude": latitude,
                                           "longitude": longitude}) as resolve,
                patch.object(bis_io.data_manager, "remember_location"),
                patch.object(bis_io, "ask_yes_no", return_value=True),
            ):
                location = bis_io.ask_search_location({})
            self.assertEqual(location["latitude"], latitude)
            resolve.assert_called_once_with(raw, "")
            ai.assert_not_called()

    def test_locked_geocode_cache_does_not_abort_location_search(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "geocode_cache.json"
            original = '{"existing": [1.39, 103.9]}\n'
            cache_file.write_text(original, encoding="utf-8")
            with (
                patch.object(geocode_cache, "CACHE_FILE", cache_file),
                patch.object(geocode_cache.os, "replace",
                             side_effect=PermissionError(5, "Access denied")) as replace,
                patch.object(geocode_cache.time, "sleep"),
            ):
                saved = geocode_cache.remember(
                    ("530912",), 1.392471, 103.903706)
            self.assertFalse(saved)
            self.assertEqual(replace.call_count, 3)
            self.assertEqual(cache_file.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(directory).glob(".geocode-*.tmp")), [])

    def test_geocode_cache_retries_a_temporary_windows_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "geocode_cache.json"
            original_replace = geocode_cache.os.replace
            attempts = []

            def replace_after_unlock(source, target):
                attempts.append((source, target))
                if len(attempts) == 1:
                    raise PermissionError(5, "Access denied")
                return original_replace(source, target)

            with (
                patch.object(geocode_cache, "CACHE_FILE", cache_file),
                patch.object(geocode_cache.os, "replace",
                             side_effect=replace_after_unlock),
                patch.object(geocode_cache.time, "sleep"),
            ):
                saved = geocode_cache.remember(
                    ("530912",), 1.392471, 103.903706)
            self.assertTrue(saved)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(json.loads(cache_file.read_text(encoding="utf-8")),
                             {"530912": [1.392471, 103.903706]})

    def test_bis_uses_own_model_chain_after_primary_failure(self):
        from BIS import ai_manager as bis_ai

        with (
            patch.object(bis_ai, "_call_openrouter",
                         side_effect=RuntimeError("primary failed")),
            patch.object(bis_ai, "MODEL_CHAIN", [
                {"provider": "gemini", "model": "test-gemini"}]),
            patch.object(brns_config, "MODEL_CHAIN", []),
            patch.object(brns_ai, "_call_gemini",
                         side_effect=AssertionError("BRNS must not be called")),
            patch.object(bis_ai, "_call_gemini",
                         return_value='{"choice":"walk"}') as backup,
        ):
            result = bis_ai.interpret_search_choice(
                "qalk", ("walk", "drive"),
                {"ai_bypass": False, "openrouter_model": "primary",
                 "gemini_api_key": "test-key"})
        self.assertEqual(result, "walk")
        backup.assert_called_once()

    def test_bis_gemini_transport_uses_bis_configuration(self):
        from BIS import ai_manager as bis_ai
        from unittest.mock import Mock

        response = Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {
            "parts": [{"text": '{"choice":"walk"}'}]}}]}
        payload = {"messages": [
            {"role": "system", "content": "Return JSON"},
            {"role": "user", "content": "qalk"}], "temperature": 0}
        with patch.object(bis_ai.requests, "post", return_value=response) as post:
            result = bis_ai._call_gemini(
                payload, "test-gemini", {"gemini_api_key": "bis-key"})
        self.assertEqual(result, '{"choice":"walk"}')
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"],
                         "bis-key")

    def test_bis_falls_back_after_invalid_model_choice(self):
        from BIS import ai_manager as bis_ai

        with (
            patch.object(bis_ai, "_call_openrouter",
                         return_value='{"choice":"fly"}'),
            patch.object(bis_ai, "MODEL_CHAIN", [
                {"provider": "gemini", "model": "test-gemini"}]),
            patch.object(bis_ai, "_call_gemini",
                         return_value='{"choice":"drive"}'),
        ):
            self.assertEqual(bis_ai.interpret_search_choice(
                "driev", ("walk", "drive"),
                {"ai_bypass": False, "openrouter_model": "primary",
                 "gemini_api_key": "test-key"}),
                "drive")

    def test_profile_free_text_spellcheck_needs_confirmation(self):
        from BIS import io_manager as bis_io

        user = {"preferences": empty_preferences()}
        with (
            patch.object(bis_io, "read_input", return_value="spciy food"),
            patch.object(bis_io.ai_manager, "review_prompt_text",
                         return_value="spicy food") as review,
            patch.object(bis_io, "ask_yes_no", return_value=True) as confirm,
        ):
            action = bis_io.collect_action(
                user, {"ai_bypass": False}, field="other_preferences")
        self.assertEqual(action["updates"]["other_preferences"],
                         ["spicy food"])
        review.assert_called_once()
        confirm.assert_called_once()

    def test_search_collection_uses_one_optional_wish_question(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile.update(dietary_requirements=["halal"],
                       disliked_cuisines=["western"],
                       liked_cuisines=["malay"])
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

    def test_new_search_cuisine_can_be_saved_or_used_once(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile.update(liked_cuisines=["chinese"],
                       disliked_cuisines=["thai"], dietary_requirements=[])
        user = {"preferences": profile}
        with (
            patch.object(bis_io, "ask_search_location",
                         return_value=request()["origin"]),
            patch.object(bis_io, "ask_search_mode", return_value="walk"),
            patch.object(bis_io, "ask_search_distance", return_value=2),
            patch.object(bis_io, "ask_search_cuisine", return_value="thai"),
            patch.object(bis_io, "ask_search_budget", return_value=10),
            patch.object(bis_io, "ask_search_wishes",
                         return_value={"selected": [], "text": ""}),
            patch.object(bis_io, "ask_yes_no", side_effect=[True, False]) as ask,
        ):
            saved = bis_io.collect_search(user, {})
            once = bis_io.collect_search(user, {})
        self.assertEqual(saved["save_cuisine"], "thai")
        self.assertIsNone(once["save_cuisine"])
        self.assertEqual(once["request"]["cuisine"], "thai")
        self.assertEqual(once["request"]["disliked_cuisines"], [])
        self.assertIn("remove it from disliked cuisines",
                      ask.call_args_list[0].args[0])

        session = {"user": {"userID": "test", "preferences": profile}}
        bis_main.remember_search_cuisine(session, "thai", {})
        self.assertEqual(session["user"]["preferences"]["liked_cuisines"],
                         ["chinese", "thai"])
        self.assertEqual(session["user"]["preferences"]["disliked_cuisines"],
                         [])
        self.saved_preferences.assert_called_with("test", session["user"][
            "preferences"], {})

    def test_search_saves_approved_new_cuisine_to_session(self):
        profile = empty_preferences()
        profile.update(location=["pasir ris"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=10,
                       dietary_requirements=[], liked_cuisines=["chinese"],
                       disliked_cuisines=[], other_preferences=[])
        session = {"user": {"userID": "test", "preferences": profile}}
        choice = dict(request(), cuisine="thai", dietary_requirements=[],
                      other_preferences=[])
        with (
            patch.object(bis_main.data_manager, "get_state", return_value=None),
            patch.object(bis_main.data_manager, "set_state"),
            patch.object(bis_main.io_manager, "collect_search",
                         return_value={"request": choice, "today_request": "",
                                       "save_cuisine": "thai"}),
            patch.object(bis_main.io_manager, "display_search_summary"),
        ):
            bis_main.run_search(session, {"ai_bypass": True})
        self.assertEqual(session["user"]["preferences"]["liked_cuisines"],
                         ["chinese", "thai"])

    def test_search_budget_interprets_natural_amount_with_confirmation(self):
        from BIS import io_manager as bis_io

        profile = empty_preferences()
        profile["budget_per_person"] = 10
        with (
            patch.object(bis_io, "read_input", return_value="i think 12"),
            patch.object(bis_io.ai_manager, "interpret_search_number",
                         return_value=12) as interpret,
            patch.object(bis_io, "ask_yes_no", return_value=True) as confirm,
        ):
            self.assertEqual(bis_io.ask_search_budget(
                profile, {"ai_bypass": False}), 12)
        interpret.assert_called_once_with(
            "i think 12", "budget_per_person", {"ai_bypass": False})
        confirm.assert_called_once()

        with (
            patch.object(bis_io, "read_input",
                         side_effect=["i think 12", "13"]),
            patch.object(bis_io.ai_manager, "interpret_search_number",
                         return_value=12),
            patch.object(bis_io, "ask_yes_no", return_value=False),
        ):
            self.assertEqual(bis_io.ask_search_budget(
                profile, {"ai_bypass": False}), 13)

    def test_search_distance_interprets_natural_units_with_confirmation(self):
        from BIS import io_manager as bis_io

        with (
            patch.object(bis_io, "read_input",
                         return_value="about 500 metres"),
            patch.object(bis_io.ai_manager, "interpret_search_number",
                         return_value=0.5) as interpret,
            patch.object(bis_io, "ask_yes_no", return_value=True),
        ):
            self.assertEqual(bis_io.ask_search_distance(
                empty_preferences(), "drive", {"ai_bypass": False}), 0.5)
        interpret.assert_called_once()

    def test_search_number_ai_rejects_non_numeric_reply(self):
        from BIS import ai_manager as bis_ai

        with (
            patch.object(bis_ai, "_call_openrouter",
                         return_value='{"value":true}'),
            patch.object(bis_ai, "MODEL_CHAIN", []),
        ):
            with self.assertRaises(RuntimeError):
                bis_ai.interpret_search_number(
                    "i think 12", "budget_per_person",
                    {"openrouter_model": "test"})

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

        with (
            patch.object(bis_ai, "_call_openrouter",
                         return_value='{"status":"ok","text":"new wish"}'),
            patch.object(bis_ai, "MODEL_CHAIN", []),
        ):
            with self.assertRaisesRegex(RuntimeError, "models are unavailable"):
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

    def test_full_price_range_can_confirm_budget(self):
        candidate = {"name": "Budget Cafe", "cuisines": ["malay"],
                     "avg_price": None, "price_start": 5,
                     "price_end": 9, "walk_meters": 800,
                     "walk_source": "route"}
        wanted = dict(request(), dietary_requirements=[])
        results = brns_logic.rank_restaurants(
            [candidate], wanted,
            [{"id": 0, "reason_codes": ["within_budget"]}])
        self.assertEqual(len(results["matches"]), 1)
        self.assertIn("listed price range is within your budget",
                      results["matches"][0]["reasons"])
        candidate["price_end"] = 15
        results = brns_logic.rank_restaurants([candidate], wanted)
        self.assertEqual(len(results["alternatives"]), 1)
        self.assertIn("! some prices may fit; full budget unverified",
                      results["alternatives"][0]["reasons"])

    def test_over_limit_route_explains_distance(self):
        candidate = {"name": "Far Cafe", "cuisines": [], "avg_price": 8,
                     "walk_meters": 13040, "walk_source": "route"}
        wanted = dict(request(), cuisine="none", max_distance_km=10,
                      dietary_requirements=[])
        results = brns_logic.rank_restaurants([candidate], wanted)
        self.assertIn("! route is 13.04 km, over your 10 km limit",
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
