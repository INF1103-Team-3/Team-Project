"""HTTP input schema; domain validation remains in the managers."""
from pydantic import BaseModel, Field, ConfigDict
from BIS.classes.logic.security.password_hasher import PasswordHasher


class RegisterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(
        min_length=PasswordHasher.MIN_LENGTH,
        max_length=PasswordHasher.MAX_LENGTH,
    )
