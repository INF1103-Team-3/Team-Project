"""Function tests for BiteFinder BRNS recommendation and ranking logic."""

import json
import importlib
import os
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


from BRNS import logic_manager as brns_logic  # noqa: E402
from BRNS import ai_manager as brns_ai  # noqa: E402
from reporting import show_case, show_summary  # noqa: E402

from sample_inputs import (  # noqa: E402
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

    test_input = ["at least 4.5 stars"]

    expected = 4.5

    actual = brns_logic.minimum_rating(test_input)

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

    test_input = ["Japanese only"]

    expected = ["japanese"]

    actual = brns_logic.hard_required_cuisines(test_input)

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

    test_input = halal_hint_restaurant()

    expected = "unofficial"

    actual = brns_logic.normalize_candidate(test_input)["halal_status"]

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

    test_input = verified_halal_restaurant()

    expected = "official"

    actual = brns_logic.normalize_candidate(test_input)["halal_status"]

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

    status, _, _ = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(budget_per_person=10)

    candidate = restaurant(avg_price=25)

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(disliked_cuisines=["japanese"])

    candidate = restaurant(cuisines=["japanese"])

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "reject",
        "reasons": ["contains a disliked cuisine"],
    }

    status, _, reasons = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(dietary_requirements=["halal"])

    candidate = restaurant(halal_status="unverified")

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "reject",
        "reasons": ["MUIS halal certification not verified"],
    }

    status, _, reasons = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(dietary_requirements=["halal"])

    candidate = brns_logic.normalize_candidate(verified_halal_restaurant())

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "match"

    status, _, _ = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(dietary_requirements=["vegetarian"])

    candidate = restaurant(dietary_requirements=[])

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = brns_logic.decide_outcome(
        candidate,
        request,
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

    request = search_request(max_travel_minutes=10)

    candidate = restaurant(walk_minutes=25)

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = "alternative"

    status, _, _ = brns_logic.decide_outcome(
        candidate,
        request,
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

    restaurants = ranking_restaurants()

    ai_response = valid_ai_recommendations()

    test_input = {
        "restaurant_names": [item["name"] for item in restaurants],
        "hardcoded_ai_response": ai_response,
    }

    expected = [
        1,
        0,
    ]

    actual = brns_logic.recommendation_order(
        restaurants,
        ai_response,
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

    restaurants = ranking_restaurants()

    ai_response = duplicate_ai_recommendations()

    test_input = {
        "restaurant_names": [item["name"] for item in restaurants],
        "hardcoded_ai_response": ai_response,
    }

    expected = "BRNS AI returned duplicate restaurant IDs."

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

    restaurants = ranking_restaurants()

    request = search_request()

    ai_response = valid_ai_recommendations()

    test_input = {
        "request": request,
        "hardcoded_ai_response": ai_response,
        "restaurant_names": [item["name"] for item in restaurants],
    }

    expected = [
        "Tokyo Choice",
        "Sakura Near",
    ]

    result = brns_logic.rank_restaurants(
        restaurants,
        request,
        recommendations=ai_response,
    )

    actual = [item["restaurant"]["name"] for item in result["matches"]]

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
        "weekly_hours": MONDAY_OPENING_HOURS,
        "time": MONDAY_NOON.isoformat(),
    }

    expected = True

    actual = brns_logic.open_now_from_weekly(
        MONDAY_OPENING_HOURS,
        MONDAY_NOON,
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
        "weekly_hours": MONDAY_OPENING_HOURS,
        "time": MONDAY_EVENING.isoformat(),
    }

    expected = False

    actual = brns_logic.open_now_from_weekly(
        MONDAY_OPENING_HOURS,
        MONDAY_EVENING,
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
                "restaurant": restaurant(
                    name="Lower",
                    rating=4.1,
                )
            },
            {
                "restaurant": restaurant(
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

    sorted_results = brns_logic.sort_results(
        results,
        "rating",
    )

    actual = sorted_results["matches"][0]["restaurant"]["name"]

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
                "restaurant": restaurant(
                    name="Far",
                    walk_meters=1500,
                )
            },
            {
                "restaurant": restaurant(
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

    sorted_results = brns_logic.sort_results(
        results,
        "distance",
    )

    actual = sorted_results["matches"][0]["restaurant"]["name"]

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

    request = search_request(other_preferences=["at least 4.5 stars"])

    candidate = restaurant_with_missing_facts()

    test_input = {
        "request": request,
        "restaurant": candidate,
    }

    expected = {
        "status": "alternative",
        "reasons": [
            "matches your selected cuisine",
            "! price unavailable",
            "! Google rating unavailable; requested at least 4.5/5",
            "! walk journey time unavailable",
        ],
    }

    status, _, reasons = brns_logic.decide_outcome(
        candidate,
        request,
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
        calls.append(f"gemini/{model}")

        return (
            False,
            "network error",
        )

    def fake_openrouter(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(f"openrouter/{model}")

        return (
            True,
            json.dumps(valid_reply),
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

        brns_ai._call_gemini = fake_gemini

        brns_ai._call_openrouter = fake_openrouter

        brns_ai.time.sleep = lambda seconds: None

        test_input = {
            "first_provider": "gemini/primary-model",
            "fallback_provider": "openrouter/backup-model",
        }

        expected = {
            "ok": True,
            "model_used": "openrouter/backup-model",
            "cuisine": "japanese",
            "call_order": [
                "gemini/primary-model",
                "openrouter/backup-model",
            ],
        }

        ok, result, model_used = brns_ai.call_ai({"cuisine": "japanese"})

        actual = {
            "ok": ok,
            "model_used": model_used,
            "cuisine": (result.get("cuisine") if ok else None),
            "call_order": calls,
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
        brns_ai.config.MODEL_CHAIN = original_chain

        brns_ai._call_gemini = original_gemini

        brns_ai._call_openrouter = original_openrouter

        brns_ai.time.sleep = original_sleep


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
        calls.append(f"gemini/{model}")

        return (
            False,
            "network error",
        )

    def fake_openrouter(
        model,
        system_prompt,
        user_text,
    ):
        calls.append(f"openrouter/{model}")

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

        brns_ai._call_gemini = fake_gemini

        brns_ai._call_openrouter = fake_openrouter

        brns_ai.time.sleep = lambda seconds: None

        test_input = {
            "gemini": "network failure",
            "openrouter": "HTTP 503",
        }

        expected = {
            "ok": False,
            "model_used": None,
            "error_returned": True,
            "call_order": [
                "gemini/primary-model",
                "openrouter/backup-model",
            ],
        }

        ok, result, model_used = brns_ai.call_ai({"cuisine": "japanese"})

        actual = {
            "ok": ok,
            "model_used": model_used,
            "error_returned": isinstance(
                result,
                str,
            ),
            "call_order": calls,
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
        brns_ai.config.MODEL_CHAIN = original_chain

        brns_ai._call_gemini = original_gemini

        brns_ai._call_openrouter = original_openrouter

        brns_ai.time.sleep = original_sleep


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
            json.dumps(
                {
                    "recommendations": [
                        {"id": 0, "reason_codes": reason_codes},
                    ],
                }
            ),
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
    original_brc_service_url = os.environ.pop("BRC_SERVICE_URL", None)
    brc_stub = types.ModuleType("BRC.main")
    brc_stub.data_manager = types.SimpleNamespace(
        CLEAN_DATABASE_PATH=Path("missing-test-database.json")
    )
    brc_stub.run = lambda _record: None
    sys.modules["BRC.main"] = brc_stub
    brns_main = importlib.import_module("BRNS.main")
    candidates = []
    for index, name in enumerate(("Error Cafe", "MUIS Cafe", "Other Cafe")):
        candidate = restaurant()
        candidate["name"] = name
        candidate["halal_hint"] = True
        candidate["address"] = (
            f"{index + 1} Test Street, Singapore 10000{index}"
        )
        candidates.append(candidate)
    calls = []

    def fake_brc_run(record):
        calls.append(record["name"])
        if record["name"] == "Error Cafe":
            raise RuntimeError("temporary provider failure")
        checked = dict(record)
        if record["name"] == "MUIS Cafe":
            checked.update(
                {
                    "halal_certification": "official",
                    "muis_check": {"status": "verified"},
                    "cuisines": ["chinese"],
                }
            )
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
            candidates, request, recommendations
        )
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
        if original_brc_service_url is not None:
            os.environ["BRC_SERVICE_URL"] = original_brc_service_url


def test_pre_discovery_strict_exclude_filters_before_limit_and_expands_pages():
    """Pre-discovery strict_exclude filters seen places and pulls 3 pages."""
    from unittest.mock import patch
    from BRNS import io_manager as brns_io
    from BRNS.classes.io.adapters.io_manager import IOManager
    from BRNS.classes.io.adapters.web_io_manager import WebIOManager
    from BRNS.classes.services.workflows.candidate_search import (
        CandidateSearch,
    )
    from common import debug_log as log

    origin = (1.300, 103.840)

    def raw_place(idx, name=None, address=None):
        addr = (
            address
            if address is not None
            else f"{idx} Orchard Rd, Singapore"
        )
        return {
            "id": f"pid-{idx}",
            "displayName": {"text": name or f"Venue {idx}"},
            "formattedAddress": addr,
            "location": {
                "latitude": 1.301 + idx * 0.0001,
                "longitude": 103.841,
            },
            "rating": 4.5,
            "userRatingCount": 120,
            "priceLevel": "PRICE_LEVEL_MODERATE",
            "types": ["japanese_restaurant"],
            "currentOpeningHours": {"openNow": True},
        }

    # 20 seen places across page 1, plus 20 fresh unseen across pages 2 & 3.
    # Include a candidate matching a name-only (empty address) prev entry.
    seen_page_1 = [raw_place(i) for i in range(20)]
    unseen_page_2 = [raw_place(20 + i) for i in range(15)]
    unseen_page_3 = [
        raw_place(35, name="Shared Branch", address="99 Tampines St"),
        *[raw_place(36 + i) for i in range(4)],
    ]
    pages_by_token = {
        None: {"places": seen_page_1, "nextPageToken": "tok-2"},
        "tok-2": {"places": unseen_page_2, "nextPageToken": "tok-3"},
        "tok-3": {"places": unseen_page_3},
    }
    text_call_tokens = []

    def fake_post(url, headers=None, json=None, timeout=None):
        if "computeRouteMatrix" in url:
            return types.SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: []
            )
        token = (json or {}).get("pageToken")
        text_call_tokens.append(token)
        payload = pages_by_token[token]
        return types.SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: payload
        )

    previous_restaurants = (
        [
            {
                "google_place_id": f"pid-{i}",
                "name": f"Renamed {i}",
                "address": "Old Address",
            }
            for i in range(10)
        ]
        + [
            {
                "google_place_id": "",
                "name": f"  venue {i} ",
                "address": f" {i} orchard rd, singapore ",
            }
            for i in range(10, 20)
        ]
        + [
            {
                "google_place_id": None,
                "name": "Shared Branch",
                "address": "",
            }
        ]
    )

    req = {
        "mode": "walk",
        "max_distance_km": 1.5,
        "max_travel_minutes": None,
        "cuisine": "japanese",
        "dietary_requirements": [],
        "other_preferences": [],
        "free_text": "",
        "budget_per_person": 50.0,
        "traffic_aware": False,
    }

    with (
        patch.object(brns_io.requests, "post", side_effect=fake_post),
        patch.object(brns_io.config, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(brns_io.config, "USE_LIVE_GOOGLE", True),
    ):
        candidates = brns_io.build_candidates(
            origin,
            req,
            [],
            previous_restaurants=previous_restaurants,
            strict_exclude=True,
        )

    # Verify generic nearby search supplements with fetch_open_places
    # (up to 3 pages) when filtering leaves < 5 open candidates.
    generic_req = dict(req, cuisine="none", budget_per_person=15.0)
    nearby_payload = {"places": [raw_place(i) for i in range(20)]}
    open_pages = {
        None: {
            "places": [raw_place(i) for i in range(18)],
            "nextPageToken": "open-2",
        },
        "open-2": {"places": [raw_place(100 + i) for i in range(6)]},
    }
    generic_urls = []

    def fake_post_generic(url, headers=None, json=None, timeout=None):
        if "computeRouteMatrix" in url:
            return types.SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: []
            )
        generic_urls.append((url, (json or {}).get("pageToken")))
        if "searchNearby" in url:
            return types.SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: nearby_payload
            )
        return types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: open_pages[(json or {}).get("pageToken")],
        )

    generic_prev = [
        {
            "google_place_id": f"pid-{i}",
            "name": f"Venue {i}",
            "address": f"{i} Orchard Rd, Singapore",
        }
        for i in range(18)
    ]
    with (
        patch.object(
            brns_io.requests, "post", side_effect=fake_post_generic
        ),
        patch.object(brns_io.config, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(brns_io.config, "USE_LIVE_GOOGLE", True),
    ):
        supplemented = brns_io.build_candidates(
            origin,
            generic_req,
            [],
            previous_restaurants=generic_prev,
            strict_exclude=True,
        )

    # Profile text leaving < 5 open unseen supplements with nearby search.
    profile_urls = []

    def fake_post_profile_supplement(
        url, headers=None, json=None, timeout=None
    ):
        if "computeRouteMatrix" in url:
            return types.SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: []
            )
        profile_urls.append(url)
        if "searchNearby" in url:
            return types.SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "places": [raw_place(i) for i in (2, 3, 4, 5)]
                },
            )
        return types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"places": [raw_place(0), raw_place(1)]},
        )

    with (
        patch.object(
            brns_io.requests,
            "post",
            side_effect=fake_post_profile_supplement,
        ),
        patch.object(brns_io.config, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(brns_io.config, "USE_LIVE_GOOGLE", True),
    ):
        profile_supplemented = brns_io.build_candidates(
            origin,
            req,
            [],
            previous_restaurants=[
                {
                    "google_place_id": "pid-0",
                    "name": "Venue 0",
                    "address": "0 Orchard Rd, Singapore",
                }
            ],
            strict_exclude=True,
        )

    # Verify offline filtering via CandidateSearch, IOManager, WebIOManager.
    all_day_hours = {
        day: [["0000", "2359"]]
        for day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    }
    saved_records = [
        {
            "google_place_id": "off-1",
            "name": "Offline Seen",
            "address": "1 Offline Rd",
            "opening_hours": all_day_hours,
        },
        {
            "google_place_id": "",
            "name": "Shared Branch",
            "address": "",
            "opening_hours": all_day_hours,
        },
        {
            "google_place_id": "off-2",
            "name": "Offline Fresh",
            "address": "2 Offline Rd",
            "opening_hours": all_day_hours,
        },
    ]
    fake_data = types.SimpleNamespace(
        load_candidate_records=lambda: saved_records
    )
    io_adapter = IOManager(
        brns_io,
        brns_logic.manager(),
        log,
        CandidateSearch(fake_data, brns_logic.manager(), brns_io, log),
    )
    web_io_adapter = WebIOManager(io_adapter)
    offline_req = {
        "origin": {
            "query": "Orchard",
            "label": "Orchard",
            "latitude": 1.300,
            "longitude": 103.840,
        },
        "mode": "walk",
        "max_distance_km": 1.5,
        "max_travel_minutes": None,
        "traffic_aware": False,
        "cuisine": "none",
        "budget_per_person": 15.0,
        "other_preferences": [],
        "dietary_requirements": [],
        "disliked_cuisines": [],
    }
    offline_prev = [
        {
            "google_place_id": "off-1",
            "name": "Offline Seen",
            "address": "1 Offline Rd",
        },
        {"google_place_id": None, "name": "Shared Branch", "address": ""},
    ]
    with patch.object(brns_io.config, "USE_LIVE_GOOGLE", False):
        offline_cands = io_adapter.find_candidates(
            offline_req,
            previous_restaurants=offline_prev,
            strict_exclude=True,
        )
        web_offline_cands = web_io_adapter.find_candidates(
            offline_req,
            previous_restaurants=offline_prev,
            strict_exclude=True,
        )

    returned_ids = {c["google_place_id"] for c in candidates}
    actual = {
        "candidate_count": len(candidates),
        "seen_overlap_count": len(
            returned_ids & {f"pid-{i}" for i in range(20)}
        ),
        "shared_branch_kept": "pid-35" in returned_ids,
        "text_page_tokens": text_call_tokens,
        "supplemented_count": len(supplemented),
        "supplemented_open_pages": [
            tok for url, tok in generic_urls if "searchText" in url
        ],
        "profile_supplemented_nearby_called": any(
            "searchNearby" in u for u in profile_urls
        ),
        "profile_supplemented_count": len(profile_supplemented),
        "offline_names": [c["name"] for c in offline_cands],
        "web_offline_names": [c["name"] for c in web_offline_cands],
    }
    expected = {
        "candidate_count": 20,
        "seen_overlap_count": 0,
        "shared_branch_kept": True,
        "text_page_tokens": [None, "tok-2", "tok-3"],
        "supplemented_count": 8,
        "supplemented_open_pages": [None, "open-2"],
        "profile_supplemented_nearby_called": True,
        "profile_supplemented_count": 5,
        "offline_names": ["Offline Fresh"],
        "web_offline_names": ["Offline Fresh"],
    }

    show_case(
        "BRNS-24: Pre-discovery strict_exclude filters before limit=20",
        "build_candidates(..., strict_exclude=True)",
        "Verifies seen venues are excluded before limit=20 sampling, "
        "name-only entries without addresses do not false-match, and "
        "multi-page/open backfill runs.",
        {"previous_count": len(previous_restaurants)},
        expected,
        actual,
    )
    assert actual == expected


def test_strict_post_ranking_excludes_matches_and_alternatives_before_slicing(
):
    """Post-ranking strict_exclude=True removes seen items before slicing."""
    request = search_request(cuisine="japanese", budget_per_person=20)
    candidates = [
        restaurant(
            google_place_id="m-seen-id",
            name="Seen Match ID",
            address="1 Rd",
        ),
        restaurant(
            google_place_id="m-seen-na",
            name="Seen Match Name",
            address="2 Rd",
        ),
        restaurant(
            google_place_id="m-fresh-1",
            name="Fresh Match 1",
            address="3 Rd",
        ),
        restaurant(
            google_place_id="m-fresh-2",
            name="Fresh Match 2",
            address="4 Rd",
        ),
        restaurant(
            google_place_id="a-seen-id",
            name="Seen Alt ID",
            address="5 Rd",
            avg_price=35,
        ),
        restaurant(
            google_place_id="a-fresh-1",
            name="Fresh Alt 1",
            address="6 Rd",
            avg_price=35,
        ),
        restaurant(
            google_place_id="a-fresh-2",
            name="Fresh Alt 2",
            address="7 Rd",
            avg_price=35,
        ),
    ]
    recommendations = [
        {"id": i, "reason_codes": []} for i in range(len(candidates))
    ]
    previous = [
        {
            "google_place_id": "m-seen-id",
            "name": "Different Label",
            "address": "Different Rd",
        },
        {
            "google_place_id": "",
            "name": " seen match name ",
            "address": " 2 rd ",
        },
        {
            "google_place_id": "a-seen-id",
            "name": "Seen Alt ID",
            "address": "5 Rd",
        },
    ]

    strict_result = brns_logic.rank_restaurants(
        candidates,
        request,
        recommendations=recommendations,
        previous_restaurants=previous,
        max_matches=2,
        max_alternatives=2,
        strict_exclude=True,
    )

    exhausted_result = brns_logic.rank_restaurants(
        [candidates[0], candidates[4]],
        request,
        recommendations=[
            {"id": 0, "reason_codes": []},
            {"id": 1, "reason_codes": []},
        ],
        previous_restaurants=previous,
        max_matches=5,
        max_alternatives=5,
        strict_exclude=True,
    )

    actual = {
        "matches": [
            item["restaurant"]["name"] for item in strict_result["matches"]
        ],
        "alternatives": [
            item["restaurant"]["name"]
            for item in strict_result["alternatives"]
        ],
        "new_count": strict_result["new_count"],
        "strict_exhausted_flag": strict_result["exhausted_previous"],
        "exhausted_matches": exhausted_result["matches"],
        "exhausted_alternatives": exhausted_result["alternatives"],
        "exhausted_new_count": exhausted_result["new_count"],
        "exhausted_flag": exhausted_result["exhausted_previous"],
    }
    expected = {
        "matches": ["Fresh Match 1", "Fresh Match 2"],
        "alternatives": ["Fresh Alt 1", "Fresh Alt 2"],
        "new_count": 4,
        "strict_exhausted_flag": False,
        "exhausted_matches": [],
        "exhausted_alternatives": [],
        "exhausted_new_count": 0,
        "exhausted_flag": True,
    }

    show_case(
        "BRNS-25: Strict post-ranking exclusion removes duplicates",
        "rank_restaurants(..., strict_exclude=True)",
        "Removes seen matches and alternatives before max_matches and "
        "max_alternatives slicing and reports exhausted_previous=True.",
        {"candidate_count": len(candidates), "previous_count": len(previous)},
        expected,
        actual,
    )
    assert actual == expected


def test_strict_exclude_false_preserves_existing_ranking_behavior():
    """Default strict_exclude=False sorts seen items behind unseen ones."""
    request = search_request(cuisine="japanese", budget_per_person=20)
    candidates = [
        restaurant(
            google_place_id="id-1", name="First Seen", address="1 Rd"
        ),
        restaurant(
            google_place_id="id-2", name="Second Unseen", address="2 Rd"
        ),
        restaurant(
            google_place_id="id-3",
            name="Alt Seen",
            address="3 Rd",
            avg_price=35,
        ),
    ]
    recommendations = [
        {"id": i, "reason_codes": []} for i in range(len(candidates))
    ]
    previous = [
        {
            "google_place_id": "id-1",
            "name": "Different Name",
            "address": "Other",
        },
        {"google_place_id": "", "name": "alt seen", "address": "3 rd"},
    ]

    default_res = brns_logic.rank_restaurants(
        candidates,
        request,
        recommendations=recommendations,
        previous_restaurants=previous,
        max_matches=5,
        max_alternatives=5,
    )
    all_seen_res = brns_logic.rank_restaurants(
        [candidates[0]],
        request,
        recommendations=[{"id": 0, "reason_codes": []}],
        previous_restaurants=previous,
        strict_exclude=False,
    )

    actual = {
        "matches_order": [
            item["restaurant"]["name"] for item in default_res["matches"]
        ],
        "default_new_count": default_res["new_count"],
        "has_exhausted_key": "exhausted_previous" in default_res,
        "all_seen_still_returned": [
            item["restaurant"]["name"] for item in all_seen_res["matches"]
        ],
        "all_seen_new_count": all_seen_res["new_count"],
    }
    expected = {
        "matches_order": ["Second Unseen", "First Seen"],
        "default_new_count": 1,
        "has_exhausted_key": False,
        "all_seen_still_returned": ["First Seen"],
        "all_seen_new_count": 0,
    }

    show_case(
        "BRNS-26: Default strict_exclude=False preserves repeat sorting",
        "rank_restaurants(..., strict_exclude=False)",
        "Verifies normal searches and CLI repeat still return seen "
        "restaurants sorted after unseen ones without removing them.",
        {"previous_count": len(previous)},
        expected,
        actual,
    )
    assert actual == expected


def test_workflow_and_service_exhausted_candidates_handling():
    """Workflow and service return clean dict on empty, raise on outage."""
    import inspect
    import requests
    from unittest.mock import patch
    from BRNS import io_manager as brns_io
    from BRNS.classes.data.helpers.search_history_scope import (
        SearchHistoryScope,
    )
    from BRNS.classes.io.adapters.io_manager import IOManager
    from BRNS.classes.io.contracts.candidate_io_interface import (
        CandidateIOInterface,
    )
    from BRNS.classes.services.workflows.candidate_search import (
        CandidateSearch,
    )
    from BRNS.classes.logic.contracts.brns_logic_manager_interface import (
        BRNSLogicManagerInterface,
    )
    from BRNS.classes.services.gateway.brns_gateway_interface import (
        BRNSGatewayInterface,
    )
    from BRNS.classes.services.gateway.brns_service import BRNSService
    from BRNS.classes.services.workflows.brns_recommendation_workflow import (
        BRNSRecommendationWorkflow,
    )
    from common import debug_log as log

    validated_request = {
        "origin": {
            "query": "Orchard",
            "label": "Orchard",
            "latitude": 1.300,
            "longitude": 103.840,
        },
        "mode": "walk",
        "max_distance_km": 1.5,
        "max_travel_minutes": None,
        "traffic_aware": False,
        "cuisine": "none",
        "budget_per_person": 20.0,
        "other_preferences": [],
        "dietary_requirements": [],
        "disliked_cuisines": [],
    }
    ai_calls = []

    def make_service(find_candidates_fn, last_failed_fn=lambda: False):
        io_stub = types.SimpleNamespace(
            accept_bis_json=lambda _payload: dict(validated_request),
            find_candidates=find_candidates_fn,
            last_discovery_failed=last_failed_fn,
            show_ai_ranking_start=lambda *_args: None,
            build_maps_link=lambda *_args: "https://maps.google.com",
        )
        ai_stub = types.SimpleNamespace(
            has_configured_provider=lambda: True,
            recommend_prepared=lambda *_args: ai_calls.append(1) or [],
        )
        logic_stub = brns_logic.manager()
        data_stub = types.SimpleNamespace(
            save_restaurants=lambda rows: len(rows),
            save_search_results=lambda *_args: True,
            load_user_history=lambda _uid: [],
            clear_user_history=lambda _uid: 0,
        )
        halal_stub = types.SimpleNamespace(
            verify=lambda c, _r, _rec: (c, None)
        )
        cfg = types.SimpleNamespace(
            USE_LIVE_GOOGLE=True,
            GOOGLE_MAPS_API_KEY="test-key",
            AI_CHAIN_TIMEOUT_SECONDS=30,
        )
        workflow = BRNSRecommendationWorkflow(
            io_stub, ai_stub, logic_stub, data_stub, halal_stub, cfg, log
        )
        return BRNSService(
            workflow=workflow,
            navigator=types.SimpleNamespace(route_to=lambda *_args: {}),
            logic_manager=logic_stub,
            data_manager=data_stub,
            history_scope=SearchHistoryScope(),
            io_manager=io_stub,
            logger=log,
        )

    prev = [
        {
            "google_place_id": "p-1",
            "name": "Seen Spot",
            "address": "1 Orchard Rd",
        }
    ]

    # 1. Exhausted strict refresh returns clean dict without calling AI
    svc_exhausted = make_service(lambda *_a, **_kw: [], lambda: False)
    exhausted_res = svc_exhausted.search(
        validated_request,
        previous_restaurants=prev,
        user_id="u-1",
        strict_exclude=True,
    )

    # 2. Normal empty search (strict_exclude=False) still raises RuntimeError
    normal_error = None
    try:
        svc_exhausted.search(validated_request, user_id="u-1")
    except RuntimeError as exc:
        normal_error = str(exc)

    # 3. API outage during strict refresh still raises RuntimeError
    fake_data = types.SimpleNamespace(load_candidate_records=lambda: [])
    real_io = IOManager(
        brns_io,
        brns_logic.manager(),
        log,
        CandidateSearch(fake_data, brns_logic.manager(), brns_io, log),
    )
    outage_workflow = BRNSRecommendationWorkflow(
        real_io,
        types.SimpleNamespace(
            has_configured_provider=lambda: True,
            recommend_prepared=lambda *_a: [],
        ),
        brns_logic.manager(),
        types.SimpleNamespace(
            save_restaurants=lambda rows: len(rows),
            save_search_results=lambda *_a: True,
        ),
        types.SimpleNamespace(verify=lambda c, _r, _rec: (c, None)),
        types.SimpleNamespace(
            USE_LIVE_GOOGLE=True,
            GOOGLE_MAPS_API_KEY="test-key",
            AI_CHAIN_TIMEOUT_SECONDS=30,
        ),
        log,
    )
    outage_error = None
    with (
        patch.object(
            brns_io.requests,
            "post",
            side_effect=requests.RequestException("503"),
        ),
        patch.object(brns_io.config, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(brns_io.config, "USE_LIVE_GOOGLE", True),
    ):
        try:
            outage_workflow.search(
                validated_request,
                previous_restaurants=prev,
                strict_exclude=True,
            )
        except RuntimeError as exc:
            outage_error = str(exc)

    gateway_params = inspect.signature(BRNSGatewayInterface.search).parameters
    io_params = inspect.signature(
        CandidateIOInterface.find_candidates
    ).parameters
    logic_params = inspect.signature(
        BRNSLogicManagerInterface.rank_restaurants
    ).parameters
    interface_defaults = {
        "gateway_strict_default": gateway_params["strict_exclude"].default,
        "candidate_io_strict_default": io_params["strict_exclude"].default,
        "logic_strict_default": logic_params["strict_exclude"].default,
    }

    actual = {
        "exhausted_res": exhausted_res,
        "ai_calls_on_exhausted": len(ai_calls),
        "normal_error": normal_error,
        "outage_error": outage_error,
        **interface_defaults,
    }
    expected = {
        "exhausted_res": {
            "matches": [],
            "alternatives": [],
            "hidden": 0,
            "new_count": 0,
            "exhausted_previous": True,
            "mode": "walk",
            "origin": validated_request["origin"],
        },
        "ai_calls_on_exhausted": 0,
        "normal_error": (
            "No restaurants found, or restaurant search is unavailable."
        ),
        "outage_error": (
            "No restaurants found, or restaurant search is unavailable."
        ),
        "gateway_strict_default": False,
        "candidate_io_strict_default": False,
        "logic_strict_default": False,
    }

    show_case(
        "BRNS-27: Exhausted refresh returns dict while outages raise",
        "BRNSService.search() / BRNSRecommendationWorkflow.search()",
        "Verifies strict refresh returns clean exhausted_previous=True dict "
        "when filtered empty, while normal searches and outages raise.",
        {"previous_count": len(prev)},
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
    test_missing_restaurant_facts_are_not_invented,
    test_ai_falls_back_to_next_provider,
    test_all_ai_providers_can_fail_safely,
    test_ai_ranking_accepts_all_grounded_reason_codes,
    test_brc_error_does_not_skip_later_candidates,
    test_pre_discovery_strict_exclude_filters_before_limit_and_expands_pages,
    test_strict_post_ranking_excludes_matches_and_alternatives_before_slicing,
    test_strict_exclude_false_preserves_existing_ranking_behavior,
    test_workflow_and_service_exhausted_candidates_handling,
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

            print(f"\nFAILED: {test.__name__}: {error}")

    show_summary(
        "BRNS",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
