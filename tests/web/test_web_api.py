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
for key in (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "NVIDIA_API_KEY",
    "SILICON_FLOW_API_KEY",
    "SILICONFLOW_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEYS",
    "OPENROUTER_API_KEYS_FILE",
    "GOOGLE_MAPS_API_KEY",
    "GOOGLE_MAPS_JS_API_KEY",
):
    os.environ.pop(key, None)

import mongomock  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from BIS.classes.data.stores.mongo.mongo_connection import MongoConnection  # noqa: E402
from BIS.classes.data.stores.mongo.mongo_user_store import MongoUserStore  # noqa: E402
from BIS.classes.data.stores.mongo.mongo_session_store import MongoSessionStore  # noqa: E402
from BIS.classes.data.stores.mongo.mongo_favorite_store import (  # noqa: E402
    MongoFavoriteStore,
)
from BIS.classes.data.stores.mongo.mongo_credential_store import (  # noqa: E402
    MongoCredentialStore,
)
from BIS.classes.data.stores.mongo.mongo_search_proposal_store import (  # noqa: E402
    MongoSearchProposalStore,
)
from BIS.classes.data.data_manager import DataManager  # noqa: E402
from BIS.classes.logic.logic_manager import LogicManager  # noqa: E402
from BIS.classes.logic.security.password_hasher import PasswordHasher  # noqa: E402
from BIS.classes.services.web.web_auth_service import WebAuthService  # noqa: E402
from BIS.classes.services.web.favorite_service import FavoriteService  # noqa: E402
from BIS.classes.services.web.bis_application_service import (  # noqa: E402
    BISApplicationService,
)
from BIS.classes.io.web.web_io_manager import WebIOManager  # noqa: E402
from BIS.classes.services.web.web_runtime import WebRuntime  # noqa: E402
from BIS.support.email_verification.classes.service.email_verification_service import (  # noqa: E402, E501
    EmailVerificationService,
)
from BIS.support.email_verification.classes.challenge.verification_challenge_manager import (  # noqa: E402, E501
    VerificationChallengeManager,
)
from BRNS.classes.data.stores.mongo.mongo_recommendation_store import (  # noqa: E402
    MongoRecommendationStore,
)
from BRNS.classes.data.helpers.search_history_scope import SearchHistoryScope  # noqa: E402
from BRNS.classes.data.data_manager import DataManager as RecommendationData  # noqa: E402
from http_gateway.main import create_app  # noqa: E402


class WebIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.mongo_client = mongomock.MongoClient()
        self.conn = MongoConnection(
            client=self.mongo_client, database="isolated_tests"
        )
        self.users = MongoUserStore(self.conn)
        self.sessions = MongoSessionStore(self.conn)
        self.favorites = MongoFavoriteStore(self.conn)
        self.proposals = MongoSearchProposalStore(self.conn)
        for store in (
            self.users,
            self.sessions,
            self.favorites,
            self.proposals,
        ):
            store.ensure_indexes()
        self.gateway = SimpleNamespace(
            resolve=lambda query, _key: dict(
                query=query, label=query, latitude=1.35, longitude=103.94
            )
        )
        self.data = DataManager(
            self.users,
            self.sessions,
            self.favorites,
            MongoCredentialStore(self.conn),
            self.proposals,
        )
        self.sent = []
        delivery = SimpleNamespace(
            send_verification_email=lambda email, code, _config: (
                self.sent.append((email, code))
            )
        )
        self.verification = EmailVerificationService(
            self.data, VerificationChallengeManager(), delivery
        )
        self.config = {
            "verification_attempt_reset_seconds": 600,
            "google_maps_api_key": "",
        }
        self.auth = WebAuthService(
            self.data, self.verification, PasswordHasher(), self.config
        )
        self.scope = SearchHistoryScope()
        self.history = RecommendationData(
            MongoRecommendationStore(self.conn, self.scope)
        )
        self.ranking_calls = []
        self.ai_calls = []

        def interpret(request, wishes, config):
            self.ai_calls.append(request)
            return request

        self.ai = SimpleNamespace(interpret_search_request=interpret)

        def search(
            payload,
            previous_restaurants=(),
            user_id=None,
            max_matches=None,
            max_alternatives=None,
        ):
            import json

            request = json.loads(payload)
            self.ranking_calls.append(request)
            results = {"matches": [], "alternatives": [], "hidden": 0}
            with self.scope.for_user(user_id):
                self.history.save_search_results(
                    request, results, "live-google"
                )
            return results

        self.application = BISApplicationService(
            self.data,
            self.ai,
            LogicManager(),
            self._make_brns_gateway(search),
            self.config,
            lambda: "fixture/provider",
            location_gateway=self.gateway,
        )
        self.io = WebIOManager(
            self.auth,
            self.application,
            FavoriteService(self.data),
            self.conn.ready,
        )
        self.client = TestClient(
            create_app(lambda: WebRuntime(self.io, self.conn))
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _make_brns_gateway(self, search_fn, route_fn=None, photo_fn=None):
        def save_history_summary(user_id, req, res, source="live-google"):
            with self.scope.for_user(user_id):
                return self.history.save_search_results(req, res, source)

        return SimpleNamespace(
            search=search_fn,
            route_to=route_fn
            or (
                lambda r, q: {
                    "name": r["name"],
                    "mode": q["mode"],
                    "route": None,
                    "link": "https://www.google.com/maps",
                }
            ),
            place_photo=photo_fn or (lambda _place_id: None),
            load_history=lambda uid: self.history.load_user_history(uid),
            save_history_summary=save_history_summary,
            clear_history=lambda uid: self.history.clear_user_history(uid),
            active_model=lambda: "fixture/provider",
            last_used_model=lambda: "fixture/provider",
        )

    def account(self, email="user@example.com"):
        response = self.client.post(
            "/api/auth/register",
            json={
                "username": "Tester",
                "email": email,
                "password": "test.password",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["otp_required"])
        response = self.client.post(
            "/api/auth/verify-otp",
            json={"email": email, "code": self.sent[-1][1]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "Authorization": "Bearer " + response.json()["token"]
        }, response.json()["user"]

    @staticmethod
    def search_payload():
        return {
            "location": "Tampines",
            "mode": "walk",
            "max_travel_minutes": 20,
            "max_distance_km": None,
            "budget_per_person": 20,
            "cuisine": "japanese",
            "dietary_requirements": [],
            "disliked_cuisines": [],
            "other_preferences": [],
        }

    def test_auth_requires_real_challenge_even_for_example_domain(self):
        headers, user = self.account()
        self.assertTrue(user["email_verified"])
        self.assertNotIn("password_hash", str(user))
        self.assertNotIn("password_salt", str(user))
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).status_code, 200
        )
        self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).status_code, 401
        )

    def test_cli_account_is_not_claimed_before_email_proof(self):
        user = self.data.register_user("cli@example.com", "CLI")
        response = self.client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": "new.password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["otp_required"])
        self.assertIsNone(self.data.get_credentials(user["userID"]))
        response = self.client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "code": "wrong"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.data.get_credentials(user["userID"]))
        response = self.client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "code": self.sent[-1][1]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.data.get_credentials(user["userID"]))

    def test_wrong_password_resend_and_attempt_limits(self):
        headers, user = self.account()
        wrong = self.client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": "incorrect"},
        )
        self.assertEqual(wrong.status_code, 401)
        login = self.client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": "test.password"},
        )
        self.assertEqual(login.status_code, 200)
        resend = self.client.post(
            "/api/auth/resend-otp", json={"email": user["email"]}
        )
        self.assertEqual(resend.status_code, 400)
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/api/auth/verify-otp",
                    json={"email": user["email"], "code": "wrong"},
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/verify-otp",
                json={"email": user["email"], "code": self.sent[-1][1]},
            ).status_code,
            400,
        )

    def test_registration_and_legacy_enrollment_enforce_8_char_minimum(self):
        short_reg = self.client.post(
            "/api/auth/register",
            json={
                "username": "Short",
                "email": "short7@example.com",
                "password": "seven77",
            },
        )
        self.assertEqual(short_reg.status_code, 422)
        legacy = self.data.register_user("legacy7@example.com", "Legacy")
        short_claim = self.client.post(
            "/api/auth/login",
            json={"email": legacy["email"], "password": "seven77"},
        )
        self.assertEqual(short_claim.status_code, 400)
        self.assertIn("8", short_claim.json()["detail"])
        ok_reg = self.client.post(
            "/api/auth/register",
            json={
                "username": "Eight",
                "email": "eight88@example.com",
                "password": "eight888",
            },
        )
        self.assertEqual(ok_reg.status_code, 200, ok_reg.text)

    def test_profiles_share_cli_data_without_json_sync(self):
        headers, user = self.account()
        payload = dict(user, username="Updated")
        payload.pop("email_verified")
        payload.update(
            location=["Tampines"],
            max_distance_km=2,
            max_travel_time_minutes=40,
            budget_per_person=20,
        )
        response = self.client.post(
            "/api/profile", json=payload, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        other_cli_store = MongoUserStore(self.conn)
        self.assertEqual(
            other_cli_store.get_user(user["user_id"])["username"], "Updated"
        )
        other_cli_store.save(
            dict(
                other_cli_store.get_user(user["user_id"]),
                username="CLI updated",
            )
        )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json()["user"][
                "username"
            ],
            "CLI updated",
        )
        payload["user_id"] = "another-user"
        self.assertEqual(
            self.client.post(
                "/api/profile", json=payload, headers=headers
            ).status_code,
            401,
        )

    def test_invalid_profile_is_rejected_before_any_record_is_saved(self):
        headers, user = self.account()
        before = self.data.get_user(user["user_id"])
        payload = dict(user, username="!", budget_per_person=25)
        payload.pop("email_verified")
        response = self.client.post(
            "/api/profile", json=payload, headers=headers
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.data.get_user(user["user_id"]), before)

    def test_confirmation_is_one_use_and_only_then_calls_brns(self):
        headers, _ = self.account()
        payload = self.search_payload()
        first = self.client.post(
            "/api/search",
            json=dict(payload, confirm_only=True),
            headers=headers,
        )
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
        self.assertEqual(
            self.client.post(
                "/api/search", json=payload, headers=headers
            ).status_code,
            400,
        )
        self.assertEqual(
            len(
                self.client.get("/api/history", headers=headers).json()[
                    "history"
                ]
            ),
            1,
        )
        self.client.delete("/api/history", headers=headers)
        self.assertEqual(
            self.client.get("/api/history", headers=headers).json()["history"],
            [],
        )

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
        token = self.client.post(
            "/api/search", json=dict(payload, confirm_only=True), headers=first
        ).json()["confirmation_token"]
        payload["confirmation_token"] = token
        self.assertEqual(
            self.client.post(
                "/api/search", json=payload, headers=second
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/search", json=payload, headers=first
            ).status_code,
            200,
        )
        restaurant = {
            "name": "Cafe",
            "address": "1 Road",
            "google_place_id": "fixture",
        }
        self.assertEqual(
            self.client.post(
                "/api/favorites",
                json={"restaurant": restaurant},
                headers=first,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/favorites", headers=second).json()[
                "favorites"
            ],
            [],
        )
        self.assertEqual(
            len(
                self.client.get("/api/favorites", headers=first).json()[
                    "favorites"
                ]
            ),
            1,
        )
        self.assertEqual(
            self.client.get("/api/history", headers=second).json()["history"],
            [],
        )
        self.client.delete(
            "/api/favorites", params={"place_key": "fixture"}, headers=first
        )
        self.assertEqual(
            self.client.get("/api/favorites", headers=first).json()[
                "favorites"
            ],
            [],
        )

        # Clear all saved favorites for `first` without affecting `second`.
        second_place = dict(
            restaurant, google_place_id="second-user-only", name="Keep Cafe"
        )
        first_two = dict(restaurant, google_place_id="first-2", name="Cafe 2")
        self.assertEqual(
            self.client.post(
                "/api/favorites",
                json={"restaurant": restaurant},
                headers=first,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/favorites",
                json={"restaurant": first_two},
                headers=first,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/favorites",
                json={"restaurant": second_place},
                headers=second,
            ).status_code,
            200,
        )
        clear_res = self.client.delete("/api/favorites", headers=first)
        self.assertEqual(clear_res.status_code, 200, clear_res.text)
        self.assertEqual(
            self.client.get("/api/favorites", headers=first).json()[
                "favorites"
            ],
            [],
        )
        self.assertEqual(
            len(
                self.client.get("/api/favorites", headers=second).json()[
                    "favorites"
                ]
            ),
            1,
        )

    def test_health_schema_validation_and_route_contract(self):
        self.assertTrue(self.client.get("/api/health").json()["mongodb"])
        self.assertIn(
            "japanese", self.client.get("/api/cuisines").json()["cuisines"]
        )
        response = self.client.post(
            "/api/search",
            json=dict(self.search_payload(), location="", locations=[]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.ai_calls, [])
        response = self.client.post(
            "/api/route",
            json={
                "origin_lat": 1.3,
                "origin_lng": 103.8,
                "dest_lat": 1.31,
                "dest_lng": 103.81,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "walk")

    def test_database_errors_are_unavailable_without_fallback_or_uri_leak(
        self,
    ):
        from pymongo.errors import ServerSelectionTimeoutError

        self.mongo_client.admin.command = Mock(
            side_effect=ServerSelectionTimeoutError("private URI")
        )
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private URI", response.text)

    def test_production_composition_uses_oop_services_without_real_network(
        self,
    ):
        from unittest.mock import patch
        from http_gateway.dependencies import build_runtime

        with (
            patch.dict(os.environ, {"BITEFINDER_STORAGE": "mongo"}),
            patch("dotenv.load_dotenv", return_value=False),
            patch(
                (
                    "BIS.classes.data.stores.mongo.mongo_connection.MongoConne"
                    "ction"
                ),
                return_value=self.conn,
            ),
        ):
            runtime = build_runtime()
            self.assertTrue(runtime.io.health()["mongodb"])
            self.assertIsInstance(runtime.io, WebIOManager)
            self.assertIsInstance(
                runtime.io._application, BISApplicationService
            )

    def test_history_identity_and_ai_deadline_are_request_local(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch

        with patch("dotenv.load_dotenv", return_value=False):
            from BRNS import ai_manager
        barrier = threading.Barrier(2)

        def task(user_id, duration):
            with (
                self.scope.for_user(user_id),
                ai_manager._recommendation_deadline(duration),
            ):
                own_deadline = ai_manager._ACTIVE_CHAIN_DEADLINE.get()
                barrier.wait(timeout=3)
                self.assertEqual(self.scope.get(), user_id)
                self.assertEqual(
                    ai_manager._ACTIVE_CHAIN_DEADLINE.get(), own_deadline
                )
                request = self.search_payload()
                request["origin"] = {
                    "latitude": 1.35,
                    "longitude": 103.9,
                    "query": user_id,
                }
                self.history.save_search_results(
                    request, {"matches": [], "alternatives": []}, "fixture"
                )
            self.assertIsNone(self.scope.get())
            self.assertIsNone(ai_manager._ACTIVE_CHAIN_DEADLINE.get())

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(
                pool.map(
                    lambda pair: task(*pair), [("first", 10), ("second", 30)]
                )
            )
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
        self.assertNotIn(
            token,
            str(list(self.conn.execute(lambda db: db.sessions.find({})))),
        )

    def test_smtp_bypass_claims_legacy_cli_user_and_syncs_with_users_json(
        self,
    ):
        import json
        import tempfile
        from BIS.classes.data.sync.cli_user_file_sync import CliUserFileSync
        from BIS.sources.profile_schema import empty_preferences

        with tempfile.TemporaryDirectory() as tmp:
            users_path = Path(tmp) / "users.json"
            cli_record = {
                "userID": "legacy-cli-1",
                "email": "test_cli@example.com",
                "email_verified": False,
                "username": "CLI Legacy",
                "preferences": dict(
                    empty_preferences(), location=["Rivervale Plaza"]
                ),
            }
            dup_record = dict(
                cli_record,
                userID="legacy-cli-dup",
                username="Duplicate Ignored",
            )
            users_path.write_text(
                json.dumps(
                    {"legacy-cli-1": cli_record, "legacy-cli-dup": dup_record}
                ),
                encoding="utf-8",
            )
            sync = CliUserFileSync(self.conn, users_path)
            sync.sync_from_file(force=True)

            data = DataManager(
                self.users,
                self.sessions,
                self.favorites,
                MongoCredentialStore(self.conn),
                self.proposals,
                user_sync=sync,
            )
            cfg = dict(self.config, smtp_bypass=True)
            verif = EmailVerificationService(
                data,
                VerificationChallengeManager(),
                SimpleNamespace(send_verification_email=lambda *a: None),
            )
            auth = WebAuthService(data, verif, PasswordHasher(), cfg)
            app_svc = BISApplicationService(
                data,
                self.ai,
                LogicManager(),
                self._make_brns_gateway(lambda *_, **_kw: {}, lambda *_: {}),
                cfg,
                lambda: None,
                location_gateway=self.gateway,
            )
            io = WebIOManager(
                auth, app_svc, FavoriteService(data), self.conn.ready
            )
            with TestClient(
                create_app(lambda: WebRuntime(io, self.conn))
            ) as client:
                login = client.post(
                    "/api/auth/login",
                    json={
                        "email": "test_cli@example.com",
                        "password": "password123",
                    },
                )
                self.assertEqual(login.status_code, 200, login.text)
                body = login.json()
                self.assertFalse(body["otp_required"])
                self.assertTrue(body["user"]["email_verified"])
                token = body["token"]

                bad = client.post(
                    "/api/auth/login",
                    json={
                        "email": "test_cli@example.com",
                        "password": "wrong",
                    },
                )
                self.assertEqual(bad.status_code, 401)

                prof = client.post(
                    "/api/profile",
                    json={"location": ["828761"], "budget_per_person": 25},
                    headers={"Authorization": "Bearer " + token},
                )
                self.assertEqual(prof.status_code, 200, prof.text)
                self.assertEqual(
                    prof.json()["user"]["location"], ["singapore 828761"]
                )

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

        def slow_search(payload, *args, **kwargs):
            barrier.wait(timeout=3)
            return original_brns.search(payload, *args, **kwargs)

        self.application._brns = SimpleNamespace(
            search=slow_search,
            last_used_model=original_brns.last_used_model,
            active_model=original_brns.active_model,
        )
        payload = self.search_payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(
                self.client.post, "/api/search", json=payload, headers=headers
            )
            f2 = pool.submit(
                self.client.post, "/api/search", json=payload, headers=headers
            )
            r1, r2 = f1.result(timeout=5), f2.result(timeout=5)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)

    def test_halal_coordinator_batches_when_verifier_supports_verify_batch(
        self,
    ):
        from BRNS.classes.services.workflows.halal_verification_coordinator import (  # noqa: E501
            HalalVerificationCoordinator,
        )
        from common import debug_log

        batch_calls = []

        class BatchVerifier:
            def database_missing(self):
                return False

            def verify_batch(self, items):
                batch_calls.append(len(items))
                return [
                    {
                        "halal_certification": "official",
                        "muis_check": {
                            "status": "verified",
                            "certificate_number": "C1",
                        },
                        "cuisines": ["malay"],
                    }
                    for _ in items
                ]

        io_stub = SimpleNamespace(
            show_halal_verification_start=lambda *_a: None,
            show_halal_verification_summary=lambda *_a: None,
        )
        from BRNS import logic_manager as recommendation_logic

        real_logic = recommendation_logic.manager()
        logic_stub = SimpleNamespace(
            recommendation_order=lambda cands, _recs: list(range(len(cands))),
            prepare_halal_candidate=real_logic.prepare_halal_candidate,
            apply_halal_evidence=real_logic.apply_halal_evidence,
        )
        coord = HalalVerificationCoordinator(
            logic_stub, io_stub, BatchVerifier(), debug_log
        )
        checked, summary = coord.verify(
            [
                {"name": "A", "dietary_requirements": []},
                {"name": "B", "dietary_requirements": []},
            ],
            {"dietary_requirements": ["halal"]},
            {"ordered_ids": [0, 1]},
        )
        self.assertEqual(batch_calls, [2])
        self.assertEqual(summary["verified"], 2)
        self.assertEqual(
            [c["halal_certification"] for c in checked],
            ["official", "official"],
        )

    def test_chatbot_parses_search_followup_clarification_and_save_profile(
        self,
    ):
        # 1. Guest without location triggers clarification
        clarify = self.client.post(
            "/api/chat",
            json={
                "message": "Find me ramen under $15",
                "current_filters": {},
                "history": [],
            },
        )
        self.assertEqual(clarify.status_code, 200, clarify.text)
        self.assertEqual(clarify.json()["action"], "clarify")
        self.assertEqual(clarify.json()["filters"]["budget_per_person"], 15.0)
        self.assertIn("ramen", clarify.json()["filters"]["liked_cuisines"])

        # 2. Meet-in-the-middle + dietary + rating + walk time confirms before
        # searching
        chat1 = self.client.post(
            "/api/chat",
            json={
                ("message"): (
                    "Halal Japanese between Tampines and Jurong East under "
                    "$25, walk 15 mins, at least 4.5 stars"
                ),
                "current_filters": {},
                "history": [],
            },
        )
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

        # 3. Incremental follow-up preserves existing locations/dietary and
        # re-confirms
        chat2 = self.client.post(
            "/api/chat",
            json={
                "message": "Make it under $15 by transit",
                "current_filters": f1,
                "awaiting_field": "confirm",
                "history": [{"role": "user", "text": "Halal Japanese..."}],
            },
        )
        self.assertEqual(chat2.status_code, 200, chat2.text)
        self.assertEqual(chat2.json()["action"], "confirm")
        f2 = chat2.json()["filters"]
        self.assertEqual(f2["locations"], ["Tampines", "Jurong East"])
        self.assertIn("halal", f2["dietary_requirements"])
        self.assertIn("japanese", f2["liked_cuisines"])
        self.assertEqual(f2["budget_per_person"], 15.0)
        self.assertEqual(f2["mode"], "transit")

        # Explicit user confirmation proceeds to search
        go = self.client.post(
            "/api/chat",
            json={
                "message": "Yes, search now",
                "current_filters": f2,
                "awaiting_field": "confirm",
            },
        )
        self.assertEqual(go.status_code, 200, go.text)
        self.assertEqual(go.json()["action"], "search")

        # 4. Save profile requires sign-in for guests, and persists when signed
        # in
        guest_save = self.client.post(
            "/api/chat",
            json={
                "message": "Save these preferences to my profile",
                "current_filters": f2,
            },
        )
        self.assertEqual(guest_save.status_code, 200)
        self.assertFalse(guest_save.json()["saved_to_profile"])
        self.assertEqual(guest_save.json()["action"], "clarify")

        headers, _ = self.account("chatbot@example.com")
        authed_save = self.client.post(
            "/api/chat",
            json={
                "message": "Save these preferences to my profile",
                "current_filters": f2,
            },
            headers=headers,
        )
        self.assertEqual(authed_save.status_code, 200, authed_save.text)
        self.assertTrue(authed_save.json()["saved_to_profile"])
        me = self.client.get("/api/auth/me", headers=headers).json()["user"]
        self.assertEqual(me["location"], ["tampines", "jurong east"])
        self.assertEqual(me["budget_per_person"], 15.0)
        self.assertIn("halal", me["dietary_requirements"])

    def test_chatbot_uses_ai_response_and_falls_back_cleanly(self):
        calls = []

        def fake_chat_turn(
            message, current_filters, history, saved_profile, config
        ):
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

        self.application._chatbot._ai = SimpleNamespace(
            chat_turn=fake_chat_turn
        )
        res = self.client.post(
            "/api/chat",
            json={
                "message": "I want Korean BBQ around Marina Bay budget 35",
                "current_filters": {},
            },
        )
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

        self.application._chatbot._ai = SimpleNamespace(
            chat_turn=broken_chat_turn
        )
        fallback = self.client.post(
            "/api/chat",
            json={
                "message": "Vegetarian near 828761 under $18 walk 15 mins",
                "current_filters": {},
            },
        )
        self.assertEqual(fallback.status_code, 200, fallback.text)
        self.assertEqual(fallback.json()["action"], "confirm")
        self.assertEqual(
            fallback.json()["filters"]["locations"], ["Singapore 828761"]
        )
        self.assertIn(
            "vegetarian", fallback.json()["filters"]["dietary_requirements"]
        )
        self.assertEqual(fallback.json()["filters"]["budget_per_person"], 18.0)
        self.assertEqual(
            fallback.json()["filters"]["max_travel_minutes"], 15.0
        )

    def test_guest_chatbot_questions_location_budget_and_travel_sequentially(
        self,
    ):
        # Step 1: Guest asks broadly -> chatbot questions location
        s1 = self.client.post(
            "/api/chat",
            json={
                "message": "Find me something good to eat",
                "current_filters": {},
                "history": [],
            },
        )
        self.assertEqual(s1.status_code, 200, s1.text)
        b1 = s1.json()
        self.assertEqual(b1["action"], "clarify")
        self.assertEqual(b1["awaiting_field"], "location")

        # Step 2: Bare location reply -> chatbot questions budget
        s2 = self.client.post(
            "/api/chat",
            json={
                "message": "Bugis",
                "current_filters": b1["filters"],
                "awaiting_field": b1["awaiting_field"],
            },
        )
        self.assertEqual(s2.status_code, 200, s2.text)
        b2 = s2.json()
        self.assertEqual(b2["action"], "clarify")
        self.assertEqual(b2["awaiting_field"], "budget_per_person")
        self.assertEqual(b2["filters"]["locations"], ["Bugis"])

        # Step 3: Bare budget reply -> chatbot questions travel
        s3 = self.client.post(
            "/api/chat",
            json={
                "message": "$22",
                "current_filters": b2["filters"],
                "awaiting_field": b2["awaiting_field"],
            },
        )
        self.assertEqual(s3.status_code, 200, s3.text)
        b3 = s3.json()
        self.assertEqual(b3["action"], "clarify")
        self.assertEqual(b3["awaiting_field"], "travel")
        self.assertEqual(b3["filters"]["budget_per_person"], 22.0)

        # Step 4: Travel reply completes required fields -> asks user to
        # confirm before searching
        s4 = self.client.post(
            "/api/chat",
            json={
                "message": "15 mins walk",
                "current_filters": b3["filters"],
                "awaiting_field": b3["awaiting_field"],
            },
        )
        self.assertEqual(s4.status_code, 200, s4.text)
        b4 = s4.json()
        self.assertEqual(b4["action"], "confirm")
        self.assertEqual(b4["awaiting_field"], "confirm")
        self.assertEqual(b4["filters"]["locations"], ["Bugis"])
        self.assertEqual(b4["filters"]["budget_per_person"], 22.0)
        self.assertEqual(b4["filters"]["max_travel_minutes"], 15.0)
        self.assertEqual(b4["filters"]["mode"], "walk")

        # Step 5: User asks to tweak budget before searching, then confirms
        edit_req = self.client.post(
            "/api/chat",
            json={
                "message": "Change budget",
                "current_filters": b4["filters"],
                "awaiting_field": b4["awaiting_field"],
            },
        )
        self.assertEqual(edit_req.status_code, 200)
        self.assertEqual(edit_req.json()["action"], "clarify")
        self.assertEqual(
            edit_req.json()["awaiting_field"], "budget_per_person"
        )

        edit_val = self.client.post(
            "/api/chat",
            json={
                "message": "$18",
                "current_filters": edit_req.json()["filters"],
                "awaiting_field": edit_req.json()["awaiting_field"],
            },
        )
        self.assertEqual(edit_val.status_code, 200)
        b5 = edit_val.json()
        self.assertEqual(b5["action"], "confirm")
        self.assertEqual(b5["filters"]["budget_per_person"], 18.0)

        confirm = self.client.post(
            "/api/chat",
            json={
                "message": "Yes, search now",
                "current_filters": b5["filters"],
                "awaiting_field": b5["awaiting_field"],
            },
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["action"], "search")

    def test_new_user_profile_onboarding_via_chatbot(self):
        headers, _ = self.account("onboard@example.com")

        # Start onboarding wizard
        start = self.client.post(
            "/api/chat",
            json={
                "message": "__start_onboarding__",
                "current_filters": {},
                "onboarding": True,
            },
            headers=headers,
        )
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
            res = self.client.post(
                "/api/chat",
                json={
                    "message": msg,
                    "current_filters": state["filters"],
                    "onboarding": True,
                    "awaiting_field": state["awaiting_field"],
                },
                headers=headers,
            )
            self.assertEqual(res.status_code, 200, res.text)
            state = res.json()
            self.assertEqual(state["action"], "onboarding")
            self.assertEqual(state["awaiting_field"], expected_next, msg)

        # Final preference step saves profile and asks user to confirm before
        # searching
        done = self.client.post(
            "/api/chat",
            json={
                "message": "At least 4.3 stars",
                "current_filters": state["filters"],
                "onboarding": True,
                "awaiting_field": state["awaiting_field"],
            },
            headers=headers,
        )
        self.assertEqual(done.status_code, 200, done.text)
        d = done.json()
        self.assertEqual(d["action"], "confirm")
        self.assertEqual(d["awaiting_field"], "confirm")
        self.assertTrue(d["saved_to_profile"])

        # Following up with a regular query also confirms first instead of
        # auto-searching
        followup = self.client.post(
            "/api/chat",
            json={
                "message": "Korean BBQ under $30",
                "current_filters": d["filters"],
                "awaiting_field": d["awaiting_field"],
            },
            headers=headers,
        )
        self.assertEqual(followup.status_code, 200, followup.text)
        self.assertEqual(followup.json()["action"], "confirm")

        # Confirming proceeds with search
        confirm = self.client.post(
            "/api/chat",
            json={
                "message": "Yes, search now",
                "current_filters": followup.json()["filters"],
                "awaiting_field": "confirm",
            },
            headers=headers,
        )
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

    def test_chatbot_negations_dietary_edit_and_custom_cuisines(self):
        base_filters = {
            "location": "Singapore 530967",
            "locations": ["Singapore 530967"],
            "mode": "walk",
            "max_travel_minutes": 10,
            "budget_per_person": 30,
            "dietary_requirements": [],
            "liked_cuisines": ["japanese"],
            "disliked_cuisines": [],
            "other_preferences": [],
        }

        # Bare "change dietary" when empty asks which dietary requirement to
        # apply
        r1 = self.client.post(
            "/api/chat",
            json={
                "message": "change dietary",
                "current_filters": base_filters,
            },
        ).json()
        self.assertEqual(r1["action"], "clarify")
        self.assertEqual(r1["awaiting_field"], "dietary_requirements")

        # User picks "i want halal" -> Halal added & confirm shown
        r2 = self.client.post(
            "/api/chat",
            json={
                "message": "i want halal",
                "current_filters": r1["filters"],
                "awaiting_field": r1["awaiting_field"],
            },
        ).json()
        self.assertEqual(r2["action"], "confirm")
        self.assertEqual(r2["filters"]["dietary_requirements"], ["halal"])

        # Asking to edit dietary while Halal is active surfaces "Remove halal"
        # quick reply
        r2_edit = self.client.post(
            "/api/chat",
            json={"message": "dietary", "current_filters": r2["filters"]},
        ).json()
        self.assertEqual(r2_edit["action"], "clarify")
        self.assertEqual(r2_edit["awaiting_field"], "dietary_requirements")
        self.assertIn("Remove halal", r2_edit["quick_replies"])

        # "i dont want halal" removes halal
        r3 = self.client.post(
            "/api/chat",
            json={
                "message": "i dont want halal",
                "current_filters": r2["filters"],
            },
        ).json()
        self.assertEqual(r3["action"], "confirm")
        self.assertEqual(r3["filters"]["dietary_requirements"], [])

        # Re-add halal, then "remove halal" also clears halal cleanly
        r3b = self.client.post(
            "/api/chat",
            json={"message": "halal please", "current_filters": r3["filters"]},
        ).json()
        self.assertEqual(r3b["filters"]["dietary_requirements"], ["halal"])
        r4 = self.client.post(
            "/api/chat",
            json={
                "message": "remove halal",
                "current_filters": r3b["filters"],
            },
        ).json()
        self.assertEqual(r4["action"], "confirm")
        self.assertEqual(r4["filters"]["dietary_requirements"], [])

        # Removing an already-liked cuisine does not mistakenly add it to
        # disliked_cuisines
        r5 = self.client.post(
            "/api/chat",
            json={
                "message": "remove japanese",
                "current_filters": r4["filters"],
            },
        ).json()
        self.assertEqual(r5["filters"]["liked_cuisines"], [])
        self.assertEqual(r5["filters"]["disliked_cuisines"], [])

        # Avoiding custom cuisines adds them to disliked_cuisines
        r6 = self.client.post(
            "/api/chat",
            json={
                "message": "avoid seafood and fast food",
                "current_filters": r5["filters"],
            },
        ).json()
        self.assertIn("seafood", r6["filters"]["disliked_cuisines"])
        self.assertIn("fast food", r6["filters"]["disliked_cuisines"])

        # Post-AI safety reconciliation protects explicit negations even if
        # live AI flips dietary_action
        def confused_ai_turn(
            message, current_filters, history, saved_profile, config
        ):
            return {
                "intent": "search",
                "reply": "Updated!",
                "updates": {
                    "dietary_requirements": ["halal"],
                    "dietary_action": "add",
                },
                "quick_replies": [],
            }

        self.application._chatbot._ai = SimpleNamespace(
            chat_turn=confused_ai_turn
        )
        r7 = self.client.post(
            "/api/chat",
            json={
                "message": "i dont want halal",
                "current_filters": {
                    **base_filters,
                    "dietary_requirements": ["halal"],
                },
            },
        ).json()
        self.assertEqual(r7["action"], "confirm")
        self.assertEqual(r7["filters"]["dietary_requirements"], [])

    def test_search_preserves_custom_disliked_cuisines_in_other_preferences(
        self,
    ):
        payload = self.search_payload()
        payload["disliked_cuisines"] = ["thai", "seafood", "fast food"]
        res = self.client.post("/api/search", json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(self.ranking_calls)
        recorded = self.ranking_calls[-1]
        self.assertEqual(recorded["disliked_cuisines"], ["thai"])
        other_cf = [o.casefold() for o in recorded["other_preferences"]]
        self.assertIn("avoid seafood cuisine", other_cf)
        self.assertIn("avoid fast food cuisine", other_cf)

    def test_chatbot_multi_location_add_phrases_and_removal(self):
        base = {
            "location": "Singapore 530967",
            "locations": ["Singapore 530967"],
            "mode": "drive",
            "max_travel_minutes": 20,
            "budget_per_person": 30,
            "dietary_requirements": [],
            "liked_cuisines": ["chinese", "japanese"],
            "disliked_cuisines": [],
            "other_preferences": [],
        }

        # Exact phrasing from bug report: must extract "Marina Bay", NOT
        # "another location"
        r1 = self.client.post(
            "/api/chat",
            json={
                "message": "add another location, marina bay",
                "current_filters": base,
            },
        ).json()
        self.assertEqual(r1["action"], "confirm")
        self.assertEqual(
            r1["filters"]["locations"], ["Singapore 530967", "Marina Bay"]
        )

        # "add second location, sentosa"
        r2 = self.client.post(
            "/api/chat",
            json={
                "message": "add second location, sentosa",
                "current_filters": r1["filters"],
            },
        ).json()
        self.assertEqual(
            r2["filters"]["locations"],
            ["Singapore 530967", "Marina Bay", "Sentosa"],
        )

        # Multi-add with filler "etc": "add locations, bugis, orchard road,
        # etc"
        r3 = self.client.post(
            "/api/chat",
            json={
                "message": "add locations, bugis, orchard road, etc",
                "current_filters": base,
            },
        ).json()
        self.assertEqual(
            r3["filters"]["locations"],
            ["Singapore 530967", "Bugis", "Orchard Road"],
        )

        # "add location, tampines"
        r4 = self.client.post(
            "/api/chat",
            json={
                "message": "add location, tampines",
                "current_filters": base,
            },
        ).json()
        self.assertEqual(
            r4["filters"]["locations"], ["Singapore 530967", "Tampines"]
        )

        # "remove location marina bay" and "remove second location"
        r5 = self.client.post(
            "/api/chat",
            json={
                "message": "remove location marina bay",
                "current_filters": r1["filters"],
            },
        ).json()
        self.assertEqual(r5["filters"]["locations"], ["Singapore 530967"])
        r6 = self.client.post(
            "/api/chat",
            json={
                "message": "remove second location",
                "current_filters": r1["filters"],
            },
        ).json()
        self.assertEqual(r6["filters"]["locations"], ["Singapore 530967"])

        # Bare "add another location" clarifies with
        # awaiting_field='add_location', then appends without replacing
        r7 = self.client.post(
            "/api/chat",
            json={"message": "add another location", "current_filters": base},
        ).json()
        self.assertEqual(r7["action"], "clarify")
        self.assertEqual(r7["awaiting_field"], "add_location")
        r8 = self.client.post(
            "/api/chat",
            json={
                "message": "Marina Bay, Sentosa",
                "current_filters": r7["filters"],
                "awaiting_field": r7["awaiting_field"],
            },
        ).json()
        self.assertEqual(
            r8["filters"]["locations"],
            ["Singapore 530967", "Marina Bay", "Sentosa"],
        )

        # Reconcile guards against confused live AI returning "another
        # location"
        def confused_loc_ai(*_args):
            return {
                "intent": "search",
                "reply": "Added!",
                "updates": {
                    "locations": ["another location"],
                    "locations_action": "add",
                },
                "quick_replies": [],
            }

        self.application._chatbot._ai = SimpleNamespace(
            chat_turn=confused_loc_ai
        )
        r9 = self.client.post(
            "/api/chat",
            json={
                "message": "add another location, marina bay",
                "current_filters": base,
            },
        ).json()
        self.assertEqual(
            r9["filters"]["locations"], ["Singapore 530967", "Marina Bay"]
        )

    def test_geocode_cache_uses_mongo_without_writing_disk_files_and_cli_defaults_mongo(  # noqa: E501
        self,
    ):
        import tempfile
        from unittest.mock import patch
        from BIS import main as bis_main
        from common import geocode_cache

        with tempfile.TemporaryDirectory() as tmp:
            missing_cache_file = Path(tmp) / "data" / "geocode_cache.json"
            with (
                patch.dict(os.environ, {"BITEFINDER_STORAGE": "mongo"}),
                patch.object(geocode_cache, "CACHE_FILE", missing_cache_file),
                patch.object(
                    geocode_cache, "_mongo_collection", return_value=self.conn
                ),
            ):
                self.assertTrue(
                    geocode_cache.remember(
                        ["Marina Bay", "marina bay sg"], 1.2834, 103.8607
                    )
                )
                self.assertEqual(
                    geocode_cache.lookup("marina bay"), (1.2834, 103.8607)
                )
                self.assertFalse(missing_cache_file.parent.exists())

        seen = {}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BITEFINDER_STORAGE", None)
            with (
                patch.object(
                    bis_main,
                    "_initialize_cli",
                    side_effect=lambda: seen.setdefault(
                        "storage", os.environ.get("BITEFINDER_STORAGE")
                    ),
                ),
                patch("BIS.main.debug_log", create=True),
                patch("BIS.main.io_manager", create=True),
                patch("BIS.main.settings", create=True) as mock_settings,
            ):
                mock_settings.load_config.side_effect = KeyboardInterrupt
                bis_main.run_cli()
        self.assertEqual(seen.get("storage"), "mongo")

    def test_cli_created_credentials_authenticate_on_web_login(self):
        user = self.data.register_user(
            "cli_pw@example.com", "CLI Password User"
        )
        user = self.data.save(dict(user, email_verified=True))
        self.data.save_credentials(
            user["userID"], PasswordHasher().create("cli.password.1")
        )
        self.config["smtp_bypass"] = True

        bad = self.client.post(
            "/api/auth/login",
            json={"email": "cli_pw@example.com", "password": "wrong"},
        )
        self.assertEqual(bad.status_code, 401)
        ok = self.client.post(
            "/api/auth/login",
            json={"email": "cli_pw@example.com", "password": "cli.password.1"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["user"]["userID"], user["userID"])

    def test_swagger_docs_disabled_by_default(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = self.client.get(path)
            self.assertEqual(
                response.status_code,
                404,
                f"{path} should return 404 by default",
            )

    def test_map_config_and_route_geometry_contract(self):
        from unittest.mock import patch

        default_res = self.client.get("/api/map-config")
        self.assertEqual(default_res.status_code, 200, default_res.text)
        self.assertEqual(
            default_res.json(),
            {"provider": "leaflet", "google_maps_api_key": ""},
        )

        try:
            self.config["google_maps_api_key"] = "backend-key"
            fallback_key_res = self.client.get("/api/map-config")
            self.assertEqual(fallback_key_res.status_code, 200)
            self.assertEqual(
                fallback_key_res.json(),
                {"provider": "google", "google_maps_api_key": "backend-key"},
            )

            self.config["google_maps_js_api_key"] = "browser-js-key"
            dedicated_key_res = self.client.get("/api/map-config")
            self.assertEqual(dedicated_key_res.status_code, 200)
            self.assertEqual(
                dedicated_key_res.json(),
                {
                    "provider": "google",
                    "google_maps_api_key": "browser-js-key",
                },
            )

            self.config["use_live_google"] = False
            disabled_res = self.client.get("/api/map-config")
            self.assertEqual(disabled_res.status_code, 200)
            self.assertEqual(
                disabled_res.json(),
                {"provider": "leaflet", "google_maps_api_key": ""},
            )
        finally:
            self.config.pop("google_maps_api_key", None)
            self.config.pop("google_maps_js_api_key", None)
            self.config["use_live_google"] = True

        sample_route = {
            "duration_min": 8,
            "distance_m": 620,
            "steps": ["Walk east"],
            "encoded_polyline": "_p~iF~ps|U_ulLnnqC",
            "path": [[1.35, 103.94], [1.354, 103.945]],
            "segments": [
                {"mode": "walk", "path": [[1.35, 103.94], [1.354, 103.945]]}
            ],
        }
        with patch.object(
            self.application._brns,
            "route_to",
            return_value={
                "name": "Target Spot",
                "mode": "walk",
                "route": sample_route,
                "link": "https://www.google.com/maps",
            },
        ):
            route_res = self.client.post(
                "/api/route",
                json={
                    "name": "Target Spot",
                    "origin_lat": 1.35,
                    "origin_lng": 103.94,
                    "dest_lat": 1.354,
                    "dest_lng": 103.945,
                    "mode": "walk",
                },
            )
        self.assertEqual(route_res.status_code, 200, route_res.text)
        body = route_res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["route"]["path"], sample_route["path"])
        self.assertEqual(body["route"]["segments"], sample_route["segments"])
        self.assertEqual(
            body["route"]["encoded_polyline"], sample_route["encoded_polyline"]
        )

    def test_place_photo_endpoint_persists_blob_in_mongodb_on_first_click(
        self,
    ):
        from unittest.mock import patch
        from BRNS.classes.data.stores.mongo.mongo_place_photo_store import (
            MongoPlacePhotoStore,
        )
        from BRNS.classes.io.gateways.google.google_place_photo_gateway import (  # noqa: E501
            GooglePlacePhotoGateway,
        )
        from BRNS.classes.services.workflows.place_photo_service import (
            PlacePhotoService,
        )

        photo_store = MongoPlacePhotoStore(self.conn)
        photo_store.ensure_indexes()
        cfg = SimpleNamespace(
            GOOGLE_MAPS_API_KEY="test-places-key",
            PLACES_DETAILS_BASE_URL="https://places.example.test/v1",
            USE_LIVE_GOOGLE=True,
        )
        gateway = GooglePlacePhotoGateway(
            cfg,
            SimpleNamespace(debug_log=lambda *_a, **_kw: None),
            lambda *_a, **_kw: None,
        )
        photo_service = PlacePhotoService(
            photo_store,
            gateway,
            SimpleNamespace(debug_log=lambda *_a, **_kw: None),
        )

        details_resp = Mock(status_code=200)
        details_resp.raise_for_status = Mock()
        details_resp.json.return_value = {
            "photos": [
                {
                    "name": "places/ChIJWebPin1/photos/Ref1",
                    "authorAttributions": [{"displayName": "Mei Lin"}],
                }
            ],
        }
        media_resp = Mock(
            status_code=200, headers={"Content-Type": "application/json"}
        )
        media_resp.raise_for_status = Mock()
        media_resp.json.return_value = {
            "photoUri": "https://img.example.test/pin.webp"
        }
        img_resp = Mock(
            status_code=200,
            headers={"Content-Type": "image/webp"},
            content=b"RIFFWEBPTESTBLOB",
        )
        img_resp.raise_for_status = Mock()

        with patch.object(
            self.application._brns,
            "place_photo",
            side_effect=photo_service.get_or_fetch_photo,
        ):
            bad = self.client.get("/api/places/bad%20place/photo")
            self.assertEqual(bad.status_code, 400)

            self.assertEqual(
                self.conn.execute(
                    lambda db: db.place_photos.count_documents({})
                ),
                0,
            )
            with patch(
                (
                    "BRNS.classes.io.gateways.google.google_place_photo_gatewa"
                    "y.requests.get"
                ),
                side_effect=[details_resp, media_resp, img_resp],
            ) as mock_get:
                first = self.client.get("/api/places/ChIJWebPin1/photo")
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.content, b"RIFFWEBPTESTBLOB")
                self.assertEqual(first.headers["content-type"], "image/webp")
                self.assertEqual(first.headers["x-photo-author"], "Mei%20Lin")
                self.assertEqual(mock_get.call_count, 3)

                # Stored in dedicated `place_photos` collection without
                # touching `restaurants`.
                self.assertEqual(
                    self.conn.execute(
                        lambda db: db.restaurants.count_documents({})
                    ),
                    0,
                )
                doc = self.conn.execute(
                    lambda db: db.place_photos.find_one({"_id": "ChIJWebPin1"})
                )
                self.assertIsNotNone(doc)
                self.assertEqual(bytes(doc["data"]), b"RIFFWEBPTESTBLOB")
                self.assertEqual(doc["content_type"], "image/webp")

                # Subsequent pin click serves directly from MongoDB without
                # Google HTTP calls.
                second = self.client.get("/api/places/ChIJWebPin1/photo")
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.content, b"RIFFWEBPTESTBLOB")
                self.assertEqual(mock_get.call_count, 3)

    def test_password_length_and_allowed_symbols_enforced(self):
        # Task 1: min 8, max 30 chars, only ASCII letters, digits, and .,?!$
        # allowed.
        for bad_pw in (
            "seven77",  # 7 chars
            "a" * 31,  # 31 chars
            "pass-word1",  # hyphen disallowed
            "pass_word1",  # underscore disallowed
            "pass@word1",  # @ disallowed
            "pass word1",  # space disallowed
        ):
            res = self.client.post(
                "/api/auth/register",
                json={
                    "username": "Pw Tester",
                    "email": "pw.bad@example.com",
                    "password": bad_pw,
                },
            )
            self.assertIn(
                res.status_code,
                (400, 422),
                f"Expected rejection for {bad_pw!r}: {res.text}",
            )
            with self.assertRaises(ValueError):
                PasswordHasher().create(bad_pw)

        for idx, good_pw in enumerate(
            (
                "pass.12!",  # exact 8 chars + symbols
                ("A1b2c3.,?!" * 3),  # exact 30 chars
                "Alpha9.,?!$",  # all allowed symbols
            )
        ):
            res = self.client.post(
                "/api/auth/register",
                json={
                    "username": f"PwOk{idx}",
                    "email": f"pw.ok.{idx}@example.com",
                    "password": good_pw,
                },
            )
            self.assertEqual(
                res.status_code,
                200,
                f"Expected acceptance for {good_pw!r}: {res.text}",
            )

    def test_email_format_validation_enforced(self):
        # Task 2: proper email format required across auth endpoints.
        for bad_email in (
            "invalid-email",
            "a@b.c",
            "a@b.123",
            "a..b@example.com",
            ".lead@example.com",
            "trail.@example.com",
            "user@-bad.com",
        ):
            res = self.client.post(
                "/api/auth/register",
                json={
                    "username": "EmailTester",
                    "email": bad_email,
                    "password": "ValidPass.1!",
                },
            )
            self.assertIn(
                res.status_code,
                (400, 422),
                f"Expected rejection for {bad_email!r}: {res.text}",
            )

        for idx, good_email in enumerate(
            (
                "valid.user+tag@sub.example.sg",
                "fuwei_@outlook.com",
                "_fuwei@outlook.com",
                "a.b+1_@sub.outlook.com",
            )
        ):
            ok = self.client.post(
                "/api/auth/register",
                json={
                    "username": f"EmailOk{idx}",
                    "email": good_email,
                    "password": "ValidPass.1!",
                },
            )
            self.assertEqual(
                ok.status_code,
                200,
                f"Expected acceptance for {good_email!r}: {ok.text}",
            )

    def test_search_mode_travel_limits_and_transit_distance_supported(self):
        # Task 3: walk <=15km/90m, drive <=50km/120m, transit <=50km/150m (both
        # supported).
        headers, _ = self.account("travel.caps@example.com")
        base = self.search_payload()

        valid_cases = [
            ("walk", 15.0, None),
            ("walk", None, 90),
            ("drive", 50.0, None),
            ("drive", None, 120),
            ("transit", 50.0, None),
            ("transit", None, 150),
        ]
        for mode, dist_km, mins in valid_cases:
            payload = dict(
                base,
                mode=mode,
                max_distance_km=dist_km,
                max_travel_minutes=mins,
                confirm_only=True,
            )
            res = self.client.post(
                "/api/search", json=payload, headers=headers
            )
            self.assertEqual(
                res.status_code,
                200,
                f"Expected OK for {(mode, dist_km, mins)}: {res.text}",
            )

        # Verify transit distance actually reaches BRNS search execution.
        confirm_transit_dist = self.client.post(
            "/api/search",
            json=dict(
                base,
                mode="transit",
                max_distance_km=50.0,
                max_travel_minutes=None,
                confirm_only=True,
            ),
            headers=headers,
        )
        self.assertEqual(
            confirm_transit_dist.status_code, 200, confirm_transit_dist.text
        )
        run_transit_dist = self.client.post(
            "/api/search",
            json=dict(
                base,
                mode="transit",
                max_distance_km=50.0,
                max_travel_minutes=None,
                confirmation_token=confirm_transit_dist.json()[
                    "confirmation_token"
                ],
            ),
            headers=headers,
        )
        self.assertEqual(
            run_transit_dist.status_code, 200, run_transit_dist.text
        )
        self.assertEqual(self.ranking_calls[-1]["mode"], "transit")
        self.assertEqual(self.ranking_calls[-1]["max_distance_km"], 50.0)

        invalid_cases = [
            ("walk", 15.1, None),
            ("walk", None, 91),
            ("drive", 50.1, None),
            ("drive", None, 121),
            ("transit", 50.1, None),
            ("transit", None, 151),
        ]
        for mode, dist_km, mins in invalid_cases:
            payload = dict(
                base,
                mode=mode,
                max_distance_km=dist_km,
                max_travel_minutes=mins,
                confirm_only=True,
            )
            res = self.client.post(
                "/api/search", json=payload, headers=headers
            )
            self.assertEqual(
                res.status_code,
                400,
                f"Expected 400 for {(mode, dist_km, mins)}: {res.text}",
            )

    def test_profile_allows_empty_or_real_location_unlimited_metrics_and_english_wishes(  # noqa: E501
        self,
    ):
        # Task 4: empty or real SG location, no upper limits for
        # time/distance/budget, proper English wishes.
        headers, user = self.account("profile.rules@example.com")

        def make_profile(**overrides):
            payload = dict(user)
            payload.pop("email_verified", None)
            payload.update(overrides)
            return payload

        # Valid: empty location + max cross-island profile limits + exact $100
        # + English wishes.
        ok = self.client.post(
            "/api/profile",
            json=make_profile(
                location=[],
                max_distance_km=50,
                max_travel_time_minutes=150,
                budget_per_person=1000,
                other_preferences=["quiet corner", "window seat"],
            ),
            headers=headers,
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        saved = self.client.get("/api/auth/me", headers=headers).json()["user"]
        self.assertEqual(saved["location"], [])
        self.assertEqual(saved["max_distance_km"], 50.0)
        self.assertEqual(saved["max_travel_time_minutes"], 150.0)
        self.assertEqual(saved["budget_per_person"], 1000.0)
        self.assertEqual(
            saved["other_preferences"], ["quiet corner", "window seat"]
        )

        # Exact $100 and minimum bounds save cleanly; max distance
        # auto-estimates clamped time.
        ok_exact = self.client.post(
            "/api/profile",
            json=make_profile(
                location=["Orchard"],
                max_distance_km=0.01,
                max_travel_time_minutes=1,
                budget_per_person=100,
            ),
            headers=headers,
        )
        self.assertEqual(ok_exact.status_code, 200, ok_exact.text)
        saved_exact = self.client.get("/api/auth/me", headers=headers).json()[
            "user"
        ]
        self.assertEqual(saved_exact["max_distance_km"], 0.01)
        self.assertEqual(saved_exact["max_travel_time_minutes"], 1.0)
        self.assertEqual(saved_exact["budget_per_person"], 100.0)

        ok_auto = self.client.post(
            "/api/profile",
            json=make_profile(
                location=["Orchard"],
                max_distance_km=50,
                max_travel_time_minutes=None,
                budget_per_person=100,
            ),
            headers=headers,
        )
        self.assertEqual(ok_auto.status_code, 200, ok_auto.text)
        saved_auto = self.client.get("/api/auth/me", headers=headers).json()[
            "user"
        ]
        self.assertEqual(saved_auto["max_distance_km"], 50.0)
        self.assertEqual(saved_auto["max_travel_time_minutes"], 150.0)

        # Out-of-range profile limits are rejected.
        for bad_limits in (
            {"max_distance_km": 50.1},
            {"max_travel_time_minutes": 0.5},
            {"max_travel_time_minutes": 151},
            {"budget_per_person": 1001},
        ):
            r_bad_limit = self.client.post(
                "/api/profile",
                json=make_profile(**bad_limits),
                headers=headers,
            )
            self.assertEqual(r_bad_limit.status_code, 400)

        # Valid: real SG coordinate string.
        ok_coord = self.client.post(
            "/api/profile",
            json=make_profile(
                location=["1.352, 103.944"],
            ),
            headers=headers,
        )
        self.assertEqual(ok_coord.status_code, 200, ok_coord.text)

        # Invalid: fake / non-Singapore location rejected by location
        # resolution.
        orig_resolve = self.gateway.resolve

        def resolve_sg(query, _key):
            if "atlantis" in query.lower():
                raise ValueError(
                    "Could not find a Singapore location for 'Atlantis'."
                )
            return orig_resolve(query, _key)

        with self.subTest("invalid location"):
            self.gateway.resolve = resolve_sg
            try:
                bad_loc = self.client.post(
                    "/api/profile",
                    json=make_profile(
                        location=["Atlantis"],
                    ),
                    headers=headers,
                )
                self.assertEqual(bad_loc.status_code, 400, bad_loc.text)
            finally:
                self.gateway.resolve = orig_resolve

        # Invalid: non-English, gibberish, digits-only, or punctuation-only
        # special wishes rejected.
        for bad_wishes in (["你好"], ["dkdk"], ["asdfghj"], ["1234"], ["!!!"]):
            bad_wish_res = self.client.post(
                "/api/profile",
                json=make_profile(
                    other_preferences=bad_wishes,
                ),
                headers=headers,
            )
            self.assertEqual(
                bad_wish_res.status_code,
                400,
                f"Expected 400 for {bad_wishes!r}: {bad_wish_res.text}",
            )

        # AI semantic validation runs when ai_bypass is False.
        self.config["ai_bypass"] = False
        self.ai.review_profile_wishes = Mock(
            side_effect=ValueError(
                (
                    "Default special wishes must be meaningful English "
                    "preferences."
                )
            )
        )
        try:
            ai_rejected = self.client.post(
                "/api/profile",
                json=make_profile(
                    other_preferences=["blorp"],
                ),
                headers=headers,
            )
            self.assertEqual(ai_rejected.status_code, 400, ai_rejected.text)
            self.ai.review_profile_wishes.assert_called_once()
        finally:
            self.config["ai_bypass"] = True

    def test_smtp_bypass_toggles_dynamically_from_env_file_without_reloading_config(  # noqa: E501
        self,
    ):
        # Task 5: editing .env SMTP_BYPASS takes effect live without
        # container/config restart.
        import os
        import tempfile
        from unittest.mock import patch
        from BIS.support import config as bis_config

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "SMTP_BYPASS=true\nAI_BYPASS=true\n", encoding="utf-8"
            )

            with (
                patch.object(bis_config, "ENV_FILE", env_path),
                patch.dict(
                    os.environ,
                    {"SMTP_BYPASS": "true", "AI_BYPASS": "true"},
                    clear=False,
                ),
            ):
                live_cfg = bis_config.load_config()

            self.assertTrue(bis_config.is_smtp_bypass(live_cfg))

            # Flip to false in .env without calling load_config() again.
            env_path.write_text(
                "SMTP_BYPASS=false\nAI_BYPASS=true\n", encoding="utf-8"
            )
            self.assertFalse(bis_config.is_smtp_bypass(live_cfg))

            # Flip back to true in .env without calling load_config() again.
            env_path.write_text(
                "SMTP_BYPASS=true\nAI_BYPASS=true\n", encoding="utf-8"
            )
            self.assertTrue(bis_config.is_smtp_bypass(live_cfg))

            # Verify live registration endpoint reacts to _env_file toggle
            # without restart.
            self.config["_env_file"] = str(env_path)
            self.config["smtp_bypass"] = False
            self.config["_smtp_bypass_initial"] = False
            try:
                env_path.write_text("SMTP_BYPASS=true\n", encoding="utf-8")
                reg_bypass = self.client.post(
                    "/api/auth/register",
                    json={
                        "username": "LiveOn",
                        "email": "live.on@example.com",
                        "password": "ValidPass.1!",
                    },
                )
                self.assertEqual(reg_bypass.status_code, 200, reg_bypass.text)
                self.assertFalse(reg_bypass.json().get("otp_required"))
                self.assertIn("token", reg_bypass.json())

                env_path.write_text("SMTP_BYPASS=false\n", encoding="utf-8")
                reg_verify = self.client.post(
                    "/api/auth/register",
                    json={
                        "username": "LiveOff",
                        "email": "live.off@example.com",
                        "password": "ValidPass.1!",
                    },
                )
                self.assertEqual(reg_verify.status_code, 200, reg_verify.text)
                self.assertTrue(reg_verify.json().get("otp_required"))
                self.assertEqual(self.sent[-1][0], "live.off@example.com")
            finally:
                self.config.pop("_env_file", None)
                self.config.pop("smtp_bypass", None)
                self.config.pop("_smtp_bypass_initial", None)

    def test_search_and_chatbot_validate_proper_english_special_requests(self):
        from BIS.classes.logic.validators.search_request_validator import (
            create_search_request_validator,
        )

        # 1. Search Filters (/api/search) & SearchRequestValidator reject
        # non-English / gibberish / symbols / empty words
        bad_inputs = (
            ["你好"],
            ["dkdk"],
            ["asdfghj"],
            ["1234"],
            ["!!!"],
            ["abc$"],
            ["x" * 101],
        )
        validator = create_search_request_validator()
        for bad_wishes in bad_inputs:
            payload = dict(self.search_payload(), other_preferences=bad_wishes)
            res = self.client.post("/api/search", json=payload)
            self.assertEqual(
                res.status_code,
                400,
                f"Expected 400 for {bad_wishes!r}: {res.text}",
            )
            self.assertIn("Special requests", res.json()["detail"])

            base_req = {
                "origin": {
                    "query": "Bugis",
                    "label": "Bugis",
                    "latitude": 1.30,
                    "longitude": 103.85,
                },
                "mode": "walk",
                "max_distance_km": None,
                "max_travel_minutes": 15.0,
                "traffic_aware": False,
                "cuisine": "none",
                "budget_per_person": 20.0,
                "other_preferences": bad_wishes,
                "dietary_requirements": [],
                "disliked_cuisines": [],
            }
            with self.assertRaises(ValueError):
                validator.validate(base_req)

        ok_search = self.client.post(
            "/api/search",
            json=dict(
                self.search_payload(),
                other_preferences=[
                    "quiet seating",
                    "at least 4.5 stars",
                    "near mrt",
                    "bbq",
                ],
            ),
        )
        self.assertEqual(ok_search.status_code, 200, ok_search.text)

        # AI semantic validation runs on search special requests when ai_bypass
        # is False.
        self.config["ai_bypass"] = False
        self.ai.review_profile_wishes = Mock(
            side_effect=ValueError(
                (
                    "Default special wishes must be meaningful English "
                    "preferences."
                )
            )
        )
        try:
            ai_bad_search = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    other_preferences=["comida picante"],
                ),
            )
            self.assertEqual(
                ai_bad_search.status_code, 400, ai_bad_search.text
            )
            self.assertIn("Special requests", ai_bad_search.json()["detail"])
            self.ai.review_profile_wishes.assert_called_once()
        finally:
            self.config["ai_bypass"] = True

        # 2. Chatbot regular flow: contextual
        # awaiting_field='other_preferences' + explicit commands + confirm
        base_filters = {
            "location": "Bugis",
            "locations": ["Bugis"],
            "mode": "walk",
            "max_travel_minutes": 15.0,
            "max_distance_km": None,
            "budget_per_person": 20.0,
            "dietary_requirements": [],
            "liked_cuisines": [],
            "disliked_cuisines": [],
            "other_preferences": [],
        }
        edit_wishes = self.client.post(
            "/api/chat",
            json={
                "message": "change wishes",
                "current_filters": base_filters,
            },
        ).json()
        self.assertEqual(edit_wishes["action"], "clarify")
        self.assertEqual(edit_wishes["awaiting_field"], "other_preferences")

        for bad_text in (
            "你好",
            "dkdk",
            "asdfghj",
            "1234",
            "!!!",
            "abc$",
            "a " + "b" * 105,
        ):
            bad_chat = self.client.post(
                "/api/chat",
                json={
                    "message": bad_text,
                    "current_filters": base_filters,
                    "awaiting_field": "other_preferences",
                },
            ).json()
            self.assertEqual(
                bad_chat["action"],
                "clarify",
                f"Expected clarify for {bad_text!r}",
            )
            self.assertEqual(bad_chat["awaiting_field"], "other_preferences")
            self.assertEqual(bad_chat["filters"]["other_preferences"], [])
            self.assertIn("Special requests", bad_chat["reply"])

        for explicit_bad in (
            "add wish 你好",
            "special request: asdfghj",
            "wish: 1234",
        ):
            bad_free = self.client.post(
                "/api/chat",
                json={
                    "message": explicit_bad,
                    "current_filters": base_filters,
                },
            ).json()
            self.assertEqual(bad_free["action"], "clarify", explicit_bad)
            self.assertEqual(bad_free["awaiting_field"], "other_preferences")
            self.assertEqual(bad_free["filters"]["other_preferences"], [])

        # Even if AI extracts invalid wishes, chatbot rejects cleanly before
        # updating filters.
        self.config["ai_bypass"] = False
        self.ai.chat_turn = lambda *_args: {
            "intent": "search",
            "reply": "Added wish.",
            "updates": {"other_preferences": ["你好"], "other_action": "add"},
            "quick_replies": [],
        }
        try:
            ai_chat_bad = self.client.post(
                "/api/chat",
                json={
                    "message": "quiet seat",
                    "current_filters": base_filters,
                },
            ).json()
            self.assertEqual(ai_chat_bad["action"], "clarify")
            self.assertEqual(
                ai_chat_bad["awaiting_field"], "other_preferences"
            )
            self.assertEqual(ai_chat_bad["filters"]["other_preferences"], [])
        finally:
            self.config["ai_bypass"] = True

        # Confirming when current_filters holds invalid wishes rejects before
        # searching, then "Clear wishes" clears it.
        confirm_bad = self.client.post(
            "/api/chat",
            json={
                "message": "Yes, search now",
                "current_filters": dict(
                    base_filters, other_preferences=["你好"]
                ),
                "awaiting_field": "confirm",
            },
        ).json()
        self.assertEqual(confirm_bad["action"], "clarify")
        self.assertEqual(confirm_bad["awaiting_field"], "other_preferences")

        cleared = self.client.post(
            "/api/chat",
            json={
                "message": "Clear wishes",
                "current_filters": confirm_bad["filters"],
                "awaiting_field": confirm_bad["awaiting_field"],
            },
        ).json()
        self.assertEqual(cleared["action"], "confirm")
        self.assertEqual(cleared["filters"]["other_preferences"], [])

        good_chat = self.client.post(
            "/api/chat",
            json={
                "message": "quiet corner, near mrt",
                "current_filters": base_filters,
                "awaiting_field": "other_preferences",
            },
        ).json()
        self.assertEqual(good_chat["action"], "confirm")
        self.assertEqual(
            good_chat["filters"]["other_preferences"],
            ["quiet corner", "near mrt"],
        )

        # 3. Chatbot Onboarding rejects invalid special requests at step 7 and
        # keeps onboarding active.
        headers, _ = self.account("onboard.wishes@example.com")
        state = self.client.post(
            "/api/chat",
            json={
                "message": "__start_onboarding__",
                "current_filters": {},
                "onboarding": True,
            },
            headers=headers,
        ).json()
        for msg in ("Punggol", "$25", "20 mins", "None", "None", "None"):
            state = self.client.post(
                "/api/chat",
                json={
                    "message": msg,
                    "current_filters": state["filters"],
                    "onboarding": True,
                    "awaiting_field": state["awaiting_field"],
                },
                headers=headers,
            ).json()
        self.assertEqual(state["awaiting_field"], "other_preferences")

        for bad_onboard in ("你好", "dkdk", "1234", "!!!"):
            retry = self.client.post(
                "/api/chat",
                json={
                    "message": bad_onboard,
                    "current_filters": state["filters"],
                    "onboarding": True,
                    "awaiting_field": "other_preferences",
                },
                headers=headers,
            ).json()
            self.assertEqual(retry["action"], "onboarding")
            self.assertEqual(retry["awaiting_field"], "other_preferences")
            self.assertFalse(retry["saved_to_profile"])
            self.assertIn("Special requests", retry["reply"])

        finish = self.client.post(
            "/api/chat",
            json={
                "message": "quiet corner, spicy food",
                "current_filters": state["filters"],
                "onboarding": True,
                "awaiting_field": "other_preferences",
            },
            headers=headers,
        ).json()
        self.assertEqual(finish["action"], "confirm")
        self.assertTrue(finish["saved_to_profile"])
        self.assertEqual(
            finish["filters"]["other_preferences"],
            ["quiet corner", "spicy food"],
        )

    def test_legacy_persisted_profile_limits_and_unrelated_docs_do_not_block_login(  # noqa: E501
        self,
    ):
        _, valid_user = self.account("test@gmail.com")
        legacy_headers, legacy_user = self.account("legacy@example.com")
        self.config["smtp_bypass"] = True

        # Simulate pre-existing MongoDB user saved under old wider numeric
        # limits.
        self.conn.execute(
            lambda db: db.users.update_one(
                {"_id": legacy_user["user_id"]},
                {
                    "$set": {
                        "preferences.max_distance_km": 200.0,
                        "preferences.max_travel_time_minutes": 300.0,
                        "preferences.budget_per_person": 2000.0,
                    }
                },
            )
        )

        # Valid account sign-in works despite another user having legacy
        # bounds.
        login_valid = self.client.post(
            "/api/auth/login",
            json={
                "email": "test@gmail.com",
                "password": "test.password",
            },
        )
        self.assertEqual(login_valid.status_code, 200, login_valid.text)
        self.assertTrue(login_valid.json()["success"])

        # Legacy account can also sign in and reads clamped bounds within
        # profile limits.
        login_legacy = self.client.post(
            "/api/auth/login",
            json={
                "email": "legacy@example.com",
                "password": "test.password",
            },
        )
        self.assertEqual(login_legacy.status_code, 200, login_legacy.text)
        me_legacy = self.client.get(
            "/api/auth/me", headers=legacy_headers
        ).json()["user"]
        self.assertEqual(me_legacy["max_distance_km"], 50.0)
        self.assertEqual(me_legacy["max_travel_time_minutes"], 150.0)
        self.assertEqual(me_legacy["budget_per_person"], 1000.0)

        # Strict validation remains enforced on new profile writes and updates.
        bad_save = self.client.post(
            "/api/profile",
            json={
                "user_id": valid_user["user_id"],
                "username": "Tester",
                "location": ["Orchard"],
                "max_distance_km": 200.0,
                "max_travel_time_minutes": 30.0,
                "budget_per_person": 25.0,
                "dietary_requirements": [],
                "liked_cuisines": [],
                "disliked_cuisines": [],
                "other_preferences": [],
            },
            headers={"Authorization": "Bearer " + login_valid.json()["token"]},
        )
        self.assertEqual(bad_save.status_code, 400)

        legacy_prefs = {
            "location": ["Orchard"],
            "max_distance_km": 200.0,
            "max_travel_time_minutes": 300.0,
            "budget_per_person": 2000.0,
            "dietary_requirements": [],
            "liked_cuisines": [],
            "disliked_cuisines": [],
            "other_preferences": [],
        }
        updated_prefs = LogicManager().apply_updates(
            legacy_prefs, {"budget_per_person": 45}
        )
        self.assertEqual(updated_prefs["max_distance_km"], 50.0)
        self.assertEqual(updated_prefs["max_travel_time_minutes"], 150.0)
        self.assertEqual(updated_prefs["budget_per_person"], 45.0)
        with self.assertRaises(ValueError):
            LogicManager().apply_updates(
                legacy_prefs, {"max_distance_km": 200}
            )

        # Unrelated malformed document in Mongo users collection does not break
        # targeted login.
        self.conn.execute(
            lambda db: db.users.insert_one(
                {"_id": "corrupt-doc", "email": "broken@example.com"}
            )
        )
        isolated_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "test@gmail.com",
                "password": "test.password",
            },
        )
        self.assertEqual(isolated_login.status_code, 200, isolated_login.text)
        wrong_pw = self.client.post(
            "/api/auth/login",
            json={
                "email": "test@gmail.com",
                "password": "wrong-password",
            },
        )
        self.assertEqual(wrong_pw.status_code, 401)

    def test_chatbot_profile_sync_plus_budget_and_all_fields(self):
        headers, user = self.account("profilesync@example.com")
        save_res = self.client.post(
            "/api/profile",
            json={
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "location": ["Bugis Junction"],
                "max_distance_km": 0.5,
                "max_travel_time_minutes": 10.0,
                "budget_per_person": 1000.0,
                "dietary_requirements": ["halal"],
                "liked_cuisines": ["japanese"],
                "disliked_cuisines": ["indian"],
                "other_preferences": ["quiet seating"],
            },
            headers=headers,
        )
        self.assertEqual(save_res.status_code, 200, save_res.text)

        show_res = self.client.post(
            "/api/chat",
            json={
                "message": "show my profile",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(show_res.status_code, 200, show_res.text)
        profile_reply = show_res.json()["reply"]
        self.assertIn("10 mins / 0.5 km", profile_reply)
        self.assertIn("SGD $100+", profile_reply)
        self.assertNotIn("SGD $1000", profile_reply)
        self.assertIn("indian", profile_reply.lower())
        self.assertIn("quiet seating", profile_reply.lower())

        # Chatbot parses "$100+" and "casual dining" and formats $100+ without
        # leaking $1000
        plus_chat = self.client.post(
            "/api/chat",
            json={
                "message": "Korean BBQ near Orchard $100+ walk 15 mins",
                "current_filters": {
                    "locations": ["Bugis Junction"],
                    "budget_per_person": 25.0,
                    "max_travel_minutes": 10.0,
                },
            },
            headers=headers,
        )
        self.assertEqual(plus_chat.status_code, 200, plus_chat.text)
        plus_json = plus_chat.json()
        self.assertEqual(plus_json["filters"]["budget_per_person"], 1000.0)
        self.assertIn("SGD $100+", plus_json["reply"])
        self.assertNotIn("SGD $1000", plus_json["reply"])
        self.assertTrue(any("SGD $100+" in c for c in plus_json["changes"]))
        self.assertTrue(any("15 mins" in c for c in plus_json["changes"]))

        casual_chat = self.client.post(
            "/api/chat",
            json={
                "message": "casual dining near Bugis 15 mins walk",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(casual_chat.status_code, 200, casual_chat.text)
        self.assertEqual(
            casual_chat.json()["filters"]["budget_per_person"], 50.0
        )

        # Cross-island profile limits (>90 mins / >15 km) auto-select transit
        # on reset/default
        long_save = self.client.post(
            "/api/profile",
            json={
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "location": ["Orchard"],
                "max_distance_km": 30.0,
                "max_travel_time_minutes": 120.0,
                "budget_per_person": 1000.0,
                "dietary_requirements": [],
                "liked_cuisines": [],
                "disliked_cuisines": [],
                "other_preferences": [],
            },
            headers=headers,
        )
        self.assertEqual(long_save.status_code, 200, long_save.text)
        reset_res = self.client.post(
            "/api/chat",
            json={
                "message": "Use my saved profile",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(reset_res.status_code, 200, reset_res.text)
        self.assertEqual(reset_res.json()["filters"]["mode"], "transit")
        self.assertEqual(
            reset_res.json()["filters"]["max_travel_minutes"], 120.0
        )

        # Even if AI strips '+' from '$100+' -> 100, reconciliation preserves
        # 1000.0 (SGD $100+)
        self.application._chatbot._ai = SimpleNamespace(
            chat_turn=lambda msg, cur, hist, prof, cfg: {
                "intent": "search",
                "reply": "Searching Orchard.",
                "updates": {
                    "locations": ["Orchard"],
                    "locations_action": "replace",
                    "budget_per_person": 100,
                    "max_travel_minutes": 15,
                },
                "quick_replies": ["Yes, search now"],
            }
        )
        ai_plus = self.client.post(
            "/api/chat",
            json={
                "message": "Korean near Orchard $100+ 15 mins",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(ai_plus.status_code, 200, ai_plus.text)
        self.assertEqual(
            ai_plus.json()["filters"]["budget_per_person"], 1000.0
        )
        self.assertIn("SGD $100+", ai_plus.json()["reply"])

    def test_multi_cuisine_merge_interleaves_and_fills_unused_quota(self):
        from BIS.classes.logic.logic_manager import LogicManager

        logic = LogicManager()
        fetched = [
            (
                "japanese",
                {
                    "matches": [
                        {
                            "restaurant": {
                                "google_place_id": f"j-{i}",
                                "name": f"Jap {i}",
                            }
                        }
                        for i in range(1, 3)
                    ],
                    "alternatives": [],
                    "hidden": 0,
                },
            ),
            (
                "korean",
                {
                    "matches": [
                        {
                            "restaurant": {
                                "google_place_id": f"k-{i}",
                                "name": f"Kor {i}",
                            }
                        }
                        for i in range(1, 13)
                    ],
                    "alternatives": [],
                    "hidden": 1,
                },
            ),
        ]
        matches, alternatives, breakdown, hidden = (
            logic.merge_multi_cuisine_results(
                fetched, num_cuisines=2, max_total=10
            )
        )
        self.assertEqual(len(matches), 10)
        self.assertEqual(alternatives, [])
        self.assertEqual(hidden, 1)
        self.assertEqual(breakdown, {"japanese": 2, "korean": 8})
        self.assertEqual(
            [m["restaurant"]["google_place_id"] for m in matches[:4]],
            ["j-1", "k-1", "j-2", "k-2"],
        )

    def test_rating_wish_normalization_ai_bypass_and_chatbot_rating_sync(self):
        # Pure rating wishes (even with decimal typo '4 .5') pass
        # deterministically without AI rejection.
        self.config["ai_bypass"] = False
        self.ai.review_profile_wishes = Mock(
            side_effect=AssertionError(
                "review_profile_wishes should not run for pure rating wishes"
            )
        )
        try:
            search_res = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    other_preferences=["minimum 4 .5 stars"],
                ),
            )
            self.assertEqual(search_res.status_code, 200, search_res.text)
            self.assertEqual(
                self.ranking_calls[-1]["other_preferences"],
                ["minimum 4.5 stars"],
            )
            self.ai.review_profile_wishes.assert_not_called()

            headers, user = self.account("rating.wish@example.com")
            prof_res = self.client.post(
                "/api/profile",
                json={
                    "user_id": user["user_id"],
                    "username": "ratingwish",
                    "email": user["email"],
                    "location": ["Bugis"],
                    "max_distance_km": 2.0,
                    "max_travel_time_minutes": 30.0,
                    "budget_per_person": 25.0,
                    "dietary_requirements": [],
                    "liked_cuisines": [],
                    "disliked_cuisines": [],
                    "other_preferences": ["minimum 4 .5 stars", "4.5/5"],
                },
                headers=headers,
            )
            self.assertEqual(prof_res.status_code, 200, prof_res.text)
            self.assertEqual(
                prof_res.json()["user"]["other_preferences"],
                ["minimum 4.5 stars", "4.5/5"],
            )
            self.ai.review_profile_wishes.assert_not_called()

            # Mixed rating + text wish strips rating clause and still validates
            # text with AI.
            self.ai.review_profile_wishes = Mock(return_value=["spicy food"])
            mixed_res = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    other_preferences=["minimum 4 .5 stars", "spicy food"],
                ),
            )
            self.assertEqual(mixed_res.status_code, 200, mixed_res.text)
            self.ai.review_profile_wishes.assert_called_once()
            self.assertEqual(
                self.ai.review_profile_wishes.call_args[0][0], ["spicy food"]
            )

            # Standalone rating phrases ('4.3 stars', '4.5+ rated') also bypass
            # AI validation cleanly.
            self.ai.review_profile_wishes = Mock(
                side_effect=AssertionError(
                    (
                        "review_profile_wishes should not run for standalone "
                        "rating wishes"
                    )
                )
            )
            bare_res = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    other_preferences=["4.3 stars"],
                ),
            )
            self.assertEqual(bare_res.status_code, 200, bare_res.text)
            self.assertEqual(
                self.ranking_calls[-1]["other_preferences"], ["4.3 stars"]
            )
            self.ai.review_profile_wishes.assert_not_called()

            # Out-of-bounds star rating (1..5) rejected before reaching AI or
            # BRNS.
            bad_res = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    other_preferences=["at least 6 stars"],
                ),
            )
            self.assertEqual(bad_res.status_code, 400, bad_res.text)
            self.assertIn("1 and 5 stars", bad_res.json()["detail"])
        finally:
            self.config["ai_bypass"] = True

        # Chatbot preserves non-rating wishes on rating updates and 'any
        # rating'.
        base = {
            "location": "Hougang 1",
            "locations": ["Hougang 1"],
            "mode": "walk",
            "max_distance_km": 1.8,
            "max_travel_minutes": None,
            "budget_per_person": 20.0,
            "dietary_requirements": [],
            "liked_cuisines": [],
            "disliked_cuisines": [],
            "other_preferences": ["spicy food"],
        }
        set_r = self.client.post(
            "/api/chat",
            json={
                "message": "minimum 4 .5 stars",
                "current_filters": base,
            },
        ).json()
        self.assertEqual(
            set_r["filters"]["other_preferences"],
            ["spicy food", "at least 4.5 stars"],
        )

        replace_r = self.client.post(
            "/api/chat",
            json={
                "message": "at least 4.0 stars",
                "current_filters": set_r["filters"],
            },
        ).json()
        self.assertEqual(
            replace_r["filters"]["other_preferences"],
            ["spicy food", "at least 4.0 stars"],
        )

        clear_r = self.client.post(
            "/api/chat",
            json={
                "message": "any rating",
                "current_filters": replace_r["filters"],
            },
        ).json()
        self.assertEqual(
            clear_r["filters"]["other_preferences"], ["spicy food"]
        )

        rated_r = self.client.post(
            "/api/chat",
            json={
                "message": "4.3+ rated",
                "current_filters": clear_r["filters"],
            },
        ).json()
        self.assertEqual(
            rated_r["filters"]["other_preferences"],
            ["spicy food", "at least 4.3 stars"],
        )

    def test_refresh_request_validation_and_normal_search_untouched(self):
        from BIS.classes.io.web.models.search.search_request_model import (
            SearchRequestModel,
        )

        base_payload = self.search_payload()
        validated_default = SearchRequestModel.model_validate(base_payload)
        self.assertEqual(validated_default.previous_restaurants, [])
        self.assertFalse(validated_default.strict_exclude)

        # Reject unknown top-level and nested fields in previous_restaurants.
        self.assertEqual(
            self.client.post(
                "/api/search", json=dict(base_payload, unknown_flag=True)
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/search",
                json=dict(
                    base_payload,
                    strict_exclude=True,
                    previous_restaurants=[
                        {"name": "Cafe", "extra_field": "bad"}
                    ],
                ),
            ).status_code,
            422,
        )

        # Enforce max_length bounds on list (200) and string fields.
        too_many = [
            {"google_place_id": f"p-{i}", "name": f"R{i}"} for i in range(201)
        ]
        self.assertEqual(
            self.client.post(
                "/api/search",
                json=dict(
                    base_payload,
                    strict_exclude=True,
                    previous_restaurants=too_many,
                ),
            ).status_code,
            422,
        )
        for bad_item in (
            {"google_place_id": "x" * 257, "name": "R"},
            {"name": "x" * 301},
            {"name": "R", "address": "x" * 501},
        ):
            self.assertEqual(
                self.client.post(
                    "/api/search",
                    json=dict(
                        base_payload,
                        strict_exclude=True,
                        previous_restaurants=[bad_item],
                    ),
                ).status_code,
                422,
            )

        # Normal search keeps legacy _brns.search call & response shape.
        headers, _ = self.account("normal.refresh.check@example.com")
        normal_res = self.client.post(
            "/api/search", json=base_payload, headers=headers
        )
        self.assertEqual(normal_res.status_code, 200, normal_res.text)
        normal_body = normal_res.json()
        self.assertTrue(normal_body["success"])
        self.assertNotIn("exhausted_previous", normal_body)
        self.assertNotIn("new_count", normal_body)

        # Chatbot /api/chat never adds strict_exclude/previous_restaurants.
        chat_res = self.client.post(
            "/api/chat",
            json={
                "message": "Japanese near Tampines under $20, 20 mins walk",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(chat_res.status_code, 200, chat_res.text)
        self.assertNotIn("strict_exclude", chat_res.json()["filters"])
        self.assertNotIn("previous_restaurants", chat_res.json()["filters"])

    def test_strict_refresh_single_cuisine_and_confirmation_skip(
        self,
    ):
        import json

        headers, user = self.account("refresh.single@example.com")
        seen_calls = []

        def refresh_brns_search(
            payload,
            previous_restaurants=(),
            user_id=None,
            max_matches=None,
            max_alternatives=None,
            strict_exclude=False,
        ):
            request = json.loads(payload)
            seen_calls.append(
                {
                    "request": request,
                    "previous_restaurants": list(previous_restaurants),
                    "user_id": user_id,
                    "max_matches": max_matches,
                    "max_alternatives": max_alternatives,
                    "strict_exclude": strict_exclude,
                }
            )
            results = {
                "matches": [
                    {
                        "restaurant": {
                            "google_place_id": "pid-seen",
                            "name": "Old By ID",
                            "address": "1 Old St",
                        }
                    },
                    {
                        "restaurant": {
                            "google_place_id": "",
                            "name": "Old By Name",
                            "address": "2 Old Ave",
                        }
                    },
                    {
                        "restaurant": {
                            "google_place_id": "pid-branch",
                            "name": "Branch Only Name",
                            "address": "99 New Rd",
                        }
                    },
                    {
                        "restaurant": {
                            "google_place_id": "pid-new-1",
                            "name": "Fresh Sushi",
                            "address": "10 Fresh Rd",
                        }
                    },
                ],
                "alternatives": [
                    {
                        "restaurant": {
                            "google_place_id": "pid-alt-1",
                            "name": "Fresh Ramen",
                            "address": "12 Fresh Rd",
                        }
                    },
                ],
                "hidden": 1,
                "exhausted_previous": False,
                "new_count": 3,
            }
            with self.scope.for_user(user_id):
                self.history.save_search_results(
                    request, results, "live-google"
                )
            return results

        orig_brns = self.application._brns
        self.application._brns = self._make_brns_gateway(refresh_brns_search)
        try:
            # Consume a confirmation token first to simulate stale cloned data.
            tok = self.client.post(
                "/api/search",
                json=dict(self.search_payload(), confirm_only=True),
                headers=headers,
            ).json()["confirmation_token"]
            self.assertEqual(
                self.client.post(
                    "/api/search",
                    json=dict(self.search_payload(), confirmation_token=tok),
                    headers=headers,
                ).status_code,
                200,
            )
            seen_calls.clear()

            previous = [
                {
                    "google_place_id": "pid-seen",
                    "name": "Old By ID Renamed",
                    "address": "Elsewhere",
                },
                {
                    "google_place_id": None,
                    "name": "old by name",
                    "address": "2 old ave",
                },
                {
                    "google_place_id": None,
                    "name": "Branch Only Name",
                    "address": "",
                },
            ]
            res = self.client.post(
                "/api/search",
                json=dict(
                    self.search_payload(),
                    confirm_only=True,
                    confirmation_token=tok,
                    previous_restaurants=previous,
                    strict_exclude=True,
                ),
                headers=headers,
            )
            self.assertEqual(res.status_code, 200, res.text)
            body = res.json()
            self.assertFalse(body["confirmation_required"])
            self.assertFalse(body["exhausted_previous"])
            self.assertEqual(body["new_count"], 3)
            self.assertEqual(body["cuisines_breakdown"], {"japanese": 3})
            self.assertEqual(
                [m["restaurant"]["google_place_id"] for m in body["matches"]],
                ["pid-branch", "pid-new-1"],
            )
            self.assertEqual(
                [
                    a["restaurant"]["google_place_id"]
                    for a in body["alternatives"]
                ],
                ["pid-alt-1"],
            )
            self.assertEqual(len(seen_calls), 1)
            self.assertTrue(seen_calls[0]["strict_exclude"])
            self.assertEqual(seen_calls[0]["user_id"], user["user_id"])
            self.assertEqual(seen_calls[0]["max_matches"], 20)
            self.assertEqual(seen_calls[0]["max_alternatives"], 20)
            self.assertEqual(
                seen_calls[0]["previous_restaurants"],
                [
                    {
                        "google_place_id": "pid-seen",
                        "name": "Old By ID Renamed",
                        "address": "Elsewhere",
                    },
                    {
                        "google_place_id": None,
                        "name": "old by name",
                        "address": "2 old ave",
                    },
                    {
                        "google_place_id": None,
                        "name": "Branch Only Name",
                        "address": "",
                    },
                ],
            )
            # History now has initial confirmed search + refresh search.
            hist_res = self.client.get("/api/history", headers=headers)
            self.assertEqual(len(hist_res.json()["history"]), 2)
        finally:
            self.application._brns = orig_brns

    def test_strict_refresh_multi_cuisine_forwarding_dedup_and_exhaustion(
        self,
    ):
        import json

        headers, _ = self.account("refresh.multi@example.com")
        sub_calls = []
        mode_box = {"mode": "partial"}

        def multi_brns_search(
            payload,
            previous_restaurants=(),
            user_id=None,
            max_matches=None,
            max_alternatives=None,
            strict_exclude=False,
        ):
            request = json.loads(payload)
            sub_calls.append(
                {
                    "cuisine": request["cuisine"],
                    "previous_restaurants": list(previous_restaurants),
                    "user_id": user_id,
                    "max_matches": max_matches,
                    "max_alternatives": max_alternatives,
                    "strict_exclude": strict_exclude,
                }
            )
            if mode_box["mode"] == "partial":
                if request["cuisine"] == "japanese":
                    return {
                        "matches": [],
                        "alternatives": [],
                        "hidden": 0,
                        "exhausted_previous": True,
                        "new_count": 0,
                    }
                return {
                    "matches": [
                        {
                            "restaurant": {
                                "google_place_id": "seen-k1",
                                "name": "Seen Kor",
                                "address": "1 K Rd",
                            }
                        },
                        {
                            "restaurant": {
                                "google_place_id": "new-k2",
                                "name": "New Kor",
                                "address": "2 K Rd",
                            }
                        },
                    ],
                    "alternatives": [],
                    "hidden": 1,
                    "exhausted_previous": False,
                    "new_count": 1,
                }
            if mode_box["mode"] == "all_empty":
                return {
                    "matches": [],
                    "alternatives": [],
                    "hidden": 0,
                    "exhausted_previous": True,
                    "new_count": 0,
                }
            if mode_box["mode"] == "all_runtime_no_open":
                raise RuntimeError("No restaurants found for this cuisine.")
            raise RuntimeError(
                "BRNS needs a configured AI provider to complete this search."
            )

        orig_brns = self.application._brns
        self.application._brns = self._make_brns_gateway(multi_brns_search)
        try:
            multi_payload = dict(
                self.search_payload(),
                cuisine="japanese, korean",
                liked_cuisines=["japanese", "korean"],
                previous_restaurants=[
                    {
                        "google_place_id": "seen-k1",
                        "name": "Seen Kor",
                        "address": "1 K Rd",
                    },
                ],
                strict_exclude=True,
            )

            # 1. Partial exhaustion: japanese empty, korean has 1 unseen.
            partial = self.client.post(
                "/api/search", json=multi_payload, headers=headers
            )
            self.assertEqual(partial.status_code, 200, partial.text)
            p_body = partial.json()
            self.assertFalse(p_body["exhausted_previous"])
            self.assertEqual(p_body["new_count"], 1)
            self.assertEqual(
                p_body["cuisines_breakdown"], {"japanese": 0, "korean": 1}
            )
            self.assertEqual(
                [
                    m["restaurant"]["google_place_id"]
                    for m in p_body["matches"]
                ],
                ["new-k2"],
            )
            self.assertEqual(len(sub_calls), 2)
            for call in sub_calls:
                self.assertTrue(call["strict_exclude"])
                self.assertIsNone(call["user_id"])
                self.assertEqual(call["max_matches"], 20)
                self.assertEqual(call["max_alternatives"], 20)
                self.assertEqual(len(call["previous_restaurants"]), 1)
            hist_partial = self.client.get("/api/history", headers=headers)
            self.assertEqual(len(hist_partial.json()["history"]), 1)

            # 2. All sub-cuisines exhausted cleanly via exhausted_previous.
            mode_box["mode"] = "all_empty"
            exhausted_res = self.client.post(
                "/api/search", json=multi_payload, headers=headers
            )
            self.assertEqual(
                exhausted_res.status_code, 200, exhausted_res.text
            )
            e_body = exhausted_res.json()
            self.assertTrue(e_body["success"])
            self.assertTrue(e_body["exhausted_previous"])
            self.assertEqual(e_body["new_count"], 0)
            self.assertEqual(e_body["matches"], [])
            self.assertEqual(e_body["alternatives"], [])
            self.assertEqual(
                e_body["message"],
                "No more new restaurants found matching your current filters. "
                "Reset seen results or adjust your filters to discover more.",
            )

            # 3. Sub-cuisines raising No-open RuntimeError returns exhausted.
            mode_box["mode"] = "all_runtime_no_open"
            exhausted_err_res = self.client.post(
                "/api/search", json=multi_payload, headers=headers
            )
            self.assertEqual(
                exhausted_err_res.status_code, 200, exhausted_err_res.text
            )
            ee_body = exhausted_err_res.json()
            self.assertTrue(ee_body["exhausted_previous"])
            self.assertEqual(ee_body["new_count"], 0)
            self.assertEqual(
                ee_body["message"],
                "No more new restaurants found matching your current filters. "
                "Reset seen results or adjust your filters to discover more.",
            )

            # 4. Real outage RuntimeError still surfaces as 503.
            mode_box["mode"] = "outage"
            outage_res = self.client.post(
                "/api/search", json=multi_payload, headers=headers
            )
            self.assertEqual(outage_res.status_code, 503)
        finally:
            self.application._brns = orig_brns

    def test_strict_refresh_single_cuisine_exhausted_and_alternatives_only(
        self,
    ):
        headers, _ = self.account("refresh.exhausted@example.com")
        mode_box = {"mode": "exhausted"}

        def single_brns_search(
            payload,
            previous_restaurants=(),
            user_id=None,
            max_matches=None,
            max_alternatives=None,
            strict_exclude=False,
        ):
            if mode_box["mode"] == "exhausted":
                return {
                    "matches": [],
                    "alternatives": [],
                    "hidden": 0,
                    "exhausted_previous": True,
                    "new_count": 0,
                }
            if mode_box["mode"] == "runtime_no_open":
                raise RuntimeError("No confirmed open restaurants found.")
            return {
                "matches": [],
                "alternatives": [
                    {
                        "restaurant": {
                            "google_place_id": "alt-only",
                            "name": "Alt Spot",
                            "address": "5 Alt Rd",
                        }
                    },
                ],
                "hidden": 0,
                "exhausted_previous": False,
                "new_count": 1,
            }

        orig_brns = self.application._brns
        self.application._brns = self._make_brns_gateway(single_brns_search)
        try:
            refresh_payload = dict(
                self.search_payload(),
                previous_restaurants=[
                    {
                        "google_place_id": "p1",
                        "name": "Seen 1",
                        "address": "1 Rd",
                    }
                ],
                strict_exclude=True,
            )

            res = self.client.post(
                "/api/search", json=refresh_payload, headers=headers
            )
            self.assertEqual(res.status_code, 200, res.text)
            body = res.json()
            self.assertTrue(body["success"])
            self.assertTrue(body["exhausted_previous"])
            self.assertEqual(body["new_count"], 0)
            self.assertEqual(body["matches"], [])
            self.assertEqual(body["alternatives"], [])
            self.assertEqual(
                body["message"],
                "No more new restaurants found matching your current filters. "
                "Reset seen results or adjust your filters to discover more.",
            )

            # Single-cuisine no-open RuntimeError also returns exhausted.
            mode_box["mode"] = "runtime_no_open"
            res_err = self.client.post(
                "/api/search", json=refresh_payload, headers=headers
            )
            self.assertEqual(res_err.status_code, 200, res_err.text)
            self.assertTrue(res_err.json()["exhausted_previous"])
            self.assertEqual(res_err.json()["new_count"], 0)
            self.assertEqual(
                res_err.json()["message"],
                "No more new restaurants found matching your current filters. "
                "Reset seen results or adjust your filters to discover more.",
            )

            # Normal search keeps original no-open msg without exhausted keys.
            normal_err = self.client.post(
                "/api/search", json=self.search_payload(), headers=headers
            )
            self.assertEqual(normal_err.status_code, 200, normal_err.text)
            self.assertNotIn("exhausted_previous", normal_err.json())
            self.assertNotIn("new_count", normal_err.json())
            self.assertIn(
                "No open restaurants found near this location right now.",
                normal_err.json()["message"],
            )

            # Alternatives-only refresh is NOT exhausted.
            mode_box["mode"] = "alt_only"
            alt_res = self.client.post(
                "/api/search", json=refresh_payload, headers=headers
            )
            self.assertEqual(alt_res.status_code, 200, alt_res.text)
            alt_body = alt_res.json()
            self.assertFalse(alt_body["exhausted_previous"])
            self.assertEqual(alt_body["new_count"], 1)
            self.assertNotIn("message", alt_body)
            self.assertEqual(len(alt_body["alternatives"]), 1)
        finally:
            self.application._brns = orig_brns

    def test_refresh_does_not_translate_provider_outage_into_exhaustion(self):
        headers, _ = self.account("refresh.outage@example.com")
        error_message = (
            "No restaurants found, or restaurant search is unavailable."
        )

        def unavailable(*_args, **_kwargs):
            raise RuntimeError(error_message)

        original = self.application._brns
        self.application._brns = self._make_brns_gateway(unavailable)
        try:
            for strict in (False, True):
                with self.subTest(strict_exclude=strict):
                    payload = self.search_payload()
                    if strict:
                        payload.update(
                            strict_exclude=True,
                            previous_restaurants=[
                                {
                                    "google_place_id": "seen-1",
                                    "name": "Seen Cafe",
                                    "address": "1 Road",
                                }
                            ],
                        )
                    response = self.client.post(
                        "/api/search", json=payload, headers=headers
                    )
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertIn(error_message, response.text)
                    self.assertNotIn("exhausted_previous", response.json())
        finally:
            self.application._brns = original

    def test_real_singapore_location_enforcement_and_suggest_endpoint(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from BIS.classes.io.gateways.location_gateway import LocationGateway

        headers, user = self.account("loc.guard@example.com")

        # 1. Profile rejects gibberish, invalid postals, and broad 'Singapore'.
        for bad_loc in (
            ["asdfghjkl"],
            ["qwrty"],
            ["12345"],
            ["999999"],
            ["Singapore"],
        ):
            res = self.client.post(
                "/api/profile",
                json={
                    "user_id": user["user_id"],
                    "username": user["username"],
                    "email": user["email"],
                    "location": bad_loc,
                    "max_distance_km": 2.0,
                    "max_travel_time_minutes": None,
                    "budget_per_person": 25.0,
                    "dietary_requirements": [],
                    "liked_cuisines": [],
                    "disliked_cuisines": [],
                    "other_preferences": [],
                },
                headers=headers,
            )
            self.assertEqual(
                res.status_code, 400, f"Expected 400 for {bad_loc}: {res.text}"
            )

        # 2. Search rejects gibberish in primary OR friend location rows.
        for payload in (
            dict(self.search_payload(), location="asdfghjkl", locations=[]),
            dict(
                self.search_payload(),
                location="Bugis",
                locations=["Bugis", "999999"],
            ),
        ):
            res = self.client.post(
                "/api/search", json=payload, headers=headers
            )
            self.assertEqual(res.status_code, 400, res.text)

        # 3. Chatbot rejects gibberish in onboarding, freeform updates,
        # Meet-in-the-Middle friend add, search confirmation, and save_profile.
        onb = self.client.post(
            "/api/chat",
            json={
                "message": "asdfghjkl",
                "onboarding": True,
                "awaiting_field": "location",
                "current_filters": {},
            },
            headers=headers,
        )
        self.assertEqual(onb.status_code, 200, onb.text)
        onb_body = onb.json()
        self.assertEqual(onb_body["action"], "onboarding")
        self.assertEqual(onb_body["awaiting_field"], "location")
        self.assertEqual(onb_body["onboarding_step"], 1)
        self.assertIn("Singapore location", onb_body["reply"])
        me_after_onb = self.client.get("/api/auth/me", headers=headers).json()
        self.assertEqual(me_after_onb["user"]["location"], [])

        chat_gibberish = self.client.post(
            "/api/chat",
            json={
                "message": "find halal food near asdfghjkl",
                "current_filters": {"locations": ["Bugis"], "mode": "walk"},
            },
            headers=headers,
        )
        self.assertEqual(chat_gibberish.status_code, 200, chat_gibberish.text)
        cg_body = chat_gibberish.json()
        self.assertEqual(cg_body["action"], "clarify")
        self.assertEqual(cg_body["filters"]["locations"], ["Bugis"])

        chat_friend_bad = self.client.post(
            "/api/chat",
            json={
                "message": "add second location, qwrty",
                "current_filters": {"locations": ["Bugis"], "mode": "walk"},
            },
            headers=headers,
        )
        self.assertEqual(chat_friend_bad.status_code, 200)
        self.assertEqual(chat_friend_bad.json()["action"], "clarify")
        self.assertEqual(
            chat_friend_bad.json()["filters"]["locations"], ["Bugis"]
        )

        chat_confirm_bad = self.client.post(
            "/api/chat",
            json={
                "message": "yes, search now",
                "awaiting_field": "confirm",
                "current_filters": {
                    "locations": ["asdfghjkl"],
                    "mode": "walk",
                    "max_travel_minutes": 15,
                    "budget_per_person": 20,
                },
            },
            headers=headers,
        )
        self.assertEqual(chat_confirm_bad.status_code, 200)
        self.assertEqual(chat_confirm_bad.json()["action"], "clarify")
        self.assertEqual(chat_confirm_bad.json()["awaiting_field"], "location")

        # 4. LocationGateway rejects Google country fallback without caching,
        # while accepting real establishment/POI matches even on partial_match.
        remembered = []
        cache = SimpleNamespace(
            lookup=lambda _q: None,
            remember=lambda queries, lat, lng: remembered.append(
                (list(queries), lat, lng)
            ),
        )
        real_gw = LocationGateway(
            self.application._logic, cache, "https://example.invalid/geocode"
        )
        with patch(
            "BIS.classes.io.gateways.location_gateway.requests.get",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "results": [
                        {
                            "formatted_address": "Singapore",
                            "types": ["country", "political"],
                            "partial_match": True,
                            "geometry": {
                                "location": {
                                    "lat": 1.352083,
                                    "lng": 103.819836,
                                }
                            },
                        }
                    ]
                },
            ),
        ):
            with self.assertRaises(ValueError):
                real_gw.resolve("hogwarts", "fake-key")
        self.assertEqual(remembered, [])

        with patch(
            "BIS.classes.io.gateways.location_gateway.requests.get",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "results": [
                        {
                            "formatted_address": (
                                "1 Sengkang Sq, Singapore 545078"
                            ),
                            "types": [
                                "establishment",
                                "point_of_interest",
                                "shopping_mall",
                            ],
                            "partial_match": True,
                            "geometry": {
                                "location": {"lat": 1.3924, "lng": 103.8954}
                            },
                        }
                    ]
                },
            ),
        ):
            ok_geo = real_gw.resolve("Compass One Mall", "fake-key")
        self.assertAlmostEqual(ok_geo["latitude"], 1.3924, places=3)
        self.assertEqual(len(remembered), 1)

        # 5. Suggest endpoint returns relevant Singapore locations.
        sug = self.client.get("/api/locations/suggest?q=Comp&limit=5")
        self.assertEqual(sug.status_code, 200, sug.text)
        labels = [item["label"] for item in sug.json().get("suggestions", [])]
        self.assertIn("Compass One", labels)
        self.assertNotIn("Singapore", labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
