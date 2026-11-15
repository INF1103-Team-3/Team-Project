"""BIS composition root for the web runtime (sole BIS boundary wiring BRNS)."""

import os
import sys
from pathlib import Path


def build_web_runtime():
    """Assemble the Mongo-backed BIS web runtime without exposing BRNS or BRC to web."""
    if os.getenv("BITEFINDER_STORAGE", "json").lower() != "mongo":
        raise RuntimeError(
            "The web API requires BITEFINDER_STORAGE=mongo; standalone CLI defaults to JSON."
        )

    bis_dir = str(Path(__file__).resolve().parent)
    if bis_dir not in sys.path:
        sys.path.insert(0, bis_dir)

    from BIS import ai_manager as bis_ai, logic_manager as bis_logic
    from BIS.classes.services.web.bis_application_service import BISApplicationService
    from BIS.classes.data.data_manager import DataManager
    from BIS.classes.services.web.favorite_service import FavoriteService
    from BIS.classes.io.gateways.location_gateway import LocationGateway
    from BIS.classes.data.stores.mongo.mongo_connection import MongoConnection
    from BIS.classes.data.stores.mongo.mongo_credential_store import MongoCredentialStore
    from BIS.classes.data.stores.mongo.mongo_favorite_store import MongoFavoriteStore
    from BIS.classes.data.stores.mongo.mongo_search_proposal_store import MongoSearchProposalStore
    from BIS.classes.data.stores.mongo.mongo_session_store import MongoSessionStore
    from BIS.classes.data.stores.mongo.mongo_user_store import MongoUserStore
    from BIS.classes.logic.security.password_hasher import PasswordHasher
    from BIS.classes.services.web.web_auth_service import WebAuthService
    from BIS.classes.io.web.web_io_manager import WebIOManager
    from BIS.classes.services.web.web_runtime import WebRuntime
    from BIS.support.config import load_config
    from BIS.support.email_verification.classes.service.email_verification_service import (
        EmailVerificationService,
    )
    from BIS.support.email_verification.classes.delivery.smtp_email_delivery import (
        SMTPEmailDelivery,
    )
    from BIS.support.email_verification.classes.challenge.verification_challenge_manager import (
        VerificationChallengeManager,
    )
    from BRNS.runtime import build_web_brns_service
    from common import geocode_cache

    connection = MongoConnection()
    try:
        connection.ready()
        users, sessions = MongoUserStore(connection), MongoSessionStore(connection)
        favorites = MongoFavoriteStore(connection)
        proposals = MongoSearchProposalStore(connection)
        for repository in (users, sessions, favorites, proposals):
            repository.ensure_indexes()

        data = DataManager(
            users,
            LocationGateway(
                bis_logic,
                geocode_cache,
                os.getenv(
                    "BITEFINDER_GEOCODE_URL",
                    "https://maps.googleapis.com/maps/api/geocode/json",
                ),
            ),
            sessions,
            favorites,
            MongoCredentialStore(connection),
            proposals,
        )
        settings = load_config()
        verification = EmailVerificationService(
            data, VerificationChallengeManager(), SMTPEmailDelivery()
        )
        auth = WebAuthService(data, verification, PasswordHasher(), settings)
        brns = build_web_brns_service(connection)
        application = BISApplicationService(
            data, bis_ai.manager(), bis_logic.manager(), brns, settings
        )
        return WebRuntime(
            WebIOManager(auth, application, FavoriteService(data), connection.ready),
            connection,
        )
    except Exception:
        connection.close()
        raise
