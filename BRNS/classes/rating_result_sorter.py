"""Rating-first BRNS result sorting strategy."""

from BRNS.classes.base_result_sorter import BaseResultSorter
from BRNS.classes.result_sorter_interface import ResultSorterInterface


class RatingResultSorter(BaseResultSorter, ResultSorterInterface):
    """Sort by rating, then reviews, distance and restaurant name."""

    @property
    def name(self):
        return "rating"

    def key(self, item, mode):
        rating, reviews, distance, name = self._facts(item, mode)
        return (
            rating is None, -(rating or 0), -reviews,
            distance is None, distance or 0, name,
        )
