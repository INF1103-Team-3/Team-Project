"""AI layer — prompt building, API call, JSON parsing, schema validation.
Model chain with automatic fallback. Zero domain logic here.
Never crashes: returns (ok, result_or_error, model_used_or_None)."""
import json
import re
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
  "min_rating": number (1-5) or null,
  "max_walk_minutes": number or null,
  "eat_time": string,
  "free_text_notes": string
}

Rules:
- "dietary" must be one of: "none", "halal", "vegetarian", "vegan".
- Singapore price bands: <= $8 inexpensive, <= $15 moderate, <= $30 expensive, else very_expensive.
  "$10" -> moderate. "cheap"/"budget" -> inexpensive. no mention -> "any".
- "min_rating": "well reviewed" -> 4.0; "top rated" -> 4.5; no mention -> null.
- If the record already contains budget_band / min_rating from a menu, copy them through.
- Normalise: "ten minutes" -> 10. Use null when unmentioned ("any" cuisine, [] allergies).
- Keep extra wishes (spicy, quiet, etc.) in "free_text_notes".
- Output JSON only. No explanations, no markdown fences."""

REQUIRED_KEYS = ["cuisine", "dietary", "allergies", "budget_band", "min_rating",
                 "max_walk_minutes", "eat_time", "free_text_notes"]
VALID_BANDS = ("any", "inexpensive", "moderate", "expensive", "very_expensive")


def build_prompt(user_record):
    return json.dumps(user_record, indent=2)


def parse_json_reply(content):
    """Strip markdown fences AND <think> reasoning blocks (Qwen3 emits these), then parse."""
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json", "", 1).strip()
    return json.loads(text)


def validate_ai_output(data):
    """Schema validation required by the spec. Returns (True, data) or (False, error)."""
    if not isinstance(data, dict):
        return False, "AI output is not a JSON object"
    for key in REQUIRED_KEYS:
        if key not in data:
            return False, f"AI output missing required key: {key}"
    for key in ("max_walk_minutes", "min_rating"):
        if data[key] is not None and not isinstance(data[key], (int, float)):
            return False, f"AI output field '{key}' must be a number or null"
    if data.get("min_rating") is not None and not (1 <= data["min_rating"] <= 5):
        return False, "AI output field 'min_rating' must be between 1 and 5"
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


def _attempt_model(model_id, user_record):
    """Try ONE model. Returns (True, reply_text) or (False, error_message).
    On 400 with json mode: retries once without response_format (some free
    models reject it). On 429: gives up on this model immediately so the
    chain can move to the next one (daily quota won't recover in seconds)."""
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(user_record)},
    ]
    for use_json_mode in (True, False):
        payload = {"model": model_id, "messages": messages, "temperature": 0.2}
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = requests.post(config.API_URL, headers=headers, json=payload, timeout=30)
        except requests.RequestException as err:
            return False, f"network error: {err}"
        if resp.status_code == 429:
            return False, "429 rate limited / free quota used"
        if resp.status_code == 400 and use_json_mode:
            continue  # retry same model without json mode
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
        try:
            return True, resp.json()["choices"][0]["message"]["content"]
        except (KeyError, ValueError) as err:
            return False, f"unexpected response shape: {err}"
    return False, "request rejected"


def call_ai(user_record):
    """Walk config.MODEL_CHAIN until one model returns schema-valid JSON.
    Returns (True, parsed_dict, model_used) or (False, error_summary, None)."""
    errors = []
    for model_id in config.MODEL_CHAIN:
        ok, content = _attempt_model(model_id, user_record)
        if ok:
            try:
                parsed = parse_json_reply(content)
            except ValueError as err:
                errors.append(f"{model_id}: unparseable output")
                _log_ai_event("fallback", f"{model_id} unparseable: {err}")
                continue
            is_valid, result = validate_ai_output(parsed)
            if is_valid:
                return True, result, model_id
            errors.append(f"{model_id}: schema invalid ({result})")
            _log_ai_event("fallback", f"{model_id} schema invalid: {result}")
            continue
        errors.append(f"{model_id}: {content}")
        _log_ai_event("fallback", f"{model_id} -> {content}")
        time.sleep(1)  # gentle before trying the next model
    return False, "; ".join(errors), None
