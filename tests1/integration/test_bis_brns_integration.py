"""Integration tests for the BiteFinder BIS-to-BRNS request boundary."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(TESTS_ROOT))


from BIS import io_manager as bis_io
from BIS import logic_manager as bis_logic
from BRNS import io_manager as brns_io
from BRNS import logic_manager as brns_logic
from reporting import show_case, show_summary
from sources.profile_schema import empty_preferences


def search_request(**changes):
    """Return one valid BIS-to-BRNS search request."""

    request = {
        "origin": {
            "query": "pasir ris mall",
            "label": "Pasir Ris Mall",
            "latitude": 1.372,
            "longitude": 103.95,
        },

        "mode": "walk",
        "max_distance_km": 2.0,
        "max_travel_minutes": None,
        "traffic_aware": False,

        "cuisine": "malay",
        "budget_per_person": 10.0,

        "other_preferences": [
            "spicy food"
        ],

        "dietary_requirements": [
            "halal"
        ],

        "disliked_cuisines": [],
    }

    request.update(
        changes
    )

    return request


def recommendation(*ids):
    """Return a hardcoded AI restaurant ordering."""

    return [
        {
            "id": index,
            "reason_codes": [],
        }

        for index
        in ids
    ]


def test_valid_bis_request_crosses_brns_boundary_unchanged():
    """A valid BIS request is accepted by BRNS without changing meaning."""

    test_input = (
        search_request()
    )

    expected = (
        bis_logic.validate_search_request(
            test_input
        )
    )

    actual = (
        brns_io.accept_bis_json(
            expected
        )
    )

    show_case(
        "INT-01: Valid BIS request accepted by BRNS",
        "BIS.validate_search_request() -> BRNS.accept_bis_json()",
        "Checks that the structured search request produced by BIS "
        "is accepted by BRNS without losing or changing confirmed choices.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_serialized_bis_json_is_accepted_by_brns():
    """The BIS request can cross the process boundary as JSON text."""

    request = (
        bis_logic.validate_search_request(
            search_request()
        )
    )

    test_input = json.dumps(
        request
    )

    expected = request

    actual = (
        brns_io.accept_bis_json(
            test_input
        )
    )

    show_case(
        "INT-02: Serialized BIS JSON accepted",
        "BRNS.accept_bis_json()",
        "Checks the BIS-to-BRNS data boundary by serializing "
        "the validated request to JSON before BRNS reads it.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_invalid_search_mode_is_rejected_by_both_systems():
    """BIS and BRNS reject the same unsupported travel mode."""

    test_input = (
        search_request(
            mode="fly"
        )
    )

    expected = {
        "BIS": "rejected",
        "BRNS": "rejected",
    }

    actual = {}

    try:
        bis_logic.validate_search_request(
            test_input
        )

        actual["BIS"] = "accepted"

    except ValueError:
        actual["BIS"] = "rejected"

    try:
        brns_io.accept_bis_json(
            test_input
        )

        actual["BRNS"] = "accepted"

    except ValueError:
        actual["BRNS"] = "rejected"

    show_case(
        "INT-03: Invalid travel mode rejected at both boundaries",
        "BIS.validate_search_request() + BRNS.accept_bis_json()",
        "Confirms that BIS and BRNS enforce the same allowed "
        "travel-mode contract.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_transit_time_contract_is_shared_by_bis_and_brns():
    """Transit uses a time limit rather than a distance limit."""

    valid = search_request(
        mode="transit",
        max_distance_km=None,
        max_travel_minutes=45,
        traffic_aware=False,
    )

    invalid = deepcopy(
        valid
    )

    invalid[
        "max_distance_km"
    ] = 5.0

    test_input = {
        "valid_transit":
            valid,

        "invalid_transit_with_distance":
            invalid,
    }

    expected = {
        "valid_BIS":
            "accepted",

        "valid_BRNS":
            "accepted",

        "invalid_BIS":
            "rejected",

        "invalid_BRNS":
            "rejected",
    }

    actual = {}

    try:
        bis_logic.validate_search_request(
            valid
        )

        actual[
            "valid_BIS"
        ] = "accepted"

    except ValueError:
        actual[
            "valid_BIS"
        ] = "rejected"

    try:
        brns_io.accept_bis_json(
            valid
        )

        actual[
            "valid_BRNS"
        ] = "accepted"

    except ValueError:
        actual[
            "valid_BRNS"
        ] = "rejected"

    try:
        bis_logic.validate_search_request(
            invalid
        )

        actual[
            "invalid_BIS"
        ] = "accepted"

    except ValueError:
        actual[
            "invalid_BIS"
        ] = "rejected"

    try:
        brns_io.accept_bis_json(
            invalid
        )

        actual[
            "invalid_BRNS"
        ] = "accepted"

    except ValueError:
        actual[
            "invalid_BRNS"
        ] = "rejected"

    show_case(
        "INT-04: Transit time contract preserved",
        "BIS.validate_search_request() + BRNS.accept_bis_json()",
        "Verifies that both modules require transit searches "
        "to use a travel-time limit rather than distance.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_live_traffic_contract_is_shared_by_bis_and_brns():
    """Live traffic is valid only for driving searches with a time limit."""

    valid = search_request(
        mode="drive",
        max_distance_km=None,
        max_travel_minutes=20,
        traffic_aware=True,
    )

    invalid = deepcopy(
        valid
    )

    invalid[
        "mode"
    ] = "walk"

    test_input = {
        "valid_drive":
            valid,

        "invalid_walk":
            invalid,
    }

    expected = {
        "valid_BIS":
            "accepted",

        "valid_BRNS":
            "accepted",

        "invalid_BIS":
            "rejected",

        "invalid_BRNS":
            "rejected",
    }

    actual = {}

    cases = (
        (
            "valid_BIS",
            valid,
            bis_logic.validate_search_request,
        ),

        (
            "valid_BRNS",
            valid,
            brns_io.accept_bis_json,
        ),

        (
            "invalid_BIS",
            invalid,
            bis_logic.validate_search_request,
        ),

        (
            "invalid_BRNS",
            invalid,
            brns_io.accept_bis_json,
        ),
    )

    for key, payload, validator in cases:

        try:
            validator(
                payload
            )

            actual[
                key
            ] = "accepted"

        except ValueError:
            actual[
                key
            ] = "rejected"

    show_case(
        "INT-05: Live-traffic contract preserved",
        "BIS.validate_search_request() + BRNS.accept_bis_json()",
        "Checks that both modules allow live traffic only "
        "for driving searches using a travel-time limit.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_bis_collected_drive_request_is_accepted_by_brns():
    """A request assembled by BIS IO passes into BRNS correctly."""

    profile = empty_preferences()

    profile.update(
        location=[
            "pasir ris"
        ],

        max_distance_km=
            2.0,

        max_travel_time_minutes=
            40.0,

        budget_per_person=
            10.0,

        dietary_requirements=[
            "halal"
        ],

        liked_cuisines=[
            "malay"
        ],

        disliked_cuisines=[],

        other_preferences=[],
    )

    user = {
        "preferences":
            profile,
    }

    with (
        patch.object(
            bis_io,
            "ask_search_location",
            return_value=
                search_request()[
                    "origin"
                ],
        ),

        patch.object(
            bis_io,
            "ask_search_mode",
            return_value=
                "drive",
        ),

        patch.object(
            bis_io,
            "ask_search_limit",
            return_value=
                (
                    None,
                    25,
                ),
        ),

        patch.object(
            bis_io,
            "ask_drive_traffic",
            return_value=
                True,
        ),

        patch.object(
            bis_io,
            "ask_search_cuisine",
            return_value=
                "malay",
        ),

        patch.object(
            bis_io,
            "ask_search_budget",
            return_value=
                10,
        ),

        patch.object(
            bis_io,
            "ask_search_wishes",
            return_value={
                "selected": [
                    "spicy food"
                ],

                "text": "",
            },
        ),
    ):

        collected = (
            bis_io.collect_search(
                user,
                {
                    "ai_bypass":
                        False
                },
            )
        )

    validated = (
        bis_logic.validate_search_request(
            collected[
                "request"
            ]
        )
    )

    accepted = (
        brns_io.accept_bis_json(
            validated
        )
    )

    test_input = (
        collected[
            "request"
        ]
    )

    expected = {
        "mode":
            "drive",

        "max_travel_minutes":
            25,

        "max_distance_km":
            None,

        "traffic_aware":
            True,

        "dietary_requirements": [
            "halal"
        ],
    }

    actual = {
        "mode":
            accepted[
                "mode"
            ],

        "max_travel_minutes":
            accepted[
                "max_travel_minutes"
            ],

        "max_distance_km":
            accepted[
                "max_distance_km"
            ],

        "traffic_aware":
            accepted[
                "traffic_aware"
            ],

        "dietary_requirements":
            accepted[
                "dietary_requirements"
            ],
    }

    show_case(
        "INT-06: BIS collected request reaches BRNS",
        "BIS.collect_search() -> BIS.validate_search_request() -> BRNS.accept_bis_json()",
        "Checks an actual BIS-collected driving request through "
        "the full structured request boundary into BRNS.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_hardcoded_ai_order_is_combined_with_brns_business_rules():
    """Hardcoded AI ordering is verified before BRNS classification."""

    request = search_request(
        cuisine="none",
        dietary_requirements=[],
        other_preferences=[],
    )

    candidates = [
        {
            "name":
                "Within Budget",

            "address":
                "1 Test Road",

            "cuisines": [
                "malay"
            ],

            "dietary_requirements":
                [],

            "avg_price":
                8,

            "walk_meters":
                500,

            "walk_source":
                "route",
        },

        {
            "name":
                "Over Budget",

            "address":
                "2 Test Road",

            "cuisines": [
                "malay"
            ],

            "dietary_requirements":
                [],

            "avg_price":
                25,

            "walk_meters":
                700,

            "walk_source":
                "route",
        },
    ]

    ai_response = (
        recommendation(
            0,
            1,
        )
    )

    test_input = {
        "BIS_request":
            request,

        "hardcoded_AI_order":
            ai_response,

        "restaurants": [
            item[
                "name"
            ]

            for item
            in candidates
        ],
    }

    validated = (
        bis_logic.validate_search_request(
            request
        )
    )

    accepted = (
        brns_io.accept_bis_json(
            validated
        )
    )

    results = (
        brns_logic.rank_restaurants(
            candidates,
            accepted,
            recommendations=
                ai_response,
        )
    )

    expected = {
        "matches": [
            "Within Budget"
        ],

        "alternatives": [
            "Over Budget"
        ],
    }

    actual = {
        "matches": [
            item[
                "restaurant"
            ][
                "name"
            ]

            for item
            in results[
                "matches"
            ]
        ],

        "alternatives": [
            item[
                "restaurant"
            ][
                "name"
            ]

            for item
            in results[
                "alternatives"
            ]
        ],
    }

    show_case(
        "INT-07: AI ordering and BRNS rules work together",
        "BIS.validate_search_request() -> BRNS.accept_bis_json() -> BRNS.rank_restaurants()",
        "Passes a BIS request and hardcoded AI ordering into BRNS, "
        "then verifies deterministic budget rules still control "
        "the final recommendation outcome.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_halal_requirement_survives_bis_to_brns_boundary():
    """A halal requirement remains mandatory after the handoff."""

    request = search_request(
        cuisine="none",
        other_preferences=[],
        dietary_requirements=[
            "halal"
        ],
    )

    unverified = {
        "name":
            "Unverified Cafe",

        "address":
            "1 Test Road",

        "cuisines": [
            "malay"
        ],

        "dietary_requirements":
            [],

        "halal_status":
            "unverified",

        "avg_price":
            8,

        "walk_meters":
            500,

        "walk_source":
            "route",
    }

    verified = {
        "name":
            "Verified Cafe",

        "address":
            "2 Test Road",

        "cuisines": [
            "malay"
        ],

        "dietary_requirements": [
            "halal"
        ],

        "halal_status":
            "official",

        "halal_certification":
            "official",

        "muis_check": {
            "status":
                "verified"
        },

        "avg_price":
            8,

        "walk_meters":
            600,

        "walk_source":
            "route",
    }

    accepted = (
        brns_io.accept_bis_json(
            bis_logic.validate_search_request(
                request
            )
        )
    )

    unverified_status, _, _ = (
        brns_logic.decide_outcome(
            brns_logic.normalize_candidate(
                unverified
            ),
            accepted,
        )
    )

    verified_status, _, _ = (
        brns_logic.decide_outcome(
            brns_logic.normalize_candidate(
                verified
            ),
            accepted,
        )
    )

    test_input = {
        "BIS_dietary_requirements":
            request[
                "dietary_requirements"
            ],

        "unverified_restaurant":
            unverified[
                "name"
            ],

        "verified_restaurant":
            verified[
                "name"
            ],
    }

    expected = {
        "BRNS_dietary_requirements": [
            "halal"
        ],

        "unverified_status":
            "reject",

        "verified_status":
            "match",
    }

    actual = {
        "BRNS_dietary_requirements":
            accepted[
                "dietary_requirements"
            ],

        "unverified_status":
            unverified_status,

        "verified_status":
            verified_status,
    }

    show_case(
        "INT-08: Halal requirement survives BIS-to-BRNS handoff",
        "BIS.validate_search_request() -> BRNS.accept_bis_json() -> BRNS.decide_outcome()",
        "Confirms that the halal restriction is preserved across "
        "the system boundary and still controls BRNS recommendation decisions.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_repeat_search_prefers_unseen_match_without_changing_request():
    """Repeat ranking prefers an unseen match without changing requirements."""

    request = search_request(
        cuisine="none",
        dietary_requirements=[],
        other_preferences=[],
    )

    original_request = deepcopy(
        request
    )

    candidates = [
        {
            "name":
                "First Cafe",

            "address":
                "1 Test Road",

            "cuisines":
                [],

            "dietary_requirements":
                [],

            "avg_price":
                8,

            "walk_meters":
                500,

            "walk_source":
                "route",
        },

        {
            "name":
                "Second Cafe",

            "address":
                "2 Test Road",

            "cuisines":
                [],

            "dietary_requirements":
                [],

            "avg_price":
                8,

            "walk_meters":
                800,

            "walk_source":
                "route",
        },
    ]

    accepted = (
        brns_io.accept_bis_json(
            bis_logic.validate_search_request(
                request
            )
        )
    )

    order = (
        recommendation(
            0,
            1,
        )
    )

    first = (
        brns_logic.rank_restaurants(
            candidates,
            accepted,
            order,
        )
    )

    repeated = (
        brns_logic.rank_restaurants(
            candidates,
            accepted,
            order,
            previous_restaurants=[
                first[
                    "matches"
                ][0][
                    "restaurant"
                ]
            ],
        )
    )

    test_input = {
        "request":
            request,

        "previous_top_match":
            first[
                "matches"
            ][0][
                "restaurant"
            ][
                "name"
            ],
    }

    expected = {
        "first_top_match":
            "First Cafe",

        "repeat_top_match":
            "Second Cafe",

        "request_unchanged":
            True,
    }

    actual = {
        "first_top_match":
            first[
                "matches"
            ][0][
                "restaurant"
            ][
                "name"
            ],

        "repeat_top_match":
            repeated[
                "matches"
            ][0][
                "restaurant"
            ][
                "name"
            ],

        "request_unchanged":
            request
            == original_request,
    }

    show_case(
        "INT-09: Repeat search prefers unseen restaurant",
        "BRNS.rank_restaurants() with BIS request",
        "Checks that BRNS can prefer a new restaurant on a repeat "
        "search without changing the user's original BIS requirements.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


def test_no_cuisine_choice_crosses_boundary_without_cuisine_penalty():
    """No cuisine preference stays optional after BIS-to-BRNS handoff."""

    request = search_request(
        cuisine="none",
        dietary_requirements=[],
        other_preferences=[],
    )

    candidate = {
        "name":
            "Malay Cafe",

        "cuisines": [
            "malay"
        ],

        "dietary_requirements":
            [],

        "halal_status":
            "unverified",

        "avg_price":
            8,

        "walk_meters":
            500,

        "walk_source":
            "route",
    }

    accepted = (
        brns_io.accept_bis_json(
            bis_logic.validate_search_request(
                request
            )
        )
    )

    outcome, _, reasons = (
        brns_logic.decide_outcome(
            candidate,
            accepted,
        )
    )

    test_input = {
        "BIS_cuisine":
            request[
                "cuisine"
            ],

        "restaurant_cuisines":
            candidate[
                "cuisines"
            ],
    }

    expected = {
        "BRNS_cuisine":
            "none",

        "outcome":
            "match",

        "cuisine_penalty_present":
            False,
    }

    actual = {
        "BRNS_cuisine":
            accepted[
                "cuisine"
            ],

        "outcome":
            outcome,

        "cuisine_penalty_present":
            any(
                "cuisine"
                in reason.lower()

                for reason
                in reasons
            ),
    }

    show_case(
        "INT-10: No-cuisine choice preserved",
        "BIS.validate_search_request() -> BRNS.accept_bis_json() -> BRNS.decide_outcome()",
        "Confirms that choosing no cuisine in BIS stays optional "
        "in BRNS and does not create an artificial cuisine mismatch.",
        test_input,
        expected,
        actual,
    )

    assert actual == expected


TESTS = (
    test_valid_bis_request_crosses_brns_boundary_unchanged,
    test_serialized_bis_json_is_accepted_by_brns,
    test_invalid_search_mode_is_rejected_by_both_systems,
    test_transit_time_contract_is_shared_by_bis_and_brns,
    test_live_traffic_contract_is_shared_by_bis_and_brns,
    test_bis_collected_drive_request_is_accepted_by_brns,
    test_hardcoded_ai_order_is_combined_with_brns_business_rules,
    test_halal_requirement_survives_bis_to_brns_boundary,
    test_repeat_search_prefers_unseen_match_without_changing_request,
    test_no_cuisine_choice_crosses_boundary_without_cuisine_penalty,
)


def run_tests():
    """Run all BIS-to-BRNS integration tests."""

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
                f"{type(error).__name__}: "
                f"{error}"
            )

    show_summary(
        "BIS to BRNS Integration",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()