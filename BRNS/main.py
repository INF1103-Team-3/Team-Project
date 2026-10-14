"""Run a BRNS search from one BIS JSON request, without user prompts."""

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRNS import ai_manager, config, data_manager, io_manager, logic_manager
from BRC import main as brc_main
from shared import debug_log as log
from shared import terminal_ui as ui


def _brc_restaurant(candidate):
    """Shape one BRNS candidate for BRC's single restaurant workflow."""
    record = dict(candidate)
    dietary = [
        item for item in candidate.get("dietary_requirements") or []
        if item in ("halal", "vegetarian")
    ]
    record["dietary"] = dietary
    record["halal_certification"] = (
        "unofficial" if candidate.get("halal_hint") or "halal" in dietary
        else "none")
    return record


def verify_halal_candidates(candidates, request, recommendations):
    """Run each AI-returned halal candidate through BRC and fail closed."""
    if "halal" not in request["dietary_requirements"]:
        return candidates, None
    order = logic_manager.recommendation_order(candidates, recommendations)
    database_missing = not brc_main.data_manager.CLEAN_DATABASE_PATH.exists()
    summary = {
        "candidates": len(order), "checked": 0, "verified": 0,
        "not_verified": 0, "errors": 0, "error_type": None,
        "database_missing": database_missing, "google_fallback": 0,
        "excluded": 0,
    }
    checked_candidates = []
    for original in candidates:
        candidate = dict(original)
        google_halal = (
            original.get("halal_hint") is True
            or "halal" in (original.get("dietary_requirements") or []))
        candidate["muis_check"] = {"status": "not_verified"}
        candidate["halal_certification"] = (
            "unofficial" if google_halal else "none")
        candidate["halal_hint"] = google_halal
        candidate["dietary_requirements"] = [
            item for item in candidate.get("dietary_requirements") or []
            if item != "halal"
        ]
        if google_halal:
            candidate["dietary_requirements"].append("halal")
        checked_candidates.append(candidate)
    io_manager.show_halal_verification_start(len(order), database_missing)
    for index in order:
        candidate = checked_candidates[index]
        try:
            checked = brc_main.run(_brc_restaurant(candidates[index]))
        except Exception as error:
            detail = log.safe_error_detail(error)
            log.debug_log(
                f"BRC check failed for candidate {index}: "
                f"{type(error).__name__}: {detail}", "ERROR",
                "BRNS.main.verify_halal_candidates")
            summary["errors"] += 1
            if summary["error_type"] is None:
                summary["error_type"] = type(error).__name__
            continue
        summary["checked"] += 1
        muis_check = checked.get("muis_check")
        verified = (
            checked.get("halal_certification") == "official"
            and isinstance(muis_check, dict)
            and muis_check.get("status") == "verified"
        )
        candidate["muis_check"] = (
            muis_check if isinstance(muis_check, dict)
            else {"status": "not_verified"})
        candidate["halal_certification"] = (
            "official" if verified else candidate["halal_certification"])
        candidate["halal_hint"] = (
            False if verified else candidate["halal_hint"])
        dietary = [
            item for item in candidate.get("dietary_requirements") or []
            if item != "halal"
        ]
        if verified:
            summary["verified"] += 1
            dietary.append("halal")
            cuisines = checked.get("cuisines")
            if isinstance(cuisines, list):
                candidate["cuisines"] = cuisines
        else:
            summary["not_verified"] += 1
            if candidate["halal_hint"]:
                dietary.append("halal")
        candidate["dietary_requirements"] = list(dict.fromkeys(dietary))
        log.debug_log(
            f"BRC {'verified' if verified else 'did not verify'} candidate "
            f"{index}.",
            "INFO" if verified else "WARNING",
            "BRNS.main.verify_halal_candidates")
    summary["google_fallback"] = sum(
        candidate.get("halal_certification") == "unofficial"
        for candidate in checked_candidates)
    summary["excluded"] = (
        summary["candidates"] - summary["verified"]
        - summary["google_fallback"])
    io_manager.show_halal_verification_summary(summary)
    return checked_candidates, summary


def search(bis_json, previous_restaurants=()):
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
        io_manager.show_ai_ranking_start(
            len(candidates), config.AI_CHAIN_TIMEOUT_SECONDS)
        recommendations = (
            ai_manager.recommend_candidates(
                request, candidates, previous_restaurants=previous_restaurants)
            if previous_restaurants else
            ai_manager.recommend_candidates(request, candidates))
        if recommendations is None:
            raise RuntimeError(
                "BRNS AI could not recommend restaurants. Please retry.")
        log.debug_log(
            f"AI ordered {len(recommendations)} candidate IDs.", "INFO",
            "BRNS.ai_manager.recommend_candidates")
        candidates, halal_verification = verify_halal_candidates(
            candidates, request, recommendations)
        results = (
            logic_manager.rank_restaurants(
                candidates, request, recommendations,
                previous_restaurants=previous_restaurants)
            if previous_restaurants else
            logic_manager.rank_restaurants(candidates, request,
                                           recommendations))
        log.debug_log(
            f"Validated {len(results['matches'])} matches, "
            f"{len(results['alternatives'])} alternatives, "
            f"{results['hidden']} hidden.", "INFO",
            "BRNS.logic_manager.rank_restaurants")
        if halal_verification is not None:
            results["halal_verification"] = halal_verification
        source = "live-google" if config.USE_LIVE_GOOGLE else "offline-restaurants"
        stored_count = data_manager.save_restaurants(candidates)
        log.debug_log(
            f"Saved {stored_count} restaurant records."
            if stored_count is not None else "Restaurant records could not be saved.",
            "INFO" if stored_count is not None else "WARNING",
            "BRNS.data_manager.save_restaurants")
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
        "route": io_manager.get_route(origin, destination, mode,
                                      request.get("traffic_aware", False)),
        "link": io_manager.build_maps_link(origin, destination, mode),
        "mode": mode,
        "traffic_aware": request.get("traffic_aware", False),
    }
    log.debug_log(
        "Route response prepared with directions."
        if result["route"] else "Route response prepared with map link.",
        "INFO", "BRNS.main.route_to")
    return result


def sort_results(results, sort_by):
    """Reorder an existing result set without running another search."""
    sorted_results = logic_manager.sort_results(results, sort_by)
    log.debug_log(f"Results sorted by {sort_by}.", "INFO",
                  "BRNS.logic_manager.sort_results")
    return sorted_results


def main():
    """Standalone BRNS accepts one BIS JSON object on standard input."""
    log.configure(io_manager.display_debug if config.DEBUG else None)
    try:
        results = search(json.load(sys.stdin))
    except json.JSONDecodeError:
        ui.message("BRNS requires valid BIS search JSON.", "error")
        return
    except (ValueError, RuntimeError, OSError) as error:
        ui.message(error, "error")
        return
    io_manager.show_results(results)


if __name__ == "__main__":
    main()
