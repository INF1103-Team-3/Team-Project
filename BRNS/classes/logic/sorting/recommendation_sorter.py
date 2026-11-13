"""BRNS recommendation sorting service."""

from BRNS.classes.logic.sorting.strategies.distance_result_sorter import DistanceResultSorter
from BRNS.classes.logic.sorting.strategies.rating_result_sorter import RatingResultSorter
from BRNS.classes.logic.sorting.result_sorter_registry import ResultSorterRegistry


class RecommendationSorter:
    """Select a polymorphic strategy for an existing result set."""

    def __init__(self, registry=None):
        self.__registry = registry or ResultSorterRegistry((
            RatingResultSorter(),
            DistanceResultSorter(),
        ))

    def sort(self, results, sort_by):
        return self.__registry.get(sort_by).sort(results)
