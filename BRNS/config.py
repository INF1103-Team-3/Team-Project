import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR.parent / ".env"
load_dotenv(ENV_FILE)
DEBUG = os.getenv("DEBUG", "false").strip().lower() == "true"


def _bounded_seconds(name, default, maximum):
    """Read a positive timeout while keeping accidental values reasonable."""
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = float(default)
    return min(max(value, 1.0), float(maximum))


# --- AI layer: OpenRouter + direct Gemini + Groq + NVIDIA + SiliconFlow ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# from aistudio.google.com — free, no card
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
SILICON_FLOW_API_KEY = (
    os.getenv("SILICON_FLOW_API_KEY", "").strip()
    or os.getenv("SILICONFLOW_API_KEY", "").strip()
)
AI_REQUEST_TIMEOUT_SECONDS = _bounded_seconds(
    "BRNS_AI_REQUEST_TIMEOUT_SECONDS", 12, 60
)
AI_CHAIN_TIMEOUT_SECONDS = _bounded_seconds(
    "BRNS_AI_CHAIN_TIMEOUT_SECONDS", 45, 180
)

OPENROUTER_URL = os.getenv(
    "BITEFINDER_OPENROUTER_URL",
    "https://openrouter.ai/api/v1/chat/completions",
)
GEMINI_URL = os.getenv(
    "BITEFINDER_GEMINI_URL",
    "https://generativelanguage.googleapis.com/v1beta/models",
)
GROQ_URL = os.getenv(
    "BITEFINDER_GROQ_URL", "https://api.groq.com/openai/v1/chat/completions"
)
NVIDIA_URL = os.getenv(
    "BITEFINDER_NVIDIA_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
SILICONFLOW_URL = os.getenv(
    "BITEFINDER_SILICONFLOW_URL",
    "https://api.siliconflow.com/v1/chat/completions",
)

# Try the responsive direct provider first; retain OpenRouter as fallback.
MODEL_CHAIN = [
    # from Google's 404 notice
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},
]


def _extend_chain_with_dynamic_models():
    """Fetch Groq, NVIDIA NIM, and SiliconFlow chat models at startup."""
    from common.ai_models import fetch_nvidia_models, fetch_siliconflow_models
    from common.groq_models import fetch_chat_models

    discoverers = (
        ("groq", GROQ_API_KEY, fetch_chat_models),
        ("nvidia", NVIDIA_API_KEY, fetch_nvidia_models),
        ("siliconflow", SILICON_FLOW_API_KEY, fetch_siliconflow_models),
    )
    for provider_name, api_key, fetcher in discoverers:
        if not api_key:
            continue
        for model_id in fetcher(api_key):
            MODEL_CHAIN.append({"provider": provider_name, "model": model_id})


_extend_chain_with_dynamic_models()
MODEL_CHAIN.extend(
    [
        {
            "provider": "gemini",
            "model": "gemini-3.6-flash",
        },  # separate daily pool
        {
            "provider": "openrouter",
            "model": "nvidia/nemotron-3.5-super-vl:free",
        },
    ]
)

# --- IO layer: Google Maps Platform ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEOCODE_URL = os.getenv(
    "BITEFINDER_GEOCODE_URL",
    "https://maps.googleapis.com/maps/api/geocode/json",
)
TEXT_SEARCH_URL = os.getenv(
    "BITEFINDER_TEXT_SEARCH_URL",
    "https://places.googleapis.com/v1/places:searchText",
)
PLACES_URL = os.getenv(
    "BITEFINDER_PLACES_URL",
    "https://places.googleapis.com/v1/places:searchNearby",
)
PLACES_DETAILS_BASE_URL = os.getenv(
    "BITEFINDER_PLACES_DETAILS_URL",
    "https://places.googleapis.com/v1",
).rstrip("/")
MATRIX_URL = os.getenv(
    "BITEFINDER_MATRIX_URL",
    "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
)
ROUTES_URL = os.getenv(
    "BITEFINDER_ROUTES_URL",
    "https://routes.googleapis.com/directions/v2:computeRoutes",
)

# --- Display limits (tunable without touching logic) ---
MAX_MATCHES_SHOWN = 5
MAX_ALTERNATIVES_SHOWN = 5

# Set USE_LIVE_GOOGLE=false in .env to use saved restaurant records.
# (deterministic output, demo backup if APIs fail)
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "true").lower() == "true"

# --- Files ---
RESTAURANT_FILE = BASE_DIR / "data" / "restaurants.json"
HISTORY_FILE = BASE_DIR / "data" / "search_history.json"
GEOCODE_CACHE_FILE = BASE_DIR.parent / "data" / "geocode_cache.json"
