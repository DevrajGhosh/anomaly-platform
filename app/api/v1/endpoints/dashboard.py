# app/api/v1/endpoints/dashboard.py
"""
Dashboard summary endpoints.

These endpoints are designed for frontend consumption:
  - One call returns everything the dashboard needs
  - All queries are optimised (single DB round trip where possible)
  - Includes real-time WebSocket connection stats
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.anomaly import Anomaly
from app.models.sensor import Sensor
from app.models.signal import Signal
from app.core.redis import redis_client
from app.core.websocket_manager import ws_manager

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", summary="Get overall platform statistics")
async def get_dashboard_stats(
    hours: int = Query(default=24, ge=1, le=168, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a complete dashboard summary:
      - Signal and anomaly counts
      - Anomaly rate
      - Severity breakdown
      - Recent anomalies
      - Top sensors by anomaly count
      - WebSocket connection stats
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # ── Total signals in window ────────────────────────────────────────────
    total_signals_result = await db.execute(
        select(func.count(Signal.id)).where(Signal.timestamp >= since)
    )
    total_signals = total_signals_result.scalar_one()

    # ── Total anomalies in window ──────────────────────────────────────────
    total_anomalies_result = await db.execute(
        select(func.count(Anomaly.id)).where(Anomaly.detected_at >= since)
    )
    total_anomalies = total_anomalies_result.scalar_one()

    # ── Severity breakdown ─────────────────────────────────────────────────
    severity_result = await db.execute(
        select(Anomaly.severity, func.count(Anomaly.id))
        .where(Anomaly.detected_at >= since)
        .group_by(Anomaly.severity)
    )
    severity_breakdown = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }
    for severity, count in severity_result.all():
        severity_breakdown[severity] = count

    # ── Anomaly rate ───────────────────────────────────────────────────────
    anomaly_rate = (
        round(total_anomalies / total_signals * 100, 2)
        if total_signals > 0
        else 0.0
    )

    # ── Recent anomalies (last 10) ─────────────────────────────────────────
    recent_anomalies_result = await db.execute(
        select(Anomaly)
        .where(Anomaly.detected_at >= since)
        .order_by(Anomaly.detected_at.desc())
        .limit(10)
    )
    recent_anomalies = recent_anomalies_result.scalars().all()

    recent_anomalies_list = [
        {
            "id": str(a.id),
            "signal_id": str(a.signal_id),
            "model_name": a.model_name,
            "anomaly_score": round(a.anomaly_score, 4),
            "severity": a.severity,
            "detected_at": a.detected_at.isoformat(),
        }
        for a in recent_anomalies
    ]

    # ── Top sensors by anomaly count ───────────────────────────────────────
    top_sensors_result = await db.execute(
        select(Signal.sensor_id, func.count(Anomaly.id).label("anomaly_count"))
        .join(Anomaly, Anomaly.signal_id == Signal.id)
        .where(Anomaly.detected_at >= since)
        .group_by(Signal.sensor_id)
        .order_by(func.count(Anomaly.id).desc())
        .limit(5)
    )
    top_sensors = [
        {
            "sensor_id": str(sensor_id),
            "anomaly_count": count,
        }
        for sensor_id, count in top_sensors_result.all()
    ]

    # ── Active sensors ─────────────────────────────────────────────────────
    active_sensors_result = await db.execute(
        select(func.count(Sensor.id)).where(Sensor.is_active == True)  # noqa
    )
    active_sensors = active_sensors_result.scalar_one()

    # ── WebSocket stats ────────────────────────────────────────────────────
    ws_stats = ws_manager.get_stats()

    return {
        "period_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "total": total_signals,
            "active_sensors": active_sensors,
        },
        "anomalies": {
            "total": total_anomalies,
            "rate_percent": anomaly_rate,
            "severity_breakdown": severity_breakdown,
            "recent": recent_anomalies_list,
        },
        "top_sensors_by_anomalies": top_sensors,
        "websocket_connections": ws_stats,
    }


@router.get("/signals/timeseries", summary="Get signal values over time for charting")
async def get_signal_timeseries(
    sensor_id: str = Query(..., description="Sensor UUID"),
    hours: int = Query(default=1, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns time-series signal data for a sensor.
    Used by frontend charts to plot signal values over time.
    """
    from uuid import UUID
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(Signal.id, Signal.value, Signal.timestamp)
        .where(
            Signal.sensor_id == UUID(sensor_id),
            Signal.timestamp >= since,
        )
        .order_by(Signal.timestamp.asc())
        .limit(500)
    )
    rows = result.all()

    return {
        "sensor_id": sensor_id,
        "period_hours": hours,
        "data_points": len(rows),
        "timeseries": [
            {
                "id": str(row.id),
                "value": row.value,
                "timestamp": row.timestamp.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/signals/timeseries/with-anomalies", summary="Signal timeseries with anomaly markers")
async def get_signal_timeseries_with_anomalies(
    sensor_id: str = Query(..., description="Sensor UUID"),
    hours: int = Query(default=1, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns signal timeseries AND anomaly markers for the same period.
    Frontend uses this to overlay anomaly points on the signal chart.
    """
    from uuid import UUID
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    sensor_uuid = UUID(sensor_id)

    # Get signals
    signals_result = await db.execute(
        select(Signal.id, Signal.value, Signal.timestamp)
        .where(
            Signal.sensor_id == sensor_uuid,
            Signal.timestamp >= since,
        )
        .order_by(Signal.timestamp.asc())
        .limit(500)
    )
    signals = signals_result.all()

    # Get anomalies for these signals
    anomalies_result = await db.execute(
        select(Anomaly.signal_id, Anomaly.anomaly_score, Anomaly.severity, Anomaly.detected_at)
        .join(Signal, Signal.id == Anomaly.signal_id)
        .where(
            Signal.sensor_id == sensor_uuid,
            Anomaly.detected_at >= since,
        )
    )
    anomaly_map = {
        str(row.signal_id): {
            "anomaly_score": row.anomaly_score,
            "severity": row.severity,
        }
        for row in anomalies_result.all()
    }

    timeseries = []
    for row in signals:
        signal_id_str = str(row.id)
        point = {
            "id": signal_id_str,
            "value": row.value,
            "timestamp": row.timestamp.isoformat(),
            "is_anomaly": signal_id_str in anomaly_map,
        }
        if signal_id_str in anomaly_map:
            point["anomaly_score"] = anomaly_map[signal_id_str]["anomaly_score"]
            point["severity"] = anomaly_map[signal_id_str]["severity"]
        timeseries.append(point)

    return {
        "sensor_id": sensor_id,
        "period_hours": hours,
        "data_points": len(timeseries),
        "anomaly_count": len(anomaly_map),
        "timeseries": timeseries,
    }


@router.get("/health/system", summary="System health check with component status")
async def system_health(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check for monitoring.
    Checks DB, Redis, and WebSocket connections.
    """
    # Check DB
    db_healthy = False
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        pass

    # Check Redis
    redis_healthy = False
    try:
        await redis_client.client.ping()
        redis_healthy = True
    except Exception:
        pass

    ws_stats = ws_manager.get_stats()

    overall = "healthy" if db_healthy and redis_healthy else "degraded"

    return {
        "status": overall,
        "components": {
            "database": "healthy" if db_healthy else "unhealthy",
            "redis": "healthy" if redis_healthy else "unhealthy",
        },
        "websockets": ws_stats,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }