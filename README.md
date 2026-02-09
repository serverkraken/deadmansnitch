# Deadmansnitch

Deadmansnitch is a specialized monitoring tool designed to act as a "Dead Man's Switch" for your Prometheus monitoring pipeline. It ensures that your entire alerting chain—from Prometheus to Alertmanager—is functional.

## How it Works

1.  **Prometheus** is configured to fire a continuous "Watchdog" alert (always firing).
2.  **Alertmanager** receives this alert and repeatedly sends it to **Deadmansnitch** via a webhook.
3.  **Deadmansnitch** listens for these heartbeats. roughly every minute (or however you configure the `repeat_interval` in Alertmanager).
4.  If **Deadmansnitch** stops receiving these heartbeats for a configured period (default: 1 hour), it assumes the monitoring pipeline is broken and sends an out-of-band notification (e.g., to Google Chat).

## Configuration

The application is configured via environment variables.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `WATCHDOG_TIMEOUT` | `3600` | Time in seconds without a heartbeat before sending an alert (1 hour). |
| `EXPECTED_ALERTNAME` | `Watchdog` | The alert name to listen for in the webhook payload. |
| `ALERT_RESEND_INTERVAL` | `21600` | Time in seconds between repeat notifications if the issue persists (6 hours). |
| `GOOGLE_CHAT_WEBHOOK_URL`| `None` | **Required**. Webhook URL for Google Chat notifications. |
| `LOG_LEVEL` | `DEBUG` | Logging level. |
| `DATA_DIR` | `/app/data` | Directory for storing persistent state. |

## Prometheus Setup

To utilize Deadmansnitch, you need to configure both Prometheus and Alertmanager.

### 1. Prometheus Configuration (`prometheus.yml`)

Add a rule that always fires. This is often unrelated to any specific target but ensures Prometheus itself is running and evaluating rules.

```yaml
groups:
  - name: watchdog
    rules:
      - alert: Watchdog
        annotations:
          message: 'This is an alert meant to ensure that the entire alerting pipeline is functional.'
        expr: vector(1)
        labels:
          severity: none
```

### 2. Alertmanager Configuration (`alertmanager.yml`)

Configure a receiver that sends a webhook to Deadmansnitch.

```yaml
receivers:
  - name: 'deadmansnitch-receiver'
    webhook_configs:
      - url: 'http://<deadmansnitch-host>:5001/watchdog'
        send_resolved: true

route:
  routes:
    # Route the Watchdog alert to Deadmansnitch
    - match:
        alertname: Watchdog
      receiver: 'deadmansnitch-receiver'
      group_wait: 0s
      group_interval: 1m
      repeat_interval: 1m  # Send frequently to keep the switch alive
```

## API Endpoints

### Core Functionality

-   **`POST /watchdog`**
    -   **Description**: The webhook endpoint for Alertmanager. Receives the "Watchdog" alert payload.
    -   **Payload**: Standard Alertmanager JSON payload.

### Monitoring & Status

-   **`GET /health`**
    -   **Description**: Health check endpoint. Returns `200 OK` if the service is receiving heartbeats (or is in startup grace period), `503 Service Unavailable` otherwise.
    -   **Use Case**: External status/uptime monitoring.

-   **`GET /status`**
    -   **Description**: Detailed internal status, including counters, last received timestamp, and config.

-   **`GET /probe/liveness`**
    -   **Description**: Kubernetes liveness probe. Checks if the service is running and dependencies are initialized.

-   **`GET /probe/readiness`**
    -   **Description**: Kubernetes readiness probe. Checks if the service is ready to traffic.

-   **`GET /`**
    -   **Description**: Returns service version and a list of available endpoints.

## Development

### Prerequisites

-   Python >= 3.10
-   [Poetry](https://python-poetry.org/) (Dependency Management)

### Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/serverkraken/deadmansnitch.git
cd deadmansnitch
poetry install
```

### Running Tests

We use `pytest` for testing.

```bash
poetry run pytest
```

To run with coverage:

```bash
poetry run pytest --cov=app tests/
```

### Code Quality

We use `ruff` for linting and formatting, and `mypy` for static type checking.

**Format code:**
```bash
poetry run ruff format .
```

**Lint code:**
```bash
poetry run ruff check --fix .
```

**Type check:**
```bash
poetry run mypy .
```

## Deployment

### Docker

```bash
docker build -t deadmansnitch .
docker run -p 5001:5001 -e GOOGLE_CHAT_WEBHOOK_URL="your-url" deadmansnitch
```

### Docker Compose

See `docker-compose.yml` for a deployment example.
