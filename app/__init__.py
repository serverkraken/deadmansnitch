import os
from flask import Flask
from app.config import Config
from app.persistence.file_repository import FileWatchdogRepository
from app.notifications.notifier import Notifier
from app.notifications.providers.google_chat import GoogleChatProvider
from app.services.watchdog_service import WatchdogService
from app.services.watchdog_monitor import WatchdogMonitor
from app.web.routes import init_routes


def create_app():
    """Application factory"""
    # Initialize configuration
    config = Config.get_instance()
    logger = config.configure_logging()

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
    # Nur initialisieren, wenn nicht unter Gunicorn (wird sonst in gunicorn_config.py initialisiert)
    if os.environ.get("RUNNING_IN_GUNICORN", "") == "":
        watchdog_service.initialize()

    # Create Flask application
    app = Flask(__name__)

    # Register routes
    app.register_blueprint(init_routes(watchdog_service))

    # Start monitor thread if not running in Gunicorn
    if not os.environ.get("RUNNING_IN_GUNICORN", ""):
        monitor = WatchdogMonitor(watchdog_service, notifier, config)
        monitor.start()
        logger.info("Started watchdog monitor thread in standalone mode")

    logger.info(
        f"Starting Watchdog Service (timeout: {config.watchdog_timeout}s, expected alertname: {config.expected_alertname})"
    )

    return app

