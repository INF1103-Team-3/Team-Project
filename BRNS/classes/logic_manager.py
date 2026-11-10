"""BRNS Logic Manager: recommendation validation, ranking, and sorting."""

from BRNS.classes.brns_logic_manager_interface import (
    BRNSLogicManagerInterface,
)
from BRNS.classes.recommendation_sorter import RecommendationSorter


class LogicManager(BRNSLogicManagerInterface):
    """Own BRNS recommendation decisions using injected rule functions."""

    def __init__(self, normalizer, outcome_decider, reason_grounder,
                 max_matches, max_alternatives, minimum_rating_reader=None,
                 hard_preference_reader=None, recommendation_sorter=None):
        self._normalize = normalizer
        self._decide = outcome_decider
        self._ground_reasons = reason_grounder
        self._max_matches = max_matches
        self._max_alternatives = max_alternatives
        self._minimum_rating_reader = minimum_rating_reader
        self._hard_preference_reader = hard_preference_reader
        self._sorter = recommendation_sorter or RecommendationSorter()

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
                         previous_restaurants=()):
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
            matches.sort(key=lambda item: item["score"], reverse=True)
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
        visible_matches = matches[:self._max_matches]
        visible_alternatives = alternatives[:self._max_alternatives]
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
