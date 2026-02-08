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
    @patch("gunicorn_config.Config.get_instance")
    @patch("gunicorn_config.FileWatchdogRepository")
    @patch("gunicorn_config.Notifier")
    @patch("gunicorn_config.WatchdogService.get_instance")
    @patch("gunicorn_config.WatchdogMonitor")
    def test_when_ready(
        self,
        mock_monitor_cls: MagicMock,
        mock_service_get: MagicMock,
        mock_notifier_cls: MagicMock,
        mock_repo_cls: MagicMock,
        mock_config_get: MagicMock,
    ) -> None:
        """Test when_ready hook initializes everything"""
        server = MagicMock()
        
        # Reset global state
        gunicorn_config.monitor_thread_started = False
        
        # Configure mocks
        mock_config = mock_config_get.return_value
        mock_config.google_chat_webhook_url = "http://chat"
        mock_config.watchdog_timeout = 3600
        
        when_ready(server)
        
        # Verify initializations
        mock_repo_cls.assert_called_once()
        # Check arguments (data_dir, filename, log_interval)
        call_args = mock_repo_cls.call_args
        assert call_args[1].get("log_interval") == 3600.0 or call_args[0][2] == 3600.0
        mock_notifier_cls.assert_called_once()
        mock_service_get.assert_called_once()
        mock_monitor_cls.assert_called_once()
        mock_monitor_cls.return_value.start.assert_called_once()
        
        # Verify idempotency
        when_ready(server)
        mock_monitor_cls.return_value.start.assert_called_once()  # Still called only once

    def test_on_exit(self) -> None:
        """Test on_exit hook"""
        server = MagicMock()
        on_exit(server)
        server.log.info.assert_called_with("Shutting down watchdog service")
