"""Capability contract for sorting classified recommendation results."""

from abc import ABC, abstractmethod


class ResultSorterInterface(ABC):
    """A strategy that can sort matches and alternatives."""

    @property
    @abstractmethod
    def name(self):
        """Return the public sort choice handled by this strategy."""

    @abstractmethod
    def sort(self, results):
        """Return a sorted result copy without changing classification."""
