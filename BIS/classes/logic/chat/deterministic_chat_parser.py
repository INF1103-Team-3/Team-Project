"""Deterministic fallback interpretation of chat input."""

from copy import deepcopy
import re

from BIS.sources.profile_schema import (
    CUISINES, DIETARY_CHOICES, NUMBER_LIMITS, SEARCH_MODE_LIMITS,
    extract_rating_wishes, normalize_wish_text, strip_rating_clauses,
    validate_english_preferences,
)

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



class DeterministicChatParser:
    """Extract requested changes; application of those changes stays in Logic."""

    _LOCATION_NOISE_WORDS = frozenset({
        "etc", "more", "others", "other", "location", "locations", "place", "places",
        "area", "areas", "spot", "spots", "another", "second", "third", "2nd", "3rd",
        "another location", "second location", "none", "any", "nothing", "so on",
    })


    def __init__(self, profile_formatter):
        self._profile_formatter = profile_formatter

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
        text = normalize_wish_text(message)
        lower = text.casefold()
        updates = {}
        if not awaiting_field or not text:
            return updates

        if awaiting_field == "budget_per_person":
            if re.search(r"(?:\$\s*100\s*\+|\b100\s*\+|(?:over|above|more\s+than)\s*(?:sgd|\$)?\s*100\b|\bfine\s+dining\b)", lower):
                updates["budget_per_person"] = 1000.0
            elif lower in ("casual dining",):
                updates["budget_per_person"] = 50.0
            elif lower in ("cheap", "budget", "hawker", "affordable"):
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
            if lower in ("none", "no", "nil", "n/a", "skip", "skip wishes", "clear", "clear wishes", "no wishes", "any"):
                updates["other_action"] = "clear"
            else:
                items = [p.strip() for p in text.split(",") if p.strip()]
                if items:
                    updates["other_preferences"] = items
                    updates["other_action"] = "add"
        return updates


    def parse(self, message, current, user, awaiting_field=None):
        text = normalize_wish_text(message)
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
                "reply": self._profile_formatter(user),
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

        updates = self._parse_contextual_answer(text, awaiting_field, current=current)
        between = re.search(
            r"\bbetween\s+([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)(?=$|\s+\$|\s+(?:for|with|under|below|within|over|above|by|budget|walk|drive|transit|mrt)\b|[.,!?])",
            text,
            re.IGNORECASE,
        )
        add_explicit_loc = re.search(
            r"\b(?:"
            r"(?:add|include|plus)\s+(?:(?:a|an|another|extra|new|more|additional|1st|2nd|3rd|4th|first|second|third|fourth)\s+)*(?:starting\s+)?(?:locations?|places?|areas?|spots?)(?:\s*[:,-]\s*|\s+(?:is|as|at|near|in)\s+|\s+)"
            r"|(?:also\s+(?:at|near|around|from|in)|meet(?:ing)?\s+(?:up\s+)?(?:with\s+(?:a\s+)?friend\s+)?(?:at|from|near)|meet\s+at)\s+"
            r")"
            r"([A-Za-z0-9][A-Za-z0-9\s,&/.'-]{1,120}?)"
            r"(?=$|\s+\$|\s+(?:for|with|under|below|within|over|above|budget|walk|drive|transit|mrt|halal|vegetarian|cuisine|cuisines)\b|[!?])",
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
            rem_locs = self._extract_location_list(rem_explicit_loc.group(1))
            if rem_locs:
                updates["locations"] = rem_locs
                updates["locations_action"] = "remove"
        elif add_explicit_loc:
            added_locs = self._extract_location_list(add_explicit_loc.group(1))
            if added_locs:
                updates["locations"] = added_locs
                updates["locations_action"] = "add"
        elif add_generic_loc and "locations" not in updates:
            added_locs = self._extract_location_list(add_generic_loc.group(1), reject_non_location=True)
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
                    r"\b(?:near|around|at(?!\s+(?:least|most|all)\b)|in(?!\s+(?:general|mind)\b)|by(?!\s+(?:walk|drive|transit|mrt|bus|train|car|foot|grab|taxi)\b))\s+([A-Za-z0-9][A-Za-z0-9\s,'-]{1,45}?)(?=$|\s+\$|\s+(?:for|with|under|below|within|over|above|budget|walk|drive|transit|mrt|halal|vegetarian)\b|[.,!?])",
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
            if "traffic" in lower and not self._has_negation_for(lower, r"traffic"):
                updates["traffic_aware"] = True
            elif "traffic" in lower and self._has_negation_for(lower, r"traffic"):
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

        plus_budget = re.search(
            r"(?:\$\s*100\s*\+|\b100\s*\+|(?:over|above|more\s+than)\s*(?:sgd|\$)?\s*100\b|\bfine\s+dining\b)",
            lower,
        )
        budget_match = re.search(
            r"(?:\$\s*(\d+(?:\.\d+)?))|\b(?:under|below|budget(?:\s+of|\s+is)?|max(?:imum)?|up\s+to|around|about)\s*(?:sgd|\$)?\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*(?:sgd|bucks|dollars?)\b",
            lower,
        )
        if plus_budget:
            updates["budget_per_person"] = 1000.0
        elif budget_match:
            raw_b = budget_match.group(1) or budget_match.group(2) or budget_match.group(3)
            updates["budget_per_person"] = float(raw_b)
        elif re.search(r"\bcasual\s+dining\b", lower):
            updates["budget_per_person"] = 50.0

        clear_diet = bool(
            re.search(
                r"\b(?:no\s+dietary|no\s+restrictions|clear\s+dietary|remove\s+dietary|reset\s+dietary|any\s+dietary|eat\s+anything|normal\s+food)\b",
                lower,
            )
            or self._has_negation_for(lower, r"dietary(?:\s+(?:limits?|requirements?|restrictions?|needs?))?")
        )
        diet_add, diet_rem = [], []
        if self._has_negation_for(lower, r"halal|muis"):
            diet_rem.append("halal")
        elif re.search(r"\b(?:halal|muis)\b", lower):
            diet_add.append("halal")
        if self._has_negation_for(lower, r"vegetarian|veggie|plant[- ]?based"):
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
                or self._has_negation_for(lower, re.escape(cuisine))
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
            for c in self._extract_custom_cuisine_list(avoid_phrase.group(1)):
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
        # Only capture bare numbers with at-least/min when followed by stars|/5|rating or a decimal rating.
        explicit_star_match = re.search(
            r"(?:(?:\b(?:at least|minimum|min\.?|no less than|above|over)\b|>=?)\s*"
            r"(?:google\s*)?(?:(?:rating|rated)\s*(?:of\s*)?(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:\+\s*)?(?:stars?|/\s*5|rating\b|rated\b))"
            r"|\b(\d+(?:\.\d+)?)\s*(?:\+\s*)?(?:stars?|/\s*5|rated|rating)\b(?:\s*(?:or higher|or above|and up|or better|minimum|min\.?|\+)(?!\w))?)",
            lower,
        )
        if explicit_star_match:
            rating_val = next(g for g in explicit_star_match.groups() if g is not None)
            other.append(f"at least {rating_val} stars")
        explicit_wish = re.search(
            r"\b(?:(?:add|set)\s+(?:special\s+)?wish(?:es)?|(?:special\s+(?:request|wish)(?:es)?|wish(?:es)?|other\s+preferences?)\s*[:=-])\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        for kw in ("spicy", "quiet", "open 24 hours", "24 hours", "outdoor seating", "aircon"):
            if (
                awaiting_field != "other_preferences"
                and not explicit_wish
                and kw in lower
                and not self._has_negation_for(lower, re.escape(kw))
            ):
                other.append(kw)
        if "only " in lower and liked_add and liked_add[0] in CUISINES:
            other.append(f"only {liked_add[0]} cuisine")
        if explicit_wish and not re.search(
            r"^\s*(?:clear(?:\s+wishes)?|none|no\s+wishes|nothing|n/a)\s*$",
            explicit_wish.group(1),
            re.IGNORECASE,
        ):
            for part in explicit_wish.group(1).split(","):
                clean_part = normalize_wish_text(part)
                if clean_part and clean_part.casefold() not in {o.casefold() for o in other}:
                    other.append(clean_part)
        if re.search(r"\b(?:clear\s+(?:special\s+)?wish(?:es)?|no\s+(?:special\s+)?wish(?:es)?)\b", lower):
            updates["other_action"] = "clear"
        elif re.search(r"\b(?:remove\s+rating|no\s+rating\s+limit|any\s+rating|clear\s+rating)\b", lower):
            updates["other_action"] = "clear_rating"
        elif other and (awaiting_field != "other_preferences" or "other_preferences" not in updates):
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
