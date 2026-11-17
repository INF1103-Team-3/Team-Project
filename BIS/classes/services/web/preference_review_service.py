"""Coordinate preference preparation, optional AI review, and acceptance."""

from copy import deepcopy

from BIS.classes.logic.validators.preference_validation_policy import (
    PreferenceValidationPolicy,
)


class PreferenceReviewService:
    """Share one IO -> AI -> Logic review flow across chat/profile/search."""

    def __init__(self, ai, logic, config, policy=None):
        self._ai = ai
        self._config = config
        self._policy = (
            policy
            or getattr(logic, "preference_validation", None)
            or PreferenceValidationPolicy()
        )

    def _review(self, capability, items):
        config = self._config or {}
        if (
            not items
            or config.get("ai_bypass")
            or self._ai is None
            or not hasattr(self._ai, capability)
        ):
            return False, None
        try:
            getattr(self._ai, capability)(items, deepcopy(config))
        except (RuntimeError, ValueError) as error:
            return True, error
        return True, None

    def validate_wishes(self, items, field_label="Special requests"):
        cleaned = self._policy.prepare_wishes(items, field_label)
        _, error = self._review(
            "review_profile_wishes", self._policy.reviewable_wishes(cleaned)
        )
        return self._policy.finish_wishes(cleaned, error, field_label)

    def validate_cuisines(self, items, field_label="Cuisine"):
        cleaned = self._policy.prepare_cuisines(items, field_label)
        unknown = self._policy.unknown_cuisines(cleaned)
        reviewed, error = self._review("review_cuisines", unknown)
        return self._policy.finish_cuisines(
            cleaned, unknown, reviewed, error, field_label
        )
