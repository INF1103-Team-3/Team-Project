"""
Direct unit tests for BRNS ai_manager.py.

These tests verify BRNS AI helper logic without making real network/API calls.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


# =========================================================
# IMPORT SETUP
# =========================================================

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from BRNS import ai_manager as brns_ai


# =========================================================
# HELPER: VALID AI OUTPUT
# =========================================================

def make_valid_ai_output(**overrides):
    """
    Create one valid AI response.

    Individual tests can change only the field they want
    to test by passing an override.
    """

    data = {
        "cuisine": "japanese",
        "dietary": "none",
        "budget_band": "any",
        "budget_min": None,
        "budget_max": 20,
        "min_rating": 4.0,
        "max_walk_minutes": 15,
        "max_drive_km": None,
        "eat_time": "now",
        "free_text_notes": "spicy",
    }

    data.update(overrides)

    return data


# =========================================================
# BRNS AI UNIT TESTS
# =========================================================

class TestBRNSAI(unittest.TestCase):

    # -----------------------------------------------------
    # TEST 1
    # A valid model chain should not produce any problems.
    # -----------------------------------------------------
    def test_validate_chain_accepts_healthy_models(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "model-a"
            },
            {
                "provider": "gemini",
                "model": "model-b"
            },
        ]

        with patch.object(
            brns_ai.config,
            "MODEL_CHAIN",
            chain
        ):
            result = brns_ai.validate_chain()

        self.assertEqual(
            result,
            []
        )


    # -----------------------------------------------------
    # TEST 2
    # Invalid placeholder model names should be detected.
    # -----------------------------------------------------
    def test_validate_chain_detects_invalid_model_names(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "<model>"
            },
            {
                "provider": "gemini",
                "model": "bad model"
            },
        ]

        with patch.object(
            brns_ai.config,
            "MODEL_CHAIN",
            chain
        ):
            problems = brns_ai.validate_chain()

        self.assertIn(
            "openrouter/<model>",
            problems
        )

        self.assertIn(
            "gemini/bad model",
            problems
        )


    # -----------------------------------------------------
    # TEST 3
    # build_prompt should convert a user record into JSON.
    # -----------------------------------------------------
    def test_build_prompt_serializes_user_record(self):

        record = {
            "location": "Punggol",
            "budget": 20
        }

        prompt = brns_ai.build_prompt(record)

        self.assertEqual(
            json.loads(prompt),
            record
        )


    # -----------------------------------------------------
    # TEST 4
    # Plain valid JSON should be parsed successfully.
    # -----------------------------------------------------
    def test_parse_json_reply_accepts_plain_json(self):

        content = '{"cuisine":"japanese"}'

        result = brns_ai.parse_json_reply(content)

        self.assertEqual(
            result,
            {
                "cuisine": "japanese"
            }
        )


    # -----------------------------------------------------
    # TEST 5
    # JSON should still be extracted even if the AI adds
    # markdown fences or extra text around it.
    # -----------------------------------------------------
    def test_parse_json_reply_extracts_json_from_extra_text(self):

        content = """
        Result follows:

        ```json
        {"cuisine":"japanese"}
        ```

        Done.
        """

        result = brns_ai.parse_json_reply(content)

        self.assertEqual(
            result,
            {
                "cuisine": "japanese"
            }
        )


    # -----------------------------------------------------
    # TEST 6
    # AI response with no JSON object should fail.
    # -----------------------------------------------------
    def test_parse_json_reply_rejects_reply_without_json(self):

        with self.assertRaises(ValueError):

            brns_ai.parse_json_reply(
                "I cannot provide JSON"
            )


    # -----------------------------------------------------
    # TEST 7
    # Malformed JSON should also fail.
    # -----------------------------------------------------
    def test_parse_json_reply_rejects_malformed_json(self):

        with self.assertRaises(ValueError):

            brns_ai.parse_json_reply(
                '{"cuisine": japanese}'
            )


    # -----------------------------------------------------
    # TEST 8
    # A complete valid AI response should pass schema
    # validation.
    # -----------------------------------------------------
    def test_validate_ai_output_accepts_valid_schema(self):

        data = make_valid_ai_output()

        ok, result = brns_ai.validate_ai_output(
            data
        )

        self.assertTrue(ok)

        self.assertEqual(
            result,
            data
        )


    # -----------------------------------------------------
    # TEST 9
    # AI output must be a JSON object / dictionary.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_non_object(self):

        ok, error = brns_ai.validate_ai_output(
            []
        )

        self.assertFalse(ok)

        self.assertEqual(
            error,
            "AI output is not a JSON object"
        )


    # -----------------------------------------------------
    # TEST 10
    # All required keys must be present.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_missing_required_key(self):

        data = make_valid_ai_output()

        del data["cuisine"]

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "missing required key: cuisine",
            error
        )


    # -----------------------------------------------------
    # TEST 11
    # Numeric AI fields must actually be numbers.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_wrong_numeric_type(self):

        data = make_valid_ai_output(
            min_rating="4.5"
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "min_rating",
            error
        )


    # -----------------------------------------------------
    # TEST 12
    # Rating cannot exceed 5.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_rating_above_five(self):

        data = make_valid_ai_output(
            min_rating=5.5
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "between 1 and 5",
            error
        )


    # -----------------------------------------------------
    # TEST 13
    # Rating cannot be below 1.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_rating_below_one(self):

        data = make_valid_ai_output(
            min_rating=0.5
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "between 1 and 5",
            error
        )


    # -----------------------------------------------------
    # TEST 14
    # Minimum budget cannot be greater than maximum budget.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_reversed_budget_range(self):

        data = make_valid_ai_output(
            budget_min=30,
            budget_max=10
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertEqual(
            error,
            "AI output budget_min exceeds budget_max"
        )


    # -----------------------------------------------------
    # TEST 15
    # budget_band must use one of the supported values.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_invalid_budget_band(self):

        data = make_valid_ai_output(
            budget_band="super_cheap"
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "budget_band",
            error
        )


    # -----------------------------------------------------
    # TEST 16
    # dietary must use one of the supported values.
    # -----------------------------------------------------
    def test_validate_ai_output_rejects_invalid_dietary_value(self):

        data = make_valid_ai_output(
            dietary="pescatarian"
        )

        ok, error = brns_ai.validate_ai_output(
            data
        )

        self.assertFalse(ok)

        self.assertIn(
            "dietary",
            error
        )


    # -----------------------------------------------------
    # TEST 17
    # Provider error bodies should not leak into logs /
    # returned error summaries.
    # -----------------------------------------------------
    def test_safe_failure_hides_http_response_body(self):

        result = brns_ai._safe_failure(
            "HTTP 500: secret provider response"
        )

        self.assertEqual(
            result,
            "HTTP 500"
        )

        self.assertNotIn(
            "secret",
            result
        )


    # -----------------------------------------------------
    # TEST 18
    # Rate-limit errors should be normalised safely.
    # -----------------------------------------------------
    def test_safe_failure_normalizes_rate_limit_message(self):

        result = brns_ai._safe_failure(
            "429 rate limited / free quota used"
        )

        self.assertEqual(
            result,
            "rate limited"
        )


    # -----------------------------------------------------
    # TEST 19
    # A valid provider with a configured API key should be
    # recognised as available.
    # -----------------------------------------------------
    def test_has_configured_provider_true_for_valid_provider(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "valid-model"
            }
        ]

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),
            patch.object(
                brns_ai.config,
                "OPENROUTER_API_KEY",
                "test-key"
            ),
        ):

            result = brns_ai.has_configured_provider()

        self.assertTrue(result)


    # -----------------------------------------------------
    # TEST 20
    # Provider should not count as configured without an
    # API key.
    # -----------------------------------------------------
    def test_has_configured_provider_false_without_credentials(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "valid-model"
            }
        ]

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),
            patch.object(
                brns_ai.config,
                "OPENROUTER_API_KEY",
                ""
            ),
            patch.object(
                brns_ai.config,
                "GEMINI_API_KEY",
                ""
            ),
            patch.object(
                brns_ai.config,
                "GROQ_API_KEY",
                ""
            ),
        ):

            result = brns_ai.has_configured_provider()

        self.assertFalse(result)


    # -----------------------------------------------------
    # TEST 21
    # If the first AI provider returns invalid schema,
    # call_ai should fall back to the next model.
    # -----------------------------------------------------
    def test_call_ai_falls_back_after_invalid_schema(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "first-model"
            },
            {
                "provider": "gemini",
                "model": "second-model"
            },
        ]

        invalid_response = json.dumps({
            "cuisine": "japanese"
        })

        valid_response = json.dumps(
            make_valid_ai_output()
        )

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),

            patch.object(
                brns_ai,
                "_call_openrouter",
                return_value=(
                    True,
                    invalid_response
                )
            ),

            patch.object(
                brns_ai,
                "_call_gemini",
                return_value=(
                    True,
                    valid_response
                )
            ),

            patch.object(
                brns_ai,
                "_log_ai_event"
            ),
        ):

            ok, result, model = brns_ai.call_ai({
                "request": "Japanese food"
            })

        self.assertTrue(ok)

        self.assertEqual(
            result,
            make_valid_ai_output()
        )

        self.assertEqual(
            model,
            "gemini/second-model"
        )


    # -----------------------------------------------------
    # TEST 22
    # If every AI provider fails, BRNS should return a
    # controlled failure instead of crashing.
    # -----------------------------------------------------
    def test_call_ai_returns_failure_when_every_provider_fails(self):

        chain = [
            {
                "provider": "openrouter",
                "model": "test-model"
            }
        ]

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),

            patch.object(
                brns_ai,
                "_call_openrouter",
                return_value=(
                    False,
                    "HTTP 500: private response body"
                )
            ),

            patch.object(
                brns_ai,
                "_log_ai_event"
            ),

            patch.object(
                brns_ai.time,
                "sleep"
            ),
        ):

            ok, error, model = brns_ai.call_ai({
                "request": "food"
            })

        self.assertFalse(ok)

        self.assertIn(
            "HTTP 500",
            error
        )

        self.assertNotIn(
            "private response body",
            error
        )

        self.assertIsNone(model)


    # -----------------------------------------------------
    # TEST 23
    # If there are no restaurant candidates, there is
    # nothing for the AI to rank.
    # -----------------------------------------------------
    def test_recommend_candidates_returns_none_for_empty_candidates(self):

        result = brns_ai.recommend_candidates(
            {
                "mode": "walk"
            },
            []
        )

        self.assertIsNone(result)


    # -----------------------------------------------------
    # TEST 24
    # A valid AI restaurant ordering should be accepted.
    # -----------------------------------------------------
    def test_recommend_candidates_accepts_valid_ai_order(self):

        request = {
            "mode": "walk",
            "other_preferences": [],
            "budget_per_person": 20,
            "max_travel_minutes": 20,
            "max_distance_km": None,
        }

        candidates = [
            {
                "name": "A",
                "cuisines": ["japanese"],
                "dietary_requirements": [],
                "avg_price": 10,
                "rating": 4.5,
                "rating_count": 100,
                "walk_meters": 500,
                "walk_minutes": 8,
                "walk_source": "route",
            },

            {
                "name": "B",
                "cuisines": ["korean"],
                "dietary_requirements": [],
                "avg_price": 12,
                "rating": 4.2,
                "rating_count": 80,
                "walk_meters": 700,
                "walk_minutes": 10,
                "walk_source": "route",
            },
        ]

        ai_reply = json.dumps({
            "recommendations": [
                {
                    "id": 1,
                    "reason_codes": [
                        "well_rated"
                    ]
                },
                {
                    "id": 0,
                    "reason_codes": [
                        "within_budget"
                    ]
                },
            ]
        })

        chain = [
            {
                "provider": "openrouter",
                "model": "test-model"
            }
        ]

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),

            patch.object(
                brns_ai.config,
                "OPENROUTER_API_KEY",
                "test-key"
            ),

            patch.object(
                brns_ai,
                "_call_openrouter",
                return_value=(
                    True,
                    ai_reply
                )
            ),

            patch.object(
                brns_ai,
                "_log_ai_event"
            ),
        ):

            result = brns_ai.recommend_candidates(
                request,
                candidates
            )

        self.assertEqual(
            result,
            [
                {
                    "id": 1,
                    "reason_codes": [
                        "well_rated"
                    ]
                },
                {
                    "id": 0,
                    "reason_codes": [
                        "within_budget"
                    ]
                },
            ]
        )


    # -----------------------------------------------------
    # TEST 25
    # AI ranking output cannot contain duplicate restaurant
    # IDs.
    # -----------------------------------------------------
    def test_recommend_candidates_rejects_duplicate_ids(self):

        request = {
            "mode": "walk",
            "other_preferences": [],
            "budget_per_person": 20,
            "max_travel_minutes": 20,
            "max_distance_km": None,
        }

        candidates = [
            {
                "name": "A",
                "cuisines": [],
                "dietary_requirements": []
            },

            {
                "name": "B",
                "cuisines": [],
                "dietary_requirements": []
            },
        ]

        ai_reply = json.dumps({
            "recommendations": [
                {
                    "id": 0,
                    "reason_codes": []
                },
                {
                    "id": 0,
                    "reason_codes": []
                },
            ]
        })

        chain = [
            {
                "provider": "openrouter",
                "model": "test-model"
            }
        ]

        with (
            patch.object(
                brns_ai.config,
                "MODEL_CHAIN",
                chain
            ),

            patch.object(
                brns_ai.config,
                "OPENROUTER_API_KEY",
                "test-key"
            ),

            patch.object(
                brns_ai,
                "_call_openrouter",
                return_value=(
                    True,
                    ai_reply
                )
            ),

            patch.object(
                brns_ai,
                "_log_ai_event"
            ),
        ):

            result = brns_ai.recommend_candidates(
                request,
                candidates
            )

        self.assertIsNone(result)


# =========================================================
# RUN TESTS
# =========================================================

if __name__ == "__main__":
    unittest.main()