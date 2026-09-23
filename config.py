import os
from dotenv import load_dotenv

load_dotenv()  # reads .env

# --- OpenRouter (AI layer) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_CHAIN = [
    "nvidia/nemotron-3-ultra-550b-a55b",   # exact ID from openrouter.ai/models
    "google/gemini-3.1-flash-lite:free",
    # "qwen/qwen3-30b-a3b:free",
]

# --- Google Maps Platform (data layer) ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Set USE_LIVE_GOOGLE=false in .env for offline catalog mode
# (deterministic output, demo backup if APIs fail)
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "true").lower() == "true"

# --- Files ---
RESTAURANT_FILE = "data/restaurants.json"
HISTORY_FILE = "data/search_history.json"
GEOCODE_CACHE_FILE = "data/geocode_cache.json"
