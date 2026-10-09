"""BRNS request boundary and output. BIS owns all user input."""

import json
import math

from BRNS import places_client
from BIS.sources.profile_schema import (
    CUISINES, clean_text, validate_value,
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "cuisine",
    "budget_per_person", "other_preferences",
    "dietary_requirements", "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}


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
    if not isinstance(cuisine, str) or cuisine not in CUISINES:
        raise ValueError("Choose one supported cuisine for the search.")
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
    return places_client.build_candidates(origin, lookup, catalog)


def get_route(origin, destination, mode):
    """Fetch a route through the IO-owned external service client."""
    return places_client.get_route(origin, destination, mode)


def build_maps_link(origin, destination, mode):
    return places_client.build_maps_link(origin, destination, mode)


def show_results(results):
    """Display ranked restaurants without collecting any input."""
    items = results["matches"] + results["alternatives"]
    if not items:
        print("BiteFinder: No restaurants found for this search.")
        return
    print("BiteFinder: Restaurant results:")
    for number, item in enumerate(items, 1):
        restaurant = item["restaurant"]
        kind = "Match" if item in results["matches"] else "Alternative"
        cuisine = ", ".join(restaurant.get("cuisines") or []) or "unknown cuisine"
        dietary = ", ".join(
            item for item in restaurant.get("dietary_requirements") or []
            if item != "halal") or "dietary evidence unavailable"
        halal = restaurant.get("halal_status")
        if halal == "unofficial":
            dietary += " | Halal (unofficial; not checked)"
        elif halal == "unverified" and "halal" in results["requested_dietary"]:
            dietary += " | Halal unverified"
        mode = results["mode"]
        meters = restaurant.get(f"{mode}_meters")
        source = restaurant.get(f"{mode}_source")
        travel = (f"{meters / 1000:.2f} km {mode}"
                  if meters is not None else "travel distance unavailable")
        if source == "estimate":
            travel += " (estimate; unverified)"
        price = restaurant.get("avg_price")
        if price is None:
            price = restaurant.get("price_start")
        budget = (f"from SGD {price:.2f}" if price is not None
                  else "price unverified")
        print(f"  {number}. {restaurant['name']} [{kind}]")
        print(f"     {restaurant.get('address') or 'address unavailable'}")
        print(f"     {cuisine} | {budget} | {travel} | {dietary}")
        for reason in item["reasons"]:
            print(f"     {reason}")


def show_route(name, route, link, mode):
    print(f"BiteFinder: {mode.title()} route to {name}:")
    if route is not None:
        print(f"  {route['distance_m']} m, {route['duration_min']} min")
        for step in route["steps"]:
            print(f"  {step}")
    else:
        print("  Detailed route unavailable; use this map link:")
    print(f"  {link}")
