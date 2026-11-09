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
from BIS import data_manager as bis_data
from BIS.sources.profile_schema import CUISINES, normalize_email, normalize_username
from BRNS import main as brns_main
from BRNS import io_manager as brns_io

app = FastAPI(
    title="BiteFinder API",
    description="Dynamic Web API for BiteFinder Singapore Restaurant Recommendation",
    version="1.1.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token or not db.is_db_available():
        return None
    try:
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
        "location": pref.get("location") or ["Compass One"],
        "max_distance_km": pref.get("max_distance_km", 1.5),
        "max_travel_time_minutes": pref.get("max_travel_time_minutes", 30.0),
        "budget_per_person": pref.get("budget_per_person", 30.0),
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
    location: str = Field(..., description="Singapore postal code, address, or landmark")
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
    location: list[str] = Field(default_factory=lambda: ["Compass One"])
    max_distance_km: float | None = 1.5
    max_travel_time_minutes: float | None = 30.0
    budget_per_person: float = 30.0
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
        "preferences": {
            "location": ["Compass One"],
            "max_distance_km": 1.5,
            "max_travel_time_minutes": 30.0,
            "budget_per_person": 30.0,
            "dietary_requirements": [],
            "liked_cuisines": [],
            "disliked_cuisines": [],
            "other_preferences": [],
        },
    }
    database.users.insert_one(user_doc)

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
    """Return recently searched locations from MongoDB (scoped to user if signed in)."""
    if not db.is_db_available():
        return {"recent": []}
    try:
        user_doc = _get_user_by_token(_extract_token(authorization))
        query_filter: dict[str, Any] = {"query": {"$exists": True, "$ne": ""}}
        if user_doc:
            uid = user_doc.get("userID") or user_doc.get("_id")
            user_docs = list(db.get_db().search_history.find(
                {"query": {"$exists": True, "$ne": ""}, "user_id": uid},
                {"query": 1, "_id": 0}
            ).sort("_id", -1).limit(25))
            if user_docs:
                docs = user_docs
            else:
                docs = list(db.get_db().search_history.find(
                    query_filter, {"query": 1, "_id": 0}
                ).sort("_id", -1).limit(25))
        else:
            docs = list(db.get_db().search_history.find(
                query_filter, {"query": 1, "_id": 0}
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

    preferences = {
        "location": [loc.strip() for loc in profile.location if loc.strip()] or ["Compass One"],
        "max_distance_km": profile.max_distance_km,
        "max_travel_time_minutes": profile.max_travel_time_minutes,
        "budget_per_person": profile.budget_per_person,
        "dietary_requirements": [d.lower() for d in profile.dietary_requirements],
        "liked_cuisines": [c.lower() for c in profile.liked_cuisines if c],
        "disliked_cuisines": [c.lower() for c in profile.disliked_cuisines if c],
        "other_preferences": [p.strip() for p in profile.other_preferences if p.strip()],
    }

    existing = database.users.find_one({"_id": target_id})
    if existing:
        database.users.update_one(
            {"_id": target_id},
            {"$set": {"username": clean_username, "preferences": preferences}},
        )
        updated = database.users.find_one({"_id": target_id})
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
        # 1. Resolve origin
        try:
            origin = bis_data.resolve_location(req.location, api_key)
        except Exception as err:
            raise HTTPException(status_code=400, detail=f"Location could not be resolved: {err}")

        # Ensure travel limit conforms to BRNS rules: exactly one of distance or minutes
        minutes = req.max_travel_minutes
        distance = req.max_distance_km
        if minutes is not None and distance is not None:
            distance = None  # Default to time limit
        if minutes is None and distance is None:
            minutes = 20.0

        # Construct the validated 10-field BRNS search payload
        cuisine_val = req.cuisine.lower() if req.cuisine and req.cuisine.lower() in CUISINES else "none"
        payload = {
            "origin": origin,
            "mode": req.mode if req.mode in ("walk", "drive", "transit") else "walk",
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": req.traffic_aware if req.mode == "drive" else False,
            "cuisine": cuisine_val,
            "budget_per_person": req.budget_per_person,
            "other_preferences": req.other_preferences,
            "dietary_requirements": [d.lower() for d in req.dietary_requirements],
            "disliked_cuisines": [c.lower() for c in req.disliked_cuisines],
        }

        # 2. Execute BRNS search (Places + Routes + AI Ranking + Halal check)
        brns_main.config.MAX_MATCHES_SHOWN = 20
        brns_main.config.MAX_ALTERNATIVES_SHOWN = 20
        serialized_payload = json.dumps(payload)
        search_results = brns_main.search(serialized_payload)

        # 3. Store search in MongoDB history if database is available
        if db.is_db_available():
            try:
                auth_user = _get_user_by_token(_extract_token(authorization))
                uid = (auth_user.get("userID") or auth_user.get("_id")) if auth_user else None
                db.get_db().search_history.insert_one({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": uid,
                    "query": req.location,
                    "origin": origin,
                    "mode": req.mode,
                    "results_count": len(search_results.get("matches", [])) + len(search_results.get("alternatives", [])),
                })
            except Exception:
                pass

        return {
            "success": True,
            "origin": origin,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_api:app", host="0.0.0.0", port=8000, reload=True)
