"""BRNS process-level black-box tests for BiteFinder."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))


from reporting import show_case

from blackbox_support import (
    PLACE_NAMES,
    assert_shows,
    clear_fixture_calls,
    close_blackbox_context,
    create_blackbox_context,
    fixture_bodies,
    fixture_paths,
    history,
    run_blackbox_tests,
    run_cli,
    search_request,
)


def test_brns_valid_json_shows_match_and_alternative():
    """Valid BRNS JSON produces one match and one alternative."""

    context = create_blackbox_context()

    try:
        request = search_request()

        output = run_cli(
            context,
            "BRNS",
            json.dumps(request),
        )

        assert_shows(
            context,
            output,
            "Matches (1)",
            "Alternatives (1)",
            PLACE_NAMES[0],
            PLACE_NAMES[1],
        )

        restaurant_path = (
            context["root"]
            / "BRNS/data/restaurants.json"
        )

        restaurant_text = (
            restaurant_path.read_text(
                encoding="utf-8"
            )
        )

        discovered = json.loads(
            restaurant_text
        )

        saved_history = history(
            context
        )

        actual = {
            "http_calls":
                fixture_paths(
                    context["fixture"]
                ),

            "history_count":
                len(saved_history),

            "top_match_place_ids":
                saved_history[0][
                    "top_match_place_ids"
                ],

            "restaurant_count":
                len(discovered),

            "first_restaurant": {
                "name":
                    discovered[0]["name"],

                "rating":
                    discovered[0]["g_rating"],

                "reviews":
                    discovered[0]["g_no_reviews"],

                "postal_code":
                    discovered[0]["postal_code"],

                "number":
                    discovered[0]["number"],

                "price_low":
                    discovered[0][
                        "avg_price_low_sgd"
                    ],

                "price_high":
                    discovered[0][
                        "avg_price_high_sgd"
                    ],

                "dietary":
                    discovered[0]["dietary"],

                "opening_hours":
                    discovered[0][
                        "opening_hours"
                    ]["monday"],

                "wheelchair_accessible":
                    discovered[0][
                        "wheelchair_accessible"
                    ],
            },

            "second_restaurant": {
                "dietary":
                    discovered[1]["dietary"],

                "wheelchair_accessible":
                    discovered[1][
                        "wheelchair_accessible"
                    ],
            },
        }

        expected = {
            "http_calls": [
                "/nearby",
                "/matrix",
                "/chat/completions",
            ],

            "history_count":
                1,

            "top_match_place_ids": [
                "test-place-1"
            ],

            "restaurant_count":
                2,

            "first_restaurant": {
                "name":
                    PLACE_NAMES[0],

                "rating":
                    "4.2",

                "reviews":
                    "125",

                "postal_code":
                    "123401",

                "number":
                    "61234001",

                "price_low":
                    5.0,

                "price_high":
                    8.0,

                "dietary":
                    [],

                "opening_hours": [
                    "0000",
                    "2359",
                ],

                "wheelchair_accessible":
                    True,
            },

            "second_restaurant": {
                "dietary": [
                    "vegetarian"
                ],

                "wheelchair_accessible":
                    False,
            },
        }

        show_case(
            "BB-BRNS-01: Valid BRNS request returns match and alternative",
            "BRNS/main.py process flow",
            "Runs BRNS from its JSON input boundary and verifies "
            "restaurant discovery, route checking, AI ranking, "
            "search history and restaurant persistence.",
            request,
            expected,
            actual,
        )

        assert actual == expected

        assert (
            '"monday": ["0000", "2359"]'
            in restaurant_text
        )

    finally:
        close_blackbox_context(
            context
        )


def test_brns_invalid_json_never_calls_places_or_saves_history():
    """Invalid BRNS input is rejected before external calls or persistence."""

    context = create_blackbox_context()

    try:
        invalid_cases = [
            (
                "{bad",
                "valid BIS search JSON",
            ),

            (
                json.dumps({
                    key: value
                    for key, value
                    in search_request().items()
                    if key != "traffic_aware"
                }),
                "ten BIS search fields",
            ),

            (
                json.dumps(
                    dict(
                        search_request(),
                        unexpected=True,
                    )
                ),
                "ten BIS search fields",
            ),

            (
                json.dumps(
                    search_request(
                        origin=dict(
                            search_request()[
                                "origin"
                            ],
                            latitude=50,
                        )
                    )
                ),
                "within Singapore",
            ),

            (
                json.dumps(
                    search_request(
                        max_travel_minutes=20
                    )
                ),
                "exactly one travel limit",
            ),

            (
                json.dumps(
                    search_request(
                        budget_per_person=-1
                    )
                ),
                "budget_per_person must be between",
            ),

            (
                json.dumps(
                    search_request(
                        dietary_requirements=
                            "halal"
                    )
                ),
                "must be lists",
            ),

            (
                json.dumps(
                    search_request(
                        mode="walk",
                        max_distance_km=None,
                        max_travel_minutes=20,
                        traffic_aware=True,
                    )
                ),
                "Live traffic",
            ),
        ]

        actual_results = []

        for payload, expected_message in invalid_cases:

            output = run_cli(
                context,
                "BRNS",
                payload,
            )

            assert_shows(
                context,
                output,
                expected_message,
            )

            actual_results.append({
                "expected_message_seen":
                    expected_message
                    in output,

                "http_calls":
                    list(
                        fixture_paths(
                            context[
                                "fixture"
                            ]
                        )
                    ),

                "history":
                    list(
                        history(
                            context
                        )
                    ),
            })

        expected = [
            {
                "expected_message_seen":
                    True,

                "http_calls":
                    [],

                "history":
                    [],
            }

            for _ in invalid_cases
        ]

        test_input = [
            {
                "payload":
                    payload[:80],

                "expected_message":
                    message,
            }

            for payload, message
            in invalid_cases
        ]

        show_case(
            "BB-BRNS-02: Invalid BRNS inputs stop at boundary",
            "BRNS/main.py input validation",
            "Sends malformed and invalid search payloads and "
            "confirms they are rejected before Places, routing, "
            "AI ranking or history writes.",
            test_input,
            expected,
            actual_results,
        )

        assert actual_results == expected

    finally:
        close_blackbox_context(
            context
        )


def test_brns_driving_traffic_changes_matrix_request():
    """Traffic-aware driving changes the route-matrix request."""

    context = create_blackbox_context()

    try:
        actual = []

        for traffic in (
            False,
            True,
        ):
            clear_fixture_calls(
                context["fixture"]
            )

            request = search_request(
                mode="drive",
                max_distance_km=None,
                max_travel_minutes=20,
                traffic_aware=traffic,
            )

            output = run_cli(
                context,
                "BRNS",
                json.dumps(request),
            )

            assert_shows(
                context,
                output,
                "min by drive",
            )

            matrix = fixture_bodies(
                context["fixture"],
                "/matrix",
            )

            actual.append({
                "traffic_aware":
                    traffic,

                "matrix_calls":
                    len(matrix),

                "routing_preference":
                    matrix[0].get(
                        "routingPreference"
                    ),
            })

        expected = [
            {
                "traffic_aware":
                    False,

                "matrix_calls":
                    1,

                "routing_preference":
                    None,
            },

            {
                "traffic_aware":
                    True,

                "matrix_calls":
                    1,

                "routing_preference":
                    "TRAFFIC_AWARE",
            },
        ]

        show_case(
            "BB-BRNS-03: Driving traffic changes matrix request",
            "BRNS/main.py driving route flow",
            "Runs driving searches with live traffic disabled "
            "and enabled, then checks the Routes request.",
            {
                "traffic_aware_values": [
                    False,
                    True,
                ]
            },
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_brns_transit_time_uses_verified_minutes():
    """Transit search uses TRANSIT routing and verified minutes."""

    context = create_blackbox_context()

    try:
        request = search_request(
            mode="transit",
            max_distance_km=None,
            max_travel_minutes=20,
        )

        output = run_cli(
            context,
            "BRNS",
            json.dumps(request),
        )

        assert_shows(
            context,
            output,
            "Matches (1)",
            "Alternatives (1)",
            "10 min by transit",
        )

        matrix = fixture_bodies(
            context["fixture"],
            "/matrix",
        )

        actual = {
            "matrix_calls":
                len(matrix),

            "travel_mode":
                matrix[0]["travelMode"],

            "routing_preference_present":
                "routingPreference"
                in matrix[0],

            "ten_minute_result_shown":
                "10 min by transit"
                in output,
        }

        expected = {
            "matrix_calls":
                1,

            "travel_mode":
                "TRANSIT",

            "routing_preference_present":
                False,

            "ten_minute_result_shown":
                True,
        }

        show_case(
            "BB-BRNS-04: Transit uses verified route minutes",
            "BRNS/main.py transit route flow",
            "Runs a transit search and verifies that the route "
            "matrix uses TRANSIT and the verified travel time "
            "is displayed to the user.",
            request,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_brns_invalid_ai_reply_does_not_save_search():
    """Malformed AI ranking output does not create search history."""

    context = create_blackbox_context()

    try:
        context[
            "fixture"
        ][
            "invalid_brns_ai"
        ] = True

        request = search_request()

        output = run_cli(
            context,
            "BRNS",
            json.dumps(request),
        )

        assert_shows(
            context,
            output,
            "BRNS AI could not recommend restaurants",
        )

        actual = {
            "history":
                history(context),

            "nearby_calls":
                fixture_paths(
                    context["fixture"]
                ).count(
                    "/nearby"
                ),

            "error_shown":
                (
                    "BRNS AI could not recommend restaurants"
                    in output
                ),
        }

        expected = {
            "history":
                [],

            "nearby_calls":
                1,

            "error_shown":
                True,
        }

        show_case(
            "BB-BRNS-05: Invalid AI ranking is not saved",
            "BRNS/main.py AI ranking flow",
            "Returns a malformed hardcoded AI ranking after "
            "restaurant discovery and verifies BRNS reports the "
            "failure without saving search history.",
            request,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


TESTS = (
    test_brns_valid_json_shows_match_and_alternative,
    test_brns_invalid_json_never_calls_places_or_saves_history,
    test_brns_driving_traffic_changes_matrix_request,
    test_brns_transit_time_uses_verified_minutes,
    test_brns_invalid_ai_reply_does_not_save_search,
)


def run_tests():
    """Run all BRNS black-box tests."""

    run_blackbox_tests(
        TESTS,
        "BRNS Black Box",
    )


if __name__ == "__main__":
    run_tests()