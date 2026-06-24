# app/core/redis_subscriber.py
"""
Redis Pub/Sub subscriber that bridges Redis messages to WebSocket clients.

This runs as a background asyncio task for each WebSocket connection.

Flow:
  1. WebSocket client connects
  2. We create a Redis subscriber for the relevant channel
  3. Background task reads from Redis and forwards to WebSocket
  4. When WebSocket disconnects, we cancel the background task
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Channel name constants
CHANNEL_SIGNALS_LIVE = "signals:live"
CHANNEL_ANOMALIES_LIVE = "anomalies:live"


async def subscribe_and_forward(
    channel: str,
    websocket,
    manager,
    broadcast_fn,
) -> None:
    """
    Subscribe to a Redis channel and forward messages to WebSocket clients.

    Args:
        channel: Redis channel name to subscribe to
        websocket: The WebSocket connection (used to detect disconnection)
        manager: ConnectionManager instance
        broadcast_fn: Async function to call with each message
    """
    # Each subscriber needs its own Redis connection (pub/sub is stateful)
    redis_conn = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    pubsub = redis_conn.pubsub()
    await pubsub.subscribe(channel)
    logger.info(f"Subscribed to Redis channel: {channel}")

    try:
        async for raw_message in pubsub.listen():
            # Skip subscription confirmation messages
            if raw_message["type"] != "message":
                continue

            try:
                data = json.loads(raw_message["data"])
                await broadcast_fn(data)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON on channel {channel}")
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")
                break

    except asyncio.CancelledError:
        logger.info(f"Subscriber cancelled for channel: {channel}")
    finally:
        await pubsub.unsubscribe(channel)
        await redis_conn.aclose()
        logger.info(f"Unsubscribed from Redis channel: {channel}")