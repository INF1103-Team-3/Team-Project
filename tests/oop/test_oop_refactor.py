"""Offline contract tests for the BiteFinder OOP refactor."""

import ast
import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

from BIS.classes.base_search_request_validator import (
    BaseSearchRequestValidator,
)
from BIS.classes.bis_ai_manager_interface import BISAIManagerInterface
from BIS.classes.bis_data_manager_interface import BISDataManagerInterface
from BIS.classes.bis_logic_manager_interface import BISLogicManagerInterface
from BIS.classes.bis_search_workflow import BISSearchWorkflow
from BIS.classes.ai_provider_interface import AIProviderInterface
from BIS.classes.ai_provider_factory_registry import (
    AIProviderFactoryRegistry as BISAIProviderFactoryRegistry,
)
from BIS.classes.ai_provider_router import AIProviderRouter
from BIS.classes.base_ai_provider import BaseAIProvider
from BIS.classes.gemini_ai_provider import GeminiAIProvider
from BIS.classes.openrouter_ai_provider import OpenRouterAIProvider
from BIS.classes.json_user_store import JsonUserStore
from BIS.classes.search_request_validator import (
    SearchRequestValidator,
    create_search_request_validator,
)
from BIS.classes.search_request_validator_interface import (
    SearchRequestValidatorInterface,
)
from BIS.classes.session_action_dispatcher import SessionActionDispatcher
from BIS.support.email_verification.classes.challenge_manager_interface import (
    ChallengeManagerInterface,
)
from BIS.support.email_verification.classes.email_delivery_interface import (
    EmailDeliveryInterface,
)
from BIS.support.email_verification.classes.email_verification_service import (
    EmailVerificationService,
)
from BIS.support.email_verification.classes.smtp_email_delivery import (
    SMTPEmailDelivery,
)
from BIS.support.email_verification.classes.verification_challenge_manager import (
    VerificationChallengeManager,
)
from BRNS.classes.base_result_sorter import BaseResultSorter
from BRNS.classes.brns_ai_manager_interface import BRNSAIManagerInterface
from BRNS.classes.brns_data_manager_interface import BRNSDataManagerInterface
from BRNS.classes.brns_logic_manager_interface import (
    BRNSLogicManagerInterface,
)
from BRNS.classes.brns_recommendation_workflow import (
    BRNSRecommendationWorkflow,
)
from BRNS.classes.ai_provider_interface import (
    AIProviderInterface as BRNSAIProviderInterface,
)
from BRNS.classes.ai_provider_factory_registry import (
    AIProviderFactoryRegistry as BRNSAIProviderFactoryRegistry,
)
from BRNS.classes.ai_provider_router import (
    AIProviderRouter as BRNSAIProviderRouter,
)
from BRNS.classes.base_ai_provider import (
    BaseAIProvider as BRNSBaseAIProvider,
)
from BRNS.classes.distance_result_sorter import DistanceResultSorter
from BRNS.classes.gemini_ai_provider import (
    GeminiAIProvider as BRNSGeminiAIProvider,
)
from BRNS.classes.json_recommendation_store import JsonRecommendationStore
from BRNS.classes.openrouter_ai_provider import (
    OpenRouterAIProvider as BRNSOpenRouterAIProvider,
)
from BRNS.classes.rating_result_sorter import RatingResultSorter
from BRNS.classes.recommendation_sorter import RecommendationSorter
from BRNS.classes.result_sorter_interface import ResultSorterInterface
from BRNS.classes.result_sorter_registry import ResultSorterRegistry
from BRC.classes.fallback_ai_client import FallbackAIClient


def search_request():
    return {
        "origin": {
            "query": "Tampines",
            "label": "Tampines, Singapore",
            "latitude": 1.352,
            "longitude": 103.944,
        },
        "mode": "walk",
        "max_distance_km": 2.0,
        "max_travel_minutes": None,
        "traffic_aware": False,
        "cuisine": "japanese",
        "budget_per_person": 20.0,
        "other_preferences": ["spicy food"],
        "dietary_requirements": [],
        "disliked_cuisines": [],
    }


def result_set():
    return {
        "mode": "walk",
        "matches": [
            {"restaurant": {
                "name": "Higher Far", "rating": 4.8,
                "rating_count": 100, "walk_meters": 1200,
            }},
            {"restaurant": {
                "name": "Lower Near", "rating": 4.1,
                "rating_count": 300, "walk_meters": 200,
            }},
        ],
        "alternatives": [],
    }


class OOPRefactorTests(unittest.TestCase):
    def test_bis_logic_retains_omitted_wish_without_mutation(self):
        from BIS.classes.logic_manager import LogicManager
        from copy import deepcopy
        request = search_request()
        request["other_preferences"] = []
        before = deepcopy(request)
        manager = LogicManager()
        result = manager.preserve_search_wish(request, request, "quiet seating")
        self.assertEqual(result["other_preferences"], ["quiet seating"])
        self.assertEqual(request, before)
        interpreted = dict(request, other_preferences=["spicy food"])
        self.assertIs(manager.preserve_search_wish(request, interpreted, "spicy"), interpreted)

    def test_bis_router_accepts_provider_implementing_only_public_contract(self):
        class ContractProvider(AIProviderInterface):
            @property
            def primary(self):
                return False

            @property
            def label(self):
                return "sample/model"

            def request(self, payload, config):
                raise RuntimeError("offline")

        router = AIProviderRouter([ContractProvider()], json.loads, lambda *_args: None)
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            router.route({}, {})

    def test_brns_logic_rejects_missing_required_readers_at_construction(self):
        from BRNS.classes.logic_manager import LogicManager
        with self.assertRaisesRegex(TypeError, "must be callable"):
            LogicManager(lambda x: x, lambda *_a: None, lambda *_a: [],
                         3, 3, None, None, lambda *_a: None, SimpleNamespace())

    def test_brns_saved_candidate_policy_and_search_order(self):
        from BRNS import logic_manager, data_manager
        logic = logic_manager.manager()
        request = search_request()
        request["other_preferences"] = ["quiet", "must have outdoor seating"]
        lookup = logic.prepare_candidate_search(request)
        self.assertEqual(lookup["free_text"], "must have outdoor seating quiet")
        self.assertEqual(request["other_preferences"][0], "quiet")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "restaurants.json"
            for value in (None, "invalid json", '{}'):
                if value is not None:
                    path.write_text(value)
                self.assertEqual(data_manager.manager().load_candidate_records(path), [])
            path.write_text(json.dumps([{"name": "Cafe", "cuisine": "japanese",
                                         "g_rating": "4.2", "g_no_reviews": "9"}, None]))
            rows = data_manager.manager().load_candidate_records(path)
            candidates = logic.saved_candidates(rows)
            self.assertEqual(candidates[0]["cuisines"], ["japanese"])
            self.assertEqual(candidates[0]["rating"], 4.2)
            self.assertEqual(candidates[0]["rating_count"], 9)

    def test_brns_context_preserves_prompt_facts_and_previous_names(self):
        from BRNS import logic_manager
        request = search_request()
        request["other_preferences"] = ["at least 4.5 stars"]
        candidate = {"name": "Cafe", "rating": 4.6, "rating_count": 100,
                     "walk_minutes": 12, "walk_meters": 600}
        context = logic_manager.manager().recommendation_context(
            request, [candidate], [{"name": "Cafe"}, {"name": "Cafe"}])
        self.assertEqual(list(context), ["request", "minimum_rating", "preferred_rating",
                                        "hard_cuisines", "hard_preferences", "candidates",
                                        "previous_restaurants"])
        self.assertEqual(context["minimum_rating"], 4.5)
        self.assertEqual(context["previous_restaurants"], ["Cafe"])
        self.assertEqual(context["candidates"][0]["travel_minutes"], 12)
        self.assertEqual(context["candidates"][0]["confidence_adjusted_rating"],
                         logic_manager.confidence_adjusted_rating(4.6, 100))

    def test_brc_cuisine_job_preserves_skips_checkpoints_and_partial_failure(self):
        from BRC.classes.cuisine_tagging_workflow import CuisineTaggingWorkflow
        from BRC.classes.logic_manager import LogicManager
        from BRC.classes.ai_response_error import AIResponseError
        rows = [SimpleNamespace(name=name, category="")
                for name in ("Cached", "Nasi Cafe", "Unknown One", "Unknown Two")]
        values = {"Cached": ["chinese"]}
        cache = SimpleNamespace(get=lambda row: values.get(row.name),
                                put=lambda row, tags: values.__setitem__(row.name, tags))
        checkpoints, batches = [], []

        def tag(batch):
            batches.append([index for index, _ in batch])
            if batch[0][0] == 2:
                raise AIResponseError("malformed")
            return {3: ["western"]}

        ai = SimpleNamespace(batch_size=lambda: 1, tag_batch=tag)
        result = CuisineTaggingWorkflow(lambda *_a: None).run(
            rows, cache, ai, LogicManager(), lambda _cache: checkpoints.append(dict(values)))
        self.assertEqual(result, [["chinese"], ["malay"], [], ["western"]])
        self.assertEqual(batches, [[2], [3]])
        self.assertEqual(len(checkpoints), 2)
        self.assertNotIn("Unknown One", values)

    def test_brc_outlet_job_preserves_exact_and_service_failure_policy(self):
        from BRC.classes.outlet_matching_workflow import OutletMatchingWorkflow
        from BRC.classes.ai_service_error import AIServiceError
        rows = [SimpleNamespace(to_dict=lambda: {"name": "Cafe"}) for _ in range(3)]
        calls = []

        def propose(number, record, candidates):
            calls.append(number)
            raise AIServiceError("offline")

        result = OutletMatchingWorkflow(lambda *_a: None).run(
            rows, [[object()]] * 3, ["EXACT", None, None], SimpleNamespace(propose_match=propose))
        self.assertEqual(result, ["EXACT", None, None])
        self.assertEqual(calls, [2])

    def test_brc_http_routes_preserve_request_response_contract(self):
        import threading
        import http.client
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        from BRC.classes.brc_http_handler import BRCRequestHandler
        received = []

        def check(value):
            received.append(value)
            return dict(value, halal_certification="none")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            with patch.object(BRCRequestHandler, "application_run", staticmethod(check)), \
                    patch.object(BRCRequestHandler, "database_path", path):
                server = ThreadingHTTPServer(("127.0.0.1", 0), BRCRequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                try:
                    for route, expected in (("/health", {"status": "ok"}),
                                            ("/status", {"database_exists": False})):
                        connection.request("GET", route)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.loads(response.read()), expected)
                    value = {"name": "Cafe", "postal_code": "123456"}
                    connection.request("POST", "/check", json.dumps(value),
                                       {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()),
                                     dict(value, halal_certification="none"))
                    self.assertEqual(received, [value])
                    connection.request("POST", "/check", '{')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    self.assertIn("error", json.loads(response.read()))
                finally:
                    connection.close()
                    server.shutdown()
                    thread.join(timeout=3)
                    server.server_close()

    def test_wish_collector_handles_plain_text_without_constraint_classification(self):
        from BIS.classes.search_wish_collector import SearchWishCollector
        from BIS.classes.logic_manager import LogicManager
        from unittest.mock import Mock
        ui = SimpleNamespace(section=Mock(), item=Mock())
        io = SimpleNamespace(read_input=lambda *_a: "quiet seating",
                             _cancelled=lambda _v: False, display_message=Mock(),
                             ask_yes_no=Mock())
        ai = SimpleNamespace(review_special_request=lambda text, _config: text,
                             classify_search_constraints=Mock())
        logic = SimpleNamespace(validate_special_request_text=lambda text: text,
                                apply_search_constraints=LogicManager.apply_search_constraints)
        result = SearchWishCollector(io, ai, logic, ui).collect(
            {"other_preferences": []}, {})
        self.assertEqual(result, {"selected": [], "text": "quiet seating"})
        ai.classify_search_constraints.assert_not_called()
        io.ask_yes_no.assert_not_called()

    def test_wish_collector_confirms_and_encodes_soft_rating_as_minimum(self):
        from BIS.classes.search_wish_collector import SearchWishCollector
        from BIS.classes.logic_manager import LogicManager
        from unittest.mock import Mock
        io = SimpleNamespace(read_input=lambda *_a: "4.5 stars",
                             _cancelled=lambda _v: False, display_message=Mock(),
                             ask_yes_no=Mock(return_value=True))
        ai = SimpleNamespace(review_special_request=lambda text, _config: text,
                             classify_search_constraints=lambda *_a: dict(
                                 rating=4.5, rating_is_minimum=False,
                                 hard_requirement=False, hard_cuisine=None))
        logic = SimpleNamespace(validate_special_request_text=lambda text: text,
                                apply_search_constraints=LogicManager.apply_search_constraints)
        result = SearchWishCollector(io, ai, logic, SimpleNamespace()).collect(
            {"other_preferences": []}, {})
        self.assertEqual(result["text"], "4.5 stars, at least 4.5 stars")
        io.ask_yes_no.assert_called_once()

    def test_restaurant_enrichment_preserves_live_precedence_and_missing_facts(self):
        from BRNS.classes.restaurant_enricher import RestaurantEnricher
        from copy import deepcopy
        enricher = RestaurantEnricher()
        place = dict(name="Cafe", address="1 Road", lat=1.3, lng=103.8,
                     types=["japanese_restaurant"], rating=4.7,
                     serves_vegetarian_food=True)
        original = deepcopy(place)
        live = enricher.enrich(place, [])
        self.assertEqual(live["cuisines"], ["japanese"])
        self.assertIsNone(live["avg_price"])
        self.assertIsNone(live["price_band"])
        self.assertEqual(live["source"], "google places")
        saved = [dict(name="Cafe", address="1 Road", avg_price=12,
                      cuisines=["korean"], dietary=["halal"], rating=1)]
        merged = enricher.enrich(place, saved)
        self.assertEqual(merged["rating"], 4.7)
        self.assertEqual(merged["avg_price"], 12)
        self.assertEqual(merged["price_band"], "moderate")
        self.assertEqual(merged["dietary_requirements"], ["halal", "vegetarian"])
        self.assertEqual(merged["source"], "saved + google places")
        saved[0]["address"] = "Different branch"
        self.assertEqual(enricher.enrich(place, saved)["source"], "google places")
        self.assertEqual(place, original)

    def test_outcome_policy_preserves_scoring_order_and_estimate_rejection(self):
        from BRNS.classes.restaurant_outcome_policy import RestaurantOutcomePolicy
        from copy import deepcopy
        rules = SimpleNamespace(has_hard_preferences=lambda _p: False,
                                hard_required_cuisines=lambda _p: [],
                                minimum_rating=lambda _p: None)
        policy = RestaurantOutcomePolicy(rules)
        request = search_request()
        request["other_preferences"] = []
        restaurant = dict(source="google places", open_now=True,
                          cuisines=[request["cuisine"]], dietary_requirements=[],
                          avg_price=10, price_start=None, price_end=None,
                          walk_source="route", walk_meters=100)
        original = deepcopy(restaurant)
        outcome = policy.evaluate(restaurant, request)
        self.assertEqual(outcome, ("match", 3, ["matches your selected cuisine",
                         "average price is within your budget", "within your route distance limit"]))
        self.assertEqual(restaurant, original)
        restaurant["walk_source"] = "estimate"
        outcome = policy.evaluate(restaurant, request)
        self.assertEqual(outcome[0], "alternative")
        self.assertIn("! travel distance estimated or unavailable", outcome[2])

    def test_ai_provider_factories_are_open_to_registration(self):
        bis_registry = BISAIProviderFactoryRegistry()
        bis_registry.register(
            "custom", lambda model: ("bis", model),
            enabled=lambda config: config["enabled"],
        )
        self.assertEqual(
            bis_registry.create("custom", "model", {"enabled": True}),
            ("bis", "model"),
        )
        self.assertIsNone(
            bis_registry.create("custom", "model", {"enabled": False}))

        brns_registry = BRNSAIProviderFactoryRegistry()
        brns_registry.register(
            "custom", lambda model: ("brns", model))
        self.assertEqual(
            brns_registry.create("custom", "model"),
            ("brns", "model"),
        )

    def test_session_action_dispatcher_is_open_to_registration(self):
        calls = []
        dispatcher = SessionActionDispatcher(
            lambda action, from_ai: calls.append(
                ("fallback", action["action"], from_ai)))
        dispatcher.register(
            ("custom",),
            lambda action, from_ai: calls.append(
                ("custom", action["value"], from_ai)),
        )
        dispatcher.dispatch({"action": "custom", "value": 3}, True)
        dispatcher.dispatch({"action": "unknown"}, False)
        self.assertEqual(calls, [
            ("custom", 3, True),
            ("fallback", "unknown", False),
        ])

    def test_bis_search_workflow_orders_io_ai_logic_data(self):
        events = []
        request = search_request()
        io_manager = SimpleNamespace(
            display_message=lambda *_args, **_kwargs: None,
            collect_search=lambda _user, _config:
                events.append("io") or {
                    "request": request,
                    "today_request": "",
                    "save_cuisine": None,
                },
            confirm_search_request=lambda *_args: True,
        )
        ai_manager = SimpleNamespace(
            interpret_search_request=lambda *_args:
                events.append("ai") or request,
        )
        logic_manager = SimpleNamespace(
            next_field=lambda _preferences: None,
            validate_search_request=lambda *_args:
                events.append("logic") or request,
            preserve_search_wish=lambda _confirmed, request, *_args: request,
            is_search_clarification=lambda _error: False,
        )
        data_manager = SimpleNamespace(
            get_state=lambda *_args: None,
            serialize_search_request=lambda _request:
                events.append("data") or "payload",
        )
        preferences = SimpleNamespace(
            remember_cuisine=lambda *_args: None,
            remember_wishes=lambda *_args: None,
        )
        results = SimpleNamespace(run=lambda *_args: None)
        logger = SimpleNamespace(
            start_trace=lambda: "trace",
            end_trace=lambda _trace: None,
            debug_log=lambda *_args: None,
            current_trace_id=lambda: "trace",
        )
        workflow = BISSearchWorkflow(
            io_manager, ai_manager, logic_manager, data_manager,
            preferences, results, logger, "other_preferences",
        )
        workflow.run({
            "user": {
                "userID": "user-1",
                "preferences": {},
            },
        }, {"ai_bypass": False})
        self.assertEqual(events, ["io", "ai", "logic", "data"])

    def test_brns_workflow_orders_io_ai_logic_data(self):
        events = []
        request = {"dietary_requirements": []}
        candidates = [{"name": "Cafe"}]
        recommendations = [{"id": 0, "reason_codes": []}]
        results = {"matches": [], "alternatives": [], "hidden": 1}
        io_manager = SimpleNamespace(
            accept_bis_json=lambda _payload:
                events.append("io") or request,
            find_candidates=lambda _request: candidates,
            show_ai_ranking_start=lambda *_args: None,
        )
        ai_manager = SimpleNamespace(
            has_configured_provider=lambda: True,
            recommend_prepared=lambda *_args, **_kwargs:
                events.append("ai") or recommendations,
        )
        logic_manager = SimpleNamespace(
            recommendation_context=lambda *_args: {},
            rank_restaurants=lambda *_args, **_kwargs:
                events.append("logic") or results,
        )
        data_manager = SimpleNamespace(
            save_restaurants=lambda _candidates:
                events.append("data") or 1,
            save_search_results=lambda *_args: True,
        )
        halal = SimpleNamespace(
            verify=lambda candidate_rows, _request, _recommendations:
                (candidate_rows, None),
        )
        config = SimpleNamespace(
            USE_LIVE_GOOGLE=False,
            GOOGLE_MAPS_API_KEY="",
            AI_CHAIN_TIMEOUT_SECONDS=30,
        )
        logger = SimpleNamespace(
            start_trace=lambda: "trace",
            end_trace=lambda _trace: None,
            debug_log=lambda *_args: None,
        )
        workflow = BRNSRecommendationWorkflow(
            io_manager, ai_manager, logic_manager, data_manager,
            halal, config, logger,
        )
        self.assertIs(workflow.search("payload"), results)
        self.assertEqual(events, ["io", "ai", "logic", "data"])

    def test_manager_interfaces_are_focused_abstract_contracts(self):
        for interface in (
                BISAIManagerInterface, BISLogicManagerInterface,
                BISDataManagerInterface, BRNSAIManagerInterface,
                BRNSLogicManagerInterface, BRNSDataManagerInterface):
            self.assertTrue(interface.__abstractmethods__)

    def test_email_challenge_manager_preserves_code_rules(self):
        manager = VerificationChallengeManager()
        self.assertIsInstance(manager, ChallengeManagerInterface)
        code, challenge = manager.create(
            now=1000, attempt_reset_seconds=600)
        self.assertRegex(code, r"^[0-9]{6}$")
        self.assertNotIn(code, challenge.values())
        checked, error = manager.check(
            challenge, code, now=1001, attempt_reset_seconds=600)
        self.assertIsNone(error)
        self.assertEqual(checked, challenge)
        failed, error = manager.check(
            challenge, "wrong", now=1001,
            attempt_reset_seconds=600,
        )
        self.assertEqual(error, "Incorrect verification code.")
        self.assertEqual(failed["attempts"], 1)

    def test_email_verification_service_composes_real_collaborators(self):
        state = {}
        saved_users = []
        sent = []

        data_manager = SimpleNamespace(
            get_state=lambda section, key: state.get((section, key)),
            set_state=lambda section, key, value:
                state.__setitem__((section, key), value),
            save=lambda user: saved_users.append(user) or user,
        )
        delivery = SimpleNamespace(
            send_verification_email=lambda email, code, config:
                sent.append((email, code, config)),
        )
        service = EmailVerificationService(
            data_manager, VerificationChallengeManager(), delivery)
        user = {
            "userID": "user-1",
            "email": "user@example.com",
            "email_verified": False,
        }
        config = {"verification_attempt_reset_seconds": 600}
        service.request_code(user, config)
        self.assertEqual(sent[0][0], "user@example.com")
        self.assertIn(("verification", "user-1"), state)
        verified = service.verify_code(user, sent[0][1], config)
        self.assertTrue(verified["email_verified"])
        self.assertEqual(saved_users, [verified])
        self.assertIsNone(state[("verification", "user-1")])
        self.assertIsInstance(SMTPEmailDelivery(), EmailDeliveryInterface)

    def test_ai_router_uses_polymorphic_provider_fallback(self):
        calls = []

        def fail_openrouter(payload, config):
            calls.append(("openrouter", payload["model"]))
            raise RuntimeError("simulated failure")

        def succeed_gemini(payload, config):
            calls.append(("gemini", payload["messages"][0]["role"]))
            return '{"status": "ok"}'

        providers = (
            OpenRouterAIProvider(
                "primary-model", fail_openrouter, primary=True),
            GeminiAIProvider("fallback-model", succeed_gemini),
        )
        logs = []
        router = AIProviderRouter(
            providers,
            json.loads,
            lambda *parts: logs.append(parts),
        )
        result = router.route(
            {
                "model": "original-model",
                "messages": [{"role": "system"}],
            }, {},
            validator=lambda value: value,
        )
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(calls, [
            ("openrouter", "primary-model"),
            ("gemini", "system"),
        ])
        for provider in providers:
            self.assertIsInstance(provider, BaseAIProvider)
            self.assertIsInstance(provider, AIProviderInterface)
        self.assertLess(
            OpenRouterAIProvider.__mro__.index(BaseAIProvider),
            OpenRouterAIProvider.__mro__.index(AIProviderInterface),
        )

    def test_brns_ai_router_uses_polymorphic_provider_fallback(self):
        calls = []
        delays = []

        def fail_gemini(system_prompt, user_text):
            calls.append(("gemini", system_prompt, user_text))
            return False, "429 rate limited"

        def succeed_openrouter(system_prompt, user_text):
            calls.append(("openrouter", system_prompt, user_text))
            return True, '{"ranked": true}'

        providers = (
            BRNSGeminiAIProvider("primary-model", fail_gemini),
            BRNSOpenRouterAIProvider("backup-model", succeed_openrouter),
        )
        logs = []
        router = BRNSAIProviderRouter(
            providers,
            json.loads,
            lambda value: (True, value),
            lambda detail: "rate limited" if "429" in detail else detail,
            lambda *parts: logs.append(parts),
            lambda seconds: delays.append(seconds),
        )
        result = router.route("system", "user")
        self.assertEqual(
            result,
            (True, {"ranked": True}, "openrouter/backup-model"),
        )
        self.assertEqual(calls, [
            ("gemini", "system", "user"),
            ("openrouter", "system", "user"),
        ])
        self.assertEqual(delays, [1])
        self.assertEqual(
            logs, [("fallback", "gemini/primary-model: rate limited")])
        for provider in providers:
            self.assertIsInstance(provider, BRNSBaseAIProvider)
            self.assertIsInstance(provider, BRNSAIProviderInterface)
        self.assertLess(
            BRNSOpenRouterAIProvider.__mro__.index(BRNSBaseAIProvider),
            BRNSOpenRouterAIProvider.__mro__.index(
                BRNSAIProviderInterface),
        )

    def test_search_validator_parent_and_interface_contract(self):
        self.assertTrue(issubclass(
            SearchRequestValidator, BaseSearchRequestValidator))
        self.assertTrue(issubclass(
            SearchRequestValidator, SearchRequestValidatorInterface))
        mro = SearchRequestValidator.__mro__
        self.assertLess(
            mro.index(BaseSearchRequestValidator),
            mro.index(SearchRequestValidatorInterface),
        )
        self.assertEqual(
            create_search_request_validator().validate(search_request()),
            search_request(),
        )

    def test_ai_cannot_change_confirmed_search_choice(self):
        proposed = search_request()
        proposed["budget_per_person"] = 50.0
        with self.assertRaisesRegex(ValueError, "confirmed choice"):
            create_search_request_validator().validate(
                search_request(), proposed)

    def test_sort_strategies_are_substitutable_and_polymorphic(self):
        sorters = (RatingResultSorter(), DistanceResultSorter())
        for sorter in sorters:
            self.assertIsInstance(sorter, BaseResultSorter)
            self.assertIsInstance(sorter, ResultSorterInterface)
            self.assertEqual(len(sorter.sort(result_set())["matches"]), 2)
        self.assertEqual(
            sorters[0].sort(result_set())["matches"][0]["restaurant"]["name"],
            "Higher Far",
        )
        self.assertEqual(
            sorters[1].sort(result_set())["matches"][0]["restaurant"]["name"],
            "Lower Near",
        )

    def test_sorter_registry_aggregates_independent_strategies(self):
        rating = RatingResultSorter()
        distance = DistanceResultSorter()
        registry = ResultSorterRegistry((rating, distance))
        service = RecommendationSorter(registry)
        self.assertIs(registry.get("rating"), rating)
        self.assertEqual(
            service.sort(result_set(), "distance")["matches"][0]
            ["restaurant"]["name"],
            "Lower Near",
        )
        with self.assertRaisesRegex(ValueError, "rating or distance"):
            service.sort(result_set(), "name")

    def test_bis_json_store_persists_compatible_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            users = Path(directory) / "users.json"
            state = Path(directory) / "profile_state.json"
            store = JsonUserStore(users, state)
            saved = store.register_user("user@example.com", "User")
            self.assertEqual(store.find_user("USER@example.com"), saved)
            self.assertEqual(store.query(
                lambda row: row["email"] == "user@example.com"), [saved])
            self.assertIn('"preferences"', users.read_text(encoding="utf-8"))

    def test_brns_json_store_preserves_restaurant_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            restaurants = Path(directory) / "restaurants.json"
            history = Path(directory) / "search_history.json"
            restaurants.write_text("[]\n", encoding="utf-8")
            store = JsonRecommendationStore(restaurants, history)
            count = store.save_restaurants([{
                "google_place_id": "place-1",
                "name": "Test Cafe",
                "address": "1 Test Road, Singapore 123456",
                "rating": 4.5,
                "rating_count": 10,
                "dietary_requirements": [],
                "cuisines": ["cafe"],
            }])
            self.assertEqual(count, 1)
            record = store.load_restaurants()[0]
            self.assertEqual(record["postal_code"], "123456")
            self.assertEqual(record["g_rating"], "4.5")
            self.assertEqual(record["halal_certification"], "none")

    def test_production_classes_have_one_subsystem_class_file_each(self):
        for subsystem in ("BIS", "BRNS", "BRC"):
            for path in (ROOT / subsystem).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                classes = [
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)]
                self.assertLessEqual(
                    len(classes), 1,
                    f"{path.relative_to(ROOT)} defines multiple classes")
                if classes:
                    self.assertIn(
                        "classes", path.parts,
                        f"{path.relative_to(ROOT)} defines a class outside "
                        "its subsystem classes directory")

    def test_brc_production_client_falls_back_after_invalid_json(self):
        calls = []
        settings = {
            "providers": [
                {"provider": "gemini", "model": "first"},
                {"provider": "groq", "model": "second"},
            ],
            "chain_timeout_seconds": 10,
            "timeout_seconds": 2,
            "report": None,
        }

        def gemini(_prompt, _settings, model):
            calls.append(("gemini", model))
            return "not-json"

        def chat(_prompt, _settings, provider, model, _timeout):
            calls.append((provider, model))
            return '{"certificate_number": null}'

        client = FallbackAIClient(settings, gemini, chat)
        result = client.request_validated("prompt", json.loads)
        self.assertEqual(result, {"certificate_number": None})
        self.assertEqual(calls, [
            ("gemini", "first"), ("groq", "second")])

    def test_fetch_by_profile_text_anchors_to_midpoint_for_drive_and_transit(self):
        from unittest.mock import patch
        from BRNS import io_manager as brns_io

        captured = []
        midpoint = (1.322544, 103.840973)

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.append((url, json, timeout))
            payload = {
                "places": [
                    {
                        "id": "near-midpoint",
                        "displayName": {"text": "Novena Ramen"},
                        "formattedAddress": "101 Thomson Rd",
                        "location": {"latitude": 1.320, "longitude": 103.844},
                        "types": ["japanese_restaurant"],
                    },
                    {
                        "id": "too-far-away",
                        "displayName": {"text": "Outer Island Ramen"},
                        "formattedAddress": "1 Tuas Link",
                        "location": {"latitude": 1.340, "longitude": 103.636},
                        "types": ["japanese_restaurant"],
                    },
                ]
            }
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: payload,
            )

        for mode in ("drive", "transit"):
            captured.clear()
            req = {
                "mode": mode,
                "max_travel_minutes": 30,
                "cuisine": "japanese",
                "dietary_requirements": [],
                "free_text": "",
            }
            with patch.object(brns_io.requests, "post", side_effect=fake_post), \
                    patch.object(brns_io.config, "GOOGLE_MAPS_API_KEY", "test-key"):
                results = brns_io.fetch_by_profile_text(midpoint, req)

            self.assertEqual(len(captured), 1)
            _, body, _ = captured[0]
            self.assertEqual(body["rankPreference"], "DISTANCE")
            self.assertNotIn("locationRestriction", body)
            self.assertEqual(
                body["locationBias"],
                {
                    "circle": {
                        "center": {"latitude": midpoint[0], "longitude": midpoint[1]},
                        "radius": 19500.0,
                    }
                },
            )
            self.assertEqual([item["google_place_id"] for item in results], ["near-midpoint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
