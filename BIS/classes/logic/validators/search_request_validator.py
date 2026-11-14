"""Concrete validator for the existing BIS-to-BRNS JSON contract."""

from BIS.classes.logic.validators.base_search_request_validator import (
    BaseSearchRequestValidator,
)
from BIS.classes.logic.validators.search_request_validator_interface import (
    SearchRequestValidatorInterface,
)
from sources.profile_schema import (
    CUISINES,
    OTHER_PREFERENCES,
    clean_text,
    validate_search_distance,
    validate_travel_minutes,
    validate_value,
)


class SearchRequestValidator(
        BaseSearchRequestValidator, SearchRequestValidatorInterface):
    """Validate user choices and constrain an AI-proposed interpretation."""

    def validate(self, request, ai_response=None):
        confirmed = self._validate_fields(request)
        if ai_response is None:
            return confirmed
        try:
            proposed = self._validate_fields(ai_response)
        except ValueError as error:
            raise ValueError(
                "The AI returned an invalid search request. Please retry."
            ) from error
        self._protect_confirmed_choices(confirmed, proposed)
        return proposed

    def _validate_fields(self, request):
        if (not isinstance(request, dict)
                or set(request) != self._search_fields):
            raise ValueError("Today's search has an invalid set of fields.")
        origin = request["origin"]
        if not isinstance(origin, dict) or set(origin) != {
                "query", "label", "latitude", "longitude"}:
            raise ValueError("Today's search needs a confirmed location.")
        latitude, longitude = origin["latitude"], origin["longitude"]
        if (type(latitude) not in (int, float)
                or type(longitude) not in (int, float)
                or not self._in_singapore(latitude, longitude)):
            raise ValueError("Today's search location must be in Singapore.")
        if request["mode"] not in ("walk", "drive", "transit"):
            raise ValueError(
                "Choose walk, drive, or transit for today's search.")
        if request["cuisine"] not in (*self.supported_cuisines, "none"):
            raise ValueError(
                "Choose a supported cuisine or none for today's search.")
        for field in (
                OTHER_PREFERENCES, "dietary_requirements",
                "disliked_cuisines"):
            if not isinstance(request[field], list):
                raise ValueError(f"{field} must be a list.")
        distance = request["max_distance_km"]
        minutes = request["max_travel_minutes"]
        if (distance is None) == (minutes is None):
            raise ValueError(
                "Choose exactly one travel limit: distance or time.")
        mode = request["mode"]
        distance = (
            validate_search_distance(distance, mode)
            if distance is not None else None
        )
        minutes = (
            validate_travel_minutes(minutes, mode)
            if minutes is not None else None
        )
        traffic_aware = request["traffic_aware"]
        if type(traffic_aware) is not bool or (
                traffic_aware and (
                    request["mode"] != "drive" or minutes is None)):
            raise ValueError(
                "Live traffic is available only for driving time searches.")
        budget = validate_value(
            "budget_per_person", request["budget_per_person"])
        if budget is None:
            raise ValueError("Today's search needs a travel limit and budget.")
        preferences = validate_value(
            OTHER_PREFERENCES, request[OTHER_PREFERENCES])
        return {
            "origin": {
                "query": clean_text(origin["query"], 200),
                "label": clean_text(origin["label"], 500),
                "latitude": latitude,
                "longitude": longitude,
            },
            "mode": request["mode"],
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": traffic_aware,
            "cuisine": request["cuisine"],
            "budget_per_person": budget,
            OTHER_PREFERENCES: preferences,
            "dietary_requirements": validate_value(
                "dietary_requirements", request["dietary_requirements"]),
            "disliked_cuisines": validate_value(
                "disliked_cuisines", request["disliked_cuisines"]),
        }

    @staticmethod
    def _in_singapore(latitude, longitude):
        import math

        return (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and 1.15 <= latitude <= 1.48
            and 103.60 <= longitude <= 104.10
        )


SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes",
    "traffic_aware", "cuisine", "budget_per_person", OTHER_PREFERENCES,
    "dietary_requirements", "disliked_cuisines",
}


def create_search_request_validator():
    """Construct the production validator with the existing vocabulary."""
    return SearchRequestValidator(SEARCH_FIELDS, CUISINES)
