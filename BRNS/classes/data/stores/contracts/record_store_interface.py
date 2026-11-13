"""Persistence capability required by the BRNS Data Manager."""

from abc import ABC, abstractmethod


class RecordStoreInterface(ABC):
    """A store that can load, save and query BRNS records."""

    @abstractmethod
    def load(self):
        """Load saved search records."""

    @abstractmethod
    def save(self, record):
        """Save one evaluated search record."""

    @abstractmethod
    def query(self, filter_fn):
        """Return saved records accepted by a predicate."""
