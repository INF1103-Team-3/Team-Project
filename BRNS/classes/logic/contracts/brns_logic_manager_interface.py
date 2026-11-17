"""Focused contract for BRNS Logic Manager operations."""

from abc import ABC, abstractmethod


class BRNSLogicManagerInterface(ABC):
    """Can apply deterministic recommendation business rules."""

    @abstractmethod
    def prepare_halal_candidate(self, candidate):
        """Initialize unofficial evidence without claiming certification."""

    @abstractmethod
    def apply_halal_evidence(self, candidate, checked):
        """Apply checked evidence and return whether it is official."""

    @abstractmethod
    def minimum_rating(self, preferences):
        """Return the required minimum rating or None."""

    @abstractmethod
    def has_hard_preferences(self, preferences):
        """Whether wishes contain mandatory constraints."""

    @abstractmethod
    def prepare_candidate_search(self, request):
        """Prepare search criteria without mutating the confirmed request."""

    @abstractmethod
    def saved_candidates(self, records):
        """Interpret raw saved records for candidate enrichment."""

    @abstractmethod
    def recommendation_context(
        self, request, candidates, previous_restaurants=()
    ):
        """Prepare domain facts and constraints consumed by AI."""

    @abstractmethod
    def sort_results(self, results, sort_by):
        """Sort results by a supported strategy."""

    @abstractmethod
    def recommendation_order(self, restaurants, recommendations):
        """Validate and return AI candidate order."""

    @abstractmethod
    def rank_restaurants(
        self,
        restaurants,
        request,
        recommendations=None,
        previous_restaurants=(),
        max_matches=None,
        max_alternatives=None,
        strict_exclude=False,
    ):
        """Classify and rank candidate restaurants."""
