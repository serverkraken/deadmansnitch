FROM python:3.14-slim

# Create non-root user for security
RUN groupadd -r deadmansnitch && useradd -r -g deadmansnitch deadmansnitch

# Set work directory
WORKDIR /app

# Create requirements.txt file
COPY requirements.txt .

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl gcc python3-dev \
  && pip install --no-cache-dir -r requirements.txt \
  && apt-get purge -y --auto-remove gcc python3-dev \
  && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY app/ /app/app/
COPY gunicorn_config.py /app/

# Create data directory and set permissions
RUN mkdir -p /app/data && \
  chown -R deadmansnitch:deadmansnitch /app/data

# Set volume for persistent data
VOLUME ["/app/data"]

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  LOG_LEVEL=info \
  DATA_DIR=/app/data \
  WATCHDOG_TIMEOUT=3600 \
  EXPECTED_ALERTNAME=Watchdog \
  ALERT_RESEND_INTERVAL=21600

# Expose port
EXPOSE 5001

# Switch to non-root user
USER deadmansnitch

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1

# Add metadata labels
LABEL maintainer="ServerKraken Team" \
  version="2.0" \
  description="Deadman's Snitch - A service that monitors for the presence of Prometheus watchdog alerts" \
  created="2025-03-06"

# Run gunicorn with our config
CMD ["gunicorn", "-c", "gunicorn_config.py", "app:create_app()"]
