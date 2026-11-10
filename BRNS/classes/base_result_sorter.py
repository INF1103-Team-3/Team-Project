"""Shared result-fact extraction and collection sorting behavior."""

from abc import ABC, abstractmethod


class BaseResultSorter(ABC):
    """Base sorter for BRNS result groups."""

    def sort(self, results):
        mode = results.get("mode")
        sorted_results = dict(results)
        sorted_results["matches"] = sorted(
            results.get("matches", []), key=lambda item: self.key(item, mode))
        sorted_results["alternatives"] = sorted(
            results.get("alternatives", []),
            key=lambda item: self.key(item, mode),
        )
        return sorted_results

    @staticmethod
    def _facts(item, mode):
        restaurant = item.get("restaurant", {})
        rating = restaurant.get("rating")
        rating = rating if type(rating) in (int, float) else None
        reviews = restaurant.get("rating_count")
        reviews = reviews if type(reviews) is int and reviews >= 0 else 0
        distance = restaurant.get(f"{mode}_meters")
        distance = (
            distance if type(distance) in (int, float) and distance >= 0
            else None
        )
        name = str(restaurant.get("name") or "").casefold()
        return rating, reviews, distance, name

    @abstractmethod
    def key(self, item, mode):
        """Return the strategy-specific stable sort key."""
