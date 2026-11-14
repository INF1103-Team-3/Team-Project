"""BRNS Logic Manager: recommendation validation, ranking, and sorting."""

from BRNS.classes.logic.contracts.brns_logic_manager_interface import (
    BRNSLogicManagerInterface,
)
from BRNS.classes.logic.sorting.recommendation_sorter import RecommendationSorter
from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy
from BRNS.classes.logic.evaluation.restaurant_enricher import RestaurantEnricher
from BIS.sources.profile_schema import CUISINES


def _default_confidence_rating(rating, review_count):
    if (type(rating) not in (int, float) or not 1 <= rating <= 5
            or type(review_count) is not int or review_count < 0):
        return None
    return round((rating * review_count + 4 * 100) / (review_count + 100), 3)


class LogicManager(BRNSLogicManagerInterface):
    """Own BRNS recommendation decisions using injected rule functions."""

    def __init__(self, normalizer, outcome_decider, reason_grounder,
                 max_matches, max_alternatives, minimum_rating_reader,
                 hard_preference_reader, today_hours_reader, context_builder,
                 recommendation_sorter=None, restaurant_enricher=None,
                 confidence_rating=None):
        if not callable(minimum_rating_reader) or not callable(hard_preference_reader):
            raise TypeError("Rating and hard-preference readers must be callable.")
        self._enricher = restaurant_enricher or RestaurantEnricher()
        self._today_hours = today_hours_reader
        self._context_builder = context_builder
        self._normalize = normalizer
        self._decide = outcome_decider
        self._ground_reasons = reason_grounder
        self._max_matches = max_matches
        self._max_alternatives = max_alternatives
        self._minimum_rating_reader = minimum_rating_reader
        self._hard_preference_reader = hard_preference_reader
        self._sorter = recommendation_sorter or RecommendationSorter()
        self._confidence_rating = confidence_rating or _default_confidence_rating

    def enrich_place(self, place, saved_restaurants):
        return self._enricher.enrich(place, saved_restaurants)

    def saved_candidates(self, data):
        restaurants = []
        for row in data:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            candidate = dict(row)
            cuisine = row.get("cuisine")
            candidate["cuisines"] = [cuisine] if cuisine in CUISINES else []
            candidate["dietary_requirements"] = [
                item for item in row.get("dietary") or []
                if item in ("halal", "vegetarian")]
            candidate["price_start"] = row.get("avg_price_low_sgd")
            candidate["price_end"] = row.get("avg_price_high_sgd")
            try:
                candidate["rating"] = float(row["g_rating"])
            except (KeyError, TypeError, ValueError):
                candidate["rating"] = None
            try:
                candidate["rating_count"] = int(row["g_no_reviews"])
            except (KeyError, TypeError, ValueError):
                candidate["rating_count"] = None
            candidate["halal_hint"] = row.get("halal_certification") == "unofficial"
            candidate["halal_certification"] = row.get("halal_certification")
            candidate["today_hours"] = self._today_hours(
                row.get("opening_hours"))
            restaurants.append(candidate)
        return restaurants

    def prepare_candidate_search(self, request):
        lookup = dict(request)
        preferences = list(request["other_preferences"])
        preferences.sort(key=lambda item: not self.has_hard_preferences([item]))
        lookup["free_text"] = " ".join(preferences)
        return lookup

    def recommendation_context(self, request, candidates, previous_restaurants=()):
        return self._context_builder.build(request, candidates, previous_restaurants)

    def minimum_rating(self, preferences):
        return self._minimum_rating_reader(preferences)

    def has_hard_preferences(self, preferences):
        return self._hard_preference_reader(preferences)

    def sort_results(self, results, sort_by):
        return self._sorter.sort(results, sort_by)

    @staticmethod
    def recommendation_order(restaurants, recommendations):
        if (not isinstance(recommendations, list)
                or len(recommendations) != len(restaurants)
                or any(
                    not isinstance(item, dict)
                    or set(item) != {"id", "reason_codes"}
                    or type(item["id"]) is not int
                    or item["id"] < 0
                    or item["id"] >= len(restaurants)
                    for item in recommendations)):
            raise ValueError("BRNS AI returned invalid restaurant IDs.")
        order = [item["id"] for item in recommendations]
        if len(set(order)) != len(restaurants):
            raise ValueError("BRNS AI returned duplicate restaurant IDs.")
        return order

    def rank_restaurants(self, restaurants, request, recommendations=None,
                         previous_restaurants=(), max_matches=None,
                         max_alternatives=None):
        if recommendations is None:
            order = list(range(len(restaurants)))
            ai_reasons = {}
        else:
            order = self.recommendation_order(restaurants, recommendations)
            ai_reasons = {}
            for item in recommendations:
                restaurant = self._normalize(restaurants[item["id"]])
                ai_reasons[item["id"]] = self._ground_reasons(
                    restaurant, request, item["reason_codes"], item["id"])
        matches, alternatives = [], []
        excluded_reasons = {}
        hidden = 0
        for index in order:
            raw = restaurants[index]
            restaurant = self._normalize(
                raw, offline=raw.get("source") == "offline restaurants")
            status, score, reasons = self._decide(restaurant, request)
            decision_reasons = list(reasons)
            for reason in ai_reasons.get(index, []):
                if reason not in reasons and f"! {reason}" not in reasons:
                    reasons.append(reason)
            item = {
                "restaurant": restaurant,
                "score": score,
                "reasons": reasons,
            }
            if status == "match":
                matches.append(item)
            elif status == "alternative":
                alternatives.append(item)
            else:
                hidden += 1
                for reason in decision_reasons:
                    excluded_reasons[reason] = (
                        excluded_reasons.get(reason, 0) + 1)
        if recommendations is None:
            matches.sort(
                key=lambda item: (
                    item["score"],
                    BudgetFitPolicy.joint_rank_score(
                        item["restaurant"], request, self._confidence_rating
                    ),
                ),
                reverse=True,
            )
        previous_keys = {
            (
                str(item.get("name", "")).casefold().strip(),
                str(item.get("address", "")).casefold().strip(),
            )
            for item in previous_restaurants if isinstance(item, dict)
        }

        def was_returned(item):
            restaurant = item["restaurant"]
            return (
                str(restaurant.get("name", "")).casefold().strip(),
                str(restaurant.get("address", "")).casefold().strip(),
            ) in previous_keys

        matches.sort(key=was_returned)
        alternatives.sort(key=was_returned)
        resolved_max_matches = (
            max_matches if max_matches is not None else (
                self._max_matches()
                if callable(self._max_matches)
                else self._max_matches
            )
        )
        resolved_max_alternatives = (
            max_alternatives if max_alternatives is not None else (
                self._max_alternatives()
                if callable(self._max_alternatives)
                else self._max_alternatives
            )
        )
        visible_matches = matches[:resolved_max_matches]
        visible_alternatives = alternatives[:resolved_max_alternatives]
        return {
            "matches": visible_matches,
            "alternatives": visible_alternatives,
            "new_count": sum(
                not was_returned(item)
                for item in visible_matches + visible_alternatives),
            "hidden": hidden,
            "excluded_reasons": excluded_reasons,
            "mode": request["mode"],
            "limit_unit": (
                "minutes"
                if request["max_travel_minutes"] is not None else "km"),
            "traffic_aware": request["traffic_aware"],
            "requested_dietary": request["dietary_requirements"],
        }
