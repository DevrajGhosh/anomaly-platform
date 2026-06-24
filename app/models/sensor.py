# app/models/sensor.py
"""
Sensor registry model.

A 'sensor' represents a physical or virtual signal source.
Examples: temperature probe, vibration sensor, network latency monitor.

Why a separate table?
  - Avoids duplicating sensor metadata on every signal row
  - Lets us store per-sensor config (unit, expected range, active status)
  - Enables multi-sensor dashboards and filtering
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique sensor identifier (UUID)",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="Human-readable sensor name, e.g. 'temperature-probe-01'",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional description of what this sensor monitors",
    )
    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Measurement unit, e.g. 'celsius', 'hz', 'ms'",
    )
    min_expected: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Minimum expected value (used for UI scaling and soft validation)",
    )
    max_expected: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Maximum expected value",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Inactive sensors are ignored by the ingestion pipeline",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    signals: Mapped[list["Signal"]] = relationship(
        "Signal",
        back_populates="sensor",
        cascade="all, delete-orphan",   # Delete signals when sensor is deleted
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Sensor id={self.id} name={self.name} active={self.is_active}>"