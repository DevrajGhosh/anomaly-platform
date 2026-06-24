# app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.endpoints.sensors import router as sensors_router
from app.api.v1.endpoints.signals import router as signals_router
from app.api.v1.endpoints.signals import router_anomalies
from app.api.v1.endpoints.websockets import router as ws_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.alerts import router as alerts_router
from app.api.v1.endpoints.explainability import router as explain_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(sensors_router)
api_router.include_router(signals_router)
api_router.include_router(router_anomalies)
api_router.include_router(ws_router)
api_router.include_router(dashboard_router)
api_router.include_router(alerts_router)
api_router.include_router(explain_router)