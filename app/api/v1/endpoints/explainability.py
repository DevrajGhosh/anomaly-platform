# app/api/v1/endpoints/explainability.py
"""
Explainability API endpoints.

Provides human-readable explanations for anomaly detections.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.anomaly import Anomaly
from app.models.signal import Signal
from app.services.explainability import explainability_service

router = APIRouter(prefix="/explain", tags=["Explainability"])


@router.get(
    "/anomaly/{anomaly_id}",
    summary="Get human-readable explanation for a specific anomaly",
)
async def explain_anomaly(
    anomaly_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a detailed plain-English explanation of why an anomaly was detected.
    Includes contributing factors ranked by impact.
    """
    result = await db.execute(
        select(Anomaly).where(Anomaly.id == anomaly_id)
    )
    anomaly = result.scalar_one_or_none()

    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found.")

    anomaly_data = {
        "id": str(anomaly.id),
        "signal_id": str(anomaly.signal_id),
        "model_name": anomaly.model_name,
        "anomaly_score": anomaly.anomaly_score,
        "severity": anomaly.severity,
        "explanation": anomaly.explanation,
        "detected_at": anomaly.detected_at.isoformat(),
    }

    explanation = explainability_service.explain_anomaly(anomaly_data)

    return {
        "anomaly_id": str(anomaly_id),
        "model_name": anomaly.model_name,
        "severity": anomaly.severity,
        "anomaly_score": anomaly.anomaly_score,
        **explanation,
    }


@router.get(
    "/signal/{signal_id}",
    summary="Get model comparison for all anomalies on a signal",
)
async def explain_signal(
    signal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    For a given signal, shows how all models scored it.
    Useful for understanding model agreement/disagreement.
    """
    # Get signal
    signal_result = await db.execute(
        select(Signal).where(Signal.id == signal_id)
    )
    signal = signal_result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found.")

    # Get all anomalies for this signal
    anomalies_result = await db.execute(
        select(Anomaly).where(Anomaly.signal_id == signal_id)
    )
    anomalies = anomalies_result.scalars().all()

    anomalies_data = [
        {
            "id": str(a.id),
            "model_name": a.model_name,
            "anomaly_score": a.anomaly_score,
            "severity": a.severity,
            "explanation": a.explanation,
        }
        for a in anomalies
    ]

    comparison = explainability_service.compare_models(anomalies_data)

    # Get individual explanations per model
    individual_explanations = {}
    for a_data in anomalies_data:
        model = a_data["model_name"]
        individual_explanations[model] = explainability_service.explain_anomaly(a_data)

    return {
        "signal_id": str(signal_id),
        "signal_value": signal.value,
        "signal_timestamp": signal.timestamp.isoformat(),
        "sensor_id": str(signal.sensor_id),
        "anomaly_count": len(anomalies),
        "model_comparison": comparison,
        "explanations_by_model": individual_explanations,
    }


@router.get(
    "/recent",
    summary="Get explanations for recent anomalies",
)
async def explain_recent(
    limit: int = Query(default=5, ge=1, le=20),
    severity: Optional[str] = Query(default=None),
    model_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns explanations for the most recent anomalies.
    Useful for a live anomaly feed with explanations.
    """
    query = select(Anomaly)
    if severity:
        query = query.where(Anomaly.severity == severity)
    if model_name:
        query = query.where(Anomaly.model_name == model_name)

    result = await db.execute(
        query.order_by(Anomaly.detected_at.desc()).limit(limit)
    )
    anomalies = result.scalars().all()

    explained = []
    for anomaly in anomalies:
        anomaly_data = {
            "id": str(anomaly.id),
            "model_name": anomaly.model_name,
            "anomaly_score": anomaly.anomaly_score,
            "severity": anomaly.severity,
            "explanation": anomaly.explanation,
        }
        exp = explainability_service.explain_anomaly(anomaly_data)
        explained.append({
            "anomaly_id": str(anomaly.id),
            "signal_id": str(anomaly.signal_id),
            "model_name": anomaly.model_name,
            "severity": anomaly.severity,
            "anomaly_score": anomaly.anomaly_score,
            "detected_at": anomaly.detected_at.isoformat(),
            "plain_english": exp["plain_english"],
            "summary": exp["summary"],
            "top_factor": exp["factors"][0] if exp["factors"] else None,
        })

    return {
        "total": len(explained),
        "anomalies": explained,
    }


@router.get(
    "/sensor/{sensor_id}/summary",
    summary="Get anomaly explanation summary for a sensor",
)
async def sensor_explanation_summary(
    sensor_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Summarizes anomaly patterns for a sensor.
    Shows most common anomaly types and severity distribution.
    """
    from sqlalchemy import func

    # Get recent anomalies for this sensor
    result = await db.execute(
        select(Anomaly)
        .join(Signal, Signal.id == Anomaly.signal_id)
        .where(Signal.sensor_id == sensor_id)
        .order_by(Anomaly.detected_at.desc())
        .limit(limit)
    )
    anomalies = result.scalars().all()

    if not anomalies:
        return {
            "sensor_id": str(sensor_id),
            "message": "No anomalies found for this sensor.",
            "anomaly_count": 0,
        }

    # Aggregate stats
    severity_counts = {}
    model_counts = {}
    avg_z_scores = []
    avg_scores = []

    for a in anomalies:
        severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1
        model_counts[a.model_name] = model_counts.get(a.model_name, 0) + 1
        avg_scores.append(a.anomaly_score)
        if a.explanation and "z_score" in a.explanation:
            avg_z_scores.append(abs(a.explanation["z_score"]))

    # Most common factor
    most_active_model = max(model_counts, key=model_counts.get)
    dominant_severity = max(severity_counts, key=severity_counts.get)

    summary_text = (
        f"Sensor has {len(anomalies)} recent anomalies. "
        f"Most detections by {most_active_model.replace('_', ' ')} model. "
        f"Dominant severity: {dominant_severity}. "
        f"Average anomaly score: {sum(avg_scores)/len(avg_scores):.4f}."
    )
    if avg_z_scores:
        summary_text += f" Average z-score magnitude: {sum(avg_z_scores)/len(avg_z_scores):.2f}."

    return {
        "sensor_id": str(sensor_id),
        "anomaly_count": len(anomalies),
        "summary": summary_text,
        "severity_distribution": severity_counts,
        "detections_by_model": model_counts,
        "average_anomaly_score": round(sum(avg_scores) / len(avg_scores), 4),
        "average_z_score_magnitude": (
            round(sum(avg_z_scores) / len(avg_z_scores), 4) if avg_z_scores else None
        ),
    }