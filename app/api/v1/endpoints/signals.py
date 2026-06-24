# app/api/v1/endpoints/signals.py
"""
Signal ingestion and retrieval endpoints.
Now uses IngestionService for full pipeline (DB + Redis).
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import signal as crud_signal
from app.db.session import get_db
from app.schemas.signal import (
    AnomalyListResponse,
    SignalBulkCreate,
    SignalCreate,
    SignalListResponse,
    SignalResponse,
)
from app.services.ingestion import ingestion_service

router = APIRouter(prefix="/signals", tags=["Signals"])


@router.post(
    "/",
    response_model=SignalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a single signal reading",
)
async def ingest_signal(
    payload: SignalCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        signal = await ingestion_service.ingest_single(db, payload)
        return signal
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/bulk",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest multiple signal readings at once",
)
async def ingest_signals_bulk(
    payload: SignalBulkCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        signals = await ingestion_service.ingest_bulk(db, payload.signals)
        return {"inserted": len(signals), "ids": [str(s.id) for s in signals]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=SignalListResponse,
    summary="List signals with optional filters",
)
async def list_signals(
    sensor_id: Optional[uuid.UUID] = Query(default=None),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    total, signals = await crud_signal.get_signals(
        db,
        sensor_id=sensor_id,
        start_time=start_time,
        end_time=end_time,
        skip=skip,
        limit=limit,
    )
    return SignalListResponse(total=total, items=signals)


@router.get(
    "/{signal_id}",
    response_model=SignalResponse,
    summary="Get a single signal by ID",
)
async def get_signal(
    signal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    signal = await crud_signal.get_signal(db, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found.")
    return signal


# ── Anomaly endpoints ──────────────────────────────────────────────────────

router_anomalies = APIRouter(prefix="/anomalies", tags=["Anomalies"])


@router_anomalies.get(
    "/",
    response_model=AnomalyListResponse,
    summary="List anomalies with optional filters",
)
async def list_anomalies(
    sensor_id: Optional[uuid.UUID] = Query(default=None),
    model_name: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    total, anomalies = await crud_signal.get_anomalies(
        db,
        sensor_id=sensor_id,
        model_name=model_name,
        severity=severity,
        skip=skip,
        limit=limit,
    )
    return AnomalyListResponse(total=total, items=anomalies)