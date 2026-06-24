# app/workers/tasks.py
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from celery import Task
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


class AsyncTask(Task):
    def run_async(self, coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)


@celery_app.task(
    bind=True,
    base=AsyncTask,
    name="detect_anomaly",
    max_retries=3,
    default_retry_delay=5,
)
def detect_anomaly_task(self, signal_data: dict) -> dict:
    return self.run_async(_detect_anomaly_async(signal_data))


async def _detect_anomaly_async(signal_data: dict) -> dict:
    from app.core.redis import redis_client
    from app.db.session import AsyncSessionLocal
    from app.ml.anomaly_detector import ensemble
    from app.models.anomaly import Anomaly
    from app.services.alerting import alerting_service

    signal_id = signal_data["id"]
    sensor_id = signal_data["sensor_id"]
    value = float(signal_data["value"])

    logger.info(f"Running ensemble detection: signal={signal_id} value={value}")

    results = ensemble.score_all(sensor_id=sensor_id, value=value)

    anomalies_detected = []

    async with AsyncSessionLocal() as db:
        for model_name, result in results.items():
            logger.info(
                f"  [{model_name}] is_anomaly={result.is_anomaly} "
                f"score={result.anomaly_score:.4f} severity={result.severity}"
            )
            if result.is_anomaly:
                anomaly = Anomaly(
                    id=uuid.uuid4(),
                    signal_id=uuid.UUID(signal_id),
                    model_name=result.model_name,
                    anomaly_score=result.anomaly_score,
                    threshold=result.threshold,
                    severity=result.severity,
                    explanation=result.explanation,
                    detected_at=datetime.now(timezone.utc),
                )
                db.add(anomaly)
                anomalies_detected.append({
                    "id": str(anomaly.id),
                    "signal_id": signal_id,
                    "sensor_id": sensor_id,
                    "value": value,
                    "model_name": result.model_name,
                    "anomaly_score": result.anomaly_score,
                    "severity": result.severity,
                    "explanation": result.explanation,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        if anomalies_detected:
            await db.commit()

    # ── Publish + Alert for each detected anomaly ──────────────────────────
    if anomalies_detected:
        try:
            if redis_client._client is None:
                await redis_client.connect()

            for anomaly_data in anomalies_detected:
                # Publish to WebSocket clients
                await redis_client.publish("anomalies:live", anomaly_data)

                # Fire alert rules
                fired_rules = await alerting_service.process_anomaly(anomaly_data)
                if fired_rules:
                    logger.info(f"Fired alert rules: {fired_rules}")

        except Exception as e:
            logger.error(f"Post-detection error: {e}")

    return {
        "signal_id": signal_id,
        "models_run": list(results.keys()),
        "anomalies_detected": len(anomalies_detected),
        "results": {
            name: {
                "is_anomaly": r.is_anomaly,
                "score": r.anomaly_score,
                "severity": r.severity,
            }
            for name, r in results.items()
        },
    }