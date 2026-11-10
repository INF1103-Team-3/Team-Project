"""Focused contract for BIS session terminal interaction."""

from abc import ABC, abstractmethod


class BISSessionIOInterface(ABC):
    """Can collect and display account-session actions."""

    @abstractmethod
    def resolve_proposed_updates(self, *args, **kwargs):
        """Resolve user-approved profile updates."""

    @abstractmethod
    def display_message(self, *args, **kwargs):
        """Display one terminal message."""

    @abstractmethod
    def collect_action(self, *args, **kwargs):
        """Collect one account-session action."""
