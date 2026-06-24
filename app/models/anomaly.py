# app/models/anomaly.py
"""
Anomaly model — records every detected anomaly.

Design decisions:
  - Decoupled from signals: one signal can be flagged by multiple models
  - model_name: tracks which ML model made the detection
  - anomaly_score: raw score from the model (for ranking severity)
  - is_confirmed: allows human-in-the-loop validation (Phase 7+)
  - explanation: JSON field for SHAP/feature importance values (Phase 8)
  - severity: derived label ('low', 'medium', 'high', 'critical')
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Anomaly(Base):
    __tablename__ = "anomalies"

    __table_args__ = (
        Index(
            "ix_anomalies_signal_id",
            "signal_id",
        ),
        Index(
            "ix_anomalies_detected_at",
            "detected_at",
            postgresql_using="btree",
        ),
        Index(
            "ix_anomalies_model_name",
            "model_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="ML model that detected this anomaly, e.g. 'isolation_forest'",
    )
    anomaly_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Raw anomaly score from the model (higher = more anomalous)",
    )
    threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Threshold value used at time of detection",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        comment="Derived severity: 'low' | 'medium' | 'high' | 'critical'",
    )
    is_confirmed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=None,
        comment="Human review: True=confirmed, False=false positive, None=unreviewed",
    )
    explanation: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="SHAP values or feature importance dict (populated in Phase 8)",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Analyst notes added during review",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="When the anomaly was detected by the ML pipeline",
    )

    # ── Relationships ──────────────────────────────────────────────────────
    signal: Mapped["Signal"] = relationship(
        "Signal",
        back_populates="anomalies",
    )

    def __repr__(self) -> str:
        return (
            f"<Anomaly id={self.id} model={self.model_name} "
            f"score={self.anomaly_score} severity={self.severity}>"
        )