"""BIS Logic Manager: profile and search business decisions."""

import math
import re
from copy import deepcopy

from BIS.classes.logic.contracts.bis_logic_manager_interface import BISLogicManagerInterface
from BIS.classes.logic.validators.search_request_validator import (
    create_search_request_validator,
)
from sources.profile_schema import (
    CUISINES,
    MINUTES_PER_KM,
    PREFERENCE_FIELDS,
    PROFILE_NUMBER_LIMITS,
    normalize_username,
    normalize_wish_text,
    validate_english_preferences as _validate_english_preferences,
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
    def apply_search_constraints(text, constraints):
        """Encode confirmed constraints without changing the original length limit."""
        additions = []
        cuisine = constraints["hard_cuisine"]
        if cuisine and not (
                re.search(
                    rf"\bonly\s+{re.escape(cuisine)}\b",
                    text, re.IGNORECASE)
                or re.search(
                    rf"\b{re.escape(cuisine)}\s+only\b",
                    text, re.IGNORECASE)
                or re.search(
                    rf"\b(?:must be|exclusively)\s+"
                    rf"{re.escape(cuisine)}\b",
                    text, re.IGNORECASE)):
            additions.append(f"only {cuisine} cuisine")
        if (constraints["rating_is_minimum"]
                and not re.search(
                    r"\b(?:minimum|at least|no less than)\b",
                    text, re.IGNORECASE)):
            additions.append(f"at least {constraints['rating']:g} stars")
        if (not additions and not cuisine
                and not constraints["rating_is_minimum"]
                and not re.search(
                    r"\b(?:only|must|required|minimum|"
                    r"at least|no less than|exclusively)\b",
                    text, re.IGNORECASE)):
            additions.append("hard requirement")
        for addition in additions:
            if (addition not in text.casefold()
                    and len(text) + len(addition) + 2 <= 100):
                text += ", " + addition
        return text

    def preserve_search_wish(self, confirmed, request, today_request,
                             field="other_preferences"):
        """Retain an explicit wish omitted from an otherwise valid AI proposal."""
        if (today_request and not confirmed[field]
                and request[field] == confirmed[field]):
            request = dict(request)
            request[field] = confirmed[field] + [today_request]
            request = self.validate_search_request(request)
        return request

    @staticmethod
    def next_field(preferences):
        for field in PREFERENCE_FIELDS:
            if preferences[field] is None:
                return field
        return None

    @staticmethod
    def validate_english_preferences(items, field_label="Default special wishes"):
        """Require proper meaningful English text for profile special wishes."""
        return _validate_english_preferences(items, field_label=field_label)

    def apply_updates(self, preferences, updates, location_action="add",
                      allow_empty_location=False):
        if location_action not in {"add", "replace", "remove"}:
            raise ValueError("Choose add, replace, or remove for locations.")
        result = deepcopy(
            validate_preferences(preferences, clamp_legacy_limits=True)
        )
        updates = self.estimate_travel_limits(
            validate_updates(
                updates, profile_mode=True,
                allow_empty_location=allow_empty_location,
            )
        )
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
        min_time, max_time = PROFILE_NUMBER_LIMITS["max_travel_time_minutes"]
        min_dist, max_dist = PROFILE_NUMBER_LIMITS["max_distance_km"]
        if distance is not None and minutes is None:
            estimated_minutes = round(distance * MINUTES_PER_KM, 2)
            updates["max_travel_time_minutes"] = round(
                max(min_time, min(max_time, estimated_minutes)), 2)
        elif minutes is not None and distance is None:
            estimated_distance = round(minutes / MINUTES_PER_KM, 2)
            updates["max_distance_km"] = round(
                max(min_dist, min(max_dist, estimated_distance)), 2)
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

    @staticmethod
    def normalize_profile_items(items, is_location=False):
        normalized = []
        for item in items:
            clean = str(item or "").strip() if is_location else normalize_wish_text(item)
            if not clean:
                continue
            if is_location and clean.isdigit():
                clean = f"Singapore {clean}"
            normalized.append(clean)
        return normalized

    def prepare_profile_save(self, user, payload, smtp_bypass=False):
        """Validate ownership/verification rules and apply profile updates."""
        if payload.get("user_id") not in (None, user["userID"]):
            raise PermissionError("A profile can only be changed by its owner.")
        if payload.get("email") not in (None, user["email"]):
            raise ValueError(
                "Changing the verified email is not supported by this profile form.")
        if not user["email_verified"] and smtp_bypass is not True:
            raise PermissionError("Verify your email before changing preferences.")
        updates = {key: payload[key] for key in PREFERENCE_FIELDS if key in payload}
        if "location" in updates and isinstance(updates["location"], list):
            updates["location"] = self.normalize_profile_items(
                updates["location"], is_location=True)
        if "other_preferences" in updates and isinstance(
                updates["other_preferences"], list):
            updates["other_preferences"] = self.normalize_profile_items(
                updates["other_preferences"], is_location=False)
            self.validate_english_preferences(updates["other_preferences"])
        preferences = self.apply_updates(
            user["preferences"], updates, "replace", allow_empty_location=True)
        username = normalize_username(payload.get("username") or user["username"])
        return dict(user, username=username, preferences=preferences)

    @staticmethod
    def collect_search_locations(payload):
        """Extract unique non-empty starting locations, keeping primary first."""
        raw_locations = []
        for item in (payload.get("locations") or []):
            clean_loc = str(item or "").strip()
            if clean_loc and clean_loc not in raw_locations:
                raw_locations.append(clean_loc)
        primary = str(payload.get("location") or "").strip()
        if primary and primary not in raw_locations:
            raw_locations.insert(0, primary)
        if not raw_locations:
            raise ValueError("Please enter at least one starting location.")
        return raw_locations

    @staticmethod
    def collect_search_cuisines(payload):
        """Parse comma-separated cuisine selections into an ordered unique list."""
        selected = []
        for raw_c in (payload.get("liked_cuisines") or []):
            for part in str(raw_c or "").split(","):
                clean = part.strip().lower()
                if (clean and clean not in ("none", "any", "any cuisine")
                        and clean not in selected):
                    selected.append(clean)
        single = payload.get("cuisine")
        if single:
            for part in str(single).split(","):
                clean = part.strip().lower()
                if (clean and clean not in ("none", "any", "any cuisine")
                        and clean not in selected):
                    selected.append(clean)
        return selected

    @staticmethod
    def compute_midpoint_origin(resolved_origins):
        """Return one resolved origin or compute the geographic midpoint of several."""
        if len(resolved_origins) == 1:
            return resolved_origins[0]
        mid_lat = round(
            sum(o["latitude"] for o in resolved_origins) / len(resolved_origins), 6)
        mid_lng = round(
            sum(o["longitude"] for o in resolved_origins) / len(resolved_origins), 6)
        short_names = [o["query"] for o in resolved_origins]
        history_query = " + ".join(short_names)[:200]
        return {
            "query": history_query,
            "label": f"Midpoint between {', '.join(short_names)}"[:500],
            "latitude": mid_lat,
            "longitude": mid_lng,
        }

    def build_base_search_request(self, payload, origin, cuisine_target):
        """Construct and validate a deterministic base BIS search request."""
        minutes = payload.get("max_travel_minutes")
        distance = payload.get("max_distance_km")
        if minutes is not None and distance is not None:
            distance = None
        if minutes is None and distance is None:
            minutes = 20.0

        other_prefs = [
            str(p).strip() for p in (payload.get("other_preferences") or [])
            if str(p or "").strip()
        ]
        _validate_english_preferences(other_prefs, field_label="Special requests")
        if not cuisine_target:
            cuisine_val = "none"
        elif cuisine_target in CUISINES:
            cuisine_val = cuisine_target
        else:
            cuisine_val = "none"
            custom_wish = f"{cuisine_target} cuisine"
            if custom_wish not in other_prefs:
                other_prefs = other_prefs + [custom_wish]

        disliked = []
        for raw_c in (payload.get("disliked_cuisines") or []):
            clean_c = str(raw_c or "").strip().lower()
            if not clean_c:
                continue
            if clean_c in CUISINES:
                if clean_c not in disliked:
                    disliked.append(clean_c)
            else:
                avoid_wish = f"avoid {clean_c} cuisine"
                if avoid_wish not in other_prefs:
                    other_prefs = other_prefs + [avoid_wish]
        mode = payload.get("mode", "walk")
        traffic = bool(
            payload.get("traffic_aware", False)
            and mode == "drive"
            and minutes is not None)
        request = {
            "origin": origin,
            "mode": mode,
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": traffic,
            "cuisine": cuisine_val,
            "budget_per_person": payload["budget_per_person"],
            "other_preferences": other_prefs,
            "dietary_requirements": payload.get("dietary_requirements", []),
            "disliked_cuisines": disliked,
        }
        return self.validate_search_request(request)

    @staticmethod
    def place_key(restaurant):
        """Return a stable deduplication key for a restaurant candidate."""
        if not isinstance(restaurant, dict):
            return ""
        pid = str(restaurant.get("google_place_id") or "").strip()
        if pid:
            return pid
        name = str(restaurant.get("name") or "").strip().lower()
        addr = str(restaurant.get("address") or "").strip().lower()
        return f"{name}|{addr}"

    def merge_multi_cuisine_results(
            self, per_cuisine_results, num_cuisines, max_total=20):
        """Deduplicate, interleave, and balance per-cuisine batches up to max_total."""
        combined_matches = []
        combined_alternatives = []
        cuisines_breakdown = {c_target: 0 for c_target, _ in per_cuisine_results}
        seen_keys = set()
        total_hidden = 0

        pools = []
        for c_target, sub_res in per_cuisine_results:
            if sub_res is None:
                continue
            total_hidden += sub_res.get("hidden", 0)
            pools.append({
                "cuisine": c_target,
                "matches": [
                    dict(m, matched_cuisine=c_target)
                    for m in sub_res.get("matches", [])
                ],
                "alternatives": [
                    dict(a, matched_cuisine=c_target)
                    for a in sub_res.get("alternatives", [])
                ],
                "m_idx": 0,
                "a_idx": 0,
            })

        def _take_next(bucket_key, idx_key, target_list, remaining_budget):
            while remaining_budget > 0:
                progressed = False
                for pool in pools:
                    items = pool[bucket_key]
                    while pool[idx_key] < len(items):
                        candidate = items[pool[idx_key]]
                        pool[idx_key] += 1
                        key = self.place_key(candidate.get("restaurant"))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        target_list.append(candidate)
                        cuisines_breakdown[pool["cuisine"]] += 1
                        remaining_budget -= 1
                        progressed = True
                        break
                    if remaining_budget <= 0:
                        break
                if not progressed:
                    break
            return remaining_budget

        remaining = _take_next("matches", "m_idx", combined_matches, max_total)
        _take_next("alternatives", "a_idx", combined_alternatives, remaining)

        return (
            combined_matches,
            combined_alternatives,
            cuisines_breakdown,
            total_hidden,
        )
