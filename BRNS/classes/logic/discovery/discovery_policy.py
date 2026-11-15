"""Restaurant discovery planning and spatial selection policies."""

import math
import re
from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy

_VENUE_WORDS = ("food", "cafe", "hawker", "restaurant", "centre", "center",
                "court", "market", "kopi", "canteen", "bakery", "bar")


class DiscoveryPolicy:
    """Produce discovery decisions; yield search requests without executing IO."""

    def __init__(self, rules, distance, normalize_name, logger, error_reporter):
        self._rules = rules
        self._distance = distance
        self._norm = normalize_name
        self._log = logger
        self._error = error_reporter

    def strip_rating_terms(self, text):
        """Strip rating filters and leftover connector words from free text."""
        normalized = self._rules._normalize_rating_spacing(text)
        stripped = self._rules._RATING_FLOOR.sub('', normalized)
        stripped = self._rules._ANY_RATING.sub('', stripped).strip()
        stripped = re.sub('\\b(?:and|with)\\b', ' ', stripped, flags=re.IGNORECASE)
        return re.sub('^[,\\s&/]+|[,\\s&/]+$', '', stripped).strip()

    def clean_free_text_query(self, preferences):
        """Exclude rating patterns from Places search text."""
        cleaned = [part for pref in preferences for part in [self.strip_rating_terms(pref)] if part]
        return ' '.join(cleaned)

    def travel_radius(self, req):
        """Radius in meters implied by the user's travel mode and limit."""
        if req.get('max_travel_minutes') is not None:
            speed = {'walk': 80, 'drive': 650, 'transit': 400}[req['mode']]
            return max(500, min(int(req['max_travel_minutes'] * speed), 50000))
        if req.get('mode') == 'drive' and req.get('max_drive_km'):
            return max(1000, min(int(req['max_drive_km'] * 1000 * 0.8), 50000))
        distance = req.get('max_distance_km')
        if distance is not None:
            return max(500, min(int(distance * 1000), 50000))
        walk = req.get('max_walk_minutes')
        return max(500, min((walk if walk else 15) * 80, 20000))

    def search_radius(self, req):
        """Choose a Places discovery radius; Routes decides actual eligibility."""
        if self._rules.has_hard_preferences(req.get('other_preferences') or []):
            return 50000
        return self.travel_radius(req)

    def build_text_query(self, req, default_query=None):
        """Build a Places Text Search query from dietary, cuisine, and free-text terms."""
        cuisine = (req.get('cuisine') or '').strip()
        dietary = req.get('dietary_requirements') or []
        free_text = self.strip_rating_terms(req.get('free_text') or '').lower()[:200]
        terms = list(dietary)
        if cuisine not in ('any', 'none', ''):
            terms.append(cuisine)
        if free_text:
            terms.append(free_text)
        if not terms:
            return default_query
        query = ' '.join(terms)
        if not any((w in query for w in _VENUE_WORDS)):
            query += ' food'
        return query

    def complementary_venue_query(self, query):
        """Return a swapped food <-> restaurants query when merging venue labels."""
        clean = ' '.join(str(query or '').split())
        if not clean or clean == 'fine dining restaurants':
            return None
        if re.search('\\bfood$', clean, re.IGNORECASE):
            return re.sub('\\bfood$', 'restaurants', clean, flags=re.IGNORECASE)
        if re.search('\\brestaurants?$', clean, re.IGNORECASE):
            return re.sub('\\brestaurants?$', 'food', clean, flags=re.IGNORECASE)
        return None

    def merge_unique_places(self, primary, secondary):
        """Merge place lists preserving primary items first and deduping by ID/name."""
        merged, seen = ([], set())
        for place in list(primary) + list(secondary):
            if not isinstance(place, dict):
                continue
            pid = str(place.get('google_place_id') or '').strip()
            key = pid or self._norm(place.get('name', ''))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(place)
        return merged

    def qualifying_open_count(self, places, min_rating=None):
        """Count confirmed-open places meeting min_rating when one is active."""
        count = 0
        for p in places:
            if not isinstance(p, dict) or p.get('open_now') is not True:
                continue
            if min_rating is not None:
                rating = p.get('rating')
                if type(rating) not in (int, float) or not 1 <= rating <= 5 or rating < min_rating:
                    continue
            count += 1
        return count

    def sample_zone_slice(self, candidates, origin, radius_m, limit):
        """Sample confirmed-open candidates evenly across near/mid/outer distance bands."""
        if len(candidates) <= limit or radius_m <= 0:
            return candidates[:limit]
        radius_km = max(radius_m / 1000.0, 0.5)
        near, mid, outer = ([], [], [])
        for p in candidates:
            dist_km = self._distance(origin, (p['lat'], p['lng']))
            ratio = dist_km / radius_km
            if ratio <= 0.35:
                near.append(p)
            elif ratio <= 0.7:
                mid.append(p)
            else:
                outer.append(p)
        selected = []
        chosen_ids = set()
        for bucket, quota in ((near, 7), (mid, 7), (outer, 6)):
            for p in bucket[:quota]:
                selected.append(p)
                chosen_ids.add(id(p))
                if len(selected) >= limit:
                    return selected
        for p in candidates:
            if id(p) not in chosen_ids:
                selected.append(p)
                chosen_ids.add(id(p))
                if len(selected) >= limit:
                    break
        return selected

    def select_zone_places(self, places, origin, radius_m, limit=20, min_rating=None):
        """Filter confirmed-open unique places, prioritizing rating matches across zones."""
        open_unique, seen = ([], set())
        for p in places:
            if not isinstance(p, dict) or 'name' not in p:
                self._error('candidate_build', 'malformed place skipped')
                continue
            if p.get('open_now') is not True:
                self._log.debug_log('Skipped a place without confirmed open status.', 'INFO', 'BRNS.io_manager.build_candidates')
                continue
            key = self._norm(p['name']) or str(p.get('google_place_id') or '')
            if not key or key in seen:
                continue
            seen.add(key)
            open_unique.append(p)
        if min_rating is None:
            return self.sample_zone_slice(open_unique, origin, radius_m, limit)
        qualified = [p for p in open_unique if type(p.get('rating')) in (int, float) and 1 <= p['rating'] <= 5 and (p['rating'] >= min_rating)]
        qualified_ids = {id(p) for p in qualified}
        remainder = [p for p in open_unique if id(p) not in qualified_ids]
        selected = self.sample_zone_slice(qualified, origin, radius_m, limit)
        if len(selected) < limit and remainder:
            selected.extend(self.sample_zone_slice(remainder, origin, radius_m, limit - len(selected)))
        return selected[:limit]

    def profile_searches(self, req):
        """Places Text Search scoped by dietary, cuisine, free-text, budget, and minRating.
        Merges food + restaurants when < 12 open venues qualify, covers upper 0.5-star tiers,
        and backfills unlabelled/rating-relaxed results when still sparse."""
        budget = req.get('budget_per_person')
        min_rating = self._rules.minimum_rating(req.get('other_preferences') or [])
        default_query = None
        if isinstance(budget, (int, float)) and (not isinstance(budget, bool)) and (budget > 25):
            default_query = 'fine dining restaurants' if budget > 100 else 'restaurants'
        elif min_rating is not None:
            default_query = 'food'
        query = self.build_text_query(req, default_query=default_query)
        if not query:
            return []
        radius_m = float(min(self.search_radius(req), 50000))
        price_levels = BudgetFitPolicy.price_levels_for_budget(budget)
        max_pages = 2 if radius_m > 3000 else 1
        places, ok = (yield ((query, radius_m, 'places_profile_text'), {'max_pages': max_pages, 'price_levels': price_levels, 'min_rating': min_rating, 'rank_preference': 'RELEVANCE', 'return_status': True}))
        qualifying_count = self.qualifying_open_count(places, min_rating)
        alt_query = self.complementary_venue_query(query)
        if ok and alt_query and (qualifying_count < 12):
            complementary = (yield ((alt_query, radius_m, 'places_profile_text_complement'), {'max_pages': 1, 'price_levels': price_levels, 'min_rating': min_rating, 'rank_preference': 'RELEVANCE'}))
            places = self.merge_unique_places(places, complementary)
            qualifying_count = self.qualifying_open_count(places, min_rating)
        broad_query = 'restaurants' if query == 'fine dining restaurants' else query
        if ok and min_rating is not None:
            floored_step = max(0.5, min(5.0, math.floor(float(min_rating) * 2) / 2))
            upper_step = round(min(5.0, math.ceil(float(min_rating) * 2) / 2), 1)
            if upper_step > floored_step:
                upper_tier = (yield ((broad_query, radius_m, 'places_profile_text_rating_tier'), {'max_pages': 1, 'price_levels': None, 'min_rating': upper_step, 'rank_preference': 'RELEVANCE'}))
                places = self.merge_unique_places(places, upper_tier)
                qualifying_count = self.qualifying_open_count(places, min_rating)
        if ok and price_levels and (qualifying_count < 12):
            backfill = (yield ((broad_query, radius_m, 'places_profile_text_backfill'), {'max_pages': 1, 'price_levels': None, 'min_rating': min_rating, 'rank_preference': 'RELEVANCE'}))
            places = self.merge_unique_places(places, backfill)
            qualifying_count = self.qualifying_open_count(places, min_rating)
        if ok and min_rating is not None and (qualifying_count < 6):
            rating_fallback = (yield ((query, radius_m, 'places_profile_text_rating_fallback'), {'max_pages': 1, 'price_levels': price_levels, 'min_rating': None, 'rank_preference': 'RELEVANCE'}))
            places = self.merge_unique_places(places, rating_fallback)
        return places

    def use_profile_search(self, request):
        budget = request.get("budget_per_person")
        return bool(
            (request.get("cuisine") or "any").lower() not in ("any", "none", "")
            or request.get("dietary_requirements")
            or (request.get("free_text") or "").strip()
            or (isinstance(budget, (int, float))
                and not isinstance(budget, bool) and budget > 25)
            or self._rules.minimum_rating(request.get("other_preferences") or [])
               is not None)

    def open_backfill_needed(self, places, origin, radius_m):
        missing_open = any(
            isinstance(p, dict) and p.get("open_now") is not True
            for p in places)
        crammed = (
            len(places) >= 20 and radius_m > 3000
            and max((self._distance(origin, (p["lat"], p["lng"])) * 1000
                     for p in places if isinstance(p, dict)
                     and "lat" in p and "lng" in p), default=0.0)
            < 0.35 * radius_m)
        return missing_open or crammed

    def saved_open_candidates(self, restaurants):
        return [dict(row, source="offline restaurants") for row in restaurants
                if self._rules.open_now_from_weekly(row.get("opening_hours"))]

    def open_search(self, request, max_pages=1):
        radius = float(min(self.travel_radius(request), 50000))
        return (
            (self.build_text_query(request, default_query="restaurants"),
             radius, "places_open_text"),
            {"max_pages": 2 if radius > 3000 else max_pages,
             "price_levels": BudgetFitPolicy.price_levels_for_budget(
                 request.get("budget_per_person")),
             "rank_preference": "RELEVANCE"},
        )
