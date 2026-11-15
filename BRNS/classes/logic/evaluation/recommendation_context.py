"""Prepare domain facts and constraints for AI without performing network IO."""

from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy


class RecommendationContext:
    """Use the existing domain rules to build the unchanged AI input record."""

    def __init__(self, rules):
        self._rules = rules

    def build(self, request, candidates, previous_restaurants=()):
        mode = request["mode"]
        budget = request.get("budget_per_person")
        rating_floor = self._rules.minimum_rating(request["other_preferences"])
        rating_preference = self._rules.preferred_rating(
            request["other_preferences"])
        hard_cuisines = self._rules.hard_required_cuisines(
            request["other_preferences"])
        hard_preferences = self._rules.has_hard_preferences(
            request["other_preferences"])
        facts = []
        for index, candidate in enumerate(candidates):
            estimated_price, price_source = BudgetFitPolicy.estimate_price(candidate)
            fit_score = BudgetFitPolicy.budget_fit_score(candidate, budget)
            price_level = candidate.get("price_level") or candidate.get("price_band")
            facts.append({
                "id": index,
                "name": candidate.get("name"),
                "cuisines": candidate.get("cuisines"),
                "dietary_requirements": candidate.get("dietary_requirements"),
                "halal_hint_unofficial": bool(candidate.get("halal_hint")),
                "avg_price": candidate.get("avg_price"),
                "price_start": candidate.get("price_start"),
                "price_end": candidate.get("price_end"),
                "price_range": candidate.get("price_range"),
                "price_level": price_level,
                "estimated_price": estimated_price,
                "price_source": price_source,
                "budget_fit_score": fit_score,
                "rating": candidate.get("rating"),
                "review_count": candidate.get("rating_count"),
                "confidence_adjusted_rating": self._rules.confidence_adjusted_rating(
                    candidate.get("rating"), candidate.get("rating_count")),
                "google_search_rank": candidate.get("google_search_rank"),
                "spicy_options": candidate.get("spicy_options"),
                "travel_meters": candidate.get(f"{mode}_meters"),
                "travel_minutes": candidate.get(f"{mode}_minutes"),
                "travel_source": candidate.get(f"{mode}_source"),
            })
        prior_names = list(dict.fromkeys(
            restaurant.get("name") for restaurant in previous_restaurants
            if isinstance(restaurant, dict)
            and isinstance(restaurant.get("name"), str)))
        return {"request": request, "minimum_rating": rating_floor,
                "preferred_rating": rating_preference, "hard_cuisines": hard_cuisines,
                "hard_preferences": hard_preferences, "candidates": facts,
                "previous_restaurants": prior_names}
