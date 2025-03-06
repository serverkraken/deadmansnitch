#!/bin/bash
set -e

echo "Starting Alertmanager Watchdog Service"

# Umgebungsvariablen anzeigen (ohne sensible Daten)
echo "Configuration:"
echo "- WATCHDOG_TIMEOUT: ${WATCHDOG_TIMEOUT:-3600} seconds"
echo "- EXPECTED_ALERTNAME: ${EXPECTED_ALERTNAME:-'Watchdog'}"
echo "- DATA_DIR: ${DATA_DIR:-'/data'}"
echo "- LOG_LEVEL: ${LOG_LEVEL:-'info'}"
echo "- GOOGLE_CHAT_WEBHOOK_URL: $(if [ -n "$GOOGLE_CHAT_WEBHOOK_URL" ]; then echo "configured"; else echo "not configured"; fi)"

# Starte Gunicorn mit der angegebenen Konfiguration
exec gunicorn --config gunicorn_config.py "app.watchdog_service:webapp"
