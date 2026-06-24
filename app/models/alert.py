# app/models/alert.py
"""
Alert Rule and Alert Event models.

AlertRule: defines WHEN to fire an alert (conditions)
AlertEvent: records THAT an alert fired (history)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AlertRule(Base):
    """
    Defines a condition that triggers an alert.

    Examples:
      - severity IN ('critical', 'high')
      - anomaly_score >= 0.8
      - model_name = 'isolation_forest' AND severity = 'critical'
    """
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Trigger conditions ─────────────────────────────────────────────────
    min_anomaly_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Fire if anomaly_score >= this value"
    )
    severities: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="Fire if severity in this list e.g. ['critical','high']"
    )
    model_names: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="Only fire for these models. None = all models."
    )
    sensor_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="Only fire for these sensor IDs. None = all sensors."
    )

    # ── Delivery ───────────────────────────────────────────────────────────
    channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="log",
        comment="Delivery channel: 'log' | 'webhook'"
    )
    webhook_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="URL to POST alert payload to (if channel=webhook)"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ── Relationships ──────────────────────────────────────────────────────
    events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="rule", cascade="all, delete-orphan"
    )

    def matches(self, anomaly_data: dict) -> bool:
        """Check if an anomaly matches this rule's conditions."""
        if not self.is_active:
            return False

        score = anomaly_data.get("anomaly_score", 0)
        severity = anomaly_data.get("severity", "low")
        model = anomaly_data.get("model_name", "")
        sensor_id = anomaly_data.get("sensor_id", "")

        if self.min_anomaly_score and score < self.min_anomaly_score:
            return False
        if self.severities and severity not in self.severities:
            return False
        if self.model_names and model not in self.model_names:
            return False
        if self.sensor_ids and sensor_id not in self.sensor_ids:
            return False

        return True


class AlertEvent(Base):
    """Records every fired alert for audit history."""
    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    anomaly_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="The anomaly that triggered this alert"
    )
    sensor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False,
        comment="Full alert payload that was delivered"
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    rule: Mapped["AlertRule"] = relationship("AlertRule", back_populates="events")
    