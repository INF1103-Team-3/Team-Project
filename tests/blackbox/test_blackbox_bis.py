"""Process-level black-box tests for the BiteFinder BIS application."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))


from reporting import show_case

from blackbox_support import (
    TEST_PASSWORD,
    assert_shows,
    clear_fixture_calls,
    close_blackbox_context,
    create_blackbox_context,
    fixture_paths,
    history,
    run_blackbox_tests,
    run_cli,
    seed_complete_user,
)


def read_users(context):
    """Read BIS users saved during a black-box test."""

    path = (
        context["root"]
        / "BIS"
        / "data"
        / "users.json"
    )

    if not path.exists():
        return {}

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def read_credentials(context):
    """Read BIS password credentials saved during a black-box test."""

    path = (
        context["root"]
        / "BIS"
        / "data"
        / "credentials.json"
    )

    if not path.exists():
        return {}

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def save_user(context, user):
    """Save one BIS user into the isolated black-box environment."""

    path = (
        context["root"]
        / "BIS"
        / "data"
        / "users.json"
    )

    path.write_text(
        json.dumps(
            {
                user["userID"]:
                    user,
            }
        ),
        encoding="utf-8",
    )


def test_signup_rejects_bad_email_without_saving_it():
    """Invalid signup email is rejected and only the valid account is saved."""

    context = create_blackbox_context()

    try:
        context["env"]["AI_BYPASS"] = "true"

        test_input = [
            "1",
            "invalid-email",
            "1",
            "new@example.com",
            "New User",
            TEST_PASSWORD,
            TEST_PASSWORD,
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
            "Enter a valid email address.",
            "Signed up.",
        )

        accounts = read_users(
            context
        )

        actual = {
            "saved_emails": [
                user["email"]
                for user
                in accounts.values()
            ],
            "external_calls":
                fixture_paths(
                    context["fixture"]
                ),
        }

        expected = {
            "saved_emails": [
                "new@example.com"
            ],
            "external_calls": [],
        }

        show_case(
            "BB-BIS-01: Invalid signup email rejected",
            "BIS main.py signup flow",
            "Runs the BIS signup process as a user and checks that "
            "an invalid email is rejected without being saved.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_profile_setup_retries_invalid_budget():
    """Profile setup retries an invalid budget and stores the corrected value."""

    context = create_blackbox_context()

    try:
        context["env"]["AI_BYPASS"] = "true"

        test_input = [
            "1",
            "new@example.com",
            "New User",
            TEST_PASSWORD,
            TEST_PASSWORD,
            "Tampines",
            "yes",
            "2 km",
            "abc",
            "10",
            "none",
            "none",
            "none",
            "none",
            "/cancel",
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
            "What is your budget per person?",
            "Preferences saved.",
            "Profile complete.",
            "Search cancelled",
        )

        accounts = read_users(
            context
        )

        profile = next(
            iter(
                accounts.values()
            )
        )["preferences"]

        actual = {
            "account_count":
                len(accounts),

            "location":
                profile["location"],

            "budget_per_person":
                profile[
                    "budget_per_person"
                ],

            "max_distance_km":
                profile[
                    "max_distance_km"
                ],

            "search_history":
                history(context),
        }

        expected = {
            "account_count": 1,
            "location": [
                "tampines"
            ],
            "budget_per_person": 10,
            "max_distance_km": 2,
            "search_history": [],
        }

        show_case(
            "BB-BIS-02: Invalid profile budget retried",
            "BIS profile setup flow",
            "Runs profile creation with an invalid budget first, "
            "then checks that the corrected numeric value is saved.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_bare_travel_number_gets_unit_and_space_separated_cuisines():
    """A bare travel number requests a unit and two cuisines are stored."""

    context = create_blackbox_context()

    try:
        context["env"]["AI_BYPASS"] = "true"

        test_input = [
            "1",
            "new@example.com",
            "New User",
            TEST_PASSWORD,
            TEST_PASSWORD,
            "Tampines",
            "yes",
            "20",
            "2",
            "10",
            "none",
            "western italian",
            "none",
            "",
            "/cancel",
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
            "What unit did you mean for 20?",
            "Choose 1 for km or 2 for minutes",
            "Profile complete.",
            "Search cancelled",
        )

        accounts = read_users(
            context
        )

        profile = next(
            iter(
                accounts.values()
            )
        )["preferences"]

        actual = {
            "travel_minutes":
                profile[
                    "max_travel_time_minutes"
                ],

            "distance_km":
                profile[
                    "max_distance_km"
                ],

            "liked_cuisines":
                profile[
                    "liked_cuisines"
                ],

            "other_preferences":
                profile[
                    "other_preferences"
                ],
        }

        expected = {
            "travel_minutes": 20,
            "distance_km": 1,
            "liked_cuisines": [
                "western",
                "italian",
            ],
            "other_preferences": [],
        }

        show_case(
            "BB-BIS-03: Travel unit and cuisines processed",
            "BIS profile setup flow",
            "Checks that BIS asks for the missing travel unit and "
            "stores multiple space-separated cuisine preferences.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_written_travel_number_requires_explicit_unit_choice():
    """A written travel number still requires explicit unit confirmation."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(
            context
        )

        user["preferences"][
            "max_distance_km"
        ] = None

        user["preferences"][
            "max_travel_time_minutes"
        ] = None

        save_user(
            context,
            user,
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "ten",
            "2",
            "yes",
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
            "How far are you willing to travel?",
            "What unit did you mean for 10?",
            "Use 10 mins for your travel preference?",
        )

        accounts = read_users(
            context
        )

        profile = accounts[
            user["userID"]
        ]["preferences"]

        actual = {
            "travel_minutes":
                profile[
                    "max_travel_time_minutes"
                ],

            "distance_km":
                profile[
                    "max_distance_km"
                ],

            "external_calls":
                fixture_paths(
                    context["fixture"]
                ),
        }

        expected = {
            "travel_minutes": 10,
            "distance_km": 0.5,
            "external_calls": [
                "/chat/completions"
            ],
        }

        show_case(
            "BB-BIS-04: Written travel number requires unit",
            "BIS profile update flow",
            "Checks that a written number interpreted by AI still "
            "requires the user to explicitly select the travel unit.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_declined_written_travel_interpretation_is_not_saved():
    """Declining the interpreted travel value leaves travel preferences empty."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(
            context
        )

        user["preferences"][
            "max_distance_km"
        ] = None

        user["preferences"][
            "max_travel_time_minutes"
        ] = None

        save_user(
            context,
            user,
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "ten",
            "1",
            "no",
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
            "What unit did you mean for 10?",
            "No preference update was applied",
        )

        accounts = read_users(
            context
        )

        profile = accounts[
            user["userID"]
        ]["preferences"]

        actual = {
            "distance_km":
                profile[
                    "max_distance_km"
                ],

            "travel_minutes":
                profile[
                    "max_travel_time_minutes"
                ],
        }

        expected = {
            "distance_km": None,
            "travel_minutes": None,
        }

        show_case(
            "BB-BIS-05: Declined travel interpretation not saved",
            "BIS profile update flow",
            "Checks that BIS does not modify travel preferences "
            "when the user rejects the interpreted value.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_ai_unit_conflict_with_explicit_minutes_is_rejected():
    """AI cannot override an explicitly entered travel unit."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(
            context
        )

        user["preferences"][
            "max_distance_km"
        ] = None

        user["preferences"][
            "max_travel_time_minutes"
        ] = None

        save_user(
            context,
            user,
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "ten minutes",
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
            "Could not confirm the travel unit",
        )

        accounts = read_users(
            context
        )

        profile = accounts[
            user["userID"]
        ]["preferences"]

        actual = {
            "distance_km":
                profile[
                    "max_distance_km"
                ],

            "travel_minutes":
                profile[
                    "max_travel_time_minutes"
                ],
        }

        expected = {
            "distance_km": None,
            "travel_minutes": None,
        }

        show_case(
            "BB-BIS-06: Explicit travel unit protected",
            "BIS profile update flow",
            "Checks that an AI interpretation cannot silently "
            "override a travel unit explicitly supplied by the user.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_ai_extracted_locations_are_saved_after_confirmation():
    """Multiple AI-extracted locations are saved only after confirmation."""

    context = create_blackbox_context()

    try:
        test_input = [
            "1",
            "new@example.com",
            "New User",
            TEST_PASSWORD,
            TEST_PASSWORD,
            "punggol sengkang nex",
            "yes",
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
            "Add these locations: Punggol, Sengkang, Nex?",
            "Preferences saved.",
        )

        accounts = read_users(
            context
        )

        profile = next(
            iter(
                accounts.values()
            )
        )["preferences"]

        calls = fixture_paths(
            context["fixture"]
        )

        actual = {
            "locations":
                profile["location"],

            "ai_call_count":
                calls.count(
                    "/chat/completions"
                ),
        }

        expected = {
            "locations": [
                "punggol",
                "sengkang",
                "nex",
            ],
            "ai_call_count": 2,
        }

        show_case(
            "BB-BIS-07: AI-extracted locations confirmed",
            "BIS profile setup flow",
            "Checks that multiple locations extracted through AI "
            "are shown to the user and saved only after confirmation.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_declined_location_list_is_not_saved():
    """Rejecting AI-extracted locations leaves the profile location empty."""

    context = create_blackbox_context()

    try:
        test_input = [
            "1",
            "new@example.com",
            "New User",
            TEST_PASSWORD,
            TEST_PASSWORD,
            "punggol sengkang nex",
            "no",
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
            "Add these locations: Punggol, Sengkang, Nex?",
            "No preference update was applied",
        )

        accounts = read_users(
            context
        )

        profile = next(
            iter(
                accounts.values()
            )
        )["preferences"]

        expected = None
        actual = profile["location"]

        show_case(
            "BB-BIS-08: Declined location list not saved",
            "BIS profile setup flow",
            "Checks that AI-extracted locations do not modify "
            "the profile when the user rejects them.",
            test_input,
            expected,
            actual,
        )

        assert actual is expected

    finally:
        close_blackbox_context(
            context
        )


def test_ai_corrects_cuisine_typo_only_after_confirmation():
    """Cuisine typo correction and extracted cuisines require confirmation."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(
            context
        )

        user["preferences"][
            "liked_cuisines"
        ] = None

        user["preferences"][
            "disliked_cuisines"
        ] = None

        user["preferences"][
            "other_preferences"
        ] = None

        save_user(
            context,
            user,
        )

        (
            context["root"]
            / "BIS"
            / "data"
            / "profile_state.json"
        ).write_text(
            "{}",
            encoding="utf-8",
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "wesaten italian",
            "yes",
            "yes",
            "none",
            "",
            "/cancel",
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
            "Use 'western italian' instead?",
            "Save likes as western, italian?",
            "Profile complete.",
        )

        accounts = read_users(
            context
        )

        profile = accounts[
            user["userID"]
        ]["preferences"]

        calls = fixture_paths(
            context["fixture"]
        )

        actual = {
            "liked_cuisines":
                profile[
                    "liked_cuisines"
                ],

            "other_preferences":
                profile[
                    "other_preferences"
                ],

            "ai_call_count":
                calls.count(
                    "/chat/completions"
                ),
        }

        expected = {
            "liked_cuisines": [
                "western",
                "italian",
            ],
            "other_preferences": [],
            "ai_call_count": 2,
        }

        show_case(
            "BB-BIS-09: Cuisine typo corrected after confirmation",
            "BIS profile update flow",
            "Checks that AI spelling correction and cuisine extraction "
            "are both confirmed before the preferences are saved.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_declined_cuisine_correction_does_not_save():
    """Rejecting a cuisine correction leaves the liked-cuisine field unchanged."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(
            context
        )

        user["preferences"][
            "liked_cuisines"
        ] = None

        save_user(
            context,
            user,
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "wesaten italian",
            "no",
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
            "Use 'western italian' instead?",
            "No preference update was applied",
        )

        accounts = read_users(
            context
        )

        actual = {
            "liked_cuisines":
                accounts[
                    user["userID"]
                ]["preferences"][
                    "liked_cuisines"
                ],

            "external_calls":
                fixture_paths(
                    context["fixture"]
                ),
        }

        expected = {
            "liked_cuisines":
                None,

            "external_calls": [
                "/chat/completions"
            ],
        }

        show_case(
            "BB-BIS-10: Declined cuisine correction not saved",
            "BIS profile update flow",
            "Checks that rejecting an AI spelling correction "
            "leaves the original cuisine preference unchanged.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_invalid_search_answers_retry_and_valid_search_is_saved():
    """Invalid search answers are retried before valid choices are stored."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        context["env"][
            "AI_BYPASS"
        ] = "true"

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "/search",
            "1.352,103.944",
            "yes",
            "fly",
            "walk",
            "9",
            "1",
            "0",
            "2",
            "none",
            "0",
            "10",
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
            "Choose walk, drive, or transit.",
            "Choose 1 or 2",
            "max_distance_km must be between",
            "budget_per_person must be between",
            "Walk up to 2.0 km",
            "restaurant search skipped",
        )

        state_path = (
            context["root"]
            / "BIS"
            / "data"
            / "profile_state.json"
        )

        state = json.loads(
            state_path.read_text(
                encoding="utf-8"
            )
        )

        actual = {
            "search_completed":
                state["search"][
                    "blackbox-user"
                ]["completed"],

            "search_history":
                history(context),

            "external_calls":
                fixture_paths(
                    context["fixture"]
                ),
        }

        expected = {
            "search_completed": True,
            "search_history": [],
            "external_calls": [],
        }

        show_case(
            "BB-BIS-11: Invalid search answers retried",
            "BIS /search flow",
            "Runs the search form with invalid answers before "
            "valid corrections and checks that only valid search "
            "choices are accepted.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_transit_search_uses_profile_time_when_enter_pressed():
    """Transit search uses the saved profile travel time when Enter is pressed."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        context["env"][
            "AI_BYPASS"
        ] = "true"

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "/search",
            "1.352,103.944",
            "yes",
            "transit",
            "",
            "none",
            "10",
            "",
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
            "[Enter = 40 min from profile]",
            "Transit up to 40 min",
            "restaurant search skipped",
        )

        actual = {
            "search_history":
                history(context),

            "summary_contains_profile_time":
                (
                    "Transit up to 40 min"
                    in output
                ),
        }

        expected = {
            "search_history": [],
            "summary_contains_profile_time":
                True,
        }

        show_case(
            "BB-BIS-12: Transit uses saved profile time",
            "BIS /search flow",
            "Checks that pressing Enter for transit duration uses "
            "the user's saved 40-minute travel preference.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_drive_search_uses_profile_time_when_enter_pressed():
    """Driving search uses the saved profile travel time when Enter is pressed."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        context["env"][
            "AI_BYPASS"
        ] = "true"

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "/search",
            "1.352,103.944",
            "yes",
            "drive",
            "2",
            "",
            "",
            "none",
            "10",
            "",
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
            "[Enter = 40 min from profile]",
            "Drive up to 40 min",
            "restaurant search skipped",
        )

        actual = {
            "search_history":
                history(context),

            "summary_contains_profile_time":
                (
                    "Drive up to 40 min"
                    in output
                ),
        }

        expected = {
            "search_history": [],
            "summary_contains_profile_time":
                True,
        }

        show_case(
            "BB-BIS-13: Drive uses saved profile time",
            "BIS /search flow",
            "Checks that pressing Enter for driving duration uses "
            "the user's saved 40-minute travel preference.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_ai_search_interpretation_can_be_declined_before_brns():
    """Rejecting the AI search interpretation stops before BRNS."""

    context = create_blackbox_context()

    try:
        seed_complete_user(
            context
        )

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "/search",
            "1.352,103.944",
            "yes",
            "walk",
            "1",
            "2",
            "none",
            "10",
            "",
            "no",
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
            "Today's search",
            "Search with these choices?",
            "Search cancelled",
        )

        assert (
            "Your profile is saved"
            not in output
        )

        assert (
            "Profile saved. Goodbye!"
            not in output
        )

        assert (
            "Goodbye!"
            in output
        )

        actual = {
            "external_calls":
                fixture_paths(
                    context["fixture"]
                ),

            "search_history":
                history(context),

            "goodbye_shown":
                "Goodbye!" in output,
        }

        expected = {
            "external_calls": [
                "/chat/completions"
            ],

            "search_history": [],

            "goodbye_shown":
                True,
        }

        show_case(
            "BB-BIS-14: AI search interpretation declined",
            "BIS /search flow",
            "Checks that rejecting the AI-interpreted search "
            "stops the workflow before restaurant search or BRNS.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(
            context
        )


def test_signup_rejects_short_and_mismatched_passwords():
    """CLI signup enforces password length and confirmation before saving."""

    context = create_blackbox_context()

    try:
        context["env"]["AI_BYPASS"] = "true"

        test_input = [
            "1",
            "new@example.com",
            "New User",
            "short",
            "validpass1",
            "different1",
            "validpass1",
            "validpass1",
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
            "Password must be 6–128 characters.",
            "Passwords do not match.",
            "Signed up.",
        )

        accounts = read_users(context)
        credentials = read_credentials(context)
        user_id = next(iter(accounts))
        cred = credentials.get(user_id, {})

        actual = {
            "saved_emails": [u["email"] for u in accounts.values()],
            "has_salt": isinstance(cred.get("password_salt"), str),
            "has_hash": isinstance(cred.get("password_hash"), str),
            "plaintext_absent": "validpass1" not in json.dumps(credentials),
        }
        expected = {
            "saved_emails": ["new@example.com"],
            "has_salt": True,
            "has_hash": True,
            "plaintext_absent": True,
        }

        show_case(
            "BB-BIS-15: Signup password validation",
            "BIS main.py signup password flow",
            "Checks that short or mismatched passwords retry cleanly and "
            "only a salted hash is persisted in credentials.json.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(context)


def test_signin_rejects_wrong_password_and_allows_retry():
    """CLI sign-in checks saved passwords even when SMTP_BYPASS is enabled."""

    context = create_blackbox_context()

    try:
        seed_complete_user(context)

        test_input = [
            "2",
            "tester@example.com",
            "wrong-password",
            TEST_PASSWORD,
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
            "Incorrect password.",
            "Hi Tester!",
        )

        actual = {
            "rejected_wrong_password": "Incorrect password." in output,
            "signed_in": "Hi Tester!" in output,
        }
        expected = {
            "rejected_wrong_password": True,
            "signed_in": True,
        }

        show_case(
            "BB-BIS-16: Sign-in rejects wrong password",
            "BIS main.py sign-in flow",
            "Checks that a wrong password is rejected and the correct "
            "password completes sign-in.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(context)


def test_legacy_passwordless_user_enrolls_password_on_signin():
    """Existing passwordless users set a password during sign-in."""

    context = create_blackbox_context()

    try:
        user = seed_complete_user(context, password=None)

        test_input = [
            "2",
            "tester@example.com",
            "enrolled-secret-7",
            "enrolled-secret-7",
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
            "No password is set for this account yet.",
            "Password saved.",
            "Hi Tester!",
        )

        from BIS.classes.password_hasher import PasswordHasher

        credentials = read_credentials(context)
        saved_cred = credentials.get(user["userID"])

        actual = {
            "prompted_to_create": "No password is set for this account yet." in output,
            "credential_saved": saved_cred is not None,
            "password_verified": (
                PasswordHasher().verify("enrolled-secret-7", saved_cred)
                if saved_cred else False
            ),
        }
        expected = {
            "prompted_to_create": True,
            "credential_saved": True,
            "password_verified": True,
        }

        show_case(
            "BB-BIS-17: Legacy account password enrollment",
            "BIS main.py sign-in enrollment flow",
            "Checks that an account without saved credentials creates and "
            "saves a password on sign-in.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(context)


def test_change_password_command_verifies_current_and_updates_hash():
    """Users can change their password via /edit password and sign in with it."""

    context = create_blackbox_context()

    try:
        seed_complete_user(context)

        test_input = [
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "/edit password",
            "wrong-current",
            "/cancel",
            "/password",
            TEST_PASSWORD,
            "short",
            "updated-secret-99",
            "mismatch-secret-99",
            "updated-secret-99",
            "updated-secret-99",
            "/logout",
            "2",
            "tester@example.com",
            TEST_PASSWORD,
            "updated-secret-99",
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
            "Password unchanged.",
            "Password updated.",
            "Logged out.",
            "Incorrect password.",
        )

        actual = {
            "cancelled_keeps_old": "Password unchanged." in output,
            "updated_password": "Password updated." in output,
            "old_password_rejected_after_logout": output.count("Incorrect password.") >= 2,
            "re_authenticated": output.count("Hi Tester!") == 2,
        }
        expected = {
            "cancelled_keeps_old": True,
            "updated_password": True,
            "old_password_rejected_after_logout": True,
            "re_authenticated": True,
        }

        show_case(
            "BB-BIS-18: Password change inside active session",
            "BIS /edit password & /password flow",
            "Checks that changing password requires the current password, "
            "updates credentials, and rejects the old password after logout.",
            test_input,
            expected,
            actual,
        )

        assert actual == expected

    finally:
        close_blackbox_context(context)


TESTS = (
    test_signup_rejects_bad_email_without_saving_it,
    test_profile_setup_retries_invalid_budget,
    test_bare_travel_number_gets_unit_and_space_separated_cuisines,
    test_written_travel_number_requires_explicit_unit_choice,
    test_declined_written_travel_interpretation_is_not_saved,
    test_ai_unit_conflict_with_explicit_minutes_is_rejected,
    test_ai_extracted_locations_are_saved_after_confirmation,
    test_declined_location_list_is_not_saved,
    test_ai_corrects_cuisine_typo_only_after_confirmation,
    test_declined_cuisine_correction_does_not_save,
    test_invalid_search_answers_retry_and_valid_search_is_saved,
    test_transit_search_uses_profile_time_when_enter_pressed,
    test_drive_search_uses_profile_time_when_enter_pressed,
    test_ai_search_interpretation_can_be_declined_before_brns,
    test_signup_rejects_short_and_mismatched_passwords,
    test_signin_rejects_wrong_password_and_allows_retry,
    test_legacy_passwordless_user_enrolls_password_on_signin,
    test_change_password_command_verifies_current_and_updates_hash,
)


def run_tests():
    """Run all BIS black-box tests."""

    run_blackbox_tests(
        TESTS,
        "BIS Black Box",
    )


if __name__ == "__main__":
    run_tests()
