"""Fetch available chat-completion models from the Groq API."""
from __future__ import annotations

import requests
from shared import debug_log as log

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# Models must have at least this context window to be useful for the
# structured JSON prompts the application sends.
_MIN_CONTEXT_WINDOW = 4096


def fetch_chat_models(api_key, timeout=(3, 10)):
    """Return Groq model IDs suitable for chat completions.

    Only *active* models whose input and output modalities both include
    ``"text"`` and whose context window is at least 4 096 tokens are
    returned.  This filters out audio-only (Whisper), speech-output
    (Orpheus), and prompt-guard models that cannot produce the structured
    JSON replies the application requires.

    Models are returned largest-context-window first so that the most
    capable model is tried before smaller ones in the fallback chain.
    """
    if not api_key:
        return []
    try:
        resp = requests.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            log.debug_log(
                f"Groq /models returned HTTP {resp.status_code}.",
                "WARNING", "shared.groq_models",
            )
            return []
        data = resp.json().get("data", [])
    except requests.RequestException as err:
        log.debug_log(
            f"Groq /models request failed: {err}",
            "WARNING", "shared.groq_models",
        )
        return []

    eligible = []
    for entry in data:
        if not entry.get("active"):
            continue
        inputs = entry.get("input_modalities") or []
        outputs = entry.get("output_modalities") or []
        if "text" not in inputs or "text" not in outputs:
            continue
        ctx = entry.get("context_window") or 0
        if ctx < _MIN_CONTEXT_WINDOW:
            continue
        eligible.append((entry["id"], ctx))

    # Largest context first → most capable model tried first.
    eligible.sort(key=lambda pair: pair[1], reverse=True)
    ids = [model_id for model_id, _ in eligible]

    log.debug_log(
        f"Groq: discovered {len(ids)} chat model(s): {ids}",
        "INFO", "shared.groq_models",
    )
    return ids
