# validate_accuracy.py
"""
Accuracy Validation Script for Anomaly Detection Platform.

This script:
  1. Generates a controlled dataset where we KNOW which points are anomalies
     (ground truth) and which are normal
  2. Sends all signals through the live platform via the API
  3. Waits for ML detection to complete
  4. Compares model predictions against ground truth
  5. Computes standard classification metrics:
       - Accuracy
       - Precision
       - Recall
       - F1-Score
       - Confusion Matrix (TP, FP, TN, FN)
  6. Does this PER MODEL (Isolation Forest, LOF, One-Class SVM)
     and for the ENSEMBLE (majority vote / any-model-flags)
  7. Prints a full report and saves results to CSV for your report/Excel chart

Run with: python validate_accuracy.py
"""

import httpx
import time
import random
import csv
from datetime import datetime

BASE_URL = "http://localhost:8000/api/v1"

# ── Step 1: Create a dedicated validation sensor ────────────────────────────
SENSOR_NAME = "temperature-probe-01"

def get_or_create_sensor() -> str:
    r = httpx.get(f"{BASE_URL}/sensors/?limit=100")
    for s in r.json()["items"]:
        if s["name"] == SENSOR_NAME:
            print(f"✅ Using existing validation sensor: {s['id']}")
            return s["id"]

    r = httpx.post(f"{BASE_URL}/sensors/", json={
        "name": SENSOR_NAME,
        "description": "Dedicated sensor for accuracy validation experiment",
        "unit": "units",
        "min_expected": 0,
        "max_expected": 200,
        "is_active": True,
    })
    sensor_id = r.json()["id"]
    print(f"✅ Created validation sensor: {sensor_id}")
    return sensor_id


# ── Step 2: Generate controlled dataset with KNOWN ground truth ─────────────
def generate_ground_truth_dataset(n_normal: int = 100, n_anomalies: int = 25):
    """
    Generates a realistic dataset where we control exactly which points
    are anomalies. Returns list of (value, is_true_anomaly) tuples.

    Normal data: Gaussian distribution, mean=70, std=4
    Anomalies: injected at random positions with values far from normal range
    """
    random.seed(42)  # Reproducible results

    dataset = []

    # First 30 points: pure normal (training window buildup, excluded from scoring)
    for _ in range(30):
        value = random.gauss(70, 4)
        dataset.append({"value": round(value, 2), "is_true_anomaly": False, "phase": "warmup"})

    # Remaining points: mix of normal and anomalous, randomly interleaved
    remaining_normal = n_normal - 30
    test_points = []

    for _ in range(remaining_normal):
        value = random.gauss(70, 4)
        test_points.append({"value": round(value, 2), "is_true_anomaly": False})

    # Anomaly types - mix of spikes, dips, and moderate deviations
    anomaly_generators = [
        lambda: random.uniform(140, 180),    # Extreme spike
        lambda: random.uniform(-10, 10),     # Extreme dip
        lambda: random.uniform(100, 120),    # Moderate spike (harder to detect)
        lambda: random.uniform(30, 45),      # Moderate dip (harder to detect)
    ]

    for i in range(n_anomalies):
        gen = anomaly_generators[i % len(anomaly_generators)]
        value = gen()
        test_points.append({"value": round(value, 2), "is_true_anomaly": True})

    # Shuffle test points so anomalies are interspersed naturally
    random.shuffle(test_points)

    for p in test_points:
        p["phase"] = "test"
        dataset.append(p)

    return dataset


# ── Step 3: Send dataset through the live API ────────────────────────────────
def send_dataset(sensor_id: str, dataset: list) -> list:
    """
    Sends each point through the real ingestion API.
    Returns the dataset enriched with signal_id for later lookup.

    Uses a dedicated client with a generous timeout and automatic
    retry-on-timeout, since each POST triggers synchronous DB + Redis
    work and can occasionally be slow under load.
    """
    print(f"\n📡 Sending {len(dataset)} signals through the live API...")
    print(f"   ({sum(1 for d in dataset if d['is_true_anomaly'])} true anomalies injected)")
    print(f"   ({sum(1 for d in dataset if d['phase']=='warmup')} warmup points excluded from scoring)\n")

    # Generous timeout (connect/read/write/pool) + connection reuse
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    client = httpx.Client(timeout=timeout)

    failed_count = 0

    try:
        for i, point in enumerate(dataset):
            point["signal_id"] = None
            success = False

            # Retry up to 3 times on timeout/network errors
            for attempt in range(3):
                try:
                    r = client.post(f"{BASE_URL}/signals/", json={
                        "sensor_id": sensor_id,
                        "value": point["value"],
                        "source": "validation_test",
                    })
                    if r.status_code == 201:
                        point["signal_id"] = r.json()["id"]
                        point["timestamp"] = r.json()["timestamp"]
                        success = True
                    break  # got a response (success or real error) -- stop retrying
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError):
                    if attempt < 2:
                        time.sleep(1.0)  # brief pause before retry
                        continue
                    else:
                        failed_count += 1

            status_icon = "🔴" if point["is_true_anomaly"] else ("·" if success else "❌")
            phase_tag = "[warmup]" if point["phase"] == "warmup" else "[test]  "
            print(f"  {status_icon} {phase_tag} [{i+1:3d}/{len(dataset)}] value={point['value']:7.2f}", end="\r")

            time.sleep(0.3)  # gentler pacing so Celery/DB aren't overwhelmed
    finally:
        client.close()

    print("\n")
    if failed_count:
        print(f"⚠️  {failed_count} signal(s) failed after 3 retries and were skipped.")
    print("✅ Signal sending complete. Waiting 8 seconds for ML processing to finish...")
    time.sleep(8)
    return dataset


# ── Step 4: Fetch what the models actually detected ─────────────────────────
def fetch_predictions(dataset: list, sensor_id: str) -> list:
    """
    Fetches ALL anomalies recorded for this sensor in one go, then matches
    them locally against each signal_id in our dataset.

    Why this approach instead of querying per-signal?
      The GET /signals/{id} endpoint does NOT include an 'anomalies' field
      in its response schema (even though the relationship exists in the
      DB model), and GET /anomalies/ has no signal_id filter. The reliable
      way to get ground-truth predictions is to pull every anomaly for the
      sensor and join locally on signal_id, which is also far more
      efficient than making 125 separate HTTP calls.
    """
    print("\n🔍 Fetching all anomalies recorded for this sensor...\n")

    model_names = ["isolation_forest", "local_outlier_factor", "one_class_svm"]
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    client = httpx.Client(timeout=timeout)

    # signal_id -> set of model_names that flagged it
    flagged_map: dict[str, set] = {}

    try:
        skip = 0
        page_size = 200
        total_fetched = 0

        while True:
            r = client.get(
                f"{BASE_URL}/anomalies/",
                params={"sensor_id": sensor_id, "limit": page_size, "skip": skip},
            )
            if r.status_code != 200:
                print(f"  ⚠️  Failed to fetch anomalies page (status {r.status_code})")
                break

            page = r.json()
            items = page.get("items", [])
            if not items:
                break

            for a in items:
                sig_id = a.get("signal_id")
                model = a.get("model_name")
                if sig_id and model:
                    flagged_map.setdefault(sig_id, set()).add(model)

            total_fetched += len(items)
            skip += page_size

            if total_fetched >= page.get("total", 0):
                break

        print(f"  Fetched {total_fetched} anomaly records for this sensor.")
        print(f"  {len(flagged_map)} unique signals were flagged by at least one model.\n")

    finally:
        client.close()

    # ── Join locally: enrich each dataset point with model predictions ─────
    for point in dataset:
        if point["signal_id"] is None:
            continue

        flagged_by = flagged_map.get(point["signal_id"], set())

        for model in model_names:
            point[f"pred_{model}"] = model in flagged_by

        point["pred_ensemble_any"] = len(flagged_by) > 0
        point["pred_ensemble_majority"] = len(flagged_by) >= 2
        point["pred_ensemble_unanimous"] = len(flagged_by) == 3

    print("✅ Predictions matched to dataset.")
    return dataset


# ── Step 5: Compute classification metrics ───────────────────────────────────
def compute_metrics(dataset: list, prediction_key: str) -> dict:
    """
    Standard binary classification metrics.

    TP = True Positive  (true anomaly, correctly flagged)
    FP = False Positive (normal point, incorrectly flagged)
    TN = True Negative  (normal point, correctly not flagged)
    FN = False Negative (true anomaly, missed)
    """
    test_points = [p for p in dataset if p["phase"] == "test" and p["signal_id"] is not None]

    tp = sum(1 for p in test_points if p["is_true_anomaly"] and p.get(prediction_key, False))
    fp = sum(1 for p in test_points if not p["is_true_anomaly"] and p.get(prediction_key, False))
    tn = sum(1 for p in test_points if not p["is_true_anomaly"] and not p.get(prediction_key, False))
    fn = sum(1 for p in test_points if p["is_true_anomaly"] and not p.get(prediction_key, False))

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
    false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0

    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "specificity": round(specificity, 4),
        "false_positive_rate": round(false_positive_rate, 4),
        "total_test_points": total,
    }


# ── Step 6: Print formatted report ───────────────────────────────────────────
def print_report(all_metrics: dict):
    print("\n" + "=" * 78)
    print("  ANOMALY DETECTION ACCURACY VALIDATION REPORT")
    print("=" * 78)

    header = f"{'Model':<28}{'Acc':>8}{'Prec':>8}{'Recall':>8}{'F1':>8}{'TP':>5}{'FP':>5}{'TN':>5}{'FN':>5}"
    print(header)
    print("-" * 78)

    display_names = {
        "pred_isolation_forest": "Isolation Forest",
        "pred_local_outlier_factor": "Local Outlier Factor",
        "pred_one_class_svm": "One-Class SVM",
        "pred_ensemble_any": "Ensemble (Any Model)",
        "pred_ensemble_majority": "Ensemble (Majority 2/3)",
        "pred_ensemble_unanimous": "Ensemble (Unanimous 3/3)",
    }

    for key, name in display_names.items():
        m = all_metrics[key]
        print(f"{name:<28}{m['accuracy']:>8.2%}{m['precision']:>8.2%}{m['recall']:>8.2%}"
              f"{m['f1_score']:>8.2%}{m['TP']:>5}{m['FP']:>5}{m['TN']:>5}{m['FN']:>5}")

    print("=" * 78)
    print("\nDefinitions:")
    print("  TP = True Positive  (real anomaly, correctly detected)")
    print("  FP = False Positive (normal value, wrongly flagged)")
    print("  TN = True Negative  (normal value, correctly not flagged)")
    print("  FN = False Negative (real anomaly, missed by model)")
    print()
    print("  Accuracy  = (TP+TN) / Total            -- overall correctness")
    print("  Precision = TP / (TP+FP)                -- of flagged points, how many were real")
    print("  Recall    = TP / (TP+FN)                -- of real anomalies, how many were caught")
    print("  F1-Score  = harmonic mean of Precision & Recall")
    print("=" * 78 + "\n")


# ── Step 7: Save to CSV for Excel charting ───────────────────────────────────
def save_to_csv(all_metrics: dict, dataset: list):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Summary metrics CSV (for your bar chart in the report)
    summary_path = f"accuracy_summary_{timestamp}.csv"
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Model", "Accuracy", "Precision", "Recall", "F1_Score",
                          "Specificity", "False_Positive_Rate", "TP", "FP", "TN", "FN"])
        display_names = {
            "pred_isolation_forest": "Isolation Forest",
            "pred_local_outlier_factor": "Local Outlier Factor",
            "pred_one_class_svm": "One-Class SVM",
            "pred_ensemble_any": "Ensemble (Any Model)",
            "pred_ensemble_majority": "Ensemble (Majority 2/3)",
            "pred_ensemble_unanimous": "Ensemble (Unanimous 3/3)",
        }
        for key, name in display_names.items():
            m = all_metrics[key]
            writer.writerow([name, m["accuracy"], m["precision"], m["recall"],
                              m["f1_score"], m["specificity"], m["false_positive_rate"],
                              m["TP"], m["FP"], m["TN"], m["FN"]])

    print(f"✅ Summary metrics saved to: {summary_path}")
    print("   Open this in Excel to build your accuracy bar chart for the report.\n")

    # Detailed per-signal CSV (raw data, optional appendix evidence)
    detail_path = f"accuracy_detail_{timestamp}.csv"
    with open(detail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["signal_id", "value", "is_true_anomaly", "phase",
                          "pred_isolation_forest", "pred_local_outlier_factor",
                          "pred_one_class_svm", "pred_ensemble_any",
                          "pred_ensemble_majority", "pred_ensemble_unanimous"])
        for p in dataset:
            if p["signal_id"] is None:
                continue
            writer.writerow([
                p["signal_id"], p["value"], p["is_true_anomaly"], p["phase"],
                p.get("pred_isolation_forest", False),
                p.get("pred_local_outlier_factor", False),
                p.get("pred_one_class_svm", False),
                p.get("pred_ensemble_any", False),
                p.get("pred_ensemble_majority", False),
                p.get("pred_ensemble_unanimous", False),
            ])

    print(f"✅ Detailed per-signal data saved to: {detail_path}")
    print("   This is your raw evidence — every signal value with ground truth vs prediction.\n")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("🧪 ANOMALY DETECTION ACCURACY VALIDATION")
    print("=" * 78)

    sensor_id = get_or_create_sensor()

    dataset = generate_ground_truth_dataset(n_normal=100, n_anomalies=25)

    dataset = send_dataset(sensor_id, dataset)

    dataset = fetch_predictions(dataset, sensor_id)

    all_metrics = {}
    for key in ["pred_isolation_forest", "pred_local_outlier_factor", "pred_one_class_svm",
                "pred_ensemble_any", "pred_ensemble_majority", "pred_ensemble_unanimous"]:
        all_metrics[key] = compute_metrics(dataset, key)

    print_report(all_metrics)
    save_to_csv(all_metrics, dataset)

    print("🎉 Validation complete! Use these numbers in your report's Results section.")


if __name__ == "__main__":
    main()