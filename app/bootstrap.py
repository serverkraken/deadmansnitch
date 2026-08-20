import logging
import os
from typing import Tuple

from app.config import Config
from app.notifications.notifier import Notifier
from app.notifications.providers.google_chat import GoogleChatProvider
from app.persistence.file_repository import FileWatchdogRepository
from app.services.watchdog_service import WatchdogService

logger = logging.getLogger("watchdog_service")


def build_services() -> Tuple[Config, Notifier, WatchdogService]:
    """Single composition root shared by create_app() and the gunicorn
    when_ready hook"""
    config = Config.get_instance()

    repository = FileWatchdogRepository(
        config.data_dir,
        os.path.basename(config.persistence_file),
        log_interval=float(config.watchdog_timeout),
    )

    notifier = Notifier()
    if config.google_chat_webhook_url:
        notifier.add_provider(GoogleChatProvider(config.google_chat_webhook_url))

    watchdog_service = WatchdogService.get_instance(repository, notifier, config)
    try:
        watchdog_service.initialize()
    except Exception as e:
        # An unwritable data dir at boot must not crash the gunicorn master
        # or workers: alerting still works read-only, and the readiness
        # probe keeps traffic away until the filesystem is writable
        logger.error(f"Watchdog service initialization failed: {e} - continuing degraded")

    return config, notifier, watchdog_service
