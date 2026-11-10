"""Compatibility façade and bootstrap for the OOP BRNS application."""

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC import main as brc_main
from BRC.classes.brc_http_client import BRCHTTPClient
from BRNS import ai_manager, config, data_manager, io_manager, logic_manager
from BRNS.classes.recommendation_system import RecommendationSystem
from shared import debug_log as log
from shared import terminal_ui as ui


_BRC_CHECKER = (
    BRCHTTPClient() if os.getenv("BRC_SERVICE_URL") else brc_main
)


_APPLICATION = RecommendationSystem(
    ai_manager.manager(),
    data_manager.manager(),
    io_manager.manager(),
    logic_manager.manager(),
    _BRC_CHECKER,
    config,
    log,
    ui,
)


def _brc_restaurant(candidate):
    return _APPLICATION.brc_restaurant(candidate)


def verify_halal_candidates(candidates, request, recommendations):
    return _APPLICATION.verify_halal_candidates(
        candidates, request, recommendations)


def search(bis_json, previous_restaurants=()):
    return _APPLICATION.search(bis_json, previous_restaurants)


def route_to(restaurant, request):
    return _APPLICATION.route_to(restaurant, request)


def sort_results(results, sort_by):
    return _APPLICATION.sort_results(results, sort_by)


def main():
    return _APPLICATION.run_cli()


if __name__ == "__main__":
    main()
