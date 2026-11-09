"""FastAPI Web Server for BiteFinder.

Exposes REST endpoints for the dynamic webpage:
- GET  /api/health
- GET  /api/profile
- POST /api/profile
- POST /api/search
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
from BIS.sources.profile_schema import CUISINES
from BRNS import main as brns_main
from BRNS import io_manager as brns_io

app = FastAPI(
    title="BiteFinder API",
    description="Dynamic Web API for BiteFinder Singapore Restaurant Recommendation",
    version="1.0.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    max_travel_time_minutes: float | None = 20.0
    budget_per_person: float = 25.0
    dietary_requirements: list[str] = Field(default_factory=list)
    liked_cuisines: list[str] = Field(default_factory=list)
    disliked_cuisines: list[str] = Field(default_factory=list)
    other_preferences: list[str] = Field(default_factory=list)


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


@app.get("/api/recent-searches")
def get_recent_searches():
    """Return recently searched locations from MongoDB."""
    if not db.is_db_available():
        return {"recent": []}
    try:
        docs = list(db.get_db().search_history.find(
            {"query": {"$exists": True, "$ne": ""}},
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
def get_profile(user_id: str = "default_user"):
    """Load user preferences from MongoDB or fall back to default profile."""
    if db.is_db_available():
        try:
            doc = db.get_db().users.find_one({"_id": user_id})
            if not doc:
                # Try finding any existing user
                doc = db.get_db().users.find_one()
            if doc:
                pref = doc.get("preferences", {})
                return {
                    "user_id": doc.get("userID", user_id),
                    "username": doc.get("username", "BiteFinder User"),
                    "email": doc.get("email", ""),
                    "location": pref.get("location", ["Compass One"]),
                    "max_distance_km": pref.get("max_distance_km", 1.5),
                    "max_travel_time_minutes": pref.get("max_travel_time_minutes", 20.0),
                    "budget_per_person": pref.get("budget_per_person", 20.0),
                    "dietary_requirements": pref.get("dietary_requirements", []),
                    "liked_cuisines": pref.get("liked_cuisines", []),
                    "disliked_cuisines": pref.get("disliked_cuisines", []),
                    "other_preferences": pref.get("other_preferences", []),
                }
        except Exception as e:
            debug_log.debug_log(f"Profile fetch error: {e}", "WARNING", "web_api.get_profile")

    # Default fallback
    return ProfileModel().dict()


@app.post("/api/profile")
def save_profile(profile: ProfileModel):
    """Save user preferences into MongoDB."""
    if not db.is_db_available():
        raise HTTPException(status_code=503, detail="Database is not available")

    doc = {
        "userID": profile.user_id,
        "username": profile.username,
        "email": profile.email,
        "preferences": {
            "location": profile.location,
            "max_distance_km": profile.max_distance_km,
            "max_travel_time_minutes": profile.max_travel_time_minutes,
            "budget_per_person": profile.budget_per_person,
            "dietary_requirements": profile.dietary_requirements,
            "liked_cuisines": profile.liked_cuisines,
            "disliked_cuisines": profile.disliked_cuisines,
            "other_preferences": profile.other_preferences,
        },
    }
    db.get_db().users.replace_one({"_id": profile.user_id}, doc, upsert=True)
    return {"success": True, "message": "Profile saved successfully."}


@app.post("/api/search")
def search_restaurants(req: SearchRequestModel):
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
        # Allow the Web UI to display up to 20 matches and 20 alternatives
        brns_main.config.MAX_MATCHES_SHOWN = 20
        brns_main.config.MAX_ALTERNATIVES_SHOWN = 20
        serialized_payload = json.dumps(payload)
        search_results = brns_main.search(serialized_payload)

        # 3. Store search in MongoDB history if database is available
        if db.is_db_available():
            try:
                db.get_db().search_history.insert_one({
                    "timestamp": brns_io.config.datetime.now().isoformat() if hasattr(brns_io.config, "datetime") else None,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_api:app", host="0.0.0.0", port=8000, reload=True)
