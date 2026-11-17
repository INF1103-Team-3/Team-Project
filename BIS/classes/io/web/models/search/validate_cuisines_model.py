"""HTTP input schema for live custom-cuisine validation."""

from pydantic import BaseModel, ConfigDict, Field


class ValidateCuisinesModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    cuisines: list[str] = Field(default_factory=list, max_length=20)
    field_label: str = Field(default="Cuisine", max_length=50)
