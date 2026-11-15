"""Compatibility façade for BRC AI classes.

New code should import from :mod:`BRC.classes`. The functions retained here
preserve the public Phase 1 provider-chain contract used by existing callers.
"""

import os
import re
import time

from BRC.classes.ai.providers.contracts.ai_client_interface import (
    AIClientInterface,
)
from BRC.classes.ai.ai_manager import (
    AIManager,
    CUISINES,
    CUISINE_PROMPT,
    MATCH_PROMPT,
)
from BRC.classes.ai.providers.fallback.ai_provider_router import (
    AIProviderRouter,
)
from BRC.classes.ai.errors.ai_response_error import AIResponseError
from BRC.classes.ai.errors.ai_service_error import AIServiceError
from BRC.classes.ai.providers.clients.gemini_client import GeminiClient
from BRC.classes.ai.providers.fallback.fallback_ai_client import (
    FallbackAIClient,
)


AIClient = AIClientInterface


def _append_discovered_provider(
    providers, provider_name, api_key, fetcher, explicit_env, fallback_model
):
    """Append discovered models for one OpenAI-compatible provider."""
    if not api_key:
        return
    models = fetcher(api_key)
    explicit = os.getenv(explicit_env, "").strip()
    if explicit and explicit not in models:
        models.insert(0, explicit)
    if not models:
        models = [fallback_model]
    for model_id in models:
        providers.append({"provider": provider_name, "model": model_id})


def create_manager(api_key, model):
    """Build BRC's independent configured provider-chain state."""
    from common.ai_models import fetch_nvidia_models, fetch_siliconflow_models
    from common.groq_models import fetch_chat_models

    try:
        interval = float(os.getenv("BRC_AI_REQUEST_INTERVAL_SECONDS", "1.5"))
    except ValueError:
        interval = 1.5
    try:
        timeout = float(os.getenv("BRC_AI_TIMEOUT_SECONDS", "12"))
    except ValueError:
        timeout = 12.0
    try:
        chain_timeout = float(os.getenv("BRC_AI_CHAIN_TIMEOUT_SECONDS", "45"))
    except ValueError:
        chain_timeout = 45.0
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    siliconflow_key = (
        os.getenv("SILICON_FLOW_API_KEY", "").strip()
        or os.getenv("SILICONFLOW_API_KEY", "").strip()
    )
    providers = []
    if api_key:
        providers.append({"provider": "gemini", "model": model})
    # Put fast OpenAI-compatible models ahead of slower fallbacks so 503/504
    # Gemini failures resolve quickly instead of stalling against deadlines.
    _append_discovered_provider(
        providers,
        "groq",
        groq_key,
        fetch_chat_models,
        "BRC_GROQ_MODEL",
        "openai/gpt-oss-20b",
    )
    _append_discovered_provider(
        providers,
        "nvidia",
        nvidia_key,
        fetch_nvidia_models,
        "BRC_NVIDIA_MODEL",
        "nvidia/nemotron-3.5-bolt-e4b",
    )
    _append_discovered_provider(
        providers,
        "siliconflow",
        siliconflow_key,
        fetch_siliconflow_models,
        "BRC_SILICONFLOW_MODEL",
        "Qwen/Qwen2.5-7B-Instruct",
    )
    if api_key:
        fallback = os.getenv(
            "BRC_GEMINI_FALLBACK_MODEL", "gemini-3.6-flash"
        ).strip()
        if fallback and fallback != model:
            providers.append({"provider": "gemini", "model": fallback})
    if openrouter_key:
        providers.append(
            {
                "provider": "openrouter",
                "model": os.getenv(
                    "BRC_OPENROUTER_MODEL",
                    "nvidia/nemotron-3-ultra-550b-a55b:free",
                ).strip(),
            }
        )
    providers = [entry for entry in providers if entry["model"]]
    if not providers:
        raise ValueError(
            "Set GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, "
            "NVIDIA_API_KEY, or SILICON_FLOW_API_KEY before running BRC."
        )
    return {
        "api_key": api_key,
        "model": model,
        "openrouter_api_key": openrouter_key,
        "groq_api_key": groq_key,
        "nvidia_api_key": nvidia_key,
        "siliconflow_api_key": siliconflow_key,
        "providers": providers,
        "client": None,
        "request_interval": min(max(interval, 0.0), 60.0),
        "timeout_seconds": min(max(timeout, 1.0), 120.0),
        "chain_timeout_seconds": min(max(chain_timeout, 1.0), 180.0),
        "last_request_at": None,
        "report": None,
    }


def create_client(settings):
    """Wire fallback behavior to the configured provider transports."""
    return FallbackAIClient(settings, _call_gemini, _call_chat_completions)


def _pace_request(manager):
    last_request = manager.get("last_request_at")
    if last_request is None:
        return
    remaining = manager.get("request_interval", 0) - (
        time.monotonic() - last_request
    )
    if remaining > 0:
        time.sleep(remaining)


def _retry_delay(error, attempt):
    match = re.search(
        r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
        str(error),
        re.IGNORECASE,
    )
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
                timeout=int(manager["timeout_seconds"] * 1000)
            ),
        )
    for attempt in range(5):
        _pace_request(manager)
        manager["last_request_at"] = time.monotonic()
        try:
            response = manager["client"].models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0, response_mime_type="application/json"
                ),
            )
        except Exception as error:
            alternatives_available = len(manager.get("providers", [])) > 1
            if (
                getattr(error, "code", None) != 429
                or attempt == 4
                or alternatives_available
            ):
                raise
            delay = _retry_delay(error, attempt)
            if manager.get("report"):
                manager["report"](
                    "AI: Gemini rate limit reached; retrying in "
                    f"{delay:g} seconds..."
                )
            time.sleep(delay)
            continue
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text
    raise RuntimeError("Gemini rate-limit retries were exhausted.")


_CHAT_PROVIDER_ENDPOINTS = {
    "openrouter": (
        "BITEFINDER_OPENROUTER_URL",
        "https://openrouter.ai/api/v1/chat/completions",
        "openrouter_api_key",
    ),
    "groq": (
        "BITEFINDER_GROQ_URL",
        "https://api.groq.com/openai/v1/chat/completions",
        "groq_api_key",
    ),
    "nvidia": (
        "BITEFINDER_NVIDIA_URL",
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "nvidia_api_key",
    ),
    "siliconflow": (
        "BITEFINDER_SILICONFLOW_URL",
        "https://api.siliconflow.com/v1/chat/completions",
        "siliconflow_api_key",
    ),
}


def _call_chat_completions(prompt, manager, provider, model, timeout):
    """Call an OpenAI-compatible chat-completions endpoint."""
    import requests

    endpoint = _CHAT_PROVIDER_ENDPOINTS.get(provider)
    if endpoint is None:
        raise ValueError(f"Unsupported chat provider: {provider}")
    url_env, default_url, key_name = endpoint
    url = os.getenv(url_env, default_url)
    key = manager.get(key_name)
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
            f"{provider} returned an unexpected response"
        ) from error
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
