"""Focused BRNS recommendation-presentation capability contract."""

from abc import ABC, abstractmethod


class RecommendationPresentationInterface(ABC):
    """Can display recommendation workflow progress and results."""

    @property
    @abstractmethod
    def display_debug(self):
        """Return the debug display callback."""

    @abstractmethod
    def show_ai_ranking_start(self, count, timeout):
        """Display AI ranking progress."""

    @abstractmethod
    def show_halal_verification_start(self, count, database_missing=False):
        """Display halal verification progress."""

    @abstractmethod
    def show_halal_verification_summary(self, summary):
        """Display halal verification results."""

    @abstractmethod
    def show_results(self, results):
        """Display recommendation results."""
