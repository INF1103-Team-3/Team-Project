import os
from dotenv import load_dotenv

load_dotenv()  # reads .env

# --- AI layer: OpenRouter + direct Gemini (separate quota pools) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")   # from aistudio.google.com — free, no card

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

MODEL_CHAIN = [
    {"provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    {"provider": "gemini", "model": "gemini-3.5-flash-lite"},   # from Google's 404 notice
    {"provider": "gemini", "model": "gemini-3.6-flash"},        # separate daily pool
]

# --- Data layer: Google Maps Platform ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
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
RESTAURANT_FILE = "data/restaurants.json"
HISTORY_FILE = "data/search_history.json"
GEOCODE_CACHE_FILE = "data/geocode_cache.json"
