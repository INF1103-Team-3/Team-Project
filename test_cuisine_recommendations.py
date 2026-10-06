import unittest
from unittest.mock import patch

import config
import data_manager
import logic_manager


class CuisineMatchingTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "cuisine": "chinese",
            "dietary": "none",
            "allergies": [],
            "budget_band": "any",
            "budget_min": None,
            "budget_max": None,
            "min_rating": None,
            "max_walk_minutes": None,
            "eat_time": "now",
            "free_text_notes": "",
        }

    def test_chinese_place_is_an_exact_match(self):
        status, _, _ = logic_manager.decide_outcome(
            {"name": "Chinese place", "cuisine": "chinese", "dietary": "none"},
            self.request,
        )
        self.assertEqual(status, "match")

    def test_non_chinese_place_is_an_alternative(self):
        status, _, _ = logic_manager.decide_outcome(
            {"name": "Western place", "cuisine": "western", "dietary": "none"},
            self.request,
        )
        self.assertEqual(status, "alternative")

    def test_unknown_cuisine_is_not_an_exact_match(self):
        status, _, _ = logic_manager.decide_outcome(
            {"name": "Unclassified place", "cuisine": "unknown", "dietary": "none"},
            self.request,
        )
        self.assertEqual(status, "alternative")

    def test_generic_google_display_name_does_not_become_a_cuisine(self):
        cuisines = data_manager._cuisines_from_types(
            [], primary_display="Restaurant",
        )
        self.assertEqual(cuisines, [])


class CuisineSearchTests(unittest.TestCase):
    @patch("data_manager.requests.post")
    def test_cuisine_search_uses_requested_cuisine_and_location_bias(self, post):
        response = post.return_value
        response.json.return_value = {"places": []}
        origin = (1.3, 103.8)

        data_manager.fetch_cuisine_restaurants(origin, {
            "cuisine": "chinese",
            "max_walk_minutes": 10,
        })

        args, kwargs = post.call_args
        self.assertEqual(args[0], config.PLACES_TEXT_URL)
        self.assertEqual(kwargs["json"]["textQuery"], "chinese restaurants")
        self.assertEqual(
            kwargs["json"]["locationBias"]["circle"]["center"],
            {"latitude": 1.3, "longitude": 103.8},
        )

    @patch("data_manager.walk_times_matrix")
    @patch("data_manager.enrich_place")
    @patch("data_manager.fetch_nearby_restaurants")
    @patch("data_manager.fetch_cuisine_restaurants")
    def test_cuisine_results_are_prioritized_and_nearby_results_fill_gaps(
        self, cuisine_search, nearby_search, enrich, _walk_times,
    ):
        chinese = {
            "name": "Chinese place",
            "lat": 1.3,
            "lng": 103.8,
            "cuisine": "chinese",
            "cuisines": ["chinese"],
            "walk_minutes": 5,
        }
        western = {
            "name": "Western place",
            "lat": 1.31,
            "lng": 103.81,
            "cuisine": "western",
            "cuisines": ["western"],
            "walk_minutes": 5,
        }
        cuisine_search.return_value = [chinese]
        nearby_search.return_value = [dict(chinese), western]
        enrich.side_effect = [dict(chinese), dict(chinese), dict(western)]

        with patch("data_manager.config.USE_LIVE_GOOGLE", True):
            results = data_manager.build_candidates(
                (1.3, 103.8),
                {"cuisine": "chinese", "max_walk_minutes": 10},
                [],
            )

        self.assertEqual([place["name"] for place in results],
                         ["Chinese place", "Western place"])
        cuisine_search.assert_called_once()
        nearby_search.assert_called_once()
        _walk_times.assert_called_once()


if __name__ == "__main__":
    unittest.main()
