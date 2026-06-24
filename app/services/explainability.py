# app/services/explainability.py
"""
Explainability service.

Turns raw ML explanation dicts into human-readable insights.
No additional ML libraries needed — we use the explanation data
already stored with each anomaly.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ExplainabilityService:

    def explain_anomaly(self, anomaly_data: dict) -> dict:
        """
        Generate a full human-readable explanation for an anomaly.

        Input: anomaly dict with explanation field from DB
        Output: structured explanation with plain English text
        """
        explanation = anomaly_data.get("explanation", {})
        model_name = anomaly_data.get("model_name", "unknown")
        score = anomaly_data.get("anomaly_score", 0)
        severity = anomaly_data.get("severity", "low")

        if not explanation or explanation.get("reason") == "insufficient_data":
            return {
                "summary": "Insufficient data to explain this anomaly.",
                "details": explanation,
                "factors": [],
                "plain_english": "Not enough historical data was available at detection time.",
            }

        value = explanation.get("value", 0)
        window_mean = explanation.get("window_mean", 0)
        window_std = explanation.get("window_std", 0)
        window_min = explanation.get("window_min", 0)
        window_max = explanation.get("window_max", 0)
        window_size = explanation.get("window_size", 0)
        z_score = explanation.get("z_score", 0)

        # ── Plain English Summary ──────────────────────────────────────────
        direction = "above" if value > window_mean else "below"
        z_abs = abs(z_score)

        if z_abs >= 4:
            deviation_desc = "extremely far"
        elif z_abs >= 3:
            deviation_desc = "very far"
        elif z_abs >= 2:
            deviation_desc = "significantly"
        else:
            deviation_desc = "somewhat"

        plain_english = (
            f"The value {value:.2f} is {deviation_desc} {direction} "
            f"the recent average of {window_mean:.2f} "
            f"(z-score: {z_score:+.2f}). "
            f"Based on the last {window_size} readings "
            f"(range: {window_min:.2f} – {window_max:.2f}, "
            f"std: {window_std:.2f}), "
            f"the {model_name.replace('_', ' ')} model assigned "
            f"an anomaly score of {score:.4f} "
            f"({severity} severity)."
        )

        # ── Ranked Contributing Factors ────────────────────────────────────
        factors = self._compute_factors(
            value, window_mean, window_std, window_min,
            window_max, z_score, window_size
        )

        # ── Model-specific insight ─────────────────────────────────────────
        model_insight = self._model_insight(model_name, z_score, score)

        # ── Contextual positioning ─────────────────────────────────────────
        window_range = window_max - window_min
        if window_range > 0:
            position_pct = ((value - window_min) / window_range) * 100
        else:
            position_pct = 50.0

        context = {
            "value_position_in_window": f"{position_pct:.1f}th percentile of recent range",
            "deviations_from_mean": round(z_abs, 2),
            "direction": direction,
            "exceeds_window_bounds": value < window_min or value > window_max,
        }

        return {
            "plain_english": plain_english,
            "summary": f"Severity: {severity.upper()} | Score: {score:.4f} | Z-score: {z_score:+.2f}",
            "model_insight": model_insight,
            "context": context,
            "factors": factors,
            "raw_explanation": explanation,
        }

    def _compute_factors(
        self,
        value: float,
        mean: float,
        std: float,
        min_val: float,
        max_val: float,
        z_score: float,
        window_size: int,
    ) -> list[dict]:
        """
        Rank the factors contributing to anomaly detection.
        Each factor has a name, value, impact (0-1), and description.
        """
        factors = []
        z_abs = abs(z_score)

        # Factor 1: Z-score deviation
        z_impact = min(z_abs / 5.0, 1.0)
        factors.append({
            "factor": "statistical_deviation",
            "display_name": "Statistical Deviation",
            "value": round(z_score, 4),
            "impact": round(z_impact, 4),
            "description": f"Value is {z_abs:.2f} standard deviations from mean",
        })

        # Factor 2: Distance from mean (absolute)
        dist_from_mean = abs(value - mean)
        dist_impact = min(dist_from_mean / (std * 5 + 1e-8), 1.0)
        factors.append({
            "factor": "distance_from_mean",
            "display_name": "Distance from Mean",
            "value": round(dist_from_mean, 4),
            "impact": round(dist_impact, 4),
            "description": f"Value differs from mean by {dist_from_mean:.2f} units",
        })

        # Factor 3: Window boundary breach
        exceeds_bounds = value < min_val or value > max_val
        breach_magnitude = 0.0
        if value > max_val:
            breach_magnitude = min((value - max_val) / (std + 1e-8), 1.0)
        elif value < min_val:
            breach_magnitude = min((min_val - value) / (std + 1e-8), 1.0)

        factors.append({
            "factor": "window_boundary_breach",
            "display_name": "Historical Range Breach",
            "value": exceeds_bounds,
            "impact": round(breach_magnitude, 4),
            "description": (
                f"Value exceeds historical range [{min_val:.2f}, {max_val:.2f}]"
                if exceeds_bounds
                else f"Value within historical range [{min_val:.2f}, {max_val:.2f}]"
            ),
        })

        # Factor 4: Window size confidence
        confidence = min(window_size / 100.0, 1.0)
        factors.append({
            "factor": "detection_confidence",
            "display_name": "Detection Confidence",
            "value": window_size,
            "impact": round(confidence, 4),
            "description": f"Based on {window_size} recent readings (higher = more confident)",
        })

        # Sort by impact descending
        factors.sort(key=lambda x: x["impact"], reverse=True)
        return factors

    def _model_insight(self, model_name: str, z_score: float, score: float) -> str:
        """Return a model-specific explanation of how it works."""
        insights = {
            "isolation_forest": (
                "Isolation Forest detected this anomaly by measuring how quickly "
                "this value was isolated in random decision trees. "
                "Values that require fewer splits to isolate are more anomalous."
            ),
            "local_outlier_factor": (
                "Local Outlier Factor detected this anomaly by comparing the "
                "local density of this value to its neighbors. "
                "This value has significantly lower density than surrounding points."
            ),
            "one_class_svm": (
                "One-Class SVM detected this anomaly because it falls outside "
                "the learned boundary of normal behavior. "
                "The kernel function mapped this value to a region of low probability."
            ),
        }
        return insights.get(
            model_name,
            f"Model '{model_name}' flagged this value with score {score:.4f}."
        )

    def compare_models(self, anomalies_for_signal: list[dict]) -> dict:
        """
        Compare how different models scored the same signal.
        Used to show model agreement/disagreement on a signal.
        """
        if not anomalies_for_signal:
            return {"agreement": "no_anomalies", "models": {}}

        models = {}
        for a in anomalies_for_signal:
            models[a["model_name"]] = {
                "is_anomaly": True,
                "score": a["anomaly_score"],
                "severity": a["severity"],
            }

        all_models = ["isolation_forest", "local_outlier_factor", "one_class_svm"]
        detected_by = list(models.keys())
        missed_by = [m for m in all_models if m not in models]

        if len(detected_by) == 3:
            agreement = "unanimous"
            agreement_text = "All 3 models agree this is an anomaly — high confidence."
        elif len(detected_by) == 2:
            agreement = "majority"
            agreement_text = f"2 of 3 models flagged this — moderate confidence. {missed_by[0].replace('_',' ')} did not flag it."
        else:
            agreement = "minority"
            agreement_text = f"Only 1 model flagged this — low confidence. Treat with caution."

        scores = [v["score"] for v in models.values()]
        avg_score = sum(scores) / len(scores) if scores else 0

        return {
            "agreement": agreement,
            "agreement_text": agreement_text,
            "detected_by": detected_by,
            "missed_by": missed_by,
            "model_count": len(detected_by),
            "average_score": round(avg_score, 4),
            "models": models,
        }


explainability_service = ExplainabilityService()