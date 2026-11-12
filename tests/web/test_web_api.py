"""Offline contracts for web/OOP integration; never use live external APIs."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "BIS")]
os.environ["BITEFINDER_STORAGE"] = "json"
for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_API_KEYS",
            "OPENROUTER_API_KEYS_FILE", "GOOGLE_MAPS_API_KEY"):
    os.environ.pop(key, None)

import mongomock
from fastapi.testclient import TestClient
from BIS.classes.mongo_connection import MongoConnection
from BIS.classes.mongo_user_store import MongoUserStore
from BIS.classes.mongo_session_store import MongoSessionStore
from BIS.classes.mongo_favorite_store import MongoFavoriteStore
from BIS.classes.mongo_credential_store import MongoCredentialStore
from BIS.classes.mongo_search_proposal_store import MongoSearchProposalStore
from BIS.classes.data_manager import DataManager
from BIS.classes.logic_manager import LogicManager
from BIS.classes.password_hasher import PasswordHasher
from BIS.classes.web_auth_service import WebAuthService
from BIS.classes.favorite_service import FavoriteService
from BIS.classes.bis_application_service import BISApplicationService
from BIS.classes.web_io_manager import WebIOManager
from BIS.classes.web_runtime import WebRuntime
from BIS.support.email_verification.classes.email_verification_service import EmailVerificationService
from BIS.support.email_verification.classes.verification_challenge_manager import VerificationChallengeManager
from BRNS.classes.mongo_recommendation_store import MongoRecommendationStore
from BRNS.classes.search_history_scope import SearchHistoryScope
from BRNS.classes.data_manager import DataManager as RecommendationData
from web_api import create_app


class WebIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = MongoConnection(client=mongomock.MongoClient(), database="isolated_tests")
        self.users = MongoUserStore(self.conn)
        self.sessions = MongoSessionStore(self.conn)
        self.favorites = MongoFavoriteStore(self.conn)
        self.proposals = MongoSearchProposalStore(self.conn)
        for store in (self.users, self.sessions, self.favorites, self.proposals):
            store.ensure_indexes()
        self.gateway = SimpleNamespace(resolve=lambda query, _key: dict(
            query=query, label=query, latitude=1.35, longitude=103.94))
        self.data = DataManager(self.users, self.gateway, self.sessions, self.favorites,
                                MongoCredentialStore(self.conn), self.proposals)
        self.sent = []
        delivery = SimpleNamespace(send_verification_email=lambda email, code, _config: self.sent.append((email, code)))
        self.verification = EmailVerificationService(self.data, VerificationChallengeManager(), delivery)
        self.config = {"verification_attempt_reset_seconds": 600, "google_maps_api_key": ""}
        self.auth = WebAuthService(self.data, self.verification, PasswordHasher(), self.config)
        self.scope = SearchHistoryScope()
        self.history = RecommendationData(MongoRecommendationStore(self.conn, self.scope))
        self.ranking_calls = []
        self.ai_calls = []
        def interpret(request, wishes, config):
            self.ai_calls.append(request)
            return request
        self.ai = SimpleNamespace(interpret_search_request=interpret)
        def search(payload):
            import json
            request = json.loads(payload)
            self.ranking_calls.append(request)
            results = {"matches": [], "alternatives": [], "hidden": 0}
            self.history.save_search_results(request, results, "live-google")
            return results
        self.application = BISApplicationService(self.data, self.ai, LogicManager(),
            SimpleNamespace(search=search), SimpleNamespace(route_to=lambda r, q: {
                "name": r["name"], "mode": q["mode"], "route": None, "link": "https://www.google.com/maps"}),
            self.history, self.scope, self.config, lambda: "fixture/provider")
        self.io = WebIOManager(self.data, self.auth, self.application, FavoriteService(self.data), self.conn.ready)
        self.client = TestClient(create_app(lambda: WebRuntime(self.io, self.conn)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def account(self, email="user@example.com"):
        response = self.client.post("/api/auth/register", json={
            "username": "Tester", "email": email, "password": "test-password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["otp_required"])
        response = self.client.post("/api/auth/verify-otp", json={"email": email, "code": self.sent[-1][1]})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}, response.json()["user"]

    @staticmethod
    def search_payload():
        return {"location": "Tampines", "mode": "walk", "max_travel_minutes": 20,
                "max_distance_km": None, "budget_per_person": 20, "cuisine": "japanese",
                "dietary_requirements": [], "disliked_cuisines": [], "other_preferences": []}

    def test_auth_requires_real_challenge_even_for_example_domain(self):
        headers, user = self.account()
        self.assertTrue(user["email_verified"])
        self.assertNotIn("password_hash", str(user))
        self.assertNotIn("password_salt", str(user))
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)
        self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_cli_account_is_not_claimed_before_email_proof(self):
        user = self.data.register_user("cli@example.com", "CLI")
        response = self.client.post("/api/auth/login", json={"email": user["email"], "password": "new-password"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["otp_required"])
        self.assertIsNone(self.data.get_credentials(user["userID"]))
        response = self.client.post("/api/auth/verify-otp", json={"email": user["email"], "code": "wrong"})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.data.get_credentials(user["userID"]))
        response = self.client.post("/api/auth/verify-otp", json={"email": user["email"], "code": self.sent[-1][1]})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.data.get_credentials(user["userID"]))

    def test_wrong_password_resend_and_attempt_limits(self):
        headers, user = self.account()
        wrong = self.client.post("/api/auth/login", json={"email": user["email"], "password": "incorrect"})
        self.assertEqual(wrong.status_code, 401)
        login = self.client.post("/api/auth/login", json={"email": user["email"], "password": "test-password"})
        self.assertEqual(login.status_code, 200)
        resend = self.client.post("/api/auth/resend-otp", json={"email": user["email"]})
        self.assertEqual(resend.status_code, 400)
        for _ in range(5):
            self.assertEqual(self.client.post("/api/auth/verify-otp", json={"email": user["email"], "code": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/verify-otp", json={"email": user["email"], "code": self.sent[-1][1]}).status_code, 400)

    def test_profiles_share_cli_data_without_json_sync(self):
        headers, user = self.account()
        payload = dict(user, username="Updated")
        payload.pop("email_verified")
        payload.update(location=["Tampines"], max_distance_km=2,
                       max_travel_time_minutes=40, budget_per_person=20)
        response = self.client.post("/api/profile", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        other_cli_store = MongoUserStore(self.conn)
        self.assertEqual(other_cli_store.get_user(user["user_id"])["username"], "Updated")
        other_cli_store.save(dict(other_cli_store.get_user(user["user_id"]), username="CLI updated"))
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).json()["user"]["username"], "CLI updated")
        payload["user_id"] = "another-user"
        self.assertEqual(self.client.post("/api/profile", json=payload, headers=headers).status_code, 401)

    def test_invalid_profile_is_rejected_before_any_record_is_saved(self):
        headers, user = self.account()
        before = self.data.get_user(user["user_id"])
        payload = dict(user, username="!", budget_per_person=25)
        payload.pop("email_verified")
        response = self.client.post("/api/profile", json=payload, headers=headers)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.data.get_user(user["user_id"]), before)

    def test_confirmation_is_one_use_and_only_then_calls_brns(self):
        headers, _ = self.account()
        payload = self.search_payload()
        first = self.client.post("/api/search", json=dict(payload, confirm_only=True), headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["confirmation_required"])
        self.assertEqual(len(self.ai_calls), 1)
        self.assertEqual(self.ranking_calls, [])
        payload["confirmation_token"] = first.json()["confirmation_token"]
        final = self.client.post("/api/search", json=payload, headers=headers)
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(final.json()["model_used"], "fixture/provider")
        self.assertEqual(len(self.ranking_calls), 1)
        self.assertEqual(len(self.ai_calls), 1)
        self.assertEqual(self.client.post("/api/search", json=payload, headers=headers).status_code, 400)
        self.assertEqual(len(self.client.get("/api/history", headers=headers).json()["history"]), 1)
        self.client.delete("/api/history", headers=headers)
        self.assertEqual(self.client.get("/api/history", headers=headers).json()["history"], [])

    def test_direct_search_supports_midpoint_and_multi_cuisine(self):
        headers, _ = self.account("multi@example.com")
        payload = dict(
            self.search_payload(),
            location="",
            locations=["Tampines", "Bedok"],
            cuisine="japanese, korean",
            liked_cuisines=["japanese", "korean"],
        )
        res = self.client.post("/api/search", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertFalse(data["confirmation_required"])
        self.assertEqual(len(data["input_origins"]), 2)
        self.assertEqual(data["selected_cuisines"], ["japanese", "korean"])
        self.assertEqual(len(self.ranking_calls), 2)

    def test_user_isolation_confirmation_and_favorites(self):
        first, _ = self.account("first@example.com")
        second, _ = self.account("second@example.com")
        payload = self.search_payload()
        token = self.client.post("/api/search", json=dict(payload, confirm_only=True), headers=first).json()["confirmation_token"]
        payload["confirmation_token"] = token
        self.assertEqual(self.client.post("/api/search", json=payload, headers=second).status_code, 400)
        self.assertEqual(self.client.post("/api/search", json=payload, headers=first).status_code, 200)
        restaurant = {"name": "Cafe", "address": "1 Road", "google_place_id": "fixture"}
        self.assertEqual(self.client.post("/api/favorites", json={"restaurant": restaurant}, headers=first).status_code, 200)
        self.assertEqual(self.client.get("/api/favorites", headers=second).json()["favorites"], [])
        self.assertEqual(len(self.client.get("/api/favorites", headers=first).json()["favorites"]), 1)
        self.assertEqual(self.client.get("/api/history", headers=second).json()["history"], [])
        self.client.delete("/api/favorites", params={"place_key": "fixture"}, headers=first)
        self.assertEqual(self.client.get("/api/favorites", headers=first).json()["favorites"], [])

    def test_health_schema_validation_and_route_contract(self):
        self.assertTrue(self.client.get("/api/health").json()["mongodb"])
        self.assertIn("japanese", self.client.get("/api/cuisines").json()["cuisines"])
        response = self.client.post("/api/search", json=dict(self.search_payload(), location="", locations=[]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.ai_calls, [])
        response = self.client.post("/api/route", json={"origin_lat": 1.3, "origin_lng": 103.8,
              "dest_lat": 1.31, "dest_lng": 103.81})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "walk")

    def test_database_errors_are_unavailable_without_fallback_or_uri_leak(self):
        from pymongo.errors import ServerSelectionTimeoutError
        self.conn._client.admin.command = Mock(side_effect=ServerSelectionTimeoutError("private URI"))
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private URI", response.text)

    def test_production_composition_uses_oop_services_without_real_network(self):
        from unittest.mock import patch
        from BIS.web_dependencies import build_runtime
        with patch.dict(os.environ, {"BITEFINDER_STORAGE": "mongo"}), \
                patch("dotenv.load_dotenv", return_value=False), \
                patch("BIS.classes.mongo_connection.MongoConnection", return_value=self.conn):
            runtime = build_runtime()
            self.assertTrue(runtime.io.health()["mongodb"])
            self.assertIsInstance(runtime.io, WebIOManager)
            self.assertIsInstance(runtime.io._application, BISApplicationService)

    def test_history_identity_and_ai_deadline_are_request_local(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        with patch("dotenv.load_dotenv", return_value=False):
            from BRNS import ai_manager
        barrier = threading.Barrier(2)
        def task(user_id, duration):
            with self.scope.for_user(user_id), ai_manager._recommendation_deadline(duration):
                own_deadline = ai_manager._ACTIVE_CHAIN_DEADLINE.get()
                barrier.wait(timeout=3)
                self.assertEqual(self.scope.get(), user_id)
                self.assertEqual(ai_manager._ACTIVE_CHAIN_DEADLINE.get(), own_deadline)
                request = self.search_payload()
                request["origin"] = {"latitude": 1.35, "longitude": 103.9, "query": user_id}
                self.history.save_search_results(request, {"matches": [], "alternatives": []}, "fixture")
            self.assertIsNone(self.scope.get())
            self.assertIsNone(ai_manager._ACTIVE_CHAIN_DEADLINE.get())
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair: task(*pair), [("first", 10), ("second", 30)]))
        self.assertEqual(len(self.history.load_user_history("first")), 1)
        self.assertEqual(len(self.history.load_user_history("second")), 1)

    def test_session_expiry_is_enforced_without_waiting_for_ttl_cleanup(self):
        import time
        now = [time.time()]
        sessions = MongoSessionStore(self.conn, clock=lambda: now[0], ttl=2)
        token = sessions.create("fixture")
        self.assertEqual(sessions.resolve(token), "fixture")
        now[0] += 3
        self.assertIsNone(sessions.resolve(token))
        self.assertNotIn(token, str(list(self.conn.db.sessions.find({}))))

    def test_smtp_bypass_claims_legacy_cli_user_and_syncs_with_users_json(self):
        import json
        import tempfile
        from BIS.classes.cli_user_file_sync import CliUserFileSync
        from BIS.sources.profile_schema import empty_preferences

        with tempfile.TemporaryDirectory() as tmp:
            users_path = Path(tmp) / "users.json"
            cli_record = {
                "userID": "legacy-cli-1",
                "email": "test_cli@example.com",
                "email_verified": False,
                "username": "CLI Legacy",
                "preferences": dict(empty_preferences(), location=["Rivervale Plaza"]),
            }
            dup_record = dict(cli_record, userID="legacy-cli-dup", username="Duplicate Ignored")
            users_path.write_text(
                json.dumps({"legacy-cli-1": cli_record, "legacy-cli-dup": dup_record}),
                encoding="utf-8",
            )
            sync = CliUserFileSync(self.conn, users_path)
            sync.sync_from_file(force=True)

            data = DataManager(
                self.users, self.gateway, self.sessions, self.favorites,
                MongoCredentialStore(self.conn), self.proposals, user_sync=sync,
            )
            cfg = dict(self.config, smtp_bypass=True)
            verif = EmailVerificationService(data, VerificationChallengeManager(),
                                             SimpleNamespace(send_verification_email=lambda *a: None))
            auth = WebAuthService(data, verif, PasswordHasher(), cfg)
            app_svc = BISApplicationService(
                data, self.ai, LogicManager(), SimpleNamespace(search=lambda *_: {}),
                SimpleNamespace(route_to=lambda *_: {}), self.history, self.scope, cfg, lambda: None,
            )
            io = WebIOManager(data, auth, app_svc, FavoriteService(data), self.conn.ready)
            with TestClient(create_app(lambda: WebRuntime(io, self.conn))) as client:
                login = client.post("/api/auth/login", json={"email": "test_cli@example.com", "password": "password123"})
                self.assertEqual(login.status_code, 200, login.text)
                body = login.json()
                self.assertFalse(body["otp_required"])
                self.assertTrue(body["user"]["email_verified"])
                token = body["token"]

                bad = client.post("/api/auth/login", json={"email": "test_cli@example.com", "password": "wrong"})
                self.assertEqual(bad.status_code, 401)

                prof = client.post(
                    "/api/profile",
                    json={"location": ["828761"], "budget_per_person": 25},
                    headers={"Authorization": "Bearer " + token},
                )
                self.assertEqual(prof.status_code, 200, prof.text)
                self.assertEqual(prof.json()["user"]["location"], ["singapore 828761"])

                saved_json = json.loads(users_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    saved_json["legacy-cli-1"]["preferences"]["location"],
                    ["singapore 828761"],
                )
                self.assertTrue(saved_json["legacy-cli-1"]["email_verified"])

    def test_concurrent_searches_do_not_block_with_in_progress_error(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        barrier = threading.Barrier(2, timeout=3)
        headers, _ = self.account("concurrent@example.com")
        original_brns = self.application._brns

        def slow_search(payload):
            barrier.wait(timeout=3)
            return original_brns.search(payload)

        self.application._brns = SimpleNamespace(search=slow_search)
        payload = self.search_payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self.client.post, "/api/search", json=payload, headers=headers)
            f2 = pool.submit(self.client.post, "/api/search", json=payload, headers=headers)
            r1, r2 = f1.result(timeout=5), f2.result(timeout=5)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)

    def test_halal_coordinator_batches_when_verifier_supports_verify_batch(self):
        from BRNS.classes.halal_verification_coordinator import HalalVerificationCoordinator
        from shared import debug_log

        batch_calls = []

        class BatchVerifier:
            def database_missing(self):
                return False

            def verify_batch(self, items):
                batch_calls.append(len(items))
                return [
                    {
                        "halal_certification": "official",
                        "muis_check": {"status": "verified", "certificate_number": "C1"},
                        "cuisines": ["malay"],
                    }
                    for _ in items
                ]

        io_stub = SimpleNamespace(
            show_halal_verification_start=lambda *_a: None,
            show_halal_verification_summary=lambda *_a: None,
        )
        logic_stub = SimpleNamespace(recommendation_order=lambda cands, _recs: list(range(len(cands))))
        coord = HalalVerificationCoordinator(logic_stub, io_stub, BatchVerifier(), debug_log)
        checked, summary = coord.verify(
            [{"name": "A", "dietary_requirements": []}, {"name": "B", "dietary_requirements": []}],
            {"dietary_requirements": ["halal"]},
            {"ordered_ids": [0, 1]},
        )
        self.assertEqual(batch_calls, [2])
        self.assertEqual(summary["verified"], 2)
        self.assertEqual([c["halal_certification"] for c in checked], ["official", "official"])

    def test_chatbot_parses_search_followup_clarification_and_save_profile(self):
        # 1. Guest without location triggers clarification
        clarify = self.client.post("/api/chat", json={
            "message": "Find me ramen under $15",
            "current_filters": {},
            "history": [],
        })
        self.assertEqual(clarify.status_code, 200, clarify.text)
        self.assertEqual(clarify.json()["action"], "clarify")
        self.assertEqual(clarify.json()["filters"]["budget_per_person"], 15.0)
        self.assertIn("ramen", clarify.json()["filters"]["liked_cuisines"])

        # 2. Meet-in-the-middle + dietary + rating + walk time confirms before searching
        chat1 = self.client.post("/api/chat", json={
            "message": "Halal Japanese between Tampines and Jurong East under $25, walk 15 mins, at least 4.5 stars",
            "current_filters": {},
            "history": [],
        })
        self.assertEqual(chat1.status_code, 200, chat1.text)
        body1 = chat1.json()
        self.assertEqual(body1["action"], "confirm")
        self.assertEqual(body1["awaiting_field"], "confirm")
        f1 = body1["filters"]
        self.assertEqual(f1["locations"], ["Tampines", "Jurong East"])
        self.assertEqual(f1["mode"], "walk")
        self.assertEqual(f1["max_travel_minutes"], 15.0)
        self.assertEqual(f1["budget_per_person"], 25.0)
        self.assertIn("halal", f1["dietary_requirements"])
        self.assertIn("japanese", f1["liked_cuisines"])
        self.assertTrue(any("4.5" in p for p in f1["other_preferences"]))

        # 3. Incremental follow-up preserves existing locations/dietary and re-confirms
        chat2 = self.client.post("/api/chat", json={
            "message": "Make it under $15 by transit",
            "current_filters": f1,
            "awaiting_field": "confirm",
            "history": [{"role": "user", "text": "Halal Japanese..."}],
        })
        self.assertEqual(chat2.status_code, 200, chat2.text)
        self.assertEqual(chat2.json()["action"], "confirm")
        f2 = chat2.json()["filters"]
        self.assertEqual(f2["locations"], ["Tampines", "Jurong East"])
        self.assertIn("halal", f2["dietary_requirements"])
        self.assertIn("japanese", f2["liked_cuisines"])
        self.assertEqual(f2["budget_per_person"], 15.0)
        self.assertEqual(f2["mode"], "transit")

        # Explicit user confirmation proceeds to search
        go = self.client.post("/api/chat", json={
            "message": "Yes, search now",
            "current_filters": f2,
            "awaiting_field": "confirm",
        })
        self.assertEqual(go.status_code, 200, go.text)
        self.assertEqual(go.json()["action"], "search")

        # 4. Save profile requires sign-in for guests, and persists when signed in
        guest_save = self.client.post("/api/chat", json={
            "message": "Save these preferences to my profile",
            "current_filters": f2,
        })
        self.assertEqual(guest_save.status_code, 200)
        self.assertFalse(guest_save.json()["saved_to_profile"])
        self.assertEqual(guest_save.json()["action"], "clarify")

        headers, _ = self.account("chatbot@example.com")
        authed_save = self.client.post("/api/chat", json={
            "message": "Save these preferences to my profile",
            "current_filters": f2,
        }, headers=headers)
        self.assertEqual(authed_save.status_code, 200, authed_save.text)
        self.assertTrue(authed_save.json()["saved_to_profile"])
        me = self.client.get("/api/auth/me", headers=headers).json()["user"]
        self.assertEqual(me["location"], ["tampines", "jurong east"])
        self.assertEqual(me["budget_per_person"], 15.0)
        self.assertIn("halal", me["dietary_requirements"])

    def test_chatbot_uses_ai_response_and_falls_back_cleanly(self):
        calls = []

        def fake_chat_turn(message, current_filters, history, saved_profile, config):
            calls.append((message, current_filters))
            return {
                "intent": "search",
                "reply": "Searching Marina Bay for Korean BBQ under $35.",
                "updates": {
                    "locations": ["Marina Bay"],
                    "locations_action": "replace",
                    "liked_cuisines": ["korean"],
                    "liked_action": "replace",
                    "budget_per_person": 35,
                },
                "quick_replies": ["Under $25", "Walk 15 mins"],
            }

        self.application._chatbot._ai = SimpleNamespace(chat_turn=fake_chat_turn)
        res = self.client.post("/api/chat", json={
            "message": "I want Korean BBQ around Marina Bay budget 35",
            "current_filters": {},
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(calls), 1)
        # Guest without travel limit must be asked for travel time/distance
        self.assertEqual(res.json()["action"], "clarify")
        self.assertEqual(res.json()["awaiting_field"], "travel")
        self.assertEqual(res.json()["filters"]["locations"], ["Marina Bay"])
        self.assertEqual(res.json()["filters"]["liked_cuisines"], ["korean"])
        self.assertEqual(res.json()["filters"]["budget_per_person"], 35.0)

        # Fallback to deterministic parsing if AI raises
        def broken_chat_turn(*_args):
            raise RuntimeError("AI timeout")

        self.application._chatbot._ai = SimpleNamespace(chat_turn=broken_chat_turn)
        fallback = self.client.post("/api/chat", json={
            "message": "Vegetarian near 828761 under $18 walk 15 mins",
            "current_filters": {},
        })
        self.assertEqual(fallback.status_code, 200, fallback.text)
        self.assertEqual(fallback.json()["action"], "confirm")
        self.assertEqual(fallback.json()["filters"]["locations"], ["Singapore 828761"])
        self.assertIn("vegetarian", fallback.json()["filters"]["dietary_requirements"])
        self.assertEqual(fallback.json()["filters"]["budget_per_person"], 18.0)
        self.assertEqual(fallback.json()["filters"]["max_travel_minutes"], 15.0)

    def test_guest_chatbot_questions_location_budget_and_travel_sequentially(self):
        # Step 1: Guest asks broadly -> chatbot questions location
        s1 = self.client.post("/api/chat", json={
            "message": "Find me something good to eat",
            "current_filters": {},
            "history": [],
        })
        self.assertEqual(s1.status_code, 200, s1.text)
        b1 = s1.json()
        self.assertEqual(b1["action"], "clarify")
        self.assertEqual(b1["awaiting_field"], "location")

        # Step 2: Bare location reply -> chatbot questions budget
        s2 = self.client.post("/api/chat", json={
            "message": "Bugis",
            "current_filters": b1["filters"],
            "awaiting_field": b1["awaiting_field"],
        })
        self.assertEqual(s2.status_code, 200, s2.text)
        b2 = s2.json()
        self.assertEqual(b2["action"], "clarify")
        self.assertEqual(b2["awaiting_field"], "budget_per_person")
        self.assertEqual(b2["filters"]["locations"], ["Bugis"])

        # Step 3: Bare budget reply -> chatbot questions travel
        s3 = self.client.post("/api/chat", json={
            "message": "$22",
            "current_filters": b2["filters"],
            "awaiting_field": b2["awaiting_field"],
        })
        self.assertEqual(s3.status_code, 200, s3.text)
        b3 = s3.json()
        self.assertEqual(b3["action"], "clarify")
        self.assertEqual(b3["awaiting_field"], "travel")
        self.assertEqual(b3["filters"]["budget_per_person"], 22.0)

        # Step 4: Travel reply completes required fields -> asks user to confirm before searching
        s4 = self.client.post("/api/chat", json={
            "message": "15 mins walk",
            "current_filters": b3["filters"],
            "awaiting_field": b3["awaiting_field"],
        })
        self.assertEqual(s4.status_code, 200, s4.text)
        b4 = s4.json()
        self.assertEqual(b4["action"], "confirm")
        self.assertEqual(b4["awaiting_field"], "confirm")
        self.assertEqual(b4["filters"]["locations"], ["Bugis"])
        self.assertEqual(b4["filters"]["budget_per_person"], 22.0)
        self.assertEqual(b4["filters"]["max_travel_minutes"], 15.0)
        self.assertEqual(b4["filters"]["mode"], "walk")

        # Step 5: User asks to tweak budget before searching, then confirms
        edit_req = self.client.post("/api/chat", json={
            "message": "Change budget",
            "current_filters": b4["filters"],
            "awaiting_field": b4["awaiting_field"],
        })
        self.assertEqual(edit_req.status_code, 200)
        self.assertEqual(edit_req.json()["action"], "clarify")
        self.assertEqual(edit_req.json()["awaiting_field"], "budget_per_person")

        edit_val = self.client.post("/api/chat", json={
            "message": "$18",
            "current_filters": edit_req.json()["filters"],
            "awaiting_field": edit_req.json()["awaiting_field"],
        })
        self.assertEqual(edit_val.status_code, 200)
        b5 = edit_val.json()
        self.assertEqual(b5["action"], "confirm")
        self.assertEqual(b5["filters"]["budget_per_person"], 18.0)

        confirm = self.client.post("/api/chat", json={
            "message": "Yes, search now",
            "current_filters": b5["filters"],
            "awaiting_field": b5["awaiting_field"],
        })
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["action"], "search")

    def test_new_user_profile_onboarding_via_chatbot(self):
        headers, _ = self.account("onboard@example.com")

        # Start onboarding wizard
        start = self.client.post("/api/chat", json={
            "message": "__start_onboarding__",
            "current_filters": {},
            "onboarding": True,
        }, headers=headers)
        self.assertEqual(start.status_code, 200, start.text)
        st = start.json()
        self.assertEqual(st["action"], "onboarding")
        self.assertEqual(st["awaiting_field"], "location")
        self.assertEqual(st["onboarding_step"], 1)
        self.assertEqual(st["onboarding_total"], 7)

        steps = [
            ("Punggol", "budget_per_person"),
            ("$25", "travel"),
            ("20 mins", "dietary_requirements"),
            ("Halal", "liked_cuisines"),
            ("Japanese, Korean", "disliked_cuisines"),
            ("Thai", "other_preferences"),
        ]
        state = st
        for msg, expected_next in steps:
            res = self.client.post("/api/chat", json={
                "message": msg,
                "current_filters": state["filters"],
                "onboarding": True,
                "awaiting_field": state["awaiting_field"],
            }, headers=headers)
            self.assertEqual(res.status_code, 200, res.text)
            state = res.json()
            self.assertEqual(state["action"], "onboarding")
            self.assertEqual(state["awaiting_field"], expected_next, msg)

        # Final preference step saves profile and asks user to confirm before searching
        done = self.client.post("/api/chat", json={
            "message": "At least 4.3 stars",
            "current_filters": state["filters"],
            "onboarding": True,
            "awaiting_field": state["awaiting_field"],
        }, headers=headers)
        self.assertEqual(done.status_code, 200, done.text)
        d = done.json()
        self.assertEqual(d["action"], "confirm")
        self.assertEqual(d["awaiting_field"], "confirm")
        self.assertTrue(d["saved_to_profile"])

        # Following up with a regular query also confirms first instead of auto-searching
        followup = self.client.post("/api/chat", json={
            "message": "Korean BBQ under $30",
            "current_filters": d["filters"],
            "awaiting_field": d["awaiting_field"],
        }, headers=headers)
        self.assertEqual(followup.status_code, 200, followup.text)
        self.assertEqual(followup.json()["action"], "confirm")

        # Confirming proceeds with search
        confirm = self.client.post("/api/chat", json={
            "message": "Yes, search now",
            "current_filters": followup.json()["filters"],
            "awaiting_field": "confirm",
        }, headers=headers)
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["action"], "search")

        # Verify profile was persisted incrementally to user store
        me = self.client.get("/api/auth/me", headers=headers).json()["user"]
        self.assertEqual(me["location"], ["punggol"])
        self.assertEqual(me["budget_per_person"], 25.0)
        self.assertEqual(me["max_travel_time_minutes"], 20.0)
        self.assertIn("halal", me["dietary_requirements"])
        self.assertIn("japanese", me["liked_cuisines"])
        self.assertIn("korean", me["liked_cuisines"])
        self.assertIn("thai", me["disliked_cuisines"])
        self.assertTrue(any("4.3" in p for p in me["other_preferences"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
