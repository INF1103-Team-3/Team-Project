"""AI layer — prompt building, API call, JSON parsing, schema validation.
Multi-provider chain (OpenRouter + direct Gemini) with automatic fallback.
Zero domain logic here. Never crashes: returns (ok, result_or_error, model_used_or_None)."""
from contextvars import ContextVar
import json
import re
import signal
import threading
import time
from contextlib import contextmanager

import requests
from BRNS import config, logic_manager
from BRNS.classes.ai_manager import AIManager
from BRNS.classes.ai_provider_router import AIProviderRouter
from BRNS.classes.ai_provider_factory_registry import AIProviderFactoryRegistry
from BRNS.classes.gemini_ai_provider import GeminiAIProvider
from BRNS.classes.groq_ai_provider import GroqAIProvider
from BRNS.classes.openrouter_ai_provider import OpenRouterAIProvider
from BRNS.classes.unsupported_ai_provider import UnsupportedAIProvider
from common import debug_log as log

SYSTEM_PROMPT = """You convert a user's food request into strict JSON.

Return ONLY a JSON object with exactly these keys:
{
  "cuisine": string,
  "dietary": string,
  "budget_band": "any" | "inexpensive" | "moderate" | "expensive" | "very_expensive",
  "budget_min": number or null,
  "budget_max": number or null,
  "min_rating": number (1-5) or null,
  "max_walk_minutes": number or null,
  "max_drive_km": number or null,
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
- "max_drive_km": copy from the record's max_drive_km (driving mode); null otherwise.
- "max_walk_minutes": copy from the record's max_walk_minutes (walking mode); null otherwise.
- Normalise: "ten minutes" -> 10. Use null when unmentioned
  ("any" cuisine, "now" eat_time if unspecified).
- Keep extra wishes (spicy, quiet, etc.) in "free_text_notes".
- Output JSON only. No explanations, no markdown fences."""

REQUIRED_KEYS = ["cuisine", "dietary", "budget_band",
                 "budget_min", "budget_max", "min_rating",
                 "max_walk_minutes", "max_drive_km", "eat_time", "free_text_notes"]
VALID_BANDS = ("any", "inexpensive", "moderate", "expensive", "very_expensive")
_ACTIVE_CHAIN_DEADLINE = ContextVar("brns_ai_deadline", default=None)
_LAST_USED_MODEL = ContextVar("brns_ai_model", default=None)
_CURRENT_ACTIVE_MODEL = None
_MANAGER = None


@contextmanager
def _recommendation_deadline(seconds):
    token = _ACTIVE_CHAIN_DEADLINE.set(time.monotonic() + seconds)
    _LAST_USED_MODEL.set(None)
    try:
        yield
    finally:
        _ACTIVE_CHAIN_DEADLINE.reset(token)


def manager():
    """Return the configured BRNS AI Manager."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AIManager(
            config, _recommend_candidates, _recommendation_deadline, _recommend_prepared)
    return _MANAGER


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
    if not isinstance(content, str):
        raise ValueError("no JSON object found in AI reply")
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
    for key in ("max_walk_minutes", "max_drive_km", "min_rating",
                "budget_min", "budget_max"):
        if data[key] is not None and not isinstance(data[key], (int, float)):
            return False, f"AI output field '{key}' must be a number or null"
    if data.get("min_rating") is not None and not (1 <= data["min_rating"] <= 5):
        return False, "AI output field 'min_rating' must be between 1 and 5"
    if data.get("budget_min") is not None and data.get("budget_max") is not None \
            and data["budget_min"] > data["budget_max"]:
        return False, "AI output budget_min exceeds budget_max"
    if data.get("budget_band") not in VALID_BANDS:
        return False, "AI output field 'budget_band' has an invalid value"
    if data.get("dietary") not in ("none", "halal", "vegetarian", "vegan"):
        return False, "AI output field 'dietary' has an invalid value"
    return True, data


def _safe_failure(detail):
    """Keep provider response bodies and URLs out of operational logs."""
    if isinstance(detail, str):
        status = re.match(r"HTTP (\d{3})", detail)
        if status:
            return f"HTTP {status.group(1)}"
        if "rate limited" in detail.lower():
            return "rate limited"
        if detail.startswith("network error"):
            return "network error"
    return "request failed"


def _log_ai_event(context, detail, level="WARNING"):
    global _CURRENT_ACTIVE_MODEL
    if isinstance(detail, str):
        if detail.startswith("Trying ") and detail.endswith("."):
            _CURRENT_ACTIVE_MODEL = detail[len("Trying "):-1].strip()
        elif detail.startswith("Accepted ") and detail.endswith(" response."):
            _CURRENT_ACTIVE_MODEL = detail[len("Accepted "):-len(" response.")].strip()
    log.debug_log(detail, level, f"BRNS.ai_manager.{context}")


@contextmanager
def _hard_request_deadline(seconds):
    """Enforce a total request deadline in the Linux application container.

    Requests' read timeout resets whenever another response chunk arrives. A
    provider can therefore keep a non-streaming request alive indefinitely by
    sending occasional bytes. SIGALRM supplies a true wall-clock deadline in
    the main thread; other platforms retain Requests' connect/read timeout.
    """
    supported = (
        hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and threading.current_thread() is threading.main_thread()
    )
    if not supported:
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expire(_signum, _frame):
        raise requests.Timeout("AI provider exceeded its total deadline")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.001, previous_timer[0] - elapsed),
                previous_timer[1],
            )


def _close_response_safely(resp):
    """Force-close an in-flight streaming socket on deadline expiry."""
    try:
        raw = getattr(resp, "raw", None)
        if raw is not None:
            fp = getattr(raw, "_fp", None)
            sock = getattr(getattr(fp, "fp", None), "raw", None)
            if hasattr(sock, "_sock") and sock._sock is not None:
                try:
                    sock._sock.close()
                except OSError:
                    pass
    except Exception:
        pass


def _post(url, **kwargs):
    """Post with socket inactivity and wall-clock limits across all threads."""
    seconds = config.AI_REQUEST_TIMEOUT_SECONDS
    deadline = _ACTIVE_CHAIN_DEADLINE.get()
    if deadline is not None:
        seconds = min(seconds, max(0.05, deadline - time.monotonic()))
    wall_deadline = time.monotonic() + seconds
    kwargs["timeout"] = (min(3, seconds), seconds)
    kwargs.setdefault("stream", True)
    with _hard_request_deadline(seconds):
        resp = requests.post(url, **kwargs)
        if not hasattr(resp, "iter_content"):
            return resp
        timed_out = threading.Event()

        def _expire():
            timed_out.set()
            _close_response_safely(resp)

        remaining = max(0.05, wall_deadline - time.monotonic())
        timer = threading.Timer(remaining, _expire)
        timer.daemon = True
        timer.start()
        try:
            chunks = []
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    chunks.append(chunk)
                if timed_out.is_set() or time.monotonic() >= wall_deadline:
                    raise requests.Timeout("AI provider exceeded its total deadline")
            if timed_out.is_set() or time.monotonic() >= wall_deadline:
                raise requests.Timeout("AI provider exceeded its total deadline")
            resp._content = b"".join(chunks)
            resp._content_consumed = True
            return resp
        except (requests.RequestException, AttributeError, OSError, ValueError):
            if timed_out.is_set():
                raise requests.Timeout("AI provider exceeded its total deadline")
            raise
        finally:
            timer.cancel()
            resp.close()


def _call_openrouter(model_id, system_prompt, user_text):
    """One OpenRouter attempt. Returns (True, reply_text) or (False, error)."""
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
               "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}]
    for use_json_mode in (True, False):
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 2048,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = _post(
                config.OPENROUTER_URL, headers=headers, json=payload)
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
        "generationConfig": {"temperature": 0,
                             "maxOutputTokens": 2048,
                             "responseMimeType": "application/json"},
    }
    for use_json in (True, False):
        if not use_json:
            body.pop("generationConfig", None)
        try:
            resp = _post(url, headers=headers, json=body)
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


def _call_groq(model_id, system_prompt, user_text):
    """One Groq attempt. Returns (True, reply_text) or (False, error)."""
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}",
               "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}]
    for use_json_mode in (True, False):
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 2048,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = _post(
                config.GROQ_URL, headers=headers, json=payload)
        except requests.RequestException as err:
            return False, f"network error: {err}"
        if resp.status_code == 429:
            return False, "429 rate limited"
        if resp.status_code == 400 and use_json_mode:
            continue                        # retry same model without json mode
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        try:
            return True, resp.json()["choices"][0]["message"]["content"]
        except (KeyError, ValueError) as err:
            return False, f"unexpected response shape: {err}"
    return False, "request rejected"


def _track_provider_call(provider, model, fn):
    global _CURRENT_ACTIVE_MODEL
    _CURRENT_ACTIVE_MODEL = f"{provider}/{model}"
    return fn()


def _provider_registry():
    """Build provider objects around the existing transport functions."""
    registry = AIProviderFactoryRegistry()
    registry.register(
        "openrouter",
        lambda model: OpenRouterAIProvider(
            model,
            lambda system_prompt, text, selected=model:
            _track_provider_call(
                "openrouter", selected,
                lambda: _call_openrouter(selected, system_prompt, text)),
        ),
    )
    registry.register(
        "gemini",
        lambda model: GeminiAIProvider(
            model,
            lambda system_prompt, text, selected=model:
            _track_provider_call(
                "gemini", selected,
                lambda: _call_gemini(selected, system_prompt, text)),
        ),
    )
    registry.register(
        "groq",
        lambda model: GroqAIProvider(
            model,
            lambda system_prompt, text, selected=model:
            _track_provider_call(
                "groq", selected,
                lambda: _call_groq(selected, system_prompt, text)),
        ),
    )
    return registry


def _provider_is_configured(provider):
    return (
        provider == "openrouter" and bool(config.OPENROUTER_API_KEY)
        or provider == "gemini" and bool(config.GEMINI_API_KEY)
        or provider == "groq" and bool(config.GROQ_API_KEY)
    )


def _provider_objects(configured_only=False):
    registry = _provider_registry()
    providers = []
    for entry in config.MODEL_CHAIN:
        provider, model = entry["provider"], entry["model"]
        if configured_only and not _provider_is_configured(provider):
            continue
        configured = registry.create(provider, model)
        providers.append(
            configured or UnsupportedAIProvider(provider, model))
    return providers


def call_ai(user_record):
    """Walk MODEL_CHAIN across providers until one returns schema-valid JSON.
    Returns (True, parsed_dict, model_used) or (False, error_summary, None)."""
    user_text = build_prompt(user_record)
    return AIProviderRouter(
        _provider_objects(),
        parse_json_reply,
        validate_ai_output,
        _safe_failure,
        _log_ai_event,
        time.sleep,
    ).route(SYSTEM_PROMPT, user_text)


def call_api(prompt):
    """Send one prepared BRNS record through the configured AI chain."""
    return call_ai(prompt)


def parse_response(raw):
    """Parse a raw BRNS AI JSON response."""
    return parse_json_reply(raw)


def validate_response(data):
    """Validate a parsed BRNS interpretation response."""
    return validate_ai_output(data)


REASON_CODES = {
    "cuisine_match", "within_budget", "within_route", "well_rated",
    "vegetarian_options", "halal_hint_unofficial", "spicy_options",
}

RECOMMEND_SYSTEM_PROMPT = """Rank every supplied restaurant candidate for the
validated search request. Return only JSON in this exact shape:
{"recommendations":[{"id":0,"reason_codes":["cuisine_match"]}]}.
Include every candidate ID exactly once, most suitable first. Use only these
reason codes when supported by the supplied facts: cuisine_match,
within_budget, within_route, well_rated, vegetarian_options,
halal_hint_unofficial, spicy_options. Use [] if no code is supported.
Treat other_preferences as the strongest part of the search. Google text
search already uses their complete wording, so use that wording when ordering
candidates. google_search_rank preserves Google's text-query relevance for
free-text wishes such as spicy food; prefer that evidence for requests not
covered by another candidate fact. Words such as only, must, exclusively, minimum, and at least mark
hard constraints. A bare rating such as "4.5 stars" is a soft preference.
When hard_preferences is true, prioritize the hard request ahead of budget
and travel because those two limits are relaxed by Logic.
minimum_rating is a hard minimum Google star rating extracted from the user's
other preferences. Put candidates below it or without a rating after those
that meet it. The next layer will enforce the minimum.
For candidates that satisfy the hard requirements, weigh Google review count
alongside the star rating. Use confidence_adjusted_rating to compare rating
quality: it shrinks ratings with few reviews toward 4/5 using 100 prior
reviews. For example, 4.3 stars from 1,920 reviews is stronger evidence than
4.5 stars from 75 reviews. Prefer the former when their other facts are similar
and no minimum excludes it. A missing review count provides weak evidence.
When previous_restaurants is supplied, prefer suitable candidates not named
there over similarly suitable candidates already returned. Include every ID.
Use within_budget only when avg_price is a number no greater than the user's
budget. price_start alone does not prove a meal fits the budget.
Use vegetarian_options only when vegetarian is requested and listed in the
candidate dietary_requirements. Use halal_hint_unofficial only when halal is
requested and the candidate has halal_hint_unofficial true.
Use cuisine_match only when the requested cuisine is in candidate cuisines.
When the requested cuisine is none, never use cuisine_match.
Use within_route only for a verified route within the chosen distance or
journey-time limit. Check the selected limit field, not the other route metric.
Do not invent restaurant facts or claim official halal certification.
The next layer will verify every reason and enforce hard requirements."""


def has_configured_provider():
    """Check credentials before BRNS spends a Places request."""
    return manager().has_configured_provider()


def _validate_recommendation_output(reply, candidate_count):
    """Validate recommendation JSON for the provider router."""
    if not isinstance(reply, dict) or set(reply) != {"recommendations"}:
        return False, "wrong keys"
    recommendations = reply["recommendations"]
    valid = (
        isinstance(recommendations, list)
        and len(recommendations) == candidate_count
        and all(
            isinstance(item, dict)
            and set(item) == {"id", "reason_codes"}
            and type(item["id"]) is int
            and 0 <= item["id"] < candidate_count
            and isinstance(item["reason_codes"], list)
            and all(
                isinstance(code, str) and code in REASON_CODES
                for code in item["reason_codes"])
            and len(item["reason_codes"]) == len(set(item["reason_codes"]))
            for item in recommendations)
        and len({item["id"] for item in recommendations}) == candidate_count
    )
    return (
        (True, recommendations)
        if valid else (False, "invalid schema"))


def _recommend_candidates(request, candidates, previous_restaurants=()):
    """Legacy request API; prepare domain facts outside the AI implementation."""
    if not candidates:
        return None
    context = logic_manager.manager().recommendation_context(
        request, candidates, previous_restaurants)
    return _recommend_prepared(context, len(candidates))


def _recommend_prepared(context, candidate_count):
    """Send prepared facts and validate model output without evaluating rules."""
    _log_ai_event("recommend_candidates",
                  f"Preparing {candidate_count} candidate summaries.", "INFO")
    _log_ai_event("recommend_candidates", "Candidate facts sent to model: "
                  + json.dumps(context["candidates"], ensure_ascii=False,
                               separators=(",", ":")), "DEBUG")
    user_text = json.dumps(context, separators=(",", ":"))
    router = AIProviderRouter(
        _provider_objects(configured_only=True),
        parse_json_reply,
        lambda reply: _validate_recommendation_output(
            reply, candidate_count),
        _safe_failure,
        _log_ai_event,
        time.sleep,
    )
    ok, result, model_used = router.route(
        RECOMMEND_SYSTEM_PROMPT, user_text)
    if ok:
        _LAST_USED_MODEL.set(model_used)
        _log_ai_event(
            "recommend_candidates",
            f"Accepted {model_used} response.", "INFO")
        _log_ai_event(
            "recommend_candidates",
            "AI recommendation: " + json.dumps(
                result, separators=(",", ":")), "DEBUG")
        return result
    _log_ai_event("recommend_candidates", "No model returned a valid order.")
    return None


def recommend_candidates(request, candidates, previous_restaurants=()):
    """Rank candidates while enforcing one deadline across all providers."""
    return manager().recommend_candidates(
        request, candidates, previous_restaurants)


def last_used_model():
    return _LAST_USED_MODEL.get()


def current_active_model():
    """Return the active/most-recent configured AI provider label."""
    if _CURRENT_ACTIVE_MODEL:
        return _CURRENT_ACTIVE_MODEL
    for entry in getattr(config, "MODEL_CHAIN", []):
        provider = entry.get("provider", "")
        model = entry.get("model", "")
        if provider == "gemini" and getattr(config, "GEMINI_API_KEY", ""):
            return f"{provider}/{model}"
        if provider == "openrouter" and getattr(config, "OPENROUTER_API_KEY", ""):
            return f"{provider}/{model}"
        if provider == "groq" and getattr(config, "GROQ_API_KEY", ""):
            return f"{provider}/{model}"
    return "Gemini AI"
