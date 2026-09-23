"""Pedestrian routing only; no straight-line substitution or guessed durations."""

import json
from http.client import HTTPException
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from debug import debug_log
from schemas import is_number, valid_coordinates

ENDPOINT = "https://api.openrouteservice.org/v2/directions/foot-walking/json"
CACHE_SECONDS = 3600
MAX_REQUESTS = 10


def cache_key(origin, destination):
    return json.dumps(["foot-walking", origin, destination], separators=(",", ":"))


def valid_route(route):
    return (isinstance(route, dict) and is_number(route.get("minutes"))
            and is_number(route.get("distance_m"))
            and route.get("provider") == "openrouteservice")


def fetch_walking_route(origin, destination, config):
    if not valid_coordinates(origin) or not valid_coordinates(destination):
        return None, "Walking route coordinates are unavailable."
    if not config.get("routing_key"):
        return None, "Set OPENROUTESERVICE_API_KEY to request walking routes."
    request = Request(
        ENDPOINT,
        data=json.dumps({"coordinates": [origin[::-1], destination[::-1]],
                         "instructions": False, "geometry": False,
                         "radiuses": [100, 100]}).encode(),
        headers={"Authorization": config["routing_key"],
                 "Content-Type": "application/json"}, method="POST",
    )
    debug_log("route_started")
    try:
        with urlopen(request, timeout=config.get("timeout", 20)) as response:
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise ValueError
        payload = json.loads(raw)
        summary = payload["routes"][0]["summary"]
        duration, distance = summary["duration"], summary["distance"]
        if not is_number(duration) or not is_number(distance):
            raise ValueError
        route = {"minutes": duration / 60, "distance_m": distance,
                 "provider": "openrouteservice"}
        debug_log("route_received")
        return route, None
    except HTTPError as error:
        debug_log("route_failed", "error", error.code)
        return None, "Walking service rejected the request; check the key and account limits."
    except (URLError, OSError, HTTPException, ValueError,
            KeyError, IndexError, TypeError, RecursionError):
        debug_log("route_failed", "error")
        return None, "Walking route unavailable. No estimated substitute was used."


def resolve_routes(origin, restaurants, config, cache, now=None):
    """Return routes, updated cache and warnings; persist via Data Manager."""
    now = time.time() if now is None else now
    routes, updated, warnings = {}, {}, []
    # Discard stale/invalid entries without making failed routes look valid.
    for key, entry in cache.items():
        if (isinstance(entry, dict) and is_number(entry.get("stored_at"))
                and 0 <= now - entry["stored_at"] < CACHE_SECONDS
                and valid_route(entry.get("route"))):
            updated[key] = entry
    if not valid_coordinates(origin):
        return routes, updated, warnings
    calls = 0
    for restaurant in restaurants:
        destination = restaurant.get("location")
        if not valid_coordinates(destination):
            warnings.append("Some restaurants have no verified coordinates.")
            continue
        key = cache_key(origin, destination)
        if key in updated:
            routes[restaurant["restaurant_id"]] = updated[key]["route"]
            continue
        if not config.get("routing_key"):
            warnings.append("Set OPENROUTESERVICE_API_KEY for uncached walking routes.")
            continue
        if calls >= MAX_REQUESTS:
            warnings.append(
                "Walking requests capped at 10 per search; remaining routes are unknown.")
            continue
        calls += 1
        route, error = fetch_walking_route(origin, destination, config)
        if error:
            warnings.append(error)
            continue
        routes[restaurant["restaurant_id"]] = route
        updated[key] = {"stored_at": now, "route": route}
    return routes, updated, sorted(set(warnings))
