import logging
import os
from unittest.mock import MagicMock, patch

# Import the module to test
# We need to be careful because importing gunicorn_config executes code at module level
# We'll use a patch to prevent side effects during import if possible, or just test the class if we can extract it.
# Since the class is defined at top level but used in a dict, we can import it.
import gunicorn_config
from gunicorn_config import HealthCheckFilter, on_exit, when_ready


class TestHealthCheckFilter:
    def test_filter_health_check_info(self) -> None:
        """Test health checks are filtered out at INFO level"""
        filter_ = HealthCheckFilter()
        record = MagicMock(spec=logging.LogRecord)
        record.getMessage.return_value = "GET /probe/liveness HTTP/1.1"

        with patch.dict(os.environ, {"LOG_LEVEL": "INFO"}):
            assert filter_.filter(record) is False

    def test_filter_health_check_debug(self) -> None:
        """Test health checks are NOT filtered out at DEBUG level"""
        filter_ = HealthCheckFilter()
        record = MagicMock(spec=logging.LogRecord)
        record.getMessage.return_value = "GET /probe/readiness HTTP/1.1"

        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            assert filter_.filter(record) is True

    def test_filter_other_requests(self) -> None:
        """Test other requests are never filtered"""
        filter_ = HealthCheckFilter()
        record = MagicMock(spec=logging.LogRecord)
        record.getMessage.return_value = "POST /watchdog HTTP/1.1"

        with patch.dict(os.environ, {"LOG_LEVEL": "INFO"}):
            assert filter_.filter(record) is True


class TestGunicornHooks:
    @patch("gunicorn_config.build_services")
    @patch("gunicorn_config.WatchdogMonitor")
    def test_when_ready(
        self,
        mock_monitor_cls: MagicMock,
        mock_build_services: MagicMock,
    ) -> None:
        """Test when_ready hook initializes everything via the shared
        composition root"""
        server = MagicMock()

        # Reset global state
        gunicorn_config.monitor_thread_started = False

        mock_config = MagicMock()
        mock_notifier = MagicMock()
        mock_service = MagicMock()
        mock_build_services.return_value = (mock_config, mock_notifier, mock_service)

        when_ready(server)

        mock_build_services.assert_called_once()
        mock_monitor_cls.assert_called_once_with(mock_service, mock_notifier, mock_config)
        mock_monitor_cls.return_value.start.assert_called_once()

        # Verify idempotency
        when_ready(server)
        mock_monitor_cls.return_value.start.assert_called_once()  # Still called only once

    def test_on_exit(self) -> None:
        """Test on_exit hook"""
        server = MagicMock()
        on_exit(server)
        server.log.info.assert_called_with("Shutting down watchdog service")
