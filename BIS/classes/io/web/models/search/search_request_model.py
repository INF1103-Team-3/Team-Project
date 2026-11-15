"""HTTP input schema; domain validation remains in the managers."""

from pydantic import BaseModel, ConfigDict, Field

from BIS.classes.io.web.models.search.previous_restaurant_model import (
    PreviousRestaurantModel,
)


class SearchRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    location: str = Field(default="", max_length=500)
    locations: list[str] = Field(default_factory=list)
    mode: str = "walk"
    max_travel_minutes: float | None = 20
    max_distance_km: float | None = None
    budget_per_person: float = 20
    dietary_requirements: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    liked_cuisines: list[str] = Field(default_factory=list)
    disliked_cuisines: list[str] = Field(default_factory=list)
    other_preferences: list[str] = Field(default_factory=list)
    traffic_aware: bool = False
    confirmation_token: str | None = None
    confirm_only: bool = False
    previous_restaurants: list[PreviousRestaurantModel] = Field(
        default_factory=list, max_length=200
    )
    strict_exclude: bool = False
