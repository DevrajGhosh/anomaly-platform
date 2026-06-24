# app/services/alerting.py
"""
Alerting service.

Responsibilities:
  1. Load active alert rules from DB
  2. Check each anomaly against each rule
  3. Fire matched alerts via the configured channel
  4. Record every fired alert in alert_events table
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.alert import AlertEvent, AlertRule

logger = logging.getLogger(__name__)


class AlertingService:

    async def process_anomaly(self, anomaly_data: dict) -> list[str]:
        """
        Check anomaly against all active rules and fire matching alerts.
        Returns list of rule names that fired.
        """
        fired = []

        async with AsyncSessionLocal() as db:
            # Load all active rules
            result = await db.execute(
                select(AlertRule).where(AlertRule.is_active == True)  # noqa
            )
            rules = result.scalars().all()

            for rule in rules:
                if rule.matches(anomaly_data):
                    logger.info(
                        f"Alert rule '{rule.name}' matched anomaly "
                        f"score={anomaly_data.get('anomaly_score'):.3f} "
                        f"severity={anomaly_data.get('severity')}"
                    )
                    delivered, error = await self._deliver(rule, anomaly_data)

                    # Record alert event
                    event = AlertEvent(
                        id=uuid.uuid4(),
                        rule_id=rule.id,
                        anomaly_id=str(anomaly_data.get("id", "")),
                        sensor_id=str(anomaly_data.get("sensor_id", "")),
                        model_name=str(anomaly_data.get("model_name", "")),
                        severity=str(anomaly_data.get("severity", "")),
                        anomaly_score=float(anomaly_data.get("anomaly_score", 0)),
                        payload=anomaly_data,
                        delivered=delivered,
                        delivery_error=error,
                        fired_at=datetime.now(timezone.utc),
                    )
                    db.add(event)
                    fired.append(rule.name)

            if fired:
                await db.commit()

        return fired

    async def _deliver(
        self, rule: AlertRule, anomaly_data: dict
    ) -> tuple[bool, str | None]:
        """
        Deliver an alert via the rule's configured channel.
        Returns (success, error_message).
        """
        if rule.channel == "log":
            return await self._deliver_log(rule, anomaly_data)
        elif rule.channel == "webhook":
            return await self._deliver_webhook(rule, anomaly_data)
        else:
            return False, f"Unknown channel: {rule.channel}"

    async def _deliver_log(
        self, rule: AlertRule, anomaly_data: dict
    ) -> tuple[bool, None]:
        """Log-based alert delivery."""
        logger.warning(
            f"🚨 ALERT FIRED: rule='{rule.name}' | "
            f"sensor={anomaly_data.get('sensor_id')} | "
            f"model={anomaly_data.get('model_name')} | "
            f"severity={anomaly_data.get('severity')} | "
            f"score={anomaly_data.get('anomaly_score', 0):.4f} | "
            f"value={anomaly_data.get('value')}"
        )
        return True, None

    async def _deliver_webhook(
        self, rule: AlertRule, anomaly_data: dict
    ) -> tuple[bool, str | None]:
        """Webhook delivery — POST anomaly data to configured URL."""
        if not rule.webhook_url:
            return False, "No webhook URL configured"

        payload = {
            "alert_rule": rule.name,
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "anomaly": anomaly_data,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    rule.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code < 300:
                    logger.info(
                        f"Webhook delivered to {rule.webhook_url}: "
                        f"{response.status_code}"
                    )
                    return True, None
                else:
                    error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(f"Webhook failed: {error}")
                    return False, error

        except Exception as e:
            error = str(e)
            logger.error(f"Webhook exception: {error}")
            return False, error


alerting_service = AlertingService()