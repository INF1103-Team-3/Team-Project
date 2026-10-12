"""
Direct unit tests for BiteFinder data managers.

These tests check persistence, loading, filtering, corruption handling,
saved user/profile data, restaurant storage, and search history.

They use temporary files so the real project data is not modified.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


# =========================================================
# IMPORT SETUP
# =========================================================

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

from BIS import data_manager as bis_data
from BIS.sources.profile_schema import empty_preferences
from BRNS import data_manager as brns_data


# =========================================================
# TEST DATA HELPERS
# =========================================================

def make_user(
    user_id="user-1",
    email="test@example.com",
    verified=True,
):
    """
    Create a valid BIS user record for testing.
    """

    return {
        "userID": user_id,
        "email": email,
        "email_verified": verified,
        "username": "Tester",
        "preferences": empty_preferences(),
    }


def make_candidate(**overrides):
    """
    Create one valid BRNS restaurant candidate.

    Individual tests can override only the field they need.
    """

    candidate = {
        "google_place_id": "place-1",
        "name": "Test Restaurant",
        "address": "1 Test Street Singapore 828761",
        "postal_code": None,
        "number": "+65 6123 4567",

        "cuisines": [
            "japanese"
        ],

        "dietary_requirements": [],

        "halal_hint": False,
        "halal_certification": "none",
        "muis_check": None,

        "rating": 4.5,
        "rating_count": 100,

        "price_start": 10,
        "price_end": 20,

        "opening_hours": {
            "monday": [
                ["0900", "1800"]
            ]
        },

        "wheelchair_accessible": True,
    }

    candidate.update(overrides)

    return candidate


# =========================================================
# BIS DATA MANAGER TESTS
# =========================================================

class TestBISDataManager(unittest.TestCase):

    # -----------------------------------------------------
    # TEST 1
    # Search request should serialize into valid JSON.
    # -----------------------------------------------------
    def test_serialize_search_request_round_trips_json(self):

        request = {
            "cuisine": "japanese",
            "budget": 20
        }

        payload = bis_data.serialize_search_request(
            request
        )

        self.assertEqual(
            json.loads(payload),
            request
        )


    # -----------------------------------------------------
    # TEST 2
    # Missing saved-data file should return an empty object
    # instead of crashing.
    # -----------------------------------------------------
    def test_read_json_missing_file_returns_empty_object(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "missing.json"

            result = bis_data._read_json(path)

        self.assertEqual(
            result,
            {}
        )


    # -----------------------------------------------------
    # TEST 3
    # Corrupt JSON should produce a controlled error.
    # -----------------------------------------------------
    def test_read_json_corrupt_file_raises_runtime_error(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "bad.json"

            path.write_text(
                "{not valid json",
                encoding="utf-8"
            )

            with self.assertRaises(RuntimeError):

                bis_data._read_json(path)


    # -----------------------------------------------------
    # TEST 4
    # BIS saved data must contain a JSON object, not a list.
    # -----------------------------------------------------
    def test_read_json_rejects_non_object_json(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "list.json"

            path.write_text(
                "[]",
                encoding="utf-8"
            )

            with self.assertRaises(RuntimeError):

                bis_data._read_json(path)


    # -----------------------------------------------------
    # TEST 5
    # A valid user can be saved and loaded again.
    # -----------------------------------------------------
    def test_save_and_load_user_record(self):

        with tempfile.TemporaryDirectory() as folder:

            users_file = Path(folder) / "users.json"

            with patch.object(
                bis_data,
                "USERS_FILE",
                users_file
            ):

                saved = bis_data.save(
                    make_user()
                )

                records = bis_data.load()

        self.assertEqual(
            saved["email"],
            "test@example.com"
        )

        self.assertEqual(
            len(records),
            1
        )

        self.assertEqual(
            records[0]["userID"],
            "user-1"
        )


    # -----------------------------------------------------
    # TEST 6
    # query() should filter stored users correctly.
    # -----------------------------------------------------
    def test_query_filters_saved_users(self):

        with tempfile.TemporaryDirectory() as folder:

            users_file = Path(folder) / "users.json"

            with patch.object(
                bis_data,
                "USERS_FILE",
                users_file
            ):

                bis_data.save(
                    make_user(
                        "u1",
                        "one@example.com"
                    )
                )

                bis_data.save(
                    make_user(
                        "u2",
                        "two@example.com"
                    )
                )

                result = bis_data.query(
                    lambda user:
                    user["email"] == "two@example.com"
                )

        self.assertEqual(
            len(result),
            1
        )

        self.assertEqual(
            result[0]["userID"],
            "u2"
        )


    # -----------------------------------------------------
    # TEST 7
    # Two different users cannot use the same email.
    # -----------------------------------------------------
    def test_save_rejects_duplicate_email_for_different_user(self):

        with tempfile.TemporaryDirectory() as folder:

            users_file = Path(folder) / "users.json"

            with patch.object(
                bis_data,
                "USERS_FILE",
                users_file
            ):

                bis_data.save(
                    make_user(
                        "u1",
                        "same@example.com"
                    )
                )

                with self.assertRaises(ValueError):

                    bis_data.save(
                        make_user(
                            "u2",
                            "same@example.com"
                        )
                    )


    # -----------------------------------------------------
    # TEST 8
    # Internal BIS state can be saved, loaded, and removed.
    # -----------------------------------------------------
    def test_state_can_be_saved_loaded_and_removed(self):

        with tempfile.TemporaryDirectory() as folder:

            state_file = Path(folder) / "state.json"

            with patch.object(
                bis_data,
                "STATE_FILE",
                state_file
            ):

                bis_data.set_state(
                    "signup",
                    "u1",
                    {
                        "step": 2
                    }
                )

                result = bis_data.get_state(
                    "signup",
                    "u1"
                )

                self.assertEqual(
                    result,
                    {
                        "step": 2
                    }
                )

                # Setting None removes the saved state.
                bis_data.set_state(
                    "signup",
                    "u1",
                    None
                )

                self.assertIsNone(
                    bis_data.get_state(
                        "signup",
                        "u1"
                    )
                )


    # -----------------------------------------------------
    # TEST 9
    # An unverified user cannot change preferences unless
    # SMTP bypass is enabled.
    # -----------------------------------------------------
    def test_save_preferences_requires_verification_without_bypass(self):

        with tempfile.TemporaryDirectory() as folder:

            users_file = Path(folder) / "users.json"

            user = make_user(
                verified=False
            )

            with patch.object(
                bis_data,
                "USERS_FILE",
                users_file
            ):

                bis_data.save(user)

                with self.assertRaises(ValueError):

                    bis_data.save_preferences(
                        "user-1",
                        empty_preferences(),
                        {
                            "smtp_bypass": False
                        }
                    )


    # -----------------------------------------------------
    # TEST 10
    # Direct Singapore coordinates can be resolved without
    # requiring Google Maps.
    # -----------------------------------------------------
    def test_resolve_location_accepts_direct_singapore_coordinates(self):

        result = bis_data.resolve_location(
            "1.3521, 103.8198",
            api_key=""
        )

        self.assertEqual(
            result["latitude"],
            1.3521
        )

        self.assertEqual(
            result["longitude"],
            103.8198
        )


    # -----------------------------------------------------
    # TEST 11
    # Cached coordinates outside Singapore must not be used.
    # -----------------------------------------------------
    def test_lookup_cached_location_rejects_overseas_cached_point(self):

        with patch.object(
            bis_data.geocode_cache,
            "lookup",
            return_value=(
                40.7128,
                -74.0060
            )
        ):

            result = bis_data.lookup_cached_location(
                "test"
            )

        self.assertIsNone(result)


# =========================================================
# BRNS DATA MANAGER TESTS
# =========================================================

class TestBRNSDataManager(unittest.TestCase):

    # -----------------------------------------------------
    # TEST 12
    # Missing restaurant database should safely return [].
    # -----------------------------------------------------
    def test_load_restaurants_missing_file_returns_empty_list(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "missing.json"

            result = brns_data.load_restaurants(
                path
            )

        self.assertEqual(
            result,
            []
        )


    # -----------------------------------------------------
    # TEST 13
    # Corrupt restaurant JSON should safely return [].
    # -----------------------------------------------------
    def test_load_restaurants_corrupt_file_returns_empty_list(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "bad.json"

            path.write_text(
                "not json",
                encoding="utf-8"
            )

            result = brns_data.load_restaurants(
                path
            )

        self.assertEqual(
            result,
            []
        )


    # -----------------------------------------------------
    # TEST 14
    # Postal code can be extracted from a Singapore address.
    # -----------------------------------------------------
    def test_restaurant_record_extracts_postal_code_from_address(self):

        record = brns_data._restaurant_record(
            make_candidate(
                postal_code=None
            )
        )

        self.assertEqual(
            record["postal_code"],
            "828761"
        )


    # -----------------------------------------------------
    # TEST 15
    # Restaurant storage requires both a Google place ID
    # and a restaurant name.
    # -----------------------------------------------------
    def test_restaurant_record_requires_place_id_and_name(self):

        missing_id = brns_data._restaurant_record(
            make_candidate(
                google_place_id=None
            )
        )

        missing_name = brns_data._restaurant_record(
            make_candidate(
                name=""
            )
        )

        self.assertIsNone(
            missing_id
        )

        self.assertIsNone(
            missing_name
        )


    # -----------------------------------------------------
    # TEST 16
    # Only MUIS-verified certification should be stored
    # as officially halal.
    # -----------------------------------------------------
    def test_restaurant_record_marks_only_verified_muis_as_official(self):

        verified = brns_data._restaurant_record(
            make_candidate(
                dietary_requirements=[
                    "halal"
                ],

                halal_certification="official",

                muis_check={
                    "status": "verified"
                },
            )
        )

        unverified = brns_data._restaurant_record(
            make_candidate(
                dietary_requirements=[
                    "halal"
                ],

                halal_certification="official",

                muis_check={
                    "status": "not_found"
                },
            )
        )

        self.assertEqual(
            verified["halal_certification"],
            "official"
        )

        self.assertEqual(
            unverified["halal_certification"],
            "unofficial"
        )


    # -----------------------------------------------------
    # TEST 17
    # Restaurant data can be saved and loaded again.
    # -----------------------------------------------------
    def test_save_restaurants_and_load_restaurants_round_trip(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "restaurants.json"

            saved = brns_data.save_restaurants(
                [
                    make_candidate()
                ],
                path
            )

            loaded = brns_data.load_restaurants(
                path
            )

        self.assertEqual(
            saved,
            1
        )

        self.assertEqual(
            len(loaded),
            1
        )

        self.assertEqual(
            loaded[0]["google_place_id"],
            "place-1"
        )


    # -----------------------------------------------------
    # TEST 18
    # Updating an existing restaurant should not erase
    # previously known values when the new value is None.
    # -----------------------------------------------------
    def test_save_restaurants_upserts_without_erasing_known_value(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "restaurants.json"

            brns_data.save_restaurants(
                [
                    make_candidate(
                        price_start=10
                    )
                ],
                path
            )

            brns_data.save_restaurants(
                [
                    make_candidate(
                        price_start=None,
                        rating=4.8
                    )
                ],
                path
            )

            loaded = brns_data.load_restaurants(
                path
            )

        # Still only one restaurant.
        self.assertEqual(
            len(loaded),
            1
        )

        # Old known price remains.
        self.assertEqual(
            loaded[0]["avg_price_low_sgd"],
            10
        )

        # New rating was updated.
        self.assertEqual(
            loaded[0]["g_rating"],
            "4.8"
        )


    # -----------------------------------------------------
    # TEST 19
    # Invalid candidates should be skipped safely.
    # -----------------------------------------------------
    def test_save_restaurants_skips_invalid_candidates(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "restaurants.json"

            saved = brns_data.save_restaurants(
                [
                    "not a dictionary",

                    {
                        "name":
                        "Missing place ID"
                    },

                    make_candidate(),
                ],
                path
            )

            loaded = brns_data.load_restaurants(
                path
            )

        self.assertEqual(
            saved,
            1
        )

        self.assertEqual(
            len(loaded),
            1
        )


    # -----------------------------------------------------
    # TEST 20
    # Missing/corrupt history should return an empty list.
    # -----------------------------------------------------
    def test_load_history_missing_or_corrupt_file_returns_empty_list(self):

        with tempfile.TemporaryDirectory() as folder:

            missing = Path(folder) / "missing.json"

            corrupt = Path(folder) / "corrupt.json"

            corrupt.write_text(
                "broken",
                encoding="utf-8"
            )

            self.assertEqual(
                brns_data.load_history(
                    missing
                ),
                []
            )

            self.assertEqual(
                brns_data.load_history(
                    corrupt
                ),
                []
            )


    # -----------------------------------------------------
    # TEST 21
    # Search history should append entries instead of
    # overwriting the previous one.
    # -----------------------------------------------------
    def test_save_history_appends_entries(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "history.json"

            self.assertTrue(
                brns_data.save_history(
                    {
                        "id": 1
                    },
                    path
                )
            )

            self.assertTrue(
                brns_data.save_history(
                    {
                        "id": 2
                    },
                    path
                )
            )

            history = brns_data.load_history(
                path
            )

        self.assertEqual(
            history,
            [
                {
                    "id": 1
                },
                {
                    "id": 2
                },
            ]
        )


    # -----------------------------------------------------
    # TEST 22
    # Live Google search history should save Google place
    # IDs rather than restaurant names.
    # -----------------------------------------------------
    def test_save_search_results_live_google_stores_place_ids(self):

        request = {
            "origin": {
                "latitude": 1.35,
                "longitude": 103.82
            },

            "mode": "walk",

            "cuisine": "japanese",
        }

        results = {
            "matches": [
                {
                    "restaurant": {
                        "name": "A",
                        "google_place_id": "pid-a"
                    }
                },

                {
                    "restaurant": {
                        "name": "B",
                        "google_place_id": None
                    }
                },
            ]
        }

        with patch.object(
            brns_data,
            "save_history",
            return_value=True
        ) as save:

            result = brns_data.save_search_results(
                request,
                results,
                "live-google"
            )

        self.assertTrue(result)

        entry = save.call_args.args[0]

        self.assertEqual(
            entry["top_match_place_ids"],
            [
                "pid-a"
            ]
        )

        self.assertNotIn(
            "top_matches",
            entry
        )


    # -----------------------------------------------------
    # TEST 23
    # Offline history should store restaurant names instead
    # of Google place IDs.
    # -----------------------------------------------------
    def test_save_search_results_offline_stores_restaurant_names(self):

        request = {
            "origin": {
                "latitude": 1.35,
                "longitude": 103.82
            },

            "mode": "walk",

            "cuisine": "japanese",
        }

        results = {
            "matches": [
                {
                    "restaurant": {
                        "name": "A"
                    }
                },

                {
                    "restaurant": {
                        "name": "B"
                    }
                },
            ]
        }

        with patch.object(
            brns_data,
            "save_history",
            return_value=True
        ) as save:

            result = brns_data.save_search_results(
                request,
                results,
                "offline"
            )

        self.assertTrue(result)

        entry = save.call_args.args[0]

        self.assertEqual(
            entry["top_matches"],
            [
                "A",
                "B"
            ]
        )

        self.assertNotIn(
            "top_match_place_ids",
            entry
        )


# =========================================================
# RUN TESTS
# =========================================================

if __name__ == "__main__":
    unittest.main()