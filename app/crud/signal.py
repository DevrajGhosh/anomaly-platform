# app/crud/signal.py
"""
CRUD operations for Signal and Anomaly.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.anomaly import Anomaly
from app.models.signal import Signal
from app.schemas.signal import SignalCreate


async def create_signal(db: AsyncSession, data: SignalCreate) -> Signal:
    """Insert a single signal reading."""
    signal_data = data.model_dump(by_alias=False)

    # Default timestamp to now if not provided
    if signal_data.get("timestamp") is None:
        signal_data["timestamp"] = datetime.now(timezone.utc)

    # Handle metadata alias
    metadata_value = signal_data.pop("metadata_", None)

    signal = Signal(**signal_data, metadata_=metadata_value)
    db.add(signal)
    await db.flush()
    await db.refresh(signal)
    return signal


async def create_signals_bulk(
    db: AsyncSession,
    signals_data: list[SignalCreate],
) -> list[Signal]:
    """Bulk insert multiple signals efficiently."""
    now = datetime.now(timezone.utc)
    signals = []

    for data in signals_data:
        signal_data = data.model_dump(by_alias=False)
        if signal_data.get("timestamp") is None:
            signal_data["timestamp"] = now
        metadata_value = signal_data.pop("metadata_", None)
        signal = Signal(**signal_data, metadata_=metadata_value)
        signals.append(signal)

    db.add_all(signals)
    await db.flush()

    # Refresh all to get generated IDs
    for signal in signals:
        await db.refresh(signal)

    return signals


async def get_signal(db: AsyncSession, signal_id: uuid.UUID) -> Optional[Signal]:
    """Fetch a single signal by ID, including its anomalies."""
    result = await db.execute(
        select(Signal)
        .options(selectinload(Signal.anomalies))
        .where(Signal.id == signal_id)
    )
    return result.scalar_one_or_none()


async def get_signals(
    db: AsyncSession,
    sensor_id: Optional[uuid.UUID] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[Signal]]:
    """
    Return paginated signals with optional filters.
    Supports filtering by sensor, time range.
    """
    query = select(Signal)

    if sensor_id:
        query = query.where(Signal.sensor_id == sensor_id)
    if start_time:
        query = query.where(Signal.timestamp >= start_time)
    if end_time:
        query = query.where(Signal.timestamp <= end_time)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(Signal.timestamp.desc()).offset(skip).limit(limit)
    )
    return total, list(result.scalars().all())


async def get_anomalies(
    db: AsyncSession,
    sensor_id: Optional[uuid.UUID] = None,
    model_name: Optional[str] = None,
    severity: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[Anomaly]]:
    """Return paginated anomalies with optional filters."""
    query = select(Anomaly)

    if sensor_id:
        # Join to signals to filter by sensor
        query = query.join(Signal).where(Signal.sensor_id == sensor_id)
    if model_name:
        query = query.where(Anomaly.model_name == model_name)
    if severity:
        query = query.where(Anomaly.severity == severity)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(Anomaly.detected_at.desc()).offset(skip).limit(limit)
    )
    return total, list(result.scalars().all())