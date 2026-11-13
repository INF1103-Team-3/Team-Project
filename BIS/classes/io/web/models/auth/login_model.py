"""HTTP input schema; domain validation remains in the managers."""
from pydantic import BaseModel, Field, ConfigDict


class LoginModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
