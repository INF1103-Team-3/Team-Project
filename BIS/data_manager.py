"""Account persistence and location data lookup. No terminal IO or AI."""

import json
import os
import tempfile
import sys
from pathlib import Path
from uuid import uuid4

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import geocode_cache

import logic_manager
from shared.debug_log import debug_log
from sources.profile_schema import (
    MINUTES_PER_KM, empty_preferences, normalize_email,
    normalize_username, validate_user, validate_preferences,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "profile_state.json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
LAST_ERROR = None


def serialize_search_request(request):
    """Produce the exact JSON object handed from BIS to BRNS IO."""
    return json.dumps(request, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _read_json(path):
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cannot read saved data. Restore the file before writing; "
            "existing data has been retained."
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError("Saved data must contain a JSON object.")
    return value


def _registry():
    users = _read_json(USERS_FILE)
    emails = set()
    for user_id, user in users.items():
        if not isinstance(user_id, str) or not user_id or (
            not isinstance(user, dict) or user.get("userID") != user_id
        ):
            raise ValueError(
                "Invalid user record in data/users.json; saved data was "
                "retained. Restore a valid copy before writing."
            )
        users[user_id] = validate_user(user)
        email = users[user_id]["email"]
        if email in emails:
            raise ValueError("Duplicate saved emails; restore the user file.")
        emails.add(email)
    return users


def load():
    """Return validated accounts, or [] if saved data cannot be read."""
    global LAST_ERROR
    try:
        records = list(_registry().values())
    except (ValueError, RuntimeError) as error:
        LAST_ERROR = str(error)
        debug_log("Registry read failed; writes blocked.",
                  "ERROR", "BIS.data.load")
        return []
    LAST_ERROR = None
    return records


def query(filter_fn):
    return [record for record in load() if filter_fn(record)]


def _atomic_write(path, value):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".profile-",
            suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(value, file, indent=4,
                      ensure_ascii=False, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Save failed. Check permissions and disk space; "
            "the previous file was retained."
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save(record):
    """Save one validated account, retaining every other account."""
    record = validate_user(record)
    users = _registry()
    if any(user["email"] == record["email"] and key != record["userID"]
           for key, user in users.items()):
        raise ValueError("This email is already registered.")
    users[record["userID"]] = record
    _atomic_write(USERS_FILE, users)
    debug_log("User record saved.", "INFO", "BIS.data.save")
    return record


def register_user(email, username):
    email = normalize_email(email)
    username = normalize_username(username)
    users = _registry()
    if any(user["email"] == email for user in users.values()):
        raise ValueError("This email is already registered. Choose resume.")
    user_id = str(uuid4())
    while user_id in users:
        user_id = str(uuid4())
    return save({
        "userID": user_id, "email": email, "email_verified": False,
        "username": username, "preferences": empty_preferences(),
    })


def email_exists(email):
    email = normalize_email(email)
    return any(user["email"] == email for user in _registry().values())


def find_user(email):
    email = normalize_email(email)
    users = _registry()
    for user in users.values():
        if user["email"] == email:
            return user
    raise ValueError("No profile found for this email. Please sign up first.")


def get_user(user_id):
    users = _registry()
    if user_id not in users:
        raise ValueError("Unknown userID. Please sign up first.")
    return users[user_id]


def save_preferences(user_id, preferences, config):
    user = get_user(user_id)
    if not user["email_verified"] and config.get("smtp_bypass") is not True:
        raise ValueError("Verify your email before changing preferences.")
    user["preferences"] = validate_preferences(preferences)
    result = save(user)
    debug_log(
        f"max_distance_km={preferences['max_distance_km']}, "
        f"max_travel_time_minutes={preferences['max_travel_time_minutes']}; "
        f"conversion assumption={MINUTES_PER_KM} min/km.",
        "INFO", "BIS.profile.travel",
    )
    return result


def get_state(section, user_id):
    state = _read_json(STATE_FILE)
    values = state.get(section, {})
    if not isinstance(values, dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    value = values.get(user_id)
    if value is not None and not isinstance(value, dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    return value


def set_state(section, user_id, value):
    state = _read_json(STATE_FILE)
    if not isinstance(state.get(section, {}), dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    values = state.setdefault(section, {})
    if value is None:
        values.pop(user_id, None)
    else:
        values[user_id] = value
    _atomic_write(STATE_FILE, state)


def lookup_cached_location(query):
    pair = geocode_cache.lookup(query)
    if pair and logic_manager.in_singapore(*pair):
        return {
            "query": query, "label": query,
            "latitude": pair[0], "longitude": pair[1],
        }
    return None


def resolve_location(query, api_key):
    """Retrieve an origin from coordinates, cache, or Google Geocoding."""
    coordinates = logic_manager.parse_coordinates(query)
    if coordinates:
        return {
            "query": query, "label": f"{coordinates[0]}, {coordinates[1]}",
            "latitude": coordinates[0], "longitude": coordinates[1],
        }
    cached = lookup_cached_location(query)
    if cached:
        return cached
    if not api_key:
        raise RuntimeError(
            "This location is not cached. Set GOOGLE_MAPS_API_KEY or enter "
            "Singapore coordinates."
        )
    try:
        response = requests.get(
            GEOCODE_URL,
            params={"address": query + ", Singapore", "key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (requests.RequestException, ValueError, AttributeError) as error:
        raise RuntimeError("Geocoding is unavailable. Try again.") from error
    for result in results:
        try:
            point = result["geometry"]["location"]
            latitude = float(point["lat"])
            longitude = float(point["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if logic_manager.in_singapore(latitude, longitude):
            geocode_cache.remember((query,), latitude, longitude)
            return {
                "query": query,
                "label": result.get("formatted_address") or query,
                "latitude": latitude, "longitude": longitude,
            }
    raise ValueError("No Singapore location found. Try another address or postal code.")


def remember_location(queries, location):
    """Save aliases for a resolved location in the shared cache."""
    geocode_cache.remember(
        queries, location["latitude"], location["longitude"],
    )
