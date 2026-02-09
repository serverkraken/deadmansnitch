import logging
import os
from unittest.mock import patch

from app.logging_setup import configure_global_logging


class TestLoggingSetup:
    def teardown_method(self) -> None:
        """Reset logging configuration after each test"""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        root.setLevel(logging.WARNING)

    def test_default_log_level(self) -> None:
        """Test default log level is INFO when env var is not set"""
        with patch.dict(os.environ, {}, clear=True):
            level = configure_global_logging()
            assert level == logging.INFO
            assert logging.getLogger().level == logging.INFO
            assert logging.getLogger("watchdog_service").level == logging.INFO

    def test_custom_log_level(self) -> None:
        """Test setting log level via environment variable"""
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            level = configure_global_logging()
            assert level == logging.DEBUG
            assert logging.getLogger().level == logging.DEBUG
            assert logging.getLogger("watchdog_service").level == logging.DEBUG

    def test_invalid_log_level(self) -> None:
        """Test fallback to INFO for invalid log level"""
        with patch.dict(os.environ, {"LOG_LEVEL": "INVALID_LEVEL"}):
            level = configure_global_logging()
            assert level == logging.INFO

    def test_handler_configuration(self) -> None:
        """Test that a single StreamHandler is configured with correct formatter"""
        configure_global_logging()

        root = logging.getLogger()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)

        # Verify formatter
        assert handler.formatter is not None
        # Format string check - depending on implementation details in logging_setup.py
        # "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        log_record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )
        formatted = handler.formatter.format(log_record)
        assert "[INFO] [test_logger] test message" in formatted

    def test_handler_cleanup(self) -> None:
        """Test that existing handlers are removed before adding new one"""
        root = logging.getLogger()
        # Add some dummy handlers
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())

        configure_global_logging()

        assert len(root.handlers) == 1
