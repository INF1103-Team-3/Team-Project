"""Offline contract tests for the BIS/BRNS OOP refactor."""

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
            recommend_candidates=lambda *_args, **_kwargs:
                events.append("ai") or recommendations,
        )
        logic_manager = SimpleNamespace(
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
