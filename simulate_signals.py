# simulate_signals.py
"""
Sends test signals to the API to trigger anomaly detection.
Run with: python simulate_signals.py
"""

import httpx
import random
import time

BASE_URL = "http://localhost:8000"
SENSOR_ID = "21cb21d2-3db6-4822-9353-aa967d3e73bd" # Your real sensor ID


def send_signal(value: float, label: str = ""):
    response = httpx.post(
        f"{BASE_URL}/api/v1/signals/",
        json={
            "sensor_id": SENSOR_ID,
            "value": value,
            "source": "simulator",
        },
    )
    status = "✅" if response.status_code == 201 else "❌"
    print(f"{status} {label} value={value:.2f} → {response.status_code}")
    return response


print("🔄 Sending 50 normal signals (building training window)...")
for i in range(50):
    value = random.gauss(mu=72.0, sigma=3.0)   # Normal: mean=72, std=3
    send_signal(value, f"[normal {i+1}/50]")
    time.sleep(0.1)

print("\n🚨 Sending 10 anomalous signals...")
anomaly_values = [150.0, 160.0, 155.0, 145.0, 165.0, 5.0, 3.0, 8.0, 2.0, 170.0]
for i, value in enumerate(anomaly_values):
    send_signal(value, f"[ANOMALY {i+1}/10]")
    time.sleep(0.2)

print("\n✅ Simulation complete. Check anomalies at:")
print(f"   GET {BASE_URL}/api/v1/anomalies/")
print(f"   WebSocket: ws://localhost:8000/api/v1/ws/anomalies/live")