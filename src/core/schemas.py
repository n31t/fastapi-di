"""Base models for all API schemas."""
from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected (422), not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base for response schemas: buildable from ORM/DTO attributes."""

    model_config = ConfigDict(from_attributes=True)
