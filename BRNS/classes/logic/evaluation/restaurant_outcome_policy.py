"""Restaurant acceptance, alternatives, and scoring policy."""

from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy


class RestaurantOutcomePolicy:
    """Evaluate all existing constraints using injected preference rules.

    Keeps the ordered reasons and advisory policy together; performs no IO,
    AI calls, normalization, or persistence and never mutates input records.
    """

    def __init__(self, rules):
        self._rules = rules

    def evaluate(self, restaurant, request):
        """Return match, alternative, or reject with explicit reasons."""
        if restaurant.get("source") in ("google places", "saved + google places") \
                and restaurant.get("open_now") is not True:
            return "reject", 0, ["not confirmed open now"]
        reasons = []
        problems = []
        unverified = []
        advisories = []
        hard_preferences = self._rules.has_hard_preferences(request["other_preferences"])
        cuisines = restaurant.get("cuisines") or []
        if set(cuisines) & set(request["disliked_cuisines"]):
            return "reject", 0, ["contains a disliked cuisine"]
        wanted = request["cuisine"]
        if wanted == "none":
            pass
        elif wanted in cuisines:
            reasons.append("matches your selected cuisine")
        elif cuisines:
            problems.append("does not match your selected cuisine")
        else:
            unverified.append("cuisine unavailable")
        for required in self._rules.hard_required_cuisines(request["other_preferences"]):
            if required in cuisines:
                reasons.append(f"meets your {required} only requirement")
            elif cuisines:
                problems.append(f"does not meet your {required} only requirement")
            else:
                unverified.append(
                    f"cuisine unavailable for your {required} only requirement")

        dietary = set(restaurant.get("dietary_requirements") or [])
        for requirement in request["dietary_requirements"]:
            if requirement == "halal":
                if restaurant.get("halal_status") == "official":
                    reasons.append("MUIS halal certification verified")
                elif restaurant.get("halal_status") == "unofficial":
                    unverified.append("Halal (unofficial; not checked)")
                else:
                    return "reject", 0, ["MUIS halal certification not verified"]
            elif requirement == "vegetarian" and "vegetarian" not in dietary:
                unverified.append("vegetarian options unverified")

        budget = request["budget_per_person"]
        budget_kind, budget_reason = BudgetFitPolicy.evaluate_budget(restaurant, budget)
        if budget_kind == "reason":
            reasons.append(budget_reason)
        elif budget_kind == "problem":
            (advisories if hard_preferences else problems).append(budget_reason)
        else:
            (advisories if hard_preferences else unverified).append(budget_reason)

        rating_floor = self._rules.minimum_rating(request["other_preferences"])
        if rating_floor is not None:
            rating = restaurant.get("rating")
            if type(rating) not in (int, float) or not 1 <= rating <= 5:
                unverified.append(
                    f"Google rating unavailable; requested at least {rating_floor:g}/5")
            elif rating < rating_floor:
                problems.append(
                    f"Google rating {rating:g}/5 is below your {rating_floor:g}/5 minimum")
            else:
                reasons.append(f"Google rating meets your {rating_floor:g}/5 minimum")

        mode = request["mode"]
        source = restaurant.get(f"{mode}_source")
        if request["max_travel_minutes"] is not None:
            minutes = restaurant.get(f"{mode}_minutes")
            if source != "route" or minutes is None:
                (advisories if hard_preferences else unverified).append(
                    f"{mode} journey time unavailable")
            elif minutes > request["max_travel_minutes"]:
                (advisories if hard_preferences else problems).append(
                    f"{mode} journey is {minutes:g} min, over your "
                    f"{request['max_travel_minutes']:g} min limit")
            else:
                reasons.append(f"within your {mode} time limit")
        else:
            meters = restaurant.get(f"{mode}_meters")
            if source != "route" or meters is None:
                (advisories if hard_preferences else unverified).append(
                    "travel distance estimated or unavailable")
            elif meters > request["max_distance_km"] * 1000:
                (advisories if hard_preferences else problems).append(
                    f"route is {meters / 1000:.2f} km, over your "
                    f"{request['max_distance_km']:g} km limit")
            else:
                reasons.append("within your route distance limit")

        if "spicy" in " ".join(request["other_preferences"]):
            if restaurant.get("spicy_options") is True:
                reasons.append("has spicy options")
        if problems or unverified:
            return "alternative", 0, (
                reasons + [f"! {item}" for item in
                           problems + unverified + advisories])
        return "match", len(reasons), (
            reasons + [f"! {item} (relaxed for hard requirement)"
                       for item in advisories])
