"""Compatibility wrapper for Groq chat-model discovery."""

from __future__ import annotations

from common.ai_models import (
    GROQ_MODELS_URL,
    derive_models_url,
    fetch_groq_models,
)


def fetch_chat_models(api_key, timeout=(3, 10)):
    """Return Groq model IDs suitable for structured chat completions."""
    url = derive_models_url("BITEFINDER_GROQ_URL", GROQ_MODELS_URL)
    return fetch_groq_models(api_key, models_url=url, timeout=timeout)
