"""HTTP input schema; domain validation remains in the managers."""
from pydantic import BaseModel, Field, ConfigDict


class RegisterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)
