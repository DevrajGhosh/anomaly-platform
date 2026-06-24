# app/crud/sensor.py
"""
CRUD operations for Sensor.

All functions are async and accept a SQLAlchemy AsyncSession.
They contain ONLY database logic — no HTTP, no FastAPI.
"""

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensor import Sensor
from app.schemas.sensor import SensorCreate, SensorUpdate


async def create_sensor(db: AsyncSession, data: SensorCreate) -> Sensor:
    """Insert a new sensor row and return it."""
    sensor = Sensor(**data.model_dump())
    db.add(sensor)
    await db.flush()        # Writes to DB but doesn't commit yet
    await db.refresh(sensor)  # Reload to get DB-generated values (id, timestamps)
    return sensor


async def get_sensor(db: AsyncSession, sensor_id: uuid.UUID) -> Optional[Sensor]:
    """Fetch a single sensor by primary key."""
    result = await db.execute(
        select(Sensor).where(Sensor.id == sensor_id)
    )
    return result.scalar_one_or_none()


async def get_sensor_by_name(db: AsyncSession, name: str) -> Optional[Sensor]:
    """Fetch a sensor by its unique name."""
    result = await db.execute(
        select(Sensor).where(Sensor.name == name)
    )
    return result.scalar_one_or_none()


async def get_sensors(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
) -> tuple[int, list[Sensor]]:
    """
    Return paginated list of sensors.
    Returns (total_count, items) tuple.
    """
    query = select(Sensor)

    if active_only:
        query = query.where(Sensor.is_active == True)  # noqa: E712

    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    # Get paginated items
    result = await db.execute(
        query.order_by(Sensor.created_at.desc()).offset(skip).limit(limit)
    )
    sensors = result.scalars().all()

    return total, list(sensors)


async def update_sensor(
    db: AsyncSession,
    sensor: Sensor,
    data: SensorUpdate,
) -> Sensor:
    """Apply partial update to a sensor."""
    update_data = data.model_dump(exclude_unset=True)  # Only update provided fields
    for field, value in update_data.items():
        setattr(sensor, field, value)
    await db.flush()
    await db.refresh(sensor)
    return sensor


async def delete_sensor(db: AsyncSession, sensor: Sensor) -> None:
    """Delete a sensor (cascades to signals and anomalies)."""
    await db.delete(sensor)
    await db.flush()