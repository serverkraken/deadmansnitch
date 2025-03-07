import os
import logging


def configure_global_logging():
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Bestehende Handler entfernen
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Neue Konfiguration anwenden
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Explizit den watchdog_service Logger konfigurieren
    logger = logging.getLogger("watchdog_service")
    logger.setLevel(log_level)

    print(f"Global logging configured with level: {log_level_name}")
    return log_level
