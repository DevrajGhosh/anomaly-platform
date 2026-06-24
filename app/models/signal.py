# app/models/signal.py
"""
Signal model — stores every raw sensor reading.

This is the highest-volume table in the system.
Design decisions:
  - UUID primary key: avoids integer sequence bottlenecks under high insert load
  - timezone-aware timestamps: critical for multi-region deployments
  - metadata_ JSON column: flexible extra fields without schema changes
    (e.g. sensor firmware version, GPS coords, batch ID)
  - Indexed on (sensor_id, timestamp): the most common query pattern
    "give me all readings from sensor X in time range Y→Z"
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Signal(Base):
    __tablename__ = "signals"

    # ── Composite index defined here (see bottom of class) ─────────────────
    __table_args__ = (
        Index(
            "ix_signals_sensor_timestamp",
            "sensor_id",
            "timestamp",
            postgresql_using="btree",
        ),
        Index(
            "ix_signals_timestamp",
            "timestamp",
            postgresql_using="btree",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    sensor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sensors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="The raw numeric reading from the sensor",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the reading was recorded (UTC)",
    )
    source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Origin of the signal: 'mqtt', 'http', 'websocket', 'csv_import'",
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Arbitrary extra fields as JSON (e.g. location, batch_id)",
    )

    # ── Relationships ──────────────────────────────────────────────────────
    sensor: Mapped["Sensor"] = relationship(
        "Sensor",
        back_populates="signals",
    )
    anomalies: Mapped[list["Anomaly"]] = relationship(
        "Anomaly",
        back_populates="signal",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Signal id={self.id} sensor_id={self.sensor_id} "
            f"value={self.value} ts={self.timestamp}>"
        )