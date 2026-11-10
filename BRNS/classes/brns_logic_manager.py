"""BRNS Logic Manager object with composed recommendation sorting."""

from BRNS.classes.recommendation_sorter import RecommendationSorter
from BRNS.classes.brns_logic_manager_interface import (
    BRNSLogicManagerInterface,
)


class BRNSLogicManager(BRNSLogicManagerInterface):
    """Own BRNS domain collaborators behind stable manager operations."""

    def __init__(self, recommendation_sorter=None, manager_module=None):
        self.__recommendation_sorter = (
            recommendation_sorter or RecommendationSorter()
        )
        self._manager = manager_module

    def sort_results(self, results, sort_by):
        return self.__recommendation_sorter.sort(results, sort_by)

    def recommendation_order(self, restaurants, recommendations):
        return self._manager.recommendation_order(
            restaurants, recommendations)

    def rank_restaurants(self, *args, **kwargs):
        return self._manager.rank_restaurants(*args, **kwargs)
