# 🔴 Real-Time Signal Anomaly Detection Platform

A production-grade platform for ingesting live sensor data streams, detecting anomalies in real time using an ensemble of machine learning models, and visualizing results on a live dashboard — all containerized with Docker.

---

## 🎯 Project Overview

This platform continuously monitors sensor data streams and automatically detects unusual patterns using three unsupervised ML models running simultaneously. Every detected anomaly is explained in plain English, stored permanently, and broadcast to a live dashboard via WebSockets in under one second.

### Key Capabilities

- **Real-Time Ingestion** — Receive sensor readings via REST API at sub-35ms response time
- **Ensemble ML Detection** — Isolation Forest + Local Outlier Factor + One-Class SVM run on every signal
- **Live Dashboard** — WebSocket-powered chart updates without page refresh
- **Explainability** — Every anomaly explained with z-score, window statistics, and ranked factors
- **Alerting** — Configurable rules with log and webhook delivery channels
- **Docker Deployment** — One command starts the entire platform

---

## 🏗️ Architecture

```
Sensor / Data Source
        │
        ▼
   FastAPI (REST API + WebSockets)
        │
        ├──► PostgreSQL (permanent storage)
        │
        ├──► Redis (pub/sub + sliding window cache)
        │
        └──► Celery Worker
                    │
                    ▼
           ML Ensemble Detection
           ┌─────────────────────┐
           │  Isolation Forest   │
           │  Local Outlier Factor│
           │  One-Class SVM      │
           └─────────────────────┘
                    │
                    ▼
           Anomaly saved + Alert fired
                    │
                    ▼
           WebSocket → Live Dashboard
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Web Framework** | FastAPI 0.111 + Uvicorn |
| **Database** | PostgreSQL 16 + SQLAlchemy 2.0 (async) |
| **Migrations** | Alembic |
| **Cache / Broker** | Redis 7 |
| **Task Queue** | Celery 5.4 |
| **ML Models** | Scikit-learn 1.4 (IF, LOF, SVM) |
| **Validation** | Pydantic 2.7 |
| **Containerization** | Docker + Docker Compose |
| **Frontend** | HTML + Tailwind CSS + SVG charts |

---

## 📁 Project Structure

```
anomaly-platform/
├── app/
│   ├── main.py                    # FastAPI entry point
│   ├── core/
│   │   ├── config.py              # Pydantic settings
│   │   ├── redis.py               # Async Redis client
│   │   ├── websocket_manager.py   # WebSocket connection registry
│   │   └── redis_subscriber.py    # Redis → WebSocket bridge
│   ├── db/
│   │   └── session.py             # SQLAlchemy engine + session
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── sensor.py
│   │   ├── signal.py
│   │   ├── anomaly.py
│   │   └── alert.py
│   ├── schemas/                   # Pydantic request/response schemas
│   ├── crud/                      # Database CRUD operations
│   ├── api/v1/endpoints/          # FastAPI route handlers
│   │   ├── sensors.py
│   │   ├── signals.py
│   │   ├── dashboard.py
│   │   ├── alerts.py
│   │   ├── explainability.py
│   │   └── websockets.py
│   ├── services/                  # Business logic layer
│   │   ├── ingestion.py
│   │   ├── alerting.py
│   │   └── explainability.py
│   ├── ml/
│   │   └── anomaly_detector.py    # IF + LOF + SVM ensemble
│   └── workers/
│       ├── celery_app.py          # Celery configuration
│       └── tasks.py               # Async ML detection tasks
├── alembic/                       # Database migrations
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── simulate_signals.py            # Test signal simulator
├── validate_accuracy.py           # Synthetic accuracy validation
├── validate_accuracy_nab.py       # NAB AWS CPU validation
├── validate_machine_temp.py       # NAB Machine Temperature validation
├── dashboard.html                 # Real-time frontend dashboard
└── .env.example                   # Environment variable template
```

---

## 🚀 Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.11+

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/anomaly-platform.git
cd anomaly-platform
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your settings if needed (defaults work for local development)
```

### 3. Start the platform

```bash
docker compose up -d
```

This starts 4 containers:
- `anomaly-postgres` — PostgreSQL database
- `anomaly-redis` — Redis cache and message broker
- `anomaly-api` — FastAPI application (port 8000)
- `anomaly-celery` — ML detection workers

### 4. Run database migrations

```bash
docker compose exec api alembic upgrade head
```

### 5. Verify everything is running

```bash
docker compose ps
curl http://localhost:8000/health
```

### 6. Open the dashboard

Open `dashboard.html` in your browser (double-click the file).

---

## 📡 API Reference

### Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health check |
| `POST` | `/api/v1/sensors/` | Register a new sensor |
| `GET` | `/api/v1/sensors/` | List all sensors |
| `POST` | `/api/v1/signals/` | Ingest a single signal |
| `POST` | `/api/v1/signals/bulk` | Ingest up to 1000 signals |
| `GET` | `/api/v1/anomalies/` | List anomalies with filters |
| `GET` | `/api/v1/dashboard/stats` | Platform statistics |
| `GET` | `/api/v1/explain/anomaly/{id}` | Explain an anomaly |
| `POST` | `/api/v1/alerts/rules` | Create alert rule |
| `GET` | `/api/v1/alerts/events` | Alert event history |

### WebSocket Channels

| Channel | Description |
|---|---|
| `ws://localhost:8000/api/v1/ws/signals/live` | All signals, all sensors |
| `ws://localhost:8000/api/v1/ws/signals/sensor/{id}` | Signals for one sensor |
| `ws://localhost:8000/api/v1/ws/anomalies/live` | Live anomaly alerts |

Full API documentation available at `http://localhost:8000/docs`

---

## 🧪 Testing

### Send test signals

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Create a sensor first
python -c "
import httpx
r = httpx.post('http://localhost:8000/api/v1/sensors/', json={
    'name': 'temperature-probe-01',
    'unit': 'celsius',
    'min_expected': -50,
    'max_expected': 200,
    'is_active': True
})
print('Sensor ID:', r.json()['id'])
"

# Update SENSOR_ID in simulate_signals.py then run:
python simulate_signals.py
```

### Validate ML accuracy

```bash
# Synthetic controlled test
python validate_accuracy.py

# Real-world NAB machine temperature dataset
python validate_machine_temp.py

# Real-world NAB AWS CPU dataset
python validate_accuracy_nab.py
```

---

## 📊 ML Models

### Isolation Forest
- Random partitioning — isolates anomalies using decision trees
- Best for: high-volume streaming, fast inference
- Window: 100 readings, Contamination: 10%

### Local Outlier Factor (LOF)
- Density-based — compares local density to neighbors
- Best for: clustered data, contextual anomalies
- Window: 100 readings, Neighbors: 20

### One-Class SVM
- Kernel-based boundary — learns normal data boundary
- Best for: non-linear patterns, complex distributions
- Window: 100 readings, Nu: 0.1, Kernel: RBF

### Ensemble Strategy

All three models score every signal simultaneously:

| Agreement | Confidence | Action |
|---|---|---|
| All 3 agree | Very High | Immediate investigation |
| 2 of 3 agree | High | Investigate promptly |
| 1 of 3 flags | Moderate | Monitor closely |

---

## 📈 Accuracy Validation Results

Validated across three datasets:

| Dataset | Type | Best F1-Score | Model |
|---|---|---|---|
| Synthetic controlled | Known injected anomalies | **91.67%** | Ensemble (Any) |
| NAB Machine Temperature | Real industrial sensor failure | **42.17%** | Ensemble (Any) |
| NAB AWS CPU | Real server metrics | **35.25%** | Ensemble (Any) |

Real-world performance is consistent with published NAB benchmark results for unsupervised anomaly detection models.

---

## 🔔 Alerting

Create configurable alert rules via the dashboard or API:

```bash
curl -X POST http://localhost:8000/api/v1/alerts/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "critical-alert",
    "severities": ["critical", "high"],
    "channel": "log",
    "is_active": true
  }'
```

Supported channels:
- **log** — prints to Celery worker terminal
- **webhook** — HTTP POST to any URL (Slack, PagerDuty, Teams)

---

## 🔍 Explainability

Every anomaly includes a plain-English explanation:

```json
{
  "plain_english": "The value 150.00 is extremely far above the recent average of 72.00 (z-score: +6.87). Based on the last 100 readings, the Isolation Forest model assigned an anomaly score of 0.8525 (critical severity).",
  "factors": [
    {"display_name": "Statistical Deviation", "impact": 1.0},
    {"display_name": "Distance from Mean", "impact": 0.70},
    {"display_name": "Historical Range Breach", "impact": 0.45},
    {"display_name": "Detection Confidence", "impact": 1.0}
  ]
}
```

---

## 🐳 Docker Commands

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# View logs
docker compose logs api -f
docker compose logs celery -f

# Check status
docker compose ps

# Run migrations
docker compose exec api alembic upgrade head
```

---

## 🌐 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL URL |
| `DATABASE_SYNC_URL` | `postgresql+psycopg2://...` | Sync URL for Alembic |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `SECRET_KEY` | (required) | Application secret key |
| `DEBUG` | `False` | Enable SQL query logging |
| `ENVIRONMENT` | `production` | Environment label |

---

## 📚 References

1. Liu et al. (2008) — Isolation Forest algorithm
2. Breunig et al. (2000) — Local Outlier Factor
3. Scholkopf et al. (2001) — One-Class SVM
4. Lavin & Ahmad (2015) — Numenta Anomaly Benchmark
5. FastAPI Documentation — https://fastapi.tiangolo.com/
6. SQLAlchemy 2.0 Documentation — https://docs.sqlalchemy.org/

---

## 👨‍💻 Author

Developed as part of the 6-Week Summer Internship Program  
Department of CSE (AI & ML)  
Institute of Engineering & Management, Kolkata  
University of Engineering and Management, Kolkata  
2025 – 2026

---

## 📄 License

This project is developed for academic purposes as part of an internship program.