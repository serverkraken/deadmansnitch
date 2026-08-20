import time
from unittest.mock import MagicMock, patch

import pytest

from app.domain.watchdog_state import WatchdogState
from app.services.kubernetes_probes import KubernetesProbes
from app.services.watchdog_service import WatchdogService


class TestKubernetesProbes:
    @pytest.fixture
    def probes(self, service: WatchdogService) -> KubernetesProbes:
        return KubernetesProbes(service)

    def test_startup_grace_period(self, probes: KubernetesProbes) -> None:
        """Test that probes fail during startup grace period"""
        probes.startup_time = time.monotonic()
        probes.startup_grace_period = 10

        is_ready, message = probes.check_readiness()
        assert is_ready is False
        assert "startup phase" in message

    def test_liveness_check_success(self, probes: KubernetesProbes) -> None:
        """Test liveness check success"""
        is_alive, message = probes.check_liveness()
        assert is_alive is True
        assert "Service is alive" in message

    def test_is_monitor_thread_running_not_started(self, probes: KubernetesProbes) -> None:
        """Test detection when the monitor never wrote a heartbeat"""
        is_running, message = probes.is_monitor_thread_running()
        assert is_running is False
        assert "No monitor heartbeat found" in message

    def test_check_readiness_success(self, probes: KubernetesProbes) -> None:
        """Test readiness check success after grace period"""
        probes.startup_time = time.monotonic() - 100  # Long ago

        # Mock dependencies to pass
        state = WatchdogState()
        state.status = "ok"
        probes.watchdog_service.state = state

        with patch.object(probes, "is_monitor_thread_running", return_value=(True, "OK")):
            with patch("os.path.join", return_value="/tmp/probe_test"):
                with patch("builtins.open", MagicMock()):
                    with patch("os.remove", MagicMock()):
                        is_ready, message = probes.check_readiness()
                        assert is_ready is True
                        assert "ready to receive traffic" in message

    def test_check_readiness_initializing(self, probes: KubernetesProbes) -> None:
        """Test readiness failure when stuck in initializing"""
        probes.startup_time = time.monotonic() - 100
        state = WatchdogState()
        state.status = "initializing"
        probes.watchdog_service.state = state

        with patch.object(probes, "is_monitor_thread_running", return_value=(True, "OK")):
            is_ready, message = probes.check_readiness()
            assert is_ready is False
            assert "stuck in initializing" in message

    def test_check_readiness_monitor_stopped(self, probes: KubernetesProbes) -> None:
        """Test readiness failure when monitor thread stops after grace period"""
        probes.startup_time = time.monotonic() - 200
        probes.startup_grace_period = 60

        state = WatchdogState()
        state.status = "ok"
        probes.watchdog_service.state = state

        with patch.object(probes, "is_monitor_thread_running", return_value=(False, "Stopped")):
            is_ready, message = probes.check_readiness()
            assert is_ready is False
            assert "monitor thread not running" in message

    def test_check_readiness_no_workaround_after_5_minutes(self, probes: KubernetesProbes) -> None:
        """A dead monitor must fail readiness even long after startup"""
        probes.startup_time = time.monotonic() - 400  # > 300s

        state = WatchdogState()
        state.status = "ok"
        probes.watchdog_service.state = state

        with patch.object(probes, "is_monitor_thread_running", return_value=(False, "Stopped")):
            is_ready, message = probes.check_readiness()
            assert is_ready is False
            assert "monitor thread not running" in message

    def test_detection_fresh_heartbeat(self, probes: KubernetesProbes) -> None:
        """Test monitor detection via a fresh heartbeat file"""
        self._write_heartbeat(probes, time.time())
        is_running, message = probes.is_monitor_thread_running()
        assert is_running is True
        assert "fresh" in message

    def test_detection_stale_heartbeat(self, probes: KubernetesProbes) -> None:
        """Test monitor detection rejects a stale heartbeat"""
        self._write_heartbeat(probes, time.time() - probes.HEARTBEAT_MAX_AGE - 10)
        is_running, message = probes.is_monitor_thread_running()
        assert is_running is False
        assert "stale" in message

    @staticmethod
    def _write_heartbeat(probes: KubernetesProbes, timestamp: float) -> None:
        import os

        from app.services.watchdog_monitor import WatchdogMonitor

        path = os.path.join(probes.watchdog_service.repository.data_dir, WatchdogMonitor.HEARTBEAT_FILENAME)
        with open(path, "w") as f:
            f.write(str(timestamp))

    def test_liveness_errors(self, probes: KubernetesProbes) -> None:
        """Test liveness probe edge cases and errors"""
        probes.watchdog_service.state = None
        is_alive, _ = probes.check_liveness()
        assert is_alive is False

        probes.watchdog_service.state = WatchdogState()
        probes.watchdog_service.repository = None  # type: ignore[assignment]
        is_alive, _ = probes.check_liveness()
        assert is_alive is False

        probes.watchdog_service.repository = MagicMock()
        probes.watchdog_service.config = None  # type: ignore[assignment]
        is_alive, _ = probes.check_liveness()
        assert is_alive is False

    def test_readiness_lock_failure(self, probes: KubernetesProbes) -> None:
        """Test readiness failure when state lock is broken"""
        probes.startup_time = time.monotonic() - 100
        probes.watchdog_service.state = WatchdogState()
        probes.watchdog_service.state.status = "ok"

        with patch.object(probes, "is_monitor_thread_running", return_value=(True, "OK")):
            # Cause exception in context manager
            probes.watchdog_service.state_lock = MagicMock()
            probes.watchdog_service.state_lock.__enter__.side_effect = Exception("Lock error")

            is_ready, message = probes.check_readiness()
            assert is_ready is False
            assert "Lock error" in message  # Fallback log message check could be added if captures logs
