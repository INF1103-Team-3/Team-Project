"""BRC Data Manager: all subsystem persistence and retrieval."""

import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from BRC.classes.data.storage.data_unavailable_error import DataUnavailableError
from BRC.classes.data.storage.json_file import JsonFile
from BRC.models import (
    SOURCE_URL,
    CuisineCache,
    HalalDatabase,
    HalalOutlet,
    MuisSnapshot,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_MUIS_PATH = DATA_DIR / "muis_establishments.json"
CLEAN_DATABASE_PATH = DATA_DIR / "halal_restaurants.json"


class DataManager:
    """Own BRC JSON files and translate them into domain records."""

    _CLEAN_DB_LOCK = Lock()
    _CLEAN_DB_CACHE = {}

    def __init__(self, folder=DATA_DIR, raw_path=None, clean_path=None,
                 cuisine_cache_path=None):
        folder = Path(folder)
        self._raw = JsonFile(raw_path or folder / RAW_MUIS_PATH.name)
        self._clean = JsonFile(clean_path or folder / CLEAN_DATABASE_PATH.name)
        if cuisine_cache_path:
            cache_path = Path(cuisine_cache_path)
        elif raw_path and Path(raw_path) != RAW_MUIS_PATH:
            cache_path = self._clean.path.with_name("cuisine_tags_cache.json")
        else:
            cache_path = folder / "cuisine_tags_cache.json"
        self._cuisine_cache = JsonFile(cache_path)
        self._checked_cache = JsonFile(
            folder / "checked_restaurants_cache.json")
        self._single_result = folder / "checked_restaurant.json"
        self._batch_result = folder / "checked_restaurants.json"
        self._scrape_progress = JsonFile(folder / "scrape_progress.json")
        self._geocode_cache = JsonFile(folder / "onemap_cache.json")

    @property
    def clean_path(self):
        return self._clean.path

    @property
    def checked_cache_path(self):
        return self._checked_cache.path

    @property
    def scrape_progress_file(self):
        return self._scrape_progress

    @property
    def geocode_cache_file(self):
        return self._geocode_cache

    def result_path(self, single, output=None):
        if output:
            return Path(output)
        return self._single_result if single else self._batch_result

    def load_raw_snapshot(self, current=True):
        value = self._raw.read()
        try:
            return MuisSnapshot.from_dict(value).validate(current)
        except ValueError as error:
            raise DataUnavailableError(str(error)) from error

    def save_raw_snapshot(self, snapshot):
        snapshot.validate(current=False)
        self._raw.write(snapshot.to_dict())

    def load_clean_database(self):
        path = self._clean.path
        try:
            stat = path.stat()
            stamp = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if stamp is not None:
            with self._CLEAN_DB_LOCK:
                cached = self._CLEAN_DB_CACHE.get(stamp[0])
                if cached and cached[0] == stamp:
                    return cached[1]
        value = self._clean.read()
        try:
            database = self._database_from_json(value)
        except ValueError as error:
            raise DataUnavailableError(str(error)) from error
        if stamp is not None:
            with self._CLEAN_DB_LOCK:
                self._CLEAN_DB_CACHE[stamp[0]] = (stamp, database)
        return database

    def save_clean_database(self, database):
        if len(database) == 0:
            raise DataUnavailableError(
                "Refusing to save an incomplete cleaned database.")
        self._clean.write({
            "source_url": database.source_url,
            "source_fetched_at": database.source_fetched_at,
            "built_at": self._now(),
            "restaurant_count": len(database),
            "restaurants": database.to_list(),
        })

    def load(self):
        try:
            return list(self.load_clean_database())
        except (DataUnavailableError, OSError):
            from common.debug_log import debug_log
            debug_log(
                "Cleaned BRC database is unavailable; returning no records.",
                "ERROR", "BRC.data.load")
            return []

    def query(self, keep):
        return [outlet for outlet in self.load() if keep(outlet)]

    def load_cuisine_cache(self):
        try:
            value = self._cuisine_cache.read()
        except DataUnavailableError:
            return CuisineCache()
        tags = value.get("tags") if isinstance(value, dict) else None
        valid = (
            isinstance(tags, dict)
            and value.get("version") == 1
            and all(
                isinstance(items, list)
                and all(isinstance(tag, str) for tag in items)
                for items in tags.values()))
        return CuisineCache(tags) if valid else CuisineCache()

    def save_cuisine_cache(self, cache):
        tags = cache.to_dict()
        self._cuisine_cache.write({
            "version": 1,
            "updated_at": self._now(),
            "entry_count": len(tags),
            "tags": tags,
        })

    def bootstrap_cuisine_cache(self, snapshot, cache):
        try:
            database = self.load_clean_database()
        except (DataUnavailableError, OSError):
            return 0
        added = 0
        for listing in snapshot.listings:
            outlet = database.get(listing.certificate_number)
            if (listing not in cache and outlet is not None
                    and outlet.cuisines):
                cache.put(listing, outlet.cuisines)
                added += 1
        return added

    def save_checked_result(self, result, single, output=None):
        merged = {
            self._restaurant_key(row): row
            for row in self._load_checked_cache()
        }
        for row in ([result] if single else result):
            merged[self._restaurant_key(row)] = row
        self._checked_cache.write({
            "updated_at": self._now(),
            "restaurant_count": len(merged),
            "restaurants": list(merged.values()),
        }, compact_hours=True)
        JsonFile(self.result_path(single, output)).write(
            result, compact_hours=True)
        return result

    def _load_checked_cache(self):
        if not self._checked_cache.exists():
            return []
        try:
            value = self._checked_cache.read()
        except DataUnavailableError:
            return []
        rows = value.get("restaurants", []) if isinstance(value, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _database_from_json(value):
        restaurants = (
            value.get("restaurants") if isinstance(value, dict) else None)
        if (not isinstance(restaurants, list) or not restaurants
                or value.get("restaurant_count") != len(restaurants)
                or not isinstance(value.get("source_fetched_at"), str)):
            raise ValueError(
                "The cleaned halal restaurant database is invalid.")
        outlets = [HalalOutlet.from_dict(row) for row in restaurants]
        return HalalDatabase(
            outlets, value.get("source_url", SOURCE_URL),
            value["source_fetched_at"])

    @staticmethod
    def _restaurant_key(row):
        place_id = row.get("google_place_id") or row.get("place_id")
        if isinstance(place_id, str) and place_id:
            return "google:" + place_id
        check = row.get("muis_check")
        if isinstance(check, dict) and check.get("certificate_number"):
            return "muis:" + str(check["certificate_number"])
        address = " ".join(re.findall(
            r"[a-z0-9]+", str(row.get("address") or "").casefold()))
        name = " ".join(re.findall(
            r"[a-z0-9]+", str(row.get("name") or "").casefold()))
        return f"outlet:{row.get('postal_code') or ''}:{address}:{name}"

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
