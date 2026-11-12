"""Composition only: build OOP collaborators without importing old web logic."""
import os
import sys
from pathlib import Path


def _seed_mongo_if_empty(connection):
    if os.getenv("BITEFINDER_AUTO_SEED", "1") != "1":
        return
    try:
        from BIS.classes.json_mongo_migration import JsonMongoMigration
        root = Path(__file__).resolve().parents[1]
        restaurants_path = root / "BRNS" / "data" / "restaurants.json"
        if restaurants_path.exists() and connection.execute(
                lambda db: db.restaurants.count_documents({})) == 0:
            migration = JsonMongoMigration()
            records = migration.prepare(restaurants=restaurants_path)
            for row in records["restaurants"]:
                connection.execute(lambda db, doc=row: db.restaurants.update_one(
                    {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True))
    except Exception:
        pass


def build_runtime():
    if os.getenv("BITEFINDER_STORAGE", "json").lower() != "mongo":
        raise RuntimeError("The web API requires BITEFINDER_STORAGE=mongo; standalone CLI defaults to JSON.")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from BIS.classes.mongo_connection import MongoConnection
    from BIS.classes.mongo_user_store import MongoUserStore
    from BIS.classes.mongo_session_store import MongoSessionStore
    from BIS.classes.mongo_credential_store import MongoCredentialStore
    from BIS.classes.mongo_favorite_store import MongoFavoriteStore
    from BIS.classes.mongo_search_proposal_store import MongoSearchProposalStore
    from BIS.classes.data_manager import DataManager
    from BIS.classes.location_gateway import LocationGateway
    from BIS.classes.password_hasher import PasswordHasher
    from BIS.classes.web_auth_service import WebAuthService
    from BIS.classes.favorite_service import FavoriteService
    from BIS.classes.bis_application_service import BISApplicationService
    from BIS.classes.web_io_manager import WebIOManager
    from BIS.classes.web_runtime import WebRuntime
    from BIS.support.config import load_config
    from BIS.support.email_verification.classes.email_verification_service import EmailVerificationService
    from BIS.support.email_verification.classes.verification_challenge_manager import VerificationChallengeManager
    from BIS.support.email_verification.classes.smtp_email_delivery import SMTPEmailDelivery
    from BIS import ai_manager as bis_ai, logic_manager as bis_logic
    from BRNS import config, ai_manager, io_manager, logic_manager
    from BRNS.classes.data_manager import DataManager as RecommendationData
    from BRNS.classes.io_manager import IOManager as RecommendationIO
    from BRNS.classes.web_io_manager import WebIOManager as RecommendationWebIO
    from BRNS.classes.mongo_recommendation_store import MongoRecommendationStore
    from BRNS.classes.search_history_scope import SearchHistoryScope
    from BRNS.classes.candidate_search import CandidateSearch
    from BRNS.classes.brns_recommendation_workflow import BRNSRecommendationWorkflow
    from BRNS.classes.halal_verification_coordinator import HalalVerificationCoordinator
    from BRNS.classes.brc_restaurant_checker_adapter import BRCRestaurantCheckerAdapter
    from BRNS.classes.navigation_service import NavigationService
    from BRC.classes.brc_http_client import BRCHTTPClient
    from shared import geocode_cache, debug_log

    connection = MongoConnection()
    try:
        connection.ready()
        users, sessions = MongoUserStore(connection), MongoSessionStore(connection)
        favorites, proposals = MongoFavoriteStore(connection), MongoSearchProposalStore(connection)
        for repository in (users, sessions, favorites, proposals):
            repository.ensure_indexes()
        data = DataManager(users, LocationGateway(bis_logic, geocode_cache,
                           os.getenv("BITEFINDER_GEOCODE_URL", "https://maps.googleapis.com/maps/api/geocode/json")),
                           sessions, favorites, MongoCredentialStore(connection), proposals)
        settings = load_config()
        verification = EmailVerificationService(data, VerificationChallengeManager(), SMTPEmailDelivery())
        auth = WebAuthService(data, verification, PasswordHasher(), settings)
        scope = SearchHistoryScope()
        store = MongoRecommendationStore(connection, scope)
        store.ensure_indexes()
        _seed_mongo_if_empty(connection)
        recommendation_data = RecommendationData(store)
        logic = logic_manager.manager()
        search = CandidateSearch(recommendation_data, logic, io_manager, debug_log)
        io = RecommendationWebIO(RecommendationIO(io_manager, logic, debug_log, search))
        checker = BRCRestaurantCheckerAdapter(BRCHTTPClient(
            base_url=os.getenv("BRC_SERVICE_URL", "http://brc:8000")))
        verifier = HalalVerificationCoordinator(logic, io, checker, debug_log)
        workflow = BRNSRecommendationWorkflow(io, ai_manager.manager(), logic,
                                              recommendation_data, verifier, config, debug_log)
        application = BISApplicationService(
            data, bis_ai.manager(), bis_logic.manager(), workflow,
            NavigationService(io, debug_log), recommendation_data, scope,
            settings, ai_manager.last_used_model)
        return WebRuntime(
            WebIOManager(
                data, auth, application, FavoriteService(data),
                connection.ready, ai_manager.current_active_model),
            connection,
        )
    except Exception:
        connection.close()
        raise
