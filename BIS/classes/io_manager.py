"""BIS IO Manager: terminal interaction and input workflow ownership."""

from BIS.classes.bis_search_io_interface import BISSearchIOInterface
from BIS.classes.bis_session_io_interface import BISSessionIOInterface
from BIS.sources.prompts import QUESTIONS
from BIS.sources.profile_schema import (
    CUISINE_FIELDS,
    OTHER_PREFERENCES,
    clean_text,
    validate_value,
)


class IOManager(BISSessionIOInterface, BISSearchIOInterface):
    """Own BIS interaction workflows and delegate focused UI primitives."""

    def __init__(self, helpers, prompt_reviewer, logic_manager):
        self._helpers = helpers
        self._review_prompt = prompt_reviewer
        self._logic = logic_manager

    def collect_search(self, user, config):
        profile = user["preferences"]
        location = self._helpers.ask_search_location(config)
        if location is None:
            return None
        mode = self._helpers.ask_search_mode(config)
        if mode is None:
            return None
        distance, minutes = self._helpers.ask_search_limit(
            profile, mode, config)
        if distance is None and minutes is None:
            return None
        traffic_aware = (
            self._helpers.ask_drive_traffic(config)
            if mode == "drive" and minutes is not None else False)
        if traffic_aware is None:
            return None
        cuisine = self._helpers.ask_search_cuisine(profile, config)
        if cuisine is None:
            return None
        save_cuisine = False
        if (cuisine != "none"
                and cuisine not in (profile["liked_cuisines"] or [])):
            disliked = cuisine in (profile["disliked_cuisines"] or [])
            question = (
                f"Add {cuisine.title()} to your saved liked cuisines"
                + (
                    " and remove it from disliked cuisines?"
                    if disliked else "?"))
            save_cuisine = self._helpers.ask_yes_no(question, config)
            if save_cuisine is None:
                return None
        budget = self._helpers.ask_search_budget(profile, config)
        if budget is None:
            return None
        wishes = self._helpers.ask_search_wishes(profile, config)
        if wishes is None:
            return None
        other = wishes["selected"]
        if config.get("ai_bypass") and wishes["text"]:
            other = validate_value(
                OTHER_PREFERENCES, other + [wishes["text"]])
        request = {
            "origin": location,
            "mode": mode,
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": traffic_aware,
            "cuisine": cuisine,
            "budget_per_person": budget,
            OTHER_PREFERENCES: other,
            "dietary_requirements": list(
                profile["dietary_requirements"] or []),
            "disliked_cuisines": [
                item for item in (profile["disliked_cuisines"] or [])
                if item != cuisine],
        }
        return {
            "request": request,
            "today_request": wishes["text"],
            "save_cuisine": cuisine if save_cuisine else None,
        }

    def collect_action(self, user, config, field=None,
                       location_action="add"):
        preferences = user["preferences"]
        field = field or self._logic.next_field(preferences)
        if field is not None:
            self.display_message(QUESTIONS[field])
        text = self._helpers.read_input()
        if text is None:
            return {"action": "exit"}
        command = self._helpers.command_action(text)
        if command is not None:
            return command
        natural_command = self._helpers.natural_command_action(
            text, config, allow_ai=field is None)
        if natural_command is not None:
            return natural_command
        if field == OTHER_PREFERENCES and not text.strip():
            return {
                "action": "profile_update",
                "updates": {OTHER_PREFERENCES: []},
                "location_action": location_action,
            }
        text = clean_text(text, 1000)
        if field in {"max_distance_km", "max_travel_time_minutes"}:
            return self._helpers._profile_travel_action(
                text, field, config, location_action)
        if (field is not None
                and field not in {
                    "max_distance_km", "max_travel_time_minutes",
                    "budget_per_person"}
                and text.lower() not in {"none", "both"}
                and not config.get("ai_bypass")):
            reviewed = self._review_prompt(
                text, config, QUESTIONS[field], 1000)
            if reviewed is None:
                raise ValueError("Please rephrase your answer in English.")
            if reviewed != text:
                accepted = self._helpers.ask_yes_no(
                    f"Use '{reviewed}' instead?", config)
                if accepted is not True:
                    raise ValueError(
                        "No changes saved. Please re-enter your answer.")
                text = reviewed
        if field in CUISINE_FIELDS:
            if (not config.get("ai_bypass")
                    and text.lower() not in {
                        "none", "no preference", "no preferences"}):
                return self._helpers.interpretation_action(
                    preferences, field, text)
            updates = self._helpers.resolve_cuisines(
                text, field, preferences, config)
            return {
                "action": "profile_update",
                "updates": updates,
                "location_action": location_action,
            }
        if field == OTHER_PREFERENCES:
            updates = self._helpers.logic_manager.parse_local_answer(
                text, field)
            return {
                "action": "profile_update",
                "updates": updates,
                "location_action": location_action,
            }
        if not config.get("ai_bypass"):
            return self._helpers.interpretation_action(
                preferences, field, text)
        if field is None:
            raise ValueError("Use /edit to change a completed profile.")
        updates = self._helpers.logic_manager.parse_local_answer(text, field)
        return {
            "action": "profile_update",
            "updates": updates,
            "location_action": location_action,
        }

    def resolve_proposed_updates(self, *args, **kwargs):
        return self._helpers.resolve_proposed_updates(*args, **kwargs)

    def display_message(self, *args, **kwargs):
        return self._helpers.display_message(*args, **kwargs)

    def prompt_username(self):
        return self._helpers.prompt_username()

    def display_profile(self, user):
        return self._helpers.display_profile(user)

    def display_help(self, topic=None):
        return self._helpers.display_help(topic)

    def apply_color_setting(self, enabled):
        return self._helpers.apply_color_setting(enabled)

    def choose_profile_edit(self):
        return self._helpers.choose_profile_edit()

    def set_color_handler(self, handler):
        return self._helpers.set_color_handler(handler)

    def display_welcome(self, user):
        return self._helpers.display_welcome(user)

    def ask_search_clarification(self, config):
        return self._helpers.ask_search_clarification(config)

    def confirm_search_request(self, request, config=None):
        return self._helpers.confirm_search_request(request, config)

    def display_search_summary(self, request):
        return self._helpers.display_search_summary(request)

    def choose_results_action(self, *args, **kwargs):
        return self._helpers.choose_results_action(*args, **kwargs)

    def choose_result_sort(self):
        return self._helpers.choose_result_sort()

    def refine_search_request(self, request, profile, config):
        return self._helpers.refine_search_request(request, profile, config)

    def choose_route_result(self, result_count):
        return self._helpers.choose_route_result(result_count)
