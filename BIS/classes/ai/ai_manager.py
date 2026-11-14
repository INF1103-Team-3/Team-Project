"""BIS AI Manager: prompt construction and validated AI interpretation."""

import json

from BIS.classes.ai.contracts.bis_ai_manager_interface import BISAIManagerInterface
from sources.profile_schema import (
    PREFERENCE_FIELDS,
    clean_text,
    validate_preferences,
)


class AIManager(BISAIManagerInterface):
    """Own BIS AI request schemas while using an injected provider router."""

    def __init__(self, fallback_request, profile_prompt_builder,
                 profile_response_validator, search_validator):
        self._request = fallback_request
        self._profile_prompt_builder = profile_prompt_builder
        self._validate_profile_response = profile_response_validator
        self._validate_search = search_validator

    def process(self, record, config):
        if config.get("ai_bypass"):
            raise RuntimeError("AI is disabled for local testing.")
        context = {
            "current_profile": validate_preferences(record["preferences"]),
            "current_field": record["field"],
            "user_message": clean_text(record["text"], 1000),
        }
        if context["current_field"] not in PREFERENCE_FIELDS + (None,):
            raise ValueError("Invalid question field.")
        payload = {
            "model": config["openrouter_model"],
            "messages": self._profile_prompt_builder(context),
            "temperature": 0,
            "max_tokens": 700,
        }
        return self._request(
            payload, config, self._validate_profile_response)

    def interpret_search_request(self, request, today_request, config):
        if config.get("ai_bypass"):
            raise RuntimeError("AI is disabled for local testing.")
        payload = {
            "model": config["openrouter_model"],
            "messages": [
                {"role": "system", "content": (
                    "Interpret today's restaurant wish into one JSON search "
                    "request with exactly these keys: origin, mode, "
                    "max_distance_km, max_travel_minutes, traffic_aware, "
                    "cuisine, budget_per_person, other_preferences, "
                    "dietary_requirements, disliked_cuisines. Copy origin, "
                    "mode, distance, journey time, traffic_aware, budget, "
                    "dietary requirements, disliked cuisines, and selected "
                    "cuisine exactly from confirmed_choices. Preserve every "
                    "selected other preference. Do not duplicate a selected "
                    "preference with equivalent wording. Add to "
                    "other_preferences only wishes explicitly stated in "
                    "today_request; use short strings. Preserve any stated "
                    "minimum Google star rating exactly as a numeric star "
                    "threshold. Other preferences are the strongest part of "
                    "the search. Preserve words such as only, must, minimum, "
                    "and at least because they mark hard constraints. A bare "
                    "star rating without minimum wording remains a soft "
                    "preference. If today_request conflicts with a confirmed "
                    "choice, reflect the conflicting choice so the next "
                    "layer can ask the user. Do not invent locations, "
                    "restrictions, or restaurant facts. Return JSON only.")},
                {"role": "user", "content": json.dumps({
                    "confirmed_choices": request,
                    "today_request": today_request,
                }, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 700,
        }
        return self._request(
            payload, config,
            lambda parsed: self._validate_search(parsed))

    def chat_turn(self, message, current_filters, history, saved_profile, config):
        from BIS import ai_manager as bis_ai
        return bis_ai.interpret_chat_turn(
            message, current_filters, history, saved_profile, config)

    def review_profile_wishes(self, wishes, config):
        from BIS import ai_manager as bis_ai
        return bis_ai.review_profile_wishes(wishes, config)
