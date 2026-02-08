import contextlib
import threading
import time
from typing import Any, cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.config import Config
from app.domain.watchdog_state import WatchdogState
from app.notifications.notifier import Notifier
from app.notifications.providers.google_chat import GoogleChatProvider
from app.persistence.repository import WatchdogRepository
from app.services.kubernetes_probes import KubernetesProbes
from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService


class TestCoverageEdgeCases:
    @pytest.fixture
    def repository_mock(self) -> MagicMock:
        return MagicMock(spec=WatchdogRepository)

    @pytest.fixture
    def service_mock(self, repository_mock: MagicMock) -> MagicMock:
        service = MagicMock(spec=WatchdogService)
        service.repository = repository_mock
        service.state = MagicMock(spec=WatchdogState)
        service.state.status = "ok"
        # Setup mock state lock
        service.state_lock = threading.RLock()

        # Setup atomic_update context manager default behavior
        @contextlib.contextmanager
        def mock_atomic_update() -> Any:
            yield service.state

        service.atomic_update = mock_atomic_update

        return service

    @pytest.fixture
    def config_mock(self) -> MagicMock:
        return MagicMock(spec=Config)

    @pytest.fixture
    def notifier_mock(self) -> MagicMock:
        return MagicMock(spec=Notifier)

    # --- KubernetesProbes Edge Cases ---

    def test_probes_liveness_exception(self, service_mock: MagicMock) -> None:
        """Test liveness check exception handling"""
        probes = KubernetesProbes(service_mock)
        # Configure service.state to raise an exception when accessed
        type(service_mock).state = PropertyMock(side_effect=Exception("Unexpected error"))

        success, message = probes.check_liveness()
        assert success is False
        assert "Liveness check failed" in message

    def test_probes_readiness_liveness_fail(self, service_mock: MagicMock) -> None:
        """Test readiness check failing because liveness failed"""
        probes = KubernetesProbes(service_mock)
        with patch.object(probes, "check_liveness", return_value=(False, "Liveness failed")):
            success, message = probes.check_readiness()
            assert success is False
            assert "Not ready: Liveness failed" in message

    def test_probes_readiness_filesystem_fail(self, service_mock: MagicMock) -> None:
        """Test readiness check with filesystem error (should only warn)"""
        probes = KubernetesProbes(service_mock)
        service_mock.repository.data_dir = "/tmp/test"

        # Mock open to raise exception
        with patch("builtins.open", side_effect=PermissionError("No write access")):
            # Also mock liveness to pass
            with patch.object(probes, "check_liveness", return_value=(True, "OK")):
                # And startup time
                probes.startup_time = time.time() - 100
                # And monitor thread check
                with patch.object(probes, "is_monitor_thread_running", return_value=(True, "OK")):
                    # And state
                    service_mock.state.status = "ok"

                    success, message = probes.check_readiness()
                    # It catches exception and logs warning, but proceeds
                    assert success is True

    def test_probes_readiness_exception(self, service_mock: MagicMock) -> None:
        """Test readiness check global exception handling"""
        probes = KubernetesProbes(service_mock)
        with patch.object(probes, "check_liveness", side_effect=Exception("Crash")):
            success, message = probes.check_readiness()
            assert success is False
            assert "Readiness check failed" in message

    def test_is_monitor_thread_running_previously_detected(self, service_mock: MagicMock) -> None:
        """Test monitor thread assumed running if previously detected and sufficient threads exist"""
        probes = KubernetesProbes(service_mock)
        probes.monitor_thread_detected = True

        # Mock threading.enumerate to return enough threads but none with expected name
        dummy_threads = [MagicMock(name="other-1"), MagicMock(name="other-2")]
        with patch("threading.enumerate", return_value=dummy_threads):
            success, message = probes.is_monitor_thread_running()
            assert success is True
            assert "Monitor assumed running" in message

    # --- WatchdogService Edge Cases ---

    def test_service_get_instance_missing_args(self) -> None:
        """Test get_instance raises ValueError if args missing on first init"""
        WatchdogService._instance = None
        with pytest.raises(ValueError):
            WatchdogService.get_instance()

    def test_process_alert_invalid_payload_type(
        self, config_mock: MagicMock, repository_mock: MagicMock, notifier_mock: MagicMock
    ) -> None:
        """Test alert processing with list payload (not dict)"""
        # We need a real service instance to test the method logic, not a mock
        service = WatchdogService(repository_mock, notifier_mock, config_mock)

        success, message = service.process_watchdog_alert(cast(Any, ["not", "a", "dict"]))
        assert success is False
        assert "Invalid payload" in message

    def test_validate_watchdog_alert_direct_format(
        self, config_mock: MagicMock, repository_mock: MagicMock, notifier_mock: MagicMock
    ) -> None:
        """Test validation of direct alert format (labels at top level)"""
        service = WatchdogService(repository_mock, notifier_mock, config_mock)
        payload = {"labels": {"alertname": "Watchdog"}}
        assert service._validate_watchdog_alert(payload) is True

    # --- GoogleChatProvider Edge Cases ---

    def test_google_chat_send_exception(self) -> None:
        """Test Google Chat send error handling"""
        provider = GoogleChatProvider("http://url")
        # It uses requests.post, not urllib
        with patch("requests.post", side_effect=Exception("Network error")):
            # Should not raise exception
            assert provider.send("Test message") is False

    # --- FileWatchdogRepository Edge Cases ---

    def test_repo_ensure_dir_fail(self) -> None:
        """Test failure to create data directory"""
        from app.persistence.file_repository import FileWatchdogRepository

        with patch("os.path.exists", return_value=False):
            with patch("os.makedirs", side_effect=OSError("No permission")):
                # Should log error but not crash (constructor calls it)
                FileWatchdogRepository("/tmp/bad", "file.json")

    def test_repo_save_exception_cleanup_fail(self) -> None:
        """Test save failure cleans up temp file, and handles cleanup failure"""
        from app.persistence.file_repository import FileWatchdogRepository

        repo = FileWatchdogRepository("/tmp/test", "file.json")
        state = WatchdogState()

        # Mock json.dump to raise exception (so temp file is created/opened)
        with patch("json.dump", side_effect=ValueError("Serialization error")):
            with patch("builtins.open"):  # Mock open to succeed
                with patch("os.path.exists", return_value=True):  # tmp file exists
                    with patch("os.remove", side_effect=OSError("Cannot delete")):  # Cleanup fails too
                        repo.save(state)
                        # Should catch both exceptions and return False

    # --- WatchdogMonitor Edge Cases ---

    def test_monitor_loop_logic_repeat_alert(
        self, config_mock: MagicMock, service_mock: MagicMock, notifier_mock: MagicMock
    ) -> None:
        """Test monitor loop repeat alert logic"""
        config_mock.watchdog_timeout = 60
        config_mock.alert_resend_interval = 300
        monitor = WatchdogMonitor(service_mock, notifier_mock, config_mock)

        # Setup state
        state = MagicMock(spec=WatchdogState)
        state.status = "alert"
        # We set specific times to match our time.time mock below
        # current_time will be 1100.0
        # last_watchdog needs to be < 1100 - 60 => 1000 is fine (diff 100)
        state.last_watchdog_time = 1000.0
        # last_alert needs to be < 1100 - 300 => 700 is fine (diff 400)
        state.last_alert_notification = 700.0
        state.last_status_notification = 0.0  # Fix

        # Override atomic_update for this test instance
        @contextlib.contextmanager
        def mock_atomic_update() -> Any:
            yield state

        service_mock.atomic_update = mock_atomic_update
        service_mock.state = state

        # Mock time.time to return [startup_time, loop_iteration_time]
        with patch("time.time", side_effect=[1000.0, 1100.0]):
            # We want sleep to raise to break loop on first call (end of loop)
            with patch("time.sleep", side_effect=Exception("BreakLoop")):
                try:
                    monitor._run_monitor()
                except Exception as e:
                    if str(e) != "BreakLoop":
                        raise

        # Check if repeated alert was sent
        notifier_mock.send_repeated_alert.assert_called()

    def test_monitor_grace_period(
        self, config_mock: MagicMock, service_mock: MagicMock, notifier_mock: MagicMock
    ) -> None:
        """Test monitor loop usage of grace period"""
        config_mock.watchdog_timeout = 60
        monitor = WatchdogMonitor(service_mock, notifier_mock, config_mock)
        service_mock.state = MagicMock()

        # Mock atomic_update to verify not called
        atomic_update_mock = MagicMock()
        service_mock.atomic_update = atomic_update_mock

        # Sequence: startup_time call, then current_time call in loop
        # We need two iterations to cover 'continue'
        # 1. startup = 100
        # 2. iter1 current = 110 (diff 10 < 60) -> sleep(30) -> continue
        # 3. iter2 current = 120 (diff 20 < 60) -> sleep(30) -> RAISE
        with patch("time.time", side_effect=[100.0, 110.0, 120.0]):
            with patch("time.sleep", side_effect=[None, Exception("BreakLoop")]):
                try:
                    monitor._run_monitor()
                except Exception:
                    pass

        atomic_update_mock.assert_not_called()

    # --- Notifier Edge Cases ---

    def test_notifier_no_providers(self) -> None:
        """Test notify_all with no providers"""
        notifier = Notifier()
        success = notifier.notify_all("test")
        assert success is False

    def test_notifier_repeated_alert(self) -> None:
        """Test send_repeated_alert"""
        notifier = Notifier()
        notifier.add_provider(MagicMock())
        # Call directly to cover MessageFactory
        with patch.object(notifier, "notify_all", return_value=True) as mock_notify:
            success = notifier.send_repeated_alert(100, "now")
            assert success is True
            # Verify message content structure roughly
            args, _ = mock_notify.call_args
            assert "Still Missing" in args[0]
            assert "100" in args[0]

    def test_message_factory_methods(self) -> None:
        from app.notifications.message_factory import MessageFactory

        msg = MessageFactory.create_repeated_alert_message(100.0, "time")
        assert "Still Missing" in msg
        assert "100" in msg

    # --- Google Chat Edge Cases ---

    def test_google_chat_empty_url(self) -> None:
        """Test Google Chat provider with empty URL"""
        provider = GoogleChatProvider("")
        assert provider.send("test") is False

    def test_google_chat_name(self) -> None:
        """Test Google Chat provider name"""
        provider = GoogleChatProvider("url")
        assert provider.name() == "Google Chat"
