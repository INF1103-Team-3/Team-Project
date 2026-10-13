"""Reusable hardcoded inputs for BiteFinder BRNS function tests."""

from datetime import datetime, timedelta, timezone


SINGAPORE_TIMEZONE = timezone(timedelta(hours=8))

MONDAY_NOON = datetime(
    2026,
    10,
    12,
    12,
    0,
    tzinfo=SINGAPORE_TIMEZONE,
)

MONDAY_EVENING = datetime(
    2026,
    10,
    12,
    20,
    0,
    tzinfo=SINGAPORE_TIMEZONE,
)

MONDAY_OPENING_HOURS = {
    "monday": [
        ["0900", "1800"]
    ],
}


def search_request(**changes):
    """Return a fresh valid BRNS search request."""

    request = {
        "cuisine": "japanese",
        "disliked_cuisines": [],
        "dietary_requirements": [],
        "budget_per_person": 20,
        "other_preferences": [],
        "mode": "walk",
        "max_travel_minutes": 30,
        "max_distance_km": None,
        "traffic_aware": False,
    }

    request.update(changes)

    return request


def restaurant(**changes):
    """Return a fresh restaurant with known price and route data."""

    value = {
        "name": "Sakura Test Cafe",
        "address": "1 Test Street, Singapore",

        "source": "saved + google places",
        "open_now": True,

        "cuisines": [
            "japanese"
        ],

        "dietary_requirements": [],
        "halal_status": "unverified",

        "avg_price": 12,
        "price_start": None,
        "price_end": None,

        "rating": 4.5,
        "rating_count": 200,

        "walk_minutes": 10,
        "walk_meters": 800,
        "walk_source": "route",

        "drive_minutes": None,
        "drive_meters": None,
        "drive_source": None,

        "transit_minutes": None,
        "transit_meters": None,
        "transit_source": None,

        "spicy_options": False,
    }

    value.update(changes)

    return value


def verified_halal_restaurant():
    """Return restaurant data with verified official MUIS evidence."""

    value = restaurant(
        name="Verified Halal Cafe",
        dietary_requirements=["halal"],
    )

    value["halal_certification"] = "official"

    value["muis_check"] = {
        "status": "verified"
    }

    return value


def halal_hint_restaurant():
    """Return restaurant data containing only an unofficial halal hint."""

    value = restaurant(
        name="Halal Hint Cafe",
        dietary_requirements=["halal"],
    )

    value["halal_hint"] = True

    return value


def ranking_restaurants():
    """Return two candidates for hardcoded AI-ranking tests."""

    return [
        restaurant(
            name="Sakura Near",
            rating=4.3,
            walk_minutes=8,
            walk_meters=600,
        ),

        restaurant(
            name="Tokyo Choice",
            rating=4.8,
            walk_minutes=12,
            walk_meters=900,
        ),
    ]


def valid_ai_recommendations():
    """Return a complete hardcoded AI ordering with valid reason codes."""

    return [
        {
            "id": 1,
            "reason_codes": [
                "cuisine_match",
                "within_budget",
                "within_route",
                "well_rated",
            ],
        },

        {
            "id": 0,
            "reason_codes": [
                "cuisine_match",
                "within_budget",
                "within_route",
                "well_rated",
            ],
        },
    ]


def duplicate_ai_recommendations():
    """Return invalid hardcoded AI output with duplicate restaurant IDs."""

    return [
        {
            "id": 0,
            "reason_codes": [],
        },

        {
            "id": 0,
            "reason_codes": [],
        },
    ]