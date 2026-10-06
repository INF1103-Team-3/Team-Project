from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchRequest:
    """What the user is looking for, collected by the I/O Manager."""

    location: str
    food_type: str  # "halal", "non-halal" or "vegetarian"
    max_walk_min: int
    min_rating: float  # 0.0 means "any rating"
    max_budget: float | None  # None means "no limit"
