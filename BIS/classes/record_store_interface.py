"""Focused persistence capability required by the BIS Data Manager."""

from abc import ABC, abstractmethod


class RecordStoreInterface(ABC):
    """A store that can load, save and query account records."""

    @abstractmethod
    def load(self):
        """Load all valid account records."""

    @abstractmethod
    def save(self, record):
        """Persist one account record and return it."""

    @abstractmethod
    def query(self, filter_fn):
        """Return records accepted by a caller-supplied predicate."""
