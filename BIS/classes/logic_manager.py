"""BIS Logic Manager: profile and search business decisions."""

import math
import re
from copy import deepcopy

from BIS.classes.bis_logic_manager_interface import BISLogicManagerInterface
from BIS.classes.search_request_validator import (
    create_search_request_validator,
)
from sources.profile_schema import (
    MINUTES_PER_KM,
    PREFERENCE_FIELDS,
    validate_preferences,
    validate_updates,
)


SEARCH_CLARIFICATION_PREFIX = "SEARCH_CLARIFICATION: "
COORDINATES = re.compile(
    r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*")


class LogicManager(BISLogicManagerInterface):
    """Own BIS profile updates and validated search-request decisions."""

    def __init__(self, search_validator=None):
        self._search_validator = (
            search_validator or create_search_request_validator())

    @property
    def search_validator(self):
        return self._search_validator

    def validate_search_request(self, request, ai_response=None):
        return self._search_validator.validate(request, ai_response)

    @staticmethod
    def next_field(preferences):
        for field in PREFERENCE_FIELDS:
            if preferences[field] is None:
                return field
        return None

    def apply_updates(self, preferences, updates, location_action="add"):
        if location_action not in {"add", "replace", "remove"}:
            raise ValueError("Choose add, replace, or remove for locations.")
        result = deepcopy(validate_preferences(preferences))
        updates = self.estimate_travel_limits(validate_updates(updates))
        if "location" in updates:
            old = result["location"] or []
            incoming = updates["location"]
            if location_action == "add":
                updates["location"] = list(
                    dict.fromkeys(old + incoming))
            elif location_action == "remove":
                if any(item not in old for item in incoming):
                    raise ValueError(
                        "That location is not in your saved list.")
                updates["location"] = [
                    item for item in old if item not in incoming]
        result.update(updates)
        return validate_preferences(result)

    @staticmethod
    def estimate_travel_limits(updates):
        updates = dict(updates)
        distance = updates.get("max_distance_km")
        minutes = updates.get("max_travel_time_minutes")
        if distance is not None and minutes is None:
            updates["max_travel_time_minutes"] = round(
                distance * MINUTES_PER_KM, 2)
        elif minutes is not None and distance is None:
            updates["max_distance_km"] = max(
                0.01, round(minutes / MINUTES_PER_KM, 2))
        return updates

    @staticmethod
    def is_search_clarification(error):
        return (
            isinstance(error, ValueError)
            and str(error).startswith(SEARCH_CLARIFICATION_PREFIX))

    @staticmethod
    def clarification_message(error):
        return str(error)[len(SEARCH_CLARIFICATION_PREFIX):]

    @staticmethod
    def in_singapore(latitude, longitude):
        return (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and 1.15 <= latitude <= 1.48
            and 103.60 <= longitude <= 104.10)

    def parse_coordinates(self, text):
        match = COORDINATES.fullmatch(text)
        if not match:
            return None
        latitude, longitude = map(float, match.groups())
        if not self.in_singapore(latitude, longitude):
            raise ValueError("Enter coordinates within Singapore.")
        return latitude, longitude

    def is_direct_location_input(self, text):
        return self.parse_coordinates(text) is not None or bool(
            re.fullmatch(r"\d{5,6}", text))
