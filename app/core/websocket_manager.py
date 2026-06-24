# app/core/websocket_manager.py
"""
WebSocket Connection Manager.

Tracks all active WebSocket connections and handles broadcasting.

Why a manager class?
  Multiple clients can connect simultaneously.
  When a Redis message arrives, we need to send it to ALL connected clients.
  The manager maintains the registry and handles dead connections gracefully.

Connection types:
  - "live"      : receives all signals
  - "sensor"    : receives signals for one specific sensor
  - "anomalies" : receives anomaly alerts only
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Optional
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # All active connections for the global live feed
        self._live_connections: set[WebSocket] = set()

        # Per-sensor connections: {sensor_id: set of websockets}
        self._sensor_connections: defaultdict[str, set[WebSocket]] = defaultdict(set)

        # Anomaly alert connections
        self._anomaly_connections: set[WebSocket] = set()

    # ── Connection lifecycle ───────────────────────────────────────────────

    async def connect_live(self, websocket: WebSocket) -> None:
        """Accept and register a live feed connection."""
        await websocket.accept()
        self._live_connections.add(websocket)
        logger.info(
            f"WebSocket connected (live). Total: {len(self._live_connections)}"
        )

    async def connect_sensor(
        self, websocket: WebSocket, sensor_id: str
    ) -> None:
        """Accept and register a per-sensor connection."""
        await websocket.accept()
        self._sensor_connections[sensor_id].add(websocket)
        logger.info(
            f"WebSocket connected (sensor={sensor_id}). "
            f"Total for sensor: {len(self._sensor_connections[sensor_id])}"
        )

    async def connect_anomalies(self, websocket: WebSocket) -> None:
        """Accept and register an anomaly alert connection."""
        await websocket.accept()
        self._anomaly_connections.add(websocket)
        logger.info(
            f"WebSocket connected (anomalies). "
            f"Total: {len(self._anomaly_connections)}"
        )

    def disconnect_live(self, websocket: WebSocket) -> None:
        self._live_connections.discard(websocket)
        logger.info(
            f"WebSocket disconnected (live). Total: {len(self._live_connections)}"
        )

    def disconnect_sensor(self, websocket: WebSocket, sensor_id: str) -> None:
        self._sensor_connections[sensor_id].discard(websocket)
        logger.info(f"WebSocket disconnected (sensor={sensor_id})")

    def disconnect_anomalies(self, websocket: WebSocket) -> None:
        self._anomaly_connections.discard(websocket)
        logger.info(
            f"WebSocket disconnected (anomalies). "
            f"Total: {len(self._anomaly_connections)}"
        )

    # ── Broadcasting ───────────────────────────────────────────────────────

    async def broadcast_live(self, message: dict) -> None:
        """Send a message to all live feed subscribers."""
        await self._broadcast_to_set(self._live_connections, message)

    async def broadcast_sensor(self, sensor_id: str, message: dict) -> None:
        """Send a message to all subscribers of a specific sensor."""
        connections = self._sensor_connections.get(sensor_id, set())
        await self._broadcast_to_set(connections, message)

    async def broadcast_anomaly(self, message: dict) -> None:
        """Send an anomaly alert to all anomaly subscribers."""
        await self._broadcast_to_set(self._anomaly_connections, message)

    async def _broadcast_to_set(
        self, connections: set[WebSocket], message: dict
    ) -> None:
        """
        Send message to a set of connections.
        Handles dead connections gracefully — removes them on failure.
        Uses asyncio.gather for concurrent sends (faster with many clients).
        """
        if not connections:
            return

        dead_connections = set()
        message_text = json.dumps(message)

        async def send_safe(ws: WebSocket) -> None:
            try:
                await ws.send_text(message_text)
            except Exception:
                dead_connections.add(ws)

        await asyncio.gather(*[send_safe(ws) for ws in connections.copy()])

        # Clean up dead connections
        for ws in dead_connections:
            connections.discard(ws)

    # ── Stats ──────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return connection counts for monitoring."""
        return {
            "live_connections": len(self._live_connections),
            "anomaly_connections": len(self._anomaly_connections),
            "sensor_connections": {
                sensor_id: len(conns)
                for sensor_id, conns in self._sensor_connections.items()
                if conns
            },
        }


# Singleton
ws_manager = ConnectionManager()