"""BIS-to-BRNS process-level black-box tests for BiteFinder."""

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
    close_blackbox_context,
    create_blackbox_context,
    fixture_bodies,
    fixture_paths,
    history,
    run_blackbox_tests,
    run_cli,
    seed_complete_user,
)


def test_bis_to_brns_retries_input_and_shows_route():
    """A BIS search reaches BRNS and displays a driving route."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        test_input = [
            "2",
            "tester@example.com",
            "/search",
            "0,0",
            "530912",
            "yes",
            "fly",
            "drive",
            "2",
            "20",
            "2",
            "none",
            "10",
            "",
            "yes",
            "1",
            "1",
            "",
            "/quit",
        ]

        output = run_cli(
            context,
            "BIS",
            test_input,
        )

        assert_shows(
            context,
            output,
            "Enter coordinates within Singapore.",
            "Found: 530912",
            "Choose walk, drive, or transit.",
            "Drive up to 20 min (live traffic)",
            "Found 1 match and 1 alternative",
            PLACE_NAMES[0],
            "Drive route to Near Cafe",
            "Head north",
        )

        paths = fixture_paths(
            context["fixture"]
        )

        prompts = [
            body[
                "messages"
            ][0][
                "content"
            ]

            for body
            in fixture_bodies(
                context["fixture"],
                "/chat/completions",
            )
        ]

        route_requests = (
            fixture_bodies(
                context["fixture"],
                "/matrix",
            )

            + fixture_bodies(
                context["fixture"],
                "/route",
            )
        )

        cache_path = (
            context["root"]
            / "data/geocode_cache.json"
        )

        cache = json.loads(
            cache_path.read_text(
                encoding="utf-8"
            )
        )

        saved_history = history(
            context
        )

        actual = {
            "geocode_calls":
                paths.count(
                    "/geocode"
                ),

            "nearby_calls":
                paths.count(
                    "/nearby"
                ),

            "matrix_calls":
                paths.count(
                    "/matrix"
                ),

            "route_calls":
                paths.count(
                    "/route"
                ),

            "ai_calls_at_least_two":
                (
                    paths.count(
                        "/chat/completions"
                    )
                    >= 2
                ),

            "search_interpretation_ai_used":
                any(
                    "Interpret today's restaurant wish"
                    in prompt

                    for prompt
                    in prompts
                ),

            "ranking_ai_used":
                any(
                    "Rank every supplied restaurant candidate"
                    in prompt

                    for prompt
                    in prompts
                ),

            "all_route_calls_traffic_aware":
                all(
                    body.get(
                        "routingPreference"
                    )
                    == "TRAFFIC_AWARE"

                    for body
                    in route_requests
                ),

            "history_count":
                len(
                    saved_history
                ),

            "top_match_place_ids":
                saved_history[0][
                    "top_match_place_ids"
                ],

            "cached_postal_code":
                cache[
                    "530912"
                ],
        }

        expected = {
            "geocode_calls":
                1,

            "nearby_calls":
                1,

            "matrix_calls":
                1,

            "route_calls":
                1,

            "ai_calls_at_least_two":
                True,

            "search_interpretation_ai_used":
                True,

            "ranking_ai_used":
                True,

            "all_route_calls_traffic_aware":
                True,

            "history_count":
                1,

            "top_match_place_ids": [
                "test-place-1"
            ],

            "cached_postal_code": [
                1.352,
                103.944,
            ],
        }

        show_case(
            "BB-FLOW-01: BIS search reaches BRNS and route service",
            "BIS/main.py -> BRNS/main.py process flow",
            "Runs a complete user search from BIS through BRNS, "
            "including input retries, geocoding, restaurant "
            "discovery, AI ranking, traffic-aware routing, route "
            "display, history and geocode caching.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_enter_starts_search_and_repeat_uses_same_choices_with_new_top_match():
    """Repeating a search can return a different top restaurant."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        context[
            "fixture"
        ][
            "six_matches"
        ] = True

        test_input = [
            "2",
            "tester@example.com",
            "/search",
            "1.352,103.944",
            "yes",
            "walk",
            "1",
            "2",
            "none",
            "10",
            "",
            "",
            "6",
            "",
            "/quit",
        ]

        output = run_cli(
            context,
            "BIS",
            test_input,
        )

        assert_shows(
            context,
            output,
            "Search with these choices?",
            "Found 5 matches",
            "Top match: Near Cafe.",
            "Top match: Sixth Cafe.",
        )

        ai_calls = fixture_bodies(
            context["fixture"],
            "/chat/completions",
        )

        recommendation_calls = [
            body

            for body
            in ai_calls

            if (
                "Rank every supplied restaurant candidate"
                in body[
                    "messages"
                ][0][
                    "content"
                ]
            )
        ]

        second_request = json.loads(
            recommendation_calls[1][
                "messages"
            ][1][
                "content"
            ]
        )

        saved_history = history(
            context
        )

        actual = {
            "searching_count":
                output.count(
                    "Searching restaurants..."
                ),

            "nearby_calls":
                fixture_paths(
                    context["fixture"]
                ).count(
                    "/nearby"
                ),

            "matrix_calls":
                fixture_paths(
                    context["fixture"]
                ).count(
                    "/matrix"
                ),

            "history_count":
                len(
                    saved_history
                ),

            "top_matches": [
                entry[
                    "top_match_place_ids"
                ][0]

                for entry
                in saved_history
            ],

            "ranking_ai_calls":
                len(
                    recommendation_calls
                ),

            "previous_restaurants_count":
                len(
                    second_request[
                        "previous_restaurants"
                    ]
                ),

            "first_previous_restaurant":
                second_request[
                    "previous_restaurants"
                ][0],
        }

        expected = {
            "searching_count":
                2,

            "nearby_calls":
                2,

            "matrix_calls":
                2,

            "history_count":
                2,

            "top_matches": [
                "test-place-1",
                "test-place-6",
            ],

            "ranking_ai_calls":
                2,

            "previous_restaurants_count":
                5,

            "first_previous_restaurant":
                "Near Cafe",
        }

        show_case(
            "BB-FLOW-02: Repeat search excludes previous restaurants",
            "BIS repeat-search -> BRNS ranking flow",
            "Runs the same search twice and verifies that the "
            "second BRNS ranking receives the previous restaurant "
            "list and returns a new top restaurant.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_repeat_explains_when_no_new_restaurants_are_available():
    """A repeated search explains when all matching results are exhausted."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        test_input = [
            "2",
            "tester@example.com",
            "/search",
            "1.352,103.944",
            "yes",
            "walk",
            "1",
            "2",
            "none",
            "10",
            "",
            "",
            "6",
            "",
            "/quit",
        ]

        output = run_cli(
            context,
            "BIS",
            test_input,
        )

        assert_shows(
            context,
            output,
            "No new restaurants found for these choices",
        )

        actual = {
            "message_shown":
                (
                    "No new restaurants found for these choices"
                    in output
                ),

            "searching_count":
                output.count(
                    "Searching restaurants..."
                ),

            "history_count":
                len(
                    history(
                        context
                    )
                ),
        }

        expected = {
            "message_shown":
                True,

            "searching_count":
                2,

            "history_count":
                2,
        }

        show_case(
            "BB-FLOW-03: Repeat search explains exhausted results",
            "BIS repeat-search -> BRNS flow",
            "Repeats a search without additional restaurants and "
            "verifies BiteFinder explains that no new choices remain.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


TESTS = (
    test_bis_to_brns_retries_input_and_shows_route,
    test_enter_starts_search_and_repeat_uses_same_choices_with_new_top_match,
    test_repeat_explains_when_no_new_restaurants_are_available,
)


def run_tests():
    """Run all BIS-to-BRNS black-box tests."""

    run_blackbox_tests(
        TESTS,
        "BIS to BRNS Black Box",
    )


if __name__ == "__main__":
    run_tests()