"""Errors raised when BRC cannot reach an AI provider."""


class AIServiceError(RuntimeError):
    """An AI provider could not complete a BRC request."""
