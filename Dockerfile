# Build stage: Poetry and its dependency tree stay here and never
# reach the runtime image
FROM python:3.14-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install runtime dependencies into an in-project venv (/app/.venv) so it
# can be copied into the runtime stage as a single unit. no-pip keeps pip
# (and its vendored msgpack/setuptools copies) out of the venv.
RUN poetry config virtualenvs.in-project true \
  && poetry config virtualenvs.options.no-pip true \
  && poetry install --without dev --no-interaction --no-ansi

# Runtime stage
FROM python:3.14-slim

# Create non-root user for security
RUN groupadd -r deadmansnitch && useradd -r -g deadmansnitch deadmansnitch

# Set work directory
WORKDIR /app

# apt-get upgrade pulls Debian security patches the base image doesn't ship yet
# We use curl for the healthcheck
# pip is removed: the runtime never installs packages, and pip's vendored
# copies (pip/_vendor/vendor.txt) trip image scanners
RUN apt-get update && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends \
  curl \
  && rm -rf /var/lib/apt/lists/* \
  && python -m pip uninstall -y pip

# Copy the prepared dependency venv from the build stage
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
  VIRTUAL_ENV="/app/.venv"

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
