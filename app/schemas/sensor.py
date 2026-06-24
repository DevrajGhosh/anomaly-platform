# app/schemas/sensor.py
"""
Pydantic schemas for Sensor API.

Three schemas per resource is a common pattern:
  - Base:    shared fields
  - Create:  fields required on POST (no id, no timestamps)
  - Response: fields returned to client (includes id, timestamps)
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SensorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["temperature-probe-01"])
    description: Optional[str] = Field(None, examples=["Main reactor temperature sensor"])
    unit: Optional[str] = Field(None, max_length=50, examples=["celsius"])
    min_expected: Optional[float] = Field(None, examples=[-50.0])
    max_expected: Optional[float] = Field(None, examples=[200.0])
    is_active: bool = Field(default=True)


class SensorCreate(SensorBase):
    """Used for POST /sensors — client sends this."""
    pass


class SensorUpdate(BaseModel):
    """Used for PATCH /sensors/{id} — all fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    unit: Optional[str] = Field(None, max_length=50)
    min_expected: Optional[float] = None
    max_expected: Optional[float] = None
    is_active: Optional[bool] = None


class SensorResponse(SensorBase):
    """Returned to client — includes DB-generated fields."""
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}  # Allows ORM model → schema conversion


class SensorListResponse(BaseModel):
    """Paginated list response."""
    total: int
    items: list[SensorResponse]