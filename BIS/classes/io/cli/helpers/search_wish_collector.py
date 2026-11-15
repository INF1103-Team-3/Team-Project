"""Interactive collection, review, and confirmation of today's search wishes."""

import re
from BIS.sources.profile_schema import OTHER_PREFERENCES


class SearchWishCollector:
    """Coordinate prompts with injected IO, AI, and domain collaborators."""

    def __init__(self, io, ai, logic, terminal_ui):
        self._io = io
        self._ai = ai
        self._logic = logic
        self._ui = terminal_ui

    def collect(self, profile, config):
        """Select earlier wishes or collect one new request for today's search."""
        saved = profile[OTHER_PREFERENCES] or []
        if saved:
            self._ui.section("Previous special requests")
            for number, item in enumerate(saved, 1):
                self._ui.item(number, item)
        while True:
            value = self._io.read_input(
                "What are you looking for today?\n"
                "Describe any extra wishes, such as 'spicy', 'minimum 4.5 "
                "stars', or 'only Korean'.\n"
                "Use 'minimum', 'at least', or 'only' for a hard requirement "
                "(this may give no matches).\n"
                "[Press Enter = none; all = every saved request; saved numbers; "
                "or new text] (/cancel): "
            )
            if self._io._cancelled(value):
                return None
            if not value or value.lower() == "none":
                return {"selected": [], "text": ""}
            if value.lower() == "all":
                return {"selected": list(saved), "text": ""}
            if re.fullmatch(r"\d+(?:\s*,\s*\d+)*", value):
                numbers = [int(part.strip()) for part in value.split(",")]
                if saved and all(1 <= number <= len(saved) for number in numbers):
                    selected = list(dict.fromkeys(
                        saved[number - 1] for number in numbers))
                    return {"selected": selected, "text": ""}
                self._io.display_message("Choose numbers shown in the previous requests list.")
                continue
            try:
                text = self._logic.validate_special_request_text(value)
                if not config.get("ai_bypass"):
                    try:
                        reviewed = self._ai.review_special_request(text, config)
                    except RuntimeError:
                        self._io.display_message(
                            "Could not check the wording. Please try again, "
                            "or press Enter for none.")
                        continue
                    if reviewed is None:
                        self._io.display_message(
                            "I could not understand that request. Please rephrase it.")
                        continue
                    self._logic.validate_special_request_text(reviewed)
                    if reviewed != text:
                        confirmed = self._io.ask_yes_no(
                            f"Use '{reviewed}' instead?", config)
                        if confirmed is None:
                            return None
                        if not confirmed:
                            continue
                        text = reviewed
                    if saved:
                        try:
                            equivalent = self._ai.equivalent_saved_request(
                                text, saved, config)
                        except RuntimeError:
                            self._io.display_message(
                                "Could not compare this with your saved requests. "
                                "Please try again.")
                            continue
                        if equivalent is not None:
                            self._io.display_message(
                                f"This matches your saved request '{equivalent}'. "
                                "Using the first saved version.")
                            return {"selected": [equivalent], "text": ""}
                    if re.search(
                            r"\b(?:only|must|required|minimum|at least|"
                            r"no less than|exclusively|[1-5](?:\.\d+)?\s*"
                            r"(?:stars?|/\s*5))\b", text, re.IGNORECASE):
                        try:
                            constraints = self._ai.classify_search_constraints(
                                text, config)
                        except RuntimeError:
                            self._io.display_message(
                                "Could not check whether this is a hard "
                                "requirement. Please try again.")
                            continue
                        hard_confirmed = False
                        rating = constraints["rating"]
                        if rating is not None and not constraints[
                                "rating_is_minimum"]:
                            hard_confirmed = self._io.ask_yes_no(
                                f"Make {rating:g} stars a hard minimum? "
                                "This may return no matching restaurants.", config)
                            if hard_confirmed is None:
                                return None
                            if hard_confirmed:
                                constraints["hard_requirement"] = True
                                constraints["rating_is_minimum"] = True
                        if constraints["hard_requirement"] and not hard_confirmed:
                            confirmed = self._io.ask_yes_no(
                                "Treat this as a hard requirement? Budget and "
                                "travel limits will become secondary, and there "
                                "may be no matching restaurants.", config)
                            if confirmed is None:
                                return None
                            if not confirmed:
                                continue
                        if constraints["hard_requirement"]:
                            text = self._logic.apply_search_constraints(text, constraints)
                return {"selected": [], "text": text}
            except ValueError as error:
                self._io.display_message(error)
