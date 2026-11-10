"""Distance-first BRNS result sorting strategy."""

from BRNS.classes.base_result_sorter import BaseResultSorter
from BRNS.classes.result_sorter_interface import ResultSorterInterface


class DistanceResultSorter(BaseResultSorter, ResultSorterInterface):
    """Sort by distance, then rating, reviews and restaurant name."""

    @property
    def name(self):
        return "distance"

    def key(self, item, mode):
        rating, reviews, distance, name = self._facts(item, mode)
        return (
            distance is None, distance or 0, rating is None,
            -(rating or 0), -reviews, name,
        )
