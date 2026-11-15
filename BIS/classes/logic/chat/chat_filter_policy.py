"""Chat filter, reconciliation and profile-mapping business rules."""

from copy import deepcopy
import re

from BIS.sources.profile_schema import (
    CUISINES,
    DIETARY_CHOICES,
    NUMBER_LIMITS,
    SEARCH_MODE_LIMITS,
    extract_rating_wishes,
    normalize_wish_text,
    strip_rating_clauses,
    validate_english_preferences,
)


class ChatFilterPolicy:
    """Own deterministic chat decisions without transport or persistence."""

    _CONFIRM_PHRASES = {
        "yes",
        "yes search now",
        "yes, search now",
        "yes please",
        "yep",
        "yeah",
        "yup",
        "sure",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "correct",
        "looks good",
        "sounds good",
        "all good",
        "all correct",
        "that's right",
        "thats right",
        "go ahead",
        "proceed",
        "search",
        "search now",
        "find now",
        "run search",
        "start search",
        "do it",
        "retry search",
        "try again",
        "lets go",
        "let's go",
        "yes lets go",
        "yes let's go",
        "ok search",
        "okay search",
        "ok search now",
        "yes looks good",
        "ok looks good",
    }

    _CONFIRM_REGEX = re.compile(
        (
            "^(?:yes|yep|yeah|yup|ok|okay|sure|great|perfect|awesome|alright)("
            "?:[,\\s]+(?:looks good|sounds good|all good|all "
            "correct|search|search now|go ahead|proceed|lets go|let's "
            "go|please|start|find it))?$"
        )
    )

    @staticmethod
    def normalize_location(raw):
        text = re.sub(r"\s+", " ", str(raw or "").strip()).strip(".,;!?")
        if not text:
            return ""
        if text.isdigit():
            return f"Singapore {text}"
        if text.islower() and any(ch.isalpha() for ch in text):
            text = re.sub(r"\bmrt\b", "MRT", text.title(), flags=re.IGNORECASE)
        return text

    @classmethod
    def default_filters(cls, user=None):
        prefs = (user or {}).get("preferences") or {}
        saved_locs = [
            cls.normalize_location(loc)
            for loc in (prefs.get("location") or [])
            if str(loc or "").strip()
        ]
        max_mins = prefs.get("max_travel_time_minutes")
        max_km = prefs.get("max_distance_km")
        walk_limits = SEARCH_MODE_LIMITS["walk"]
        needs_transit = (
            max_mins is not None
            and float(max_mins) > walk_limits["max_travel_minutes"][1]
        ) or (
            max_km is not None
            and float(max_km) > walk_limits["max_distance_km"][1]
        )
        if max_mins is not None:
            max_km = None
        budget = prefs.get("budget_per_person")
        return {
            "location": saved_locs[0] if saved_locs else "",
            "locations": saved_locs,
            "mode": "transit" if needs_transit else "walk",
            "traffic_aware": False,
            "max_travel_minutes": float(max_mins)
            if max_mins is not None
            else None,
            "max_distance_km": float(max_km) if max_km is not None else None,
            "budget_per_person": float(budget) if budget is not None else None,
            "dietary_requirements": list(
                prefs.get("dietary_requirements") or []
            ),
            "liked_cuisines": [
                str(c).strip().lower()
                for c in (prefs.get("liked_cuisines") or [])
                if str(c).strip()
            ],
            "disliked_cuisines": [
                str(c).strip().lower()
                for c in (prefs.get("disliked_cuisines") or [])
                if str(c).strip()
            ],
            "other_preferences": [
                str(p).strip()
                for p in (prefs.get("other_preferences") or [])
                if str(p).strip()
            ],
        }

    @classmethod
    def normalize_filters(cls, raw, user=None):
        defaults = cls.default_filters(user)
        if not isinstance(raw, dict):
            return defaults

        if "locations" not in raw and "location" not in raw:
            locs = list(defaults["locations"])
        else:
            locs = []
            for entry in raw.get("locations") or []:
                clean = cls.normalize_location(entry)
                if clean and clean.casefold() not in {
                    x.casefold() for x in locs
                }:
                    locs.append(clean)
            primary = cls.normalize_location(raw.get("location"))
            if primary and primary.casefold() not in {
                x.casefold() for x in locs
            }:
                locs.insert(0, primary)

        mode = str(raw.get("mode") or defaults["mode"]).strip().lower()
        if mode not in ("walk", "drive", "transit"):
            mode = "walk"

        mode_limits = SEARCH_MODE_LIMITS[mode]
        max_mins = (
            raw.get("max_travel_minutes")
            if "max_travel_minutes" in raw
            else defaults["max_travel_minutes"]
        )
        max_km = (
            raw.get("max_distance_km")
            if "max_distance_km" in raw
            else defaults["max_distance_km"]
        )
        if (
            isinstance(max_mins, (int, float))
            and not isinstance(max_mins, bool)
            and max_mins > 0
        ):
            low, high = mode_limits["max_travel_minutes"]
            max_mins = round(max(low, min(high, float(max_mins))), 1)
            max_km = None
        elif (
            isinstance(max_km, (int, float))
            and not isinstance(max_km, bool)
            and max_km > 0
        ):
            low, high = mode_limits["max_distance_km"]
            max_km = round(max(low, min(high, float(max_km))), 2)
            max_mins = None
        else:
            max_mins = None
            max_km = None

        budget = (
            raw.get("budget_per_person")
            if "budget_per_person" in raw
            else defaults["budget_per_person"]
        )
        if (
            isinstance(budget, (int, float))
            and not isinstance(budget, bool)
            and budget > 0
        ):
            b_low, b_high = NUMBER_LIMITS["budget_per_person"]
            budget = round(max(b_low, min(b_high, float(budget))), 2)
        else:
            budget = None

        diet = []
        for item in raw.get("dietary_requirements") or []:
            clean = str(item or "").strip().lower()
            if clean in DIETARY_CHOICES and clean not in diet:
                diet.append(clean)

        liked = []
        for item in raw.get("liked_cuisines") or []:
            clean = str(item or "").strip().lower()
            if (
                clean
                and clean not in ("none", "any", "any cuisine")
                and clean not in liked
            ):
                liked.append(clean)

        disliked = []
        for item in raw.get("disliked_cuisines") or []:
            clean = str(item or "").strip().lower()
            if (
                clean
                and clean not in ("none", "any", "any cuisine", "nothing")
                and clean not in disliked
                and clean not in liked
            ):
                disliked.append(clean)

        other = []
        for item in raw.get("other_preferences") or []:
            clean = str(item or "").strip()
            if clean and clean.casefold() not in {o.casefold() for o in other}:
                other.append(clean)

        return {
            "location": locs[0] if locs else "",
            "locations": locs,
            "mode": mode,
            "traffic_aware": bool(
                raw.get("traffic_aware") and mode == "drive"
            ),
            "max_travel_minutes": max_mins,
            "max_distance_km": max_km,
            "budget_per_person": budget,
            "dietary_requirements": diet,
            "liked_cuisines": liked,
            "disliked_cuisines": disliked,
            "other_preferences": other,
        }

    @staticmethod
    def _merge_list(existing, incoming, action, allowed=None):
        base = list(existing)
        items = []
        for entry in incoming or []:
            clean = str(entry or "").strip()
            if not clean:
                continue
            key = clean.lower()
            if allowed is not None and key not in allowed:
                continue
            val = key if allowed is not None else clean
            if val.casefold() not in {x.casefold() for x in items}:
                items.append(val)
        if action == "clear":
            return []
        if action == "remove":
            remove_keys = {i.casefold() for i in items}
            return [x for x in base if x.casefold() not in remove_keys]
        if action == "replace":
            return items
        merged = list(base)
        for item in items:
            if item.casefold() not in {x.casefold() for x in merged}:
                merged.append(item)
        return merged

    @classmethod
    def apply_updates(cls, current, updates, user=None):
        result = deepcopy(current)
        if not isinstance(updates, dict):
            return result

        locs_in = updates.get("locations")
        loc_action = updates.get("locations_action") or "replace"
        if loc_action == "clear":
            result["locations"] = []
            result["location"] = ""
        elif isinstance(locs_in, list) and locs_in:
            cleaned = [
                cls.normalize_location(loc)
                for loc in locs_in
                if cls.normalize_location(loc)
            ]
            result["locations"] = cls._merge_list(
                result["locations"], cleaned, loc_action
            )
            result["location"] = (
                result["locations"][0] if result["locations"] else ""
            )

        mode = str(updates.get("mode") or "").strip().lower()
        if mode in ("walk", "drive", "transit"):
            result["mode"] = mode
            if mode != "drive":
                result["traffic_aware"] = False

        if (
            updates.get("traffic_aware") is not None
            and result["mode"] == "drive"
        ):
            result["traffic_aware"] = bool(updates.get("traffic_aware"))

        mins = updates.get("max_travel_minutes")
        km = updates.get("max_distance_km")
        if (
            isinstance(mins, (int, float))
            and not isinstance(mins, bool)
            and mins > 0
        ):
            result["max_travel_minutes"] = mins
            result["max_distance_km"] = None
        elif (
            isinstance(km, (int, float))
            and not isinstance(km, bool)
            and km > 0
        ):
            result["max_distance_km"] = km
            result["max_travel_minutes"] = None

        budget = updates.get("budget_per_person")
        if (
            isinstance(budget, (int, float))
            and not isinstance(budget, bool)
            and budget > 0
        ):
            result["budget_per_person"] = budget

        if (
            isinstance(updates.get("dietary_requirements"), list)
            or updates.get("dietary_action") == "clear"
        ):
            action = updates.get("dietary_action") or "replace"
            result["dietary_requirements"] = cls._merge_list(
                result["dietary_requirements"],
                updates.get("dietary_requirements") or [],
                action,
                allowed=set(DIETARY_CHOICES),
            )

        if (
            isinstance(updates.get("liked_cuisines"), list)
            or updates.get("liked_action") == "clear"
        ):
            action = updates.get("liked_action") or "replace"
            raw_liked = [
                str(c).strip().lower()
                for c in (updates.get("liked_cuisines") or [])
                if str(c).strip()
            ]
            result["liked_cuisines"] = cls._merge_list(
                result["liked_cuisines"], raw_liked, action
            )
            liked_keys = {c.casefold() for c in result["liked_cuisines"]}
            result["disliked_cuisines"] = [
                d
                for d in result["disliked_cuisines"]
                if d.casefold() not in liked_keys
            ]

        if (
            isinstance(updates.get("disliked_cuisines"), list)
            or updates.get("disliked_action") == "clear"
        ):
            action = updates.get("disliked_action") or "add"
            raw_disliked = [
                str(c).strip().lower()
                for c in (updates.get("disliked_cuisines") or [])
                if str(c or "").strip()
                and str(c or "").strip().lower()
                not in ("none", "any", "nothing")
            ]
            result["disliked_cuisines"] = cls._merge_list(
                result["disliked_cuisines"],
                raw_disliked,
                action,
            )
            disliked_keys = {d.casefold() for d in result["disliked_cuisines"]}
            result["liked_cuisines"] = [
                c
                for c in result["liked_cuisines"]
                if c.casefold() not in disliked_keys
            ]

        if isinstance(updates.get("other_preferences"), list) or updates.get(
            "other_action"
        ) in ("clear", "clear_rating"):
            action = updates.get("other_action") or "add"
            if action == "clear_rating":
                kept = []
                for existing in result["other_preferences"]:
                    rem = strip_rating_clauses(existing)
                    if rem:
                        kept.append(rem)
                result["other_preferences"] = kept
            else:
                incoming = [
                    normalize_wish_text(x)
                    for x in (updates.get("other_preferences") or [])
                    if normalize_wish_text(x)
                ]
                has_incoming_rating = any(
                    strip_rating_clauses(x) != x for x in incoming
                )
                base_other = result["other_preferences"]
                if action == "add" and has_incoming_rating:
                    base_other = [
                        rem
                        for item in base_other
                        for rem in [strip_rating_clauses(item)]
                        if rem
                    ]
                result["other_preferences"] = cls._merge_list(
                    base_other,
                    incoming,
                    action,
                )

        return cls.normalize_filters(result, user=user)

    @staticmethod
    def next_missing_search_field(filters):
        if not filters.get("locations"):
            return "location"
        if filters.get("budget_per_person") is None:
            return "budget_per_person"
        if (
            filters.get("max_travel_minutes") is None
            and filters.get("max_distance_km") is None
        ):
            return "travel"
        return None

    @staticmethod
    def next_onboarding_field(prefs):
        if not prefs.get("location"):
            return "location"
        if prefs.get("budget_per_person") is None:
            return "budget_per_person"
        if (
            prefs.get("max_travel_time_minutes") is None
            and prefs.get("max_distance_km") is None
        ):
            return "travel"
        if prefs.get("dietary_requirements") is None:
            return "dietary_requirements"
        if prefs.get("liked_cuisines") is None:
            return "liked_cuisines"
        if prefs.get("disliked_cuisines") is None:
            return "disliked_cuisines"
        if prefs.get("other_preferences") is None:
            return "other_preferences"
        return None

    @staticmethod
    def build_safe_profile_payload(user, filters, fallback_prefs=None):
        prefs = (
            fallback_prefs
            if fallback_prefs is not None
            else ((user or {}).get("preferences") or {})
        )
        supported_liked = []
        extra_other = list(filters.get("other_preferences") or [])
        for cuisine in filters.get("liked_cuisines") or []:
            clean = str(cuisine or "").strip().lower()
            if clean in CUISINES:
                if clean not in supported_liked:
                    supported_liked.append(clean)
            elif clean:
                custom_wish = f"{clean} cuisine"
                if custom_wish.casefold() not in {
                    o.casefold() for o in extra_other
                }:
                    extra_other.append(custom_wish)

        supported_disliked = []
        for cuisine in filters.get("disliked_cuisines") or []:
            clean = str(cuisine or "").strip().lower()
            if clean in CUISINES:
                if clean not in supported_disliked:
                    supported_disliked.append(clean)
            elif clean:
                custom_avoid = f"avoid {clean} cuisine"
                if custom_avoid.casefold() not in {
                    o.casefold() for o in extra_other
                }:
                    extra_other.append(custom_avoid)

        locs = filters.get("locations") or prefs.get("location")
        budget = filters.get("budget_per_person")
        if budget is None:
            budget = prefs.get("budget_per_person") or 30.0
        max_mins = filters.get("max_travel_minutes")
        max_km = filters.get("max_distance_km")
        if max_mins is None and max_km is None:
            max_mins = prefs.get("max_travel_time_minutes")
            max_km = prefs.get("max_distance_km")
            if max_mins is None and max_km is None:
                max_mins = 30.0

        return {
            "user_id": user["userID"],
            "location": locs or ["Compass One"],
            "max_distance_km": max_km,
            "max_travel_time_minutes": max_mins,
            "budget_per_person": budget,
            "dietary_requirements": filters.get("dietary_requirements") or [],
            "liked_cuisines": supported_liked,
            "disliked_cuisines": supported_disliked,
            "other_preferences": extra_other,
        }

    @classmethod
    def is_search_confirmation(cls, message):
        cleaned = re.sub(
            r"[.!?\s]+$", "", str(message or "").casefold().strip()
        )
        if cleaned in cls._CONFIRM_PHRASES:
            return True
        return bool(cls._CONFIRM_REGEX.match(cleaned))

    @staticmethod
    def reconcile_ai_updates(det_parsed, ai_parsed, current):
        """Guard explicit deterministic negations/removals from accidental
        AI reversal.
        """
        det_updates = dict((det_parsed or {}).get("updates") or {})
        result = (
            deepcopy(ai_parsed)
            if isinstance(ai_parsed, dict)
            else {
                "intent": "search",
                "updates": {},
                "reply": "",
                "quick_replies": [],
            }
        )
        ai_updates = dict(result.get("updates") or {})

        # 1. Explicit dietary negation / clear must ALWAYS win over AI
        # confusion (e.g. "i dont want halal").
        if det_updates.get("dietary_action") in ("remove", "clear"):
            ai_updates["dietary_action"] = det_updates["dietary_action"]
            ai_updates["dietary_requirements"] = list(
                det_updates.get("dietary_requirements") or []
            )
            if ai_updates.get("disliked_cuisines"):
                ai_updates["disliked_cuisines"] = [
                    c
                    for c in ai_updates["disliked_cuisines"]
                    if str(c).strip().casefold()
                    not in ("halal", "vegetarian", "dietary")
                ]
            result["intent"] = "search"

        # 2. Explicit liked removal/clear ("remove japanese" when japanese is
        # liked) should not blacklist it.
        if det_updates.get("liked_action") in ("remove", "clear"):
            ai_updates["liked_action"] = det_updates["liked_action"]
            det_liked = list(det_updates.get("liked_cuisines") or [])
            ai_updates["liked_cuisines"] = det_liked
            if ai_updates.get("disliked_cuisines"):
                det_liked_cf = {str(c).strip().casefold() for c in det_liked}
                ai_updates["disliked_cuisines"] = [
                    c
                    for c in ai_updates["disliked_cuisines"]
                    if str(c).strip().casefold() not in det_liked_cf
                ]
            result["intent"] = "search"

        # 3. Explicit disliked removal/clear ("stop avoiding chinese", "clear
        # dislikes").
        if det_updates.get("disliked_action") in ("remove", "clear"):
            ai_updates["disliked_action"] = det_updates["disliked_action"]
            ai_updates["disliked_cuisines"] = list(
                det_updates.get("disliked_cuisines") or []
            )
            result["intent"] = "search"
        elif det_updates.get("disliked_cuisines"):
            existing_disliked = list(ai_updates.get("disliked_cuisines") or [])
            existing_cf = {
                str(c).strip().casefold() for c in existing_disliked
            }
            for item in det_updates["disliked_cuisines"]:
                if str(item).strip().casefold() not in existing_cf:
                    existing_disliked.append(item)
            ai_updates["disliked_cuisines"] = existing_disliked
            if not ai_updates.get("disliked_action"):
                ai_updates["disliked_action"] = (
                    det_updates.get("disliked_action") or "add"
                )
            result["intent"] = "search"

        # 4. Location add/remove preservation.
        if det_updates.get("locations_action") in ("remove", "clear", "add"):
            ai_updates["locations_action"] = det_updates["locations_action"]
            if det_updates.get("locations"):
                ai_updates["locations"] = list(det_updates["locations"])
            result["intent"] = "search"

        # 5. Wishes remove/clear preservation.
        if det_updates.get("other_action") in ("remove", "clear"):
            ai_updates["other_action"] = det_updates["other_action"]
            ai_updates["other_preferences"] = list(
                det_updates.get("other_preferences") or []
            )
            result["intent"] = "search"

        # 6. Preserve deterministic $100+ / fine dining (1000.0) and missed
        # numeric bounds if AI drops or truncates '+'.
        if det_updates.get("budget_per_person") == 1000.0 and ai_updates.get(
            "budget_per_person"
        ) in (None, 100, 100.0):
            ai_updates["budget_per_person"] = 1000.0
        elif (
            det_updates.get("budget_per_person") is not None
            and ai_updates.get("budget_per_person") is None
        ):
            ai_updates["budget_per_person"] = det_updates["budget_per_person"]
        if (
            ai_updates.get("max_distance_km") is None
            and ai_updates.get("max_travel_minutes") is None
        ):
            if det_updates.get("max_distance_km") is not None:
                ai_updates["max_distance_km"] = det_updates["max_distance_km"]
            elif det_updates.get("max_travel_minutes") is not None:
                ai_updates["max_travel_minutes"] = det_updates[
                    "max_travel_minutes"
                ]

        # 7. If AI produced no updates at all despite deterministic rule
        # extraction, trust deterministic parse.
        if not ai_updates and det_updates:
            ai_updates.update(det_updates)
            result["intent"] = det_parsed.get("intent", "search")

        result["updates"] = ai_updates
        return result

    @staticmethod
    def apply_onboarding_answer(
        prefs,
        updated_filters,
        merged_updates,
        target_field,
        lower,
        estimate_travel_limits,
    ):
        """Apply accepted profile answers without IO or saving."""
        accepted = False

        if target_field == "location" and merged_updates.get("locations"):
            prefs["location"] = [
                loc.lower() for loc in updated_filters["locations"]
            ]
            accepted = True
        if (
            target_field == "budget_per_person"
            and merged_updates.get("budget_per_person") is not None
            and updated_filters["budget_per_person"] is not None
        ):
            prefs["budget_per_person"] = updated_filters["budget_per_person"]
            accepted = True
        if target_field == "travel" and (
            merged_updates.get("max_travel_minutes") is not None
            or merged_updates.get("max_distance_km") is not None
        ):
            prefs.update(
                estimate_travel_limits(
                    {
                        key: val
                        for key, val in (
                            (
                                "max_travel_time_minutes",
                                updated_filters["max_travel_minutes"],
                            ),
                            (
                                "max_distance_km",
                                updated_filters["max_distance_km"],
                            ),
                        )
                        if val is not None
                    }
                )
            )
            accepted = True
        if target_field == "dietary_requirements" and (
            "dietary_requirements" in merged_updates or "both" in lower
        ):
            prefs["dietary_requirements"] = (
                ["halal", "vegetarian"]
                if "both" in lower
                else updated_filters["dietary_requirements"]
            )
            accepted = True
        if target_field == "liked_cuisines":
            supported = [
                c for c in updated_filters["liked_cuisines"] if c in CUISINES
            ]
            custom_liked = [
                f"{c} cuisine"
                for c in updated_filters["liked_cuisines"]
                if c not in CUISINES
            ]
            if supported or custom_liked:
                prefs["liked_cuisines"] = supported
                if custom_liked:
                    existing_other = list(prefs.get("other_preferences") or [])
                    existing_cf = {str(x).casefold() for x in existing_other}
                    for wish in custom_liked:
                        if wish.casefold() not in existing_cf:
                            existing_other.append(wish)
                    prefs["other_preferences"] = existing_other
                accepted = True
        if target_field == "disliked_cuisines":
            supported = [
                c
                for c in updated_filters["disliked_cuisines"]
                if c in CUISINES
            ]
            custom_disliked = [
                f"avoid {c} cuisine"
                for c in updated_filters["disliked_cuisines"]
                if c not in CUISINES
            ]
            if supported or custom_disliked:
                prefs["disliked_cuisines"] = supported
                if custom_disliked:
                    existing_other = list(prefs.get("other_preferences") or [])
                    existing_cf = {str(x).casefold() for x in existing_other}
                    for wish in custom_disliked:
                        if wish.casefold() not in existing_cf:
                            existing_other.append(wish)
                    prefs["other_preferences"] = existing_other
                accepted = True
        return accepted
