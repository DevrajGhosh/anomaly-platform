# app/api/v1/endpoints/websockets.py
"""
WebSocket endpoints for real-time signal and anomaly streaming.

Three endpoints:
  /ws/signals/live              - all signals, all sensors
  /ws/signals/sensor/{sensor_id} - signals for one sensor
  /ws/anomalies/live            - anomaly alerts only

Each endpoint:
  1. Accepts the WebSocket connection
  2. Sends a welcome/confirmation message
  3. Starts a background Redis subscriber task
  4. Keeps the connection alive until client disconnects
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.redis_subscriber import (
    CHANNEL_ANOMALIES_LIVE,
    CHANNEL_SIGNALS_LIVE,
    subscribe_and_forward,
)
from app.core.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws/signals/live")
async def websocket_signals_live(websocket: WebSocket):
    """
    Stream all incoming signals in real time.
    Connect with: ws://localhost:8000/ws/signals/live
    """
    await ws_manager.connect_live(websocket)

    # Confirm connection to client
    await websocket.send_json({
        "type": "connected",
        "channel": "signals:live",
        "message": "Streaming all live signals",
    })

    # Start Redis subscriber as background task
    subscriber_task = asyncio.create_task(
        subscribe_and_forward(
            channel=CHANNEL_SIGNALS_LIVE,
            websocket=websocket,
            manager=ws_manager,
            broadcast_fn=ws_manager.broadcast_live,
        )
    )

    try:
        # Keep connection open — wait for client to disconnect
        while True:
            # We still need to receive to detect disconnection
            data = await websocket.receive_text()
            # Optionally handle ping/pong or client commands here
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Live signal WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        subscriber_task.cancel()
        ws_manager.disconnect_live(websocket)


@router.websocket("/ws/signals/sensor/{sensor_id}")
async def websocket_signals_sensor(websocket: WebSocket, sensor_id: str):
    """
    Stream signals for a specific sensor.
    Connect with: ws://localhost:8000/ws/signals/sensor/<uuid>
    """
    await ws_manager.connect_sensor(websocket, sensor_id)

    await websocket.send_json({
        "type": "connected",
        "channel": f"signals:sensor:{sensor_id}",
        "message": f"Streaming signals for sensor {sensor_id}",
    })

    # Per-sensor Redis channel
    sensor_channel = f"signals:sensor:{sensor_id}"

    subscriber_task = asyncio.create_task(
        subscribe_and_forward(
            channel=sensor_channel,
            websocket=websocket,
            manager=ws_manager,
            broadcast_fn=lambda msg: ws_manager.broadcast_sensor(sensor_id, msg),
        )
    )

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Sensor {sensor_id} WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        subscriber_task.cancel()
        ws_manager.disconnect_sensor(websocket, sensor_id)


@router.websocket("/ws/anomalies/live")
async def websocket_anomalies_live(websocket: WebSocket):
    """
    Stream anomaly alerts in real time.
    Connect with: ws://localhost:8000/ws/anomalies/live
    """
    await ws_manager.connect_anomalies(websocket)

    await websocket.send_json({
        "type": "connected",
        "channel": "anomalies:live",
        "message": "Streaming live anomaly alerts",
    })

    subscriber_task = asyncio.create_task(
        subscribe_and_forward(
            channel=CHANNEL_ANOMALIES_LIVE,
            websocket=websocket,
            manager=ws_manager,
            broadcast_fn=ws_manager.broadcast_anomaly,
        )
    )

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Anomaly WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        subscriber_task.cancel()
        ws_manager.disconnect_anomalies(websocket)