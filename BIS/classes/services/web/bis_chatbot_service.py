"""Conversational BIS assistant: parses chat turns into synced search and
profile actions.
"""

from BIS.classes.logic.chat.chat_filter_policy import ChatFilterPolicy
from BIS.classes.logic.chat.deterministic_chat_parser import (
    DeterministicChatParser,
)
from BIS.classes.io.web.chat.chat_presenter import (
    ChatPresenter,
    _ONBOARDING_QUESTIONS,
)

from BIS.classes.services.web.preference_review_service import (
    PreferenceReviewService,
)

from copy import deepcopy
import re

from common.singapore_locations import validate_location_syntax


class BISChatbotService:
    """Turn natural-language user messages into incremental filter updates
    and actions.
    """

    def __init__(
        self,
        ai,
        logic,
        config,
        model_reader=lambda: None,
        profile_saver=None,
        location_gateway=None,
        preference_review=None,
    ):
        self._ai = ai
        self._logic = logic
        self._config = config
        self._model = model_reader
        self._save_profile = profile_saver
        self._locations = location_gateway
        self._reviews = preference_review or PreferenceReviewService(
            ai, logic, config
        )
        self._filters = (
            getattr(logic, "chat_filters", None) or ChatFilterPolicy()
        )
        self._presenter = ChatPresenter(model_reader)
        self._parser = DeterministicChatParser(
            self._presenter.format_profile_summary
        )

    def _validate_locations(self, raw_locations, label="Starting location"):
        validated = []
        api_key = (self._config or {}).get("google_maps_api_key")
        for raw in raw_locations or ():
            text = re.sub(r"\s+", " ", str(raw or "").strip())
            if not text:
                continue
            clean = validate_location_syntax(text, label=label)
            if re.fullmatch(r"\d{6}", clean):
                clean = f"Singapore {clean}"
            if self._locations is not None:
                try:
                    self._locations.resolve(clean, api_key)
                except ValueError as err:
                    raise ValueError(
                        f"'{text}' is not a valid Singapore location ({err})"
                    ) from err
                except RuntimeError as err:
                    if "unavailable" not in str(err).lower():
                        raise ValueError(
                            f"'{text}' could not be verified as a Singapore "
                            "location."
                        ) from err
            if clean not in validated:
                validated.append(clean)
        return validated

    def __handle_onboarding(self, user, message, awaiting_field, current):
        prefs = deepcopy((user or {}).get("preferences") or {})
        text = str(message or "").strip()
        lower = text.casefold()
        next_needed = self._filters.next_onboarding_field(prefs)

        if text == "__start_onboarding__" or not next_needed:
            if not next_needed:
                filters = self._filters.default_filters(user)
                return {
                    "success": True,
                    "action": "confirm",
                    "awaiting_field": "confirm",
                    "reply": self._presenter.format_confirmation_reply(
                        filters,
                        prefix="Your BiteFinder profile is already set up!",
                    ),
                    "filters": filters,
                    "changes": [],
                    (
                        "quick_replies"
                    ): self._presenter.confirmation_quick_replies(
                        filters, True
                    ),
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            prompt, quick_replies = _ONBOARDING_QUESTIONS[next_needed]
            step_num = (
                list(_ONBOARDING_QUESTIONS.keys()).index(next_needed) + 1
            )
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

        target_field = (
            awaiting_field
            if awaiting_field in _ONBOARDING_QUESTIONS
            else next_needed
        )
        is_none_answer = lower in (
            "none",
            "no",
            "nil",
            "n/a",
            "skip",
            "skip for now",
            "anything",
            "any",
        )

        if (
            target_field
            in (
                "dietary_requirements",
                "liked_cuisines",
                "disliked_cuisines",
                "other_preferences",
            )
            and is_none_answer
        ):
            prefs[target_field] = []
        else:
            parsed = None
            if not self._config.get("ai_bypass") and hasattr(
                self._ai, "chat_turn"
            ):
                try:
                    parsed = self._ai.chat_turn(
                        (
                            "[Profile setup question for "
                            f"{target_field}"
                            "] User answered: "
                            f"{text}"
                        ),
                        current,
                        [],
                        prefs,
                        deepcopy(self._config),
                    )
                except (RuntimeError, ValueError, TypeError):
                    parsed = None
            det_parsed = self._parser.parse(
                text, current, user, awaiting_field=target_field
            )
            reconciled = (
                self._filters.reconcile_ai_updates(det_parsed, parsed, current)
                if parsed is not None
                else det_parsed
            )
            merged_updates = dict(reconciled.get("updates") or {})
            if is_none_answer and target_field == "dietary_requirements":
                merged_updates["dietary_requirements"] = []
                merged_updates["dietary_action"] = "clear"

            updated_filters = self._filters.apply_updates(
                current, merged_updates, user=user
            )
            accepted = self._filters.apply_onboarding_answer(
                prefs,
                updated_filters,
                merged_updates,
                target_field,
                lower,
                self._logic.estimate_travel_limits,
            )
            onboarding_err = ""
            if (
                target_field == "location"
                and accepted
                and prefs.get("location")
            ):
                try:
                    prefs["location"] = self._validate_locations(
                        prefs["location"], label="Default location"
                    )
                except ValueError as err:
                    accepted = False
                    prefs.pop("location", None)
                    onboarding_err = str(err)
            if (
                target_field == "liked_cuisines"
                and accepted
                and prefs.get("liked_cuisines")
            ):
                try:
                    prefs["liked_cuisines"] = self._reviews.validate_cuisines(
                        prefs["liked_cuisines"],
                        field_label="Default preferred cuisines",
                    )
                except ValueError as err:
                    accepted = False
                    prefs.pop("liked_cuisines", None)
                    onboarding_err = str(err)
            if (
                target_field == "disliked_cuisines"
                and accepted
                and prefs.get("disliked_cuisines")
            ):
                try:
                    prefs["disliked_cuisines"] = (
                        self._reviews.validate_cuisines(
                            prefs["disliked_cuisines"],
                            field_label="Default disliked cuisines",
                        )
                    )
                except ValueError as err:
                    accepted = False
                    prefs.pop("disliked_cuisines", None)
                    onboarding_err = str(err)
            if target_field == "other_preferences":
                if merged_updates.get("other_action") == "clear":
                    prefs["other_preferences"] = []
                    accepted = True
                else:
                    candidate_wishes = list(
                        merged_updates.get("other_preferences")
                        or [p.strip() for p in text.split(",") if p.strip()]
                    )
                    try:
                        candidate_wishes = self._reviews.validate_wishes(
                            candidate_wishes,
                            field_label="Special requests",
                        )
                    except ValueError as err:
                        onboarding_err = str(err)
                    else:
                        if candidate_wishes:
                            prefs["other_preferences"] = candidate_wishes
                            accepted = True

            if not accepted:
                return self._presenter.onboarding_retry(
                    target_field, current, onboarding_err or None
                )

        # Persist only already-answered profile fields directly via
        # save_profile when possible
        saved_user = user
        if self._save_profile is not None:
            answered_payload = {"user_id": user["userID"]}
            for field in (
                "location",
                "max_distance_km",
                "max_travel_time_minutes",
                "budget_per_person",
                "dietary_requirements",
                "liked_cuisines",
                "disliked_cuisines",
                "other_preferences",
            ):
                if prefs.get(field) is not None:
                    answered_payload[field] = prefs[field]
            try:
                saved_user = self._save_profile(user, answered_payload)
            except ValueError as err:
                return self._presenter.onboarding_retry(
                    target_field, current, str(err)
                )

        updated_filters = self._filters.default_filters(saved_user)
        if not updated_filters.get("locations") and prefs.get("location"):
            updated_filters["locations"] = [
                self._filters.normalize_location(loc)
                for loc in prefs["location"]
            ]
            updated_filters["location"] = updated_filters["locations"][0]
        if current.get("mode") in ("walk", "drive", "transit"):
            updated_filters["mode"] = current["mode"]

        changes = self._presenter.summarize_changes(current, updated_filters)
        remaining = self._filters.next_onboarding_field(
            saved_user.get("preferences") or prefs
        )
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
            "reply": self._presenter.format_confirmation_reply(
                updated_filters,
                prefix="Your BiteFinder profile is complete and saved!",
            ),
            "filters": updated_filters,
            "changes": changes,
            "quick_replies": self._presenter.confirmation_quick_replies(
                updated_filters, True
            ),
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": True,
        }

    def respond(self, user, payload):
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError(
                "Please enter a message for the BiteFinder chatbot."
            )

        current = self._filters.normalize_filters(
            payload.get("current_filters"), user=user
        )
        awaiting_field = payload.get("awaiting_field")

        if payload.get("onboarding") and user:
            return self.__handle_onboarding(
                user, message, awaiting_field, current
            )

        lower = message.casefold().strip()
        edit_reply = self._presenter.handle_edit_request(lower, current)
        if edit_reply is not None:
            return edit_reply

        if self._filters.is_search_confirmation(lower):
            missing_field = self._filters.next_missing_search_field(current)
            if missing_field:
                prompt, qrs = self._presenter.prompt_for_missing_search_field(
                    missing_field
                )
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
            try:
                self._validate_locations(
                    current.get("locations") or [], label="Starting location"
                )
            except ValueError as err:
                return self._presenter.reject_invalid_location(
                    current, err, target_field="location"
                )
            try:
                self._reviews.validate_wishes(
                    current.get("other_preferences") or [],
                    field_label="Special requests",
                )
            except ValueError as err:
                return self._presenter.reject_invalid_wishes(current, err)
            return {
                "success": True,
                "action": "search",
                "awaiting_field": None,
                ("reply"): (
                    "Confirmed! Searching Google Places, travel routes, and "
                    "MUIS records now."
                ),
                "filters": current,
                "changes": [],
                "quick_replies": self._presenter.default_quick_replies(
                    current, bool(user)
                ),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        history = [
            {
                "role": str(item.get("role", "")),
                "text": str(item.get("text", ""))[:300],
            }
            for item in (payload.get("history") or [])[-6:]
            if isinstance(item, dict) and item.get("text")
        ]

        parsed = None
        if not self._config.get("ai_bypass") and hasattr(
            self._ai, "chat_turn"
        ):
            is_utility = lower in (
                "/help",
                "help",
                "/profile",
                "/reset",
                "reset",
                "/save",
            )
            if not is_utility:
                try:
                    saved_profile = (user or {}).get("preferences") or {}
                    ai_msg = (
                        f"[Answering question for {awaiting_field}] {message}"
                        if awaiting_field and awaiting_field != "confirm"
                        else message
                    )
                    parsed = self._ai.chat_turn(
                        ai_msg,
                        current,
                        history,
                        saved_profile,
                        deepcopy(self._config),
                    )
                except (RuntimeError, ValueError, TypeError):
                    parsed = None

        det_awaiting = None if awaiting_field == "confirm" else awaiting_field
        det_parsed = self._parser.parse(
            message, current, user, awaiting_field=det_awaiting
        )

        if parsed is None:
            parsed = det_parsed
        else:
            parsed = self._filters.reconcile_ai_updates(
                det_parsed, parsed, current
            )

        intent = parsed["intent"]
        reply = str(parsed.get("reply") or "").strip()
        quick_replies = [
            str(q).strip()[:45]
            for q in (parsed.get("quick_replies") or [])
            if str(q).strip()
        ][:4]

        if intent == "reset":
            updated = self._filters.default_filters(user)
            changes = self._presenter.summarize_changes(current, updated)
            if not changes and updated.get("locations"):
                changes = ["📍 " + " + ".join(updated["locations"])]
            return {
                "success": True,
                "action": "reset",
                "awaiting_field": None,
                "reply": reply or "Filters reset.",
                "filters": updated,
                "changes": changes,
                "quick_replies": quick_replies
                or self._presenter.default_quick_replies(updated, bool(user)),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        updates_dict = dict(parsed.get("updates") or {})
        if updates_dict.get("locations_action") not in ("remove", "clear"):
            if updates_dict.get("locations"):
                try:
                    updates_dict["locations"] = self._validate_locations(
                        updates_dict["locations"],
                        label="Starting location",
                    )
                except ValueError as err:
                    return self._presenter.reject_invalid_location(
                        current, err, target_field=awaiting_field
                    )
            elif (
                awaiting_field in ("location", "add_location")
                and not updates_dict
                and intent in ("clarify", "update_filters", "search")
            ):
                return self._presenter.reject_invalid_location(
                    current,
                    ValueError(
                        f"'{message}' is not a valid Singapore location."
                    ),
                    target_field=awaiting_field,
                )
        if updates_dict.get("liked_action") not in ("clear", "remove") and (
            updates_dict.get("liked_cuisines")
        ):
            try:
                updates_dict["liked_cuisines"] = (
                    self._reviews.validate_cuisines(
                        updates_dict["liked_cuisines"],
                        field_label="Preferred cuisines",
                    )
                )
            except ValueError as err:
                return self._presenter.reject_invalid_cuisines(
                    current, err, target_field="liked_cuisines"
                )
        if updates_dict.get("disliked_action") not in ("clear", "remove") and (
            updates_dict.get("disliked_cuisines")
        ):
            try:
                updates_dict["disliked_cuisines"] = (
                    self._reviews.validate_cuisines(
                        updates_dict["disliked_cuisines"],
                        field_label="Disliked cuisines",
                    )
                )
            except ValueError as err:
                return self._presenter.reject_invalid_cuisines(
                    current, err, target_field="disliked_cuisines"
                )
        if updates_dict.get("other_action") not in (
            "clear",
            "clear_rating",
            "remove",
        ) and updates_dict.get("other_preferences"):
            try:
                updates_dict["other_preferences"] = (
                    self._reviews.validate_wishes(
                        updates_dict["other_preferences"],
                        field_label="Special requests",
                    )
                )
            except ValueError as err:
                return self._presenter.reject_invalid_wishes(current, err)

        updated = self._filters.apply_updates(current, updates_dict, user=user)
        changes = self._presenter.summarize_changes(current, updated)
        saved_to_profile = False

        if intent == "save_profile":
            if not user or self._save_profile is None:
                return {
                    "success": True,
                    "action": "clarify",
                    "awaiting_field": None,
                    ("reply"): (
                        "Please sign in first so I can save your preferences "
                        "to your BiteFinder profile."
                    ),
                    "filters": updated,
                    "changes": changes,
                    "quick_replies": ["Yes, search now", "Help"],
                    "model_used": self._model() or "BiteFinder Assistant",
                    "saved_to_profile": False,
                }
            profile_payload = self._filters.build_safe_profile_payload(
                user, updated
            )
            try:
                self._save_profile(user, profile_payload)
            except ValueError as err:
                msg_low = str(err).lower()
                if "location" in msg_low:
                    return self._presenter.reject_invalid_location(
                        current, err, target_field="location"
                    )
                if "cuisine" in msg_low or "halal" in msg_low:
                    return self._presenter.reject_invalid_cuisines(
                        current,
                        err,
                        target_field=(
                            "disliked_cuisines"
                            if "disliked" in msg_low
                            else "liked_cuisines"
                        ),
                    )
                return self._presenter.reject_invalid_wishes(current, err)
            saved_to_profile = True
            reply = (
                "Saved your current preferences to your BiteFinder profile."
            )

        elif intent == "show_profile":
            reply = self._presenter.format_profile_summary(user)

        elif intent == "search" or bool(parsed.get("updates")):
            missing_field = self._filters.next_missing_search_field(updated)
            if missing_field:
                intent = "clarify"
                reply, quick_replies = (
                    self._presenter.prompt_for_missing_search_field(
                        missing_field
                    )
                )
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
            try:
                updated["other_preferences"] = self._reviews.validate_wishes(
                    updated.get("other_preferences") or [],
                    field_label="Special requests",
                )
            except ValueError as err:
                return self._presenter.reject_invalid_wishes(updated, err)
            return {
                "success": True,
                "action": "confirm",
                "awaiting_field": "confirm",
                "reply": self._presenter.format_confirmation_reply(
                    updated,
                    prefix="Got it! Please check if everything looks right:",
                ),
                "filters": updated,
                "changes": changes,
                "quick_replies": self._presenter.confirmation_quick_replies(
                    updated, bool(user)
                ),
                "model_used": self._model() or "BiteFinder Assistant",
                "saved_to_profile": False,
            }

        next_awaiting = None
        if intent == "clarify":
            next_awaiting = (
                "other_preferences"
                if awaiting_field == "other_preferences"
                and not parsed.get("updates")
                else self._filters.next_missing_search_field(updated)
            )
        return {
            "success": True,
            "action": intent,
            "awaiting_field": next_awaiting,
            "reply": reply,
            "filters": updated,
            "changes": changes,
            "quick_replies": quick_replies
            or self._presenter.default_quick_replies(updated, bool(user)),
            "model_used": self._model() or "BiteFinder Assistant",
            "saved_to_profile": saved_to_profile,
        }
