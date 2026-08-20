from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.notifications.notifier import Notifier
from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService


class TestWatchdogMonitor:
    @pytest.fixture
    def monitor(self, service: WatchdogService, mock_config: Config) -> WatchdogMonitor:
        notifier = MagicMock(spec=Notifier)
        return WatchdogMonitor(service, notifier, mock_config)

    def test_start_monitor(self, monitor: WatchdogMonitor) -> None:
        """Test starting the monitor thread"""
        with patch("threading.Thread") as mock_thread:
            monitor.start()
            mock_thread.assert_called_once()
            assert monitor.thread is not None
            # Cleanup
            monitor.thread = None

    def test_start_already_running(self, monitor: WatchdogMonitor) -> None:
        """Test starting when already running"""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        monitor.thread = mock_thread

        with patch("threading.Thread") as mock_new_thread:
            monitor.start()
            mock_new_thread.assert_not_called()

    def test_run_monitor_initializes_service(self, monitor: WatchdogMonitor) -> None:
        """Test that monitor initializes service if state is None"""
        monitor.watchdog_service.state = None
        with patch.object(monitor.watchdog_service, "initialize") as mock_init:
            with patch("time.time", return_value=1000.0):
                # Force exit loop immediately
                with patch("time.sleep", side_effect=InterruptedError()):
                    try:
                        monitor._run_monitor()
                    except InterruptedError:
                        pass
            mock_init.assert_called_once()

    def test_run_monitor_grace_period(self, monitor: WatchdogMonitor) -> None:
        """Test monitor respects grace period: no tick while grace remains"""
        with patch.object(monitor, "_compute_grace_period", return_value=60.0):
            with patch.object(monitor, "_tick") as mock_tick:
                with patch("time.sleep", side_effect=InterruptedError()) as mock_sleep:
                    try:
                        monitor._run_monitor()
                    except InterruptedError:
                        pass
        mock_tick.assert_not_called()
        mock_sleep.assert_any_call(min(30.0, monitor._tick_interval))

    def test_run_monitor_trigger_alert(self, monitor: WatchdogMonitor) -> None:
        """Test monitor triggers alert when timeout occurs"""
        import time

        now = time.time()
        with monitor.watchdog_service.atomic_update() as state:
            state.last_watchdog_time = now - monitor.config.watchdog_timeout - 40
            state.status = "ok"
        monitor.notifier.send_alert.return_value = True  # type: ignore[attr-defined]

        monitor._tick(now)

        persisted = monitor.watchdog_service.repository.load()
        assert persisted.status == "alert"
        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]

    def test_run_monitor_daily_status(self, monitor: WatchdogMonitor) -> None:
        """Test monitor sends daily status update"""
        import time

        now = time.time()
        with monitor.watchdog_service.atomic_update() as state:
            state.last_watchdog_time = now - 10
            state.last_status_notification = now - 90000  # > 86400s ago
            state.status = "ok"
        monitor.notifier.send_status_update.return_value = True  # type: ignore[attr-defined]

        monitor._tick(now)

        monitor.notifier.send_status_update.assert_called_once()  # type: ignore[attr-defined]

    def test_stop_monitor(self, monitor: WatchdogMonitor) -> None:
        # Currently no stop() method in WatchdogMonitor, it's a daemon thread.
        pass
