"""Web chat wording, summaries and clarification presentation."""

import re


_ONBOARDING_QUESTIONS = {
    "location": (
        (
            "Welcome to BiteFinder! Let's set up your profile. First, which "
            "starting location(s) in Singapore do you usually search around? "
            "(e.g. Compass One, Bugis, or 828761)"
        ),
        ["Compass One", "Bugis Junction", "Rivervale Plaza", "Jewel Changi"],
    ),
    "budget_per_person": (
        (
            "Got it! What is your usual budget per person in SGD? (e.g. $15, "
            "$25, or $40)"
        ),
        ["$15", "$25", "$40", "$60"],
    ),
    "travel": (
        (
            "How far or how long are you usually willing to travel? (e.g. 20 "
            "mins or 1.5 km)"
        ),
        ["15 mins walk", "30 mins walk", "2 km", "20 mins MRT"],
    ),
    "dietary_requirements": (
        (
            "Do you have any dietary requirements to save? (Halal, "
            "Vegetarian, Both, or None)"
        ),
        ["Halal", "Vegetarian", "Both", "None"],
    ),
    "liked_cuisines": (
        (
            "Which cuisines do you like most? (e.g. Japanese, Chinese, Korean "
            "— or None)"
        ),
        ["Japanese, Korean", "Chinese, Malay", "Western, Italian", "None"],
    ),
    "disliked_cuisines": (
        "Are there any cuisines you prefer to avoid? (or None)",
        ["None", "Indian", "Malay", "Thai"],
    ),
    "other_preferences": (
        (
            "Any other regular preferences? (e.g. spicy food, at least 4.5 "
            "stars — or None)"
        ),
        ["At least 4.5 stars", "Spicy food", "Quiet", "None"],
    ),
}


class ChatPresenter:
    """Render conversation responses without applying filter policies."""

    def __init__(self, model_reader=lambda: None):
        self._model = model_reader

    @staticmethod
    def prompt_for_missing_search_field(field):
        if field == "location":
            return (
                (
                    "Where in Singapore would you like me to search? Enter an "
                    "area, landmark, MRT, or 6-digit postal code (or 'between "
                    "X and Y')."
                ),
                [
                    "Bugis Junction",
                    "Compass One",
                    "Rivervale Plaza",
                    "Jewel Changi",
                ],
            )
        if field == "budget_per_person":
            return (
                (
                    "What is your budget per person in SGD? (e.g. $15, $25, "
                    "or $40)"
                ),
                ["$15", "$25", "$40", "$60"],
            )
        return (
            (
                "How far or how long are you willing to travel? (e.g. 15 mins "
                "walk, 2 km, or 20 mins MRT)"
            ),
            ["15 mins walk", "30 mins walk", "2 km", "20 mins MRT"],
        )

    def onboarding_retry(self, target_field, current, prefix=None):
        prompt, quick_replies = _ONBOARDING_QUESTIONS[target_field]
        step_num = list(_ONBOARDING_QUESTIONS.keys()).index(target_field) + 1
        lead = prefix or (
            "I didn't catch a valid value for "
            f"{target_field.replace('_', ' ')}"
            "."
        )
        return {
            "success": True,
            "action": "onboarding",
            "awaiting_field": target_field,
            "onboarding_step": step_num,
            "onboarding_total": len(_ONBOARDING_QUESTIONS),
            "reply": f"{lead} {prompt}",
            "filters": current,
            "changes": [],
            "quick_replies": quick_replies,
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": False,
        }

    @staticmethod
    def format_budget_display(budget):
        if budget is None:
            return "Not set"
        num = float(budget)
        return "SGD $100+" if num > 100 else f"SGD ${num:g}"

    @classmethod
    def format_profile_summary(cls, user):
        if not user:
            return (
                "You're currently browsing as a guest. Sign in to load and "
                "save default preferences."
            )
        prefs = user.get("preferences") or {}
        locs = ", ".join(prefs.get("location") or []) or "Not set"
        travel_parts = []
        if prefs.get("max_travel_time_minutes") is not None:
            travel_parts.append(
                f"{float(prefs['max_travel_time_minutes']):g} mins"
            )
        if prefs.get("max_distance_km") is not None:
            travel_parts.append(f"{float(prefs['max_distance_km']):g} km")
        travel = " / ".join(travel_parts) if travel_parts else "Not set"
        budget = cls.format_budget_display(prefs.get("budget_per_person"))
        diet = ", ".join(prefs.get("dietary_requirements") or []) or "Not set"
        liked = ", ".join(prefs.get("liked_cuisines") or []) or "Any / Not set"
        disliked = ", ".join(prefs.get("disliked_cuisines") or []) or "None"
        wishes = ", ".join(prefs.get("other_preferences") or []) or "None"
        return (
            "Saved profile for "
            f"{user.get('username', 'User')}"
            ": Locations ["
            f"{locs}"
            "], Travel ["
            f"{travel}"
            "], Budget ["
            f"{budget}"
            "], Dietary ["
            f"{diet}"
            "], Likes ["
            f"{liked}"
            "], Avoid ["
            f"{disliked}"
            "], Wishes ["
            f"{wishes}"
            "]."
        )

    @staticmethod
    def default_quick_replies(filters, signed_in):
        suggestions = []
        budget = filters.get("budget_per_person")
        if budget is None or float(budget) > 15:
            suggestions.append("Under $15")
        if "halal" not in (filters.get("dietary_requirements") or []):
            suggestions.append("Halal only")
        if not any(
            "star" in p.casefold()
            for p in (filters.get("other_preferences") or [])
        ):
            suggestions.append("At least 4.5 stars")
        if filters.get("mode") == "walk":
            suggestions.append("Switch to transit")
        else:
            suggestions.append("Walk 15 mins")
        if signed_in and len(suggestions) < 4:
            suggestions.append("Save to profile")
        return suggestions[:4]

    @classmethod
    def summarize_changes(cls, before, after):
        changes = []
        if before.get("locations") != after.get("locations") and after.get(
            "locations"
        ):
            changes.append("📍 " + " + ".join(after["locations"]))
        if (
            before.get("mode"),
            before.get("max_travel_minutes"),
            before.get("max_distance_km"),
        ) != (
            after.get("mode"),
            after.get("max_travel_minutes"),
            after.get("max_distance_km"),
        ):
            icon = {
                "walk": "🚶 Walk",
                "drive": "🚗 Drive",
                "transit": "🚆 Transit",
            }.get(after["mode"], "🚶 Walk")
            if after.get("max_distance_km") is not None:
                changes.append(f"{icon} · {after['max_distance_km']:g} km")
            elif after.get("max_travel_minutes") is not None:
                changes.append(
                    f"{icon} · {int(round(after['max_travel_minutes']))} mins"
                )
        if (
            before.get("budget_per_person") != after.get("budget_per_person")
            and after.get("budget_per_person") is not None
        ):
            changes.append(
                f"💰 {cls.format_budget_display(after['budget_per_person'])}"
            )
        if before.get("dietary_requirements") != after.get(
            "dietary_requirements"
        ):
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
                changes.append(
                    "🍽️ "
                    + ", ".join(c.title() for c in after["liked_cuisines"])
                )
            else:
                changes.append("Any cuisine")
        if before.get("disliked_cuisines") != after.get(
            "disliked_cuisines"
        ) and after.get("disliked_cuisines"):
            changes.append(
                "🚫 No "
                + ", ".join(c.title() for c in after["disliked_cuisines"])
            )
        if before.get("other_preferences") != after.get(
            "other_preferences"
        ) and after.get("other_preferences"):
            changes.append("✨ " + ", ".join(after["other_preferences"]))
        return changes

    @classmethod
    def format_confirmation_reply(
        cls, filters, prefix="Here is your current search setup:"
    ):
        locs = " + ".join(filters.get("locations") or []) or "Not set"
        loc_label = (
            "Meet between"
            if len(filters.get("locations") or []) > 1
            else "Location"
        )
        mode_name = {
            "walk": "Walk",
            "drive": "Drive",
            "transit": "Transit",
        }.get(filters.get("mode"), "Walk")
        if filters.get("max_distance_km") is not None:
            travel = f"{mode_name} · {filters['max_distance_km']:g} km"
        elif filters.get("max_travel_minutes") is not None:
            travel = (
                f"{mode_name}"
                " · "
                f"{int(round(filters['max_travel_minutes']))}"
                " mins"
            )
        else:
            travel = "Not set"
        budget = cls.format_budget_display(filters.get("budget_per_person"))
        diet = (
            ", ".join(
                d.title() for d in (filters.get("dietary_requirements") or [])
            )
            or "None"
        )
        liked = (
            ", ".join(c.title() for c in (filters.get("liked_cuisines") or []))
            or "Any"
        )
        lines = [
            prefix,
            f"• {loc_label}: {locs}",
            f"• Travel: {travel}",
            f"• Budget: {budget}",
            f"• Dietary: {diet}",
            f"• Cuisines: {liked}",
        ]
        if filters.get("disliked_cuisines"):
            lines.append(
                "• Avoid: "
                + ", ".join(c.title() for c in filters["disliked_cuisines"])
            )
        if filters.get("other_preferences"):
            lines.append(
                "• Wishes: " + ", ".join(filters["other_preferences"])
            )
        lines.append("")
        lines.append(
            (
                "Should I proceed with searching, or would you like to change "
                "anything?"
            )
        )
        return "\n".join(lines)

    @staticmethod
    def confirmation_quick_replies(filters, signed_in):
        replies = ["Yes, search now", "Change location"]
        if filters.get("dietary_requirements"):
            replies.append("No dietary limits")
        else:
            replies.append("Change budget")
        replies.append("Save to profile" if signed_in else "Edit cuisines")
        return replies

    def clarify_response(self, current, awaiting_field, reply, quick_replies):
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

    def handle_edit_request(self, lower, current):
        cleaned = re.sub(r"[.!?\s]+$", "", lower.strip())
        if cleaned in (
            "change location",
            "edit location",
            "change starting location",
            "location",
            "change place",
        ):
            prompt, qrs = self.prompt_for_missing_search_field("location")
            return self.clarify_response(current, "location", prompt, qrs)

        if cleaned in (
            "add location",
            "add another location",
            "add second location",
            "add more locations",
            "add a location",
        ):
            return self.clarify_response(
                current,
                "add_location",
                (
                    "Sure! Which Singapore location(s) would you like to add "
                    "to meet in the middle? (e.g. 'Marina Bay' or 'Marina "
                    "Bay, Sentosa')"
                ),
                ["Marina Bay", "Orchard Road", "Bugis Junction", "Sentosa"],
            )

        if cleaned in ("change budget", "edit budget", "budget"):
            prompt, qrs = self.prompt_for_missing_search_field(
                "budget_per_person"
            )
            return self.clarify_response(
                current, "budget_per_person", prompt, qrs
            )

        if cleaned in (
            "change travel",
            "edit travel",
            "change time",
            "edit time",
            "change distance",
            "edit distance",
            "travel",
            "change transport",
        ):
            prompt, qrs = self.prompt_for_missing_search_field("travel")
            return self.clarify_response(current, "travel", prompt, qrs)

        if cleaned in (
            "change dietary",
            "edit dietary",
            "dietary",
            "dietary requirements",
            "change diet",
            "edit diet",
            "diet",
            "change halal",
            "edit halal",
        ):
            active_diet = [
                d
                for d in (current.get("dietary_requirements") or [])
                if d in ("halal", "vegetarian")
            ]
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
                return self.clarify_response(
                    current,
                    "dietary_requirements",
                    (
                        "Dietary is currently set to "
                        f"{active_label}"
                        ". Would you like to remove it, clear all dietary "
                        "limits, or switch?"
                    ),
                    qrs[:4],
                )
            return self.clarify_response(
                current,
                "dietary_requirements",
                (
                    "Which dietary requirement would you like to apply? (e.g. "
                    "'Halal', 'Vegetarian', or 'No dietary limits')"
                ),
                ["Halal", "Vegetarian", "Both", "No dietary limits"],
            )

        if cleaned in (
            "change cuisine",
            "edit cuisine",
            "edit cuisines",
            "change cuisines",
            "cuisines",
            "change liked cuisines",
            "edit liked cuisines",
        ):
            liked = current.get("liked_cuisines") or []
            qrs = [
                "Japanese, Korean",
                "Mexican",
                "Any cuisine",
                "Yes, search now",
            ]
            if liked:
                qrs = [
                    f"Remove {liked[0].title()}",
                    "Any cuisine",
                    "Japanese, Korean",
                    "Yes, search now",
                ]
            return self.clarify_response(
                current,
                "liked_cuisines",
                (
                    "Which cuisines would you like to include, add, or "
                    "remove? (e.g. 'Japanese, Mexican', 'remove japanese', or "
                    "'any cuisine')"
                ),
                qrs,
            )

        if cleaned in (
            "change dislikes",
            "edit dislikes",
            "edit disliked cuisines",
            "change disliked cuisines",
            "disliked cuisines",
            "dislikes",
            "avoid cuisines",
        ):
            disliked = current.get("disliked_cuisines") or []
            qrs = (
                [
                    "Clear dislikes",
                    "Avoid fast food",
                    "Avoid seafood",
                    "Yes, search now",
                ]
                if disliked
                else [
                    "Avoid fast food",
                    "Avoid seafood",
                    "Avoid chinese",
                    "Yes, search now",
                ]
            )
            return self.clarify_response(
                current,
                "disliked_cuisines",
                (
                    "Which cuisines would you like to avoid or clear from "
                    "your dislikes? (e.g. 'avoid seafood', 'clear dislikes')"
                ),
                qrs,
            )

        if cleaned in (
            "change wishes",
            "edit wishes",
            "wishes",
            "other preferences",
            "change preferences",
            "edit preferences",
            "special wishes",
        ):
            return self.clarify_response(
                current,
                "other_preferences",
                (
                    "What special wishes or atmosphere should I look for? "
                    "(e.g. 'quiet cozy spot', 'near mrt', or 'clear wishes')"
                ),
                [
                    "Quiet & cozy",
                    "Air-conditioned",
                    "Near MRT",
                    "Clear wishes",
                ],
            )

        if cleaned in (
            "no",
            "nope",
            "not yet",
            "wait",
            "edit",
            "change something",
            "cancel",
        ):
            return self.clarify_response(
                current,
                "confirm",
                (
                    "No problem! Tell me what you'd like to adjust (location, "
                    "budget, travel limit, dietary needs, cuisines, dislikes, "
                    "or wishes)."
                ),
                [
                    "Change location",
                    "Change budget",
                    "Change dietary",
                    "Edit cuisines",
                ],
            )
        return None

    def reject_invalid_location(self, current, err, target_field=None):
        field = (
            target_field
            if target_field in ("location", "add_location")
            else "location"
        )
        return self.clarify_response(
            current,
            field,
            (
                f"{err} Please enter a real Singapore area, MRT station, "
                "landmark, or 6-digit postal code (e.g. Bugis, Compass One, "
                "545078)."
            ),
            ["Bugis", "Orchard", "Tampines", "Jurong East"],
        )

    def reject_invalid_wishes(self, current, err):
        return self.clarify_response(
            current,
            "other_preferences",
            (
                f"{err}"
                " What special wishes or atmosphere should I look for? "
                "(e.g. 'quiet cozy spot', 'at least 4.5 stars', or 'clear "
                "wishes')"
            ),
            ["Quiet & cozy", "Air-conditioned", "Near MRT", "Clear wishes"],
        )

    def reject_invalid_cuisines(
        self, current, err, target_field="liked_cuisines"
    ):
        field = (
            target_field
            if target_field in ("liked_cuisines", "disliked_cuisines")
            else "liked_cuisines"
        )
        prompt = (
            "Which cuisines do you want to avoid? (e.g. 'Seafood', "
            "'Fast Food', 'None')"
            if field == "disliked_cuisines"
            else "Which cuisines would you prefer? (e.g. 'Japanese', "
            "'Spanish', 'Taiwanese', 'Seafood', or 'Any cuisine')"
        )
        replies = (
            ["No restrictions", "Seafood", "Fast Food", "Japanese"]
            if field == "disliked_cuisines"
            else ["Any cuisine", "Japanese", "Spanish", "Seafood"]
        )
        return self.clarify_response(
            current,
            field,
            f"{err} {prompt}",
            replies,
        )
