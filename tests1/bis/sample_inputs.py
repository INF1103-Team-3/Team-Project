"""Reusable hardcoded inputs for BiteFinder BIS function tests."""

from copy import deepcopy


VALID_SINGAPORE_COORDINATES = "1.405, 103.902"
OVERSEAS_COORDINATES = "40.7128, -74.0060"
SINGAPORE_POSTAL_CODE = "828761"

VALID_BUDGET_TEXT = "20"
INVALID_BUDGET_TEXT = "twenty dollars"

DIETARY_BOTH_TEXT = "both"
LIKED_CUISINES_TEXT = "I like Japanese and Korean"
DISLIKE_AS_LIKE_TEXT = "I dislike Japanese"

VALID_SPECIAL_REQUEST = "something spicy and quiet"
INVALID_SPECIAL_REQUEST = "abc$"


def complete_preferences():
    """Return a fresh complete BIS preference profile."""
    return {
        "location": ["punggol"],
        "max_distance_km": 2.0,
        "max_travel_time_minutes": 40.0,
        "budget_per_person": 20.0,
        "dietary_requirements": ["halal"],
        "liked_cuisines": ["japanese"],
        "disliked_cuisines": [],
        "other_preferences": ["spicy food"],
    }


def confirmed_search_request():
    """Return a fresh valid BIS-to-BRNS search request."""
    return {
        "origin": {
            "query": "Punggol",
            "label": "Punggol, Singapore",
            "latitude": 1.405,
            "longitude": 103.902,
        },
        "mode": "walk",
        "max_distance_km": 2.0,
        "max_travel_minutes": None,
        "traffic_aware": False,
        "cuisine": "japanese",
        "budget_per_person": 20.0,
        "other_preferences": ["spicy food"],
        "dietary_requirements": ["halal"],
        "disliked_cuisines": [],
    }


def valid_ai_search_response():
    """Return hardcoded AI output that keeps confirmed choices intact."""
    response = deepcopy(confirmed_search_request())
    response["other_preferences"] = [
        "spicy food",
        "quiet place",
    ]
    return response


def conflicting_ai_search_response():
    """Return hardcoded AI output that incorrectly changes a confirmed budget."""
    response = deepcopy(confirmed_search_request())
    response["budget_per_person"] = 50.0
    return response