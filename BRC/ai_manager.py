"""Procedural Gemini adapter for BRC cuisine and outlet processing."""

from __future__ import annotations

import json
import os
import re
import time

import requests

from shared import debug_log


CUISINES = (
    "chinese", "malay", "indian", "peranakan", "indonesian", "thai",
    "vietnamese", "filipino", "japanese", "korean", "western", "italian",
    "french", "american", "mexican", "turkish", "middle eastern",
    "mediterranean", "fusion", "lebanese",
)


def create_manager(api_key, model):
    """Create BRC's independent Gemini, OpenRouter, and Groq chain."""
    try:
        interval = float(os.getenv("BRC_AI_REQUEST_INTERVAL_SECONDS", "4.2"))
    except ValueError:
        interval = 4.2
    try:
        timeout = float(os.getenv("BRC_AI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        timeout = 20.0
    try:
        chain_timeout = float(os.getenv("BRC_AI_CHAIN_TIMEOUT_SECONDS", "45"))
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
        configured = os.getenv(
            "BRC_GROQ_MODEL", "openai/gpt-oss-20b").strip()
        groq_models = [configured] if configured else []
        from shared.groq_models import fetch_chat_models
        for model_id in fetch_chat_models(groq_key):
            if model_id not in groq_models:
                groq_models.append(model_id)
        providers.extend(
            {"provider": "groq", "model": model_id}
            for model_id in groq_models)
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


def build_prompt(record):
    """Serialize one BRC record into the JSON portion of an AI prompt."""
    if not isinstance(record, dict):
        raise ValueError("BRC AI prompt input must be a record dictionary.")
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def parse_response(raw, object_ok=False):
    """Decode a JSON response, tolerating Markdown JSON fences."""
    value = json.loads(re.sub(r"```(?:json)?", "", raw).strip())
    if object_ok and isinstance(value, dict):
        return value
    if not isinstance(value, list):
        raise ValueError("BRC AI response has the wrong shape.")
    return value


def validate_response(data, *, expected_ids=None, object_keys=None):
    """Validate the response shape before BRC Logic receives it."""
    if object_keys is not None:
        return isinstance(data, dict) and set(data) == set(object_keys)
    if not isinstance(data, list):
        return False
    if expected_ids is None:
        return True
    identifiers = [item.get("index") for item in data
                   if isinstance(item, dict)]
    return len(data) == len(expected_ids) and set(identifiers) == set(expected_ids)


def process(context, manager):
    """Process BRC input through AI and return structured proposals."""
    manager["report"] = context.get("report")
    if context["scenario"] == "build_database":
        return {"cuisines": _tag_cuisines(
            context["raw_snapshot"]["listings"], context.get("report"),
            context.get("cuisine_cache"), context.get("save_cuisine_cache"),
            manager=manager)}
    return {"matches": _match(
        context["records"], context["candidates"], context.get("report"),
        manager=manager)}


def _tag_cuisines(rows, report=None, cache=None, save_cache=None,
                  manager=None, request=None):
    """Tag cuisines and checkpoint every completed AI batch."""
    from BRC import data_manager

    cache = cache if cache is not None else {}
    result, pending = [[] for _ in rows], []
    keywords = {
        "malay": "malay", "nasi": "malay", "chicken rice": "chinese",
        "chinese": "chinese", "indian": "indian", "biryani": "indian",
        "japanese": "japanese", "sushi": "japanese", "korean": "korean",
        "thai": "thai", "western": "western", "pizza": "italian",
    }
    for index, row in enumerate(rows):
        cache_key = data_manager.cuisine_cache_key(row)
        if cache_key in cache:
            result[index] = list(cache[cache_key])
            continue
        text = f"{row.get('name', '')} {row.get('category', '')}".casefold()
        tags = sorted({tag for word, tag in keywords.items() if word in text})
        if tags:
            result[index] = tags
            cache[cache_key] = list(tags)
        else:
            pending.append((index, row))
    cached_count = len(rows) - len(pending)
    if report and cached_count:
        report(f"AI: reused or derived {cached_count} cached cuisine tags; "
               f"{len(pending)} still need AI.")
    if save_cache:
        save_cache(cache)
    try:
        batch_size = int(os.getenv("BRC_AI_BATCH_SIZE", "100"))
    except ValueError:
        batch_size = 100
    batch_size = min(max(batch_size, 1), 200)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        if report:
            report(f"AI: tagging cuisines for restaurants "
                   f"{start + 1}–{start + len(batch)} of {len(pending)} "
                   f"(currently {batch[0][1].get('name', 'unknown')})")
        prompt = (
            "Tag every restaurant with zero or more allowed cuisines. Generic "
            "words such as restaurant are not cuisines. Return only a JSON "
            "array of {index,cuisines}. Allowed: " + ", ".join(CUISINES) + "\n"
            + json.dumps([{"index": index, "name": row.get("name"),
                           "category": row.get("category")}
                          for index, row in batch]))
        allowed = {index for index, _row in batch}

        def valid_cuisine_reply(raw):
            try:
                proposed = parse_response(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
            return (
                validate_response(proposed, expected_ids=allowed)
                and all(
                    isinstance(item, dict)
                    and set(item) == {"index", "cuisines"}
                    and item["index"] in allowed
                    and isinstance(item["cuisines"], list)
                    for item in proposed
                )
            )

        raw = (request(prompt) if request else
               call_api(prompt, manager, validator=valid_cuisine_reply))
        parsed = parse_response(raw)
        if not validate_response(parsed, expected_ids=allowed):
            raise ValueError("BRC AI omitted or duplicated cuisine rows.")
        for item in parsed:
            if (not isinstance(item, dict)
                    or set(item) != {"index", "cuisines"}
                    or item["index"] not in allowed
                    or not isinstance(item["cuisines"], list)):
                raise ValueError("BRC AI returned invalid cuisine tags.")
            normalized = []
            for tag in item["cuisines"]:
                if not isinstance(tag, str):
                    continue
                tag = re.sub(r"\s+", " ", tag.strip().casefold())
                if tag in CUISINES and tag not in normalized:
                    normalized.append(tag)
            result[item["index"]] = normalized
            cache[data_manager.cuisine_cache_key(rows[item["index"]])] = list(
                normalized)
        if save_cache:
            save_cache(cache)
    return result


def _match(records, groups, report=None, manager=None, request=None):
    """Return the certificate selected for each candidate group."""
    output = []
    for index, (record, candidates) in enumerate(zip(records, groups), 1):
        if report:
            report(f"AI: checking restaurant {index} of {len(records)} "
                   f"({record.get('name', 'unknown')})")
        if not candidates:
            output.append(None)
            continue
        from BRC import logic_manager
        exact = [row for row in candidates if logic_manager._same(record, row)]
        if len(exact) == 1:
            output.append(exact[0]["muis"]["certificate_number"])
            continue
        prompt = (
            "Select the exact same outlet or null. Branch and unit must agree. "
            "Return only {\"certificate_number\": string|null}.\n"
            + json.dumps({"restaurant": record, "candidates": candidates}))
        allowed = {row["muis"]["certificate_number"] for row in candidates}

        def valid_match_reply(raw):
            try:
                proposed = parse_response(raw, object_ok=True)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
            return (
                validate_response(
                    proposed, object_keys={"certificate_number"})
                and proposed["certificate_number"] in allowed | {None}
            )

        raw = (request(prompt) if request else
               call_api(prompt, manager, validator=valid_match_reply))
        item = parse_response(raw, object_ok=True)
        if not validate_response(item, object_keys={"certificate_number"}):
            raise ValueError(
                f"BRC AI returned an invalid match for restaurant {index}.")
        certificate = item["certificate_number"]
        if certificate not in allowed | {None}:
            raise ValueError(
                f"BRC AI invented a match for restaurant {index}.")
        output.append(certificate)
    return output


def _pace_request(manager):
    if manager["last_request_at"] is None:
        return
    remaining = manager["request_interval"] - (
        time.monotonic() - manager["last_request_at"])
    if remaining > 0:
        time.sleep(remaining)


def _retry_delay(error, attempt):
    match = re.search(
        r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
        str(error), re.IGNORECASE)
    supplied = float(match.group(1)) if match else 0.0
    return max(supplied, 4.2 * (attempt + 1))


def _call_gemini(prompt, manager, model):
    """Call one Gemini model with rate-limit recovery."""
    from google import genai
    from google.genai import types

    if manager["client"] is None:
        manager["client"] = genai.Client(
            api_key=manager["api_key"],
            http_options=types.HttpOptions(
                timeout=int(manager["timeout_seconds"] * 1000)))
    for attempt in range(5):
        _pace_request(manager)
        manager["last_request_at"] = time.monotonic()
        try:
            response = manager["client"].models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0, response_mime_type="application/json"))
        except Exception as error:
            alternatives_available = len(manager.get("providers", [])) > 1
            if (getattr(error, "code", None) != 429 or attempt == 4
                    or alternatives_available):
                raise
            delay = _retry_delay(error, attempt)
            if manager["report"]:
                manager["report"](
                    f"AI: Gemini rate limit reached; retrying in "
                    f"{delay:g} seconds...")
            time.sleep(delay)
            continue
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text
    raise RuntimeError("Gemini rate-limit retries were exhausted.")


def _call_chat_completions(prompt, manager, provider, model, timeout):
    """Call one OpenAI-compatible OpenRouter or Groq model."""
    if provider == "openrouter":
        url = os.getenv(
            "BITEFINDER_OPENROUTER_URL",
            "https://openrouter.ai/api/v1/chat/completions")
        key = manager["openrouter_api_key"]
    else:
        url = os.getenv(
            "BITEFINDER_GROQ_URL",
            "https://api.groq.com/openai/v1/chat/completions")
        key = manager["groq_api_key"]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4096,
    }
    _pace_request(manager)
    manager["last_request_at"] = time.monotonic()
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json=body,
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


def _valid_json_text(raw):
    """Require a JSON object or array before accepting a provider reply."""
    try:
        value = json.loads(re.sub(r"```(?:json)?", "", raw).strip())
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(value, (dict, list))


def call_api(prompt, manager, validator=None):
    """Try BRC's provider chain until valid structured output is returned."""
    if manager is None:
        raise ValueError("BRC AI manager state is required.")
    deadline = time.monotonic() + manager["chain_timeout_seconds"]
    failures = []
    for entry in manager["providers"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures.append("provider chain deadline reached")
            break
        provider, model = entry["provider"], entry["model"]
        debug_log.debug_log(
            f"BRC trying {provider}/{model}.",
            "INFO", "BRC.ai_manager.fallback")
        try:
            if provider == "gemini":
                raw = _call_gemini(prompt, manager, model)
            elif provider in {"openrouter", "groq"}:
                raw = _call_chat_completions(
                    prompt, manager, provider, model,
                    min(manager["timeout_seconds"], remaining))
            else:
                continue
        except Exception as error:
            failures.append(f"{provider}/{model}: {type(error).__name__}")
            debug_log.debug_log(
                f"BRC {provider}/{model} failed with "
                f"{type(error).__name__}; trying the next provider.",
                "WARNING", "BRC.ai_manager.fallback")
            continue
        if not _valid_json_text(raw) or validator and not validator(raw):
            failures.append(f"{provider}/{model}: invalid response")
            debug_log.debug_log(
                f"BRC {provider}/{model} returned invalid structured data; "
                "trying the next provider.",
                "WARNING", "BRC.ai_manager.fallback")
            continue
        debug_log.debug_log(
            f"BRC accepted {provider}/{model} response.",
            "INFO", "BRC.ai_manager.fallback")
        return raw
    raise RuntimeError(
        "BRC AI providers are unavailable or returned invalid data: "
        + "; ".join(failures))
