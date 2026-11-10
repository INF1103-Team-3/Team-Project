"""Errors raised for invalid BRC AI responses."""


class AIResponseError(ValueError):
    """An AI provider returned data that BRC cannot safely use."""
