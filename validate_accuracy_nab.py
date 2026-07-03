# validate_accuracy_nab.py
"""
Accuracy Validation using the REAL Numenta Anomaly Benchmark (NAB) dataset.

Unlike validate_accuracy.py (which uses synthetic data we generated ourselves),
this script uses:
  1. Real AWS EC2 CPU utilization data (actual production server metrics)
  2. Official NAB ground-truth labels published by Numenta researchers
     (not authored by us -- this is published, peer-reviewed benchmark data)

This is much stronger evidence for an evaluator because the ground truth
is independent and external to our own project.

Dataset: realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv
Source:  https://github.com/numenta/NAB

Run with: python validate_accuracy_nab.py
"""

import httpx
import time
import csv
import io
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api/v1"
SENSOR_NAME = "nab-validation-aws-cpu-v3"

# Real NAB dataset files (raw GitHub content)
NAB_DATA_URL = "https://raw.githubusercontent.com/numenta/NAB/master/data/realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv"
NAB_LABELS_URL = "https://raw.githubusercontent.com/numenta/NAB/master/labels/combined_windows.json"
NAB_DATASET_KEY = "realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv"


# ── Step 1: Sensor setup ─────────────────────────────────────────────────────
def get_or_create_sensor() -> str:
    r = httpx.get(f"{BASE_URL}/sensors/?limit=100")
    for s in r.json()["items"]:
        if s["name"] == SENSOR_NAME:
            print(f"✅ Using existing NAB validation sensor: {s['id']}")
            return s["id"]

    r = httpx.post(f"{BASE_URL}/sensors/", json={
        "name": SENSOR_NAME,
        "description": "Real AWS EC2 CPU utilization (NAB benchmark) for accuracy validation",
        "unit": "percent",
        "min_expected": 0,
        "max_expected": 100,
        "is_active": True,
    })
    sensor_id = r.json()["id"]
    print(f"✅ Created NAB validation sensor: {sensor_id}")
    return sensor_id


# ── Step 2: Download real data + official ground truth labels ───────────────
def download_nab_data_and_labels():
    print("📥 Downloading real NAB dataset (AWS EC2 CPU utilization)...")
    r = httpx.get(NAB_DATA_URL, timeout=30)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    print(f"✅ Loaded {len(rows)} real data points (actual AWS production metrics)")

    print("📥 Downloading official NAB ground-truth anomaly labels...")
    r2 = httpx.get(NAB_LABELS_URL, timeout=30)
    r2.raise_for_status()
    all_labels = r2.json()
    windows = all_labels.get(NAB_DATASET_KEY, [])
    print(f"✅ Loaded {len(windows)} official labeled anomaly window(s):")
    for w in windows:
        print(f"     {w[0]}  →  {w[1]}")

    return rows, windows


def is_in_anomaly_window(timestamp_str: str, windows: list) -> bool:
    """Check if a timestamp falls inside any officially labeled anomaly window."""
    ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    for start_str, end_str in windows:
        start = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S.%f") if "." in start_str else datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S.%f") if "." in end_str else datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
        if start <= ts <= end:
            return True
    return False


# ── Step 3: Build dataset with REAL values + OFFICIAL ground truth ──────────
def build_dataset(rows: list, windows: list, start_index: int = 0, max_points: int = None):
    """
    Builds the test dataset starting at start_index in the raw NAB file.

    The first 100 points of the SLICE are used as warmup (to build the
    sliding window) and excluded from scoring; everything after that is
    a scored test point. start_index lets us position the slice so it
    actually contains the officially labeled anomaly window, since NAB
    anomaly windows are often located deep into a 4000+ point file.
    """
    end_index = start_index + max_points if max_points else len(rows)
    sliced_rows = rows[start_index:end_index]

    dataset = []
    for i, row in enumerate(sliced_rows):
        value = float(row["value"])
        timestamp = row["timestamp"]
        is_true_anomaly = is_in_anomaly_window(timestamp, windows)
        phase = "warmup" if i < 100 else "test"  # first 100 of the SLICE build the sliding window
        dataset.append({
            "value": round(value, 4),
            "is_true_anomaly": is_true_anomaly,
            "phase": phase,
            "original_timestamp": timestamp,
        })

    n_anom = sum(1 for d in dataset if d["is_true_anomaly"] and d["phase"] == "test")
    n_normal = sum(1 for d in dataset if not d["is_true_anomaly"] and d["phase"] == "test")
    print(f"\n📊 Dataset prepared: {len(dataset)} total points (rows {start_index}–{end_index} of {len(rows)} in source file)")
    print(f"   Warmup (window buildup, excluded from scoring): 100")
    print(f"   Test points: {n_anom + n_normal}  ({n_anom} true anomalies, {n_normal} true normal)")
    return dataset


# ── Step 4: Send through the live API ────────────────────────────────────────
def send_dataset(sensor_id: str, dataset: list) -> list:
    print(f"\n📡 Sending {len(dataset)} real signals through the live API...\n")

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    client = httpx.Client(timeout=timeout)
    failed_count = 0

    try:
        for i, point in enumerate(dataset):
            point["signal_id"] = None
            success = False

            for attempt in range(3):
                try:
                    r = client.post(f"{BASE_URL}/signals/", json={
                        "sensor_id": sensor_id,
                        "value": point["value"],
                        "source": "nab_validation",
                    })
                    if r.status_code == 201:
                        point["signal_id"] = r.json()["id"]
                        success = True
                    break
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError):
                    if attempt < 2:
                        time.sleep(1.0)
                        continue
                    else:
                        failed_count += 1

            status_icon = "🔴" if point["is_true_anomaly"] else ("·" if success else "❌")
            phase_tag = "[warmup]" if point["phase"] == "warmup" else "[test]  "
            print(f"  {status_icon} {phase_tag} [{i+1:4d}/{len(dataset)}] value={point['value']:7.2f}", end="\r")

            time.sleep(0.12)
    finally:
        client.close()

    print("\n")
    if failed_count:
        print(f"⚠️  {failed_count} signal(s) failed after retries and were skipped.")
    print("✅ Signal sending complete. Waiting 20 seconds for ML processing to finish...")
    time.sleep(20)
    return dataset


# ── Step 5: Fetch predictions via bulk anomaly fetch + local join ───────────
def fetch_predictions(dataset: list, sensor_id: str) -> list:
    print("\n🔍 Fetching all anomalies recorded for this sensor...\n")

    model_names = ["isolation_forest", "local_outlier_factor", "one_class_svm"]
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    client = httpx.Client(timeout=timeout)

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


# ── Step 6: Metrics ───────────────────────────────────────────────────────────
def compute_metrics(dataset: list, prediction_key: str) -> dict:
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
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0

    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "accuracy": round(accuracy, 4), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1_score": round(f1, 4),
        "specificity": round(specificity, 4), "false_positive_rate": round(fpr, 4),
        "total_test_points": total,
    }


def print_report(all_metrics: dict, windows: list):
    print("\n" + "=" * 82)
    print("  NAB ACCURACY VALIDATION — REAL AWS DATA + OFFICIAL GROUND-TRUTH LABELS")
    print("=" * 82)
    print(f"  Dataset: {NAB_DATASET_KEY}")
    print(f"  Official labeled anomaly windows: {len(windows)}")
    print("=" * 82)

    header = f"{'Model':<28}{'Acc':>8}{'Prec':>8}{'Recall':>8}{'F1':>8}{'TP':>5}{'FP':>5}{'TN':>5}{'FN':>5}"
    print(header)
    print("-" * 82)

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

    print("=" * 82 + "\n")


def save_to_csv(all_metrics: dict, dataset: list):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    summary_path = f"nab_accuracy_summary_{timestamp}.csv"
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

    detail_path = f"nab_accuracy_detail_{timestamp}.csv"
    with open(detail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["signal_id", "value", "original_timestamp", "is_true_anomaly", "phase",
                          "pred_isolation_forest", "pred_local_outlier_factor",
                          "pred_one_class_svm", "pred_ensemble_any",
                          "pred_ensemble_majority", "pred_ensemble_unanimous"])
        for p in dataset:
            if p["signal_id"] is None:
                continue
            writer.writerow([
                p["signal_id"], p["value"], p["original_timestamp"], p["is_true_anomaly"], p["phase"],
                p.get("pred_isolation_forest", False),
                p.get("pred_local_outlier_factor", False),
                p.get("pred_one_class_svm", False),
                p.get("pred_ensemble_any", False),
                p.get("pred_ensemble_majority", False),
                p.get("pred_ensemble_unanimous", False),
            ])
    print(f"✅ Detailed per-signal data saved to: {detail_path}\n")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("🧪 NAB BENCHMARK ACCURACY VALIDATION (Real Data + Official Labels)")
    print("=" * 82)

    sensor_id = get_or_create_sensor()

    rows, windows = download_nab_data_and_labels()
    if not windows:
        print("⚠️  No labeled anomaly windows found for this dataset key. Aborting.")
        return

    # Limit to a window that actually CONTAINS the labeled anomaly period.
    # The official NAB window for this file falls around rows 1526-1868,
    # so we take points 1300-2000 (100 warmup + ~600 test points spanning
    # well before, during, and after the labeled anomaly window).
    dataset = build_dataset(rows, windows, start_index=1300, max_points=600)

    dataset = send_dataset(sensor_id, dataset)
    dataset = fetch_predictions(dataset, sensor_id)

    all_metrics = {}
    for key in ["pred_isolation_forest", "pred_local_outlier_factor", "pred_one_class_svm",
                "pred_ensemble_any", "pred_ensemble_majority", "pred_ensemble_unanimous"]:
        all_metrics[key] = compute_metrics(dataset, key)

    print_report(all_metrics, windows)
    save_to_csv(all_metrics, dataset)

    print("🎉 NAB validation complete! These results are backed by an independent,")
    print("   published benchmark dataset — strong evidence for your report.")


if __name__ == "__main__":
    main()