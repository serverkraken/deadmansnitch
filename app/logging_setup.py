import logging
import os


def configure_global_logging() -> int:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level: int = getattr(logging, log_level_name, logging.INFO)

    # Consistent format for app and gunicorn
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add new handler with standardized formatter
    handler = logging.StreamHandler()
    formatter = logging.Formatter(log_format, datefmt=date_format)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Explicitly set level for watchdog_service
    logger = logging.getLogger("watchdog_service")
    logger.setLevel(log_level)

    logger.debug(f"Logging initialized (level: {log_level_name})")
    return log_level
