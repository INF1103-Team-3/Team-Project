"""Focused contract for BRNS Logic Manager operations."""

from abc import ABC, abstractmethod


class BRNSLogicManagerInterface(ABC):
    """Can apply deterministic recommendation business rules."""

    @abstractmethod
    def sort_results(self, results, sort_by):
        """Sort results by a supported strategy."""

    @abstractmethod
    def recommendation_order(self, restaurants, recommendations):
        """Validate and return AI candidate order."""

    @abstractmethod
    def rank_restaurants(self, *args, **kwargs):
        """Classify and rank candidate restaurants."""
