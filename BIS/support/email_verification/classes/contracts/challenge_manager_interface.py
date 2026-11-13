"""Capability contract for email verification challenge management."""

from abc import ABC, abstractmethod


class ChallengeManagerInterface(ABC):
    """A component that can create, validate, and check challenge state."""

    @abstractmethod
    def validate(self, challenge):
        """Return normalized challenge state or raise ``ValueError``."""

    @abstractmethod
    def create(self, previous=None, now=None, *, attempt_reset_seconds):
        """Return a plaintext delivery code and persistable challenge."""

    @abstractmethod
    def check(self, challenge, code, now=None, *, attempt_reset_seconds):
        """Return updated challenge state and an optional error message."""
