"""Deterministic preference acceptance and review-failure decisions."""

from BIS.sources.profile_schema import (
    is_recognized_cuisine,
    normalize_wish_text,
    strip_rating_clauses,
    validate_cuisine_list,
    validate_english_preferences,
)


class PreferenceValidationPolicy:
    """Keep cuisine/wish rules independent of AI providers and web flows."""

    @staticmethod
    def prepare_wishes(items, field_label):
        cleaned = [
            normalize_wish_text(w)
            for w in (items or [])
            if normalize_wish_text(w)
        ]
        if not cleaned:
            return []
        return validate_english_preferences(cleaned, field_label=field_label)

    @staticmethod
    def reviewable_wishes(cleaned):
        return [
            rem
            for item in cleaned
            for rem in [strip_rating_clauses(item)]
            if rem
        ]

    @staticmethod
    def finish_wishes(cleaned, error, field_label):
        # Existing wishes remain valid during provider outages; a negative
        # structured review is still a rejection, with the caller's label.
        if error is None or isinstance(error, RuntimeError):
            return cleaned
        message = str(error).strip()
        if (
            message.startswith("Default special wishes")
            and field_label != "Default special wishes"
        ):
            message = field_label + message[len("Default special wishes"):]
        raise ValueError(
            message
            or (
                f"{field_label} must be proper, meaningful "
                "English preferences."
            )
        ) from error

    @staticmethod
    def prepare_cuisines(items, field_label):
        raw = [
            str(c or "").strip() for c in (items or []) if str(c or "").strip()
        ]
        return (
            validate_cuisine_list(raw, field_label=field_label) if raw else []
        )

    @staticmethod
    def unknown_cuisines(cleaned):
        return [c for c in cleaned if not is_recognized_cuisine(c)]

    @staticmethod
    def finish_cuisines(cleaned, unknown, reviewed, error, field_label):
        if not unknown or (reviewed and error is None):
            return cleaned
        if isinstance(error, ValueError):
            message = str(error).strip()
            if message and not message.lower().startswith(field_label.lower()):
                message = f"{field_label}: {message}"
            raise ValueError(
                message
                or (
                    f"{field_label}: '{unknown[0]}' is not a recognized "
                    "cuisine or food style (e.g. Japanese, Spanish, "
                    "Taiwanese, Seafood, Ramen)."
                )
            ) from error
        raise ValueError(
            f"{field_label}: '{unknown[0]}' is not a recognized cuisine or "
            "food style (e.g. Japanese, Spanish, Taiwanese, Seafood, Ramen)."
        )
