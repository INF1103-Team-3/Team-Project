"""HTTP input schema for seen restaurants excluded on refresh."""
from pydantic import BaseModel, ConfigDict, Field


class PreviousRestaurantModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    google_place_id: str | None = Field(default=None, max_length=256)
    name: str = Field(default="", max_length=300)
    address: str = Field(default="", max_length=500)
