"""Fetch available chat-completion models from OpenAI-compatible APIs."""

from __future__ import annotations

import os
import re

import requests

from common import debug_log as log

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"

# Groq models must have at least this context window to be useful for the
# structured JSON prompts the application sends.
_MIN_GROQ_CONTEXT_WINDOW = 4096
_DEFAULT_CAP = 5

_NVIDIA_EXCLUDE_TOKENS = (
    "embed",
    "rerank",
    "reward",
    "guard",
    "safety",
    "topic-control",
    "parse",
    "clip",
    "detector",
    "calibration",
    "vila",
    "neva",
    "kosmos",
    "deplot",
    "fuyu",
    "translate",
    "starcoder",
    "codellama",
    "codegemma",
    "codestral",
    "-coder",
    "-code-",
    "-vl-",
    "vision",
    "-omni-",
    "muse",
    "cosmos",
    "palmyra-med",
    "palmyra-fin",
    "recurrentgemma",
    "llama2-70b",
    "gemma-2b",
    "mistral-7b-instruct",
)


def derive_models_url(chat_url_env, default_models_url, query=""):
    """Derive a ``/models`` URL from a configured chat-completions URL."""
    chat_url = os.getenv(chat_url_env, "").strip()
    if not chat_url:
        return default_models_url
    base = chat_url.split("?", 1)[0].rstrip("/")
    suffix = "/chat/completions"
    if base.endswith(suffix):
        base = base[: -len(suffix)]
    models_url = f"{base}/models"
    return f"{models_url}?{query}" if query else models_url


def _fetch_model_entries(url, api_key, provider_label, timeout=(3, 10)):
    """Fetch raw ``data`` entries from an OpenAI-compatible ``/models`` API."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            log.debug_log(
                f"{provider_label} /models returned HTTP {resp.status_code}.",
                "WARNING",
                "common.ai_models",
            )
            return []
        data = resp.json().get("data", [])
    except (requests.RequestException, ValueError, TypeError) as err:
        log.debug_log(
            f"{provider_label} /models request failed: {err}",
            "WARNING",
            "common.ai_models",
        )
        return []
    return data if isinstance(data, list) else []


def _extract_version_score(model_id):
    """Return the highest semantic version number encoded in *model_id*."""
    matches = re.findall(
        r"(?<![a-z0-9])(\d+)(?:\.(\d+))?(?![0-9.]*[btk]\b)",
        model_id.lower(),
    )
    best = 0.0
    for major, minor in matches:
        num = float(f"{major}.{minor or 0}")
        if num <= 20:
            best = max(best, num)
    return best


def fetch_groq_models(api_key, models_url=None, timeout=(3, 10)):
    """Return Groq model IDs suitable for structured chat completions."""
    url = models_url or GROQ_MODELS_URL
    data = _fetch_model_entries(url, api_key, "Groq", timeout=timeout)
    if not data:
        return []

    eligible = []
    for entry in data:
        if not entry.get("active"):
            continue
        model_id = (entry.get("id") or "").lower()
        if not model_id or "guard" in model_id or "safeguard" in model_id:
            continue
        inputs = entry.get("input_modalities") or []
        outputs = entry.get("output_modalities") or []
        if "text" not in inputs or "text" not in outputs:
            continue
        ctx = entry.get("context_window") or 0
        if ctx < _MIN_GROQ_CONTEXT_WINDOW:
            continue
        eligible.append((entry["id"], ctx))

    # Largest context first -> most capable model tried first.
    eligible.sort(key=lambda pair: pair[1], reverse=True)
    ids = [model_id for model_id, _ in eligible]
    log.debug_log(
        f"Groq: discovered {len(ids)} chat model(s): {ids}",
        "INFO",
        "common.ai_models",
    )
    return ids


def _rank_nvidia_model(index_and_id):
    idx, model_id = index_and_id
    lower = model_id.lower()
    if "bolt" in lower:
        speed_tier = 0
    elif "lightning" in lower:
        speed_tier = 1
    elif any(
        re.search(rf"(?<![a-z0-9]){tag}(?![a-z0-9])", lower)
        for tag in ("ultra", "flash", "mini", "nano")
    ):
        speed_tier = 2
    elif any(
        re.search(rf"(?<![a-z0-9]){tag}(?![a-z0-9])", lower)
        for tag in ("large", "super", "instruct", "it")
    ):
        speed_tier = 3
    else:
        speed_tier = 4
    nvidia_bonus = 0 if lower.startswith("nvidia/") else 1
    version = _extract_version_score(lower)
    return (speed_tier, nvidia_bonus, -version, idx)


def fetch_nvidia_models(
    api_key, models_url=None, timeout=(3, 5), limit=_DEFAULT_CAP
):
    """Return prioritized NVIDIA NIM chat model IDs."""
    url = models_url or derive_models_url(
        "BITEFINDER_NVIDIA_URL",
        NVIDIA_MODELS_URL,
    )
    data = _fetch_model_entries(url, api_key, "NVIDIA", timeout=timeout)
    if not data:
        return []

    eligible = []
    for entry in data:
        model_id = (entry.get("id") or "").strip()
        if not model_id:
            continue
        lower = model_id.lower()
        if any(token in lower for token in _NVIDIA_EXCLUDE_TOKENS):
            continue
        eligible.append(model_id)

    ranked = sorted(enumerate(eligible), key=_rank_nvidia_model)
    ids = [model_id for _, model_id in ranked]
    if limit and limit > 0:
        ids = ids[:limit]
    log.debug_log(
        f"NVIDIA: selected {len(ids)} chat model(s): {ids}",
        "INFO",
        "common.ai_models",
    )
    return ids
