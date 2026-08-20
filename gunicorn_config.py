import logging
import os
from typing import Any

from app.logging_setup import configure_global_logging

# Globales Log-Level konfigurieren
log_level_name = os.getenv("LOG_LEVEL", "info")
os.environ["LOG_LEVEL"] = log_level_name  # Umgebungsvariable setzen BEVOR weitere Module geladen werden
configure_global_logging()  # Explizit die globale Logger-Konfiguration aufrufen

# Gunicorn-spezifische Konfiguration
loglevel = log_level_name.lower()  # Gunicorn verwendet Kleinbuchstaben

from app.bootstrap import build_services  # noqa: E402
from app.services.watchdog_monitor import WatchdogMonitor  # noqa: E402

# Gunicorn configuration for production environments
bind = "0.0.0.0:5001"
workers = 1  # Only one worker since we need just one watchdog thread
threads = 2
worker_class = "gthread"
timeout = 120


class HealthCheckFilter(logging.Filter):
    # /probe/* is polled by Kubernetes, /health by the Docker healthcheck -
    # together thousands of access-log lines per day
    QUIET_PATHS = ("GET /probe/", "GET /health")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(path in message for path in self.QUIET_PATHS):
            return os.getenv("LOG_LEVEL", "info").upper() == "DEBUG"
        return True


# Gunicorn logging configuration
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "unified": {
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "filters": {
        "healthcheck": {
            "()": HealthCheckFilter,
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "unified",
            "stream": "ext://sys.stdout",
            "filters": ["healthcheck"],
        },
    },
    "loggers": {
        "gunicorn.error": {
            "level": log_level_name.upper(),
            "handlers": ["console"],
            "propagate": False,
        },
        "gunicorn.access": {
            "level": log_level_name.upper(),
            "handlers": ["console"],
            "propagate": False,
        },
    },
    "root": {
        "level": log_level_name.upper(),
        "handlers": ["console"],
    },
}

# Ensure the LOG_LEVEL is used for the watchdog service too
os.environ["LOG_LEVEL"] = log_level_name.upper()

# Set environment variable to indicate we're running under Gunicorn
os.environ["RUNNING_IN_GUNICORN"] = "true"

# Variable to track whether the monitor thread has started
monitor_thread_started = False


def when_ready(server: Any) -> None:
    """Called when Gunicorn server is ready to handle requests."""
    global monitor_thread_started

    if not monitor_thread_started:
        server.log.info("Initializing and starting watchdog monitor thread in when_ready hook")

        config, notifier, watchdog_service = build_services()

        # Start monitor thread
        monitor = WatchdogMonitor(watchdog_service, notifier, config)
        monitor.start()
        monitor_thread_started = True

        server.log.info(
            f"Watchdog monitor thread started (timeout: {config.watchdog_timeout}s, "
            f"expected alertname: {config.expected_alertname}, "
            f"alert resend interval: {config.alert_resend_interval}s)"
        )
    else:
        server.log.info("Watchdog monitor thread already running")


def on_exit(server: Any) -> None:
    """Called when Gunicorn is shutting down."""
    server.log.info("Shutting down watchdog service")
