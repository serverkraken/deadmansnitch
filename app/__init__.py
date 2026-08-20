import logging
import os

from flask import Flask

from app.bootstrap import build_services
from app.logging_setup import configure_global_logging
from app.services.watchdog_monitor import WatchdogMonitor
from app.web.routes import init_routes


def create_app() -> Flask:
    """Application factory"""
    configure_global_logging()
    logger = logging.getLogger("watchdog_service")

    config, notifier, watchdog_service = build_services()

    # Create Flask application
    app = Flask(__name__)
    # Reject oversized bodies before they can occupy worker threads or RAM
    app.config["MAX_CONTENT_LENGTH"] = config.max_content_length

    # Register routes
    app.register_blueprint(init_routes(watchdog_service))

    # Start monitor thread if not running in Gunicorn
    if not os.environ.get("RUNNING_IN_GUNICORN", ""):
        monitor = WatchdogMonitor(watchdog_service, notifier, config)
        monitor.start()
        logger.info("Started watchdog monitor thread in standalone mode")

    logger.info(
        f"Starting Watchdog Service (timeout: {config.watchdog_timeout}s, "
        f"expected alertname: {config.expected_alertname})"
    )

    return app
