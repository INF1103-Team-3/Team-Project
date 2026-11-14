"""Runtime composition factories for BRNS (keeps BRNS and BRC hidden from web/BIS)."""

import json
import os
from pathlib import Path

from BRC.classes.io.http.client.brc_http_client import BRCHTTPClient
from BRNS import ai_manager, config, io_manager, logic_manager
from BRNS.classes.io.gateways.verification.brc_restaurant_checker_adapter import BRCRestaurantCheckerAdapter
from BRNS.classes.services.workflows.brns_recommendation_workflow import BRNSRecommendationWorkflow
from BRNS.classes.services.gateway.brns_service import BRNSService
from BRNS.classes.io.gateways.google.candidate_search import CandidateSearch
from BRNS.classes.data.data_manager import DataManager as RecommendationData
from BRNS.classes.services.workflows.halal_verification_coordinator import HalalVerificationCoordinator
from BRNS.classes.io.adapters.io_manager import IOManager as RecommendationIO
from BRNS.classes.data.stores.mongo.mongo_place_photo_store import MongoPlacePhotoStore
from BRNS.classes.data.stores.mongo.mongo_recommendation_store import MongoRecommendationStore
from BRNS.classes.data.stores.json.null_place_photo_store import NullPlacePhotoStore
from BRNS.classes.io.gateways.google.google_place_photo_gateway import GooglePlacePhotoGateway
from BRNS.classes.services.workflows.navigation_service import NavigationService
from BRNS.classes.services.workflows.place_photo_service import PlacePhotoService
from BRNS.classes.data.helpers.search_history_scope import SearchHistoryScope
from BRNS.classes.io.adapters.web_io_manager import WebIOManager as RecommendationWebIO
from common import debug_log


def _seed_restaurants_if_empty(connection, restaurants_path=None):
    """Populate initial restaurant documents in MongoDB once when collection is empty."""
    if os.getenv("BITEFINDER_AUTO_SEED", "1") != "1":
        return
    try:
        path = restaurants_path or (Path(__file__).resolve().parent / "data" / "restaurants.json")
        if not path.exists():
            return
        if connection.execute(lambda db: db.restaurants.count_documents({})) != 0:
            return
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return
        seen = set()
        for row in rows:
            key = row.get("google_place_id") if isinstance(row, dict) else None
            if not isinstance(key, str) or not key.strip() or key in seen or not row.get("name"):
                continue
            seen.add(key)
            doc = dict(row, _id=key)
            connection.execute(
                lambda db, item=doc: db.restaurants.update_one(
                    {"_id": item["_id"]}, {"$setOnInsert": item}, upsert=True
                )
            )
    except Exception:
        pass


def build_web_brns_service(connection, brc_service_url=None):
    """Build a Mongo-backed headless BRNS service wired to BRC via HTTP."""
    scope = SearchHistoryScope()
    store = MongoRecommendationStore(connection, scope)
    store.ensure_indexes()
    photo_store = MongoPlacePhotoStore(connection)
    photo_store.ensure_indexes()
    _seed_restaurants_if_empty(connection)
    recommendation_data = RecommendationData(store)
    logic = logic_manager.manager()
    search = CandidateSearch(recommendation_data, logic, io_manager, debug_log)
    io = RecommendationWebIO(RecommendationIO(io_manager, logic, debug_log, search))
    checker = BRCRestaurantCheckerAdapter(
        BRCHTTPClient(base_url=brc_service_url or os.getenv("BRC_SERVICE_URL", "http://brc:8000"))
    )
    verifier = HalalVerificationCoordinator(logic, io, checker, debug_log)
    workflow = BRNSRecommendationWorkflow(
        io, ai_manager.manager(), logic, recommendation_data, verifier, config, debug_log
    )
    photo_service = PlacePhotoService(
        photo_store,
        GooglePlacePhotoGateway(config, debug_log, io_manager._log_api_error),
        debug_log,
    )
    return BRNSService(
        workflow=workflow,
        navigator=NavigationService(io, debug_log),
        logic_manager=logic,
        data_manager=recommendation_data,
        history_scope=scope,
        io_manager=io,
        logger=debug_log,
        active_model_reader=ai_manager.current_active_model,
        last_model_reader=ai_manager.last_used_model,
        photo_service=photo_service,
    )


def build_cli_brns_service():
    """Build the headless BRNS service used by BIS CLI workflows."""
    from BRNS import data_manager

    if os.getenv("BRC_SERVICE_URL"):
        brc_checker = BRCHTTPClient()
    else:
        from BRC import main as brc_main

        brc_checker = brc_main
    logic = logic_manager.manager()
    io = io_manager.manager()
    recommendation_data = data_manager.manager()
    verifier = HalalVerificationCoordinator(
        logic, io, BRCRestaurantCheckerAdapter(brc_checker), debug_log
    )
    workflow = BRNSRecommendationWorkflow(
        io, ai_manager.manager(), logic, recommendation_data, verifier, config, debug_log
    )
    photo_service = PlacePhotoService(
        NullPlacePhotoStore(),
        GooglePlacePhotoGateway(config, debug_log, io_manager._log_api_error),
        debug_log,
    )
    return BRNSService(
        workflow=workflow,
        navigator=NavigationService(io, debug_log),
        logic_manager=logic,
        data_manager=recommendation_data,
        history_scope=data_manager.history_scope,
        io_manager=io,
        logger=debug_log,
        active_model_reader=ai_manager.current_active_model,
        last_model_reader=ai_manager.last_used_model,
        photo_service=photo_service,
    )
