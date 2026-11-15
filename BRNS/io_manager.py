"""BRNS request boundary and output. BIS owns all user input."""

from BRNS.classes.logic.discovery.discovery_policy import DiscoveryPolicy
from BRNS.classes.io.gateways.google.google_places_gateway import (
    GooglePlacesGateway,
)
from BRNS.classes.services.workflows.candidate_search import CandidateSearch

import json
import math
import sys
import re
import requests
from pathlib import Path

from BRNS import config, logic_manager
from BRNS.classes.io.gateways.google.google_route_gateway import (
    GoogleRouteGateway,
)
from BRNS.classes.io.adapters.io_manager import IOManager
from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy
from BRNS.classes.logic.evaluation.restaurant_enricher import (
    RestaurantEnricher,
)
from common import geocode_cache
from common import debug_log as log
from common import recommendation_ui
from common import terminal_ui as ui
from BIS.sources.profile_schema import (
    CUISINES,
    clean_text,
    validate_travel_minutes,
    validate_value,
)

SEARCH_FIELDS = {
    "origin",
    "mode",
    "max_distance_km",
    "max_travel_minutes",
    "traffic_aware",
    "cuisine",
    "budget_per_person",
    "other_preferences",
    "dietary_requirements",
    "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}
_MANAGER = None
_ENRICHER = RestaurantEnricher()


def manager():
    """Return the configured BRNS IO Manager."""
    global _MANAGER
    if _MANAGER is None:
        from BRNS import data_manager
        from BRNS.classes.services.workflows.candidate_search import (
            CandidateSearch,
        )

        search = CandidateSearch(
            data_manager.manager(),
            logic_manager.manager(),
            sys.modules[__name__],
            log,
        )
        _MANAGER = IOManager(
            sys.modules[__name__], logic_manager.manager(), log, search
        )
    return _MANAGER


def display_debug(line):
    """Mirror shared operational logs to stderr when DEBUG is enabled."""
    print(line, file=sys.stderr)


def accept_bis_json(payload):
    """Validate one BIS search request without prompting or changing it."""
    return manager().accept_bis_json(payload)


def _strip_rating_terms(text):
    return _DISCOVERY_POLICY.strip_rating_terms(text)


def _clean_free_text_query(preferences):
    return _DISCOVERY_POLICY.clean_free_text_query(preferences)


def find_candidates(request):
    """Collect restaurant facts through Places or saved records."""
    return manager().find_candidates(request)


def show_results(results, announce_no_matches=True):
    """Display ranked restaurants without collecting any input."""
    recommendation_ui.show_results(results, announce_no_matches)


def display_record(record):
    """Display one ranked restaurant record."""
    display_result({"matches": [record], "alternatives": [], "mode": "walk"})


def display_list(records):
    """Display a validated collection of ranked restaurant records."""
    display_result(
        {"matches": list(records), "alternatives": [], "mode": "walk"}
    )


def display_result(result):
    """Display one complete BRNS result dictionary."""
    show_results(result, announce_no_matches=False)


def show_result_list(results):
    """Show a compact numbered list before optional details or routing."""
    recommendation_ui.show_result_list(results)


def show_no_matches(results):
    """Explain why the leading alternative is not a verified match."""
    recommendation_ui.show_no_matches(results)


def show_halal_verification_start(candidate_count, database_missing=False):
    """Show the official halal check stage before potentially slow BRC work."""
    ui.message(
        f"BRC is checking {candidate_count} candidate(s) against official "
        "MUIS halal records."
    )
    if database_missing:
        ui.message(
            "BRC is preparing its cleaned MUIS database; the first check may "
            "take longer.",
            "warning",
        )


def show_ai_ranking_start(candidate_count, timeout_seconds):
    """Tell the user what happens during the bounded AI ranking stage."""
    ui.message(
        f"BRNS found {candidate_count} candidate(s). AI is ranking them "
        f"(up to {timeout_seconds:g} seconds)."
    )


def show_halal_verification_summary(summary):
    """Show how many candidates BRC accepted or rejected."""
    ui.message(
        f"BRC halal check: {summary['verified']} verified, "
        f"{summary['not_verified']} not verified."
    )
    if summary["google_fallback"]:
        ui.message(
            f"Using {summary['google_fallback']} Google-indicated halal "
            "candidate(s) as unofficial fallback results.",
            "warning",
        )
    if summary["errors"]:
        ui.message(
            f"BRC encountered {summary['errors']} "
            f"{summary['error_type']} error"
            f"{'s' if summary['errors'] != 1 else ''} during individual "
            "checks; it continued checking the other candidates and used "
            "Google halal information where available. "
            f"{summary['excluded']} candidate(s) had no accepted halal "
            "evidence. Details: logs/bitefinder.log.",
            "warning",
        )


def _show_result(number, item, results, role):
    """Print one restaurant card with the evidence behind its ranking."""
    recommendation_ui.show_result_card(number, item, results, role)


def show_route(name, route, link, mode, traffic_aware=False):
    recommendation_ui.show_route(name, route, link, mode, traffic_aware)


# ---------- Google Places, geocoding, and routing (IO) ----------


def load_saved_restaurants(path=config.RESTAURANT_FILE):
    """Preserve the saved-enrichment API through Data and Logic owners."""
    from BRNS import data_manager

    return logic_manager.manager().saved_candidates(
        data_manager.manager().load_candidate_records(path)
    )


def _log_api_error(context, err):
    """Record only error type and HTTP status, never URL or response body."""
    if isinstance(err, str):
        kind = "invalid response"
        status = None
    else:
        kind = type(err).__name__
        status = getattr(getattr(err, "response", None), "status_code", None)
    detail = f"{kind}; HTTP {status}" if status is not None else kind
    log.debug_log(detail, "WARNING", f"BRNS.io_manager.{context}")


# ---------- price helpers ----------

# <=8 $, <=15 $$, <=30 $$$, else $$$$
BAND_THRESHOLDS = RestaurantEnricher.BAND_THRESHOLDS


def price_to_band(avg_price):
    return _ENRICHER.price_to_band(avg_price)


def _money_to_float(money):
    return _PLACES_GATEWAY.money_to_float(money)


def _fmt_price_range(pr):
    return _PLACES_GATEWAY.fmt_price_range(pr)


def _band_from_range(start, end):
    return _ENRICHER._band_from_range(start, end)


# ---------- Google Geocoding API (classic, with permanent cache) ----------


def geocode_location(address_text):
    return _PLACES_GATEWAY.geocode_location(address_text)


# ---------- Google Places API (New): nearby + profile text search ----------

_CUISINE_MAP = RestaurantEnricher.CUISINE_MAP


def _cuisine_from_types(types):
    return _ENRICHER._cuisine_from_types(types)


def _weekday_index(name):
    return _PLACES_GATEWAY.weekday_index(name)


def _hours_string_for_day(regular_hours, weekday_index):
    return _PLACES_GATEWAY.hours_string_for_day(regular_hours, weekday_index)


def _parse_place(p):
    return _PLACES_GATEWAY.parse_place(p)


def _travel_radius(req):
    return _DISCOVERY_POLICY.travel_radius(req)


def _search_radius(req):
    return _DISCOVERY_POLICY.search_radius(req)


def fetch_nearby_restaurants(origin, req, debug=False):
    return _PLACES_GATEWAY.fetch_nearby_restaurants(origin, req, debug)


_VENUE_WORDS = (
    "food",
    "cafe",
    "hawker",
    "restaurant",
    "centre",
    "center",
    "court",
    "market",
    "kopi",
    "canteen",
    "bakery",
    "bar",
)


def _build_text_query(req, default_query=None):
    return _DISCOVERY_POLICY.build_text_query(req, default_query)


def _complementary_venue_query(query):
    return _DISCOVERY_POLICY.complementary_venue_query(query)


def _run_text_search(
    origin,
    query,
    radius_m,
    error_tag,
    max_pages=1,
    price_levels=None,
    min_rating=None,
    rank_preference="RELEVANCE",
    return_status=False,
):
    return _PLACES_GATEWAY.run_text_search(
        origin,
        query,
        radius_m,
        error_tag,
        max_pages,
        price_levels,
        min_rating,
        rank_preference,
        return_status,
    )


def _merge_unique_places(primary, secondary):
    return _DISCOVERY_POLICY.merge_unique_places(primary, secondary)


def _qualifying_open_count(places, min_rating=None):
    return _DISCOVERY_POLICY.qualifying_open_count(places, min_rating)


def fetch_by_profile_text(origin, req):
    return _DISCOVERY_SEARCH.fetch_profile(origin, req)


OPEN_SEARCH_MAX_PAGES = 1  # Keep open-now fallback fast within API budget


def fetch_open_places(origin, req):
    return _DISCOVERY_SEARCH.fetch_open(origin, req)


# ---------- enrichment: Places results x saved restaurants ----------


def _norm(name):
    return _ENRICHER._norm(name)


def _match_saved_restaurant(place, saved_restaurants):
    return _ENRICHER._match_saved_restaurant(place, saved_restaurants)


def enrich_place(place, saved_restaurants):
    """Compatibility entry point for the domain enrichment policy."""
    return logic_manager.manager().enrich_place(place, saved_restaurants)


# ---------- Google Routes API ----------
_ROUTE_GATEWAY = GoogleRouteGateway(config, log, _log_api_error)


def _haversine_km(first, second):
    return _ROUTE_GATEWAY.haversine_km(first, second)


def _estimate_travel_minutes(origin, restaurant, mode):
    return _ROUTE_GATEWAY.estimate_travel_minutes(origin, restaurant, mode)


def travel_times_matrix(origin, restaurants, mode, traffic_aware=False):
    return _ROUTE_GATEWAY.travel_times_matrix(
        origin, restaurants, mode, traffic_aware
    )


def _fill_travel_estimates(origin, restaurants):
    return _ROUTE_GATEWAY.fill_travel_estimates(origin, restaurants)


def format_transit_step(step):
    return _ROUTE_GATEWAY.format_transit_step(step)


def get_route(origin, destination, mode, traffic_aware=False):
    return _ROUTE_GATEWAY.get_route(origin, destination, mode, traffic_aware)


def build_maps_link(origin, destination, mode):
    return _ROUTE_GATEWAY.build_maps_link(origin, destination, mode)


def _sample_zone_slice(candidates, origin, radius_m, limit):
    return _DISCOVERY_POLICY.sample_zone_slice(
        candidates, origin, radius_m, limit
    )


def _select_zone_places(places, origin, radius_m, limit=20, min_rating=None):
    return _DISCOVERY_POLICY.select_zone_places(
        places, origin, radius_m, limit, min_rating
    )


# ---------- candidate builder ----------


def build_candidates(origin, req, saved_restaurants):
    return _DISCOVERY_SEARCH.build(origin, req, saved_restaurants)


# Composition of discovery policy, provider transport and application workflow.

_DISCOVERY_POLICY = DiscoveryPolicy(
    logic_manager, _haversine_km, _norm, log, _log_api_error
)
_PLACES_GATEWAY = GooglePlacesGateway(
    config,
    logic_manager,
    _DISCOVERY_POLICY,
    log,
    _log_api_error,
    _haversine_km,
    geocode_cache,
)


def discovery_policy():
    return _DISCOVERY_POLICY


_DISCOVERY_SEARCH = CandidateSearch(None, None, sys.modules[__name__], log)
