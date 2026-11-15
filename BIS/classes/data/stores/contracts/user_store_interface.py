"""Account and workflow-state persistence capability shared by JSON and Mongo."""
from abc import ABC, abstractmethod


class UserStoreInterface(ABC):
    @abstractmethod
    def registry(self):
        """Return validated domain users keyed by userID."""

    @abstractmethod
    def save(self, record):
        """Persist and return a validated user without backend metadata."""

    @abstractmethod
    def get_state(self, section, user_id):
        """Read an optional workflow state dictionary."""

    @abstractmethod
    def set_state(self, section, user_id, value):
        """Store state or remove it when value is None."""
