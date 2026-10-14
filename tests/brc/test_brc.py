"""Function tests for BiteFinder BRC halal verification logic."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))


from BRC import logic_manager as brc_logic
from BRC import ai_manager as brc_ai
from reporting import show_case, show_summary


def official_listing():
    """Return one official MUIS restaurant record."""

    return {
        "name":
            "Sakura Test Cafe",

        "postal_code":
            "828761",

        "address":
            "1 Test Street #01-01 Singapore 828761",

        "cuisine":
            [
                "japanese"
            ],

        "dietary":
            [
                "halal"
            ],

        "halal_certification":
            "official",

        "muis": {
            "certificate_number":
                "TEST-123",

            "listing_id":
                "LISTING-1",

            "source_url":
                "https://halal.muis.gov.sg/halal/establishments",

            "valid_until":
                "2099-12-31",
        },
    }


def test_correct_outlet_can_be_verified():
    """A restaurant matching the official outlet may become verified halal."""

    restaurant = {
        "name":
            "Sakura Test Cafe",

        "postal_code":
            "828761",

        "address":
            "1 Test Street #01-01 Singapore 828761",

        "dietary":
            [],

        "halal_certification":
            "none",
    }

    database = [
        official_listing()
    ]

    matches = [
        "TEST-123"
    ]

    result = (
        brc_logic.check_restaurants(
            [
                restaurant
            ],
            database,
            matches,
        )[0]
    )

    actual = {
        "halal_certification":
            result[
                "halal_certification"
            ],

        "muis_status":
            result[
                "muis_check"
            ][
                "status"
            ],

        "halal_added":
            (
                "halal"
                in result[
                    "dietary"
                ]
            ),
    }

    expected = {
        "halal_certification":
            "official",

        "muis_status":
            "verified",

        "halal_added":
            True,
    }

    show_case(
        "BRC-01: Correct MUIS outlet is verified",
        "check_restaurants()",
        "Checks that official halal status is only granted "
        "when the restaurant identity matches the MUIS outlet.",
        {
            "restaurant":
                restaurant,

            "certificate":
                "TEST-123",
        },
        expected,
        actual,
    )

    assert actual == expected


def test_wrong_outlet_cannot_become_official_halal():
    """A certificate belonging to another outlet must be rejected."""

    restaurant = {
        "name":
            "Sakura Test Cafe",

        "postal_code":
            "999999",

        "address":
            "99 Wrong Street #01-01 Singapore 999999",

        "dietary":
            [
                "halal"
            ],

        "halal_certification":
            "official",
    }

    database = [
        official_listing()
    ]

    matches = [
        "TEST-123"
    ]

    result = (
        brc_logic.check_restaurants(
            [
                restaurant
            ],
            database,
            matches,
        )[0]
    )

    actual = {
        "halal_certification":
            result[
                "halal_certification"
            ],

        "muis_status":
            result[
                "muis_check"
            ][
                "status"
            ],

        "halal_present":
            (
                "halal"
                in result.get(
                    "dietary",
                    [],
                )
            ),
    }

    expected = {
        "halal_certification":
            "none",

        "muis_status":
            "not_verified",

        "halal_present":
            False,
    }

    show_case(
        "BRC-02: Wrong MUIS outlet is rejected",
        "check_restaurants()",
        "Checks that an AI-selected certificate cannot make "
        "the wrong restaurant outlet officially halal.",
        {
            "restaurant":
                restaurant,

            "certificate":
                "TEST-123",
        },
        expected,
        actual,
    )

    assert actual == expected


def test_brc_ai_falls_back_to_groq_after_invalid_gemini():
    """BRC should continue when Gemini returns unusable structured data."""
    original_gemini = brc_ai._call_gemini
    original_chat = brc_ai._call_chat_completions
    calls = []
    manager = {
        "providers": [
            {"provider": "gemini", "model": "gemini-test"},
            {"provider": "groq", "model": "groq-test"},
        ],
        "chain_timeout_seconds": 10,
        "timeout_seconds": 2,
    }

    def fake_gemini(_prompt, _manager, model):
        calls.append(f"gemini/{model}")
        return "not json"

    def fake_chat(_prompt, _manager, provider, model, _timeout):
        calls.append(f"{provider}/{model}")
        return json.dumps({"certificate_number": "TEST-123"})

    try:
        brc_ai._call_gemini = fake_gemini
        brc_ai._call_chat_completions = fake_chat
        raw = brc_ai.call_api(
            "match this outlet",
            manager,
            validator=lambda text: (
                json.loads(text).get("certificate_number") == "TEST-123"),
        )
        actual = {
            "calls": calls,
            "certificate_number": json.loads(raw)["certificate_number"],
        }
        expected = {
            "calls": ["gemini/gemini-test", "groq/groq-test"],
            "certificate_number": "TEST-123",
        }

        show_case(
            "BRC-03: Invalid Gemini output falls back to Groq",
            "call_api()",
            "Checks that BRC rejects invalid structured output and obtains a "
            "valid outlet decision from its next configured provider.",
            {"providers": manager["providers"]},
            expected,
            actual,
        )

        assert actual == expected
    finally:
        brc_ai._call_gemini = original_gemini
        brc_ai._call_chat_completions = original_chat


def test_brc_ai_falls_back_after_gemini_provider_error():
    """A Gemini service error should advance to OpenRouter."""
    original_gemini = brc_ai._call_gemini
    original_chat = brc_ai._call_chat_completions
    calls = []
    manager = {
        "providers": [
            {"provider": "gemini", "model": "gemini-test"},
            {"provider": "openrouter", "model": "openrouter-test"},
        ],
        "chain_timeout_seconds": 10,
        "timeout_seconds": 2,
    }

    def failed_gemini(_prompt, _manager, model):
        calls.append(f"gemini/{model}")
        raise RuntimeError("503 unavailable")

    def successful_openrouter(_prompt, _manager, provider, model, _timeout):
        calls.append(f"{provider}/{model}")
        return json.dumps({"certificate_number": None})

    try:
        brc_ai._call_gemini = failed_gemini
        brc_ai._call_chat_completions = successful_openrouter
        raw = brc_ai.call_api("match this outlet", manager)
        actual = {
            "calls": calls,
            "certificate_number": json.loads(raw)["certificate_number"],
        }
        expected = {
            "calls": [
                "gemini/gemini-test",
                "openrouter/openrouter-test",
            ],
            "certificate_number": None,
        }

        show_case(
            "BRC-04: Gemini service errors use OpenRouter fallback",
            "call_api()",
            "Checks that a provider error such as HTTP 503 does not stop an "
            "ambiguous MUIS outlet check while another provider is available.",
            {"providers": manager["providers"]},
            expected,
            actual,
        )

        assert actual == expected
    finally:
        brc_ai._call_gemini = original_gemini
        brc_ai._call_chat_completions = original_chat


TESTS = (
    test_correct_outlet_can_be_verified,
    test_wrong_outlet_cannot_become_official_halal,
    test_brc_ai_falls_back_to_groq_after_invalid_gemini,
    test_brc_ai_falls_back_after_gemini_provider_error,
)


def run_tests():
    """Run all BRC tests and print a teacher-facing summary."""

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

    show_summary(
        "BRC",
        len(TESTS),
        failures,
    )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
