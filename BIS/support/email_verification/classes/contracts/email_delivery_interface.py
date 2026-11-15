"""Capability contract for delivering BiteFinder emails."""

from abc import ABC, abstractmethod


class EmailDeliveryInterface(ABC):
    """A delivery mechanism that can send BIS account-related emails."""

    @abstractmethod
    def send_verification_email(self, email, code, config):
        """Send one verification code email."""

    @abstractmethod
    def send_maps_link_email(self, email, restaurant_name, link, config):
        """Send one restaurant directions email."""
