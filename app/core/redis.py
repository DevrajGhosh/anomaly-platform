# app/core/redis.py
"""
Async Redis client singleton.

Why a singleton?
  Creating a new Redis connection per request is expensive.
  One shared async connection pool handles all requests efficiently.

Redis roles in this system:
  1. Pub/Sub  — broadcast live signals to WebSocket clients
  2. Cache    — store recent signal windows for ML models
  3. Broker   — Celery task queue backend
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis

from app.core.config import settings


class RedisClient:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        """Initialize the Redis connection pool."""
        self._client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
        # Test connection
        await self._client.ping()
        print("   Redis       : ✅ Connected")

    async def disconnect(self):
        """Close Redis connection pool."""
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    async def publish(self, channel: str, data: dict[str, Any]) -> int:
        """
        Publish a message to a Redis channel.
        Returns number of subscribers that received the message.
        Serializes UUIDs and datetimes automatically.
        """
        message = json.dumps(data, default=self._json_serializer)
        return await self.client.publish(channel, message)

    async def set_with_expiry(
        self, key: str, value: Any, ttl_seconds: int = 3600
    ) -> None:
        """Store a value with automatic expiry (used for signal windows)."""
        serialized = json.dumps(value, default=self._json_serializer)
        await self.client.setex(key, ttl_seconds, serialized)

    async def get(self, key: str) -> Any | None:
        """Retrieve a cached value."""
        value = await self.client.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def lpush_with_trim(
        self, key: str, value: Any, max_length: int = 100
    ) -> None:
        """
        Push to a Redis list and trim to max_length.
        Used to maintain a rolling window of recent signals per sensor.
        """
        serialized = json.dumps(value, default=self._json_serializer)
        pipe = self.client.pipeline()
        pipe.lpush(key, serialized)
        pipe.ltrim(key, 0, max_length - 1)
        await pipe.execute()

    async def get_list(self, key: str, count: int = 100) -> list[Any]:
        """Retrieve a Redis list (signal window)."""
        items = await self.client.lrange(key, 0, count - 1)
        return [json.loads(item) for item in items]

    @staticmethod
    def _json_serializer(obj: Any) -> str:
        """Handle types that json.dumps can't serialize by default."""
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")


# Singleton instance — import this everywhere
redis_client = RedisClient()