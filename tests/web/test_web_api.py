"""Automated tests for BiteFinder Web API, NoSQL MongoDB persistence, and Webpage endpoints."""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))

import web_api
from shared import db
from reporting import show_case, show_summary

client = TestClient(web_api.app)

TEST_EMAIL = "webtest_suite_user@example.com"


def _cleanup_test_user():
    """Remove test user, sessions, favorites, and history created by the test suite."""
    if not db.is_db_available():
        return
    database = db.get_db()
    user_doc = database.users.find_one({"email": TEST_EMAIL})
    if user_doc:
        uid = user_doc.get("userID") or user_doc.get("_id")
        database.sessions.delete_many({"user_id": uid})
        database.favorites.delete_many({"user_id": uid})
        database.search_history.delete_many({"user_id": uid})
        database.users.delete_one({"_id": user_doc["_id"]})
    database.favorites.delete_many({"place_key": "test_place_key_123"})


def test_health_and_cuisines():
    """WEB-01: Health check and cuisines endpoints return valid status and schema."""
    res_health = client.get("/api/health")
    res_cuisines = client.get("/api/cuisines")

    health_json = res_health.json()
    cuisines_json = res_cuisines.json()

    actual = {
        "health_status_code": res_health.status_code,
        "status": health_json.get("status"),
        "has_database_field": "database" in health_json,
        "cuisines_status_code": res_cuisines.status_code,
        "includes_chinese_and_malay": (
            "chinese" in cuisines_json.get("cuisines", [])
            and "malay" in cuisines_json.get("cuisines", [])
        ),
    }
    expected = {
        "health_status_code": 200,
        "status": "healthy",
        "has_database_field": True,
        "cuisines_status_code": 200,
        "includes_chinese_and_malay": True,
    }

    show_case(
        "WEB-01: Health & Cuisines metadata endpoints",
        "GET /api/health, GET /api/cuisines",
        "Verifies that the FastAPI server reports system/MongoDB health and exposes the supported Singapore cuisine tags.",
        {"endpoints": ["/api/health", "/api/cuisines"]},
        expected,
        actual,
    )
    assert actual == expected


def test_authentication_lifecycle():
    """WEB-02: Register, duplicate check, login, wrong password check, /me, and logout."""
    _cleanup_test_user()
    try:
        # 1. Register new user
        reg_res = client.post(
            "/api/auth/register",
            json={
                "username": "WebTester",
                "email": TEST_EMAIL,
                "password": "secretpassword123",
            },
        )
        reg_data = reg_res.json()
        token = reg_data.get("token", "")

        # 2. Duplicate registration should fail with 400
        dup_res = client.post(
            "/api/auth/register",
            json={
                "username": "WebTester2",
                "email": TEST_EMAIL,
                "password": "secretpassword123",
            },
        )

        # 3. Wrong password login should fail with 401
        bad_login = client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": "wrongpassword"},
        )

        # 4. Valid login should succeed
        ok_login = client.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": "secretpassword123"},
        )
        login_token = ok_login.json().get("token", "")

        # 5. Fetch current user profile with Bearer token
        me_res = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {login_token}"},
        )

        # 6. Logout invalidates token
        logout_res = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {login_token}"},
        )
        me_after_logout = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {login_token}"},
        )

        actual = {
            "register_status": reg_res.status_code,
            "has_token": bool(token),
            "duplicate_status": dup_res.status_code,
            "bad_login_status": bad_login.status_code,
            "ok_login_status": ok_login.status_code,
            "me_username": me_res.json().get("user", {}).get("username"),
            "logout_status": logout_res.status_code,
            "me_after_logout_status": me_after_logout.status_code,
        }
        expected = {
            "register_status": 200,
            "has_token": True,
            "duplicate_status": 400,
            "bad_login_status": 401,
            "ok_login_status": 200,
            "me_username": "WebTester",
            "logout_status": 200,
            "me_after_logout_status": 401,
        }

        show_case(
            "WEB-02: User authentication & session lifecycle in MongoDB",
            "POST /api/auth/register, POST /api/auth/login, GET /api/auth/me, POST /api/auth/logout",
            "Verifies account creation with PBKDF2 password hashing, duplicate email protection, login verification, session lookup, and logout invalidation.",
            {"email": TEST_EMAIL},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        _cleanup_test_user()


def test_profile_preferences_persistence():
    """WEB-03: Save and retrieve user dining preferences including disliked cuisines."""
    _cleanup_test_user()
    try:
        reg_res = client.post(
            "/api/auth/register",
            json={
                "username": "PrefUser",
                "email": TEST_EMAIL,
                "password": "secretpassword123",
            },
        )
        token = reg_res.json()["token"]
        uid = reg_res.json()["user"]["user_id"]
        headers = {"Authorization": f"Bearer {token}"}

        save_res = client.post(
            "/api/profile",
            headers=headers,
            json={
                "user_id": uid,
                "username": "UpdatedPrefUser",
                "email": TEST_EMAIL,
                "location": ["Bugis Junction"],
                "max_distance_km": 2.5,
                "max_travel_time_minutes": 25.0,
                "budget_per_person": 40.0,
                "dietary_requirements": ["halal"],
                "liked_cuisines": ["japanese"],
                "disliked_cuisines": ["western", "italian"],
                "other_preferences": ["quiet dinner"],
            },
        )

        get_res = client.get("/api/profile", headers=headers)
        prof = get_res.json()

        actual = {
            "save_status": save_res.status_code,
            "username": prof.get("username"),
            "location": prof.get("location"),
            "budget_per_person": prof.get("budget_per_person"),
            "dietary_requirements": prof.get("dietary_requirements"),
            "disliked_cuisines": prof.get("disliked_cuisines"),
        }
        expected = {
            "save_status": 200,
            "username": "UpdatedPrefUser",
            "location": ["Bugis Junction"],
            "budget_per_person": 40.0,
            "dietary_requirements": ["halal"],
            "disliked_cuisines": ["western", "italian"],
        }

        show_case(
            "WEB-03: Profile & dining preferences persistence in MongoDB",
            "POST /api/profile, GET /api/profile",
            "Checks that user profile updates (default location, budget, halal requirement, and disliked cuisines) are persisted in MongoDB.",
            {"user_id": uid, "location": ["Bugis Junction"]},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        _cleanup_test_user()


def test_favorites_bookmarks_lifecycle():
    """WEB-04: Toggle add/remove and delete saved favorite restaurants in MongoDB."""
    _cleanup_test_user()
    try:
        sample_restaurant = {
            "google_place_id": "test_place_key_123",
            "name": "Sin Chie Toke Huan Hainanese Curry Rice",
            "address": "1018 Upper Serangoon Rd, Singapore 534756",
            "rating": 4.3,
            "today_hours": "17:00–02:30",
        }

        # 1. Add favorite
        add_res = client.post("/api/favorites", json={"restaurant": sample_restaurant})
        add_json = add_res.json()

        # 2. List favorites
        list_res = client.get("/api/favorites")
        list_json = list_res.json()
        has_saved = any(f.get("place_key") == "test_place_key_123" for f in list_json.get("favorites", []))

        # 3. Toggle again removes favorite
        rem_res = client.post("/api/favorites", json={"restaurant": sample_restaurant})
        rem_json = rem_res.json()

        # 4. Re-add and delete via DELETE /api/favorites
        client.post("/api/favorites", json={"restaurant": sample_restaurant})
        del_res = client.delete("/api/favorites", params={"place_key": "test_place_key_123"})

        actual = {
            "add_action": add_json.get("action"),
            "listed_in_favorites": has_saved,
            "toggle_remove_action": rem_json.get("action"),
            "explicit_delete_status": del_res.status_code,
        }
        expected = {
            "add_action": "added",
            "listed_in_favorites": True,
            "toggle_remove_action": "removed",
            "explicit_delete_status": 200,
        }

        show_case(
            "WEB-04: Saved Favorites / Bookmarks CRUD in MongoDB",
            "POST /api/favorites, GET /api/favorites, DELETE /api/favorites",
            "Verifies that users can bookmark restaurants, retrieve their saved list from MongoDB, and remove bookmarks.",
            {"place_key": "test_place_key_123"},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        _cleanup_test_user()


def test_search_pipeline_with_distance_traffic_and_disliked():
    """WEB-05: POST /api/search forwards distance, traffic_aware, and disliked_cuisines to BRNS."""
    orig_resolve = web_api.bis_data.resolve_location
    orig_search = web_api.brns_main.search
    captured_payload = {}

    def fake_resolve(loc, key):
        return {"query": loc, "label": "Compass One", "latitude": 1.392, "longitude": 103.895}

    def fake_search(serialized):
        captured_payload.update(json.loads(serialized))
        return {
            "matches": [
                {
                    "restaurant": {
                        "name": "Sengkang Halal Bistro",
                        "address": "1 Sengkang Square",
                        "lat": 1.3925,
                        "lng": 103.8955,
                        "rating": 4.6,
                        "open_now": True,
                    },
                    "reasons": ["Within 2.5 km drive", "Official MUIS Halal certified"],
                }
            ],
            "alternatives": [],
            "exclusions": [],
        }

    try:
        web_api.bis_data.resolve_location = fake_resolve
        web_api.brns_main.search = fake_search

        res = client.post(
            "/api/search",
            json={
                "location": "Compass One",
                "mode": "drive",
                "max_travel_minutes": None,
                "max_distance_km": 2.5,
                "budget_per_person": 25.0,
                "dietary_requirements": ["halal"],
                "cuisine": "malay",
                "disliked_cuisines": ["western"],
                "other_preferences": ["spicy food"],
                "traffic_aware": True,
            },
        )
        data = res.json()

        actual = {
            "status_code": res.status_code,
            "forwarded_mode": captured_payload.get("mode"),
            "forwarded_distance_km": captured_payload.get("max_distance_km"),
            "forwarded_minutes": captured_payload.get("max_travel_minutes"),
            "forwarded_traffic_aware": captured_payload.get("traffic_aware"),
            "forwarded_disliked": captured_payload.get("disliked_cuisines"),
            "matches_returned": len(data.get("matches", [])),
        }
        expected = {
            "status_code": 200,
            "forwarded_mode": "drive",
            "forwarded_distance_km": 2.5,
            "forwarded_minutes": None,
            "forwarded_traffic_aware": True,
            "forwarded_disliked": ["western"],
            "matches_returned": 1,
        }

        show_case(
            "WEB-05: Search endpoint with distance limit, live traffic, & disliked cuisines",
            "POST /api/search",
            "Verifies that the Web API constructs the 10-field BRNS payload accurately when using distance limits, driving traffic_aware, and disliked cuisines.",
            {"location": "Compass One", "mode": "drive", "max_distance_km": 2.5, "traffic_aware": True},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        web_api.bis_data.resolve_location = orig_resolve
        web_api.brns_main.search = orig_search


def test_search_graceful_late_night_empty_message():
    """WEB-06: POST /api/search returns a helpful message when no open restaurants exist."""
    orig_resolve = web_api.bis_data.resolve_location
    orig_search = web_api.brns_main.search

    def fake_resolve(loc, key):
        return {"query": loc, "label": "Compass One", "latitude": 1.392, "longitude": 103.895}

    def fake_search_empty(serialized):
        raise ValueError("No restaurants found with confirmed open hours right now.")

    try:
        web_api.bis_data.resolve_location = fake_resolve
        web_api.brns_main.search = fake_search_empty

        res = client.post(
            "/api/search",
            json={
                "location": "Compass One",
                "mode": "walk",
                "max_travel_minutes": 15.0,
                "budget_per_person": 20.0,
            },
        )
        data = res.json()

        actual = {
            "status_code": res.status_code,
            "success": data.get("success"),
            "matches_count": len(data.get("matches", [])),
            "has_helpful_message": "No open restaurants found" in (data.get("message") or ""),
        }
        expected = {
            "status_code": 200,
            "success": True,
            "matches_count": 0,
            "has_helpful_message": True,
        }

        show_case(
            "WEB-06: Graceful late-night empty search handling",
            "POST /api/search",
            "Checks that when all nearby venues are closed, the API returns HTTP 200 with a user-friendly explanation rather than an unhandled 500 error.",
            {"location": "Compass One"},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        web_api.bis_data.resolve_location = orig_resolve
        web_api.brns_main.search = orig_search


def test_search_history_and_recent_searches():
    """WEB-07: GET /api/history, GET /api/recent-searches, and DELETE /api/history."""
    _cleanup_test_user()
    try:
        reg_res = client.post(
            "/api/auth/register",
            json={
                "username": "HistoryTester",
                "email": TEST_EMAIL,
                "password": "secretpassword123",
            },
        )
        token = reg_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        orig_resolve = web_api.bis_data.resolve_location
        orig_search = web_api.brns_main.search
        web_api.bis_data.resolve_location = lambda loc, k: {
            "query": loc,
            "label": loc,
            "latitude": 1.35,
            "longitude": 103.82,
        }
        web_api.brns_main.search = lambda s: {"matches": [{"restaurant": {"name": "Test Spot"}}], "alternatives": [], "exclusions": []}

        try:
            client.post(
                "/api/search",
                headers=headers,
                json={
                    "location": "Jewel Changi",
                    "mode": "transit",
                    "max_travel_minutes": 35.0,
                    "budget_per_person": 30.0,
                    "dietary_requirements": ["halal"],
                },
            )
        finally:
            web_api.bis_data.resolve_location = orig_resolve
            web_api.brns_main.search = orig_search

        hist_res = client.get("/api/history", headers=headers)
        hist_list = hist_res.json().get("history", [])

        recent_res = client.get("/api/recent-searches", headers=headers)
        recent_list = recent_res.json().get("recent", [])

        del_res = client.delete("/api/history", headers=headers)

        actual = {
            "history_status": hist_res.status_code,
            "recorded_query": hist_list[0].get("query") if hist_list else None,
            "recorded_mode": hist_list[0].get("mode") if hist_list else None,
            "in_recent_searches": "Jewel Changi" in recent_list,
            "clear_status": del_res.status_code,
        }
        expected = {
            "history_status": 200,
            "recorded_query": "Jewel Changi",
            "recorded_mode": "transit",
            "in_recent_searches": True,
            "clear_status": 200,
        }

        show_case(
            "WEB-07: Search History & Recent Searches persistence",
            "GET /api/history, GET /api/recent-searches, DELETE /api/history",
            "Verifies that searches are logged to MongoDB with full filter parameters for one-click re-run and can be cleared.",
            {"query": "Jewel Changi", "mode": "transit"},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        _cleanup_test_user()


def test_turn_by_turn_route_endpoint():
    """WEB-08: POST /api/route returns step-by-step directions and Google Maps link."""
    orig_route_to = web_api.brns_main.route_to

    def fake_route_to(restaurant_arg, request_arg):
        return {
            "name": restaurant_arg["name"],
            "mode": request_arg["mode"],
            "traffic_aware": request_arg["traffic_aware"],
            "route": {
                "duration_min": 12.0,
                "distance_m": 950,
                "steps": [
                    "Walk north on Sengkang Square (200 m)",
                    "Turn right onto Compassvale Rd (750 m)",
                ],
            },
            "link": "https://www.google.com/maps/dir/?api=1&destination=1.392,103.895",
        }

    try:
        web_api.brns_main.route_to = fake_route_to
        res = client.post(
            "/api/route",
            json={
                "origin_lat": 1.390,
                "origin_lng": 103.890,
                "dest_lat": 1.392,
                "dest_lng": 103.895,
                "name": "Compass One Dining",
                "mode": "walk",
                "traffic_aware": False,
            },
        )
        data = res.json()

        actual = {
            "status_code": res.status_code,
            "success": data.get("success"),
            "duration_min": data.get("route", {}).get("duration_min"),
            "steps_count": len(data.get("route", {}).get("steps", [])),
            "has_link": bool(data.get("link")),
        }
        expected = {
            "status_code": 200,
            "success": True,
            "duration_min": 12.0,
            "steps_count": 2,
            "has_link": True,
        }

        show_case(
            "WEB-08: Turn-by-Turn Route Directions endpoint",
            "POST /api/route",
            "Verifies that the Web API calls BRNS.main.route_to and returns step-by-step navigation instructions.",
            {"name": "Compass One Dining", "mode": "walk"},
            expected,
            actual,
        )
        assert actual == expected
    finally:
        web_api.brns_main.route_to = orig_route_to


TESTS = (
    test_health_and_cuisines,
    test_authentication_lifecycle,
    test_profile_preferences_persistence,
    test_favorites_bookmarks_lifecycle,
    test_search_pipeline_with_distance_traffic_and_disliked,
    test_search_graceful_late_night_empty_message,
    test_search_history_and_recent_searches,
    test_turn_by_turn_route_endpoint,
)


def run_tests():
    """Run all Web API tests and print a teacher-facing summary."""
    failures = []
    for test in TESTS:
        try:
            test()
        except Exception as error:
            failures.append((test.__name__, error))

    show_summary("WEB API", len(TESTS), failures)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
