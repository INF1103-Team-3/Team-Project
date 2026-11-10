"""Persistence errors exposed by the BRC Data Manager."""


class DataUnavailableError(ValueError):
    """A required BRC data file is missing, corrupt, invalid, or stale."""
