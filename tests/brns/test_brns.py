"""Function tests for BiteFinder BRNS recommendation and ranking logic."""
import json
import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(TEST_DIR))


from BRNS import logic_manager as brns_logic
from BRNS import ai_manager as brns_ai
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
    restaurant_with_missing_facts,
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
def test_missing_restaurant_facts_are_not_invented():
    """Missing restaurant facts remain unavailable instead of being guessed."""

    request = search_request(
        other_preferences=[
            "at least 4.5 stars"
        ]
    )

    candidate = (
        restaurant_with_missing_facts()
    )

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "alternative",
        "reasons": [
            "matches your selected cuisine",
            "! Google rating unavailable; requested at least 4.5/5",
            "! price unavailable",
            "! walk journey time unavailable",
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
        "BRNS-19: Missing facts are not invented",
        "decide_outcome()",
        "Checks that missing price, rating and route facts "
        "remain unavailable instead of being guessed, so the "
        "restaurant cannot become an exact match.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected
def test_ai_falls_back_to_next_provider():
    """If the first AI provider fails, BRNS tries the next provider."""

    original_chain = brns_ai.config.MODEL_CHAIN
    original_gemini = brns_ai._call_gemini
    original_openrouter = brns_ai._call_openrouter
    original_sleep = brns_ai.time.sleep

    calls = []

    valid_reply = {
        "cuisine": "japanese",
        "dietary": "none",
        "budget_band": "any",
        "budget_min": None,
        "budget_max": 20,
        "min_rating": None,
        "max_walk_minutes": 30,
        "max_drive_km": None,
        "eat_time": "now",
        "free_text_notes": "",
    }

    def fake_gemini(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(
            f"gemini/{model}"
        )

        return (
            False,
            "network error",
        )

    def fake_openrouter(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(
            f"openrouter/{model}"
        )

        return (
            True,
            json.dumps(
                valid_reply
            ),
        )

    try:
        brns_ai.config.MODEL_CHAIN = [
            {
                "provider": "gemini",
                "model": "primary-model",
            },
            {
                "provider": "openrouter",
                "model": "backup-model",
            },
        ]

        brns_ai._call_gemini = (
            fake_gemini
        )

        brns_ai._call_openrouter = (
            fake_openrouter
        )

        brns_ai.time.sleep = (
            lambda seconds: None
        )

        test_input = {
            "first_provider":
                "gemini/primary-model",

            "fallback_provider":
                "openrouter/backup-model",
        }

        expected = {
            "ok":
                True,

            "model_used":
                "openrouter/backup-model",

            "cuisine":
                "japanese",

            "call_order": [
                "gemini/primary-model",
                "openrouter/backup-model",
            ],
        }

        ok, result, model_used = (
            brns_ai.call_ai(
                {
                    "cuisine":
                        "japanese"
                }
            )
        )

        actual = {
            "ok":
                ok,

            "model_used":
                model_used,

            "cuisine":
                (
                    result.get(
                        "cuisine"
                    )
                    if ok
                    else None
                ),

            "call_order":
                calls,
        }

        show_case(
            "BRNS-20: AI provider fallback works",
            "call_ai()",
            "Checks that BRNS continues to the next configured "
            "AI provider when the first provider fails.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        brns_ai.config.MODEL_CHAIN = (
            original_chain
        )

        brns_ai._call_gemini = (
            original_gemini
        )

        brns_ai._call_openrouter = (
            original_openrouter
        )

        brns_ai.time.sleep = (
            original_sleep
        )


def test_all_ai_providers_can_fail_safely():
    """BRNS returns a controlled failure when every provider fails."""

    original_chain = brns_ai.config.MODEL_CHAIN
    original_gemini = brns_ai._call_gemini
    original_openrouter = brns_ai._call_openrouter
    original_sleep = brns_ai.time.sleep

    calls = []

    def fake_gemini(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(
            f"gemini/{model}"
        )

        return (
            False,
            "network error",
        )

    def fake_openrouter(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(
            f"openrouter/{model}"
        )

        return (
            False,
            "HTTP 503",
        )

    try:
        brns_ai.config.MODEL_CHAIN = [
            {
                "provider": "gemini",
                "model": "primary-model",
            },
            {
                "provider": "openrouter",
                "model": "backup-model",
            },
        ]

        brns_ai._call_gemini = (
            fake_gemini
        )

        brns_ai._call_openrouter = (
            fake_openrouter
        )

        brns_ai.time.sleep = (
            lambda seconds: None
        )

        test_input = {
            "gemini":
                "network failure",

            "openrouter":
                "HTTP 503",
        }

        expected = {
            "ok":
                False,

            "model_used":
                None,

            "error_returned":
                True,

            "call_order": [
                "gemini/primary-model",
                "openrouter/backup-model",
            ],
        }

        ok, result, model_used = (
            brns_ai.call_ai(
                {
                    "cuisine":
                        "japanese"
                }
            )
        )

        actual = {
            "ok":
                ok,

            "model_used":
                model_used,

            "error_returned":
                isinstance(
                    result,
                    str,
                ),

            "call_order":
                calls,
        }

        show_case(
            "BRNS-21: All AI providers fail safely",
            "call_ai()",
            "Checks that exhausting the AI fallback chain "
            "returns a controlled failure instead of crashing "
            "or inventing a recommendation.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        brns_ai.config.MODEL_CHAIN = (
            original_chain
        )

        brns_ai._call_gemini = (
            original_gemini
        )

        brns_ai._call_openrouter = (
            original_openrouter
        )

        brns_ai.time.sleep = (
            original_sleep
        )


def test_ai_ranking_accepts_all_grounded_reason_codes():
    """A detailed result may legitimately carry more than four facts."""
    original_chain = brns_ai.config.MODEL_CHAIN
    original_key = brns_ai.config.GEMINI_API_KEY
    original_gemini = brns_ai._call_gemini
    reason_codes = [
        "cuisine_match",
        "within_budget",
        "within_route",
        "well_rated",
        "vegetarian_options",
        "halal_hint_unofficial",
    ]

    try:
        brns_ai.config.MODEL_CHAIN = [
            {"provider": "gemini", "model": "test-model"},
        ]
        brns_ai.config.GEMINI_API_KEY = "test-key"
        brns_ai._call_gemini = lambda *_args: (
            True,
            json.dumps({
                "recommendations": [
                    {"id": 0, "reason_codes": reason_codes},
                ],
            }),
        )

        request = search_request()
        request["dietary_requirements"] = ["halal", "vegetarian"]
        candidate = restaurant()
        candidate["dietary_requirements"] = ["vegetarian"]
        candidate["halal_hint"] = True
        recommendation = brns_ai.recommend_candidates(request, [candidate])
        grounded = brns_logic._grounded_ai_reasons(
            brns_logic.normalize_candidate(candidate),
            request,
            recommendation[0]["reason_codes"],
            0,
        )
        actual = {
            "recommendation": recommendation,
            "grounded_reason_count": len(grounded),
        }
        expected = {
            "recommendation": [{"id": 0, "reason_codes": reason_codes}],
            "grounded_reason_count": 6,
        }

        show_case(
            "BRNS-22: Detailed AI evidence is accepted",
            "recommend_candidates()",
            "Checks that a restaurant satisfying many search facts does not "
            "invalidate the AI response and trigger unnecessary fallbacks.",
            {"reason_codes": reason_codes},
            expected,
            actual,
        )

        assert actual == expected
    finally:
        brns_ai.config.MODEL_CHAIN = original_chain
        brns_ai.config.GEMINI_API_KEY = original_key
        brns_ai._call_gemini = original_gemini


def test_brc_error_does_not_skip_later_candidates():
    """One provider error must not prevent later exact MUIS checks."""
    original_brns_main = sys.modules.pop("BRNS.main", None)
    original_brc_main = sys.modules.get("BRC.main")
    brc_stub = types.ModuleType("BRC.main")
    brc_stub.data_manager = types.SimpleNamespace(
        CLEAN_DATABASE_PATH=Path("missing-test-database.json"))
    brc_stub.run = lambda _record: None
    sys.modules["BRC.main"] = brc_stub
    brns_main = importlib.import_module("BRNS.main")
    candidates = []
    for index, name in enumerate(("Error Cafe", "MUIS Cafe", "Other Cafe")):
        candidate = restaurant()
        candidate["name"] = name
        candidate["halal_hint"] = True
        candidate["address"] = f"{index + 1} Test Street, Singapore 10000{index}"
        candidates.append(candidate)
    calls = []

    def fake_brc_run(record):
        calls.append(record["name"])
        if record["name"] == "Error Cafe":
            raise RuntimeError("temporary provider failure")
        checked = dict(record)
        if record["name"] == "MUIS Cafe":
            checked.update({
                "halal_certification": "official",
                "muis_check": {"status": "verified"},
                "cuisines": ["chinese"],
            })
        else:
            checked["muis_check"] = {"status": "not_verified"}
        return checked

    try:
        brns_main.brc_main.run = fake_brc_run
        request = search_request()
        request["dietary_requirements"] = ["halal"]
        recommendations = [
            {"id": index, "reason_codes": []}
            for index in range(len(candidates))
        ]
        checked, summary = brns_main.verify_halal_candidates(
            candidates, request, recommendations)
        actual = {
            "calls": calls,
            "errors": summary["errors"],
            "checked": summary["checked"],
            "verified": summary["verified"],
            "later_candidate_status": checked[1]["halal_certification"],
        }
        expected = {
            "calls": ["Error Cafe", "MUIS Cafe", "Other Cafe"],
            "errors": 1,
            "checked": 2,
            "verified": 1,
            "later_candidate_status": "official",
        }

        show_case(
            "BRNS-23: BRC candidate failures are isolated",
            "verify_halal_candidates()",
            "Checks that one temporary BRC error does not skip later "
            "restaurants that can still be matched to official MUIS data.",
            {"candidate_names": [item["name"] for item in candidates]},
            expected,
            actual,
        )

        assert actual == expected
    finally:
        sys.modules.pop("BRNS.main", None)
        if original_brns_main is not None:
            sys.modules["BRNS.main"] = original_brns_main
        if original_brc_main is None:
            sys.modules.pop("BRC.main", None)
        else:
            sys.modules["BRC.main"] = original_brc_main

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
    test_missing_restaurant_facts_are_not_invented,
    test_ai_falls_back_to_next_provider,
    test_all_ai_providers_can_fail_safely,
    test_ai_ranking_accepts_all_grounded_reason_codes,
    test_brc_error_does_not_skip_later_candidates,
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
