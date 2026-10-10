"""BRNS request boundary and output. BIS owns all user input."""

import json
import math
import sys

from BRNS import places_client
from shared import debug_log as log
from shared import terminal_ui as ui
from BIS.sources.profile_schema import (
    CUISINES, clean_text, validate_value,
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "cuisine",
    "budget_per_person", "other_preferences",
    "dietary_requirements", "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}


def display_debug(line):
    """Mirror shared operational logs to stderr when DEBUG is enabled."""
    print(line, file=sys.stderr)


def accept_bis_json(payload):
    """Validate one BIS search request without prompting or changing it."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise ValueError("BRNS requires valid BIS search JSON.") from error
    if not isinstance(payload, dict) or set(payload) != SEARCH_FIELDS:
        raise ValueError("BRNS requires the eight BIS search fields only.")
    origin = payload["origin"]
    if not isinstance(origin, dict) or set(origin) != ORIGIN_FIELDS:
        raise ValueError("BRNS requires a confirmed origin object.")
    query = clean_text(origin["query"], 200)
    label = clean_text(origin["label"], 500)
    latitude, longitude = origin["latitude"], origin["longitude"]
    if (type(latitude) not in (int, float)
            or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not 1.15 <= latitude <= 1.48
            or not 103.60 <= longitude <= 104.10):
        raise ValueError("The search origin must be within Singapore.")
    if payload["mode"] not in ("walk", "drive"):
        raise ValueError("Choose walk or drive for the search.")
    if payload["max_distance_km"] is None or payload["budget_per_person"] is None:
        raise ValueError("Search distance and budget are required.")
    if any(not isinstance(payload[field], list) for field in (
        "other_preferences", "dietary_requirements", "disliked_cuisines",
    )):
        raise ValueError("Search preferences and dietary requirements must be lists.")
    cuisine = payload["cuisine"]
    if not isinstance(cuisine, str) or cuisine not in (*CUISINES, "none"):
        raise ValueError("Choose a supported cuisine or none for the search.")
    return {
        "origin": {
            "query": query, "label": label,
            "latitude": latitude, "longitude": longitude,
        },
        "mode": payload["mode"],
        "max_distance_km": validate_value(
            "max_distance_km", payload["max_distance_km"]),
        "cuisine": cuisine,
        "budget_per_person": validate_value(
            "budget_per_person", payload["budget_per_person"]),
        "other_preferences": validate_value(
            "other_preferences", payload["other_preferences"]),
        "dietary_requirements": validate_value(
            "dietary_requirements", payload["dietary_requirements"]),
        "disliked_cuisines": validate_value(
            "disliked_cuisines", payload["disliked_cuisines"]),
    }


def find_candidates(request):
    """Collect restaurant facts through Places or the catalog fallback."""
    origin = (request["origin"]["latitude"],
              request["origin"]["longitude"])
    lookup = dict(request)
    lookup["free_text"] = " ".join(request["other_preferences"])
    catalog = places_client.load_catalog()
    log.debug_log(f"Catalog loaded with {len(catalog)} records.", "DEBUG",
                  "BRNS.io_manager.find_candidates")
    candidates = places_client.build_candidates(origin, lookup, catalog)
    log.debug_log(f"Candidate builder returned {len(candidates)} records.",
                  "DEBUG", "BRNS.io_manager.find_candidates")
    return candidates


def get_route(origin, destination, mode):
    """Fetch a route through the IO-owned external service client."""
    route = places_client.get_route(origin, destination, mode)
    log.debug_log("Route available." if route else "Route unavailable.",
                  "INFO" if route else "WARNING",
                  "BRNS.io_manager.get_route")
    return route


def build_maps_link(origin, destination, mode):
    return places_client.build_maps_link(origin, destination, mode)


def show_results(results, announce_no_matches=True):
    """Display ranked restaurants without collecting any input."""
    matches = results["matches"]
    alternatives = results["alternatives"]
    if not matches and announce_no_matches:
        ui.message("No restaurants matched all your search choices.", "warning")
    if not matches and not alternatives:
        ui.message("No alternatives found either.", "warning")
        return
    number = 0
    for heading, items in (("Matches", matches), ("Alternatives", alternatives)):
        if not items:
            continue
        ui.section(f"{heading} ({len(items)})",
                   "match" if heading == "Matches" else "alternative")
        for item in items:
            number += 1
            _show_result(number, item, results,
                         "match" if heading == "Matches" else "alternative")


def show_result_list(results):
    """Show a compact numbered list before optional details or routing."""
    number = 0
    for heading, items in (("Matches", results["matches"]),
                           ("Alternatives", results["alternatives"])):
        if not items:
            continue
        role = "match" if heading == "Matches" else "alternative"
        ui.section(f"{heading} ({len(items)})", role)
        for item in items:
            number += 1
            restaurant = item["restaurant"]
            mode = results["mode"]
            meters = restaurant.get(f"{mode}_meters")
            distance = (f"{meters / 1000:.2f} km by {mode}"
                        if meters is not None else "distance unavailable")
            ui.item(number, f"{restaurant['name']} · {distance}", role=role)


def show_no_matches(results):
    """Explain why the leading alternative is not a verified match."""
    ui.message("No fully verified matches for these search choices.",
               "warning")
    alternatives = results["alternatives"]
    if not alternatives:
        ui.message("No alternatives found. Try changing today's search.",
                   "warning")
        return
    cautions = [reason[2:] for reason in alternatives[0]["reasons"]
                if reason.startswith("! ")]
    if cautions:
        ui.message("Why the top alternative is not a match: "
                   + "; ".join(cautions[:3]) + ".", "warning")


def _show_result(number, item, results, role):
    """Print one restaurant card with the evidence behind its ranking."""
    restaurant = item["restaurant"]
    cuisine = ", ".join(restaurant.get("cuisines") or []) or "Unavailable"
    dietary = ", ".join(
        item for item in restaurant.get("dietary_requirements") or []
        if item != "halal")
    halal = restaurant.get("halal_status")
    mode = results["mode"]
    meters = restaurant.get(f"{mode}_meters")
    source = restaurant.get(f"{mode}_source")
    travel = (f"{meters / 1000:.2f} km by {mode}"
              if meters is not None else "distance unavailable")
    if source == "estimate":
        travel += " (estimate, unverified)"
    average = restaurant.get("avg_price")
    starting = restaurant.get("price_start")
    price = (f"Average SGD {average:.2f}" if average is not None
             else f"From SGD {starting:.2f}" if starting is not None
             else "Unverified")
    ui.item(number, restaurant['name'], role=role)
    ui.line(f"     {restaurant.get('address') or 'Address unavailable'}", "muted")
    ui.field("Cuisine", cuisine, indent=5)
    ui.field("Price", price, indent=5)
    ui.field("Travel", travel, indent=5)
    if dietary:
        ui.field("Dietary", dietary, indent=5)
    if halal == "unofficial":
        ui.field("Halal", "Unofficial indication; not checked",
                 indent=5, role="warning")
    elif halal == "unverified" and "halal" in results["requested_dietary"]:
        ui.field("Halal", "Unverified", indent=5, role="warning")
    highlights = []
    checks = []
    for reason in item["reasons"]:
        if (reason == "! cuisine unavailable" and not restaurant.get("cuisines")):
            continue
        if (reason in ("! Halal (unofficial; not checked)",
                      "Halal (unofficial; not checked)") and halal == "unofficial"):
            continue
        if reason == "! halal status unverified" and halal == "unverified":
            continue
        caution = reason.startswith("! ")
        (checks if caution else highlights).append(
            reason[2:] if caution else reason)
    if highlights:
        ui.line("     Highlights:", "success")
        for reason in highlights:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "success")
    if checks:
        ui.line("     Things to check:", "warning")
        for reason in checks:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "warning")
    ui.line()


def show_route(name, route, link, mode):
    ui.section(f"{mode.title()} route to {name}")
    if route is not None:
        ui.field("Journey", f"{route['distance_m']} m · "
                 f"{route['duration_min']} min")
        for step in route["steps"]:
            ui.line(f"  {step}")
    else:
        ui.line("  Detailed route unavailable; use this map link:", "warning")
    ui.field("Map", link)
