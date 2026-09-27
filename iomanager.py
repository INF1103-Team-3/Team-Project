"""Procedural BiteFinder signup, profile storage, and AI chatbot.

Run ``python iomanager.py`` to select a user and collect food preferences.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import sys
import tempfile
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
LEGACY_PROFILE_FILE = DATA_DIR / "user_profile.json"
USERS_FILE = DATA_DIR / "users.json"
LOG_FILE = LOG_DIR / "bitefinder.log"
DEBUG_ENABLED = False
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
VERIFICATION_TTL_SECONDS = 600
VERIFICATION_RESEND_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5
MINUTES_PER_KM = 20


def load_config():
    """Load application configuration from environment variables."""
    load_dotenv(ENV_FILE)
    ai_bypass = os.getenv("AI_BYPASS", "false").strip().lower() == "true"

    config = {
        "app_name": (
            os.getenv("APP_NAME", "BiteFinder").strip() or "BiteFinder"
        ),
        "ai_bypass": ai_bypass,
        "openrouter_api_keys": [] if ai_bypass else load_api_keys(),
        "openrouter_key_index": 0,
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "").strip(),
        "openrouter_base_url": os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        "openrouter_timeout_seconds": _read_positive_int(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30"),
            default=30,
        ),
        "smtp_host": os.getenv("SMTP_HOST", "").strip(),
        "smtp_bypass": (
            os.getenv("SMTP_BYPASS", "false").strip().lower() == "true"
        ),
        "smtp_security": (
            os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        ),
        "smtp_port": _read_positive_int(
            os.getenv("SMTP_PORT", "587"), default=587,
        ),
        "smtp_username": os.getenv("SMTP_USERNAME", "").strip(),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_from_email": os.getenv("SMTP_FROM_EMAIL", "").strip(),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    debug_log("Configuration loaded.")
    return config


def validate_config(config):
    """Return a list of configuration errors."""
    errors = []
    if config.get("ai_bypass") is True:
        return errors
    if not config.get("openrouter_api_keys"):
        errors.append(
            "Set OPENROUTER_API_KEYS, OPENROUTER_API_KEYS_FILE, or "
            "OPENROUTER_API_KEY in .env."
        )

    if not config.get("openrouter_model"):
        errors.append("Set OPENROUTER_MODEL in .env.")

    debug_log(f"Configuration validated with {len(errors)} error(s).")
    return errors


def load_api_keys():
    """Load selected keys: env list, then key file, then legacy single key.

    Lists accept JSON arrays or comma/newline-separated strings. Relative
    file paths resolve against the application directory. Never log keys.
    """
    value = os.getenv("OPENROUTER_API_KEYS", "").strip()
    filename = os.getenv("OPENROUTER_API_KEYS_FILE", "").strip()
    if not value and filename:
        path = Path(filename).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise ValueError(
                "Cannot read OPENROUTER_API_KEYS_FILE."
            ) from error
        if not value:
            raise ValueError("OPENROUTER_API_KEYS_FILE is empty.")
    elif not value:
        value = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            keys = json.loads(value)
        except ValueError as error:
            raise ValueError("API key list must be valid JSON.") from error
    else:
        keys = re.split(r"[,\r\n]+", value)
    if not isinstance(keys, list) or not keys:
        raise ValueError("API key list must contain at least one key.")
    selected = []
    for key in keys:
        if (
            not isinstance(key, str)
            or not key.strip()
            or any(character.isspace() for character in key.strip())
            or key.strip().startswith("replace_with_")
        ):
            raise ValueError("API key list contains an invalid entry.")
        key = key.strip()
        if key not in selected:
            selected.append(key)
    return selected


def next_api_key(config):
    """Advance the session's round-robin cursor once per request attempt."""
    keys = config.get("openrouter_api_keys")
    if not keys:
        # Support callers that still supply the original configuration shape.
        key = config.get("openrouter_api_key")
        keys = [key] if key else []
    if not keys:
        raise RuntimeError("No OpenRouter API keys are configured.")
    index = config.get("openrouter_key_index", 0) % len(keys)
    config["openrouter_key_index"] = (index + 1) % len(keys)
    debug_log(
        f"Selected key slot {index + 1} of {len(keys)}.",
        event="ai.route",
    )
    return keys[index]


def _read_positive_int(value, default):
    """Convert a value to a positive integer, otherwise return the default."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default

    if parsed_value <= 0:
        return default

    return parsed_value


def debug_log(message, level="DEBUG", event="application"):
    """Log timestamp, severity, and event; --debug also prints to stderr.

    Callers should pass operational messages, never credentials or user text.
    Logging failures must not interrupt onboarding.
    """
    level = level.upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Unsupported log level.")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    message = str(message).replace("\n", " ").replace("\r", " ")
    line = f"{timestamp} | {level:<7} | {event} | {message}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        if DEBUG_ENABLED:
            print("Debug log could not be written.", file=sys.stderr)
    if DEBUG_ENABLED:
        print(line, file=sys.stderr)


ALLOWED_PROFILE_FIELDS = {
    "name",
    "location",
    "max_distance_km",
    "max_travel_time_minutes",
    "budget_per_person",
    "dietary_requirements",
    "allergies",
    "liked_cuisines",
    "disliked_cuisines",
    "spice_preference",
    "dining_preferences",
}


LIST_FIELDS = {
    "dietary_requirements",
    "allergies",
    "liked_cuisines",
    "disliked_cuisines",
    "dining_preferences",
}


TEXT_FIELDS = {
    "name",
    "location",
    "spice_preference",
}


NUMBER_FIELDS = {
    "max_distance_km",
    "max_travel_time_minutes",
    "budget_per_person",
}


SPICE_CHOICES = ("none", "mild", "medium", "hot", "extra hot")
DIETARY_CHOICES = (
    "halal", "kosher", "vegetarian", "vegan", "pescatarian",
    "gluten-free", "dairy-free", "lactose-free", "egg-free", "nut-free",
    "peanut-free", "shellfish-free", "soy-free", "low-sodium", "low-sugar",
    "low-carb", "keto",
)
DIETARY_ALIASES = {
    "gluten free": "gluten-free", "no gluten": "gluten-free",
    "dairy free": "dairy-free", "no dairy": "dairy-free",
    "lactose free": "lactose-free", "lactose intolerant": "lactose-free",
    "egg free": "egg-free", "no eggs": "egg-free",
    "nut free": "nut-free", "no nuts": "nut-free",
    "peanut free": "peanut-free", "no peanuts": "peanut-free",
    "shellfish free": "shellfish-free", "no shellfish": "shellfish-free",
    "soy free": "soy-free", "no soy": "soy-free",
    "low sodium": "low-sodium", "low salt": "low-sodium",
    "low sugar": "low-sugar", "low carb": "low-carb",
    "ketogenic": "keto", "pescetarian": "pescatarian",
}


def dietary_answer_hint():
    """List the supported dietary categories without silently guessing."""
    return "Choose dietary requirements from: " + ", ".join(
        DIETARY_CHOICES
    ) + "; or none. Separate multiple requirements with commas."


def normalize_dietary_requirements(value):
    """Canonicalize known terms; reject the entire list if any is unknown."""
    items = _normalize_list(value)
    if items is None:
        return None
    normalized = []
    for item in items:
        term = " ".join(item.lower().split())
        if term == "none":
            return [] if len(items) == 1 else None
        term = DIETARY_ALIASES.get(term, term)
        if term not in DIETARY_CHOICES:
            return None
        if term not in normalized:
            normalized.append(term)
    return normalized


def validate_profile_updates(updates, strict=False):
    """Validate and normalize AI-produced profile updates."""
    if not isinstance(updates, dict):
        if strict:
            raise ValueError(
                "The AI returned invalid profile data. Try again.")
        debug_log(
            "Updates must be a dictionary.", "WARNING", "profile.validate"
        )
        return {}

    validated = {}
    rejected = []

    for field, value in updates.items():
        if field not in ALLOWED_PROFILE_FIELDS or value is None:
            continue

        if field == "allergies" and not valid_allergy_answer(value):
            debug_log("Numeric allergy answer rejected.", "WARNING",
                      "profile.validate")
            rejected.append(field)
            continue

        if field == "dietary_requirements":
            normalized = normalize_dietary_requirements(value)
        elif field == "spice_preference":
            normalized = _normalize_text(value)
            if normalized is not None:
                normalized = normalized.lower()
            if normalized not in SPICE_CHOICES:
                normalized = None
        elif field in LIST_FIELDS:
            normalized = _normalize_list(value)
        elif field in NUMBER_FIELDS:
            normalized = _normalize_number(field, value)
        elif field in TEXT_FIELDS:
            normalized = _normalize_text(value)
        else:
            normalized = None

        if normalized is not None:
            validated[field] = normalized
        else:
            rejected.append(field)

    if strict and rejected:
        message = "Please clarify " + ", ".join(
            field.replace("_", " ") for field in rejected
        ) + ". "
        if "dietary_requirements" in rejected:
            message += dietary_answer_hint() + " "
        if "spice_preference" in rejected:
            message += "Spice choices: " + ", ".join(SPICE_CHOICES) + "."
        raise ValueError(message.strip())

    estimate_travel_limits(validated)
    debug_log(f"Validated profile update fields: {list(validated.keys())}")
    return validated


def valid_allergy_answer(value):
    """Accept allergy text or an empty list; reject numbers and digits."""
    items = [value] if isinstance(value, str) else value
    return isinstance(items, list) and all(
        isinstance(item, str)
        and not any(character.isnumeric() for character in item)
        for item in items
    )


def estimate_travel_limits(updates):
    """Fill a missing travel limit using an approximate walking conversion.

    Work on the current update only so corrections replace stale estimates.
    Keep both limits when both were supplied explicitly.
    """
    distance = updates.get("max_distance_km")
    minutes = updates.get("max_travel_time_minutes")
    if minutes is not None and distance is None:
        estimate = _normalize_number(
            "max_distance_km", minutes / MINUTES_PER_KM,
        )
        if estimate is not None:
            updates["max_distance_km"] = estimate
    elif distance is not None and minutes is None:
        estimate = _normalize_number(
            "max_travel_time_minutes", distance * MINUTES_PER_KM,
        )
        if estimate is not None:
            updates["max_travel_time_minutes"] = estimate


def _normalize_text(value):
    """Normalize a profile text value."""
    if not isinstance(value, str):
        return None

    value = value.strip()
    if (
        not value or len(value) > 200
        or not any(character.isalnum() for character in value)
        or any(ord(character) < 32 for character in value)
    ):
        return None

    return value


def _normalize_list(value):
    """Normalize a list of short text values; an empty list is meaningful."""
    if value == []:
        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return None

    cleaned = []
    for item in value:
        if not isinstance(item, str):
            return None

        item = item.strip()
        if (
            not item or len(item) > 100
            or not any(character.isalpha() for character in item)
            or any(ord(character) < 32 for character in item)
        ):
            return None
        if item not in cleaned:
            cleaned.append(item)

    if not cleaned and value:
        return None

    return cleaned


def _normalize_number(field, value):
    """Normalize a numeric profile value and enforce reasonable MVP limits."""
    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if field == "max_distance_km" and not 0 < number <= 100:
        return None

    if (
        field == "max_travel_time_minutes"
        and not 0 < number <= 100 * MINUTES_PER_KM
    ):
        return None

    if field == "budget_per_person" and not 0 < number <= 1000:
        return None

    if number.is_integer():
        return int(number)

    rounded = round(number, 2)
    return rounded if rounded > 0 else None


PROFILE_FIELDS = [
    "name",
    "location",
    "max_distance_km",
    "max_travel_time_minutes",
    "budget_per_person",
    "dietary_requirements",
    "allergies",
    "liked_cuisines",
    "disliked_cuisines",
    "spice_preference",
    "dining_preferences",
]


QUESTION_MAP = {
    "name": "What should I call you?",
    "location": "Which area are you usually looking for food around?",
    "max_distance_km": (
        "How far are you willing to travel for food (in km or mins)? "
        "For example, 1 km or 20 minutes away."
    ),
    "max_travel_time_minutes": (
        "How long are you willing to travel for food (in mins)?"
    ),
    "budget_per_person": "What's your usual budget per person (in dollars)?",
    "dietary_requirements": (
        "Do you have any dietary requirements? " + dietary_answer_hint()
    ),
    "allergies": "Do you have any food allergies I should know about?",
    "liked_cuisines": "What cuisines or foods do you usually enjoy?",
    "disliked_cuisines": "Are there any cuisines or foods you normally avoid?",
    "spice_preference": (
        "How do you feel about spicy food? ("
        + ", ".join(SPICE_CHOICES) + ")"
    ),
    "dining_preferences": (
        "What kind of places do you usually like, for example hawker centres, "
        "cafes, casual restaurants, or something else?"
    ),
}


def create_empty_profile():
    """Create a new unanswered BiteFinder profile."""
    profile = {field: None for field in PROFILE_FIELDS}
    debug_log("Created an empty user profile.")
    return profile


def load_profile(user_id, config=None):
    """Load only the registered user's preferences."""
    user = require_verified_user(load_users(), user_id, config)
    profile = create_empty_profile()
    profile.update(validate_profile_updates(user["preferences"]))
    debug_log("Loaded preferences.", event="storage.load")
    return profile


def save_profile(user_id, profile, config=None):
    """Save this user's preferences while retaining every other user."""
    users = load_users()
    user = require_verified_user(users, user_id, config)
    preferences = create_empty_profile()
    preferences.update(validate_profile_updates(profile, strict=True))
    user["preferences"] = preferences
    write_users(users)
    debug_log("Saved preferences.", "INFO", "storage.save")
    if preferences["max_distance_km"] is not None:
        debug_log(
            f"max_travel_time_minutes="
            f"{preferences['max_travel_time_minutes']}, "
            f"max_distance_km={preferences['max_distance_km']}; "
            f"conversion assumption={MINUTES_PER_KM} min/km.",
            "INFO", "profile.travel",
        )
    return True


def update_profile(profile, updates):
    """Merge validated updates into the profile."""
    updates = validate_profile_updates(updates)
    changed_fields = []

    for field, value in updates.items():
        if profile.get(field) != value:
            profile[field] = value
            changed_fields.append(field)

    debug_log(f"Updated profile fields: {changed_fields}")
    return changed_fields


def get_next_question(profile, local_mode=False):
    """Return the next unanswered profile field and its question."""
    for field in PROFILE_FIELDS:
        if profile.get(field) is None:
            debug_log(f"Next profile question selected: {field}")
            question = QUESTION_MAP[field]
            if local_mode:
                if field in LIST_FIELDS:
                    question += " (Comma-separated answers, or none.)"
                elif field == "max_distance_km":
                    question += " Enter a number followed by km or mins."
                elif field == "budget_per_person":
                    question += " Enter a number from 0.01 to 1000."
                elif field in TEXT_FIELDS:
                    question += " (1–200 characters)"
            return field, question

    debug_log("Profile questionnaire is complete.")
    return None, None


def reset_profile(user_id, config=None):
    """Clear only this user's preferences, retaining their ID and email."""
    profile = create_empty_profile()
    save_profile(user_id, profile, config)
    debug_log("Reset preferences.", "INFO", "profile.reset")
    return profile


def format_profile(profile):
    """Return a human-readable profile summary."""
    labels = {
        "name": "Name",
        "location": "Location",
        "max_distance_km": "Max travel distance",
        "max_travel_time_minutes": "Max travel time",
        "budget_per_person": "Budget per person",
        "dietary_requirements": "Dietary requirements",
        "allergies": "Allergies",
        "liked_cuisines": "Likes",
        "disliked_cuisines": "Avoids",
        "spice_preference": "Spice preference",
        "dining_preferences": "Dining preferences",
    }

    lines = []
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        display_value = _format_value(field, value)
        lines.append(f"{labels[field]}: {display_value}")

    if profile.get("max_distance_km") is not None:
        lines.append(
            f"Time/distance conversions assume about {MINUTES_PER_KM} "
            "minutes per km on foot; actual travel times may vary."
        )
    debug_log("Formatted user profile for display.")
    return "\n".join(lines)


def _format_value(field, value):
    """Format one profile value for display."""
    if value is None:
        return "Not answered"

    if value == []:
        return "None"

    if isinstance(value, list):
        return ", ".join(value)

    if field == "max_distance_km":
        return f"{value} km"

    if field == "max_travel_time_minutes":
        return f"{value} minutes"

    if field == "budget_per_person":
        return f"${value}"

    return str(value)


SYSTEM_PROMPT = """
You are the natural-language understanding component for BiteFinder, a food
recommendation application.

Your job is to understand the user's message and extract profile information.
Python code, not you, controls the application flow.

Return ONLY one valid JSON object with this exact top-level structure:
{
  "intent": "profile_update",
  "profile_updates": {
    "name": null,
    "location": null,
    "max_distance_km": null,
    "max_travel_time_minutes": null,
    "budget_per_person": null,
    "dietary_requirements": null,
    "allergies": null,
    "liked_cuisines": null,
    "disliked_cuisines": null,
    "spice_preference": null,
    "dining_preferences": null
  }
}

Allowed intents:
- profile_update
- show_profile
- reset_profile
- help
- exit
- logout
- unknown

Rules:
1. Never invent information.
2. Extract all useful profile facts from the message, even if several fields
   are answered at once.
3. Use null when a profile field was not mentioned or cannot be inferred
   safely from the current question and user reply.
4. For list fields, use [] only when the user explicitly says "none", "no",
   or equivalent in response to that field. Otherwise use null when absent.
5. If the current question asks about allergies and the user says "no", set
   allergies to []. Apply the same rule to other list fields.
6. max_distance_km, max_travel_time_minutes, and budget_per_person must be
   numbers without units or currency symbols.
7. A phrase such as "below $20" should be represented as 20 for this MVP.
8. Preserve specific dietary terms such as halal, vegetarian, vegan, kosher,
   gluten-free, etc.
9. If the user clearly corrects an existing value, return the corrected value.
10. Do not delete an existing profile value unless the user's message clearly
    replaces it. For a replacement list, return the intended complete list.
11. If the user simply answers the current question, intent is profile_update.
12. Commands like "show my profile", "start over", "help", or "exit" should
    use the matching intent and normally return no profile updates.
    "Log out" or "switch user" should use logout, not exit.
13. Do not include markdown, explanations, or code fences.
14. Users can give their travel limit as distance or duration. Convert hours
    to minutes and metres to kilometres. For approximate walking estimates,
    use 20 minutes per kilometre: "10 mins away" means
    max_travel_time_minutes=10 and max_distance_km=0.5; "2 km away" means
    max_distance_km=2 and max_travel_time_minutes=40. This conversion is the
    only permitted estimate and is not a measured route time.
15. When the user corrects either travel limit, return the new value and
    recalculate its counterpart rather than copying an old profile value.
    If both limits are explicitly given, preserve both. If neither is
    mentioned, return null for both. Do not treat waiting, opening hours,
    or meal duration as travel time. The conversion is a walking estimate,
    not an estimate for driving, cycling, or public transport.
""".strip()
SYSTEM_PROMPT += (
    "\n16. spice_preference must be exactly one of: "
    + ", ".join(SPICE_CHOICES)
    + ". Map clear natural-language preferences to these exact terms. "
    "If ambiguous, return null rather than guess."
    "\n17. dietary_requirements may contain only: "
    + ", ".join(DIETARY_CHOICES)
    + ". Normalize clear synonyms to these canonical terms and deduplicate. "
    "Keep distinct requirements as separate entries. Do not map an unknown "
    "restriction to the closest supported one. In particular, random text "
    "such as dkdk is not a dietary requirement. Return null for an unclear "
    "field, never an invented category or an empty list meaning none."
    "\n18. All extracted values must be meaningful, supported by the user's "
    "message, and relevant to the field. Do not copy random text, "
    "placeholders, or instructions as preferences. Return null when unsure. "
    "Never invent "
    "an allergy or omit one because its name is unfamiliar."
)


def understand_user_message(
    user_input,
    profile,
    current_field,
    current_question,
    config,
):
    """Send the user message to OpenRouter and return safe structured data."""
    if config.get("ai_bypass") is True:
        return parse_local_answer(user_input, current_field)
    payload = _build_payload(
        user_input,
        profile,
        current_field,
        current_question,
        config,
    )

    raw_content = _call_openrouter(payload, config)
    parsed_response = _parse_json_response(raw_content)

    intent = parsed_response.get("intent", "unknown")
    if not isinstance(intent, str) or intent not in {
        "profile_update",
        "show_profile",
        "reset_profile",
        "help",
        "exit",
        "logout",
        "unknown",
    }:
        intent = "unknown"

    updates = validate_profile_updates(
        parsed_response.get("profile_updates", {}), strict=True,
    )

    debug_log(
        "AI response processed. "
        f"Intent={intent}, fields={list(updates.keys())}"
    )

    return {
        "intent": intent,
        "profile_updates": updates,
    }


def parse_local_answer(answer, field):
    """Validate one fixed-format CLI answer without making an AI request."""
    if field is None:
        raise ValueError(
            "Profile complete. Use /profile, /reset, /logout, or /quit.")
    answer = answer.strip()
    if answer.startswith("/"):
        raise ValueError(
            "Unknown command. Use /help to see available commands.")
    if not answer or any(ord(character) < 32 for character in answer):
        raise ValueError(
            "Enter a non-empty answer without control characters.")
    if field in {"max_distance_km", "max_travel_time_minutes"}:
        match = re.fullmatch(
            r"(\d+(?:\.\d{1,2})?)\s*(km|mins?|minutes?)?",
            answer, flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("Enter a positive number, e.g. 1 km or 20 mins.")
        number, unit = match.groups()
        if field == "max_distance_km" and unit is None:
            raise ValueError("Include the unit: km or mins, e.g. 1 km.")
        target = (
            "max_distance_km" if unit and unit.lower() == "km"
            else "max_travel_time_minutes"
        )
        updates = validate_profile_updates({target: number})
        if not all(key in updates for key in (
            "max_distance_km", "max_travel_time_minutes",
        )):
            raise ValueError(
                "Enter 0.01–100 km or 0.1–2000 mins, using at most "
                "two decimal places."
            )
    elif field == "budget_per_person":
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", answer):
            raise ValueError("Enter a number, e.g. 20 or 20.50 (no symbols).")
        updates = validate_profile_updates({field: answer})
        if not updates:
            raise ValueError("Budget must be between 0.01 and 1000 dollars.")
    elif field in LIST_FIELDS:
        if field == "allergies" and not valid_allergy_answer(answer):
            raise ValueError(
                "Allergies cannot contain numbers. Enter names such as "
                "peanuts, shellfish, or none."
            )
        if answer.lower() == "none":
            items = []
        else:
            items = [item.strip() for item in answer.split(",")]
            if any(
                not item or len(item) > 100 or item.lower() == "none"
                or not any(character.isalpha() for character in item)
                for item in items
            ):
                raise ValueError(
                    "Enter comma-separated text entries (1–100 characters "
                    "each), or none by itself."
                )
        updates = validate_profile_updates({field: items}, strict=True)
    elif field in TEXT_FIELDS:
        if len(answer) > 200 or not any(c.isalnum() for c in answer):
            raise ValueError(
                "Enter 1–200 characters containing text or digits.")
        if field == "spice_preference":
            answer = answer.lower()
            if answer not in SPICE_CHOICES:
                raise ValueError(
                    "Choose none, mild, medium, hot, or extra hot.")
        updates = validate_profile_updates({field: answer})
    else:
        raise ValueError("Unknown profile question. Use /reset to start over.")
    return {"intent": "profile_update", "profile_updates": updates}


def _build_payload(
    user_input,
    profile,
    current_field,
    current_question,
    config,
):
    """Build the OpenRouter chat-completions request payload."""
    context = {
        "current_profile": profile,
        "current_question_field": current_field,
        "current_question": current_question,
        "user_message": user_input,
    }

    payload = {
        "model": config["openrouter_model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(context, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 500,
    }

    debug_log("Built OpenRouter request payload.")
    return payload


def _call_openrouter(payload, config):
    """Call OpenRouter's chat-completions endpoint and return model text."""
    url = f"{config['openrouter_base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {next_api_key(config)}",
        "Content-Type": "application/json",
        "X-Title": config["app_name"],
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config["openrouter_timeout_seconds"],
        )
        response.raise_for_status()
    except requests.Timeout as error:
        debug_log("Request timed out.", "ERROR", "ai.request")
        raise RuntimeError(
            "The AI request timed out. Please try again.") from error
    except requests.RequestException as error:
        status_text = _get_safe_error_message(error)
        debug_log(status_text, "ERROR", "ai.request")
        raise RuntimeError(
            f"OpenRouter request failed: {status_text}"
        ) from error

    try:
        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        debug_log("OpenRouter returned an unexpected response structure.")
        raise RuntimeError(
            "OpenRouter returned an unexpected response."
        ) from error

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenRouter returned an empty response.")

    debug_log("OpenRouter request completed successfully.")
    return content.strip()


def _parse_json_response(content):
    """Parse a JSON object from the model response."""
    cleaned = content.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as error:
        debug_log("Invalid JSON response.", "ERROR", "ai.parse")
        raise RuntimeError(
            "The AI returned invalid structured data. Please try again."
        ) from error

    if not isinstance(parsed, dict):
        raise RuntimeError("The AI response was not a JSON object.")

    debug_log("Parsed structured JSON from AI response.")
    return parsed


def _get_safe_error_message(error):
    """Describe HTTP errors without logging provider bodies or credentials."""
    response = getattr(error, "response", None)
    if response is None:
        return "network error"
    return f"HTTP {response.status_code}"


LOCAL_COMMANDS = {
    "/profile": "show_profile",
    "/reset": "reset_profile",
    "/help": "help",
    "/quit": "exit",
    "/exit": "exit",
    "/logout": "logout",
}


def run_profile_chatbot(config, user_id):
    """Run the BiteFinder CLI conversation until the user exits."""
    profile = load_profile(user_id, config)
    app_name = config["app_name"]

    local_mode = config.get("ai_bypass", False)
    _print_welcome(app_name, config.get("openrouter_model", ""), local_mode)

    current_field, current_question = get_next_question(profile, local_mode)
    if current_question is None:
        print(f"\n{app_name}: Your profile is already complete.")
        print(format_profile(profile))
        if local_mode:
            print(f"\n{app_name}: Use /reset to answer the questions again.")
        else:
            print(f"\n{app_name}: You can still tell me about any changes.")
    else:
        print(f"\n{app_name}: {current_question}")

    while True:
        user_input = _read_user_input()
        if user_input is None:
            save_profile(user_id, profile, config)
            print(f"\n{app_name}: Profile saved. Goodbye!")
            break

        if not user_input:
            print(f"{app_name}: Please type a response.")
            continue

        local_intent = LOCAL_COMMANDS.get(user_input.lower())

        if local_intent:
            result = {
                "intent": local_intent,
                "profile_updates": {},
            }
        else:
            try:
                result = understand_user_message(
                    user_input,
                    profile,
                    current_field,
                    current_question,
                    config,
                )
            except (RuntimeError, ValueError) as error:
                print(f"{app_name}: {error}")
                print(
                    f"{app_name}: Your profile was not changed. "
                    "You can retry your answer."
                )
                continue

        intent = result["intent"]
        updates = result["profile_updates"]

        if intent == "logout":
            save_profile(user_id, profile, config)
            print(f"{app_name}: Profile saved. Logged out.")
            debug_log("User logged out.", "INFO", "session.logout")
            return "logout"

        if intent == "exit":
            save_profile(user_id, profile, config)
            print(f"{app_name}: Profile saved. Goodbye!")
            break

        if intent == "show_profile":
            print(f"\n{format_profile(profile)}\n")
            _repeat_or_advance(app_name, profile, local_mode)
            current_field, current_question = get_next_question(
                profile, local_mode)
            continue

        if intent == "reset_profile":
            profile = reset_profile(user_id, config)
            current_field, current_question = get_next_question(
                profile, local_mode)
            print(f"{app_name}: Your profile has been reset.")
            print(f"{app_name}: {current_question}")
            continue

        if intent == "help":
            _print_help(app_name, local_mode)
            current_field, current_question = get_next_question(
                profile, local_mode)
            if current_question:
                print(f"{app_name}: {current_question}")
            continue

        if updates:
            changed_fields = update_profile(profile, updates)
            if changed_fields:
                save_profile(user_id, profile, config)
                print(
                    f"{app_name}: Got it — I updated "
                    f"{_friendly_field_list(changed_fields)}."
                )
        elif intent in {"profile_update", "unknown"}:
            print(
                f"{app_name}: I couldn't confidently extract profile "
                "information from that."
            )

        current_field, current_question = get_next_question(
            profile, local_mode)

        if current_question is None:
            print(
                f"\n{app_name}: Great — your BiteFinder profile is complete!"
            )
            print(format_profile(profile))
            print(
                f"\n{app_name}: Use /profile, /reset, /logout, or /quit."
            )
        else:
            print(f"{app_name}: {current_question}")

    debug_log("Chatbot session ended.", "INFO", "session.end")
    return "exit"


def _read_user_input():
    """Read one line from the user and handle terminal EOF/interrupt."""
    try:
        user_input = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    debug_log("Received CLI user input.")
    return user_input


def _print_welcome(app_name, model, local_mode=False):
    """Print the CLI welcome message."""
    print("=" * 60)
    print(app_name)
    print("Local CLI profile setup" if local_mode
          else "AI-powered food preference profile setup")
    print("=" * 60)
    if not local_mode:
        print(f"Model: {model}")
    print("Commands: /profile  /reset  /help  /logout  /quit")
    debug_log("Printed chatbot welcome message.")


def _print_help(app_name, local_mode=False):
    """Print concise CLI help."""
    print(f"\n{app_name} commands:")
    print("  /profile  Show your current profile")
    print("  /reset    Clear your saved profile")
    print("  /help     Show this help")
    print("  /logout   Save and sign in with another email")
    print("  /quit     Save and exit")
    if local_mode:
        print("Answer one question at a time using its expected format.\n")
    else:
        print("You can also answer in normal natural language.\n")
    debug_log("Printed chatbot help.")


def _repeat_or_advance(app_name, profile, local_mode=False):
    """Print the next unanswered question after a utility action."""
    _, question = get_next_question(profile, local_mode)
    if question:
        print(f"{app_name}: {question}")


def _friendly_field_list(fields):
    """Convert internal field names to readable labels."""
    readable = [field.replace("_", " ") for field in fields]

    if len(readable) == 1:
        return readable[0]

    if len(readable) == 2:
        return f"{readable[0]} and {readable[1]}"

    return ", ".join(readable[:-1]) + f", and {readable[-1]}"


def main():
    """Select a registered user, validate configuration, and start chatting."""
    global DEBUG_ENABLED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--debug", action="store_true",
        help="Also print timestamped debug events to stderr.",
    )
    DEBUG_ENABLED = parser.parse_args().debug
    try:
        config = load_config()
        errors = validate_config(config)
        if errors:
            print("BiteFinder could not start:\n")
            for error in errors:
                print(f"- {error}")
            print("\nEdit the .env file and try again.")
            debug_log("Invalid configuration.", "ERROR", "config.validate")
            return
        while True:
            user = select_user(config)
            if user is None:
                print("BiteFinder: Goodbye!")
                return
            debug_log("Starting chatbot.", "INFO", "session.start")
            if run_profile_chatbot(config, user["userID"]) != "logout":
                break
    except (OSError, RuntimeError, ValueError) as error:
        debug_log(
            f"Operation failed ({type(error).__name__}).",
            "ERROR", "application.failure",
        )
        print(f"BiteFinder: {error}")
    except (EOFError, KeyboardInterrupt):
        print("\nBiteFinder: Goodbye!")


def normalize_email(email):
    """Validate a practical email format and normalize for unique lookup."""
    if not isinstance(email, str):
        raise ValueError("Please enter a valid email address.")
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("Please enter a valid email address.")
    local_part = email.split("@", 1)[0]
    if (
        len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
    ):
        raise ValueError("Please enter a valid email address.")
    return email


def load_users():
    """Read the user registry; never silently replace damaged saved data."""
    try:
        with USERS_FILE.open("r", encoding="utf-8") as file:
            users = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cannot read users.json. Check or restore the file before "
            "continuing; saved data has not been replaced."
        ) from error

    if not isinstance(users, dict):
        raise RuntimeError(
            "users.json must contain an object keyed by userID.")
    emails = set()
    for user_id, user in users.items():
        if (
            not user_id
            or not isinstance(user, dict)
            or user.get("userID") != user_id
            or not isinstance(user.get("preferences"), dict)
        ):
            raise RuntimeError("users.json contains an invalid user record.")
        try:
            email = normalize_email(user.get("email"))
        except ValueError as error:
            raise RuntimeError(
                "users.json contains an invalid email.") from error
        if email in emails:
            raise RuntimeError("users.json contains duplicate emails.")
        emails.add(email)
    return users


def write_users(users):
    """Atomically replace the JSON file so failed writes keep existing data."""
    temporary_path = None
    try:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=USERS_FILE.parent,
            prefix=".users-", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(users, file, indent=4,
                      ensure_ascii=False, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, USERS_FILE)
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Could not save users.json. Check disk space and permissions; "
            "the previous saved file has been retained."
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def require_user(users, user_id):
    """Require signup before any profile can be loaded, updated, or reset."""
    if user_id not in users:
        raise ValueError("Unknown userID. Please sign up first.")
    return users[user_id]


def require_verified_user(users, user_id, config=None):
    """Block preference access until email ownership has been verified."""
    user = require_user(users, user_id)
    if config and config.get("smtp_bypass") is True:
        return user
    if user.get("email_verified") is not True:
        raise ValueError("Verify your email before starting the chatbot.")
    return user


def register_user(email):
    """Persist a new user with a generated unique ID and unique email."""
    email = normalize_email(email)
    users = load_users()
    if any(normalize_email(user["email"]) == email for user in users.values()):
        raise ValueError("This email is already registered. Choose resume.")
    user_id = str(uuid4())
    while user_id in users:
        user_id = str(uuid4())
    user = {
        "userID": user_id,
        "email": email,
        "email_verified": False,
        "preferences": create_empty_profile(),
    }
    users[user_id] = user
    write_users(users)
    debug_log("Registered new user.", "INFO", "user.signup")
    return user


def find_user(email):
    """Find a saved profile by normalized email address."""
    email = normalize_email(email)
    for user in load_users().values():
        if normalize_email(user["email"]) == email:
            return user
    raise ValueError("No profile found for this email. Please sign up first.")


def validate_email_config(config):
    """Validate SMTP delivery settings without exposing credentials."""
    if not config.get("smtp_host"):
        raise ValueError("Set SMTP_HOST in .env to send verification emails.")
    if config.get("smtp_security") not in {"starttls", "ssl"}:
        raise ValueError("SMTP_SECURITY must be starttls or ssl.")
    port = config.get("smtp_port", 0)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be between 1 and 65535.")
    if bool(config.get("smtp_username")) != bool(config.get("smtp_password")):
        raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD in .env.")
    try:
        normalize_email(config.get("smtp_from_email"))
    except ValueError as error:
        raise ValueError("Set a valid SMTP_FROM_EMAIL in .env.") from error


def send_verification_email(email, code, config):
    """Deliver a code over TLS; never print or log the code or SMTP errors."""
    validate_email_config(config)
    message = EmailMessage()
    message["Subject"] = "Your BiteFinder email verification code"
    message["From"] = normalize_email(config["smtp_from_email"])
    message["To"] = normalize_email(email)
    message.set_content(
        f"Your BiteFinder verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not request it, "
        "you can ignore this email.\n"
    )
    context = ssl.create_default_context()
    try:
        if config["smtp_security"] == "ssl":
            connection = smtplib.SMTP_SSL(
                config["smtp_host"], config["smtp_port"],
                timeout=30, context=context,
            )
        else:
            connection = smtplib.SMTP(
                config["smtp_host"], config["smtp_port"], timeout=30,
            )
        with connection as server:
            if config["smtp_security"] == "starttls":
                server.starttls(context=context)
            if config.get("smtp_username"):
                server.login(config["smtp_username"], config["smtp_password"])
            if server.send_message(message):
                raise RuntimeError("The verification email was refused.")
    except (OSError, RuntimeError) as error:
        debug_log("Email delivery failed.", "ERROR", "email.send")
        raise RuntimeError(
            "Could not send verification email. Check SMTP settings "
            "and try again."
        ) from error
    debug_log("Verification email sent.", "INFO", "email.send")


def hash_verification_code(code, salt):
    """Derive a salted hash; the plaintext code is never stored on disk."""
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), salt.encode("ascii"), 100_000,
    ).hex()


def request_email_verification(user_id, config):
    """Send a fresh code with persistent expiry and a resend cooldown."""
    users = load_users()
    user = require_user(users, user_id)
    if user.get("email_verified") is True:
        raise ValueError("This email is already verified.")
    now = time.time()
    previous = user.get("email_verification", {})
    if now < previous.get("sent_at", 0) + VERIFICATION_RESEND_SECONDS:
        raise ValueError("Wait 60 seconds between verification emails.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    send_verification_email(user["email"], code, config)
    user["email_verification"] = {
        "salt": salt,
        "code_hash": hash_verification_code(code, salt),
        "sent_at": now,
        "expires_at": now + VERIFICATION_TTL_SECONDS,
        "attempts": 0,
    }
    write_users(users)


def verify_email_code(user_id, code):
    """Consume a valid code or persist a failed attempt."""
    users = load_users()
    user = require_user(users, user_id)
    challenge = user.get("email_verification")
    if not challenge:
        raise ValueError("Request a verification code first.")
    if time.time() >= challenge["expires_at"]:
        raise ValueError("Verification code expired. Use /resend.")
    if challenge["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
        raise ValueError("Too many incorrect attempts. Use /resend.")
    challenge["attempts"] += 1
    valid = (
        isinstance(code, str)
        and re.fullmatch(r"[0-9]{6}", code.strip()) is not None
        and secrets.compare_digest(
            hash_verification_code(code.strip(), challenge["salt"]),
            challenge["code_hash"],
        )
    )
    if not valid:
        write_users(users)
        debug_log("Code rejected.", "WARNING", "email.verify")
        raise ValueError("Incorrect verification code.")
    user["email_verified"] = True
    user["email_verified_at"] = datetime.now().astimezone().isoformat()
    del user["email_verification"]
    write_users(users)
    debug_log("Email verified.", "INFO", "email.verify")
    return user


def verify_email_interactively(user, config):
    """Verify an unverified user; allow resending or leaving signup pending."""
    if user.get("email_verified") is True:
        return user
    if config.get("smtp_bypass") is True:
        print("BiteFinder: SMTP verification bypass is enabled for testing.")
        debug_log("Verification bypassed for testing.", "INFO", "email.bypass")
        return user
    user_id = user["userID"]
    challenge = user.get("email_verification", {})
    if (
        not challenge
        or time.time() >= challenge["expires_at"]
        or challenge["attempts"] >= VERIFICATION_MAX_ATTEMPTS
    ):
        try:
            request_email_verification(user_id, config)
            print("A verification email was sent. Check your inbox.")
        except (ValueError, RuntimeError) as error:
            print(f"BiteFinder: {error}")
    else:
        print("Use the six-digit verification code previously emailed to you.")
    print("Enter the code, /resend, or /quit to continue later.")
    while True:
        code = input("Verification: ").strip()
        if code.lower() in {"/quit", "/exit"}:
            return None
        try:
            if code.lower() == "/resend":
                request_email_verification(user_id, config)
                print("A new verification code was sent.")
                continue
            verified_user = verify_email_code(user_id, code)
            print("Email verified.")
            return verified_user
        except (ValueError, RuntimeError) as error:
            print(f"BiteFinder: {error}")


def import_legacy_profile(user_id, config=None):
    """Explicitly copy the original single-user preferences to a new user."""
    try:
        with LEGACY_PROFILE_FILE.open("r", encoding="utf-8") as file:
            profile = json.load(file)
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "The original profile could not be read.") from error
    if not isinstance(profile, dict):
        raise RuntimeError("The original profile is not a JSON object.")
    save_profile(user_id, profile, config)
    debug_log("Imported original preferences.", "INFO", "storage.import")


def select_user(config):
    """Require signup or selection of an existing profile before chatting."""
    print("\nBiteFinder user profiles")
    print("1. Sign up\n2. Resume a saved profile\n3. Quit")
    print("Resume your saved profile using your email address.")
    while True:
        choice = input("Choose 1, 2, or 3: ").strip().lower()
        if choice in {"3", "/quit", "/exit"}:
            return None
        if choice not in {"1", "2"}:
            print("Please choose 1, 2, or 3.")
            continue
        try:
            if choice == "1":
                user = register_user(input("Email: "))
                print("Signed up. Use your email to resume this profile.")
                user = verify_email_interactively(user, config)
                if user is None:
                    return None
                return user
            user = find_user(input("Email: "))
            return verify_email_interactively(user, config)
        except ValueError as error:
            print(f"BiteFinder: {error}")


if __name__ == "__main__":
    main()
