FROM python:3.13-slim

# Create non-root user for security
RUN groupadd -r deadmansnitch && useradd -r -g deadmansnitch deadmansnitch

# Set work directory
WORKDIR /app

# Install Poetry and dependencies
# We use curl for healthcheck and pip to install poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  && pip install poetry \
  && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies
# Disable virtualenvs validation since we are in a container
RUN poetry config virtualenvs.create false \
  && poetry install --without dev --no-interaction --no-ansi

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
