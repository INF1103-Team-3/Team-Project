"""Conversational BIS assistant: parses chat turns into synced search and profile actions."""
from copy import deepcopy
import re

from BIS.sources.profile_schema import CUISINES, DIETARY_CHOICES, NUMBER_LIMITS


_COMMON_CUSTOM_CUISINES = (
    "ramen", "sushi", "dim sum", "hawker", "zi char", "hotpot", "bbq",
    "bakery", "cafe", "seafood", "steamboat", "prata", "biryani", "fast food",
)

_ONBOARDING_QUESTIONS = {
    "location": (
        "Welcome to BiteFinder! Let's set up your profile. First, which starting location(s) "
        "in Singapore do you usually search around? (e.g. Compass One, Bugis, or 828761)",
        ["Compass One", "Bugis Junction", "Rivervale Plaza", "Jewel Changi"],
    ),
    "budget_per_person": (
        "Got it! What is your usual budget per person in SGD? (e.g. $15, $25, or $40)",
        ["$15", "$25", "$40", "$60"],
    ),
    "travel": (
        "How far or how long are you usually willing to travel? (e.g. 20 mins or 1.5 km)",
        ["15 mins walk", "30 mins walk", "2 km", "20 mins MRT"],
    ),
    "dietary_requirements": (
        "Do you have any dietary requirements to save? (Halal, Vegetarian, Both, or None)",
        ["Halal", "Vegetarian", "Both", "None"],
    ),
    "liked_cuisines": (
        "Which cuisines do you like most? (e.g. Japanese, Chinese, Korean — or None)",
        ["Japanese, Korean", "Chinese, Malay", "Western, Italian", "None"],
    ),
    "disliked_cuisines": (
        "Are there any cuisines you prefer to avoid? (or None)",
        ["None", "Indian", "Malay", "Thai"],
    ),
    "other_preferences": (
        "Any other regular preferences? (e.g. spicy food, at least 4.5 stars — or None)",
        ["At least 4.5 stars", "Spicy food", "Quiet", "None"],
    ),
}


class BISChatbotService:
    """Turn natural-language user messages into incremental filter updates and actions."""

    def __init__(self, ai, logic, config, model_reader=lambda: None, profile_saver=None):
        self._ai = ai
        self._logic = logic
        self._config = config
        self._model = model_reader
        self._save_profile = profile_saver

    @staticmethod
    def _normalize_location(raw):
        text = re.sub(r"\s+", " ", str(raw or "").strip()).strip(".,;!?")
        if not text:
            return ""
        if text.isdigit():
            return f"Singapore {text}"
        return text

    @classmethod
    def _default_filters(cls, user=None):
        prefs = (user or {}).get("preferences") or {}
        saved_locs = [
            cls._normalize_location(loc)
            for loc in (prefs.get("location") or [])
            if str(loc or "").strip()
        ]
        max_mins = prefs.get("max_travel_time_minutes")
        max_km = prefs.get("max_distance_km")
        if max_mins is not None:
            max_km = None
        budget = prefs.get("budget_per_person")
        return {
            "location": saved_locs[0] if saved_locs else "",
            "locations": saved_locs,
            "mode": "walk",
            "traffic_aware": False,
            "max_travel_minutes": float(max_mins) if max_mins is not None else None,
            "max_distance_km": float(max_km) if max_km is not None else None,
            "budget_per_person": float(budget) if budget is not None else None,
            "dietary_requirements": list(prefs.get("dietary_requirements") or []),
            "liked_cuisines": [str(c).strip().lower() for c in (prefs.get("liked_cuisines") or []) if str(c).strip()],
            "disliked_cuisines": [str(c).strip().lower() for c in (prefs.get("disliked_cuisines") or []) if str(c).strip()],
            "other_preferences": [str(p).strip() for p in (prefs.get("other_preferences") or []) if str(p).strip()],
        }

    @classmethod
    def normalize_filters(cls, raw, user=None):
        defaults = cls._default_filters(user)
        if not isinstance(raw, dict):
            return defaults

        locs = []
        for entry in (raw.get("locations") or []):
            clean = cls._normalize_location(entry)
            if clean and clean.casefold() not in {x.casefold() for x in locs}:
                locs.append(clean)
        primary = cls._normalize_location(raw.get("location"))
        if primary and primary.casefold() not in {x.casefold() for x in locs}:
            locs.insert(0, primary)

        mode = str(raw.get("mode") or defaults["mode"]).strip().lower()
        if mode not in ("walk", "drive", "transit"):
            mode = "walk"

        max_mins = raw.get("max_travel_minutes") if "max_travel_minutes" in raw else defaults["max_travel_minutes"]
        max_km = raw.get("max_distance_km") if "max_distance_km" in raw else defaults["max_distance_km"]
        if isinstance(max_mins, (int, float)) and not isinstance(max_mins, bool) and max_mins > 0:
            low, high = NUMBER_LIMITS["max_travel_time_minutes"]
            max_mins = round(max(low, min(high, float(max_mins))), 1)
            max_km = None
        elif isinstance(max_km, (int, float)) and not isinstance(max_km, bool) and max_km > 0:
            low, high = NUMBER_LIMITS["max_distance_km"]
            max_km = round(max(low, min(high, float(max_km))), 2)
            max_mins = None
        else:
            max_mins = None
            max_km = None

        budget = raw.get("budget_per_person") if "budget_per_person" in raw else defaults["budget_per_person"]
        if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
            b_low, b_high = NUMBER_LIMITS["budget_per_person"]
            budget = round(max(b_low, min(b_high, float(budget))), 2)
        else:
            budget = None

        diet = []
        for item in (raw.get("dietary_requirements") or []):
            clean = str(item or "").strip().lower()
            if clean in DIETARY_CHOICES and clean not in diet:
                diet.append(clean)

        liked = []
        for item in (raw.get("liked_cuisines") or []):
            clean = str(item or "").strip().lower()
            if clean and clean not in ("none", "any", "any cuisine") and clean not in liked:
                liked.append(clean)

        disliked = []
        for item in (raw.get("disliked_cuisines") or []):
            clean = str(item or "").strip().lower()
            if clean in CUISINES and clean not in disliked and clean not in liked:
                disliked.append(clean)

        other = []
        for item in (raw.get("other_preferences") or []):
            clean = str(item or "").strip()
            if clean and clean.casefold() not in {o.casefold() for o in other}:
                other.append(clean)

        return {
            "location": locs[0] if locs else "",
            "locations": locs,
            "mode": mode,
            "traffic_aware": bool(raw.get("traffic_aware") and mode == "drive"),
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
        for entry in (incoming or []):
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
    def _apply_updates(cls, current, updates, user=None):
        result = deepcopy(current)
        if not isinstance(updates, dict):
            return result

        locs_in = updates.get("locations")
        loc_action = updates.get("locations_action") or "replace"
        if loc_action == "clear":
            result["locations"] = []
            result["location"] = ""
        elif isinstance(locs_in, list) and locs_in:
            cleaned = [cls._normalize_location(loc) for loc in locs_in if cls._normalize_location(loc)]
            result["locations"] = cls._merge_list(result["locations"], cleaned, loc_action)
            result["location"] = result["locations"][0] if result["locations"] else ""

        mode = str(updates.get("mode") or "").strip().lower()
        if mode in ("walk", "drive", "transit"):
            result["mode"] = mode
            if mode != "drive":
                result["traffic_aware"] = False

        if updates.get("traffic_aware") is not None and result["mode"] == "drive":
            result["traffic_aware"] = bool(updates.get("traffic_aware"))

        mins = updates.get("max_travel_minutes")
        km = updates.get("max_distance_km")
        if isinstance(mins, (int, float)) and not isinstance(mins, bool) and mins > 0:
            result["max_travel_minutes"] = mins
            result["max_distance_km"] = None
        elif isinstance(km, (int, float)) and not isinstance(km, bool) and km > 0:
            result["max_distance_km"] = km
            result["max_travel_minutes"] = None

        budget = updates.get("budget_per_person")
        if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
            result["budget_per_person"] = budget

        if isinstance(updates.get("dietary_requirements"), list) or updates.get("dietary_action") == "clear":
            action = updates.get("dietary_action") or "replace"
            result["dietary_requirements"] = cls._merge_list(
                result["dietary_requirements"],
                updates.get("dietary_requirements") or [],
                action,
                allowed=set(DIETARY_CHOICES),
            )

        if isinstance(updates.get("liked_cuisines"), list) or updates.get("liked_action") == "clear":
            action = updates.get("liked_action") or "replace"
            raw_liked = [str(c).strip().lower() for c in (updates.get("liked_cuisines") or []) if str(c).strip()]
            result["liked_cuisines"] = cls._merge_list(result["liked_cuisines"], raw_liked, action)
            liked_keys = {c.casefold() for c in result["liked_cuisines"]}
            result["disliked_cuisines"] = [
                d for d in result["disliked_cuisines"] if d.casefold() not in liked_keys
            ]

        if isinstance(updates.get("disliked_cuisines"), list) or updates.get("disliked_action") == "clear":
            action = updates.get("disliked_action") or "add"
            result["disliked_cuisines"] = cls._merge_list(
                result["disliked_cuisines"],
                updates.get("disliked_cuisines") or [],
                action,
                allowed=set(CUISINES),
            )
            disliked_keys = {d.casefold() for d in result["disliked_cuisines"]}
            result["liked_cuisines"] = [
                c for c in result["liked_cuisines"] if c.casefold() not in disliked_keys
            ]

        if isinstance(updates.get("other_preferences"), list) or updates.get("other_action") == "clear":
            action = updates.get("other_action") or "add"
            result["other_preferences"] = cls._merge_list(
                result["other_preferences"],
                updates.get("other_preferences") or [],
                action,
            )

        return cls.normalize_filters(result, user=user)

    @classmethod
    def _parse_contextual_answer(cls, message, awaiting_field):
        """Parse concise direct answers when the chatbot just asked a targeted question."""
        text = str(message or "").strip()
        lower = text.casefold()
        updates = {}
        if not awaiting_field or not text:
            return updates

        if awaiting_field == "budget_per_person":
            num_match = re.search(r"^\s*(?:sgd|\$)?\s*(\d+(?:\.\d+)?)\s*(?:dollars?|sgd)?\s*$", lower)
            if num_match:
                updates["budget_per_person"] = float(num_match.group(1))
        elif awaiting_field == "travel":
            if re.search(r"\b(?:drive|driving|car)\b", lower):
                updates["mode"] = "drive"
            elif re.search(r"\b(?:transit|mrt|bus|train|public transport)\b", lower):
                updates["mode"] = "transit"
            elif re.search(r"\b(?:walk|walking|foot)\b", lower):
                updates["mode"] = "walk"
            km_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometres?|kilometers?)\b", lower)
            mins_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|mins?|minutes?)?\b", lower)
            if km_match:
                updates["max_distance_km"] = float(km_match.group(1))
            elif mins_match:
                updates["max_travel_minutes"] = float(mins_match.group(1))
        elif awaiting_field == "location":
            between = re.search(
                r"\b(?:between\s+)?([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)$",
                text,
                re.IGNORECASE,
            )
            if between and not re.search(r"\b(?:halal|vegetarian|budget|walk|drive|transit)\b", lower):
                updates["locations"] = [between.group(1).strip(), between.group(2).strip()]
                updates["locations_action"] = "replace"
            elif "," in text and len(text) < 120:
                parts = [p.strip() for p in text.split(",") if p.strip()]
                if parts:
                    updates["locations"] = parts
                    updates["locations_action"] = "replace"
            elif len(text) <= 80 and not re.search(r"\b(?:help|cancel|reset|profile|none|skip)\b", lower):
                updates["locations"] = [text]
                updates["locations_action"] = "replace"
        return updates

    @classmethod
    def _deterministic_parse(cls, message, current, user, awaiting_field=None):
        text = str(message or "").strip()
        lower = text.casefold()

        if lower in ("/help", "help", "commands", "what can you do", "how does this work"):
            return {
                "intent": "help",
                "reply": (
                    "Just tell me what you're craving! Combine location, budget, travel time/distance, "
                    "cuisine, dietary needs, or ratings — or let me walk you through step-by-step."
                ),
                "updates": {},
                "quick_replies": [
                    "Halal Japanese near Bugis under $20, 15 mins walk",
                    "Meet between Tampines and Jurong East",
                    "At least 4.5 stars near Compass One",
                ],
            }

        if lower in ("/profile", "show profile", "show my profile", "my profile", "view profile"):
            return {
                "intent": "show_profile",
                "reply": cls._format_profile_summary(user),
                "updates": {},
                "quick_replies": ["Use my saved profile", "Help"],
            }

        if re.search(r"\b(?:save|remember|store)\b.*\b(?:profile|default|preferences)\b", lower) or lower == "/save":
            return {
                "intent": "save_profile",
                "reply": "Saving your current preferences to your profile.",
                "updates": {},
                "quick_replies": ["Search now", "Show my profile"],
            }

        if lower in ("/reset", "reset", "clear filters", "start over") or "use my saved profile" in lower:
            return {
                "intent": "reset",
                "reply": (
                    "Restored your saved profile defaults."
                    if user and user.get("preferences")
                    else "Cleared filters. Tell me your starting location, budget, and travel limit to search!"
                ),
                "updates": {},
                "quick_replies": (
                    ["Search now", "Halal Japanese under $20"]
                    if user and user.get("preferences")
                    else ["Bugis Junction", "Compass One", "Rivervale Plaza"]
                ),
            }

        updates = cls._parse_contextual_answer(text, awaiting_field)
        between = re.search(
            r"\bbetween\s+([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)(?=$|\s+(?:for|with|under|below|within|by|walk|drive|transit|mrt)\b|[.,!?])",
            text,
            re.IGNORECASE,
        )
        if between:
            updates["locations"] = [between.group(1).strip(), between.group(2).strip()]
            updates["locations_action"] = "replace"
        elif "locations" not in updates:
            postal = re.search(r"\b(\d{6})\b", text)
            loc_match = re.search(
                r"\b(?:near|around|at(?!\s+(?:least|most|all)\b)|in(?!\s+(?:general|mind)\b)|by(?!\s+(?:walk|drive|transit|mrt|bus|train|car|foot)\b))\s+([A-Za-z0-9][A-Za-z0-9\s,'-]{1,45}?)(?=$|\s+(?:for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian)\b|[.,!?])",
                text,
                re.IGNORECASE,
            )
            if loc_match:
                candidate_loc = loc_match.group(1).strip()
                if (
                    candidate_loc.casefold() not in ("halal", "vegetarian", "walk", "drive", "transit", "mrt", "singapore")
                    and not re.match(r"^(?:least|most|min|minimum|max|under|below)\b", candidate_loc, re.IGNORECASE)
                ):
                    updates["locations"] = [candidate_loc]
                    updates["locations_action"] = "replace"
            elif postal:
                updates["locations"] = [postal.group(1)]
                updates["locations_action"] = "replace"

        if re.search(r"\b(?:drive|driving|car)\b", lower):
            updates["mode"] = "drive"
            if "traffic" in lower:
                updates["traffic_aware"] = True
        elif re.search(r"\b(?:transit|mrt|bus|train|public transport)\b", lower):
            updates["mode"] = "transit"
        elif re.search(r"\b(?:walk|walking|on foot)\b", lower):
            updates["mode"] = "walk"

        mins_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mins?|minutes?)\b", lower)
        km_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:km|kilometres?|kilometers?)\b", lower)
        if mins_match:
            updates["max_travel_minutes"] = float(mins_match.group(1))
        elif km_match:
            updates["max_distance_km"] = float(km_match.group(1))

        budget_match = re.search(
            r"(?:\$\s*(\d+(?:\.\d+)?))|\b(?:under|below|budget|max)\s*(?:sgd|\$)?\s*(\d+(?:\.\d+)?)\b",
            lower,
        )
        if budget_match:
            raw_b = budget_match.group(1) or budget_match.group(2)
            updates["budget_per_person"] = float(raw_b)

        diet_add, diet_rem = [], []
        if re.search(r"\b(?:non[- ]?halal|no halal|not halal)\b", lower):
            diet_rem.append("halal")
        elif "halal" in lower or "muis" in lower:
            diet_add.append("halal")
        if re.search(r"\b(?:not vegetarian|no vegetarian)\b", lower):
            diet_rem.append("vegetarian")
        elif re.search(r"\b(?:vegetarian|veggie|plant[- ]based)\b", lower):
            diet_add.append("vegetarian")
        if "no dietary" in lower or "no restrictions" in lower:
            updates["dietary_action"] = "clear"
        elif diet_add:
            updates["dietary_requirements"] = diet_add
            updates["dietary_action"] = "add"
        elif diet_rem:
            updates["dietary_requirements"] = diet_rem
            updates["dietary_action"] = "remove"

        liked, disliked = [], []
        for cuisine in tuple(CUISINES) + _COMMON_CUSTOM_CUISINES:
            if not re.search(rf"\b{re.escape(cuisine)}\b", lower):
                continue
            if (
                awaiting_field == "disliked_cuisines"
                or re.search(rf"\b(?:no|avoid|dislike|exclude|not|without)\s+{re.escape(cuisine)}\b", lower)
            ):
                if cuisine in CUISINES:
                    disliked.append(cuisine)
            else:
                liked.append(cuisine)
        if "any cuisine" in lower or "clear cuisine" in lower:
            updates["liked_action"] = "clear"
        elif liked:
            updates["liked_cuisines"] = liked
            updates["liked_action"] = "replace" if re.search(r"\b(?:switch|change|instead|only)\b", lower) else "add"
        if disliked:
            updates["disliked_cuisines"] = disliked
            updates["disliked_action"] = "add"

        other = []
        rating_match = re.search(
            r"\b(?:at least|minimum|min|>=)?\s*([1-5](?:\.\d+)?)\s*(?:stars?|/\s*5)\b",
            lower,
        )
        if rating_match:
            rating_val = rating_match.group(1)
            other.append(
                f"at least {rating_val} stars"
                if re.search(r"\b(?:at least|minimum|min|>=)\b", lower)
                else f"{rating_val} stars"
            )
        for kw in ("spicy", "quiet", "open 24 hours", "24 hours", "outdoor seating", "aircon"):
            if kw in lower:
                other.append(kw)
        if "only " in lower and liked and liked[0] in CUISINES:
            other.append(f"only {liked[0]} cuisine")
        if other:
            updates["other_preferences"] = other
            updates["other_action"] = "add"

        has_search_signal = bool(
            updates
            or re.search(r"\b(?:search|find|recommend|suggest|eat|food|dinner|lunch|breakfast|supper|restaurant|cafe|hungry|retry)\b", lower)
            or lower in ("yes", "go", "go ahead", "search now", "ok", "okay", "try again")
        )
        if not has_search_signal:
            return {
                "intent": "clarify",
                "reply": (
                    "Tell me what you'd like to eat, or start with your location, budget, and travel limit!"
                ),
                "updates": {},
                "quick_replies": [
                    "Halal Japanese near Bugis under $20, 15 mins walk",
                    "Compass One",
                    "Bugis Junction",
                ],
            }

        return {
            "intent": "search",
            "reply": "Got it! Updating your search preferences and finding matching restaurants now.",
            "updates": updates,
            "quick_replies": [],
        }

    @staticmethod
    def _next_missing_search_field(filters):
        if not filters.get("locations"):
            return "location"
        if filters.get("budget_per_person") is None:
            return "budget_per_person"
        if filters.get("max_travel_minutes") is None and filters.get("max_distance_km") is None:
            return "travel"
        return None

    @staticmethod
    def _prompt_for_missing_search_field(field):
        if field == "location":
            return (
                "Where in Singapore would you like me to search? Enter an area, landmark, MRT, or 6-digit postal code (or 'between X and Y').",
                ["Bugis Junction", "Compass One", "Rivervale Plaza", "Jewel Changi"],
            )
        if field == "budget_per_person":
            return (
                "What is your budget per person in SGD? (e.g. $15, $25, or $40)",
                ["$15", "$25", "$40", "$60"],
            )
        return (
            "How far or how long are you willing to travel? (e.g. 15 mins walk, 2 km, or 20 mins MRT)",
            ["15 mins walk", "30 mins walk", "2 km", "20 mins MRT"],
        )

    @staticmethod
    def _next_onboarding_field(prefs):
        if not prefs.get("location"):
            return "location"
        if prefs.get("budget_per_person") is None:
            return "budget_per_person"
        if prefs.get("max_travel_time_minutes") is None and prefs.get("max_distance_km") is None:
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

    def _build_safe_profile_payload(self, user, filters, fallback_prefs=None):
        prefs = fallback_prefs if fallback_prefs is not None else ((user or {}).get("preferences") or {})
        supported_liked = []
        extra_other = list(filters.get("other_preferences") or [])
        for cuisine in (filters.get("liked_cuisines") or []):
            clean = str(cuisine or "").strip().lower()
            if clean in CUISINES:
                if clean not in supported_liked:
                    supported_liked.append(clean)
            elif clean:
                custom_wish = f"{clean} cuisine"
                if custom_wish.casefold() not in {o.casefold() for o in extra_other}:
                    extra_other.append(custom_wish)

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
            "disliked_cuisines": [c for c in (filters.get("disliked_cuisines") or []) if c in CUISINES],
            "other_preferences": extra_other,
        }

    def _handle_onboarding(self, user, message, awaiting_field, current):
        prefs = deepcopy((user or {}).get("preferences") or {})
        text = str(message or "").strip()
        lower = text.casefold()
        next_needed = self._next_onboarding_field(prefs)

        if text == "__start_onboarding__" or not next_needed:
            if not next_needed:
                filters = self._default_filters(user)
                return {
                    "success": True,
                    "action": "confirm",
                    "awaiting_field": "confirm",
                    "reply": self._format_confirmation_reply(
                        filters,
                        prefix="Your BiteFinder profile is already set up!",
                    ),
                    "filters": filters,
                    "changes": [],
                    "quick_replies": self._confirmation_quick_replies(filters, True),
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            prompt, quick_replies = _ONBOARDING_QUESTIONS[next_needed]
            step_num = list(_ONBOARDING_QUESTIONS.keys()).index(next_needed) + 1
            return {
                "success": True,
                "action": "onboarding",
                "awaiting_field": next_needed,
                "onboarding_step": step_num,
                "onboarding_total": len(_ONBOARDING_QUESTIONS),
                "reply": prompt,
                "filters": current,
                "changes": [],
                "quick_replies": quick_replies,
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        target_field = awaiting_field if awaiting_field in _ONBOARDING_QUESTIONS else next_needed
        is_none_answer = lower in ("none", "no", "nil", "n/a", "skip", "skip for now", "anything", "any")
        updates = {}

        if target_field in ("dietary_requirements", "liked_cuisines", "disliked_cuisines", "other_preferences") and is_none_answer:
            prefs[target_field] = []
        else:
            parsed = None
            if not self._config.get("ai_bypass") and hasattr(self._ai, "chat_turn"):
                try:
                    parsed = self._ai.chat_turn(
                        f"[Profile setup question for {target_field}] User answered: {text}",
                        current, [], prefs, deepcopy(self._config),
                    )
                except (RuntimeError, ValueError, TypeError):
                    parsed = None
            raw_updates = (parsed or {}).get("updates") or {}
            det_updates = self._deterministic_parse(text, current, user, awaiting_field=target_field).get("updates") or {}
            merged_updates = dict(det_updates)
            merged_updates.update({k: v for k, v in raw_updates.items() if v is not None})

            updated_filters = self._apply_updates(current, merged_updates, user=user)
            accepted = False

            if target_field == "location" and merged_updates.get("locations"):
                prefs["location"] = [loc.lower() for loc in updated_filters["locations"]]
                accepted = True
            if target_field == "budget_per_person" and merged_updates.get("budget_per_person") is not None and updated_filters["budget_per_person"] is not None:
                prefs["budget_per_person"] = updated_filters["budget_per_person"]
                accepted = True
            if target_field == "travel" and (merged_updates.get("max_travel_minutes") is not None or merged_updates.get("max_distance_km") is not None):
                prefs.update(self._logic.estimate_travel_limits({
                    key: val for key, val in (
                        ("max_travel_time_minutes", updated_filters["max_travel_minutes"]),
                        ("max_distance_km", updated_filters["max_distance_km"]),
                    ) if val is not None
                }))
                accepted = True
            if target_field == "dietary_requirements" and ("dietary_requirements" in merged_updates or "both" in lower):
                prefs["dietary_requirements"] = ["halal", "vegetarian"] if "both" in lower else updated_filters["dietary_requirements"]
                accepted = True
            if target_field == "liked_cuisines":
                supported = [c for c in updated_filters["liked_cuisines"] if c in CUISINES]
                if supported:
                    prefs["liked_cuisines"] = supported
                    accepted = True
            if target_field == "disliked_cuisines":
                if updated_filters["disliked_cuisines"]:
                    prefs["disliked_cuisines"] = updated_filters["disliked_cuisines"]
                    accepted = True
            if target_field == "other_preferences":
                prefs["other_preferences"] = updated_filters["other_preferences"] or [text]
                accepted = True

            if not accepted:
                prompt, quick_replies = _ONBOARDING_QUESTIONS[target_field]
                step_num = list(_ONBOARDING_QUESTIONS.keys()).index(target_field) + 1
                return {
                    "success": True,
                    "action": "onboarding",
                    "awaiting_field": target_field,
                    "onboarding_step": step_num,
                    "onboarding_total": len(_ONBOARDING_QUESTIONS),
                    "reply": f"I didn't catch a valid value for {target_field.replace('_', ' ')}. {prompt}",
                    "filters": current,
                    "changes": [],
                    "quick_replies": quick_replies,
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }

        # Persist only already-answered profile fields directly via save_profile when possible
        saved_user = user
        if self._save_profile is not None:
            answered_payload = {"user_id": user["userID"]}
            for field in (
                "location", "max_distance_km", "max_travel_time_minutes",
                "budget_per_person", "dietary_requirements", "liked_cuisines",
                "disliked_cuisines", "other_preferences",
            ):
                if prefs.get(field) is not None:
                    answered_payload[field] = prefs[field]
            saved_user = self._save_profile(user, answered_payload)

        updated_filters = self._default_filters(saved_user)
        if not updated_filters.get("locations") and prefs.get("location"):
            updated_filters["locations"] = [self._normalize_location(loc) for loc in prefs["location"]]
            updated_filters["location"] = updated_filters["locations"][0]
        if current.get("mode") in ("walk", "drive", "transit"):
            updated_filters["mode"] = current["mode"]

        changes = self._summarize_changes(current, updated_filters)
        remaining = self._next_onboarding_field(saved_user.get("preferences") or prefs)
        if remaining:
            next_prompt, quick_replies = _ONBOARDING_QUESTIONS[remaining]
            step_num = list(_ONBOARDING_QUESTIONS.keys()).index(remaining) + 1
            return {
                "success": True,
                "action": "onboarding",
                "awaiting_field": remaining,
                "onboarding_step": step_num,
                "onboarding_total": len(_ONBOARDING_QUESTIONS),
                "reply": f"Saved! {next_prompt}",
                "filters": updated_filters,
                "changes": changes,
                "quick_replies": quick_replies,
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": True,
            }

        return {
            "success": True,
            "action": "confirm",
            "awaiting_field": "confirm",
            "onboarding_step": len(_ONBOARDING_QUESTIONS),
            "onboarding_total": len(_ONBOARDING_QUESTIONS),
            "reply": self._format_confirmation_reply(
                updated_filters,
                prefix="Your BiteFinder profile is complete and saved!",
            ),
            "filters": updated_filters,
            "changes": changes,
            "quick_replies": self._confirmation_quick_replies(updated_filters, True),
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": True,
        }

    @staticmethod
    def _format_profile_summary(user):
        if not user:
            return "You're currently browsing as a guest. Sign in to load and save default preferences."
        prefs = user.get("preferences") or {}
        locs = ", ".join(prefs.get("location") or []) or "Not set"
        budget = f"SGD ${prefs['budget_per_person']}" if prefs.get("budget_per_person") else "Not set"
        diet = ", ".join(prefs.get("dietary_requirements") or []) or "Not set"
        liked = ", ".join(prefs.get("liked_cuisines") or []) or "Any / Not set"
        return (
            f"Saved profile for {user.get('username', 'User')}: "
            f"Locations [{locs}], Budget [{budget}], Dietary [{diet}], Likes [{liked}]."
        )

    @staticmethod
    def _default_quick_replies(filters, signed_in):
        suggestions = []
        budget = filters.get("budget_per_person")
        if budget is None or float(budget) > 15:
            suggestions.append("Under $15")
        if "halal" not in (filters.get("dietary_requirements") or []):
            suggestions.append("Halal only")
        if not any("star" in p.casefold() for p in (filters.get("other_preferences") or [])):
            suggestions.append("At least 4.5 stars")
        if filters.get("mode") == "walk":
            suggestions.append("Switch to transit")
        else:
            suggestions.append("Walk 15 mins")
        if signed_in and len(suggestions) < 4:
            suggestions.append("Save to profile")
        return suggestions[:4]

    @staticmethod
    def _summarize_changes(before, after):
        changes = []
        if before.get("locations") != after.get("locations") and after.get("locations"):
            changes.append("📍 " + " + ".join(after["locations"]))
        if (before.get("mode"), before.get("max_travel_minutes"), before.get("max_distance_km")) != (
            after.get("mode"), after.get("max_travel_minutes"), after.get("max_distance_km")
        ):
            icon = {"walk": "🚶 Walk", "drive": "🚗 Drive", "transit": "🚆 Transit"}.get(after["mode"], "🚶 Walk")
            if after.get("max_distance_km") is not None:
                changes.append(f"{icon} · {after['max_distance_km']:g}km")
            elif after.get("max_travel_minutes") is not None:
                changes.append(f"{icon} · {int(round(after['max_travel_minutes']))}m")
        if before.get("budget_per_person") != after.get("budget_per_person") and after.get("budget_per_person") is not None:
            changes.append(f"💰 SGD ${after['budget_per_person']:g}")
        if before.get("dietary_requirements") != after.get("dietary_requirements"):
            if after.get("dietary_requirements"):
                badges = [
                    "🕌 Halal" if d == "halal" else "🥗 Vegetarian"
                    for d in after["dietary_requirements"]
                ]
                changes.extend(badges)
            else:
                changes.append("No dietary limits")
        if before.get("liked_cuisines") != after.get("liked_cuisines"):
            if after.get("liked_cuisines"):
                changes.append("🍽️ " + ", ".join(c.title() for c in after["liked_cuisines"]))
            else:
                changes.append("Any cuisine")
        if before.get("disliked_cuisines") != after.get("disliked_cuisines") and after.get("disliked_cuisines"):
            changes.append("🚫 No " + ", ".join(c.title() for c in after["disliked_cuisines"]))
        if before.get("other_preferences") != after.get("other_preferences") and after.get("other_preferences"):
            changes.append("✨ " + ", ".join(after["other_preferences"]))
        return changes

    _CONFIRM_PHRASES = {
        "yes", "yes search now", "yes, search now", "yes please", "yep", "yeah",
        "yup", "sure", "ok", "okay", "confirm", "confirmed", "correct",
        "looks good", "sounds good", "all good", "all correct", "that's right",
        "thats right", "go ahead", "proceed", "search", "search now",
        "find now", "run search", "start search", "do it", "retry search",
        "try again",
    }

    @classmethod
    def _is_search_confirmation(cls, message):
        cleaned = re.sub(r"[.!?\s]+$", "", str(message or "").casefold().strip())
        return cleaned in cls._CONFIRM_PHRASES

    @staticmethod
    def _format_confirmation_reply(filters, prefix="Here is your current search setup:"):
        locs = " + ".join(filters.get("locations") or []) or "Not set"
        loc_label = "Meet between" if len(filters.get("locations") or []) > 1 else "Location"
        mode_name = {"walk": "Walk", "drive": "Drive", "transit": "Transit"}.get(filters.get("mode"), "Walk")
        if filters.get("max_distance_km") is not None:
            travel = f"{mode_name} · {filters['max_distance_km']:g} km"
        elif filters.get("max_travel_minutes") is not None:
            travel = f"{mode_name} · {int(round(filters['max_travel_minutes']))} mins"
        else:
            travel = "Not set"
        budget = f"SGD ${filters['budget_per_person']:g}" if filters.get("budget_per_person") is not None else "Not set"
        diet = ", ".join(d.title() for d in (filters.get("dietary_requirements") or [])) or "None"
        liked = ", ".join(c.title() for c in (filters.get("liked_cuisines") or [])) or "Any"
        parts = [f"{loc_label}: {locs}", f"Travel: {travel}", f"Budget: {budget}", f"Dietary: {diet}", f"Cuisines: {liked}"]
        if filters.get("disliked_cuisines"):
            parts.append("Avoid: " + ", ".join(c.title() for c in filters["disliked_cuisines"]))
        if filters.get("other_preferences"):
            parts.append("Wishes: " + ", ".join(filters["other_preferences"]))
        return f"{prefix} {' | '.join(parts)}. Should I proceed with searching, or would you like to change anything?"

    @staticmethod
    def _confirmation_quick_replies(filters, signed_in):
        replies = ["Yes, search now", "Change location", "Change budget", "Edit cuisines"]
        if signed_in and len(replies) < 4:
            replies[3] = "Save to profile"
        return replies

    def _handle_edit_request(self, lower, current):
        cleaned = re.sub(r"[.!?\s]+$", "", lower.strip())
        if cleaned in ("change location", "edit location", "change starting location"):
            prompt, qrs = self._prompt_for_missing_search_field("location")
            return {
                "success": True,
                "action": "clarify",
                "awaiting_field": "location",
                "reply": prompt,
                "filters": current,
                "changes": [],
                "quick_replies": qrs,
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }
        if cleaned in ("change budget", "edit budget"):
            prompt, qrs = self._prompt_for_missing_search_field("budget_per_person")
            return {
                "success": True,
                "action": "clarify",
                "awaiting_field": "budget_per_person",
                "reply": prompt,
                "filters": current,
                "changes": [],
                "quick_replies": qrs,
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }
        if cleaned in ("change travel", "edit travel", "change time", "change distance"):
            prompt, qrs = self._prompt_for_missing_search_field("travel")
            return {
                "success": True,
                "action": "clarify",
                "awaiting_field": "travel",
                "reply": prompt,
                "filters": current,
                "changes": [],
                "quick_replies": qrs,
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }
        if cleaned in ("change cuisine", "edit cuisine", "edit cuisines", "change cuisines"):
            return {
                "success": True,
                "action": "clarify",
                "awaiting_field": "confirm",
                "reply": "Which cuisines would you like to search for instead? (e.g. 'Japanese, Korean' or 'any cuisine')",
                "filters": current,
                "changes": [],
                "quick_replies": ["Japanese, Korean", "Halal only", "Any cuisine", "Yes, search now"],
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }
        if cleaned in ("no", "not yet", "wait", "edit", "change something", "cancel"):
            return {
                "success": True,
                "action": "clarify",
                "awaiting_field": "confirm",
                "reply": "No problem! Tell me what you'd like to adjust (location, budget, travel limit, dietary needs, cuisines, or wishes).",
                "filters": current,
                "changes": [],
                "quick_replies": ["Change location", "Change budget", "Change travel", "Edit cuisines"],
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }
        return None

    def respond(self, user, payload):
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("Please enter a message for the BiteFinder chatbot.")

        current = self.normalize_filters(payload.get("current_filters"), user=user)
        awaiting_field = payload.get("awaiting_field")

        if payload.get("onboarding") and user:
            return self._handle_onboarding(user, message, awaiting_field, current)

        lower = message.casefold().strip()
        edit_reply = self._handle_edit_request(lower, current)
        if edit_reply is not None:
            return edit_reply

        if self._is_search_confirmation(lower):
            missing_field = self._next_missing_search_field(current)
            if missing_field:
                prompt, qrs = self._prompt_for_missing_search_field(missing_field)
                return {
                    "success": True,
                    "action": "clarify",
                    "awaiting_field": missing_field,
                    "reply": prompt,
                    "filters": current,
                    "changes": [],
                    "quick_replies": qrs,
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            return {
                "success": True,
                "action": "search",
                "awaiting_field": None,
                "reply": "Confirmed! Searching Google Places, travel routes, and MUIS records now.",
                "filters": current,
                "changes": [],
                "quick_replies": self._default_quick_replies(current, bool(user)),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        history = [
            {"role": str(item.get("role", "")), "text": str(item.get("text", ""))[:300]}
            for item in (payload.get("history") or [])[-6:]
            if isinstance(item, dict) and item.get("text")
        ]

        parsed = None
        if not self._config.get("ai_bypass") and hasattr(self._ai, "chat_turn"):
            is_utility = lower in ("/help", "help", "/profile", "/reset", "reset", "/save")
            if not is_utility:
                try:
                    saved_profile = (user or {}).get("preferences") or {}
                    ai_msg = (
                        f"[Answering question for {awaiting_field}] {message}"
                        if awaiting_field and awaiting_field != "confirm" else message
                    )
                    parsed = self._ai.chat_turn(ai_msg, current, history, saved_profile, deepcopy(self._config))
                except (RuntimeError, ValueError, TypeError):
                    parsed = None

        if parsed is None:
            det_awaiting = None if awaiting_field == "confirm" else awaiting_field
            parsed = self._deterministic_parse(message, current, user, awaiting_field=det_awaiting)
        elif awaiting_field and awaiting_field != "confirm" and not parsed.get("updates"):
            ctx_updates = self._parse_contextual_answer(message, awaiting_field)
            if ctx_updates:
                parsed["updates"] = ctx_updates
                parsed["intent"] = "search"

        intent = parsed["intent"]
        reply = str(parsed.get("reply") or "").strip()
        quick_replies = [
            str(q).strip()[:45] for q in (parsed.get("quick_replies") or [])
            if str(q).strip()
        ][:4]

        if intent == "reset":
            updated = self._default_filters(user)
            changes = self._summarize_changes(current, updated)
            if not changes and updated.get("locations"):
                changes = ["📍 " + " + ".join(updated["locations"])]
            return {
                "success": True,
                "action": "reset",
                "awaiting_field": None,
                "reply": reply or "Filters reset.",
                "filters": updated,
                "changes": changes,
                "quick_replies": quick_replies or self._default_quick_replies(updated, bool(user)),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        updated = self._apply_updates(current, parsed.get("updates"), user=user)
        changes = self._summarize_changes(current, updated)
        saved_to_profile = False

        if intent == "save_profile":
            if not user or self._save_profile is None:
                return {
                    "success": True,
                    "action": "clarify",
                    "awaiting_field": None,
                    "reply": "Please sign in first so I can save your preferences to your BiteFinder profile.",
                    "filters": updated,
                    "changes": changes,
                    "quick_replies": ["Yes, search now", "Help"],
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            profile_payload = self._build_safe_profile_payload(user, updated)
            self._save_profile(user, profile_payload)
            saved_to_profile = True
            reply = "Saved your current preferences to your BiteFinder profile."

        elif intent == "show_profile":
            reply = self._format_profile_summary(user)

        elif intent == "search" or bool(parsed.get("updates")):
            missing_field = self._next_missing_search_field(updated)
            if missing_field:
                intent = "clarify"
                reply, quick_replies = self._prompt_for_missing_search_field(missing_field)
                return {
                    "success": True,
                    "action": intent,
                    "awaiting_field": missing_field,
                    "reply": reply,
                    "filters": updated,
                    "changes": changes,
                    "quick_replies": quick_replies,
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            return {
                "success": True,
                "action": "confirm",
                "awaiting_field": "confirm",
                "reply": self._format_confirmation_reply(updated, prefix="Got it! Please check if everything looks right:"),
                "filters": updated,
                "changes": changes,
                "quick_replies": self._confirmation_quick_replies(updated, bool(user)),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        return {
            "success": True,
            "action": intent,
            "awaiting_field": self._next_missing_search_field(updated) if intent == "clarify" else None,
            "reply": reply,
            "filters": updated,
            "changes": changes,
            "quick_replies": quick_replies or self._default_quick_replies(updated, bool(user)),
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": saved_to_profile,
        }
