"""Conversational BIS assistant: parses chat turns into synced search/profile actions."""
from copy import deepcopy
import re

from BIS.sources.profile_schema import CUISINES, DIETARY_CHOICES, NUMBER_LIMITS


_COMMON_CUSTOM_CUISINES = (
    "ramen", "sushi", "dim sum", "hawker", "zi char", "hotpot", "bbq",
    "bakery", "cafe", "seafood", "steamboat", "prata", "biryani", "fast food",
)


class BISChatbotService:
    """Turn natural-language user messages into incremental filter updates and actions."""

    def __init__(self, ai, logic, config, model_reader=lambda: None, profile_saver=None):
        self._ai = ai
        self._logic = logic
        self._config = config
        self._model = model_reader
        self._save_profile = profile_saver

    @staticmethod
    def _default_filters(user=None):
        prefs = (user or {}).get("preferences") or {}
        saved_locs = [
            BISChatbotService._normalize_location(loc)
            for loc in (prefs.get("location") or [])
            if str(loc or "").strip()
        ]
        max_mins = prefs.get("max_travel_time_minutes")
        max_km = prefs.get("max_distance_km")
        if max_mins is None and max_km is None:
            max_mins = 30.0
        elif max_mins is not None:
            max_km = None
        return {
            "location": saved_locs[0] if saved_locs else "",
            "locations": saved_locs,
            "mode": "walk",
            "traffic_aware": False,
            "max_travel_minutes": max_mins,
            "max_distance_km": max_km,
            "budget_per_person": prefs.get("budget_per_person") or 30.0,
            "dietary_requirements": list(prefs.get("dietary_requirements") or []),
            "liked_cuisines": [str(c).strip().lower() for c in (prefs.get("liked_cuisines") or []) if str(c).strip()],
            "disliked_cuisines": [str(c).strip().lower() for c in (prefs.get("disliked_cuisines") or []) if str(c).strip()],
            "other_preferences": [str(p).strip() for p in (prefs.get("other_preferences") or []) if str(p).strip()],
        }

    @staticmethod
    def _normalize_location(raw):
        text = re.sub(r"\s+", " ", str(raw or "").strip()).strip(".,;!?")
        if not text:
            return ""
        if text.isdigit():
            return f"Singapore {text}"
        return text

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

        max_mins = raw.get("max_travel_minutes")
        max_km = raw.get("max_distance_km")
        if isinstance(max_mins, (int, float)) and not isinstance(max_mins, bool) and max_mins > 0:
            low, high = NUMBER_LIMITS["max_travel_time_minutes"]
            max_mins = round(max(low, min(high, float(max_mins))), 1)
            max_km = None
        elif isinstance(max_km, (int, float)) and not isinstance(max_km, bool) and max_km > 0:
            low, high = NUMBER_LIMITS["max_distance_km"]
            max_km = round(max(low, min(high, float(max_km))), 2)
            max_mins = None
        else:
            max_mins = defaults["max_travel_minutes"]
            max_km = defaults["max_distance_km"]

        budget = raw.get("budget_per_person")
        if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget <= 0:
            budget = defaults["budget_per_person"]
        else:
            b_low, b_high = NUMBER_LIMITS["budget_per_person"]
            budget = round(max(b_low, min(b_high, float(budget))), 2)

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
    def _deterministic_parse(cls, message, current, user):
        text = str(message or "").strip()
        lower = text.casefold()

        if lower in ("/help", "help", "commands", "what can you do", "how does this work"):
            return {
                "intent": "help",
                "reply": (
                    "Just tell me what you're craving! You can combine location, cuisine, "
                    "budget, dietary needs, travel mode, or ratings — or ask to meet a friend "
                    "between two spots, refine results ('cheaper', '4.5 stars'), or 'save to profile'."
                ),
                "updates": {},
                "quick_replies": [
                    "Halal Japanese near Bugis under $20",
                    "Meet between Tampines and Jurong East",
                    "At least 4.5 stars near Compass One",
                ],
            }

        if lower in ("/profile", "show profile", "show my profile", "my profile", "view profile"):
            return {
                "intent": "show_profile",
                "reply": cls._format_profile_summary(user),
                "updates": {},
                "quick_replies": ["Use my saved profile", "Halal food near me", "Help"],
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
                    else "Reset filters back to defaults."
                ),
                "updates": {},
                "quick_replies": ["Search now", "Bugis Junction under $20", "Halal food near Compass One"],
            }

        updates = {}
        between = re.search(
            r"\bbetween\s+([A-Za-z0-9\s,'-]{2,50}?)\s+(?:and|&)\s+([A-Za-z0-9\s,'-]{2,50}?)(?=$|\s+(?:for|with|under|below|within|by|walk|drive|transit|mrt)\b|[.,!?])",
            text,
            re.IGNORECASE,
        )
        if between:
            updates["locations"] = [between.group(1).strip(), between.group(2).strip()]
            updates["locations_action"] = "replace"
        else:
            postal = re.search(r"\b(\d{6})\b", text)
            loc_match = re.search(
                r"\b(?:near|around|at|in|by)\s+([A-Za-z0-9][A-Za-z0-9\s,'-]{1,45}?)(?=$|\s+(?:for|with|under|below|within|budget|walk|drive|transit|mrt|halal|vegetarian)\b|[.,!?])",
                text,
                re.IGNORECASE,
            )
            if loc_match:
                candidate_loc = loc_match.group(1).strip()
                if candidate_loc.casefold() not in ("halal", "vegetarian", "walk", "drive", "transit", "mrt", "singapore"):
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
            if re.search(rf"\b(?:no|avoid|dislike|exclude|not|without)\s+{re.escape(cuisine)}\b", lower):
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
            if re.search(r"\b(?:at least|minimum|min|>=)\b", lower):
                other.append(f"at least {rating_val} stars")
            else:
                other.append(f"{rating_val} stars")
        for kw in ("spicy", "quiet", "open 24 hours", "24 hours", "outdoor seating", "aircon"):
            if kw in lower:
                other.append(kw)
        if "only " in lower and liked:
            if liked[0] in CUISINES:
                other.append(f"only {liked[0]} cuisine")
        if other:
            updates["other_preferences"] = other
            updates["other_action"] = "add"

        merged_preview = cls._apply_updates(current, updates, user=user)
        has_search_signal = bool(
            updates
            or re.search(r"\b(?:search|find|recommend|suggest|eat|food|dinner|lunch|breakfast|supper|restaurant|cafe|hungry|retry)\b", lower)
            or lower in ("yes", "go", "go ahead", "search now", "ok", "okay", "try again")
        )
        if not has_search_signal:
            return {
                "intent": "clarify",
                "reply": (
                    "Tell me what kind of food, area, budget, or dietary option you want "
                    "(for example: 'Halal Japanese near Bugis under $20')."
                ),
                "updates": {},
                "quick_replies": [
                    "Halal Japanese near Bugis under $20",
                    "Meet between Tampines and Jurong East",
                    "Search with current filters",
                ],
            }

        if not merged_preview["locations"]:
            return {
                "intent": "clarify",
                "reply": "Where in Singapore would you like me to search? Enter an area, landmark, MRT, or 6-digit postal code.",
                "updates": updates,
                "quick_replies": ["Bugis Junction", "Compass One", "Rivervale Plaza", "Jewel Changi"],
            }

        return {
            "intent": "search",
            "reply": "Got it! Updating your search preferences and finding matching restaurants now.",
            "updates": updates,
            "quick_replies": cls._default_quick_replies(merged_preview, bool(user)),
        }

    @staticmethod
    def _format_profile_summary(user):
        if not user:
            return "You're currently browsing as a guest. Sign in to load and save default preferences."
        prefs = user.get("preferences") or {}
        locs = ", ".join(prefs.get("location") or []) or "Not set"
        budget = f"SGD ${prefs['budget_per_person']}" if prefs.get("budget_per_person") else "Not set"
        diet = ", ".join(prefs.get("dietary_requirements") or []) or "None"
        liked = ", ".join(prefs.get("liked_cuisines") or []) or "Any"
        return (
            f"Saved profile for {user.get('username', 'User')}: "
            f"Locations [{locs}], Budget [{budget}], Dietary [{diet}], Likes [{liked}]."
        )

    @staticmethod
    def _default_quick_replies(filters, signed_in):
        suggestions = []
        if float(filters.get("budget_per_person") or 30) > 15:
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
            limit = (
                f"{after['max_distance_km']:g}km"
                if after.get("max_distance_km")
                else f"{int(round(after.get('max_travel_minutes') or 30))}m"
            )
            changes.append(f"{icon} · {limit}")
        if before.get("budget_per_person") != after.get("budget_per_person"):
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

    def respond(self, user, payload):
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("Please enter a message for the BiteFinder chatbot.")

        current = self.normalize_filters(payload.get("current_filters"), user=user)
        history = [
            {"role": str(item.get("role", "")), "text": str(item.get("text", ""))[:300]}
            for item in (payload.get("history") or [])[-6:]
            if isinstance(item, dict) and item.get("text")
        ]

        parsed = None
        if not self._config.get("ai_bypass") and hasattr(self._ai, "chat_turn"):
            lower = message.casefold().strip()
            is_utility = lower in ("/help", "help", "/profile", "/reset", "reset", "/save")
            if not is_utility:
                try:
                    saved_profile = (user or {}).get("preferences") or {}
                    parsed = self._ai.chat_turn(message, current, history, saved_profile, deepcopy(self._config))
                except (RuntimeError, ValueError, TypeError):
                    parsed = None

        if parsed is None:
            parsed = self._deterministic_parse(message, current, user)

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
                    "reply": "Please sign in first so I can save your preferences to your BiteFinder profile.",
                    "filters": updated,
                    "changes": changes,
                    "quick_replies": ["Search with current filters", "Help"],
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            profile_payload = {
                "user_id": user["userID"],
                "location": updated["locations"] or (user.get("preferences") or {}).get("location") or ["Compass One"],
                "max_distance_km": updated["max_distance_km"],
                "max_travel_time_minutes": updated["max_travel_minutes"],
                "budget_per_person": updated["budget_per_person"],
                "dietary_requirements": updated["dietary_requirements"],
                "liked_cuisines": updated["liked_cuisines"],
                "disliked_cuisines": updated["disliked_cuisines"],
                "other_preferences": updated["other_preferences"],
            }
            self._save_profile(user, profile_payload)
            saved_to_profile = True
            reply = "Saved your current preferences to your BiteFinder profile."

        elif intent == "show_profile":
            reply = self._format_profile_summary(user)

        elif intent == "search" and not updated["locations"]:
            fallback_locs = self._default_filters(user)["locations"]
            if fallback_locs:
                updated["locations"] = fallback_locs
                updated["location"] = fallback_locs[0]
                changes = self._summarize_changes(current, updated)
            else:
                intent = "clarify"
                reply = (
                    "I've noted your preferences! Where in Singapore would you like me to search? "
                    "(e.g. 'Bugis Junction', '529510', or 'between Tampines and Jurong East')"
                )
                quick_replies = ["Bugis Junction", "Compass One", "Rivervale Plaza", "Jewel Changi"]

        return {
            "success": True,
            "action": intent,
            "reply": reply,
            "filters": updated,
            "changes": changes,
            "quick_replies": quick_replies or self._default_quick_replies(updated, bool(user)),
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": saved_to_profile,
        }
