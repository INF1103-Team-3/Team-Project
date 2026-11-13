"""HTTP input schema; domain validation remains in the managers."""
from pydantic import BaseModel, Field, ConfigDict


class ResendOtpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    email: str = Field(min_length=3, max_length=254)
