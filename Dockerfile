# Single source of truth for the Python version: the copied venv hardcodes
# lib/python3.X paths, so builder and runtime must never drift apart
ARG PYTHON_IMAGE=python:3.14-slim

# Build stage: Poetry and its dependency tree stay here and never
# reach the runtime image
FROM ${PYTHON_IMAGE} AS builder

WORKDIR /app

# Pinned to the version that wrote poetry.lock
RUN pip install --no-cache-dir poetry==2.4.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install runtime dependencies into an in-project venv (/app/.venv) so it
# can be copied into the runtime stage as a single unit. no-pip keeps pip
# (and its vendored msgpack/setuptools copies) out of the venv.
# --compile pre-builds bytecode: the runtime venv is root-owned and
# PYTHONDONTWRITEBYTECODE is set, so it can never be compiled later
RUN poetry config virtualenvs.in-project true \
  && poetry config virtualenvs.options.no-pip true \
  && poetry install --without dev --no-interaction --no-ansi --compile

# Runtime stage
FROM ${PYTHON_IMAGE}

# Create non-root user for security
RUN groupadd -r deadmansnitch && useradd -r -g deadmansnitch deadmansnitch

# Set work directory
WORKDIR /app

# apt-get upgrade pulls Debian security patches the base image doesn't ship yet
# pip is removed: the runtime never installs packages, and pip's vendored
# copies (pip/_vendor/vendor.txt) trip image scanners. The ensurepip
# directory must go too, or `python -m ensurepip` restores pip from the
# bundled wheel at runtime
RUN apt-get update && apt-get upgrade -y \
  && rm -rf /var/lib/apt/lists/* \
  && python -m pip uninstall -y pip \
  && d="$(python -c 'import ensurepip, os; print(os.path.dirname(ensurepip.__file__))')" \
  && test -n "$d" && rm -rf "$d"

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

# Fail the build (not the deploy) if the shipped code doesn't run here:
# importing the app package pulls the full dependency closure, and running
# as deadmansnitch after the ENV block also catches unreadable venv files
# without writing bytecode into the layer
RUN python -c "import app, gunicorn, setproctitle"

# Health check via stdlib instead of curl: opening with an empty
# ProxyHandler ignores injected HTTP_PROXY env (as curl did for http://),
# and the request raises on HTTP >= 400 and on connection failure, so the
# CMD exits non-zero without extra CVE-prone packages in the image
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://localhost:5001/health', timeout=25)"

# Add metadata labels
LABEL maintainer="ServerKraken Team" \
  version="2.0" \
  description="Deadman's Snitch - A service that monitors for the presence of Prometheus watchdog alerts" \
  created="2025-03-06"

# Run gunicorn with our config
CMD ["gunicorn", "-c", "gunicorn_config.py", "app:create_app()"]
