# app/ml/anomaly_detector.py
"""
Anomaly detection engine — multiple model support.

Models:
  1. Isolation Forest  — fast, works well on high-dimensional data
  2. Local Outlier Factor — density-based, good for clusters
  3. One-Class SVM — kernel-based, handles non-linear boundaries
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

MIN_TRAINING_SAMPLES = 20


@dataclass
class DetectionResult:
    is_anomaly: bool
    anomaly_score: float
    raw_score: float
    model_name: str
    threshold: float
    severity: str
    explanation: dict


def compute_severity(score: float) -> str:
    if score >= 0.85:
        return "critical"
    elif score >= 0.70:
        return "high"
    elif score >= 0.55:
        return "medium"
    else:
        return "low"


def build_explanation(
    model_name: str,
    value: float,
    normalized_score: float,
    raw_score: float,
    window: list[float],
) -> dict:
    """Shared explanation builder for all models."""
    window_arr = np.array(window)
    return {
        "model": model_name,
        "value": value,
        "normalized_score": round(normalized_score, 4),
        "raw_score": round(float(raw_score), 4),
        "window_size": len(window),
        "window_mean": round(float(window_arr.mean()), 4),
        "window_std": round(float(window_arr.std()), 4),
        "window_min": round(float(window_arr.min()), 4),
        "window_max": round(float(window_arr.max()), 4),
        "z_score": round(
            float((value - window_arr.mean()) / (window_arr.std() + 1e-8)), 4
        ),
    }


# ── Base detector ──────────────────────────────────────────────────────────

class BaseDetector:
    """Shared sliding window logic for all detectors."""

    def __init__(self, window_size: int = 100, threshold: float = 0.5):
        self.window_size = window_size
        self.threshold = threshold
        self._windows: dict[str, list[float]] = {}
        self._scalers: dict[str, StandardScaler] = {}

    def _get_window(self, sensor_id: str) -> list[float]:
        if sensor_id not in self._windows:
            self._windows[sensor_id] = []
        return self._windows[sensor_id]

    def _update_window(self, sensor_id: str, value: float) -> None:
        window = self._get_window(sensor_id)
        window.append(value)
        if len(window) > self.window_size:
            self._windows[sensor_id] = window[-self.window_size:]

    def _get_scaled(self, sensor_id: str) -> Optional[tuple[np.ndarray, StandardScaler]]:
        window = self._get_window(sensor_id)
        if len(window) < MIN_TRAINING_SAMPLES:
            return None
        X = np.array(window).reshape(-1, 1)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        self._scalers[sensor_id] = scaler
        return X_scaled, scaler

    def _insufficient_data_result(self, sensor_id: str) -> DetectionResult:
        window = self._get_window(sensor_id)
        return DetectionResult(
            is_anomaly=False,
            anomaly_score=0.0,
            raw_score=0.0,
            model_name=self.model_name,
            threshold=self.threshold,
            severity="low",
            explanation={
                "reason": "insufficient_data",
                "samples_collected": len(window),
                "samples_needed": MIN_TRAINING_SAMPLES,
            },
        )


# ── Isolation Forest ───────────────────────────────────────────────────────

class IsolationForestDetector(BaseDetector):
    model_name = "isolation_forest"

    def __init__(self, window_size=100, contamination=0.1, threshold=0.5):
        super().__init__(window_size, threshold)
        self.contamination = contamination
        self._models: dict[str, IsolationForest] = {}

    def score(self, sensor_id: str, value: float) -> DetectionResult:
        self._update_window(sensor_id, value)
        scaled = self._get_scaled(sensor_id)
        if scaled is None:
            return self._insufficient_data_result(sensor_id)

        X_scaled, scaler = scaled
        model = IsolationForest(
            contamination=self.contamination,
            random_state=42,
            n_estimators=100,
        )
        model.fit(X_scaled)
        self._models[sensor_id] = model

        X_new = scaler.transform(np.array([[value]]))
        raw_score = model.decision_function(X_new)[0]
        normalized_score = float(np.clip(0.5 - raw_score, 0, 1))
        is_anomaly = normalized_score >= self.threshold
        severity = compute_severity(normalized_score) if is_anomaly else "low"

        return DetectionResult(
            is_anomaly=is_anomaly,
            anomaly_score=normalized_score,
            raw_score=float(raw_score),
            model_name=self.model_name,
            threshold=self.threshold,
            severity=severity,
            explanation=build_explanation(
                self.model_name, value, normalized_score,
                float(raw_score), self._get_window(sensor_id)
            ),
        )


# ── Local Outlier Factor ───────────────────────────────────────────────────

class LOFDetector(BaseDetector):
    """
    Local Outlier Factor.

    Measures local density deviation of a point compared to its neighbors.
    An anomaly has a substantially lower density than its neighbors.

    Best for: clustered data with varying density regions.
    """
    model_name = "local_outlier_factor"

    def __init__(self, window_size=100, contamination=0.1, threshold=0.5, n_neighbors=20):
        super().__init__(window_size, threshold)
        self.contamination = contamination
        self.n_neighbors = n_neighbors

    def score(self, sensor_id: str, value: float) -> DetectionResult:
        self._update_window(sensor_id, value)
        window = self._get_window(sensor_id)

        if len(window) < MIN_TRAINING_SAMPLES:
            return self._insufficient_data_result(sensor_id)

        X = np.array(window).reshape(-1, 1)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # LOF needs n_neighbors < n_samples
        n_neighbors = min(self.n_neighbors, len(window) - 1)

        # novelty=True allows scoring new points
        model = LocalOutlierFactor(
            n_neighbors=n_neighbors,
            contamination=self.contamination,
            novelty=True,
        )
        model.fit(X_scaled)

        X_new = scaler.transform(np.array([[value]]))
        raw_score = model.decision_function(X_new)[0]

        # LOF: negative scores = outliers, positive = inliers
        # Normalize to 0-1 (higher = more anomalous)
        normalized_score = float(np.clip(0.5 - raw_score, 0, 1))
        is_anomaly = normalized_score >= self.threshold
        severity = compute_severity(normalized_score) if is_anomaly else "low"

        return DetectionResult(
            is_anomaly=is_anomaly,
            anomaly_score=normalized_score,
            raw_score=float(raw_score),
            model_name=self.model_name,
            threshold=self.threshold,
            severity=severity,
            explanation=build_explanation(
                self.model_name, value, normalized_score,
                float(raw_score), window
            ),
        )


# ── One-Class SVM ──────────────────────────────────────────────────────────

class OneClassSVMDetector(BaseDetector):
    """
    One-Class SVM.

    Learns a decision boundary around normal data.
    Points outside the boundary are anomalies.

    Best for: non-linear decision boundaries, small datasets.
    Note: Slower than IF and LOF — use smaller windows.
    """
    model_name = "one_class_svm"

    def __init__(self, window_size=100, threshold=0.5, nu=0.1, kernel="rbf"):
        super().__init__(window_size, threshold)
        self.nu = nu          # Upper bound on fraction of outliers
        self.kernel = kernel

    def score(self, sensor_id: str, value: float) -> DetectionResult:
        self._update_window(sensor_id, value)
        window = self._get_window(sensor_id)

        if len(window) < MIN_TRAINING_SAMPLES:
            return self._insufficient_data_result(sensor_id)

        X = np.array(window).reshape(-1, 1)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = OneClassSVM(nu=self.nu, kernel=self.kernel, gamma="scale")
        model.fit(X_scaled)

        X_new = scaler.transform(np.array([[value]]))
        raw_score = model.decision_function(X_new)[0]

        # SVM: negative = anomaly, normalize to 0-1
        normalized_score = float(np.clip(0.5 - raw_score, 0, 1))
        is_anomaly = normalized_score >= self.threshold
        severity = compute_severity(normalized_score) if is_anomaly else "low"

        return DetectionResult(
            is_anomaly=is_anomaly,
            anomaly_score=normalized_score,
            raw_score=float(raw_score),
            model_name=self.model_name,
            threshold=self.threshold,
            severity=severity,
            explanation=build_explanation(
                self.model_name, value, normalized_score,
                float(raw_score), window
            ),
        )


# ── Ensemble ───────────────────────────────────────────────────────────────

class AnomalyDetectionEnsemble:
    """
    Runs all three models and returns results from each.
    The Celery task decides which results to persist.
    """

    def __init__(self):
        self.detectors = {
            "isolation_forest": IsolationForestDetector(
                window_size=100, contamination=0.1, threshold=0.5
            ),
            "local_outlier_factor": LOFDetector(
                window_size=100, contamination=0.1, threshold=0.5
            ),
            "one_class_svm": OneClassSVMDetector(
                window_size=100, threshold=0.5, nu=0.1
            ),
        }

    def score_all(
        self,
        sensor_id: str,
        value: float,
        models: Optional[list[str]] = None,
    ) -> dict[str, DetectionResult]:
        """
        Score a value with all (or selected) models.

        Args:
            sensor_id: sensor UUID string
            value: signal value
            models: list of model names to use, or None for all

        Returns:
            dict mapping model_name → DetectionResult
        """
        active = models or list(self.detectors.keys())
        results = {}
        for name in active:
            if name in self.detectors:
                try:
                    results[name] = self.detectors[name].score(sensor_id, value)
                except Exception as e:
                    logger.error(f"Model {name} failed for sensor {sensor_id}: {e}")
        return results


# Singleton
ensemble = AnomalyDetectionEnsemble()

# Keep individual detectors accessible for backward compatibility
isolation_forest_detector = ensemble.detectors["isolation_forest"]