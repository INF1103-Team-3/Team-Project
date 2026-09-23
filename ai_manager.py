"""AI layer — prompt building, API call, JSON parsing, schema validation.
Multi-provider chain (OpenRouter + direct Gemini) with automatic fallback.
Zero domain logic here. Never crashes: returns (ok, result_or_error, model_used_or_None)."""
import json
import time
import requests
import config

SYSTEM_PROMPT = """You convert a user's food request into strict JSON.

Return ONLY a JSON object with exactly these keys:
{
  "cuisine": string,
  "dietary": string,
  "allergies": [string],
  "budget_band": "any" | "inexpensive" | "moderate" | "expensive" | "very_expensive",
  "budget_min": number or null,
  "budget_max": number or null,
  "min_rating": number (1-5) or null,
  "max_walk_minutes": number or null,
  "eat_time": string,
  "free_text_notes": string
}

Rules:
- "dietary" must be one of: "none", "halal", "vegetarian", "vegan".
- Budget: if the record already contains budget_band / budget_min / budget_max
  (chosen from a menu), copy them through exactly.
  Free-text dollars: "$10" or "under 10" -> budget_max 10, budget_band "any".
  "between 5 and 15" or "5 to 15 dollars" -> budget_min 5, budget_max 15, budget_band "any".
  "cheap"/"budget"/"affordable" with no dollars -> budget_band "inexpensive".
  No budget mention -> budget_band "any", budget_min null, budget_max null.
- "min_rating": "well reviewed" -> 4.0; "top rated" -> 4.5; no mention -> null.
- Normalise: "ten minutes" -> 10. Use null when unmentioned
  ("any" cuisine, [] allergies, "now" eat_time if unspecified).
- Keep extra wishes (spicy, quiet, etc.) in "free_text_notes".
- Output JSON only. No explanations, no markdown fences."""

REQUIRED_KEYS = ["cuisine", "dietary", "allergies", "budget_band",
                 "budget_min", "budget_max", "min_rating",
                 "max_walk_minutes", "eat_time", "free_text_notes"]
VALID_BANDS = ("any", "inexpensive", "moderate", "expensive", "very_expensive")


def validate_chain():
    """Fail fast on placeholder/broken model entries before any API call."""
    problems = []
    for entry in config.MODEL_CHAIN:
        model = entry.get("model", "")
        if "<" in model or ">" in model or " " in model:
            problems.append(f"{entry.get('provider')}/{model}")
    return problems   # empty list = healthy


def build_prompt(user_record):
    return json.dumps(user_record, indent=2)


def parse_json_reply(content):
    """Extract the JSON object from an AI reply, tolerating markdown fences,
    reasoning preamble, or trailing commentary around it."""
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in AI reply")
    return json.loads(text[start:end + 1])


def validate_ai_output(data):
    """Schema validation required by the spec. Returns (True, data) or (False, error)."""
    if not isinstance(data, dict):
        return False, "AI output is not a JSON object"
    for key in REQUIRED_KEYS:
        if key not in data:
            return False, f"AI output missing required key: {key}"
    for key in ("max_walk_minutes", "min_rating", "budget_min", "budget_max"):
        if data[key] is not None and not isinstance(data[key], (int, float)):
            return False, f"AI output field '{key}' must be a number or null"
    if data.get("min_rating") is not None and not (1 <= data["min_rating"] <= 5):
        return False, "AI output field 'min_rating' must be between 1 and 5"
    if data.get("budget_min") is not None and data.get("budget_max") is not None \
            and data["budget_min"] > data["budget_max"]:
        return False, "AI output budget_min exceeds budget_max"
    if data.get("budget_band") not in VALID_BANDS:
        return False, "AI output field 'budget_band' has an invalid value"
    if not isinstance(data["allergies"], list):
        return False, "AI output field 'allergies' must be a list"
    if data.get("dietary") not in ("none", "halal", "vegetarian", "vegan"):
        return False, "AI output field 'dietary' has an invalid value"
    return True, data


def _log_ai_event(context, detail):
    """Spec: handle API failure gracefully — log and continue, never crash."""
    try:
        with open("data/api_errors.log", "a", encoding="utf-8") as f:
            f.write(f"ai_manager: {context}: {detail}\n")
    except OSError:
        pass


def _call_openrouter(model_id, system_prompt, user_text):
    """One OpenRouter attempt. Returns (True, reply_text) or (False, error)."""
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
               "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}]
    for use_json_mode in (True, False):
        payload = {"model": model_id, "messages": messages, "temperature": 0.2}
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = requests.post(config.OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        except requests.RequestException as err:
            return False, f"network error: {err}"
        if resp.status_code == 429:
            return False, "429 rate limited / free quota used"
        if resp.status_code == 400 and use_json_mode:
            continue                        # retry same model without json mode
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        try:
            return True, resp.json()["choices"][0]["message"]["content"]
        except (KeyError, ValueError) as err:
            return False, f"unexpected response shape: {err}"
    return False, "request rejected"


def _call_gemini(model_name, system_prompt, user_text):
    """One direct Google-Gemini attempt. Returns (True, reply_text) or (False, error)."""
    url = f"{config.GEMINI_URL}/{model_name}:generateContent"
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.2,
                             "responseMimeType": "application/json"},
    }
    for use_json in (True, False):
        if not use_json:
            body.pop("generationConfig", None)
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
        except requests.RequestException as err:
            return False, f"network error: {err}"
        if resp.status_code == 429:
            return False, "429 rate limited"
        if resp.status_code == 400 and use_json:
            continue                        # retry without json mime type
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        try:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            return True, "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, ValueError) as err:
            return False, f"unexpected response shape: {err}"
    return False, "request rejected"


def call_ai(user_record):
    """Walk MODEL_CHAIN across providers until one returns schema-valid JSON.
    Returns (True, parsed_dict, model_used) or (False, error_summary, None)."""
    user_text = build_prompt(user_record)
    errors = []
    for entry in config.MODEL_CHAIN:
        provider, model = entry["provider"], entry["model"]
        if provider == "openrouter":
            ok, content = _call_openrouter(model, SYSTEM_PROMPT, user_text)
        elif provider == "gemini":
            ok, content = _call_gemini(model, SYSTEM_PROMPT, user_text)
        else:
            ok, content = False, f"unknown provider '{provider}'"
        if ok:
            try:
                parsed = parse_json_reply(content)
            except ValueError as err:
                errors.append(f"{provider}/{model}: unparseable")
                _log_ai_event("fallback", f"{provider}/{model} unparseable: {err}")
                continue
            is_valid, result = validate_ai_output(parsed)
            if is_valid:
                return True, result, f"{provider}/{model}"
            errors.append(f"{provider}/{model}: schema invalid ({result})")
            _log_ai_event("fallback", f"{provider}/{model} schema: {result}")
            continue
        errors.append(f"{provider}/{model}: {content}")
        _log_ai_event("fallback", f"{provider}/{model} -> {content}")
        time.sleep(1)
    return False, "; ".join(errors), None
