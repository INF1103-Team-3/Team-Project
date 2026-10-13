"""Function tests for BiteFinder BRNS recommendation and ranking logic."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(TEST_DIR))


from BRNS import logic_manager as brns_logic
from reporting import show_case, show_summary

from sample_inputs import (
    MONDAY_EVENING,
    MONDAY_NOON,
    MONDAY_OPENING_HOURS,
    duplicate_ai_recommendations,
    halal_hint_restaurant,
    ranking_restaurants,
    restaurant,
    search_request,
    valid_ai_recommendations,
    verified_halal_restaurant,
)


def test_explicit_minimum_rating_is_read():
    """A stated minimum Google rating becomes a numeric requirement."""

    test_input = [
        "at least 4.5 stars"
    ]

    expected = 4.5

    actual = brns_logic.minimum_rating(
        test_input
    )

    show_case(
        "BRNS-01: Minimum rating recognised",
        "minimum_rating()",
        "Reads an explicit minimum Google rating from "
        "the user's other preferences.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_hard_cuisine_requirement_is_detected():
    """Hard cuisine wording is preserved as a mandatory requirement."""

    test_input = [
        "Japanese only"
    ]

    expected = [
        "japanese"
    ]

    actual = (
        brns_logic.hard_required_cuisines(
            test_input
        )
    )

    show_case(
        "BRNS-02: Hard cuisine requirement recognised",
        "hard_required_cuisines()",
        "Finds cuisine wording that the user marked as "
        "mandatory instead of a normal preference.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_halal_hint_is_not_treated_as_official():
    """A halal hint cannot become official halal certification."""

    test_input = (
        halal_hint_restaurant()
    )

    expected = "unofficial"

    actual = (
        brns_logic.normalize_candidate(
            test_input
        )["halal_status"]
    )

    show_case(
        "BRNS-03: Halal hint remains unofficial",
        "normalize_candidate()",
        "Normalises restaurant information without turning "
        "an unverified halal hint into official certification.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_verified_muis_evidence_becomes_official_halal():
    """Official halal status requires verified MUIS evidence."""

    test_input = (
        verified_halal_restaurant()
    )

    expected = "official"

    actual = (
        brns_logic.normalize_candidate(
            test_input
        )["halal_status"]
    )

    show_case(
        "BRNS-04: Verified MUIS status accepted",
        "normalize_candidate()",
        "Marks halal status as official only when the restaurant "
        "has official certification and verified MUIS evidence.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_restaurant_meeting_requirements_is_a_match():
    """A suitable restaurant is classified as an exact match."""

    request = search_request()
    candidate = restaurant()

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "match"

    status, _, _ = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = status

    show_case(
        "BRNS-05: Suitable restaurant becomes a match",
        "decide_outcome()",
        "Applies the user's requirements to determine whether "
        "a restaurant is a match, alternative or rejection.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_over_budget_restaurant_becomes_alternative():
    """A restaurant above budget is not treated as an exact match."""

    request = search_request(
        budget_per_person=10
    )

    candidate = restaurant(
        avg_price=25
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = status

    show_case(
        "BRNS-06: Over-budget restaurant becomes alternative",
        "decide_outcome()",
        "Checks restaurant price against the user's budget "
        "before determining the recommendation outcome.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_disliked_cuisine_is_rejected():
    """A cuisine explicitly disliked by the user causes rejection."""

    request = search_request(
        disliked_cuisines=[
            "japanese"
        ]
    )

    candidate = restaurant(
        cuisines=[
            "japanese"
        ]
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "reject",
        "reasons": [
            "contains a disliked cuisine"
        ],
    }

    status, _, reasons = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = {
        "status": status,
        "reasons": reasons,
    }

    show_case(
        "BRNS-07: Disliked cuisine rejected",
        "decide_outcome()",
        "Prevents restaurants serving a cuisine explicitly "
        "disliked by the user from being recommended.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_unverified_halal_restaurant_is_rejected():
    """A halal request rejects restaurants without verified certification."""

    request = search_request(
        dietary_requirements=[
            "halal"
        ]
    )

    candidate = restaurant(
        halal_status="unverified"
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "reject",
        "reasons": [
            "MUIS halal certification not verified"
        ],
    }

    status, _, reasons = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = {
        "status": status,
        "reasons": reasons,
    }

    show_case(
        "BRNS-08: Unverified halal restaurant rejected",
        "decide_outcome()",
        "Enforces the user's halal requirement by requiring "
        "verified official halal information.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_verified_halal_restaurant_can_match():
    """A verified halal restaurant can satisfy a halal request."""

    request = search_request(
        dietary_requirements=[
            "halal"
        ]
    )

    candidate = (
        brns_logic.normalize_candidate(
            verified_halal_restaurant()
        )
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "match"

    status, _, _ = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = status

    show_case(
        "BRNS-09: Verified halal restaurant can match",
        "decide_outcome()",
        "Allows a restaurant with verified official halal "
        "evidence to satisfy a halal search requirement.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_unverified_vegetarian_option_is_not_exact_match():
    """Missing vegetarian evidence prevents an exact match."""

    request = search_request(
        dietary_requirements=[
            "vegetarian"
        ]
    )

    candidate = restaurant(
        dietary_requirements=[]
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = status

    show_case(
        "BRNS-10: Unverified vegetarian option becomes alternative",
        "decide_outcome()",
        "Prevents a restaurant from being treated as an exact "
        "vegetarian match when vegetarian information is unverified.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_over_travel_time_restaurant_becomes_alternative():
    """A restaurant outside the walking limit is not an exact match."""

    request = search_request(
        max_travel_minutes=10
    )

    candidate = restaurant(
        walk_minutes=25
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = (
        brns_logic.decide_outcome(
            candidate,
            request,
        )
    )

    actual = status

    show_case(
        "BRNS-11: Travel-time limit enforced",
        "decide_outcome()",
        "Checks route time against the user's maximum travel "
        "time before classifying the restaurant.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_valid_hardcoded_ai_order_is_accepted():
    """A complete unique AI ordering is accepted without a live API."""

    restaurants = (
        ranking_restaurants()
    )

    ai_response = (
        valid_ai_recommendations()
    )

    test_input = {
        "restaurant_names": [
            item["name"]
            for item in restaurants
        ],

        "hardcoded_ai_response":
            ai_response,
    }

    expected = [
        1,
        0,
    ]

    actual = (
        brns_logic.recommendation_order(
            restaurants,
            ai_response,
        )
    )

    show_case(
        "BRNS-12: Hardcoded AI recommendation order accepted",
        "recommendation_order()",
        "Validates that AI output contains exactly one valid "
        "restaurant ID for every available candidate.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_duplicate_hardcoded_ai_ids_are_rejected():
    """Duplicate IDs in AI output are rejected."""

    restaurants = (
        ranking_restaurants()
    )

    ai_response = (
        duplicate_ai_recommendations()
    )

    test_input = {
        "restaurant_names": [
            item["name"]
            for item in restaurants
        ],

        "hardcoded_ai_response":
            ai_response,
    }

    expected = (
        "BRNS AI returned duplicate restaurant IDs."
    )

    try:
        brns_logic.recommendation_order(
            restaurants,
            ai_response,
        )

        actual = "Accepted"

    except ValueError as error:
        actual = str(error)

    show_case(
        "BRNS-13: Duplicate AI restaurant IDs rejected",
        "recommendation_order()",
        "Protects recommendation ranking from malformed AI "
        "output that repeats a restaurant ID.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_hardcoded_ai_ranking_is_checked_against_business_rules():
    """AI ordering still passes through deterministic BRNS rules."""

    restaurants = (
        ranking_restaurants()
    )

    request = search_request()

    ai_response = (
        valid_ai_recommendations()
    )

    test_input = {
        "request":
            request,

        "hardcoded_ai_response":
            ai_response,

        "restaurant_names": [
            item["name"]
            for item in restaurants
        ],
    }

    expected = [
        "Tokyo Choice",
        "Sakura Near",
    ]

    result = (
        brns_logic.rank_restaurants(
            restaurants,
            request,
            recommendations=ai_response,
        )
    )

    actual = [
        item["restaurant"]["name"]
        for item in result["matches"]
    ]

    show_case(
        "BRNS-14: AI ranking passes through BRNS business rules",
        "rank_restaurants()",
        "Uses hardcoded AI ordering and reason codes, then "
        "independently enforces BRNS business rules before "
        "returning recommendations.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_weekly_hours_detect_open_restaurant():
    """Weekly hours identify a restaurant as open at Monday noon."""

    test_input = {
        "weekly_hours":
            MONDAY_OPENING_HOURS,

        "time":
            MONDAY_NOON.isoformat(),
    }

    expected = True

    actual = (
        brns_logic.open_now_from_weekly(
            MONDAY_OPENING_HOURS,
            MONDAY_NOON,
        )
    )

    show_case(
        "BRNS-15: Opening hours detect open restaurant",
        "open_now_from_weekly()",
        "Checks saved restaurant opening hours against "
        "a specific Singapore local time.",
        test_input,
        expected,
        actual,
    )

    assert actual is expected


def test_weekly_hours_detect_closed_restaurant():
    """Weekly hours identify a restaurant as closed after operating hours."""

    test_input = {
        "weekly_hours":
            MONDAY_OPENING_HOURS,

        "time":
            MONDAY_EVENING.isoformat(),
    }

    expected = False

    actual = (
        brns_logic.open_now_from_weekly(
            MONDAY_OPENING_HOURS,
            MONDAY_EVENING,
        )
    )

    show_case(
        "BRNS-16: Opening hours detect closed restaurant",
        "open_now_from_weekly()",
        "Checks that a restaurant outside its saved opening "
        "interval is not treated as open.",
        test_input,
        expected,
        actual,
    )

    assert actual is expected


def test_rating_sort_places_highest_rated_first():
    """Sorting by rating places the highest-rated restaurant first."""

    results = {
        "mode": "walk",

        "matches": [
            {
                "restaurant":
                    restaurant(
                        name="Lower",
                        rating=4.1,
                    )
            },

            {
                "restaurant":
                    restaurant(
                        name="Higher",
                        rating=4.8,
                    )
            },
        ],

        "alternatives": [],
    }

    test_input = {
        "sort_by": "rating",

        "restaurants": [
            "Lower: 4.1",
            "Higher: 4.8",
        ],
    }

    expected = "Higher"

    sorted_results = (
        brns_logic.sort_results(
            results,
            "rating",
        )
    )

    actual = (
        sorted_results["matches"][0]
        ["restaurant"]["name"]
    )

    show_case(
        "BRNS-17: Results sorted by rating",
        "sort_results()",
        "Orders classified recommendations by Google rating "
        "when the user chooses rating sorting.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_distance_sort_places_nearest_first():
    """Sorting by distance places the nearest restaurant first."""

    results = {
        "mode": "walk",

        "matches": [
            {
                "restaurant":
                    restaurant(
                        name="Far",
                        walk_meters=1500,
                    )
            },

            {
                "restaurant":
                    restaurant(
                        name="Near",
                        walk_meters=300,
                    )
            },
        ],

        "alternatives": [],
    }

    test_input = {
        "sort_by": "distance",

        "restaurants": [
            "Far: 1500 m",
            "Near: 300 m",
        ],
    }

    expected = "Near"

    sorted_results = (
        brns_logic.sort_results(
            results,
            "distance",
        )
    )

    actual = (
        sorted_results["matches"][0]
        ["restaurant"]["name"]
    )

    show_case(
        "BRNS-18: Results sorted by distance",
        "sort_results()",
        "Orders classified recommendations by route distance "
        "when the user chooses distance sorting.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


TESTS = (
    test_explicit_minimum_rating_is_read,
    test_hard_cuisine_requirement_is_detected,
    test_halal_hint_is_not_treated_as_official,
    test_verified_muis_evidence_becomes_official_halal,
    test_restaurant_meeting_requirements_is_a_match,
    test_over_budget_restaurant_becomes_alternative,
    test_disliked_cuisine_is_rejected,
    test_unverified_halal_restaurant_is_rejected,
    test_verified_halal_restaurant_can_match,
    test_unverified_vegetarian_option_is_not_exact_match,
    test_over_travel_time_restaurant_becomes_alternative,
    test_valid_hardcoded_ai_order_is_accepted,
    test_duplicate_hardcoded_ai_ids_are_rejected,
    test_hardcoded_ai_ranking_is_checked_against_business_rules,
    test_weekly_hours_detect_open_restaurant,
    test_weekly_hours_detect_closed_restaurant,
    test_rating_sort_places_highest_rated_first,
    test_distance_sort_places_nearest_first,
)


def run_tests():
    """Run all BRNS function tests without a live AI API."""

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
        "BRNS",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()