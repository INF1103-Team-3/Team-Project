"""Store the BRNS catalog and approved search history."""
import json
import os
from BRNS import config


# ---------- generic helpers ----------

def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


# ---------- catalog (flat file) ----------

def load_restaurants(path=config.RESTAURANT_FILE):
    """Load all records on startup. Missing or corrupt file -> empty list."""
    data = _load_json(path)
    return data if isinstance(data, list) else []


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def save_history(entry, path=config.HISTORY_FILE):
    history = load_history(path)
    history.append(entry)
    return _save_json(path, history)


def save_search_results(request, results, source):
    """Keep only validated search facts in the history file."""
    origin = request["origin"]
    return save_history({
        "mode": source,
        "origin": [origin["latitude"], origin["longitude"]],
        "travel_mode": request["mode"],
        "cuisine": request["cuisine"],
        "top_matches": [
            item["restaurant"]["name"] for item in results["matches"]],
    })
