"""Run a BRNS search from one BIS JSON request, without user prompts."""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRNS import ai_manager, config, data_manager, io_manager, logic_manager


def search(bis_json):
    """Run IO → AI → Logic → Data for one validated BIS search."""
    request = io_manager.accept_bis_json(bis_json)
    if config.USE_LIVE_GOOGLE and not config.GOOGLE_MAPS_API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY for live restaurant search.")
    candidates = io_manager.find_candidates(request)
    if not candidates:
        raise RuntimeError("No restaurants found, or restaurant search is unavailable.")
    suggested_order = ai_manager.recommend_candidates(request, candidates)
    results = logic_manager.rank_restaurants(
        candidates, request, suggested_order)
    source = "live-google" if config.USE_LIVE_GOOGLE else "offline-catalog"
    data_manager.save_search_results(request, results, source)
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
        "route": io_manager.get_route(origin, destination, mode),
        "link": io_manager.build_maps_link(origin, destination, mode),
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
