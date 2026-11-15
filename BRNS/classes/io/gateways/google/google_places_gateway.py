"""Google Places/geocoding transport and provider response mapping."""

import math
import requests


class GooglePlacesGateway:
    "Execute planned searches without deciding the discovery fallback policy."

    def __init__(
        self, config, rules, policy, logger, error_reporter, distance, cache
    ):
        self._config, self._rules, self._policy = config, rules, policy
        self._log, self._error = logger, error_reporter
        self._distance, self._cache = distance, cache

    def money_to_float(self, money):
        """Google Money object -> float (e.g. {'units': '20', 'nanos': 0}
        -> 20.0).
        """
        if not isinstance(money, dict) or "units" not in money:
            return None
        try:
            return (
                float(money["units"])
                + (money.get("nanos", 0) or 0) / 1000000000.0
            )
        except (TypeError, ValueError):
            return None

    def fmt_price_range(self, pr):
        "priceRange object -> display string like '$20-70'. None if absent."
        if not isinstance(pr, dict):
            return None
        start = self.money_to_float(pr.get("startPrice"))
        end = self.money_to_float(pr.get("endPrice"))
        if start is None and end is None:
            return None
        if start is None:
            return f"up to ${end:.0f}"
        if end is None or end <= start:
            return f"from ${start:.0f}"
        return f"${start:.0f}-{end:.0f}"

    def geocode_location(self, address_text):
        "'postal code' / 'landmark' -> (lat, lng) or None. Cached globally."
        key = (address_text or "").strip()
        if not key:
            return None
        cached = self._cache.lookup(key)
        if cached:
            self._log.debug_log(
                "Geocode cache hit.",
                "DEBUG",
                "BRNS.io_manager.geocode_location",
            )
            return cached
        self._log.debug_log(
            "Geocoding request started.",
            "INFO",
            "BRNS.io_manager.geocode_location",
        )
        try:
            resp = requests.get(
                self._config.GEOCODE_URL,
                params={
                    "address": address_text,
                    "key": self._config.GOOGLE_MAPS_API_KEY,
                },
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return None
            loc = results[0]["geometry"]["location"]
            self._cache.remember((key,), loc["lat"], loc["lng"])
            self._log.debug_log(
                "Geocoding result cached.",
                "INFO",
                "BRNS.io_manager.geocode_location",
            )
            return (loc["lat"], loc["lng"])
        except (
            requests.RequestException,
            KeyError,
            ValueError,
            RuntimeError,
        ) as err:
            self._error("geocode_location", err)
            return None

    def weekday_index(self, name):
        days = (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
        return days.index(name.lower()) if name.lower() in days else None

    def hours_string_for_day(self, regular_hours, weekday_index):
        """regularOpeningHours.periods -> 'HH:MM-HH:MM' for the given day,
        or None.
                Google weekday index: 0=Sunday..6=Saturday. Handles
        past-midnight closes
                by using the period's OPEN day (e.g. Fri 18:00-02:00
        shows under Friday).
        """
        if not isinstance(regular_hours, dict):
            return None
        for period in regular_hours.get("periods", []):
            open_info = period.get("open", {})
            close_info = period.get("close", {})
            if open_info.get("day") != weekday_index:
                continue
            o_h, o_m = (open_info.get("hour", 0), open_info.get("minute", 0))
            if close_info:
                c_h, c_m = (
                    close_info.get("hour", 0),
                    close_info.get("minute", 0),
                )
            else:
                c_h, c_m = (23, 59)
            return f"{o_h:02d}:{o_m:02d}-{c_h:02d}:{c_m:02d}"
        return None

    def parse_place(self, p):
        """Raw Google place object -> our normalized dict (or None if
        unusable).
                Also converts regular hours into the full weekly
        schedule.
        """
        name = (p.get("displayName") or {}).get("text")
        point = p.get("location") or {}
        if not name or "latitude" not in point or "longitude" not in point:
            return None
        pr = p.get("priceRange") or {}
        current_hours = p.get("currentOpeningHours")
        regular_hours = p.get("regularOpeningHours")
        weekly = self._rules.weekly_opening_hours(regular_hours)
        return {
            "google_place_id": p.get("id"),
            "name": name,
            "address": p.get("formattedAddress", "unavailable"),
            "postal_code": (p.get("postalAddress") or {}).get("postalCode"),
            "number": p.get("nationalPhoneNumber"),
            "lat": point["latitude"],
            "lng": point["longitude"],
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount"),
            "serves_vegetarian_food": p.get("servesVegetarianFood") is True
            or "vegetarian_restaurant" in (p.get("types") or [])
            or "vegan_restaurant" in (p.get("types") or []),
            "halal_hint": "halal_restaurant" in (p.get("types") or []),
            "wheelchair_accessible": (p.get("accessibilityOptions") or {}).get(
                "wheelchairAccessibleEntrance"
            ),
            "open_now": self._rules.open_now(current_hours),
            "today_hours": self._rules.today_hours(
                current_hours if current_hours is not None else regular_hours
            ),
            "price_level": (p.get("priceLevel") or "")
            .replace("PRICE_LEVEL_", "")
            .lower()
            or None,
            "price_start": self.money_to_float(pr.get("startPrice")),
            "price_end": self.money_to_float(pr.get("endPrice")),
            "price_range": self.fmt_price_range(pr),
            "types": p.get("types", []),
            "opening_hours": weekly,
        }

    def fetch_nearby_restaurants(self, origin, req, debug=False):
        """ONE Places request per search (up to 20 places). [] on failure."""
        self._log.debug_log(
            "Nearby Places request started.",
            "INFO",
            "BRNS.io_manager.fetch_nearby_restaurants",
        )
        lat, lng = origin
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._config.GOOGLE_MAPS_API_KEY,
            ("X-Goog-FieldMask"): (
                "places.id,places.displayName,places.formattedAddress,places.l"
                "ocation,places.rating,places.priceLevel,places.priceRange,pla"
                "ces.types,places.userRatingCount,places.currentOpeningHours,p"
                "laces.regularOpeningHours,places.nationalPhoneNumber,places.p"
                "ostalAddress,places.accessibilityOptions,places.servesVegetar"
                "ianFood"
            ),
        }
        body = {
            "includedTypes": ["restaurant", "cafe", "fast_food_restaurant"],
            "maxResultCount": 20,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": self._policy.search_radius(req),
                }
            },
        }
        try:
            resp = requests.post(
                self._config.PLACES_URL, headers=headers, json=body, timeout=15
            )
            if debug:
                self._log.debug_log(
                    f"Nearby Places HTTP {resp.status_code}.",
                    "DEBUG",
                    "BRNS.io_manager.fetch_nearby_restaurants",
                )
            resp.raise_for_status()
            places = []
            for p in resp.json().get("places", []):
                parsed = self.parse_place(p)
                if parsed:
                    places.append(parsed)
            self._log.debug_log(
                f"Nearby Places returned {len(places)} usable records.",
                "INFO",
                "BRNS.io_manager.fetch_nearby_restaurants",
            )
            return places
        except (requests.RequestException, KeyError, ValueError) as err:
            self._error("places_search", err)
            return []

    def run_text_search(
        self,
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
        """Execute Google Places Text Search anchored by locationBias
        around origin.
        """
        lat, lng = origin
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._config.GOOGLE_MAPS_API_KEY,
            ("X-Goog-FieldMask"): (
                "places.id,places.displayName,places.formattedAddress,places.l"
                "ocation,places.rating,places.priceLevel,places.priceRange,pla"
                "ces.types,places.userRatingCount,places.currentOpeningHours,p"
                "laces.regularOpeningHours,places.nationalPhoneNumber,places.p"
                "ostalAddress,places.accessibilityOptions,places.servesVegetar"
                "ianFood,nextPageToken"
            ),
        }
        body = {
            "textQuery": query,
            "languageCode": "en",
            "pageSize": 20,
            "openNow": True,
            "rankPreference": rank_preference,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius_m,
                }
            },
        }
        if price_levels:
            body["priceLevels"] = list(price_levels)
        if min_rating is not None:
            api_min_rating = max(
                0.5, min(5.0, math.floor(float(min_rating) * 2) / 2)
            )
            body["minRating"] = api_min_rating
        places = []
        try:
            for _ in range(max_pages):
                resp = requests.post(
                    self._config.TEXT_SEARCH_URL,
                    headers=headers,
                    json=body,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                for p in data.get("places", []):
                    parsed = self.parse_place(p)
                    if (
                        parsed
                        and self._distance(
                            origin, (parsed["lat"], parsed["lng"])
                        )
                        * 1000
                        <= radius_m
                    ):
                        places.append(parsed)
                token = data.get("nextPageToken")
                if not token:
                    break
                body = dict(body, pageToken=token)
        except (
            requests.RequestException,
            KeyError,
            ValueError,
            AttributeError,
        ) as err:
            self._error(error_tag, err)
            return ([], False) if return_status else []
        return (places, True) if return_status else places
