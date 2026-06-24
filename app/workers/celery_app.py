# app/workers/celery_app.py
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "anomaly_platform",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    task_default_retry_delay=5,
    result_expires=3600,
    # Fix the deprecation warning
    broker_connection_retry_on_startup=True,
)