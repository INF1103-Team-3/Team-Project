"""BIS AI adapter for profile input and today's search preferences.

No persistence, user interaction, or restaurant recommendation logic.
"""

import json
import math
import os
import re
from pathlib import Path

import requests

from BIS.classes.ai.fallback.ai_provider_router import AIProviderRouter
from BIS.classes.ai.fallback.ai_provider_factory_registry import (
    AIProviderFactoryRegistry,
)
from BIS.classes.ai.ai_manager import AIManager
from BIS.classes.ai.tasks.bis_interpreter import BISInterpreter
from BIS.classes.ai.providers.clients.gemini_ai_provider import (
    GeminiAIProvider,
)
from BIS.classes.ai.providers.clients.groq_ai_provider import GroqAIProvider
from BIS.classes.ai.providers.clients.openrouter_ai_provider import (
    OpenRouterAIProvider,
)

from sources.prompts import INTENTS, SYSTEM_PROMPT

from common.debug_log import debug_log
from sources.profile_schema import PREFERENCE_FIELDS, validate_updates

BASE_DIR = Path(__file__).resolve().parent
GEMINI_URL = os.getenv(
    "BITEFINDER_GEMINI_URL",
    "https://generativelanguage.googleapis.com/v1beta/models",
)
GROQ_URL = os.getenv(
    "BITEFINDER_GROQ_URL",
    "https://api.groq.com/openai/v1/chat/completions",
)

# BIS owns this fallback order. Keep it independent of BRNS's model chain.
# Groq responds in ~1-2s; place discovered Groq models ahead of slower/broken
# secondary providers just like BRNS/BRC while keeping Gemini Flash Lite first.
MODEL_CHAIN = [
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},
]
_MANAGER = None


def manager():
    """Return the configured BIS AI Manager."""
    global _MANAGER
    if _MANAGER is None:
        from BIS import logic_manager

        _MANAGER = AIManager(
            _call_json_with_fallback,
            build_prompt,
            validate_response,
            logic_manager.validate_search_request,
            interpreter=BISInterpreter(
                lambda *args, **kwargs: _call_json_with_fallback(
                    *args, **kwargs
                )
            ),
        )
    return _MANAGER


def _extend_bis_chain_with_groq():
    """Fetch Groq chat models at startup and register them ahead of slow
    fallbacks.
    """
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR.parent / ".env")
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        from common.groq_models import fetch_chat_models

        for model_id in fetch_chat_models(api_key):
            MODEL_CHAIN.append({"provider": "groq", "model": model_id})
    MODEL_CHAIN.extend(
        [
            {"provider": "gemini", "model": "gemini-3.6-flash"},
            {
                "provider": "openrouter",
                "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
            },
        ]
    )


_extend_bis_chain_with_groq()


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
        event="BIS.ai.route",
    )
    return keys[index]


def _call_openrouter(payload, config):
    return _transport().call_openrouter(payload, config)


def _call_gemini(payload, model, config):
    return _transport().call_gemini(payload, model, config)


def _call_groq(payload, model, config):
    return _transport().call_groq(payload, model, config)


def _parse_json_response(content):
    """Parse a JSON object from the model response."""
    cleaned = content.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as error:
        debug_log("Invalid JSON response.", "ERROR", "BIS.ai.parse")
        raise RuntimeError(
            "The AI returned invalid structured data. Please try again."
        ) from error

    if not isinstance(parsed, dict):
        raise RuntimeError("The AI response was not a JSON object.")

    debug_log(
        "Parsed structured JSON from AI response.", "DEBUG", "BIS.ai.parse"
    )
    return parsed


def _call_json_with_fallback(
    payload, config, validator=None, skip_primary=False
):
    """Try the BIS primary model, then BIS's own fallback chain for JSON."""
    providers = []
    primary_model = config.get("openrouter_model")
    has_openrouter_key = bool(
        config.get("openrouter_api_keys") or config.get("openrouter_api_key")
    )
    if primary_model and not skip_primary:
        providers.append(
            OpenRouterAIProvider(
                primary_model,
                lambda request, settings: _call_openrouter(request, settings),
                primary=True,
                include_model=False,
            )
        )
    registry = AIProviderFactoryRegistry()
    registry.register(
        "gemini",
        lambda model: GeminiAIProvider(
            model,
            lambda request, settings, selected=model: _call_gemini(
                request, selected, settings
            ),
        ),
        enabled=lambda settings: bool(settings.get("gemini_api_key")),
    )
    registry.register(
        "openrouter",
        lambda model: OpenRouterAIProvider(
            model,
            lambda request, settings: _call_openrouter(request, settings),
        ),
        enabled=lambda _settings: has_openrouter_key,
    )
    registry.register(
        "groq",
        lambda model: GroqAIProvider(
            model,
            lambda request, settings, selected=model: _call_groq(
                request, selected, settings
            ),
        ),
        enabled=lambda settings: bool(settings.get("groq_api_key")),
    )
    for entry in MODEL_CHAIN:
        provider, model = entry.get("provider"), entry.get("model")
        if not model or any(char in model for char in "<> "):
            continue
        if (
            provider == "openrouter"
            and model == primary_model
            and has_openrouter_key
        ):
            continue
        configured = registry.create(provider, model, config)
        if configured is not None:
            providers.append(configured)
    return AIProviderRouter(
        providers,
        _parse_json_response,
        debug_log,
    ).route(payload, config, validator)


def has_fallback_provider(config):
    """Whether BIS can use at least one entry in its own model chain."""
    return any(
        entry.get("model")
        and not any(char in entry["model"] for char in "<> ")
        and (
            entry.get("provider") == "gemini"
            and config.get("gemini_api_key")
            or entry.get("provider") == "openrouter"
            and (
                config.get("openrouter_api_keys")
                or config.get("openrouter_api_key")
            )
            or entry.get("provider") == "groq"
            and config.get("groq_api_key")
        )
        for entry in MODEL_CHAIN
    )


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
        "intent",
        "profile_updates",
        "location_action",
    }:
        raise ValueError("The AI returned an unsupported response schema.")
    intent = data.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        raise ValueError("The AI returned an invalid intent.")
    if "profile_updates" not in data:
        raise ValueError("The AI response is missing profile_updates.")
    updates = validate_updates(data["profile_updates"])
    action = "add"
    if "location" in updates:
        action = data.get("location_action", "add")
        if action not in ("add", "replace", "remove"):
            raise ValueError("The AI returned an invalid location action.")
    if intent != "profile_update" and updates:
        raise ValueError("Utility commands cannot also change preferences.")
    return {"action": intent, "updates": updates, "location_action": action}


def call_api(prompt, config):
    """Send prepared messages through the configured model chain."""
    payload = {
        "model": config["openrouter_model"],
        "messages": prompt,
        "temperature": 0,
        "max_tokens": 700,
    }
    return _call_json_with_fallback(payload, config)


def parse_response(raw):
    """Parse one raw AI JSON response before schema validation."""
    return _parse_json_response(raw)


def process(record, config):
    """Stable temporary interface for the forthcoming team AI Manager."""
    return manager().process(record, config)


def interpret_command(text, config):
    return manager().interpreter.interpret_command(text, config)


def interpret_location(text, config):
    return manager().interpreter.interpret_location(text, config)


def interpret_search_choice(text, choices, config):
    return manager().interpreter.interpret_search_choice(text, choices, config)


def interpret_search_number(text, field, config):
    return manager().interpreter.interpret_search_number(text, field, config)


def interpret_profile_travel(text, config):
    return manager().interpreter.interpret_profile_travel(text, config)


def review_special_request(text, config):
    return manager().interpreter.review_special_request(text, config)


def review_prompt_text(text, config, context, maximum=1000):
    return manager().interpreter.review_prompt_text(
        text, config, context, maximum
    )


def equivalent_saved_request(text, saved, config):
    return manager().interpreter.equivalent_saved_request(text, saved, config)


def classify_search_constraints(text, config):
    return manager().interpreter.classify_search_constraints(text, config)


def interpret_search_request(request, today_request, config):
    """Propose a structured search from today's natural-language request."""
    return manager().interpret_search_request(request, today_request, config)


def interpret_chat_turn(
    message, current_filters, history, saved_profile, config
):
    return manager().interpreter.interpret_chat_turn(
        message, current_filters, history, saved_profile, config
    )


def review_profile_wishes(wishes, config):
    return manager().interpreter.review_profile_wishes(wishes, config)


def _transport():
    from BIS.classes.ai.providers.clients.provider_transport import (
        ProviderTransport,
    )

    return ProviderTransport(
        requests,
        debug_log,
        next_api_key,
        _get_safe_error_message,
        lambda: GEMINI_URL,
        lambda: GROQ_URL,
    )
