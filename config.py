import os
from dotenv import load_dotenv

load_dotenv()

# --- AI layer ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

MODEL_CHAIN = [
    # 1. Proven JSON output, 131K context — most reliable for structured responses.
    {"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},

    # 2. Router — auto-picks a free model that supports structured outputs.
    {"provider": "openrouter", "model": "openrouter/free"},

    # 3. Gemini — current free model. 503s are temporary; retry if needed.
    {"provider": "gemini", "model": "gemini-3.8-flash"},
]

# --- Data layer: Google Maps Platform ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# --- Display limits ---
MAX_MATCHES_SHOWN = 5
MAX_ALTERNATIVES_SHOWN = 5

# Set USE_LIVE_GOOGLE=false in .env for offline catalog mode
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "true").lower() == "true"

# --- Files ---
RESTAURANT_FILE = "data/restaurants.json"
HISTORY_FILE = "data/search_history.json"
GEOCODE_CACHE_FILE = "data/geocode_cache.json"
HALAL_FILE = "data/HalalFreak_restaurants.json"
API_ERROR_LOG = "data/api_errors.log"