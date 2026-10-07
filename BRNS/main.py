"""Run a BRNS search from one BIS JSON request, without user prompts."""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRNS import config, data_manager, io_manager, logic_manager


def search(bis_json):
    """Return ranked results for BIS's validated search choices."""
    request = io_manager.accept_bis_json(bis_json)
    if config.USE_LIVE_GOOGLE and not config.GOOGLE_MAPS_API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY for live restaurant search.")
    origin = (request["origin"]["latitude"], request["origin"]["longitude"])
    catalog = data_manager.load_restaurants()
    lookup = dict(request)
    lookup["free_text"] = " ".join(request["other_preferences"])
    candidates = data_manager.build_candidates(origin, lookup, catalog)
    if not candidates:
        raise RuntimeError("No restaurants found, or restaurant search is unavailable.")
    if not config.USE_LIVE_GOOGLE:
        candidates = [dict(candidate, source="offline catalog")
                      for candidate in candidates]
    results = logic_manager.rank_restaurants(candidates, request)
    data_manager.save_history({
        "mode": "live-google" if config.USE_LIVE_GOOGLE else "offline-catalog",
        "origin": list(origin),
        "travel_mode": request["mode"],
        "cuisine": request["cuisine"],
        "top_matches": [
            item["restaurant"]["name"] for item in results["matches"]],
    })
    return results


def route_to(restaurant, request):
    """Return an optional route for a BIS-selected result."""
    origin = (request["origin"]["latitude"], request["origin"]["longitude"])
    latitude, longitude = restaurant.get("lat"), restaurant.get("lng")
    if latitude is None or longitude is None:
        raise ValueError("No verified coordinates are available for that restaurant.")
    destination = (latitude, longitude)
    mode = request["mode"]
    return {
        "name": restaurant["name"],
        "route": data_manager.get_route(origin, destination, mode),
        "link": data_manager.build_maps_link(origin, destination, mode),
        "mode": mode,
    }


def main():
    """Standalone BRNS accepts one BIS JSON object on standard input."""
    try:
        results = search(json.load(sys.stdin))
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"BiteFinder: {error}")
        return
    io_manager.show_results(results)


if __name__ == "__main__":
    main()
