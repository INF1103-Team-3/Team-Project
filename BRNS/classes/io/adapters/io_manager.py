"""BRNS IO Manager: request boundary and recommendation presentation."""

import json
import math
import re

from BIS.sources.profile_schema import (
    CUISINES,
    clean_text,
    validate_travel_minutes,
    validate_value,
)
from BRNS.classes.io.contracts.candidate_io_interface import CandidateIOInterface
from BRNS.classes.io.contracts.navigation_io_interface import NavigationIOInterface
from BRNS.classes.io.contracts.recommendation_presentation_interface import (
    RecommendationPresentationInterface,
)


SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes",
    "traffic_aware", "cuisine", "budget_per_person",
    "other_preferences", "dietary_requirements", "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}


class IOManager(
        CandidateIOInterface, RecommendationPresentationInterface,
        NavigationIOInterface):
    """Own BRNS input validation, candidate IO orchestration, and output."""

    def __init__(self, helpers, logic_manager, logger, candidate_search):
        self._candidate_search = candidate_search
        self._helpers = helpers
        self._logic = logic_manager
        self._log = logger

    @property
    def display_debug(self):
        return self._helpers.display_debug

    def accept_bis_json(self, payload):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as error:
                raise ValueError(
                    "BRNS requires valid BIS search JSON.") from error
        if not isinstance(payload, dict) or set(payload) != SEARCH_FIELDS:
            raise ValueError("BRNS requires the ten BIS search fields only.")
        origin = payload["origin"]
        if not isinstance(origin, dict) or set(origin) != ORIGIN_FIELDS:
            raise ValueError("BRNS requires a confirmed origin object.")
        query = clean_text(origin["query"], 200)
        label = clean_text(origin["label"], 500)
        latitude, longitude = origin["latitude"], origin["longitude"]
        if (type(latitude) not in (int, float)
                or type(longitude) not in (int, float)
                or not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not 1.15 <= latitude <= 1.48
                or not 103.60 <= longitude <= 104.10):
            raise ValueError("The search origin must be within Singapore.")
        if payload["mode"] not in ("walk", "drive", "transit"):
            raise ValueError("Choose walk, drive, or transit for the search.")
        distance = payload["max_distance_km"]
        minutes = payload["max_travel_minutes"]
        if (distance is None) == (minutes is None):
            raise ValueError("BRNS requires exactly one travel limit.")
        if payload["mode"] == "transit" and distance is not None:
            raise ValueError("Transit searches require a time limit.")
        distance = (
            validate_value("max_distance_km", distance)
            if distance is not None else None)
        minutes = (
            validate_travel_minutes(minutes)
            if minutes is not None else None)
        traffic_aware = payload["traffic_aware"]
        if (type(traffic_aware) is not bool
                or traffic_aware and (
                    payload["mode"] != "drive" or minutes is None)):
            raise ValueError(
                "Live traffic is available only for driving time searches.")
        if payload["budget_per_person"] is None:
            raise ValueError("Search budget is required.")
        if any(not isinstance(payload[field], list) for field in (
                "other_preferences", "dietary_requirements",
                "disliked_cuisines")):
            raise ValueError(
                "Search preferences and dietary requirements must be lists.")
        cuisine = payload["cuisine"]
        if (not isinstance(cuisine, str)
                or cuisine not in (*CUISINES, "none")):
            raise ValueError(
                "Choose a supported cuisine or none for the search.")
        other_preferences = validate_value(
            "other_preferences", payload["other_preferences"])
        self._logic.minimum_rating(other_preferences)
        return {
            "origin": {
                "query": query,
                "label": label,
                "latitude": latitude,
                "longitude": longitude,
            },
            "mode": payload["mode"],
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": traffic_aware,
            "cuisine": cuisine,
            "budget_per_person": validate_value(
                "budget_per_person", payload["budget_per_person"]),
            "other_preferences": other_preferences,
            "dietary_requirements": validate_value(
                "dietary_requirements", payload["dietary_requirements"]),
            "disliked_cuisines": validate_value(
                "disliked_cuisines", payload["disliked_cuisines"]),
        }

    def find_candidates(self, request):
        return self._candidate_search.find(request)

    def show_ai_ranking_start(self, count, timeout):
        return self._helpers.show_ai_ranking_start(count, timeout)

    def show_halal_verification_start(self, count, database_missing=False):
        return self._helpers.show_halal_verification_start(
            count, database_missing)

    def show_halal_verification_summary(self, summary):
        return self._helpers.show_halal_verification_summary(summary)

    def get_route(self, *args, **kwargs):
        return self._helpers.get_route(*args, **kwargs)

    def build_maps_link(self, *args, **kwargs):
        return self._helpers.build_maps_link(*args, **kwargs)

    def show_results(self, results):
        return self._helpers.show_results(results)
