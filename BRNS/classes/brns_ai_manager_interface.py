"""Focused contract for BRNS AI Manager operations."""

from abc import ABC, abstractmethod


class BRNSAIManagerInterface(ABC):
    """Can report provider availability and rank candidates."""

    @abstractmethod
    def has_configured_provider(self):
        """Return whether an AI provider can be used."""

    @abstractmethod
    def recommend_candidates(self, *args, **kwargs):
        """Return schema-validated AI recommendation ordering."""
