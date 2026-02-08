import time
import threading
import pytest
from unittest.mock import MagicMock, patch
from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService
from app.notifications.notifier import Notifier
from app.config import Config
from app.domain.watchdog_state import WatchdogState

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
        """Test monitor respects grace period"""
        monitor.config.watchdog_timeout = 60
        # 1. startup_time = 1000
        # 2. loop start current_time = 1010
        # Difference 10 < 60 -> enters grace period sleep
        with patch("time.time", side_effect=[1000.0, 1010.0, 1010.0, 1010.0]):
            with patch("time.sleep", side_effect=InterruptedError()) as mock_sleep:
                try:
                    monitor._run_monitor()
                except InterruptedError:
                    pass
                mock_sleep.assert_any_call(30)

    def test_run_monitor_trigger_alert(self, monitor: WatchdogMonitor) -> None:
        """Test monitor triggers alert when timeout occurs"""
        monitor.config.watchdog_timeout = 60
        monitor.config.alert_resend_interval = 300
        
        state = WatchdogState()
        state.last_watchdog_time = 1000.0
        state.status = "ok"
        monitor.watchdog_service.state = state
        
        # startup=1000, loop_start=1100 (> 60s timeout)
        with patch("time.time", side_effect=[1000.0, 1100.0, 1100.0, 1100.0, 1100.0]):
            with patch.object(monitor.watchdog_service, "atomic_update") as mock_atomic:
                mock_atomic.return_value.__enter__.return_value = state
                
                with patch("time.sleep", side_effect=InterruptedError()):
                    try:
                        monitor._run_monitor()
                    except InterruptedError:
                        pass
                
                assert state.status == "alert"
                monitor.notifier.send_alert.assert_called_once()

    def test_run_monitor_daily_status(self, monitor: WatchdogMonitor) -> None:
        """Test monitor sends daily status update"""
        monitor.config.watchdog_timeout = 60
        
        state = WatchdogState()
        state.last_watchdog_time = 99990.0 # Just 10s ago
        state.last_status_notification = 1000.0 # 99000s ago (> 86400)
        state.status = "ok"
        monitor.watchdog_service.state = state
        
        # startup=0, loop_start=100000.0
        with patch("time.time", side_effect=[0.0, 100000.0, 100000.0, 100000.0, 100000.0]):
            with patch.object(monitor.watchdog_service, "atomic_update") as mock_atomic:
                mock_atomic.return_value.__enter__.return_value = state
                
                with patch("time.sleep", side_effect=InterruptedError()):
                    try:
                        monitor._run_monitor()
                    except InterruptedError:
                        pass
                
                monitor.notifier.send_status_update.assert_called_once()

    def test_stop_monitor(self, monitor: WatchdogMonitor) -> None:
        # Currently no stop() method in WatchdogMonitor, it's a daemon thread.
        pass
