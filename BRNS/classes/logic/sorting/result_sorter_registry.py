"""Aggregate independently usable BRNS result-sort strategies."""


class ResultSorterRegistry:
    """Store result sorters by their public choice name."""

    def __init__(self, sorters):
        self.__sorters = {sorter.name: sorter for sorter in sorters}

    def get(self, name):
        try:
            return self.__sorters[name]
        except KeyError as error:
            raise ValueError("Sort results by rating or distance.") from error

    def names(self):
        return tuple(self.__sorters)
