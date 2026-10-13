"""Function tests for BiteFinder BIS profile and search logic."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(TEST_DIR))


from BIS import logic_manager as bis_logic
from sources.profile_schema import empty_preferences
from reporting import show_case, show_summary

from sample_inputs import (
    VALID_SINGAPORE_COORDINATES,
    OVERSEAS_COORDINATES,
    SINGAPORE_POSTAL_CODE,
    VALID_BUDGET_TEXT,
    INVALID_BUDGET_TEXT,
    DIETARY_BOTH_TEXT,
    LIKED_CUISINES_TEXT,
    DISLIKE_AS_LIKE_TEXT,
    VALID_SPECIAL_REQUEST,
    INVALID_SPECIAL_REQUEST,
    confirmed_search_request,
    valid_ai_search_response,
    conflicting_ai_search_response,
)


def test_valid_singapore_coordinates_are_parsed():
    """Valid Singapore coordinates become numeric latitude and longitude."""

    test_input = VALID_SINGAPORE_COORDINATES
    expected = (1.405, 103.902)

    actual = bis_logic.parse_coordinates(
        test_input
    )

    show_case(
        "BIS-01: Valid Singapore coordinates",
        "parse_coordinates()",
        "Checks coordinate text and converts a valid Singapore "
        "location into latitude and longitude.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_overseas_coordinates_are_rejected():
    """Coordinates outside Singapore are rejected before a search is prepared."""

    test_input = OVERSEAS_COORDINATES
    expected = "Enter coordinates within Singapore."

    try:
        bis_logic.parse_coordinates(
            test_input
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

    show_case(
        "BIS-02: Overseas coordinates rejected",
        "parse_coordinates()",
        "Validates that manually entered coordinates fall inside "
        "BiteFinder's supported Singapore area.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_postal_code_is_recognised_as_direct_location():
    """A Singapore postal code can bypass AI location interpretation."""

    test_input = SINGAPORE_POSTAL_CODE
    expected = True

    actual = bis_logic.is_direct_location_input(
        test_input
    )

    show_case(
        "BIS-03: Postal code recognised",
        "is_direct_location_input()",
        "Checks whether a location is already a postal code or "
        "coordinate that can be handled directly.",
        test_input,
        expected,
        actual,
    )

    assert actual is expected


def test_distance_estimates_walking_time():
    """A distance-only profile update gets the matching walking-time estimate."""

    test_input = {
        "max_distance_km": 2.0,
    }

    expected = {
        "max_distance_km": 2.0,
        "max_travel_time_minutes": 40.0,
    }

    actual = bis_logic.estimate_travel_limits(
        test_input
    )

    show_case(
        "BIS-04: Distance converted to walking time",
        "estimate_travel_limits()",
        "Completes the missing travel-limit counterpart using "
        "BiteFinder's walking-time conversion rule.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_numeric_budget_becomes_structured_update():
    """A valid numeric budget is converted to the structured profile format."""

    test_input = {
        "field": "budget_per_person",
        "answer": VALID_BUDGET_TEXT,
    }

    expected = {
        "budget_per_person": 20.0,
    }

    actual = bis_logic.parse_local_answer(
        test_input["answer"],
        test_input["field"],
    )

    show_case(
        "BIS-05: Valid budget accepted",
        "parse_local_answer()",
        "Validates a user's answer and converts it into the typed "
        "preference update used by BIS.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_written_budget_is_rejected():
    """A non-numeric budget is rejected instead of being guessed."""

    test_input = {
        "field": "budget_per_person",
        "answer": INVALID_BUDGET_TEXT,
    }

    expected = (
        "Enter SGD as a number, e.g. 5 or 5.50."
    )

    try:
        bis_logic.parse_local_answer(
            test_input["answer"],
            test_input["field"],
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

    show_case(
        "BIS-06: Invalid budget rejected",
        "parse_local_answer()",
        "Rejects an invalid budget before it can enter the "
        "BiteFinder search profile.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_both_dietary_requirements_are_preserved():
    """Choosing both stores halal and vegetarian as separate requirements."""

    test_input = {
        "field": "dietary_requirements",
        "answer": DIETARY_BOTH_TEXT,
    }

    expected = {
        "dietary_requirements": [
            "halal",
            "vegetarian",
        ]
    }

    actual = bis_logic.parse_local_answer(
        test_input["answer"],
        test_input["field"],
    )

    show_case(
        "BIS-07: Dietary requirements preserved",
        "parse_local_answer()",
        "Converts the user's dietary answer into the structured "
        "restrictions passed through BiteFinder.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_multiple_cuisines_are_extracted():
    """Simple natural wording can produce more than one supported cuisine."""

    test_input = {
        "field": "liked_cuisines",
        "answer": LIKED_CUISINES_TEXT,
    }

    expected = [
        "japanese",
        "korean",
    ]

    actual = bis_logic.cuisine_tokens(
        test_input["answer"],
        test_input["field"],
    )

    show_case(
        "BIS-08: Multiple cuisines recognised",
        "cuisine_tokens()",
        "Extracts supported cuisine names from simple user wording "
        "without using a live AI call.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_dislike_wording_cannot_be_saved_as_a_like():
    """A dislike statement cannot accidentally become a liked cuisine."""

    test_input = {
        "field": "liked_cuisines",
        "answer": DISLIKE_AS_LIKE_TEXT,
    }

    expected = (
        "That describes dislikes. "
        "Enter cuisines you like."
    )

    try:
        bis_logic.cuisine_tokens(
            test_input["answer"],
            test_input["field"],
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

    show_case(
        "BIS-09: Conflicting cuisine wording rejected",
        "cuisine_tokens()",
        "Prevents negative cuisine wording from being stored "
        "under the user's liked cuisines.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_profile_update_does_not_mutate_original_profile():
    """Applying a new budget leaves the original profile unchanged."""

    preferences = empty_preferences()

    test_input = {
        "budget_per_person": 20.0,
    }

    expected = {
        "updated_budget": 20.0,
        "original_budget": None,
    }

    updated = bis_logic.apply_updates(
        preferences,
        test_input,
    )

    actual = {
        "updated_budget":
            updated["budget_per_person"],

        "original_budget":
            preferences["budget_per_person"],
    }

    show_case(
        "BIS-10: Profile update keeps original unchanged",
        "apply_updates()",
        "Builds a validated updated preference profile without "
        "mutating the original saved values.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_valid_special_request_text_is_accepted():
    """A meaningful English special request is accepted for interpretation."""

    test_input = VALID_SPECIAL_REQUEST
    expected = VALID_SPECIAL_REQUEST

    actual = bis_logic.validate_special_request_text(
        test_input
    )

    show_case(
        "BIS-11: Valid special request accepted",
        "validate_special_request_text()",
        "Checks free-text search wording before BIS sends it "
        "for AI interpretation.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_invalid_special_request_text_is_rejected():
    """Malformed special-request text is rejected before reaching the AI."""

    test_input = INVALID_SPECIAL_REQUEST

    expected = (
        "Write your special request in English letters and words, "
        "such as chicken rice or a quiet cafe."
    )

    try:
        bis_logic.validate_special_request_text(
            test_input
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

    show_case(
        "BIS-12: Invalid special request rejected",
        "validate_special_request_text()",
        "Rejects malformed free-text requests before they reach "
        "the AI interpretation step.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_hardcoded_ai_response_can_add_soft_preferences():
    """Valid hardcoded AI output may add soft preferences."""

    confirmed = confirmed_search_request()
    ai_response = valid_ai_search_response()

    test_input = {
        "confirmed_request":
            confirmed,

        "hardcoded_ai_response":
            ai_response,
    }

    expected = [
        "spicy food",
        "quiet place",
    ]

    result = bis_logic.validate_search_request(
        confirmed,
        ai_response,
    )

    actual = result[
        "other_preferences"
    ]

    show_case(
        "BIS-13: Hardcoded AI interpretation accepted",
        "validate_search_request()",
        "Validates structured AI output and allows additional "
        "soft preferences when confirmed search choices remain unchanged.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_hardcoded_ai_response_cannot_change_confirmed_budget():
    """AI output cannot change a budget already confirmed by the user."""

    confirmed = confirmed_search_request()
    ai_response = conflicting_ai_search_response()

    test_input = {
        "confirmed_budget":
            confirmed["budget_per_person"],

        "hardcoded_ai_budget":
            ai_response["budget_per_person"],
    }

    expected = (
        "The AI interpretation conflicts with a confirmed choice. "
        "Please clarify what you want today."
    )

    try:
        bis_logic.validate_search_request(
            confirmed,
            ai_response,
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

        # Remove the internal clarification marker if the
        # current BIS version includes one.
        prefix = "SEARCH_CLARIFICATION: "

        if actual.startswith(prefix):
            actual = actual[len(prefix):]

    show_case(
        "BIS-14: AI cannot override confirmed budget",
        "validate_search_request()",
        "Protects a budget already confirmed by the user by "
        "rejecting AI output that attempts to change it.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


TESTS = (
    test_valid_singapore_coordinates_are_parsed,
    test_overseas_coordinates_are_rejected,
    test_postal_code_is_recognised_as_direct_location,
    test_distance_estimates_walking_time,
    test_numeric_budget_becomes_structured_update,
    test_written_budget_is_rejected,
    test_both_dietary_requirements_are_preserved,
    test_multiple_cuisines_are_extracted,
    test_dislike_wording_cannot_be_saved_as_a_like,
    test_profile_update_does_not_mutate_original_profile,
    test_valid_special_request_text_is_accepted,
    test_invalid_special_request_text_is_rejected,
    test_hardcoded_ai_response_can_add_soft_preferences,
    test_hardcoded_ai_response_cannot_change_confirmed_budget,
)


def run_tests():
    """Run all BIS function tests without requiring a live API."""

    failures = []

    for test in TESTS:

        try:
            test()

        except Exception as error:

            failures.append(
                (
                    test.__name__,
                    error,
                )
            )

            print(
                f"\nFAILED: "
                f"{test.__name__}: "
                f"{error}"
            )

    show_summary(
        "BIS",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()