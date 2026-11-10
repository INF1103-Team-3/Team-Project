"""Compatibility façade for BRC AI classes.

New code should import from :mod:`BRC.classes`. The functions retained here
preserve the public Phase 1 provider-chain contract used by existing callers.
"""

import os
import re
import time

from BRC.classes.ai_client_interface import AIClientInterface
from BRC.classes.ai_manager import AIManager, CUISINES, CUISINE_PROMPT, MATCH_PROMPT
from BRC.classes.ai_provider_router import AIProviderRouter
from BRC.classes.ai_response_error import AIResponseError
from BRC.classes.ai_service_error import AIServiceError
from BRC.classes.gemini_client import GeminiClient


AIClient = AIClientInterface


def create_manager(api_key, model):
    """Build BRC's independent configured provider-chain state."""
    try:
        interval = float(os.getenv(
            "BRC_AI_REQUEST_INTERVAL_SECONDS", "4.2"))
    except ValueError:
        interval = 4.2
    try:
        timeout = float(os.getenv("BRC_AI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        timeout = 20.0
    try:
        chain_timeout = float(os.getenv(
            "BRC_AI_CHAIN_TIMEOUT_SECONDS", "45"))
    except ValueError:
        chain_timeout = 45.0
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    providers = []
    if api_key:
        providers.append({"provider": "gemini", "model": model})
        fallback = os.getenv(
            "BRC_GEMINI_FALLBACK_MODEL", "gemini-3.6-flash").strip()
        if fallback and fallback != model:
            providers.append({"provider": "gemini", "model": fallback})
    if openrouter_key:
        providers.append({
            "provider": "openrouter",
            "model": os.getenv(
                "BRC_OPENROUTER_MODEL",
                "nvidia/nemotron-3-ultra-550b-a55b:free").strip(),
        })
    if groq_key:
        providers.append({
            "provider": "groq",
            "model": os.getenv(
                "BRC_GROQ_MODEL", "openai/gpt-oss-20b").strip(),
        })
    providers = [entry for entry in providers if entry["model"]]
    if not providers:
        raise ValueError(
            "Set GEMINI_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY "
            "before running BRC.")
    return {
        "api_key": api_key,
        "model": model,
        "openrouter_api_key": openrouter_key,
        "groq_api_key": groq_key,
        "providers": providers,
        "client": None,
        "request_interval": min(max(interval, 0.0), 60.0),
        "timeout_seconds": min(max(timeout, 1.0), 120.0),
        "chain_timeout_seconds": min(max(chain_timeout, 1.0), 180.0),
        "last_request_at": None,
        "report": None,
    }


def _pace_request(manager):
    last_request = manager.get("last_request_at")
    if last_request is None:
        return
    remaining = manager.get("request_interval", 0) - (
        time.monotonic() - last_request)
    if remaining > 0:
        time.sleep(remaining)


def _retry_delay(error, attempt):
    match = re.search(
        r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
        str(error), re.IGNORECASE)
    supplied = float(match.group(1)) if match else 0.0
    return max(supplied, 4.2 * (attempt + 1))


def _call_gemini(prompt, manager, model):
    """Call one Gemini model using the legacy manager-dictionary contract."""
    from google import genai
    from google.genai import types

    if manager.get("client") is None:
        manager["client"] = genai.Client(
            api_key=manager.get("api_key"),
            http_options=types.HttpOptions(
                timeout=int(manager["timeout_seconds"] * 1000)))
    for attempt in range(5):
        _pace_request(manager)
        manager["last_request_at"] = time.monotonic()
        try:
            response = manager["client"].models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0, response_mime_type="application/json"))
        except Exception as error:
            alternatives_available = len(manager.get("providers", [])) > 1
            if (getattr(error, "code", None) != 429
                    or attempt == 4 or alternatives_available):
                raise
            delay = _retry_delay(error, attempt)
            if manager.get("report"):
                manager["report"](
                    "AI: Gemini rate limit reached; retrying in "
                    f"{delay:g} seconds...")
            time.sleep(delay)
            continue
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text
    raise RuntimeError("Gemini rate-limit retries were exhausted.")


def _call_chat_completions(prompt, manager, provider, model, timeout):
    """Call OpenRouter or Groq through its OpenAI-compatible endpoint."""
    import requests

    if provider == "openrouter":
        url = os.getenv(
            "BITEFINDER_OPENROUTER_URL",
            "https://openrouter.ai/api/v1/chat/completions")
        key = manager.get("openrouter_api_key")
    else:
        url = os.getenv(
            "BITEFINDER_GROQ_URL",
            "https://api.groq.com/openai/v1/chat/completions")
        key = manager.get("groq_api_key")
    _pace_request(manager)
    manager["last_request_at"] = time.monotonic()
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 4096,
            },
            timeout=(min(3, timeout), timeout),
        )
    except requests.RequestException as error:
        raise RuntimeError(f"{provider} network error") from error
    if response.status_code != 200:
        raise RuntimeError(f"{provider} HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RuntimeError(
            f"{provider} returned an unexpected response") from error
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"{provider} returned an empty response")
    return content


def call_api(prompt, manager, validator=None):
    """Preserve the legacy fallback API using the object router."""
    router = AIProviderRouter(_call_gemini, _call_chat_completions)
    return router.request(prompt, manager, validator)


__all__ = [
    "AIClient",
    "AIClientInterface",
    "AIManager",
    "AIResponseError",
    "AIServiceError",
    "CUISINES",
    "CUISINE_PROMPT",
    "GeminiClient",
    "MATCH_PROMPT",
    "call_api",
    "create_manager",
]
