"""Temporary profile AI adapter; replace process() with the team integration.

No persistence, user interaction, or restaurant recommendation logic.
"""

import json
import os
import re
from pathlib import Path

import requests

from sources.prompts import INTENTS, SYSTEM_PROMPT

from support.debug_log import debug_log
from sources.profile_schema import PREFERENCE_FIELDS, validate_updates

BASE_DIR = Path(__file__).resolve().parent


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


def build_prompt(record):
    """Return chat messages; only validated preferences go to the provider."""
    system = SYSTEM_PROMPT
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(record, ensure_ascii=False)},
    ]


def validate_response(data):
    """Reject malformed or obsolete output before using any fields."""
    if not isinstance(data, dict) or set(data) - {
        "intent", "profile_updates", "location_action",
    }:
        raise ValueError("The AI returned an unsupported response schema.")
    intent = data.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        raise ValueError("The AI returned an invalid intent.")
    if "profile_updates" not in data:
        raise ValueError("The AI response is missing profile_updates.")
    updates = validate_updates(data["profile_updates"])
    action = data.get("location_action", "add")
    if action not in ("add", "replace", "remove"):
        raise ValueError("The AI returned an invalid location action.")
    if intent != "profile_update" and updates:
        raise ValueError("Utility commands cannot also change preferences.")
    return {"action": intent, "updates": updates, "location_action": action}


def process(record, config):
    """Stable temporary interface for the forthcoming team AI Manager."""
    if config.get("ai_bypass"):
        raise RuntimeError("AI is disabled for local testing.")
    from sources.profile_schema import clean_text, validate_preferences

    context = {
        "current_profile": validate_preferences(record["preferences"]),
        "current_field": record["field"],
        "user_message": clean_text(record["text"], 1000),
    }
    if context["current_field"] not in PREFERENCE_FIELDS + (None,):
        raise ValueError("Invalid question field.")
    payload = {
        "model": config["openrouter_model"], "messages": build_prompt(context),
        "temperature": 0, "max_tokens": 700,
    }
    return validate_response(
        _parse_json_response(
            _call_openrouter(
                payload, config)))
