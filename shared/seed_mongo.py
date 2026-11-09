"""Seed existing JSON file data into MongoDB."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.db import get_db
USERS_FILE = ROOT / "BIS" / "data" / "users.json"
RESTAURANTS_FILE = ROOT / "BRNS" / "data" / "restaurants.json"
GEOCODE_FILE = ROOT / "data" / "geocode_cache.json"
HALAL_FILE = ROOT / "BRC" / "data" / "halal_restaurants.json"


def seed():
    db = get_db()
    print("Connecting to MongoDB...")

    # 1. Seed Users
    if USERS_FILE.exists():
        try:
            users_data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(users_data, dict):
                count = 0
                for user_id, doc in users_data.items():
                    doc["_id"] = user_id
                    db.users.replace_one({"_id": user_id}, doc, upsert=True)
                    count += 1
                print(f"Seeded {count} user(s) into 'users' collection.")
        except Exception as e:
            print(f"Failed to seed users: {e}")

    # 2. Seed Restaurants
    if RESTAURANTS_FILE.exists():
        try:
            restaurants_data = json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8"))
            if isinstance(restaurants_data, list):
                count = 0
                for r in restaurants_data:
                    place_id = r.get("google_place_id") or r.get("place_id")
                    if place_id:
                        r["_id"] = place_id
                        db.restaurants.replace_one({"_id": place_id}, r, upsert=True)
                        count += 1
                # Create index on name and cuisines for faster search
                db.restaurants.create_index("name")
                db.restaurants.create_index("cuisines")
                print(f"Seeded {count} restaurant(s) into 'restaurants' collection.")
        except Exception as e:
            print(f"Failed to seed restaurants: {e}")

    # 3. Seed Geocode Cache
    if GEOCODE_FILE.exists():
        try:
            geo_data = json.loads(GEOCODE_FILE.read_text(encoding="utf-8"))
            if isinstance(geo_data, dict):
                count = 0
                for key, val in geo_data.items():
                    db.geocode_cache.replace_one(
                        {"_id": key},
                        {"_id": key, "query": key, "data": val},
                        upsert=True
                    )
                    count += 1
                print(f"Seeded {count} geocode entry/entries into 'geocode_cache' collection.")
        except Exception as e:
            print(f"Failed to seed geocode cache: {e}")

    # 4. Seed Halal Restaurants (if present)
    if HALAL_FILE.exists():
        try:
            halal_data = json.loads(HALAL_FILE.read_text(encoding="utf-8"))
            if isinstance(halal_data, list):
                count = 0
                for h in halal_data:
                    cert = h.get("cert_no") or h.get("name")
                    if cert:
                        db.halal_restaurants.replace_one({"_id": cert}, h, upsert=True)
                        count += 1
                print(f"Seeded {count} halal restaurant(s) into 'halal_restaurants' collection.")
        except Exception as e:
            print(f"Failed to seed halal restaurants: {e}")

    print("Database seeding completed.")


if __name__ == "__main__":
    seed()
