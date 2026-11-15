"""Capabilities required by the web conversation workflow."""

from abc import ABC, abstractmethod


class ChatAIInterface(ABC):
    @abstractmethod
    def chat_turn(
        self, message, current_filters, history, saved_profile, config
    ):
        """Interpret one conversation turn through the configured AI chain."""

    @abstractmethod
    def review_profile_wishes(self, wishes, config):
        """Validate structured AI review of profile wishes."""
