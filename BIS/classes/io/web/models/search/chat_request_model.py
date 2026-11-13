"""Validated payload model for BIS conversational search chat turns."""
from typing import Any
from pydantic import BaseModel, Field


class ChatRequestModel(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    current_filters: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)
    onboarding: bool = False
    awaiting_field: str | None = None
