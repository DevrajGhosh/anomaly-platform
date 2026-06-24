# app/schemas/signal.py
"""
Pydantic schemas for Signal and Anomaly API.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Signal Schemas ─────────────────────────────────────────────────────────

class SignalBase(BaseModel):
    sensor_id: uuid.UUID = Field(..., description="ID of the sensor that produced this signal")
    value: float = Field(..., description="Raw numeric reading")
    timestamp: Optional[datetime] = Field(
        None,
        description="When the reading was taken. Defaults to now if not provided."
    )
    source: Optional[str] = Field(
        None,
        max_length=100,
        examples=["http", "mqtt", "websocket", "csv_import"]
    )
    metadata_: Optional[dict[str, Any]] = Field(
        None,
        alias="metadata",
        description="Arbitrary extra fields as JSON"
    )

    model_config = {"populate_by_name": True}


class SignalCreate(SignalBase):
    """Used for POST /signals."""
    pass


class SignalResponse(BaseModel):
    """Returned to client."""
    id: uuid.UUID
    sensor_id: uuid.UUID
    value: float
    timestamp: datetime
    source: Optional[str]
    metadata: Optional[dict[str, Any]] = Field(None, alias="metadata_")
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class SignalListResponse(BaseModel):
    total: int
    items: list[SignalResponse]


# ── Bulk ingest schema ─────────────────────────────────────────────────────

class SignalBulkCreate(BaseModel):
    """
    Used for POST /signals/bulk — ingest multiple readings at once.
    Useful for batch imports and high-frequency sensors.
    """
    signals: list[SignalCreate] = Field(..., min_length=1, max_length=1000)


# ── Anomaly Schemas ────────────────────────────────────────────────────────

class AnomalyResponse(BaseModel):
    id: uuid.UUID
    signal_id: uuid.UUID
    model_name: str
    anomaly_score: float
    threshold: float
    severity: str
    is_confirmed: Optional[bool]
    explanation: Optional[dict[str, Any]]
    notes: Optional[str]
    detected_at: datetime

    model_config = {"from_attributes": True}


class AnomalyListResponse(BaseModel):
    total: int
    items: list[AnomalyResponse]