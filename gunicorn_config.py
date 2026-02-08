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

from app.config import Config  # noqa: E402
from app.notifications.notifier import Notifier  # noqa: E402
from app.notifications.providers.google_chat import GoogleChatProvider  # noqa: E402
from app.persistence.file_repository import FileWatchdogRepository  # noqa: E402
from app.services.watchdog_monitor import WatchdogMonitor  # noqa: E402
from app.services.watchdog_service import WatchdogService  # noqa: E402

# Gunicorn configuration for production environments
bind = "0.0.0.0:5001"
workers = 1  # Only one worker since we need just one watchdog thread
threads = 2
worker_class = "gthread"
timeout = 120




class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if "GET /probe/" in record.getMessage():
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

        # Initialize configuration
        config = Config.get_instance()

        # Initialize persistence
        repository = FileWatchdogRepository(config.data_dir, os.path.basename(config.persistence_file))

        # Initialize notification system
        notifier = Notifier()

        # Add notification providers if configured
        if config.google_chat_webhook_url:
            google_chat = GoogleChatProvider(config.google_chat_webhook_url)
            notifier.add_provider(google_chat)

        # Initialize watchdog service
        watchdog_service = WatchdogService.get_instance(repository, notifier, config)
        watchdog_service.initialize()

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
