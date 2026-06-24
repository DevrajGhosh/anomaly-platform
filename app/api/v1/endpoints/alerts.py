# app/api/v1/endpoints/alerts.py
"""
Alert rule management and alert event history endpoints.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.alert import AlertRule, AlertEvent

router = APIRouter(prefix="/alerts", tags=["Alerts"])


# ── Schemas ────────────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    min_anomaly_score: Optional[float] = None
    severities: Optional[list[str]] = None
    model_names: Optional[list[str]] = None
    sensor_ids: Optional[list[str]] = None
    channel: str = "log"
    webhook_url: Optional[str] = None
    is_active: bool = True


class AlertRuleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    min_anomaly_score: Optional[float]
    severities: Optional[list[str]]
    model_names: Optional[list[str]]
    sensor_ids: Optional[list[str]]
    channel: str
    webhook_url: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True, "protected_namespaces": ()}


# ── Alert Rule endpoints ───────────────────────────────────────────────────

@router.post("/rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert rule."""
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.get("/rules", summary="List all alert rules")
async def list_alert_rules(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    query = select(AlertRule)
    if active_only:
        query = query.where(AlertRule.is_active == True)  # noqa
    result = await db.execute(query.order_by(AlertRule.created_at.desc()))
    rules = result.scalars().all()
    return {"total": len(rules), "items": [
        {
            "id": str(r.id),
            "name": r.name,
            "channel": r.channel,
            "is_active": r.is_active,
            "min_anomaly_score": r.min_anomaly_score,
            "severities": r.severities,
            "model_names": r.model_names,
        }
        for r in rules
    ]}


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found.")
    await db.delete(rule)


# ── Alert Event endpoints ──────────────────────────────────────────────────

@router.get("/events", summary="List fired alert events")
async def list_alert_events(
    severity: Optional[str] = Query(default=None),
    delivered: Optional[bool] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(AlertEvent)
    if severity:
        query = query.where(AlertEvent.severity == severity)
    if delivered is not None:
        query = query.where(AlertEvent.delivered == delivered)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(AlertEvent.fired_at.desc()).offset(skip).limit(limit)
    )
    events = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": str(e.id),
                "rule_id": str(e.rule_id),
                "sensor_id": e.sensor_id,
                "model_name": e.model_name,
                "severity": e.severity,
                "anomaly_score": e.anomaly_score,
                "delivered": e.delivered,
                "fired_at": e.fired_at.isoformat(),
            }
            for e in events
        ],
    }