"""FastAPI Web Server for BiteFinder.

Exposes REST endpoints for the dynamic webpage:
- GET  /api/health
- POST /api/auth/register
- POST /api/auth/login
- GET  /api/auth/me
- POST /api/auth/logout
- GET  /api/profile
- POST /api/profile
- GET  /api/recent-searches
- POST /api/search
"""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import secrets
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure project root and BIS are in sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
load_dotenv(ROOT / ".env")

from shared import db
from shared import debug_log
from shared import geocode_cache
from shared.seed_mongo import seed_if_empty
from BIS import data_manager as bis_data
from BIS.sources.profile_schema import CUISINES, empty_preferences, normalize_email, normalize_username
from BRNS import main as brns_main
from BRNS import io_manager as brns_io

app = FastAPI(
    title="BiteFinder API",
    description="Dynamic Web API for BiteFinder Singapore Restaurant Recommendation",
    version="1.2.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup_seed():
    """Auto-seed MongoDB collections and indexes on container startup if empty."""
    try:
        seed_if_empty()
    except Exception as exc:
        debug_log.debug_log(f"Startup MongoDB auto-seed warning: {exc}", "WARNING", "web_api.startup")


# ---------- Password & Session Helpers ----------

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), 100_000
    ).hex()


def _extract_token(authorization: str | None = None, token_param: str | None = None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if token_param:
        return token_param.strip()
    return None


def _sync_from_cli_users_file() -> None:
    """Sync any profile updates made via the BIS CLI (users.json) into MongoDB."""
    if not db.is_db_available():
        return
    try:
        users_path = getattr(bis_data, "USERS_FILE", ROOT / "BIS" / "data" / "users.json")
        if not users_path.exists():
            return
        with users_path.open("r", encoding="utf-8") as f:
            cli_users = json.load(f)
        if not isinstance(cli_users, dict):
            return
        database = db.get_db()
        for uid, udata in cli_users.items():
            if not isinstance(udata, dict):
                continue
            database.users.update_one(
                {"_id": uid},
                {
                    "$set": {
                        "userID": uid,
                        "email": udata.get("email", ""),
                        "email_verified": bool(udata.get("email_verified", False)),
                        "username": udata.get("username", "BiteFinder User"),
                        "preferences": udata.get("preferences") or {},
                    }
                },
                upsert=True,
            )
    except Exception as exc:
        debug_log.debug_log(f"CLI->Mongo sync warning: {exc}", "WARNING", "web_api.sync")


def _normalize_cli_list_items(items: list[str] | None, is_location: bool = False, lowercase: bool = False) -> list[str] | None:
    """Ensure list items contain at least one letter so BIS profile_schema.normalize_list accepts them."""
    if items is None:
        return None
    if not isinstance(items, list):
        return None
    cleaned: list[str] = []
    for raw in items:
        val = str(raw or "").strip()
        if lowercase:
            val = val.lower()
        if not val:
            continue
        if not any(c.isalpha() for c in val):
            prefix = "singapore" if lowercase else "Singapore"
            val = f"{prefix} {val}" if is_location else f"pref {val}"
        if val not in cleaned:
            cleaned.append(val)
    return cleaned


def _sync_to_cli_users_file(doc: dict[str, Any]) -> None:
    """Sync a Web UI user profile update back to BIS/data/users.json for the CLI."""
    email = str(doc.get("email") or "")
    if email == "webtest_suite_user@example.com":
        return
    try:
        users_path = getattr(bis_data, "USERS_FILE", ROOT / "BIS" / "data" / "users.json")
        cli_users: dict[str, Any] = {}
        if users_path.exists():
            with users_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    cli_users = loaded
        uid = str(doc.get("userID") or doc.get("_id"))
        pref = doc.get("preferences") or {}
        locs = _normalize_cli_list_items(pref.get("location"), is_location=True, lowercase=True)
        other_prefs = _normalize_cli_list_items(pref.get("other_preferences"), is_location=False, lowercase=True)
        raw_liked = pref.get("liked_cuisines")
        cli_liked = [str(c).strip().lower() for c in raw_liked if str(c).strip().lower() in CUISINES] if isinstance(raw_liked, list) else None
        raw_disliked = pref.get("disliked_cuisines")
        cli_disliked = [str(c).strip().lower() for c in raw_disliked if str(c).strip().lower() in CUISINES] if isinstance(raw_disliked, list) else None
        cli_users[uid] = {
            "userID": uid,
            "email": email,
            "email_verified": bool(doc.get("email_verified", False)),
            "username": doc.get("username", "BiteFinder User"),
            "preferences": {
                "location": locs if (isinstance(locs, list) and len(locs) > 0) else None,
                "max_distance_km": pref.get("max_distance_km"),
                "max_travel_time_minutes": pref.get("max_travel_time_minutes"),
                "budget_per_person": pref.get("budget_per_person"),
                "dietary_requirements": pref.get("dietary_requirements"),
                "liked_cuisines": cli_liked,
                "disliked_cuisines": cli_disliked,
                "other_preferences": other_prefs,
            },
        }
        users_path.parent.mkdir(parents=True, exist_ok=True)
        with users_path.open("w", encoding="utf-8") as f:
            json.dump(cli_users, f, indent=4, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        debug_log.debug_log(f"Mongo->CLI sync warning: {exc}", "WARNING", "web_api.sync")


def _get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token or not db.is_db_available():
        return None
    try:
        _sync_from_cli_users_file()
        database = db.get_db()
        session = database.sessions.find_one({"token": token})
        if not session:
            return None
        user_doc = database.users.find_one({"_id": session.get("user_id")})
        return user_doc
    except Exception:
        return None


def _format_user_response(doc: dict[str, Any]) -> dict[str, Any]:
    pref = doc.get("preferences") or {}
    return {
        "user_id": doc.get("userID") or doc.get("_id"),
        "username": doc.get("username", "BiteFinder User"),
        "email": doc.get("email", ""),
        "email_verified": bool(doc.get("email_verified", False)),
        "location": pref.get("location") or [],
        "max_distance_km": pref.get("max_distance_km"),
        "max_travel_time_minutes": pref.get("max_travel_time_minutes"),
        "budget_per_person": pref.get("budget_per_person"),
        "dietary_requirements": pref.get("dietary_requirements") or [],
        "liked_cuisines": pref.get("liked_cuisines") or [],
        "disliked_cuisines": pref.get("disliked_cuisines") or [],
        "other_preferences": pref.get("other_preferences") or [],
    }


# ---------- Pydantic Models ----------

class RegisterModel(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=6, max_length=128)


class LoginModel(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class SearchRequestModel(BaseModel):
    location: str = Field("", description="Singapore postal code, address, or landmark")
    locations: list[str] = Field(default_factory=list, description="Multiple Singapore addresses to find restaurants in between (Meet in the Middle)")
    mode: str = Field("walk", description="Travel mode: walk, drive, or transit")
    max_travel_minutes: float | None = Field(20.0, description="Maximum travel time in minutes")
    max_distance_km: float | None = Field(None, description="Maximum travel distance in kilometers")
    budget_per_person: float = Field(20.0, description="Max budget per person in SGD")
    dietary_requirements: list[str] = Field(default_factory=list, description="List of dietary requirements (e.g. ['halal'])")
    cuisine: str | None = Field(None, description="Specific desired cuisine")
    liked_cuisines: list[str] = Field(default_factory=list, description="Liked cuisines")
    disliked_cuisines: list[str] = Field(default_factory=list, description="Disliked cuisines")
    other_preferences: list[str] = Field(default_factory=list, description="Special requests e.g. ['at least 4.5 stars']")
    traffic_aware: bool = Field(False, description="Consider real-time traffic for driving")


class ProfileModel(BaseModel):
    user_id: str = "default_user"
    username: str = "BiteFinder User"
    email: str = "user@example.com"
    location: list[str] = Field(default_factory=list)
    max_distance_km: float | None = None
    max_travel_time_minutes: float | None = None
    budget_per_person: float | None = None
    dietary_requirements: list[str] = Field(default_factory=list)
    liked_cuisines: list[str] = Field(default_factory=list)
    disliked_cuisines: list[str] = Field(default_factory=list)
    other_preferences: list[str] = Field(default_factory=list)


class RouteRequestModel(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float
    name: str = "Restaurant"
    mode: str = "walk"
    traffic_aware: bool = False


class FavoriteToggleModel(BaseModel):
    restaurant: dict[str, Any]


def _make_place_key(restaurant: dict[str, Any]) -> str:
    """Create a deterministic unique key for a restaurant document."""
    pid = str(restaurant.get("google_place_id") or "").strip()
    if pid:
        return pid
    name = str(restaurant.get("name") or "restaurant").strip().lower()
    addr = str(restaurant.get("address") or "singapore").strip().lower()
    return f"{name}|{addr}"


def _resolve_user_scope(authorization: str | None) -> str:
    """Return the signed-in user's ID or 'guest' when unauthenticated."""
    user_doc = _get_user_by_token(_extract_token(authorization))
    if user_doc:
        return str(user_doc.get("userID") or user_doc.get("_id") or "guest")
    return "guest"


def _format_model_display(raw_model: str) -> str:
    """Format 'provider/model' into a clean display label e.g. 'Gemini AI (gemini-3.5-flash-lite)'."""
    clean = str(raw_model or "").strip()
    if not clean:
        return "Gemini AI"
    if "/" in clean:
        provider, model_name = clean.split("/", 1)
        p_lower = provider.lower()
        if p_lower == "gemini":
            return f"Gemini AI ({model_name})"
        if p_lower == "groq":
            return f"Groq AI ({model_name})"
        if p_lower == "openrouter":
            return f"OpenRouter AI ({model_name})"
    return clean


def _get_default_active_model() -> str:
    """Return the first configured AI model in BRNS MODEL_CHAIN."""
    chain = getattr(brns_main.config, "MODEL_CHAIN", [])
    for entry in chain:
        prov = entry.get("provider", "")
        mod = entry.get("model", "")
        if prov == "gemini" and getattr(brns_main.config, "GEMINI_API_KEY", ""):
            return _format_model_display(f"{prov}/{mod}")
        if prov == "openrouter" and getattr(brns_main.config, "OPENROUTER_API_KEY", ""):
            return _format_model_display(f"{prov}/{mod}")
        if prov == "groq" and getattr(brns_main.config, "GROQ_API_KEY", ""):
            return _format_model_display(f"{prov}/{mod}")
    return "Gemini AI"


_CURRENT_ACTIVE_MODEL: str = _get_default_active_model()


# ---------- Health & Metadata Endpoints ----------

@app.get("/api/health")
def health():
    """Health check for database, cache, and services."""
    mongo_ok = db.is_db_available()
    restaurants_count = 0
    if mongo_ok:
        try:
            restaurants_count = db.get_db().restaurants.count_documents({})
        except Exception:
            pass
    return {
        "status": "healthy",
        "database": "mongodb_connected" if mongo_ok else "mongodb_offline",
        "cached_restaurants_count": restaurants_count,
    }


@app.get("/api/cuisines")
def get_cuisines():
    """Return available cuisine tags."""
    return {"cuisines": sorted(list(CUISINES))}


@app.get("/api/active-model")
def get_active_model():
    """Return the AI model currently being tried or most recently used by BRNS."""
    return {"active_model": _CURRENT_ACTIVE_MODEL}


# ---------- Authentication Endpoints ----------

@app.post("/api/auth/register")
def register_user(req: RegisterModel):
    """Register a new user account in MongoDB and issue a session token."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")

    try:
        email = normalize_email(req.email)
        username = normalize_username(req.username)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    database = db.get_db()
    existing = database.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="This email is already registered. Please sign in.")

    user_id = str(uuid4())
    salt = secrets.token_hex(16)
    password_hash = _hash_password(req.password, salt)

    user_doc = {
        "_id": user_id,
        "userID": user_id,
        "email": email,
        "email_verified": True,
        "username": username,
        "password_salt": salt,
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "preferences": empty_preferences(),
    }
    database.users.insert_one(user_doc)
    _sync_to_cli_users_file(user_doc)

    token = secrets.token_urlsafe(32)
    database.sessions.insert_one({
        "token": token,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "success": True,
        "message": f"Welcome to BiteFinder, {username}!",
        "token": token,
        "user": _format_user_response(user_doc),
    }


@app.post("/api/auth/login")
def login_user(req: LoginModel):
    """Authenticate an existing user by email & password and issue a session token."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")

    try:
        email = normalize_email(req.email)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    _sync_from_cli_users_file()
    database = db.get_db()
    user_doc = database.users.find_one({"email": email})
    if not user_doc:
        raise HTTPException(status_code=401, detail="No account found with this email. Please sign up first.")

    stored_hash = user_doc.get("password_hash")
    stored_salt = user_doc.get("password_salt")

    if stored_hash and stored_salt:
        candidate_hash = _hash_password(req.password, stored_salt)
        if not secrets.compare_digest(candidate_hash, stored_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
    else:
        # Legacy CLI account without a password yet: set password on first web login
        if len(req.password) < 6:
            raise HTTPException(
                status_code=400,
                detail="This CLI account has no web password yet. Enter a password of at least 6 characters to set it.",
            )
        salt = secrets.token_hex(16)
        password_hash = _hash_password(req.password, salt)
        database.users.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"password_salt": salt, "password_hash": password_hash}},
        )

    user_id = user_doc.get("userID") or user_doc.get("_id")
    token = secrets.token_urlsafe(32)
    database.sessions.insert_one({
        "token": token,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "success": True,
        "message": f"Welcome back, {user_doc.get('username', 'User')}!",
        "token": token,
        "user": _format_user_response(user_doc),
    }


@app.get("/api/auth/me")
def get_current_user(authorization: str | None = Header(default=None), token: str | None = None):
    """Return the currently authenticated user profile from session token."""
    raw_token = _extract_token(authorization, token)
    user_doc = _get_user_by_token(raw_token)
    if not user_doc:
        raise HTTPException(status_code=401, detail="Not authenticated or session expired.")
    return {
        "authenticated": True,
        "user": _format_user_response(user_doc),
    }


@app.post("/api/auth/logout")
def logout_user(authorization: str | None = Header(default=None), token: str | None = None):
    """Invalidate the current session token."""
    raw_token = _extract_token(authorization, token)
    if raw_token and db.is_db_available():
        try:
            db.get_db().sessions.delete_one({"token": raw_token})
        except Exception:
            pass
    return {"success": True, "message": "Signed out successfully."}


# ---------- Profile & Recent Searches ----------

@app.get("/api/recent-searches")
def get_recent_searches(authorization: str | None = Header(default=None)):
    """Return recently searched locations from MongoDB strictly for the signed-in user."""
    if not db.is_db_available():
        return {"recent": []}
    try:
        user_doc = _get_user_by_token(_extract_token(authorization))
        if not user_doc:
            return {"recent": []}
        uid = str(user_doc.get("userID") or user_doc.get("_id"))
        docs = list(db.get_db().search_history.find(
            {"query": {"$exists": True, "$ne": ""}, "user_id": uid},
            {"query": 1, "_id": 0}
        ).sort("_id", -1).limit(25))

        seen = set()
        recent = []
        for d in docs:
            q = d.get("query", "").strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                recent.append(q)
            if len(recent) >= 6:
                break
        return {"recent": recent}
    except Exception as e:
        debug_log.debug_log(f"Failed to fetch recent searches: {e}", "WARNING", "web_api.get_recent_searches")
        return {"recent": []}


@app.get("/api/profile")
def get_profile(user_id: str | None = None, authorization: str | None = Header(default=None)):
    """Load user preferences from session token or user_id."""
    if db.is_db_available():
        try:
            doc = _get_user_by_token(_extract_token(authorization))
            if not doc and user_id and user_id != "default_user":
                doc = db.get_db().users.find_one({"_id": user_id})
            if doc:
                return _format_user_response(doc)
        except Exception as e:
            debug_log.debug_log(f"Profile fetch error: {e}", "WARNING", "web_api.get_profile")

    # Default guest fallback
    return ProfileModel().dict()


@app.post("/api/profile")
def save_profile(profile: ProfileModel, authorization: str | None = Header(default=None)):
    """Save user preferences into MongoDB for the signed-in user."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")

    database = db.get_db()
    auth_doc = _get_user_by_token(_extract_token(authorization))
    target_id = (auth_doc.get("userID") or auth_doc.get("_id")) if auth_doc else profile.user_id

    try:
        clean_username = normalize_username(profile.username)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    clean_locs = _normalize_cli_list_items([loc.strip() for loc in profile.location if loc and loc.strip()], is_location=True) or []
    other_prefs = _normalize_cli_list_items([p.strip() for p in profile.other_preferences if p.strip()], is_location=False) or []
    preferences = {
        "location": clean_locs if clean_locs else None,
        "max_distance_km": profile.max_distance_km,
        "max_travel_time_minutes": profile.max_travel_time_minutes,
        "budget_per_person": profile.budget_per_person,
        "dietary_requirements": [d.lower() for d in profile.dietary_requirements],
        "liked_cuisines": [c.lower() for c in profile.liked_cuisines if c],
        "disliked_cuisines": [c.lower() for c in profile.disliked_cuisines if c],
        "other_preferences": other_prefs,
    }

    existing = database.users.find_one({"_id": target_id})
    if existing:
        database.users.update_one(
            {"_id": target_id},
            {"$set": {"username": clean_username, "preferences": preferences}},
        )
        updated = database.users.find_one({"_id": target_id})
        if updated:
            _sync_to_cli_users_file(updated)
        return {
            "success": True,
            "message": "Profile preferences saved to your account.",
            "user": _format_user_response(updated),
        }

    doc = {
        "_id": target_id,
        "userID": target_id,
        "username": clean_username,
        "email": profile.email,
        "preferences": preferences,
    }
    database.users.replace_one({"_id": target_id}, doc, upsert=True)
    _sync_to_cli_users_file(doc)
    return {
        "success": True,
        "message": "Profile preferences saved.",
        "user": _format_user_response(doc),
    }


# ---------- Restaurant Search Endpoint ----------

@app.post("/api/search")
def search_restaurants(req: SearchRequestModel, authorization: str | None = Header(default=None)):
    """Execute full restaurant search pipeline."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    token = debug_log.start_trace()
    debug_log.debug_log(f"Web API search request for location: {req.location}", "INFO", "web_api.search")

    try:
        # 1. Collect and resolve one or more starting locations (supports "Meet in the Middle")
        raw_locations: list[str] = []
        for item in (req.locations or []):
            clean_loc = str(item or "").strip()
            if clean_loc and clean_loc not in raw_locations:
                raw_locations.append(clean_loc)
        if req.location and req.location.strip():
            primary_loc = req.location.strip()
            if primary_loc not in raw_locations:
                raw_locations.insert(0, primary_loc)

        if not raw_locations:
            raise HTTPException(status_code=400, detail="Please enter at least one starting location.")

        resolved_origins: list[dict[str, Any]] = []
        for loc_str in raw_locations:
            try:
                resolved_origins.append(bis_data.resolve_location(loc_str, api_key))
            except Exception as err:
                raise HTTPException(
                    status_code=400,
                    detail=f"Location '{loc_str}' could not be resolved: {err}",
                )

        if len(resolved_origins) == 1:
            origin = resolved_origins[0]
            history_query = raw_locations[0]
        else:
            mid_lat = round(sum(o["latitude"] for o in resolved_origins) / len(resolved_origins), 6)
            mid_lng = round(sum(o["longitude"] for o in resolved_origins) / len(resolved_origins), 6)
            short_names = [o["query"] for o in resolved_origins]
            history_query = " + ".join(short_names)[:200]
            origin = {
                "query": history_query,
                "label": f"Midpoint between {', '.join(short_names)}"[:500],
                "latitude": mid_lat,
                "longitude": mid_lng,
            }

        # Ensure travel limit conforms to BRNS rules: exactly one of distance or minutes
        minutes = req.max_travel_minutes
        distance = req.max_distance_km
        if minutes is not None and distance is not None:
            distance = None  # Default to time limit
        if minutes is None and distance is None:
            minutes = 20.0

        # Collect all selected preferred cuisines (supports multiple + custom typed cuisines)
        selected_cuisines: list[str] = []
        for raw_c in (req.liked_cuisines or []):
            for part in str(raw_c or "").split(","):
                c_clean = part.strip().lower()
                if c_clean and c_clean not in ("none", "any", "any cuisine") and c_clean not in selected_cuisines:
                    selected_cuisines.append(c_clean)
        if req.cuisine:
            for part in str(req.cuisine).split(","):
                c_clean = part.strip().lower()
                if c_clean and c_clean not in ("none", "any", "any cuisine") and c_clean not in selected_cuisines:
                    selected_cuisines.append(c_clean)

        base_other_prefs = _normalize_cli_list_items(list(req.other_preferences), is_location=False) or []
        base_disliked = [c.strip().lower() for c in req.disliked_cuisines if c and c.strip().lower() in CUISINES]

        def _build_payload_for_cuisine(c_target: str | None) -> dict[str, Any]:
            if not c_target:
                c_val = "none"
                other_p = list(base_other_prefs)
            elif c_target in CUISINES:
                c_val = c_target
                other_p = list(base_other_prefs)
            else:
                # Custom typed cuisine not in standard 20 CUISINES list
                c_val = "none"
                custom_wish = _normalize_cli_list_items([f"{c_target} cuisine"], is_location=False) or []
                other_p = list(base_other_prefs) + [w for w in custom_wish if w not in base_other_prefs]
            return {
                "origin": origin,
                "mode": req.mode if req.mode in ("walk", "drive", "transit") else "walk",
                "max_distance_km": distance,
                "max_travel_minutes": minutes,
                "traffic_aware": req.traffic_aware if req.mode == "drive" else False,
                "cuisine": c_val,
                "budget_per_person": req.budget_per_person,
                "other_preferences": other_p,
                "dietary_requirements": [d.lower() for d in req.dietary_requirements],
                "disliked_cuisines": base_disliked,
            }

        # 2. Execute BRNS search (Places + Routes + AI Ranking + Halal check)
        brns_main.config.MAX_MATCHES_SHOWN = 20
        brns_main.config.MAX_ALTERNATIVES_SHOWN = 20

        global _CURRENT_ACTIVE_MODEL
        _CURRENT_ACTIVE_MODEL = _get_default_active_model()
        captured_models: list[str] = []
        orig_log_ai = getattr(brns_main.ai_manager, "_log_ai_event", None)

        def _tracking_log_ai(context: str, detail: str, level: str = "WARNING"):
            global _CURRENT_ACTIVE_MODEL
            if isinstance(detail, str):
                if detail.startswith("Trying ") and detail.endswith("."):
                    raw_trying = detail[len("Trying "):-1].strip()
                    _CURRENT_ACTIVE_MODEL = _format_model_display(raw_trying)
                elif detail.startswith("Accepted ") and detail.endswith(" response."):
                    raw_accepted = detail[len("Accepted "):-len(" response.")].strip()
                    formatted = _format_model_display(raw_accepted)
                    _CURRENT_ACTIVE_MODEL = formatted
                    captured_models.append(formatted)
            if orig_log_ai:
                orig_log_ai(context, detail, level)

        cuisines_breakdown: dict[str, int] = {}

        if orig_log_ai:
            brns_main.ai_manager._log_ai_event = _tracking_log_ai
        try:
            if len(selected_cuisines) <= 1:
                single_c = selected_cuisines[0] if selected_cuisines else None
                payload = _build_payload_for_cuisine(single_c)
                search_results = brns_main.search(json.dumps(payload))
                if single_c:
                    for item in search_results.get("matches", []) + search_results.get("alternatives", []):
                        if isinstance(item, dict):
                            item["matched_cuisine"] = single_c
                    cuisines_breakdown[single_c] = len(search_results.get("matches", [])) + len(search_results.get("alternatives", []))
            else:
                # Multiple preferred cuisines selected: divide outputs by the number of cuisines selected
                num_cuisines = len(selected_cuisines)
                combined_matches: list[dict[str, Any]] = []
                combined_alternatives: list[dict[str, Any]] = []
                combined_exclusions: list[Any] = []
                seen_keys: set[str] = set()
                last_empty_error: Exception | None = None

                for c_target in selected_cuisines:
                    sub_payload = _build_payload_for_cuisine(c_target)
                    try:
                        sub_res = brns_main.search(json.dumps(sub_payload))
                    except Exception as sub_exc:
                        sub_msg = str(sub_exc)
                        if "No restaurants found" in sub_msg or "no confirmed open" in sub_msg.lower():
                            last_empty_error = sub_exc
                            cuisines_breakdown[c_target] = 0
                            continue
                        raise

                    raw_m = [
                        dict(m, matched_cuisine=c_target)
                        for m in sub_res.get("matches", [])
                        if _make_place_key(m.get("restaurant") or {}) not in seen_keys
                    ]
                    raw_a = [
                        dict(a, matched_cuisine=c_target)
                        for a in sub_res.get("alternatives", [])
                        if _make_place_key(a.get("restaurant") or {}) not in seen_keys
                    ]
                    total_for_c = len(raw_m) + len(raw_a)
                    if total_for_c == 0:
                        cuisines_breakdown[c_target] = 0
                        continue

                    # Divide this cuisine's outputs by the number of cuisines selected
                    quota_for_c = min(
                        max(1, 20 // num_cuisines),
                        max(1, math.ceil(total_for_c / num_cuisines)),
                    )
                    taken_m = raw_m[:quota_for_c]
                    rem_slots = max(0, quota_for_c - len(taken_m))
                    taken_a = raw_a[:rem_slots]

                    for item in taken_m + taken_a:
                        seen_keys.add(_make_place_key(item.get("restaurant") or {}))
                    combined_matches.extend(taken_m)
                    combined_alternatives.extend(taken_a)
                    combined_exclusions.extend(sub_res.get("exclusions", []))
                    cuisines_breakdown[c_target] = len(taken_m) + len(taken_a)

                if not combined_matches and not combined_alternatives and last_empty_error is not None:
                    raise last_empty_error

                search_results = {
                    "matches": combined_matches,
                    "alternatives": combined_alternatives,
                    "exclusions": combined_exclusions,
                }
        finally:
            if orig_log_ai:
                brns_main.ai_manager._log_ai_event = orig_log_ai

        model_used = captured_models[-1] if captured_models else _CURRENT_ACTIVE_MODEL
        cuisine_summary_str = ", ".join(selected_cuisines)

        # 3. Store search in MongoDB history if database is available
        if db.is_db_available():
            try:
                auth_user = _get_user_by_token(_extract_token(authorization))
                uid = (auth_user.get("userID") or auth_user.get("_id")) if auth_user else "guest"
                matches_list = search_results.get("matches", [])
                alt_list = search_results.get("alternatives", [])
                db.get_db().search_history.insert_one({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": uid,
                    "query": history_query,
                    "locations": raw_locations,
                    "origin": origin,
                    "input_origins": resolved_origins,
                    "mode": req.mode,
                    "max_travel_minutes": minutes,
                    "max_distance_km": distance,
                    "traffic_aware": bool(req.traffic_aware and req.mode == "drive"),
                    "budget_per_person": req.budget_per_person,
                    "dietary_requirements": [d.lower() for d in req.dietary_requirements],
                    "cuisine": cuisine_summary_str,
                    "liked_cuisines": selected_cuisines,
                    "disliked_cuisines": [c.lower() for c in req.disliked_cuisines],
                    "other_preferences": req.other_preferences,
                    "model_used": model_used,
                    "matches_count": len(matches_list),
                    "alternatives_count": len(alt_list),
                    "results_count": len(matches_list) + len(alt_list),
                })
            except Exception:
                pass

        return {
            "success": True,
            "origin": origin,
            "input_origins": resolved_origins,
            "model_used": model_used,
            "selected_cuisines": selected_cuisines,
            "cuisines_breakdown": cuisines_breakdown,
            "matches": search_results.get("matches", []),
            "alternatives": search_results.get("alternatives", []),
            "exclusions_count": len(search_results.get("exclusions", [])),
        }

    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc)
        if "No restaurants found" in msg or "no confirmed open" in msg.lower():
            return {
                "success": True,
                "origin": origin if 'origin' in locals() else None,
                "matches": [],
                "alternatives": [],
                "exclusions_count": 0,
                "message": (
                    "No open restaurants found near this location right now. "
                    "Note: In Singapore, many mall outlets close after 10:00 PM. "
                    "Try searching a 24-hour hotspot (e.g. 'Rivervale Plaza' or 'Jewel Changi') or increasing travel limits."
                ),
            }
        debug_log.debug_log(f"Search failed: {exc}", "ERROR", "web_api.search")
        raise HTTPException(status_code=500, detail=f"Search execution failed: {str(exc)}")
    finally:
        debug_log.end_trace(token)


@app.post("/api/route")
def get_restaurant_route(req: RouteRequestModel):
    """Fetch turn-by-turn directions from Google Routes API via BRNS.main.route_to."""
    mode = req.mode if req.mode in ("walk", "drive", "transit") else "walk"
    restaurant_arg = {
        "name": req.name,
        "lat": req.dest_lat,
        "lng": req.dest_lng,
    }
    request_arg = {
        "origin": {
            "latitude": req.origin_lat,
            "longitude": req.origin_lng,
        },
        "mode": mode,
        "traffic_aware": req.traffic_aware if mode == "drive" else False,
    }
    try:
        result = brns_main.route_to(restaurant_arg, request_arg)
        return {
            "success": True,
            "name": result.get("name", req.name),
            "mode": result.get("mode", mode),
            "traffic_aware": result.get("traffic_aware", False),
            "route": result.get("route"),
            "link": result.get("link"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch route: {exc}")


# ---------- Saved Favorites / Bookmarks Endpoints ----------

@app.get("/api/favorites")
def get_favorites(authorization: str | None = Header(default=None)):
    """Return bookmarked restaurants from MongoDB strictly for the signed-in user."""
    if not db.is_db_available():
        return {"favorites": [], "count": 0}
    user_scope = _resolve_user_scope(authorization)
    if user_scope == "guest":
        return {"favorites": [], "count": 0}
    try:
        docs = list(
            db.get_db().favorites.find(
                {"user_id": user_scope},
                {"_id": 0},
            ).sort("saved_at", -1)
        )
        return {"favorites": docs, "count": len(docs)}
    except Exception as exc:
        debug_log.debug_log(f"Failed to fetch favorites: {exc}", "WARNING", "web_api.get_favorites")
        return {"favorites": [], "count": 0}


@app.post("/api/favorites")
def toggle_favorite(req: FavoriteToggleModel, authorization: str | None = Header(default=None)):
    """Toggle a restaurant bookmark in MongoDB (add if not saved, remove if already saved)."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")
    user_scope = _resolve_user_scope(authorization)
    if user_scope == "guest":
        raise HTTPException(status_code=401, detail="Please sign in to save favorite restaurants.")
    place_key = _make_place_key(req.restaurant)
    database = db.get_db()

    existing = database.favorites.find_one({"user_id": user_scope, "place_key": place_key})
    if existing:
        database.favorites.delete_one({"user_id": user_scope, "place_key": place_key})
        count = database.favorites.count_documents({"user_id": user_scope})
        return {
            "success": True,
            "action": "removed",
            "place_key": place_key,
            "count": count,
        }

    doc = {
        "user_id": user_scope,
        "place_key": place_key,
        "restaurant": req.restaurant,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    database.favorites.insert_one(doc)
    count = database.favorites.count_documents({"user_id": user_scope})
    return {
        "success": True,
        "action": "added",
        "place_key": place_key,
        "count": count,
    }


@app.delete("/api/favorites")
def remove_favorite(place_key: str, authorization: str | None = Header(default=None)):
    """Remove a specific bookmarked restaurant from MongoDB by place_key."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")
    user_scope = _resolve_user_scope(authorization)
    if user_scope == "guest":
        raise HTTPException(status_code=401, detail="Please sign in to manage favorite restaurants.")
    database = db.get_db()
    database.favorites.delete_one({"user_id": user_scope, "place_key": place_key})
    count = database.favorites.count_documents({"user_id": user_scope})
    return {"success": True, "place_key": place_key, "count": count}


# ---------- Full Search History Endpoints ----------

@app.get("/api/history")
def get_search_history(authorization: str | None = Header(default=None)):
    """Return recent search history entries from MongoDB strictly for the signed-in user."""
    if not db.is_db_available():
        return {"history": []}
    try:
        user_doc = _get_user_by_token(_extract_token(authorization))
        if not user_doc:
            return {"history": []}
        database = db.get_db()
        uid = str(user_doc.get("userID") or user_doc.get("_id"))
        raw_docs = list(database.search_history.find({"user_id": uid}).sort("_id", -1).limit(20))

        history = []
        for d in raw_docs:
            history.append({
                "id": str(d.get("_id", "")),
                "timestamp": d.get("timestamp", ""),
                "query": d.get("query", ""),
                "locations": d.get("locations") or [],
                "mode": d.get("mode", "walk"),
                "max_travel_minutes": d.get("max_travel_minutes"),
                "max_distance_km": d.get("max_distance_km"),
                "traffic_aware": bool(d.get("traffic_aware", False)),
                "budget_per_person": d.get("budget_per_person", 30),
                "dietary_requirements": d.get("dietary_requirements") or [],
                "cuisine": d.get("cuisine") or "",
                "liked_cuisines": d.get("liked_cuisines") or [],
                "disliked_cuisines": d.get("disliked_cuisines") or [],
                "other_preferences": d.get("other_preferences") or [],
                "matches_count": d.get("matches_count"),
                "alternatives_count": d.get("alternatives_count"),
                "results_count": d.get("results_count", 0),
            })
        return {"history": history}
    except Exception as exc:
        debug_log.debug_log(f"Failed to fetch search history: {exc}", "WARNING", "web_api.get_search_history")
        return {"history": []}


@app.delete("/api/history")
def clear_search_history(authorization: str | None = Header(default=None)):
    """Clear search history in MongoDB for the current user (or guest)."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")
    user_doc = _get_user_by_token(_extract_token(authorization))
    database = db.get_db()
    if user_doc:
        uid = str(user_doc.get("userID") or user_doc.get("_id"))
        database.search_history.delete_many({"user_id": uid})
    else:
        database.search_history.delete_many({"user_id": {"$in": [None, "guest"]}})
    return {"success": True, "message": "Search history cleared."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_api:app", host="0.0.0.0", port=8000, reload=True)
