"""Run a BRNS search from one BIS JSON request, without user prompts."""

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRNS import ai_manager, config, data_manager, io_manager, logic_manager
from shared import debug_log as log
from shared import terminal_ui as ui


def search(bis_json):
    """Run IO → AI → Logic → Data for one validated BIS search."""
    trace_token = log.start_trace()
    started = time.monotonic()
    log.debug_log("Search started.", "INFO", "BRNS.main.search")
    try:
        request = io_manager.accept_bis_json(bis_json)
        log.debug_log("BIS JSON validated.", "INFO",
                      "BRNS.io_manager.accept_bis_json")
        if not ai_manager.has_configured_provider():
            raise RuntimeError(
                "BRNS needs a configured AI provider to complete this search.")
        if config.USE_LIVE_GOOGLE and not config.GOOGLE_MAPS_API_KEY:
            raise RuntimeError("Set GOOGLE_MAPS_API_KEY for live restaurant search.")
        candidates = io_manager.find_candidates(request)
        log.debug_log(f"Gathered {len(candidates)} candidates.", "INFO",
                      "BRNS.io_manager.find_candidates")
        if not candidates:
            raise RuntimeError(
                "No restaurants found, or restaurant search is unavailable.")
        recommendations = ai_manager.recommend_candidates(request, candidates)
        if recommendations is None:
            raise RuntimeError(
                "BRNS AI could not recommend restaurants. Please retry.")
        log.debug_log(
            f"AI ordered {len(recommendations)} candidate IDs.", "INFO",
            "BRNS.ai_manager.recommend_candidates")
        results = logic_manager.rank_restaurants(
            candidates, request, recommendations)
        log.debug_log(
            f"Validated {len(results['matches'])} matches, "
            f"{len(results['alternatives'])} alternatives, "
            f"{results['hidden']} hidden.", "INFO",
            "BRNS.logic_manager.rank_restaurants")
        source = "live-google" if config.USE_LIVE_GOOGLE else "offline-catalog"
        saved = data_manager.save_search_results(request, results, source)
        log.debug_log(
            "Search summary saved." if saved else "Search summary could not be saved.",
            "INFO" if saved else "WARNING", "BRNS.data_manager.save_search_results")
        return results
    except (ValueError, RuntimeError, OSError) as error:
        log.debug_log(f"Search stopped: {type(error).__name__}.", "ERROR",
                      "BRNS.main.search")
        raise
    finally:
        log.debug_log(
            f"Search flow finished in {time.monotonic() - started:.2f}s.",
            "INFO", "BRNS.main.search")
        log.end_trace(trace_token)


def route_to(restaurant, request):
    """Return an optional route for a BIS-selected result."""
    log.debug_log("Route requested.", "INFO", "BRNS.main.route_to")
    origin = (request["origin"]["latitude"], request["origin"]["longitude"])
    latitude, longitude = restaurant.get("lat"), restaurant.get("lng")
    if latitude is None or longitude is None:
        raise ValueError("No verified coordinates are available for that restaurant.")
    destination = (latitude, longitude)
    mode = request["mode"]
    result = {
        "name": restaurant["name"],
        "route": io_manager.get_route(origin, destination, mode),
        "link": io_manager.build_maps_link(origin, destination, mode),
        "mode": mode,
    }
    log.debug_log(
        "Route response prepared with directions."
        if result["route"] else "Route response prepared with map link.",
        "INFO", "BRNS.main.route_to")
    return result


def main():
    """Standalone BRNS accepts one BIS JSON object on standard input."""
    log.configure(io_manager.display_debug if config.DEBUG else None)
    try:
        results = search(json.load(sys.stdin))
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        ui.message(error, "error")
        return
    io_manager.show_results(results)


if __name__ == "__main__":
    main()
