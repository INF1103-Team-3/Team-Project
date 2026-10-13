"""
Direct unit tests for BIS logic_manager.py

These tests check individual BIS logic functions in isolation.
They do not require Docker, Google APIs, AI services, BRNS, or BRC.
"""

import sys
import unittest
from pathlib import Path


# =========================================================
# IMPORT SETUP
# =========================================================

# Find the root Team-Project folder.
ROOT = Path(__file__).resolve().parents[1]

# Allow Python to import project files.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))

# Import the real BIS logic we want to test.
from BIS import logic_manager as bis_logic

# Helper used to create a blank preference profile.
from sources.profile_schema import empty_preferences


# =========================================================
# BIS LOGIC UNIT TESTS
# =========================================================

class TestBISLogic(unittest.TestCase):

    # -----------------------------------------------------
    # TEST 1
    # Valid Singapore coordinates should be accepted.
    # -----------------------------------------------------
    def test_in_singapore_accepts_valid_coordinates(self):

        result = bis_logic.in_singapore(
            1.3521,
            103.8198
        )

        self.assertTrue(result)


    # -----------------------------------------------------
    # TEST 2
    # Overseas coordinates should be rejected.
    # -----------------------------------------------------
    def test_in_singapore_rejects_overseas_coordinates(self):

        # New York coordinates
        result = bis_logic.in_singapore(
            40.7128,
            -74.0060
        )

        self.assertFalse(result)


    # -----------------------------------------------------
    # TEST 3
    # Valid coordinate text should be converted into
    # latitude and longitude numbers.
    # -----------------------------------------------------
    def test_parse_coordinates_returns_latitude_and_longitude(self):

        result = bis_logic.parse_coordinates(
            "1.405, 103.902"
        )

        self.assertEqual(
            result,
            (1.405, 103.902)
        )


    # -----------------------------------------------------
    # TEST 4
    # Coordinates outside Singapore should cause an error.
    # -----------------------------------------------------
    def test_parse_coordinates_rejects_overseas_location(self):

        with self.assertRaises(ValueError):

            bis_logic.parse_coordinates(
                "40.7128, -74.0060"
            )


    # -----------------------------------------------------
    # TEST 5
    # Normal location text should not be mistaken for
    # latitude/longitude coordinates.
    # -----------------------------------------------------
    def test_parse_coordinates_returns_none_for_normal_text(self):

        result = bis_logic.parse_coordinates(
            "Punggol"
        )

        self.assertIsNone(result)


    # -----------------------------------------------------
    # TEST 6
    # A Singapore postal code should be recognised as a
    # direct location input.
    # -----------------------------------------------------
    def test_postal_code_is_direct_location_input(self):

        result = bis_logic.is_direct_location_input(
            "828761"
        )

        self.assertTrue(result)


    # -----------------------------------------------------
    # TEST 7
    # A normal place name should not be treated as a
    # direct postal-code/coordinate input.
    # -----------------------------------------------------
    def test_place_name_is_not_direct_location_input(self):

        result = bis_logic.is_direct_location_input(
            "Waterway Point"
        )

        self.assertFalse(result)


    # -----------------------------------------------------
    # TEST 8
    # When distance is provided, BIS should estimate
    # the corresponding travel time.
    #
    # Current rule:
    # 20 minutes per kilometre.
    # -----------------------------------------------------
    def test_distance_is_converted_to_travel_time(self):

        updates = {
            "max_distance_km": 2
        }

        result = bis_logic.estimate_travel_limits(
            updates
        )

        self.assertEqual(
            result["max_travel_time_minutes"],
            40
        )


    # -----------------------------------------------------
    # TEST 9
    # When travel time is provided, BIS should estimate
    # the corresponding distance.
    # -----------------------------------------------------
    def test_travel_time_is_converted_to_distance(self):

        updates = {
            "max_travel_time_minutes": 40
        }

        result = bis_logic.estimate_travel_limits(
            updates
        )

        self.assertEqual(
            result["max_distance_km"],
            2
        )


    # -----------------------------------------------------
    # TEST 10
    # BIS should detect when the same cuisine appears in
    # both liked and disliked cuisines.
    # -----------------------------------------------------
    def test_cuisine_conflict_is_detected(self):

        preferences = empty_preferences()

        preferences["liked_cuisines"] = [
            "japanese",
            "korean"
        ]

        preferences["disliked_cuisines"] = []

        updates = {
            "disliked_cuisines": [
                "japanese"
            ]
        }

        result = bis_logic.cuisine_conflicts(
            preferences,
            updates
        )

        self.assertEqual(
            result,
            ["japanese"]
        )


    # -----------------------------------------------------
    # TEST 11
    # BIS should extract multiple supported cuisines
    # from simple user text.
    # -----------------------------------------------------
    def test_cuisine_tokens_extracts_multiple_cuisines(self):

        result = bis_logic.cuisine_tokens(
            "I like Japanese and Korean",
            "liked_cuisines"
        )

        self.assertEqual(
            result,
            ["japanese", "korean"]
        )


    # -----------------------------------------------------
    # TEST 12
    # Dislike wording must not accidentally be stored
    # under liked cuisines.
    # -----------------------------------------------------
    def test_dislike_text_cannot_be_saved_as_liked_cuisine(self):

        with self.assertRaises(ValueError):

            bis_logic.cuisine_tokens(
                "I dislike Japanese",
                "liked_cuisines"
            )


    # -----------------------------------------------------
    # TEST 13
    # Applying updates should return a NEW profile and
    # should not mutate/change the original profile.
    # -----------------------------------------------------
    def test_apply_updates_does_not_change_original_profile(self):

        preferences = empty_preferences()

        updated = bis_logic.apply_updates(
            preferences,
            {
                "budget_per_person": 20
            }
        )

        # Original profile should remain unchanged.
        self.assertIsNone(
            preferences["budget_per_person"]
        )

        # Updated profile should contain the new budget.
        self.assertEqual(
            updated["budget_per_person"],
            20
        )


    # -----------------------------------------------------
    # TEST 14
    # Invalid location_action values should be rejected.
    # -----------------------------------------------------
    def test_apply_updates_rejects_invalid_location_action(self):

        preferences = empty_preferences()

        with self.assertRaises(ValueError):

            bis_logic.apply_updates(
                preferences,
                {},
                location_action="invalid"
            )


    # -----------------------------------------------------
    # TEST 15
    # cuisine_suggestions should suggest a close cuisine
    # name for a typo.
    # -----------------------------------------------------
    def test_cuisine_suggestions_returns_close_match(self):

        result = bis_logic.cuisine_suggestions(
            "japnese"
        )

        self.assertIn(
            "japanese",
            result
        )


    # -----------------------------------------------------
    # TEST 16
    # Very short/poor cuisine text should not generate
    # random suggestions.
    # -----------------------------------------------------
    def test_cuisine_suggestions_rejects_short_text(self):

        result = bis_logic.cuisine_suggestions(
            "jp"
        )

        self.assertEqual(
            result,
            []
        )


    # -----------------------------------------------------
    # TEST 17
    # Simple budget text should be converted into a
    # typed budget update.
    # -----------------------------------------------------
    def test_parse_local_answer_parses_budget(self):

        result = bis_logic.parse_local_answer(
            "20",
            "budget_per_person"
        )

        self.assertEqual(
            result["budget_per_person"],
            20
        )


    # -----------------------------------------------------
    # TEST 18
    # Invalid budget text should be rejected.
    # -----------------------------------------------------
    def test_parse_local_answer_rejects_invalid_budget(self):

        with self.assertRaises(ValueError):

            bis_logic.parse_local_answer(
                "twenty dollars",
                "budget_per_person"
            )


    # -----------------------------------------------------
    # TEST 19
    # Dietary input "both" should become both supported
    # dietary requirements.
    # -----------------------------------------------------
    def test_parse_local_answer_parses_both_dietary_requirements(self):

        result = bis_logic.parse_local_answer(
            "both",
            "dietary_requirements"
        )

        self.assertEqual(
            result["dietary_requirements"],
            ["halal", "vegetarian"]
        )


    # -----------------------------------------------------
    # TEST 20
    # next_field should return the first unanswered
    # preference field.
    # -----------------------------------------------------
    def test_next_field_returns_first_unanswered_field(self):

        preferences = empty_preferences()

        result = bis_logic.next_field(
            preferences
        )

        self.assertEqual(
            result,
            "location"
        )


    # -----------------------------------------------------
    # TEST 21
    # next_field should return None when all preference
    # fields have already been answered.
    # -----------------------------------------------------
    def test_next_field_returns_none_when_profile_complete(self):

        preferences = {
            "location": ["Punggol"],
            "max_distance_km": 2,
            "max_travel_time_minutes": 40,
            "budget_per_person": 20,
            "dietary_requirements": [],
            "liked_cuisines": [],
            "disliked_cuisines": [],
            "other_preferences": [],
        }

        result = bis_logic.next_field(
            preferences
        )

        self.assertIsNone(result)


# =========================================================
# RUN TESTS
# =========================================================

if __name__ == "__main__":
    unittest.main()   