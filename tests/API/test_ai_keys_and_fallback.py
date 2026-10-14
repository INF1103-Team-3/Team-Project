"""Tests for AI API keys connectivity and multi-provider fallback chains.

Covers:
1. Direct API key validation for OpenRouter, Gemini, and Groq.
2. BIS AI fallback chain:
   - Live execution with primary provider.
   - Fallback activation when primary provider fails (simulated outage).
   - Multi-tier fallback cascade (primary + secondary failure).
   - Graceful error handling when all providers are exhausted.
3. BRNS AI fallback chain:
   - Live recommendation ranking execution.
   - Fallback activation when primary model fails.
   - Graceful return of None when all providers in MODEL_CHAIN fail.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv
import requests

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

# Ensure project and manager modules can be imported
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(ROOT / "BRNS"))
sys.path.insert(0, str(TESTS_ROOT))

# Load .env explicitly for live API credentials
load_dotenv(ROOT / ".env")

from reporting import show_case, show_summary, style
import BIS.ai_manager as bis_ai
sys.modules["ai_manager"] = bis_ai
import BIS.support.config as bis_config
import BRNS.ai_manager as brns_ai
import BRNS.config as brns_config
from shared.groq_models import fetch_chat_models


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SEARCH_REQUEST = {
    "cuisine": "japanese",
    "disliked_cuisines": [],
    "dietary_requirements": [],
    "budget_per_person": 30.0,
    "other_preferences": ["quiet atmosphere"],
    "mode": "walk",
    "max_travel_minutes": 20,
    "max_distance_km": None,
    "traffic_aware": False,
}

SAMPLE_CANDIDATES = [
    {
        "name": "Ichiban Bento",
        "cuisines": ["japanese"],
        "dietary_requirements": [],
        "halal_hint": False,
        "avg_price": 18.0,
        "price_start": 12.0,
        "rating": 4.4,
        "rating_count": 210,
        "google_search_rank": 1,
        "spicy_options": False,
        "walk_meters": 450,
        "walk_minutes": 6,
        "walk_source": "google_routes",
    },
    {
        "name": "Sakura Japanese Dining",
        "cuisines": ["japanese"],
        "dietary_requirements": [],
        "halal_hint": False,
        "avg_price": 28.0,
        "price_start": 20.0,
        "rating": 4.6,
        "rating_count": 520,
        "google_search_rank": 2,
        "spicy_options": False,
        "walk_meters": 750,
        "walk_minutes": 10,
        "walk_source": "google_routes",
    },
]


# ---------------------------------------------------------------------------
# Part 1: Individual Key Connectivity
# ---------------------------------------------------------------------------

def test_openrouter_api_key_connectivity():
    """Verify that OPENROUTER_API_KEY is valid and can generate text."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        actual = {"status": "SKIPPED", "reason": "OPENROUTER_API_KEY not set in .env"}
        expected = deepcopy(actual)
        show_case(
            "API-AI-01: OpenRouter API Key Connectivity",
            "openrouter.ai/api/v1/chat/completions",
            "Verify OpenRouter API key authentication and minimal chat completion.",
            {"api_key_present": False},
            expected,
            actual,
        )
        return

    model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    url = f"{os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "BiteFinder-APITest",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Return the single word OK."}
        ],
        "temperature": 0,
        "max_tokens": 15,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        is_ok = resp.status_code == 200
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") if is_ok else resp.text
        actual = {
            "status_code": resp.status_code,
            "has_content": bool(content.strip()),
            "authenticated": is_ok,
        }
    except Exception as err:
        actual = {"error": str(err), "authenticated": False}

    expected = {"status_code": 200, "has_content": True, "authenticated": True}

    show_case(
        "API-AI-01: OpenRouter API Key Connectivity",
        "openrouter.ai/api/v1/chat/completions",
        "Verify OpenRouter API key authentication and minimal chat completion.",
        {"provider": "openrouter", "model": model},
        expected,
        actual,
    )
    assert actual == expected


def test_gemini_api_key_connectivity():
    """Verify that GEMINI_API_KEY is valid and can generate text."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        actual = {"status": "SKIPPED", "reason": "GEMINI_API_KEY not set in .env"}
        expected = deepcopy(actual)
        show_case(
            "API-AI-02: Google Gemini API Key Connectivity",
            "generativelanguage.googleapis.com",
            "Verify Gemini API key authentication and generateContent response.",
            {"api_key_present": False},
            expected,
            actual,
        )
        return

    # Test with standard flash or lite model
    model = "gemini-3.5-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": key,
        "Content-Type": "application/json",
    }
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": "Return the single word OK."}]}
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 15},
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        is_ok = resp.status_code == 200
        if is_ok:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
        else:
            text = resp.text
        actual = {
            "status_code": resp.status_code,
            "has_content": bool(text.strip()),
            "authenticated": is_ok,
        }
    except Exception as err:
        actual = {"error": str(err), "authenticated": False}

    expected = {"status_code": 200, "has_content": True, "authenticated": True}

    show_case(
        "API-AI-02: Google Gemini API Key Connectivity",
        "generativelanguage.googleapis.com",
        "Verify Gemini API key authentication and generateContent response.",
        {"provider": "gemini", "model": model},
        expected,
        actual,
    )
    assert actual == expected


def test_groq_api_key_connectivity():
    """Verify that GROQ_API_KEY is valid and can discover models and generate text."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        actual = {"status": "SKIPPED", "reason": "GROQ_API_KEY not set in .env"}
        expected = deepcopy(actual)
        show_case(
            "API-AI-03: Groq API Key Connectivity",
            "api.groq.com/openai/v1/chat/completions",
            "Verify Groq API key authentication and model discovery.",
            {"api_key_present": False},
            expected,
            actual,
        )
        return

    models = fetch_chat_models(key)
    model = models[0] if models else "llama-3.1-8b-instant"

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Return the single word OK."}
        ],
        "temperature": 0,
        "max_tokens": 100,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        is_ok = resp.status_code == 200
        msg = resp.json().get("choices", [{}])[0].get("message", {}) if is_ok else {}
        content = msg.get("content", "") or msg.get("reasoning", "")
        actual = {
            "status_code": resp.status_code,
            "has_content": bool(content.strip()),
            "models_discovered": len(models) > 0,
            "authenticated": is_ok,
        }
    except Exception as err:
        actual = {"error": str(err), "authenticated": False, "models_discovered": False}

    expected = {
        "status_code": 200,
        "has_content": True,
        "models_discovered": True,
        "authenticated": True,
    }

    show_case(
        "API-AI-03: Groq API Key Connectivity",
        "api.groq.com/openai/v1/chat/completions",
        "Verify Groq API key authentication, model discovery, and chat completion.",
        {"provider": "groq", "model": model, "models_found": len(models)},
        expected,
        actual,
    )
    assert actual == expected


# ---------------------------------------------------------------------------
# Part 2: BIS AI Fallback Chain Tests
# ---------------------------------------------------------------------------

def test_bis_fallback_chain_normal_execution():
    """Verify that BIS AI executes successfully using the configured fallback pipeline."""
    config = bis_config.load_config()
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "Return valid JSON with key 'status' set to 'ok' and key 'app' set to 'BiteFinder'.",
            },
            {"role": "user", "content": "Return the JSON."},
        ],
        "temperature": 0,
    }

    result = bis_ai._call_json_with_fallback(payload, config)
    actual = {
        "is_dict": isinstance(result, dict),
        "has_status": "status" in result,
    }
    expected = {"is_dict": True, "has_status": True}

    show_case(
        "API-AI-04: BIS Fallback Chain Normal Execution",
        "BIS.ai_manager._call_json_with_fallback()",
        "Test that BIS obtains valid JSON through its configured model pipeline.",
        {"configured_primary": config.get("openrouter_model")},
        expected,
        actual,
    )
    assert actual == expected


def test_bis_fallback_activates_on_primary_failure():
    """Verify that BIS smoothly falls back to secondary provider when primary fails."""
    config = bis_config.load_config()
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "Return valid JSON with key 'fallback' set to true.",
            },
            {"role": "user", "content": "Generate JSON."},
        ],
        "temperature": 0,
    }

    # Simulate primary OpenRouter failure
    with patch("BIS.ai_manager._call_openrouter", side_effect=RuntimeError("Simulated primary failure")):
        result = bis_ai._call_json_with_fallback(payload, config)

    actual = {
        "is_dict": isinstance(result, dict),
        "fallback_succeeded": isinstance(result, dict) and len(result) > 0,
    }
    expected = {"is_dict": True, "fallback_succeeded": True}

    show_case(
        "API-AI-05: BIS Fallback Activation On Primary Failure",
        "BIS.ai_manager._call_json_with_fallback()",
        "Simulate OpenRouter primary outage and assert automatic fallback to Gemini/Groq.",
        {"simulated_failure": "OpenRouter RuntimeError"},
        expected,
        actual,
    )
    assert actual == expected


def test_bis_fallback_cascades_multi_tier():
    """Verify that BIS cascades down to tertiary provider when first two fail."""
    config = bis_config.load_config()
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "Return valid JSON with key 'tier' set to 3.",
            },
            {"role": "user", "content": "Generate JSON."},
        ],
        "temperature": 0,
    }

    # Simulate failure on OpenRouter and Gemini, forcing Groq (or subsequent model)
    with patch("BIS.ai_manager._call_openrouter", side_effect=RuntimeError("Simulated primary failure")), \
         patch("BIS.ai_manager._call_gemini", side_effect=RuntimeError("Simulated secondary failure")):
        result = bis_ai._call_json_with_fallback(payload, config)

    actual = {
        "is_dict": isinstance(result, dict),
        "tier_3_succeeded": isinstance(result, dict) and len(result) > 0,
    }
    expected = {"is_dict": True, "tier_3_succeeded": True}

    show_case(
        "API-AI-06: BIS Multi-Tier Fallback Cascade",
        "BIS.ai_manager._call_json_with_fallback()",
        "Simulate OpenRouter and Gemini failures and assert fallback to tertiary provider.",
        {"simulated_failures": ["OpenRouter", "Gemini"]},
        expected,
        actual,
    )
    assert actual == expected


def test_bis_fallback_graceful_exhaustion():
    """Verify that BIS raises RuntimeError safely when all fallback models fail."""
    config = bis_config.load_config()
    payload = {
        "messages": [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "JSON"},
        ],
    }

    with patch("BIS.ai_manager._call_openrouter", side_effect=RuntimeError("Simulated failure")), \
         patch("BIS.ai_manager._call_gemini", side_effect=RuntimeError("Simulated failure")), \
         patch("BIS.ai_manager._call_groq", side_effect=RuntimeError("Simulated failure")):
        try:
            bis_ai._call_json_with_fallback(payload, config)
            actual = "no_error"
        except RuntimeError as err:
            actual = "BIS AI models are unavailable" in str(err)

    expected = True

    show_case(
        "API-AI-07: BIS Fallback Graceful Exhaustion",
        "BIS.ai_manager._call_json_with_fallback()",
        "Simulate failure across all providers and assert clear user-facing error.",
        {"simulated_failures": "ALL_PROVIDERS"},
        expected,
        actual,
    )
    assert actual is True


# ---------------------------------------------------------------------------
# Part 3: BRNS AI Fallback Chain Tests
# ---------------------------------------------------------------------------

def test_brns_candidate_ranking_normal_execution():
    """Verify that BRNS candidate ranking executes successfully with live models."""
    recommendation = brns_ai.recommend_candidates(SAMPLE_SEARCH_REQUEST, SAMPLE_CANDIDATES)

    actual = {
        "is_list": isinstance(recommendation, list),
        "candidate_count": len(recommendation) if isinstance(recommendation, list) else 0,
        "has_reasons": bool(
            recommendation
            and isinstance(recommendation[0], dict)
            and ("reason_codes" in recommendation[0] or "reasons" in recommendation[0])
        ),
    }
    expected = {
        "is_list": True,
        "candidate_count": len(SAMPLE_CANDIDATES),
        "has_reasons": True,
    }

    show_case(
        "API-AI-08: BRNS Candidate Ranking Live Execution",
        "BRNS.ai_manager.recommend_candidates()",
        "Test candidate ranking and reason code generation using live model chain.",
        {"candidate_count": len(SAMPLE_CANDIDATES)},
        expected,
        actual,
    )
    assert actual == expected


def test_brns_fallback_activates_on_provider_failure():
    """Verify that BRNS cascades to next model in MODEL_CHAIN when first model fails."""
    # Patch the first provider in BRNS MODEL_CHAIN (gemini) to fail with rate limit
    with patch("BRNS.ai_manager._call_gemini", return_value=(False, "429 rate limited")):
        recommendation = brns_ai.recommend_candidates(SAMPLE_SEARCH_REQUEST, SAMPLE_CANDIDATES)

    actual = {
        "is_list": isinstance(recommendation, list),
        "candidate_count": len(recommendation) if isinstance(recommendation, list) else 0,
        "fallback_succeeded": bool(recommendation),
    }
    expected = {
        "is_list": True,
        "candidate_count": len(SAMPLE_CANDIDATES),
        "fallback_succeeded": True,
    }

    show_case(
        "API-AI-09: BRNS Fallback Activation On Provider Outage",
        "BRNS.ai_manager.recommend_candidates()",
        "Simulate 429 quota exhaustion on primary model and assert fallback recovery.",
        {"simulated_failure": "Gemini 429 rate limited"},
        expected,
        actual,
    )
    assert actual == expected


def test_brns_fallback_exhaustion_returns_none():
    """Verify that BRNS returns None gracefully when every model in MODEL_CHAIN fails."""
    with patch("BRNS.ai_manager._call_gemini", return_value=(False, "HTTP 500")), \
         patch("BRNS.ai_manager._call_openrouter", return_value=(False, "HTTP 500")), \
         patch("BRNS.ai_manager._call_groq", return_value=(False, "HTTP 500")):
        recommendation = brns_ai.recommend_candidates(SAMPLE_SEARCH_REQUEST, SAMPLE_CANDIDATES)

    actual = recommendation is None
    expected = True

    show_case(
        "API-AI-10: BRNS Fallback Total Exhaustion",
        "BRNS.ai_manager.recommend_candidates()",
        "Simulate failure across all BRNS providers and assert graceful None return.",
        {"simulated_failures": "ALL_BRNS_MODELS"},
        expected,
        actual,
    )
    assert actual is True


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

TESTS = (
    test_openrouter_api_key_connectivity,
    test_gemini_api_key_connectivity,
    test_groq_api_key_connectivity,
    test_bis_fallback_chain_normal_execution,
    test_bis_fallback_activates_on_primary_failure,
    test_bis_fallback_cascades_multi_tier,
    test_bis_fallback_graceful_exhaustion,
    test_brns_candidate_ranking_normal_execution,
    test_brns_fallback_activates_on_provider_failure,
    test_brns_fallback_exhaustion_returns_none,
)


def run_tests():
    """Run all AI API key connectivity and fallback tests."""
    failures = []
    print("\n" + style("#" * 72, "rule"))
    print(style("BITEFINDER - AI API KEYS & FALLBACK CHAIN TESTS", "heading"))
    print(style("#" * 72, "rule"))

    for test in TESTS:
        try:
            test()
        except Exception as error:
            failures.append((test.__name__, error))
            print(f"\n{style('FAILED:', 'fail')} {test.__name__}: {error}")

    show_summary("AI API KEYS & FALLBACK", len(TESTS), failures)
    return len(failures)


if __name__ == "__main__":
    sys.exit(run_tests())
