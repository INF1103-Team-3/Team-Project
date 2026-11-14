"""Contract for BIS Web IO adapters exposed to the HTTP transport layer."""

from abc import ABC, abstractmethod


class BISWebIOInterface(ABC):
    """Define all user-facing HTTP operations managed by BIS Web IO."""

    @abstractmethod
    def user(self, authorization, required=True):
        """Authenticate and return the BIS user for an Authorization header."""

    @abstractmethod
    def health(self):
        """Return web service and database readiness."""

    @abstractmethod
    def cuisines(self):
        """Return the supported cuisine catalog."""

    @abstractmethod
    def active_model(self):
        """Return the formatted display label for the active AI model."""

    @abstractmethod
    def map_config(self):
        """Return map provider settings for the web UI."""

    @abstractmethod
    def register(self, payload):
        """Register a new BIS web user account."""

    @abstractmethod
    def login(self, payload):
        """Authenticate user credentials and issue a session token."""

    @abstractmethod
    def verify(self, payload):
        """Verify an account email code and return session details."""

    @abstractmethod
    def resend(self, payload):
        """Resend the email verification code."""

    @abstractmethod
    def me(self, authorization):
        """Return the authenticated user's session profile."""

    @abstractmethod
    def logout(self, authorization):
        """Invalidate the current bearer session token."""

    @abstractmethod
    def profile(self, authorization, user_id=None):
        """Return the authorized owner's saved profile."""

    @abstractmethod
    def save_profile(self, authorization, payload):
        """Update and return the authorized owner's saved profile."""

    @abstractmethod
    def search(self, authorization, payload):
        """Validate, confirm or execute a BIS search request."""

    @abstractmethod
    def chat(self, authorization, payload):
        """Process one conversational BIS assistant turn."""

    @abstractmethod
    def route(self, payload):
        """Return route directions and map link for a selected restaurant."""

    @abstractmethod
    def place_photo(self, place_id):
        """Return cached or freshly fetched thumbnail bytes for one place ID."""

    @abstractmethod
    def favorites(self, authorization):
        """List saved favorite restaurants for the authenticated user."""

    @abstractmethod
    def toggle_favorite(self, authorization, payload):
        """Add or remove a restaurant favorite for the authenticated user."""

    @abstractmethod
    def delete_favorite(self, authorization, key):
        """Delete one saved favorite restaurant by key."""

    @abstractmethod
    def history(self, authorization):
        """Return formatted search history for the authenticated user."""

    @abstractmethod
    def recent(self, authorization):
        """Return distinct recent search queries for the authenticated user."""

    @abstractmethod
    def clear_history(self, authorization):
        """Clear saved search history for the authenticated user."""
