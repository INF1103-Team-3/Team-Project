import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR.parent / ".env"
load_dotenv(ENV_FILE)
DEBUG = os.getenv("DEBUG", "false").strip().lower() == "true"

# --- AI layer: OpenRouter + direct Gemini (separate quota pools) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")   # from aistudio.google.com — free, no card

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Try the responsive direct provider first; retain OpenRouter as fallback.
MODEL_CHAIN = [
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},   # from Google's 404 notice
    {"provider": "gemini", "model": "gemini-3.6-flash"},        # separate daily pool
    {"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
]

# --- IO layer: Google Maps Platform ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# --- Display limits (tunable without touching logic) ---
MAX_MATCHES_SHOWN = 5
MAX_ALTERNATIVES_SHOWN = 5

# Set USE_LIVE_GOOGLE=false in .env for offline catalog mode
# (deterministic output, demo backup if APIs fail)
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "true").lower() == "true"

# --- Files ---
RESTAURANT_FILE = BASE_DIR / "data" / "restaurants.json"
HISTORY_FILE = BASE_DIR / "data" / "search_history.json"
GEOCODE_CACHE_FILE = BASE_DIR.parent / "data" / "geocode_cache.json"
