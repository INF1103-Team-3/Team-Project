"""HTTP input schema; domain validation remains in the managers."""
from pydantic import BaseModel, Field, ConfigDict


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    user_id: str | None = None
    username: str = "BiteFinder User"
    email: str | None = None
    location: list[str] = Field(default_factory=list)
    max_distance_km: float | None = None
    max_travel_time_minutes: float | None = None
    budget_per_person: float | None = None
    dietary_requirements: list[str] = Field(default_factory=list)
    liked_cuisines: list[str] = Field(default_factory=list)
    disliked_cuisines: list[str] = Field(default_factory=list)
    other_preferences: list[str] = Field(default_factory=list)
