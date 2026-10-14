# BiteFinder Live API & Fallback Chain Tests

This directory contains automated live validation tests for all external API keys used by BiteFinder (`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, and `GOOGLE_MAPS_API_KEY`), as well as comprehensive verification of the multi-provider AI fallback chain and Google offline fallback resilience.

---

## Directory Map

| Script | Purpose |
| --- | --- |
| `test_ai_keys_and_fallback.py` | Direct API key connectivity for OpenRouter, Gemini, and Groq, plus multi-tier fallback cascade and exhaustion testing for both BIS and BRNS. |
| `test_google_api.py` | Dedicated tests for Google Maps Platform: Geocoding, Places (New), Routes (New), Geocode Caching, invalid key rejection, and offline restaurant fallback. |
| `run_api_tests.py` | Master runner executing both test suites with colored teacher-facing test case reporting and summary metrics. |

---

## What Is Tested

### 1. AI API Keys & Fallback Chain (`test_ai_keys_and_fallback.py`)

- **API-AI-01: OpenRouter API Key Connectivity**
  - Sends a minimal chat completion request to `https://openrouter.ai/api/v1/chat/completions`.
  - Verifies HTTP 200, valid JSON response, and presence of generated text.
- **API-AI-02: Google Gemini API Key Connectivity**
  - Sends a minimal `generateContent` request to `generativelanguage.googleapis.com` with `x-goog-api-key`.
  - Verifies HTTP 200 and text generation.
- **API-AI-03: Groq API Key Connectivity & Model Discovery**
  - Queries Groq active text models via `fetch_chat_models()`.
  - Sends a minimal chat completion request to `api.groq.com/openai/v1/chat/completions`.
  - Verifies authentication and response generation.
- **API-AI-04: BIS Fallback Chain Normal Execution**
  - Calls `BIS.ai_manager._call_json_with_fallback()` with real config and verifies valid structured output.
- **API-AI-05: BIS Fallback Activation On Primary Failure**
  - Simulates an OpenRouter primary failure (e.g., 429 quota exhaustion or network timeout).
  - Verifies that BIS automatically catches the exception, engages the secondary provider in `MODEL_CHAIN` (Gemini or Groq), and still successfully returns valid JSON.
- **API-AI-06: BIS Multi-Tier Fallback Cascade**
  - Simulates failure of both primary (OpenRouter) and secondary (Gemini) providers.
  - Verifies that BIS cascades down to tertiary providers (Groq) and returns valid JSON.
- **API-AI-07: BIS Fallback Graceful Exhaustion**
  - Simulates total failure across all providers.
  - Verifies that `RuntimeError("BIS AI models are unavailable")` is raised cleanly without crashing.
- **API-AI-08: BRNS Candidate Ranking Live Execution**
  - Feeds candidate restaurant facts into `BRNS.ai_manager.recommend_candidates()`.
  - Verifies that candidates are ranked with grounded `reason_codes`.
- **API-AI-09: BRNS Fallback Activation On Provider Outage**
  - Simulates an outage or quota limit on the first BRNS model.
  - Asserts that BRNS automatically cascades to the next provider in `MODEL_CHAIN` and returns ranked candidates.
- **API-AI-10: BRNS Fallback Total Exhaustion**
  - Simulates failure across all models in `MODEL_CHAIN`.
  - Asserts that BRNS returns `None` safely as specified by the recommendation contract.

---

### 2. Dedicated Google Maps Platform Tests (`test_google_api.py`)

- **API-GOOGLE-01: Google Geocoding API**
  - Geocodes a Singapore landmark (`"10 Bayfront Ave, Singapore 018956"`).
  - Asserts HTTP 200, status `OK`, and coordinates within the Singapore bounding box (`lat 1.15–1.48`, `lng 103.55–104.10`).
- **API-GOOGLE-02: Geocode Cache Integration**
  - Verifies `shared.geocode_cache.remember()` and `shared.geocode_cache.lookup()`.
  - Confirms cached coordinates are retrieved without hitting the network.
- **API-GOOGLE-03: Google Places API (New) Text Search**
  - Queries `places.googleapis.com/v1/places:searchText` with `X-Goog-Api-Key` and `X-Goog-FieldMask`.
  - Confirms places are returned with names, formatted addresses, and coordinates.
- **API-GOOGLE-04: Google Places API (New) Nearby Search**
  - Queries `places.googleapis.com/v1/places:searchNearby` with circular coordinate boundary around Singapore.
  - Confirms nearby eateries are returned.
- **API-GOOGLE-05: Google Routes API (New) Distance Matrix**
  - Computes route distance matrix via `routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix`.
  - Verifies distance meters and duration seconds are returned for walking travel mode.
- **API-GOOGLE-06: Google Routes API (New) Compute Routes**
  - Requests turn-by-turn directions via `routes.googleapis.com/directions/v2:computeRoutes`.
  - Verifies route calculation and polyline data.
- **API-GOOGLE-07: Invalid Google Key Error Handling**
  - Passes an invalid key to test API failure handling.
  - Verifies that BRNS catches the error safely, logs the rejection, and returns `None` without crashing.
- **API-GOOGLE-08: Offline Restaurant Fallback**
  - Verifies candidate loading from `BRNS/data/restaurants.json` when live Google search is disabled (`USE_LIVE_GOOGLE=false`).

---

## How to Run

Ensure your `.env` file at the root of the project contains your API keys:

```bash
OPENROUTER_API_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
GOOGLE_MAPS_API_KEY=...
```

### Run All API Tests:
```bash
python "tests/API/run_api_tests.py"
```

### Run Individual Test Suites:
```bash
# Run AI keys & fallback chain tests:
python "tests/API/test_ai_keys_and_fallback.py"

# Run Google Maps Platform API tests:
python "tests/API/test_google_api.py"
```
