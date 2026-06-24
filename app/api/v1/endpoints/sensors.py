# app/api/v1/endpoints/sensors.py
"""
Sensor API endpoints.

Why versioned routes (/api/v1/...)?
  Allows breaking changes in v2 without breaking existing clients.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import sensor as crud_sensor
from app.db.session import get_db
from app.schemas.sensor import (
    SensorCreate,
    SensorListResponse,
    SensorResponse,
    SensorUpdate,
)

router = APIRouter(prefix="/sensors", tags=["Sensors"])


@router.post(
    "/",
    response_model=SensorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new sensor",
)
async def create_sensor(
    payload: SensorCreate,
    db: AsyncSession = Depends(get_db),
):
    # Check for duplicate name
    existing = await crud_sensor.get_sensor_by_name(db, payload.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sensor with name '{payload.name}' already exists.",
        )
    sensor = await crud_sensor.create_sensor(db, payload)
    return sensor


@router.get(
    "/",
    response_model=SensorListResponse,
    summary="List all sensors",
)
async def list_sensors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    total, sensors = await crud_sensor.get_sensors(
        db, skip=skip, limit=limit, active_only=active_only
    )
    return SensorListResponse(total=total, items=sensors)


@router.get(
    "/{sensor_id}",
    response_model=SensorResponse,
    summary="Get a sensor by ID",
)
async def get_sensor(
    sensor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    sensor = await crud_sensor.get_sensor(db, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found.")
    return sensor


@router.patch(
    "/{sensor_id}",
    response_model=SensorResponse,
    summary="Update a sensor",
)
async def update_sensor(
    sensor_id: uuid.UUID,
    payload: SensorUpdate,
    db: AsyncSession = Depends(get_db),
):
    sensor = await crud_sensor.get_sensor(db, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found.")
    return await crud_sensor.update_sensor(db, sensor, payload)


@router.delete(
    "/{sensor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sensor",
)
async def delete_sensor(
    sensor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    sensor = await crud_sensor.get_sensor(db, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found.")
    await crud_sensor.delete_sensor(db, sensor)

# Add this import at the top of sensors.py
from app.core.websocket_manager import ws_manager

# Add this route at the bottom of sensors.py
@router.get(
    "/ws/stats",
    tags=["WebSockets"],
    summary="Get active WebSocket connection counts",
)
async def websocket_stats():
    """Shows how many clients are currently connected via WebSocket."""
    return ws_manager.get_stats()