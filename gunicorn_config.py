#!/usr/bin/env python3
import os
from app.config import Config
from app.persistence.file_repository import FileWatchdogRepository
from app.notifications.notifier import Notifier
from app.notifications.providers.google_chat import GoogleChatProvider
from app.services.watchdog_service import WatchdogService
from app.services.watchdog_monitor import WatchdogMonitor

# Gunicorn configuration for production environments
bind = "0.0.0.0:5001"
workers = 1  # Only one worker since we need just one watchdog thread
threads = 2
worker_class = "gthread"
timeout = 120

# Format access logs
accesslog = "-"  # Stdout
errorlog = "-"  # Stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# Ensure the LOG_LEVEL is used for the watchdog service too
os.environ["LOG_LEVEL"] = loglevel

# Set environment variable to indicate we're running under Gunicorn
os.environ["RUNNING_IN_GUNICORN"] = "true"

# Variable to track whether the monitor thread has started
monitor_thread_started = False


def when_ready(server):
    """Called when Gunicorn server is ready to handle requests."""
    global monitor_thread_started

    if not monitor_thread_started:
        server.log.info(
            "Initializing and starting watchdog monitor thread in when_ready hook"
        )

        # Initialize configuration
        config = Config.get_instance()

        # Initialize persistence
        repository = FileWatchdogRepository(
            config.data_dir, os.path.basename(config.persistence_file)
        )

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


def on_exit(server):
    """Called when Gunicorn is shutting down."""
    server.log.info("Shutting down watchdog service")
