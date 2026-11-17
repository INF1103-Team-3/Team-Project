"""HTTP input schema; domain validation remains in the managers."""

from pydantic import BaseModel, ConfigDict


class FavoriteToggleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    restaurant: dict
