"""Shared budget-tier estimation, fit scoring, and travel-joint ranking helpers."""


class BudgetFitPolicy:
    """Evaluate budget fit without modifying raw or missing restaurant fields."""

    TIER_TYPICAL_SGD = {
        "inexpensive": 10.0,
        "moderate": 28.0,
        "expensive": 65.0,
        "very_expensive": 140.0,
    }

    TIER_LABELS = {
        "inexpensive": "Budget",
        "moderate": "Casual Dining",
        "expensive": "Upscale",
        "very_expensive": "Fine Dining",
    }

    @staticmethod
    def _is_valid_number(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        )

    @classmethod
    def normalize_price_tier(cls, raw_tier):
        if not isinstance(raw_tier, str) or not raw_tier.strip():
            return None
        cleaned = raw_tier.strip().lower().removeprefix("price_level_")
        return cleaned if cleaned in cls.TIER_TYPICAL_SGD else None

    @classmethod
    def price_levels_for_budget(cls, budget):
        """Map exact SGD budget to Google Places Text Search priceLevels."""
        if not cls._is_valid_number(budget) or budget <= 0:
            return None
        if budget <= 15:
            return ["PRICE_LEVEL_INEXPENSIVE"]
        if budget <= 35:
            return ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
        if budget <= 80:
            return ["PRICE_LEVEL_MODERATE", "PRICE_LEVEL_EXPENSIVE"]
        if budget <= 100:
            return ["PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"]
        return ["PRICE_LEVEL_VERY_EXPENSIVE", "PRICE_LEVEL_EXPENSIVE"]

    @classmethod
    def estimate_price(cls, restaurant):
        """Derive continuous estimated price in SGD and its source label."""
        avg_price = restaurant.get("avg_price")
        if cls._is_valid_number(avg_price):
            return round(float(avg_price), 2), "avg_price"

        start = restaurant.get("price_start")
        end = restaurant.get("price_end")
        valid_start = cls._is_valid_number(start)
        valid_end = cls._is_valid_number(end)

        if valid_start and valid_end and start <= end:
            return round((float(start) + float(end)) / 2.0, 2), "price_range"
        if valid_start:
            return round(float(start), 2), "price_start"
        if valid_end:
            return round(float(end), 2), "price_end"

        tier = cls.normalize_price_tier(
            restaurant.get("price_level") or restaurant.get("price_band")
        )
        if tier:
            return cls.TIER_TYPICAL_SGD[tier], "price_tier"

        return None, None

    @classmethod
    def budget_fit_score(cls, restaurant, budget):
        """Compute continuous 0.0-1.0 fit score against exact user budget."""
        if not cls._is_valid_number(budget) or budget <= 0:
            return 0.5

        avg_price = restaurant.get("avg_price")
        if cls._is_valid_number(avg_price) and avg_price > budget:
            excess = (avg_price - budget) / max(float(budget), 1.0)
            return round(max(0.0, 0.25 - 0.35 * excess), 3)

        price_start = restaurant.get("price_start")
        if avg_price is None and cls._is_valid_number(price_start) and price_start > budget:
            excess = (price_start - budget) / max(float(budget), 1.0)
            return round(max(0.0, 0.25 - 0.35 * excess), 3)

        estimated, _ = cls.estimate_price(restaurant)
        if estimated is None:
            return 0.25

        tier = cls.normalize_price_tier(
            restaurant.get("price_level") or restaurant.get("price_band")
        )

        if budget > 100:
            if estimated >= 80 or tier == "very_expensive":
                return 1.0
            if estimated >= 50 or tier == "expensive":
                return round(0.76 + 0.16 * min(1.0, max(0.0, estimated - 50.0) / 30.0), 3)
            if estimated >= 25 or tier == "moderate":
                return round(0.45 + 0.25 * min(1.0, max(0.0, estimated - 25.0) / 25.0), 3)
            return round(max(0.12, 0.15 + 0.20 * min(1.0, estimated / 25.0)), 3)

        if estimated > budget:
            excess = (estimated - budget) / max(float(budget), 1.0)
            return round(max(0.0, 0.28 - 0.40 * excess), 3)

        if budget <= 15:
            ratio = estimated / max(float(budget), 0.01)
            return round(min(1.0, 0.85 + 0.15 * min(1.0, ratio / 0.80)), 3)

        ratio = estimated / float(budget)
        if ratio >= 0.55:
            return round(1.0 - 0.10 * abs(ratio - 0.85) / 0.30, 3)
        return round(0.30 + 0.60 * (ratio / 0.55), 3)

    @classmethod
    def evaluate_budget(cls, restaurant, budget):
        """Return (status_kind, reason_text) shared by policy and AI grounding."""
        avg_price = restaurant.get("avg_price")
        minimum_price = restaurant.get("price_start")
        maximum_price = restaurant.get("price_end")

        if cls._is_valid_number(avg_price):
            if avg_price > budget:
                return (
                    "problem",
                    f"average price SGD {avg_price:g} exceeds your SGD {budget:g} budget",
                )
            return "reason", "average price is within your budget"

        if cls._is_valid_number(minimum_price) and minimum_price > budget:
            return (
                "problem",
                f"prices start at SGD {minimum_price:g}, over your budget",
            )

        if (
            cls._is_valid_number(maximum_price)
            and maximum_price <= budget
            and (minimum_price is None or (cls._is_valid_number(minimum_price) and minimum_price <= maximum_price))
        ):
            if budget > 100 and ((minimum_price or maximum_price) >= 50):
                return "reason", "listed price range fits within your SGD $100+ fine-dining tier"
            return "reason", "listed price range is within your budget"

        if (
            cls._is_valid_number(minimum_price)
            and cls._is_valid_number(maximum_price)
            and minimum_price <= maximum_price
        ):
            midpoint = round((minimum_price + maximum_price) / 2.0, 2)
            if midpoint <= budget:
                if budget > 100:
                    return (
                        "reason",
                        f"estimated price (~SGD {midpoint:g}) fits within your SGD $100+ fine-dining tier",
                    )
                return (
                    "reason",
                    f"estimated price (~SGD {midpoint:g}) aligns with your SGD {budget:g} budget",
                )
            return (
                "problem",
                f"listed midpoint SGD {midpoint:g} (SGD {minimum_price:g}-{maximum_price:g}) exceeds your SGD {budget:g} budget",
            )

        if cls._is_valid_number(minimum_price):
            return "unverified", "some prices may fit; full budget unverified"

        if cls._is_valid_number(maximum_price) and maximum_price > budget:
            return (
                "problem",
                f"prices go up to SGD {maximum_price:g}, over your SGD {budget:g} budget",
            )

        tier = cls.normalize_price_tier(
            restaurant.get("price_level") or restaurant.get("price_band")
        )
        if tier:
            typical = cls.TIER_TYPICAL_SGD[tier]
            label = cls.TIER_LABELS[tier]
            if budget > 100:
                if tier in ("expensive", "very_expensive"):
                    return (
                        "reason",
                        f"within your SGD $100+ fine-dining tier ({label}, ~SGD {typical:g})",
                    )
                return (
                    "reason",
                    f"Google price tier ({label}, ~SGD {typical:g}) fits within your SGD $100+ limit",
                )
            if typical <= budget:
                return (
                    "reason",
                    f"estimated price (~SGD {typical:g}, {label}) aligns with your SGD {budget:g} budget",
                )
            return (
                "problem",
                f"Google price tier ({label}, ~SGD {typical:g}) likely exceeds your SGD {budget:g} budget",
            )

        return "unverified", "price unavailable"

    @classmethod
    def joint_rank_score(cls, restaurant, request, rating_confidence_fn):
        """Compute deterministic Pure Best-Fit score across budget, quality, and proximity."""
        fit = cls.budget_fit_score(restaurant, request.get("budget_per_person"))
        conf_rating = rating_confidence_fn(
            restaurant.get("rating"),
            restaurant.get("rating_count"),
        )
        quality_norm = (
            (conf_rating - 1.0) / 4.0
            if conf_rating is not None
            else 0.55
        )
        mode = request.get("mode", "walk")
        proximity = 0.0
        if request.get("max_travel_minutes") is not None:
            mins = restaurant.get(f"{mode}_minutes")
            if cls._is_valid_number(mins):
                limit = max(float(request["max_travel_minutes"]), 1.0)
                proximity = max(0.0, 1.0 - min(1.0, float(mins) / limit))
        elif request.get("max_distance_km") is not None:
            meters = restaurant.get(f"{mode}_meters")
            if cls._is_valid_number(meters):
                limit_m = max(float(request["max_distance_km"]) * 1000.0, 10.0)
                proximity = max(0.0, 1.0 - min(1.0, float(meters) / limit_m))

        return round(0.50 * fit + 0.45 * quality_norm + 0.05 * proximity, 4)
