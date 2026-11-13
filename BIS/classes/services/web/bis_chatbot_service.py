"""Conversational BIS assistant: parses chat turns into synced search and profile actions."""
from copy import deepcopy
import re

from BIS.sources.profile_schema import CUISINES, DIETARY_CHOICES, NUMBER_LIMITS


_COMMON_CUSTOM_CUISINES = (
    "ramen", "sushi", "dim sum", "hawker", "zi char", "hotpot", "bbq",
    "bakery", "cafe", "seafood", "steamboat", "prata", "biryani", "fast food",
    "mexican", "spanish", "french", "turkish", "mediterranean", "taiwanese",
    "cantonese", "filipino", "burmese", "lebanese", "greek", "steak",
    "burger", "burgers", "pizza", "pasta", "noodles", "dessert", "brunch",
)

_STOP_WORDS_NOT_CUISINES = {
    "halal", "muis", "vegetarian", "veggie", "veg", "plant", "dietary",
    "limit", "limits", "restriction", "restrictions", "budget", "location",
    "locations", "travel", "time", "distance", "walk", "drive", "transit",
    "mrt", "bus", "car", "wishes", "preferences", "preference", "rating",
    "stars", "star", "spicy", "quiet", "anything", "everything", "all",
    "none", "more", "food", "restaurants", "restaurant", "cuisine", "cuisines",
}

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
        if text.islower() and any(ch.isalpha() for ch in text):
            text = re.sub(r"\bmrt\b", "MRT", text.title(), flags=re.IGNORECASE)
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
            if clean and clean not in ("none", "any", "any cuisine", "nothing") and clean not in disliked and clean not in liked:
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
            raw_disliked = [
                str(c).strip().lower()
                for c in (updates.get("disliked_cuisines") or [])
                if str(c or "").strip() and str(c or "").strip().lower() not in ("none", "any", "nothing")
            ]
            result["disliked_cuisines"] = cls._merge_list(
                result["disliked_cuisines"],
                raw_disliked,
                action,
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

    @staticmethod
    def _has_negation_for(lower, keyword_pattern):
        """Return True when the user explicitly negates, removes, or turns off keyword_pattern."""
        neg_prefix = (
            r"(?:"
            r"(?:i\s+)?(?:do\s*not|don'?t)\s+(?:want|need|require|care\s+for)"
            r"|no\s+need(?:\s+for)?"
            r"|not\s+looking\s+for"
            r"|never\s*mind"
            r"|remove|drop|delete|take\s+out|clear|undo|cancel|unselect|uncheck|skip|without|exclude|off"
            r"|non[- ]?|not|no"
            r")"
        )
        filler = r"(?:\s+(?:any|the|to|be|for|of|it|strictly|only|all|more|from|options?|food|restaurants?|cuisine|dietary|limits?|requirements?)){0,4}"
        before_rx = rf"\b{neg_prefix}{filler}\s+(?:{keyword_pattern})\b"
        after_rx = rf"\b(?:{keyword_pattern})\b\s+(?:not\s+needed|not\s+required|removed?|off)\b"
        return bool(re.search(before_rx, lower) or re.search(after_rx, lower))

    @staticmethod
    def _extract_custom_cuisine_list(text):
        """Split comma/'and'-separated cuisine phrases while stripping non-cuisine filler words."""
        cleaned = re.sub(r"\b(?:only|switch\s+to|change\s+to|prefer|avoid|dislike|no)\b", ",", text, flags=re.IGNORECASE)
        items = []
        for chunk in re.split(r"[,/&]|\band\b|\bor\b", cleaned, flags=re.IGNORECASE):
            token = re.sub(
                r"(?<!fast\s)(?<!street\s)(?<!comfort\s)(?<!soul\s)(?<!pub\s)(?<!bar\s)(?<!health\s)(?<!finger\s)(?<!hawker\s)\b(?:cuisine|cuisines|food|restaurants?)\b",
                "",
                chunk,
                flags=re.IGNORECASE,
            )
            token = re.sub(r"\s+", " ", token.strip(" .,!?;:-")).lower()
            if token and token not in _STOP_WORDS_NOT_CUISINES and token not in items and len(token) <= 32:
                items.append(token)
        return items

    _LOCATION_NOISE_WORDS = frozenset({
        "etc", "more", "others", "other", "location", "locations", "place", "places",
        "area", "areas", "spot", "spots", "another", "second", "third", "2nd", "3rd",
        "another location", "second location", "none", "any", "nothing", "so on",
    })

    @classmethod
    def _extract_location_list(cls, raw_text, reject_non_location=False):
        """Extract one or more Singapore place/postal strings from free-form phrasing."""
        text = str(raw_text or "").strip()
        if not text:
            return []
        text = re.sub(
            r"^(?:(?:a|an|another|extra|new|more|my|the|next|additional|1st|2nd|3rd|4th|first|second|third|fourth)\s+)*"
            r"(?:starting\s+)?(?:locations?|places?|areas?|spots?|points?|addresses?)"
            r"(?:\s*[:,-]\s*|\s+(?:is|to|as|at|near|in)\s+|\s+|$)",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,:;-")
        if not text:
            return []
        non_loc = (
            set(CUISINES) | set(_COMMON_CUSTOM_CUISINES) | set(DIETARY_CHOICES) | _STOP_WORDS_NOT_CUISINES
            if reject_non_location else set(DIETARY_CHOICES)
        )
        items = []
        for chunk in re.split(r"[,/&;]|\band\b", text, flags=re.IGNORECASE):
            token = re.sub(r"^(?:and|or|also|to|at|near|around|in)\s+", "", chunk.strip(" .,!?;:-"), flags=re.IGNORECASE)
            token = re.sub(r"\s+", " ", token.strip(" .,!?;:-"))
            token_cf = token.casefold()
            if not token or token_cf in cls._LOCATION_NOISE_WORDS or token_cf in non_loc:
                continue
            if len(token) < 2 or len(token) > 60:
                continue
            if token_cf not in {x.casefold() for x in items}:
                items.append(token)
        return items

    @classmethod
    def _parse_contextual_answer(cls, message, awaiting_field, current=None):
        """Parse concise direct answers when the chatbot just asked a targeted question."""
        text = str(message or "").strip()
        lower = text.casefold()
        updates = {}
        if not awaiting_field or not text:
            return updates

        if awaiting_field == "budget_per_person":
            if lower in ("cheap", "budget", "hawker", "affordable"):
                updates["budget_per_person"] = 12.0
            elif lower in ("moderate", "mid", "mid-range", "casual"):
                updates["budget_per_person"] = 25.0
            else:
                range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|and)\s*\$?\s*(\d+(?:\.\d+)?)", lower)
                num_match = re.search(r"^(?:around|about|roughly|max|under|below|sgd|\$|\s)*(\d+(?:\.\d+)?)\s*(?:dollars?|sgd|bucks)?\s*$", lower)
                if range_match:
                    updates["budget_per_person"] = float(range_match.group(2))
                elif num_match:
                    updates["budget_per_person"] = float(num_match.group(1))
        elif awaiting_field == "travel":
            if re.search(r"\b(?:drive|driving|car|grab|taxi)\b", lower):
                updates["mode"] = "drive"
            elif re.search(r"\b(?:transit|mrt|bus|train|public transport)\b", lower):
                updates["mode"] = "transit"
            elif re.search(r"\b(?:walk|walking|foot)\b", lower):
                updates["mode"] = "walk"
            km_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometres?|kilometers?)\b", lower)
            mins_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|mins?|minutes?)?\b", lower)
            if "half an hour" in lower or "half hour" in lower:
                updates["max_travel_minutes"] = 30.0
            elif km_match:
                updates["max_distance_km"] = float(km_match.group(1))
            elif mins_match:
                updates["max_travel_minutes"] = float(mins_match.group(1))
        elif awaiting_field in ("location", "add_location"):
            target_action = "add" if awaiting_field == "add_location" else "replace"
            between = re.search(
                r"\b(?:between\s+)?([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)$",
                text,
                re.IGNORECASE,
            )
            if between and target_action == "replace" and not re.search(r"\b(?:halal|vegetarian|budget|walk|drive|transit)\b", lower):
                updates["locations"] = [between.group(1).strip(), between.group(2).strip()]
                updates["locations_action"] = "replace"
            elif not re.search(r"\b(?:help|cancel|reset|profile|none|skip)\b", lower):
                locs = cls._extract_location_list(text)
                if locs:
                    updates["locations"] = locs
                    updates["locations_action"] = target_action
        elif awaiting_field == "dietary_requirements":
            if lower in ("none", "no", "no limits", "no dietary", "no dietary limits", "clear", "none / clear", "anything", "normal"):
                updates["dietary_action"] = "clear"
            elif "both" in lower or ("halal" in lower and ("vegetarian" in lower or "veggie" in lower)):
                if not cls._has_negation_for(lower, r"halal|vegetarian|veggie"):
                    updates["dietary_requirements"] = ["halal", "vegetarian"]
                    updates["dietary_action"] = "replace"
            else:
                rem, add = [], []
                if cls._has_negation_for(lower, r"halal|muis"):
                    rem.append("halal")
                elif "halal" in lower or "muis" in lower:
                    add.append("halal")
                if cls._has_negation_for(lower, r"vegetarian|veggie|veg|plant[- ]?based"):
                    rem.append("vegetarian")
                elif re.search(r"\b(?:vegetarian|veggie|veg|plant[- ]?based)\b", lower):
                    add.append("vegetarian")
                if add:
                    updates["dietary_requirements"] = add
                    updates["dietary_action"] = "replace" if re.search(r"\bonly\b", lower) else "add"
                elif rem:
                    updates["dietary_requirements"] = rem
                    updates["dietary_action"] = "remove"
        elif awaiting_field == "liked_cuisines":
            if lower in ("any", "any cuisine", "none", "no preference", "clear", "clear cuisines", "all"):
                updates["liked_action"] = "clear"
            elif re.match(r"^(?:remove|drop|take\s+out|clear)\s+", lower):
                items = cls._extract_custom_cuisine_list(re.sub(r"^(?:remove|drop|take\s+out|clear)\s+", "", text, flags=re.IGNORECASE))
                if items:
                    updates["liked_cuisines"] = items
                    updates["liked_action"] = "remove"
            else:
                items = cls._extract_custom_cuisine_list(text)
                if items:
                    updates["liked_cuisines"] = items
                    updates["liked_action"] = "add" if re.match(r"^(?:add|also|plus)\b", lower) else "replace"
        elif awaiting_field == "disliked_cuisines":
            if lower in ("none", "nothing", "clear", "clear avoids", "clear all avoids", "no dislikes", "allow all"):
                updates["disliked_action"] = "clear"
            elif re.match(r"^(?:allow|unblock|remove|drop|clear|don'?t\s+avoid|dont\s+avoid)\s+", lower):
                cleaned_txt = re.sub(r"^(?:allow|unblock|remove|drop|clear|don'?t\s+avoid|dont\s+avoid)\s+", "", text, flags=re.IGNORECASE)
                items = cls._extract_custom_cuisine_list(cleaned_txt)
                if items:
                    updates["disliked_cuisines"] = items
                    updates["disliked_action"] = "remove"
            else:
                items = cls._extract_custom_cuisine_list(text)
                if items:
                    updates["disliked_cuisines"] = items
                    updates["disliked_action"] = "add"
        elif awaiting_field == "other_preferences":
            if lower in ("none", "no", "clear", "clear wishes", "no wishes", "any"):
                updates["other_action"] = "clear"
            elif len(text) <= 120:
                items = [p.strip() for p in text.split(",") if p.strip()]
                if items:
                    updates["other_preferences"] = items
                    updates["other_action"] = "add"
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

        updates = cls._parse_contextual_answer(text, awaiting_field, current=current)
        between = re.search(
            r"\bbetween\s+([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)(?=$|\s+(?:for|with|under|below|within|by|walk|drive|transit|mrt)\b|[.,!?])",
            text,
            re.IGNORECASE,
        )
        add_explicit_loc = re.search(
            r"\b(?:"
            r"(?:add|include|plus)\s+(?:(?:a|an|another|extra|new|more|additional|1st|2nd|3rd|4th|first|second|third|fourth)\s+)*(?:starting\s+)?(?:locations?|places?|areas?|spots?)(?:\s*[:,-]\s*|\s+(?:is|as|at|near|in)\s+|\s+)"
            r"|(?:also\s+(?:at|near|around|from|in)|meet(?:ing)?\s+(?:up\s+)?(?:with\s+(?:a\s+)?friend\s+)?(?:at|from|near)|meet\s+at)\s+"
            r")"
            r"([A-Za-z0-9][A-Za-z0-9\s,&/.'-]{1,120}?)"
            r"(?=$|\s+(?:for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian|cuisine|cuisines)\b|[!?])",
            text,
            re.IGNORECASE,
        )
        add_generic_loc = re.search(
            r"\badd\s+([A-Za-z0-9][A-Za-z0-9\s,&/'-]{1,80}?)"
            r"(?=$|\s+(?:for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian|cuisine|cuisines)\b|[.!?])",
            text,
            re.IGNORECASE,
        )
        rem_explicit_loc = re.search(
            r"\b(?:remove|drop|delete|take\s+out|exclude)\s+(?:(?:the|my)\s+)?(?:starting\s+)?(?:locations?|places?|areas?|spots?)(?:\s*[:,-]\s*|\s+)"
            r"([A-Za-z0-9][A-Za-z0-9\s,&/'-]{1,100}?)"
            r"(?=$|\s+(?:from|for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian)\b|[.!?])",
            text,
            re.IGNORECASE,
        )
        rem_nth_loc = bool(re.search(
            r"\b(?:remove|drop|delete|take\s+out|clear)\s+(?:the\s+)?(?:2nd|second|last|extra|other)\s+location\b",
            lower,
        ))

        if between:
            updates["locations"] = [between.group(1).strip(), between.group(2).strip()]
            updates["locations_action"] = "replace"
        elif rem_nth_loc and len(current.get("locations") or []) > 1:
            updates["locations"] = [current["locations"][-1]]
            updates["locations_action"] = "remove"
        elif rem_explicit_loc:
            rem_locs = cls._extract_location_list(rem_explicit_loc.group(1))
            if rem_locs:
                updates["locations"] = rem_locs
                updates["locations_action"] = "remove"
        elif add_explicit_loc:
            added_locs = cls._extract_location_list(add_explicit_loc.group(1))
            if added_locs:
                updates["locations"] = added_locs
                updates["locations_action"] = "add"
        elif add_generic_loc and "locations" not in updates:
            added_locs = cls._extract_location_list(add_generic_loc.group(1), reject_non_location=True)
            if added_locs:
                updates["locations"] = added_locs
                updates["locations_action"] = "add"
        elif "locations" not in updates:
            current_locs = list(current.get("locations") or [])
            matched_rem_locs = [
                loc for loc in current_locs
                if re.search(rf"\b(?:remove|drop|delete|take\s+out)\s+{re.escape(loc)}\b", lower)
            ]
            if matched_rem_locs:
                updates["locations"] = matched_rem_locs
                updates["locations_action"] = "remove"
            else:
                postal = re.search(r"\b(\d{6})\b", text)
                loc_match = re.search(
                    r"\b(?:near|around|at(?!\s+(?:least|most|all)\b)|in(?!\s+(?:general|mind)\b)|by(?!\s+(?:walk|drive|transit|mrt|bus|train|car|foot|grab|taxi)\b))\s+([A-Za-z0-9][A-Za-z0-9\s,'-]{1,45}?)(?=$|\s+(?:for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian)\b|[.,!?])",
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

        if re.search(r"\b(?:drive|driving|car|grab|taxi)\b", lower):
            updates["mode"] = "drive"
            if "traffic" in lower and not cls._has_negation_for(lower, r"traffic"):
                updates["traffic_aware"] = True
            elif "traffic" in lower and cls._has_negation_for(lower, r"traffic"):
                updates["traffic_aware"] = False
        elif re.search(r"\b(?:transit|mrt|bus|train|public transport)\b", lower):
            updates["mode"] = "transit"
        elif re.search(r"\b(?:walk|walking|on foot)\b", lower):
            updates["mode"] = "walk"

        mins_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:m|mins?|minutes?)\b", lower)
        km_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:km|kilometres?|kilometers?)\b", lower)
        if "half an hour" in lower or "half hour" in lower:
            updates["max_travel_minutes"] = 30.0
        elif mins_match:
            updates["max_travel_minutes"] = float(mins_match.group(1))
        elif km_match:
            updates["max_distance_km"] = float(km_match.group(1))

        budget_match = re.search(
            r"(?:\$\s*(\d+(?:\.\d+)?))|\b(?:under|below|budget(?:\s+of|\s+is)?|max(?:imum)?|up\s+to|around|about)\s*(?:sgd|\$)?\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*(?:sgd|bucks|dollars?)\b",
            lower,
        )
        if budget_match:
            raw_b = budget_match.group(1) or budget_match.group(2) or budget_match.group(3)
            updates["budget_per_person"] = float(raw_b)

        clear_diet = bool(
            re.search(
                r"\b(?:no\s+dietary|no\s+restrictions|clear\s+dietary|remove\s+dietary|reset\s+dietary|any\s+dietary|eat\s+anything|normal\s+food)\b",
                lower,
            )
            or cls._has_negation_for(lower, r"dietary(?:\s+(?:limits?|requirements?|restrictions?|needs?))?")
        )
        diet_add, diet_rem = [], []
        if cls._has_negation_for(lower, r"halal|muis"):
            diet_rem.append("halal")
        elif re.search(r"\b(?:halal|muis)\b", lower):
            diet_add.append("halal")
        if cls._has_negation_for(lower, r"vegetarian|veggie|plant[- ]?based"):
            diet_rem.append("vegetarian")
        elif re.search(r"\b(?:vegetarian|veggie|plant[- ]?based)\b", lower):
            diet_add.append("vegetarian")

        if clear_diet:
            updates["dietary_action"] = "clear"
        elif diet_add and diet_rem:
            # e.g. "vegetarian instead of halal" / "not halal, vegetarian"
            updates["dietary_requirements"] = diet_add
            updates["dietary_action"] = "replace"
        elif diet_add:
            updates["dietary_requirements"] = diet_add
            updates["dietary_action"] = "replace" if re.search(r"\b(?:only|instead|switch)\b", lower) else "add"
        elif diet_rem:
            updates["dietary_requirements"] = diet_rem
            updates["dietary_action"] = "remove"

        current_liked = {c.casefold() for c in (current.get("liked_cuisines") or [])}
        current_disliked = {c.casefold() for c in (current.get("disliked_cuisines") or [])}
        liked_add, liked_rem, disliked_add, disliked_rem = [], [], [], []
        explicit_dislike_cue = bool(re.search(r"\b(?:avoid|dislike|exclude|hate|allergic|don'?t\s+like|dont\s+like|no\s+(?:spicy\s+)?)\b", lower))

        all_known_cuisines = list(dict.fromkeys(tuple(CUISINES) + _COMMON_CUSTOM_CUISINES + tuple(current_liked) + tuple(current_disliked)))
        for cuisine in all_known_cuisines:
            if not re.search(rf"\b{re.escape(cuisine)}\b", lower):
                continue
            unblock_cuisine = bool(
                re.search(rf"\b(?:allow|unblock|stop\s+avoiding|don'?t\s+avoid|dont\s+avoid|not\s+avoiding)\s+{re.escape(cuisine)}\b", lower)
                or re.search(rf"\bremove\s+{re.escape(cuisine)}\s+from\s+(?:avoid|disliked?)\b", lower)
            )
            soft_remove = bool(re.search(rf"\b(?:remove|drop|take\s+out|delete|unselect|never\s*mind|cancel)\s+{re.escape(cuisine)}\b", lower))
            strict_dislike = bool(
                awaiting_field == "disliked_cuisines"
                or re.search(rf"\b(?:avoid|dislike|exclude|hate|without|no|not)\s+{re.escape(cuisine)}\b", lower)
                or cls._has_negation_for(lower, re.escape(cuisine))
            )
            if unblock_cuisine or (soft_remove and cuisine.casefold() in current_disliked):
                disliked_rem.append(cuisine)
            elif (soft_remove or (strict_dislike and not explicit_dislike_cue)) and cuisine.casefold() in current_liked:
                liked_rem.append(cuisine)
            elif strict_dislike:
                disliked_add.append(cuisine)
            else:
                liked_add.append(cuisine)

        # Also catch explicit free-form avoid/dislike phrases like "avoid seafood, dim sum"
        avoid_phrase = re.search(
            r"\b(?:avoid|dislike|exclude|hate|don'?t\s+like|dont\s+like)\s+([a-zA-Z][a-zA-Z\s,&/-]{2,50}?)(?=$|\s+(?:near|at|in|under|below|within|walk|drive|transit|budget)\b|[.!?])",
            lower,
        )
        if avoid_phrase and not re.search(r"\b(?:halal|vegetarian|traffic|all|everything)\b", avoid_phrase.group(1)):
            for c in cls._extract_custom_cuisine_list(avoid_phrase.group(1)):
                if c not in disliked_add and c not in disliked_rem:
                    disliked_add.append(c)

        if re.search(r"\b(?:any\s+cuisine|clear\s+(?:liked\s+)?cuisines?|remove\s+all\s+cuisines?|no\s+cuisine\s+pref)\b", lower):
            updates["liked_action"] = "clear"
        else:
            if liked_add:
                updates["liked_cuisines"] = liked_add
                updates["liked_action"] = "replace" if re.search(r"\b(?:switch|change|instead|only)\b", lower) else "add"
            elif liked_rem:
                updates["liked_cuisines"] = liked_rem
                updates["liked_action"] = "remove"

        if re.search(r"\b(?:clear\s+(?:disliked?|avoids?)|no\s+dislikes?|allow\s+all\s+cuisines?|don'?t\s+avoid\s+any)\b", lower):
            updates["disliked_action"] = "clear"
        elif disliked_add:
            updates["disliked_cuisines"] = disliked_add
            updates["disliked_action"] = "add"
        elif disliked_rem:
            updates["disliked_cuisines"] = disliked_rem
            updates["disliked_action"] = "remove"

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
            if kw in lower and not cls._has_negation_for(lower, re.escape(kw)):
                other.append(kw)
        if "only " in lower and liked_add and liked_add[0] in CUISINES:
            other.append(f"only {liked_add[0]} cuisine")
        if re.search(r"\b(?:clear\s+(?:special\s+)?wish(?:es)?|no\s+(?:special\s+)?wish(?:es)?|remove\s+rating|no\s+rating\s+limit|any\s+rating)\b", lower):
            updates["other_action"] = "clear"
        elif other:
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

        supported_disliked = []
        for cuisine in (filters.get("disliked_cuisines") or []):
            clean = str(cuisine or "").strip().lower()
            if clean in CUISINES:
                if clean not in supported_disliked:
                    supported_disliked.append(clean)
            elif clean:
                custom_avoid = f"avoid {clean} cuisine"
                if custom_avoid.casefold() not in {o.casefold() for o in extra_other}:
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
            det_parsed = self._deterministic_parse(text, current, user, awaiting_field=target_field)
            reconciled = self._reconcile_ai_updates(det_parsed, parsed, current) if parsed is not None else det_parsed
            merged_updates = dict(reconciled.get("updates") or {})
            if is_none_answer and target_field == "dietary_requirements":
                merged_updates["dietary_requirements"] = []
                merged_updates["dietary_action"] = "clear"

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
                custom_liked = [f"{c} cuisine" for c in updated_filters["liked_cuisines"] if c not in CUISINES]
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
                supported = [c for c in updated_filters["disliked_cuisines"] if c in CUISINES]
                custom_disliked = [f"avoid {c} cuisine" for c in updated_filters["disliked_cuisines"] if c not in CUISINES]
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
        "try again", "lets go", "let's go", "yes lets go", "yes let's go",
        "ok search", "okay search", "ok search now", "yes looks good", "ok looks good",
    }

    _CONFIRM_REGEX = re.compile(
        r"^(?:yes|yep|yeah|yup|ok|okay|sure|great|perfect|awesome|alright)"
        r"(?:[,\s]+(?:looks good|sounds good|all good|all correct|search|search now|go ahead|proceed|lets go|let's go|please|start|find it))?$"
    )

    @classmethod
    def _is_search_confirmation(cls, message):
        cleaned = re.sub(r"[.!?\s]+$", "", str(message or "").casefold().strip())
        if cleaned in cls._CONFIRM_PHRASES:
            return True
        return bool(cls._CONFIRM_REGEX.match(cleaned))

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
        lines = [
            prefix,
            f"• {loc_label}: {locs}",
            f"• Travel: {travel}",
            f"• Budget: {budget}",
            f"• Dietary: {diet}",
            f"• Cuisines: {liked}",
        ]
        if filters.get("disliked_cuisines"):
            lines.append("• Avoid: " + ", ".join(c.title() for c in filters["disliked_cuisines"]))
        if filters.get("other_preferences"):
            lines.append("• Wishes: " + ", ".join(filters["other_preferences"]))
        lines.append("")
        lines.append("Should I proceed with searching, or would you like to change anything?")
        return "\n".join(lines)

    @staticmethod
    def _confirmation_quick_replies(filters, signed_in):
        replies = ["Yes, search now", "Change location"]
        if filters.get("dietary_requirements"):
            replies.append("No dietary limits")
        else:
            replies.append("Change budget")
        replies.append("Save to profile" if signed_in else "Edit cuisines")
        return replies

    def _clarify_response(self, current, awaiting_field, reply, quick_replies):
        return {
            "success": True,
            "action": "clarify",
            "awaiting_field": awaiting_field,
            "reply": reply,
            "filters": current,
            "changes": [],
            "quick_replies": quick_replies,
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": False,
        }

    def _handle_edit_request(self, lower, current):
        cleaned = re.sub(r"[.!?\s]+$", "", lower.strip())
        if cleaned in ("change location", "edit location", "change starting location", "location", "change place"):
            prompt, qrs = self._prompt_for_missing_search_field("location")
            return self._clarify_response(current, "location", prompt, qrs)

        if cleaned in ("add location", "add another location", "add second location", "add more locations", "add a location"):
            return self._clarify_response(
                current,
                "add_location",
                "Sure! Which Singapore location(s) would you like to add to meet in the middle? (e.g. 'Marina Bay' or 'Marina Bay, Sentosa')",
                ["Marina Bay", "Orchard Road", "Bugis Junction", "Sentosa"],
            )

        if cleaned in ("change budget", "edit budget", "budget"):
            prompt, qrs = self._prompt_for_missing_search_field("budget_per_person")
            return self._clarify_response(current, "budget_per_person", prompt, qrs)

        if cleaned in ("change travel", "edit travel", "change time", "edit time", "change distance", "edit distance", "travel", "change transport"):
            prompt, qrs = self._prompt_for_missing_search_field("travel")
            return self._clarify_response(current, "travel", prompt, qrs)

        if cleaned in (
            "change dietary", "edit dietary", "dietary", "dietary requirements",
            "change diet", "edit diet", "diet", "change halal", "edit halal",
        ):
            active_diet = [d for d in (current.get("dietary_requirements") or []) if d in ("halal", "vegetarian")]
            if active_diet:
                active_label = ", ".join(d.title() for d in active_diet)
                qrs = []
                if "halal" in active_diet:
                    qrs.append("Remove halal")
                if "vegetarian" in active_diet:
                    qrs.append("Remove vegetarian")
                qrs.append("No dietary limits")
                if "halal" not in active_diet:
                    qrs.append("Halal")
                if "vegetarian" not in active_diet and len(qrs) < 4:
                    qrs.append("Vegetarian")
                return self._clarify_response(
                    current,
                    "dietary_requirements",
                    f"Dietary is currently set to {active_label}. Would you like to remove it, clear all dietary limits, or switch?",
                    qrs[:4],
                )
            return self._clarify_response(
                current,
                "dietary_requirements",
                "Which dietary requirement would you like to apply? (e.g. 'Halal', 'Vegetarian', or 'No dietary limits')",
                ["Halal", "Vegetarian", "Both", "No dietary limits"],
            )

        if cleaned in (
            "change cuisine", "edit cuisine", "edit cuisines", "change cuisines",
            "cuisines", "change liked cuisines", "edit liked cuisines",
        ):
            liked = current.get("liked_cuisines") or []
            qrs = ["Japanese, Korean", "Mexican", "Any cuisine", "Yes, search now"]
            if liked:
                qrs = [f"Remove {liked[0].title()}", "Any cuisine", "Japanese, Korean", "Yes, search now"]
            return self._clarify_response(
                current,
                "liked_cuisines",
                "Which cuisines would you like to include, add, or remove? (e.g. 'Japanese, Mexican', 'remove japanese', or 'any cuisine')",
                qrs,
            )

        if cleaned in (
            "change dislikes", "edit dislikes", "edit disliked cuisines",
            "change disliked cuisines", "disliked cuisines", "dislikes", "avoid cuisines",
        ):
            disliked = current.get("disliked_cuisines") or []
            qrs = ["Clear dislikes", "Avoid fast food", "Avoid seafood", "Yes, search now"] if disliked else ["Avoid fast food", "Avoid seafood", "Avoid chinese", "Yes, search now"]
            return self._clarify_response(
                current,
                "disliked_cuisines",
                "Which cuisines would you like to avoid or clear from your dislikes? (e.g. 'avoid seafood', 'clear dislikes')",
                qrs,
            )

        if cleaned in (
            "change wishes", "edit wishes", "wishes", "other preferences",
            "change preferences", "edit preferences", "special wishes",
        ):
            return self._clarify_response(
                current,
                "other_preferences",
                "What special wishes or atmosphere should I look for? (e.g. 'quiet cozy spot', 'near mrt', or 'clear wishes')",
                ["Quiet & cozy", "Air-conditioned", "Near MRT", "Clear wishes"],
            )

        if cleaned in ("no", "nope", "not yet", "wait", "edit", "change something", "cancel"):
            return self._clarify_response(
                current,
                "confirm",
                "No problem! Tell me what you'd like to adjust (location, budget, travel limit, dietary needs, cuisines, dislikes, or wishes).",
                ["Change location", "Change budget", "Change dietary", "Edit cuisines"],
            )
        return None

    @staticmethod
    def _reconcile_ai_updates(det_parsed, ai_parsed, current):
        """Guard explicit deterministic negations/removals from accidental AI reversal."""
        det_updates = dict((det_parsed or {}).get("updates") or {})
        result = deepcopy(ai_parsed) if isinstance(ai_parsed, dict) else {"intent": "search", "updates": {}, "reply": "", "quick_replies": []}
        ai_updates = dict(result.get("updates") or {})

        # 1. Explicit dietary negation / clear must ALWAYS win over AI confusion (e.g. "i dont want halal").
        if det_updates.get("dietary_action") in ("remove", "clear"):
            ai_updates["dietary_action"] = det_updates["dietary_action"]
            ai_updates["dietary_requirements"] = list(det_updates.get("dietary_requirements") or [])
            if ai_updates.get("disliked_cuisines"):
                ai_updates["disliked_cuisines"] = [
                    c for c in ai_updates["disliked_cuisines"]
                    if str(c).strip().casefold() not in ("halal", "vegetarian", "dietary")
                ]
            result["intent"] = "search"

        # 2. Explicit liked removal/clear ("remove japanese" when japanese is liked) should not blacklist it.
        if det_updates.get("liked_action") in ("remove", "clear"):
            ai_updates["liked_action"] = det_updates["liked_action"]
            det_liked = list(det_updates.get("liked_cuisines") or [])
            ai_updates["liked_cuisines"] = det_liked
            if ai_updates.get("disliked_cuisines"):
                det_liked_cf = {str(c).strip().casefold() for c in det_liked}
                ai_updates["disliked_cuisines"] = [
                    c for c in ai_updates["disliked_cuisines"]
                    if str(c).strip().casefold() not in det_liked_cf
                ]
            result["intent"] = "search"

        # 3. Explicit disliked removal/clear ("stop avoiding chinese", "clear dislikes").
        if det_updates.get("disliked_action") in ("remove", "clear"):
            ai_updates["disliked_action"] = det_updates["disliked_action"]
            ai_updates["disliked_cuisines"] = list(det_updates.get("disliked_cuisines") or [])
            result["intent"] = "search"
        elif det_updates.get("disliked_cuisines"):
            existing_disliked = list(ai_updates.get("disliked_cuisines") or [])
            existing_cf = {str(c).strip().casefold() for c in existing_disliked}
            for item in det_updates["disliked_cuisines"]:
                if str(item).strip().casefold() not in existing_cf:
                    existing_disliked.append(item)
            ai_updates["disliked_cuisines"] = existing_disliked
            if not ai_updates.get("disliked_action"):
                ai_updates["disliked_action"] = det_updates.get("disliked_action") or "add"
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
            ai_updates["other_preferences"] = list(det_updates.get("other_preferences") or [])
            result["intent"] = "search"

        # 6. If AI produced no updates at all despite deterministic rule extraction, trust deterministic parse.
        if not ai_updates and det_updates:
            ai_updates.update(det_updates)
            result["intent"] = det_parsed.get("intent", "search")

        result["updates"] = ai_updates
        return result

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

        det_awaiting = None if awaiting_field == "confirm" else awaiting_field
        det_parsed = self._deterministic_parse(message, current, user, awaiting_field=det_awaiting)

        if parsed is None:
            parsed = det_parsed
        else:
            parsed = self._reconcile_ai_updates(det_parsed, parsed, current)

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
