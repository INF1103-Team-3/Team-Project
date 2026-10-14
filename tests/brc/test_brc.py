"""Function tests for BiteFinder BRC halal verification logic."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS_ROOT))


from BRC import logic_manager as brc_logic
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


TESTS = (
    test_correct_outlet_can_be_verified,
    test_wrong_outlet_cannot_become_official_halal,
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