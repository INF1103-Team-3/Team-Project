"""OpenRouter communication and request parsing; no restaurant business rules."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from debug import debug_log
from schemas import normalize_request, validate_request

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_RESPONSE_BYTES = 100_000


def build_messages(text):
    prompt = (Path(__file__).parent / "prompts" / "interpret_request.txt")
    return [
        {"role": "system", "content": prompt.read_text(encoding="utf-8")},
        {"role": "user", "content": text},
    ]


def request_completion(messages, config):
    body = {
        "model": config["model"], "messages": messages, "temperature": 0,
        "max_tokens": 1000, "response_format": {"type": "json_object"},
    }
    request = Request(
        ENDPOINT, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + config["api_key"],
                 "Content-Type": "application/json"}, method="POST",
    )
    debug_log("ai_started")
    try:
        with urlopen(request, timeout=config["timeout"]) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return None, "AI response exceeded the size limit."
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        debug_log("ai_received")
        return content, None
    except HTTPError as error:
        debug_log("ai_failed", "error", error.code)
        return None, "AI service rejected the request. Check key, model and account limits."
    except (URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        debug_log("ai_failed", "error")
        return None, "AI service is unavailable or returned an invalid response."


def parse_interpretation(content):
    try:
        request = json.loads(content)
    except (ValueError, TypeError):
        return None, "AI response was not valid JSON."
    error = validate_request(request)
    if error:
        return None, error
    return normalize_request(request), None


def interpret_request(text, config):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        return None, "Enter a food request between 1 and 2000 characters."
    if not config.get("api_key") or not config.get("model"):
        return None, "Set OPENROUTER_API_KEY and OPENROUTER_MODEL, or use manual search."
    try:
        messages = build_messages(text)
    except (OSError, UnicodeError):
        return None, "AI prompt file is unavailable."
    for attempt in range(2):
        content, error = request_completion(messages, config)
        if error:
            return None, error
        request, error = parse_interpretation(content)
        if not error:
            return request, None
        debug_log("ai_invalid", "error")
        messages.append({"role": "user", "content":
                         "Return valid JSON matching every required field and type."})
    return None, "AI interpretation failed validation. Please use manual search."
