# Deadmansnitch

Deadmansnitch is a monitoring tool designed to ensure that your scheduled tasks (like cron jobs) are running correctly. It alerts you when your tasks don't report back on time, allowing you to quickly identify and resolve issues.

## Features

- Monitor scheduled tasks and ensure they are running correctly.
- Receive alerts when tasks fail to report back.
- Simple integration with existing task schedulers.

## Getting Started

### Prerequisites

- Docker
- Docker Compose

### Installation

1. Clone the repository:

   ```sh
   git clone https://github.com/serverkraken/deadmansnitch.git
   cd deadmansnitch
   ```

2. Create a `.env` file to configure the application (if needed):

   ```sh
   touch .env
   ```

### Usage

#### Running with Docker Compose

1. Update the `docker-compose.yml` file as needed:

    ```yaml name=docker-compose.yml
    version: '3.8'

    services:
      deadmansnitch:
        image: ghcr.io/serverkraken/deadmansnitch:latest
        environment:
          - DATA_DIR=/app/data
          - GOOGLE_CHAT_WEBHOOK_URL=https://chat.googleapis.com/v1/spaces/...
        ports:
          - "5001:5001"
        volumes:
          - ./data:/app/data
        restart: unless-stopped
    ```

2. Start the application:

    ```sh
    docker-compose up -d
    ```

3. The app should now be running on `http://localhost:5001`.

### Prometheus Setup

To integrate Deadmansnitch with Prometheus, you need to add a receiver and a route to your Prometheus configuration.

1. Add a receiver to `prometheus.yml`:

    ```yaml
    receivers:
      - name: 'watchdog-receiver'
        webhook_configs:
          - url: 'http://serviceurl:5001/watchdog'
            send_resolved: true
    ```

2. Add a route to `prometheus.yml`:

    ```yaml
    route:
      routes:
        - match:
            alertname: Watchdog
          receiver: "watchdog-receiver"
    ```

### Endpoints


#### Health

```http
GET /health
```

#### Status Informations

```http
GET /status
```
