# app/services/ingestion.py
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client
from app.crud import sensor as crud_sensor
from app.crud import signal as crud_signal
from app.models.signal import Signal
from app.schemas.signal import SignalCreate

logger = logging.getLogger(__name__)

CHANNEL_SIGNALS_LIVE = "signals:live"
CHANNEL_SIGNALS_SENSOR = "signals:sensor:{sensor_id}"


class IngestionService:

    async def ingest_single(
        self,
        db: AsyncSession,
        data: SignalCreate,
        validate_sensor: bool = True,
    ) -> Signal:

        # ── 1. Validate sensor ────────────────────────────────────────────
        if validate_sensor:
            sensor = await crud_sensor.get_sensor(db, data.sensor_id)
            if not sensor:
                raise ValueError(f"Sensor '{data.sensor_id}' not found.")
            if not sensor.is_active:
                raise ValueError(f"Sensor '{sensor.name}' is inactive.")

        # ── 2. Save to PostgreSQL ─────────────────────────────────────────
        signal = await crud_signal.create_signal(db, data)

        # ── 3. Append to rolling window in Redis ──────────────────────────
        window_key = f"window:sensor:{signal.sensor_id}"
        await redis_client.lpush_with_trim(
            key=window_key,
            value={
                "id": str(signal.id),
                "value": signal.value,
                "timestamp": signal.timestamp.isoformat(),
            },
            max_length=200,
        )

        # ── 4. Publish to Redis pub/sub ───────────────────────────────────
        payload = {
            "id": str(signal.id),
            "sensor_id": str(signal.sensor_id),
            "value": signal.value,
            "timestamp": signal.timestamp.isoformat(),
            "source": signal.source,
        }

        await redis_client.publish(CHANNEL_SIGNALS_LIVE, payload)

        sensor_channel = CHANNEL_SIGNALS_SENSOR.format(
            sensor_id=signal.sensor_id
        )
        await redis_client.publish(sensor_channel, payload)

        # ── 5. Trigger Celery ML detection task (safe) ────────────────────
        try:
            from app.workers.tasks import detect_anomaly_task
            detect_anomaly_task.delay(payload)
        except Exception as e:
            logger.error(f"Failed to queue ML task: {e}")
            # Signal is already saved — don't fail the request

        return signal

    async def ingest_bulk(
        self,
        db: AsyncSession,
        signals_data: list[SignalCreate],
    ) -> list[Signal]:

        sensor_ids = {s.sensor_id for s in signals_data}
        for sensor_id in sensor_ids:
            sensor = await crud_sensor.get_sensor(db, sensor_id)
            if not sensor:
                raise ValueError(f"Sensor '{sensor_id}' not found.")
            if not sensor.is_active:
                raise ValueError(f"Sensor '{sensor.name}' is inactive.")

        signals = await crud_signal.create_signals_bulk(db, signals_data)

        for signal in signals:
            window_key = f"window:sensor:{signal.sensor_id}"
            await redis_client.lpush_with_trim(
                key=window_key,
                value={
                    "id": str(signal.id),
                    "value": signal.value,
                    "timestamp": signal.timestamp.isoformat(),
                },
                max_length=200,
            )

            payload = {
                "id": str(signal.id),
                "sensor_id": str(signal.sensor_id),
                "value": signal.value,
                "timestamp": signal.timestamp.isoformat(),
                "source": signal.source,
            }
            await redis_client.publish(CHANNEL_SIGNALS_LIVE, payload)

            try:
                from app.workers.tasks import detect_anomaly_task
                detect_anomaly_task.delay(payload)
            except Exception as e:
                logger.error(f"Failed to queue ML task: {e}")

        return signals


ingestion_service = IngestionService()