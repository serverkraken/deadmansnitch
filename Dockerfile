FROM python:3.13-slim

# Labels hinzufügen
LABEL maintainer="merin80" \
  description="Alertmanager Watchdog Service" \
  version="1.0.0"

# Arbeitsverzeichnis setzen
WORKDIR /app

# Pakete installieren
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  curl \
  ca-certificates && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode kopieren
COPY app/ ./app/
COPY gunicorn_config.py .
COPY docker/entrypoint.sh .

# Datenverzeichnis erstellen
RUN mkdir -p /data && chmod 777 /data

# Das Entrypoint-Skript ausführbar machen
RUN chmod +x entrypoint.sh

# Port freigeben
EXPOSE 5001

# Umgebungsvariablen setzen
ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  DATA_DIR=/data \
  LOG_LEVEL=info \
  WATCHDOG_TIMEOUT=3600 \
  EXPECTED_ALERTNAME=Watchdog

# Healthcheck konfigurieren
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1

# Entrypoint setzen
ENTRYPOINT ["./entrypoint.sh"]
