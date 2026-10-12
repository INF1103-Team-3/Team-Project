"""
Direct unit tests for BRNS logic_manager.py

These tests check individual BRNS business rules in isolation.
They do not require Docker, Google APIs, BIS, BRC, or live AI calls.
"""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path


# =========================================================
# IMPORT SETUP
# =========================================================

# Find the root Team-Project folder.
ROOT = Path(__file__).resolve().parents[1]

# Allow Python to import project files.
sys.path.insert(0, str(ROOT))

# Import the real BRNS logic we want to test.
from BRNS import logic_manager as brns_logic


# =========================================================
# TEST DATA HELPERS
# =========================================================

def make_request(**overrides):
    """
    Create a complete sample BRNS search request.

    Individual tests can override only the field they care about.
    """

    request = {
        "cuisine": "none",
        "disliked_cuisines": [],
        "dietary_requirements": [],
        "budget_per_person": 20,
        "other_preferences": [],
        "mode": "walk",
        "max_travel_minutes": 30,
        "max_distance_km": None,
        "traffic_aware": False,
    }

    request.update(overrides)

    return request


def make_restaurant(**overrides):
    """
    Create a complete sample restaurant.

    Individual tests can change only the restaurant property
    they want to test.
    """

    restaurant = {
        "name": "Test Cafe",
        "address": "1 Test Street",
        "source": "offline restaurants",

        "cuisines": ["japanese"],
        "dietary_requirements": [],
        "halal_status": "unverified",

        "avg_price": 12,
        "price_start": None,
        "price_end": None,

        "rating": 4.5,
        "rating_count": 200,

        "walk_minutes": 10,
        "walk_meters": 800,
        "walk_source": "route",

        "drive_minutes": None,
        "drive_meters": None,
        "drive_source": None,

        "transit_minutes": None,
        "transit_meters": None,
        "transit_source": None,

        "spicy_options": False,
    }

    restaurant.update(overrides)

    return restaurant


# =========================================================
# BRNS LOGIC UNIT TESTS
# =========================================================

class TestBRNSLogic(unittest.TestCase):

    # -----------------------------------------------------
    # TEST 1
    # BRNS should recognise an explicit minimum rating.
    # -----------------------------------------------------
    def test_minimum_rating_reads_explicit_floor(self):

        result = brns_logic.minimum_rating([
            "at least 4.5 stars"
        ])

        self.assertEqual(
            result,
            4.5
        )


    # -----------------------------------------------------
    # TEST 2
    # If multiple minimum ratings are mentioned,
    # BRNS should use the highest requirement.
    # -----------------------------------------------------
    def test_minimum_rating_returns_highest_floor(self):

        result = brns_logic.minimum_rating([
            "minimum 4 stars",
            "at least 4.5 stars",
        ])

        self.assertEqual(
            result,
            4.5
        )


    # -----------------------------------------------------
    # TEST 3
    # BRNS should recognise a softer rating preference.
    # -----------------------------------------------------
    def test_preferred_rating_reads_soft_rating(self):

        result = brns_logic.preferred_rating([
            "rated 4.2 stars"
        ])

        self.assertEqual(
            result,
            4.2
        )


    # -----------------------------------------------------
    # TEST 4
    # BRNS should detect hard cuisine wording such as
    # "Japanese only".
    # -----------------------------------------------------
    def test_hard_required_cuisines_detects_only_requirement(self):

        result = brns_logic.hard_required_cuisines([
            "Japanese only"
        ])

        self.assertEqual(
            result,
            ["japanese"]
        )


    # -----------------------------------------------------
    # TEST 5
    # BRNS should distinguish between hard and soft
    # preference wording.
    # -----------------------------------------------------
    def test_has_hard_preferences_detects_hard_language(self):

        self.assertTrue(
            brns_logic.has_hard_preferences([
                "must be spicy"
            ])
        )

        self.assertFalse(
            brns_logic.has_hard_preferences([
                "prefer spicy food"
            ])
        )


    # -----------------------------------------------------
    # TEST 6
    # Restaurants with very few reviews should have
    # less confidence than equally rated restaurants
    # with many reviews.
    # -----------------------------------------------------
    def test_confidence_adjusted_rating_penalises_small_review_count(self):

        low_reviews = brns_logic.confidence_adjusted_rating(
            5.0,
            5
        )

        many_reviews = brns_logic.confidence_adjusted_rating(
            5.0,
            500
        )

        self.assertLess(
            low_reviews,
            many_reviews
        )


    # -----------------------------------------------------
    # TEST 7
    # Invalid rating/review values should return None
    # instead of producing an invalid ranking score.
    # -----------------------------------------------------
    def test_confidence_adjusted_rating_rejects_invalid_input(self):

        self.assertIsNone(
            brns_logic.confidence_adjusted_rating(
                6.0,
                100
            )
        )

        self.assertIsNone(
            brns_logic.confidence_adjusted_rating(
                4.5,
                -1
            )
        )


    # -----------------------------------------------------
    # TEST 8
    # A halal search hint must NOT automatically become
    # official halal certification.
    # -----------------------------------------------------
    def test_normalize_candidate_halal_hint_is_not_official(self):

        candidate = brns_logic.normalize_candidate({
            "name": "Hinted Restaurant",
            "cuisine": "japanese",
            "dietary_requirements": ["halal"],
            "halal_hint": True,
        })

        self.assertEqual(
            candidate["halal_status"],
            "unofficial"
        )


    # -----------------------------------------------------
    # TEST 9
    # Only a restaurant with official certification and
    # verified MUIS evidence should become "official".
    # -----------------------------------------------------
    def test_normalize_candidate_accepts_only_verified_official_halal(self):

        candidate = brns_logic.normalize_candidate({
            "name": "Verified Restaurant",
            "cuisine": "japanese",
            "halal_certification": "official",
            "muis_check": {
                "status": "verified"
            },
        })

        self.assertEqual(
            candidate["halal_status"],
            "official"
        )


    # -----------------------------------------------------
    # TEST 10
    # Offline restaurants should not keep old live route
    # information from previous searches.
    # -----------------------------------------------------
    def test_normalize_candidate_offline_clears_live_route_data(self):

        candidate = brns_logic.normalize_candidate(
            {
                "name": "Saved Restaurant",
                "cuisine": "japanese",
                "walk_minutes": 5,
                "walk_meters": 300,
                "walk_source": "route",
            },
            offline=True
        )

        self.assertIsNone(
            candidate["walk_minutes"]
        )

        self.assertIsNone(
            candidate["walk_meters"]
        )

        self.assertIsNone(
            candidate["walk_source"]
        )

        self.assertEqual(
            candidate["source"],
            "offline restaurants"
        )


    # -----------------------------------------------------
    # TEST 11
    # A restaurant satisfying the user's main requirements
    # should be classified as a match.
    # -----------------------------------------------------
    def test_decide_outcome_returns_match_for_valid_restaurant(self):

        request = make_request(
            cuisine="japanese"
        )

        restaurant = make_restaurant()

        status, score, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "match"
        )

        self.assertGreater(
            score,
            0
        )

        self.assertIn(
            "matches your selected cuisine",
            reasons
        )


    # -----------------------------------------------------
    # TEST 12
    # A restaurant over the user's budget should become
    # an alternative rather than an exact match.
    # -----------------------------------------------------
    def test_decide_outcome_over_budget_becomes_alternative(self):

        request = make_request(
            budget_per_person=10
        )

        restaurant = make_restaurant(
            avg_price=25
        )

        status, score, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "alternative"
        )

        self.assertEqual(
            score,
            0
        )

        self.assertTrue(
            any(
                "exceeds your SGD 10 budget" in reason
                for reason in reasons
            )
        )


    # -----------------------------------------------------
    # TEST 13
    # A disliked cuisine should cause immediate rejection.
    # -----------------------------------------------------
    def test_decide_outcome_disliked_cuisine_is_rejected(self):

        request = make_request(
            disliked_cuisines=["japanese"]
        )

        restaurant = make_restaurant(
            cuisines=["japanese"]
        )

        status, score, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "reject"
        )

        self.assertEqual(
            score,
            0
        )

        self.assertEqual(
            reasons,
            ["contains a disliked cuisine"]
        )


    # -----------------------------------------------------
    # TEST 14
    # If halal is required but official MUIS verification
    # is missing, the restaurant should be rejected.
    # -----------------------------------------------------
    def test_decide_outcome_unverified_halal_is_rejected(self):

        request = make_request(
            dietary_requirements=["halal"]
        )

        restaurant = make_restaurant(
            halal_status="unverified"
        )

        status, _, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "reject"
        )

        self.assertEqual(
            reasons,
            ["MUIS halal certification not verified"]
        )


    # -----------------------------------------------------
    # TEST 15
    # Officially verified halal restaurants should be
    # allowed to match a halal request.
    # -----------------------------------------------------
    def test_decide_outcome_official_halal_can_match(self):

        request = make_request(
            dietary_requirements=["halal"]
        )

        restaurant = make_restaurant(
            halal_status="official",
            dietary_requirements=["halal"],
        )

        status, _, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "match"
        )

        self.assertIn(
            "MUIS halal certification verified",
            reasons
        )
    # -----------------------------------------------------
    # TEST 24
    # A restaurant marked as vegetarian should be able
    # to match a vegetarian request.
    # -----------------------------------------------------
    def test_decide_outcome_verified_vegetarian_can_match(self):

        request = make_request(
            dietary_requirements=["vegetarian"]
        )

        restaurant = make_restaurant(
            dietary_requirements=["vegetarian"]
        )

        status, _, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "match"
        )


    # -----------------------------------------------------
    # TEST 25
    # A restaurant without vegetarian information should
    # not be treated as an exact vegetarian match.
    # -----------------------------------------------------
    def test_decide_outcome_unverified_vegetarian_is_not_exact_match(self):

        request = make_request(
            dietary_requirements=["vegetarian"]
        )

        restaurant = make_restaurant(
            dietary_requirements=[]
        )

        status, _, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertNotEqual(
            status,
            "match"
        )

    # -----------------------------------------------------
    # TEST 16
    # A restaurant that exceeds the user's travel-time
    # limit should become an alternative.
    # -----------------------------------------------------
    def test_decide_outcome_over_travel_time_becomes_alternative(self):

        request = make_request(
            max_travel_minutes=10
        )

        restaurant = make_restaurant(
            walk_minutes=25
        )

        status, _, reasons = brns_logic.decide_outcome(
            restaurant,
            request
        )

        self.assertEqual(
            status,
            "alternative"
        )

        self.assertTrue(
            any(
                "over your 10 min limit" in reason
                for reason in reasons
            )
        )


    # -----------------------------------------------------
    # TEST 17
    # AI recommendation IDs must be unique.
    # Duplicate restaurant IDs should be rejected.
    # -----------------------------------------------------
    def test_recommendation_order_rejects_duplicate_ids(self):

        restaurants = [
            make_restaurant(name="A"),
            make_restaurant(name="B"),
        ]

        recommendations = [
            {
                "id": 0,
                "reason_codes": []
            },
            {
                "id": 0,
                "reason_codes": []
            },
        ]

        with self.assertRaises(ValueError):

            brns_logic.recommendation_order(
                restaurants,
                recommendations
            )


    # -----------------------------------------------------
    # TEST 18
    # A valid complete AI restaurant ordering should
    # be accepted.
    # -----------------------------------------------------
    def test_recommendation_order_accepts_complete_unique_order(self):

        restaurants = [
            make_restaurant(name="A"),
            make_restaurant(name="B"),
        ]

        recommendations = [
            {
                "id": 1,
                "reason_codes": []
            },
            {
                "id": 0,
                "reason_codes": []
            },
        ]

        result = brns_logic.recommendation_order(
            restaurants,
            recommendations
        )

        self.assertEqual(
            result,
            [1, 0]
        )


    # -----------------------------------------------------
    # TEST 19
    # Weekly opening-hour data should correctly identify
    # a restaurant as open.
    # -----------------------------------------------------
    def test_open_now_from_weekly_detects_open_restaurant(self):

        hours = {
            "monday": [
                ["0900", "1800"]
            ]
        }

        now = datetime(
            2026,
            10,
            12,
            12,
            0,
            tzinfo=timezone(timedelta(hours=8))
        )

        result = brns_logic.open_now_from_weekly(
            hours,
            now
        )

        self.assertTrue(result)


    # -----------------------------------------------------
    # TEST 20
    # Weekly opening-hour data should correctly identify
    # a restaurant as closed outside its opening hours.
    # -----------------------------------------------------
    def test_open_now_from_weekly_detects_closed_restaurant(self):

        hours = {
            "monday": [
                ["0900", "1800"]
            ]
        }

        now = datetime(
            2026,
            10,
            12,
            20,
            0,
            tzinfo=timezone(timedelta(hours=8))
        )

        result = brns_logic.open_now_from_weekly(
            hours,
            now
        )

        self.assertFalse(result)


    # -----------------------------------------------------
    # TEST 21
    # BRNS should format today's saved opening hours
    # correctly for display.
    # -----------------------------------------------------
    def test_today_hours_from_weekly_formats_hours(self):

        hours = {
            "monday": [
                ["0900", "1800"]
            ]
        }

        now = datetime(
            2026,
            10,
            12,
            12,
            0,
            tzinfo=timezone(timedelta(hours=8))
        )

        result = brns_logic.today_hours_from_weekly(
            hours,
            now
        )

        self.assertEqual(
            result,
            "09:00–18:00"
        )


    # -----------------------------------------------------
    # TEST 22
    # Sorting by rating should place the highest-rated
    # restaurant first.
    # -----------------------------------------------------
    def test_sort_results_by_rating_places_highest_rating_first(self):

        results = {
            "mode": "walk",

            "matches": [
                {
                    "restaurant": make_restaurant(
                        name="Lower",
                        rating=4.1
                    )
                },

                {
                    "restaurant": make_restaurant(
                        name="Higher",
                        rating=4.8
                    )
                },
            ],

            "alternatives": [],
        }

        sorted_results = brns_logic.sort_results(
            results,
            "rating"
        )

        self.assertEqual(
            sorted_results["matches"][0]["restaurant"]["name"],
            "Higher"
        )


    # -----------------------------------------------------
    # TEST 23
    # Sorting by distance should place the nearest
    # restaurant first.
    # -----------------------------------------------------
    def test_sort_results_by_distance_places_nearest_first(self):

        results = {
            "mode": "walk",

            "matches": [
                {
                    "restaurant": make_restaurant(
                        name="Far",
                        walk_meters=1500
                    )
                },

                {
                    "restaurant": make_restaurant(
                        name="Near",
                        walk_meters=300
                    )
                },
            ],

            "alternatives": [],
        }

        sorted_results = brns_logic.sort_results(
            results,
            "distance"
        )

        self.assertEqual(
            sorted_results["matches"][0]["restaurant"]["name"],
            "Near"
        )


# =========================================================
# RUN TESTS
# =========================================================

if __name__ == "__main__":
    unittest.main()