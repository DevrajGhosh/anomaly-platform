# real_data_nab.py
"""
Loads real NAB (Numenta Anomaly Benchmark) data into your platform.
Downloads automatically — no API key needed.
Real AWS server CPU usage data with known anomalies.
"""

import httpx
import time
import csv
import io

PLATFORM_URL = "http://localhost:8000/api/v1"

# Real NAB dataset — AWS server CPU usage (public GitHub)
NAB_URL = "https://raw.githubusercontent.com/numenta/NAB/master/data/realAWSCloudwatch/ec2_cpu_utilization_825cc2.csv"

SENSOR_NAME = "temperature-probe-01"


def setup_sensor() -> str:
    # Check if exists
    r = httpx.get(f"{PLATFORM_URL}/sensors/")
    for s in r.json()["items"]:
        if s["name"] == SENSOR_NAME:
            print(f"✅ Using existing sensor: {s['id']}")
            return s["id"]

    # Create
    r = httpx.post(f"{PLATFORM_URL}/sensors/", json={
        "name": SENSOR_NAME,
        "description": "Real AWS EC2 CPU utilization from NAB dataset",
        "unit": "percent",
        "min_expected": 0,
        "max_expected": 100,
        "is_active": True,
    })
    sensor_id = r.json()["id"]
    print(f"✅ Created sensor: {sensor_id}")
    return sensor_id


def load_nab_data() -> list:
    print("📥 Downloading real NAB dataset...")
    r = httpx.get(NAB_URL, timeout=30)
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    print(f"✅ Loaded {len(rows)} real data points")
    return rows


def run():
    print("🚀 Loading real AWS CPU data into anomaly platform...")
    sensor_id = setup_sensor()
    rows = load_nab_data()

    print(f"\n📡 Ingesting {len(rows)} real data points...")
    print("   (Speed: 10 points/second to simulate streaming)\n")

    batch = []
    for i, row in enumerate(rows):
        value = float(row["value"])
        timestamp = row["timestamp"]

        batch.append({
            "sensor_id": sensor_id,
            "value": value,
            "source": "nab_dataset",
            "metadata": {"original_timestamp": timestamp, "index": i},
        })

        # Send in batches of 20
        if len(batch) >= 20:
            r = httpx.post(
                f"{PLATFORM_URL}/signals/bulk",
                json={"signals": batch},
                timeout=30,
            )
            if r.status_code == 201:
                print(f"  ✅ Batch {i//20 + 1}: ingested {len(batch)} points | latest value: {value:.2f}%")
            else:
                print(f"  ❌ Batch failed: {r.text}")
            batch = []
            time.sleep(0.1)  # 10 batches/second = 200 points/second

    print(f"\n✅ Done! {len(rows)} real data points ingested.")
    print(f"   Check anomalies: GET {PLATFORM_URL}/anomalies/")
    print(f"   Dashboard: open dashboard.html")


if __name__ == "__main__":
    run()