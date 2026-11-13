"""Web route request validation; BIS validates user IO before delegating to BRNS."""
from pydantic import BaseModel, ConfigDict, Field


class RouteRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    origin_lat: float = Field(ge=1.15, le=1.48)
    origin_lng: float = Field(ge=103.60, le=104.10)
    dest_lat: float = Field(ge=1.15, le=1.48)
    dest_lng: float = Field(ge=103.60, le=104.10)
    name: str = "Restaurant"
    mode: str = Field(default="walk", pattern="^(walk|drive|transit)$")
    traffic_aware: bool = False
