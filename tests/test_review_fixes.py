"""Regression tests for the 2026-08 main-branch code review findings.

Each test class maps to one finding. See the review report for details.
"""

import json
import os
import threading
import time
from typing import Any, Callable, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.notifications.notifier import Notifier
from app.persistence.file_repository import FileWatchdogRepository
from app.services.kubernetes_probes import KubernetesProbes
from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService


@pytest.fixture
def monitor(service: WatchdogService, mock_config: Config) -> WatchdogMonitor:
    notifier = MagicMock(spec=Notifier)
    return WatchdogMonitor(service, notifier, mock_config)


def _set_state(service: WatchdogService, **attrs: Any) -> None:
    """Persist given attributes into the on-disk state."""
    with service.atomic_update() as state:
        for key, value in attrs.items():
            setattr(state, key, value)


def _lock_free_probe(service: WatchdogService, seen: Dict[str, Any]) -> Callable[..., bool]:
    """Return a side-effect that records whether the service locks are free.

    It tries a full atomic_update from a second thread; if the caller still
    holds the state lock / file lock, the thread times out and we record False.
    """

    def side_effect(*args: Any, **kwargs: Any) -> bool:
        result: Dict[str, bool] = {}

        def try_update() -> None:
            try:
                with service.atomic_update():
                    pass
                result["ok"] = True
            except Exception:
                result["ok"] = False

        t = threading.Thread(target=try_update, daemon=True)
        t.start()
        t.join(timeout=2)
        seen["lock_free"] = result.get("ok", False)
        return True

    return side_effect


class TestAlertOnlyMarkedNotifiedOnSuccess:
    """Finding 1: a failed webhook POST must not silence the alert for 6h."""

    def test_failed_send_leaves_state_unmarked(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = False  # type: ignore[attr-defined]

        monitor._tick(now)

        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]
        persisted = service.repository.load()
        assert persisted.last_alert_notification == 0
        assert persisted.status == "ok"

    def test_failed_send_is_retried(
        self, monitor: WatchdogMonitor, service: WatchdogService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = False  # type: ignore[attr-defined]

        monitor._tick(now)
        # Within the retry throttle window: no second attempt yet
        monitor._tick(now + 1)
        assert monitor.notifier.send_alert.call_count == 1  # type: ignore[attr-defined]
        # After the throttle window (monotonic clock) the send is retried
        real_monotonic = time.monotonic
        offset = WatchdogMonitor.SEND_RETRY_INTERVAL + 1
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + offset)
        monitor._tick(now + offset)
        assert monitor.notifier.send_alert.call_count == 2  # type: ignore[attr-defined]

    def test_successful_send_marks_notified(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = True  # type: ignore[attr-defined]

        monitor._tick(now)

        persisted = service.repository.load()
        assert persisted.status == "alert"
        assert persisted.last_alert_notification > 0


class TestHealthCheckIsReadOnly:
    """Finding 2: /health must not persist alert status behind the monitor's back."""

    def test_health_reports_alert_without_persisting(self, service: WatchdogService) -> None:
        _set_state(service, last_watchdog_time=time.time() - 120, status="ok")

        health = service.get_health_status()

        assert health["status"] == "alert"
        assert health["is_healthy"] is False
        persisted = service.repository.load()
        assert persisted.status == "ok"
        assert persisted.last_alert_notification == 0


class TestResolvedWatchdogIsNotAPing:
    """Finding 3: a 'resolved' Watchdog webhook must not reset the dead-man timer."""

    def test_resolved_alert_does_not_reset_timer(self, service: WatchdogService) -> None:
        old = time.time() - 120
        _set_state(service, last_watchdog_time=old, status="alert")

        payload = {"alerts": [{"labels": {"alertname": "Watchdog"}, "status": "resolved"}]}
        success, message = service.process_watchdog_alert(payload)

        assert success is True
        assert "resolved" in message.lower()
        persisted = service.repository.load()
        assert persisted.last_watchdog_time == pytest.approx(old)
        assert persisted.status == "alert"
        service.notifier.send_recovery.assert_not_called()  # type: ignore[attr-defined]
        assert persisted.total_received == 1
        assert persisted.invalid_received == 0


class TestSaveFailureHandling:
    """Finding 4: save() failures must neither storm nor silence alerts."""

    def test_atomic_update_raises_on_save_failure(self, service: WatchdogService) -> None:
        from app.persistence.repository import StatePersistenceError

        with patch.object(service.repository, "save", return_value=False):
            with pytest.raises(StatePersistenceError):
                with service.atomic_update():
                    pass

    def test_no_alert_storm_when_save_fails(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = True  # type: ignore[attr-defined]

        with patch.object(service.repository, "save", return_value=False):
            monitor._tick(now)
            monitor._tick(now + 1)
            monitor._tick(now + 2)

        # Initial alert sent exactly once despite persistence being broken
        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]

    def test_repeat_alert_uses_memory_marker_when_save_fails(
        self, monitor: WatchdogMonitor, service: WatchdogService, mock_config: Config
    ) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = True  # type: ignore[attr-defined]
        monitor.notifier.send_repeated_alert.return_value = True  # type: ignore[attr-defined]

        with patch.object(service.repository, "save", return_value=False):
            monitor._tick(now)
            monitor._tick(now + mock_config.alert_resend_interval + 1)

        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]
        monitor.notifier.send_repeated_alert.assert_called_once()  # type: ignore[attr-defined]

    def test_alert_sent_even_if_locking_is_broken(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        """EROFS scenario: atomic_update unusable, the alert must still go out."""
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        monitor.notifier.send_alert.return_value = True  # type: ignore[attr-defined]

        with patch.object(service, "atomic_update", side_effect=OSError("read-only fs")):
            monitor._tick(now)

        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]


class TestMonitorHeartbeat:
    """Finding 5: readiness must detect a dead monitor via a heartbeat, not thread heuristics."""

    def test_monitor_writes_heartbeat(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        monitor._write_heartbeat(1234.5)
        path = os.path.join(service.repository.data_dir, WatchdogMonitor.HEARTBEAT_FILENAME)
        with open(path) as f:
            assert float(f.read()) == 1234.5

    def test_probe_accepts_fresh_heartbeat(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        monitor._write_heartbeat(time.time())
        probes = KubernetesProbes(service)
        is_running, _ = probes.is_monitor_thread_running()
        assert is_running is True

    def test_probe_rejects_stale_heartbeat(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        monitor._write_heartbeat(time.time() - 1000)
        probes = KubernetesProbes(service)
        is_running, _ = probes.is_monitor_thread_running()
        assert is_running is False

    def test_probe_rejects_missing_heartbeat(self, service: WatchdogService) -> None:
        probes = KubernetesProbes(service)
        is_running, _ = probes.is_monitor_thread_running()
        assert is_running is False

    def test_readiness_fails_on_dead_monitor_even_after_5_minutes(self, service: WatchdogService) -> None:
        """The old 300s 'temporary workaround' must not override a dead monitor."""
        probes = KubernetesProbes(service)
        probes.startup_time = time.monotonic() - 400
        _set_state(service, status="ok", last_watchdog_time=time.time())
        service.state = service.repository.load()

        is_ready, message = probes.check_readiness()

        assert is_ready is False
        assert "monitor" in message.lower()


class TestCorruptStateFallback:
    """Finding 6: a corrupt state file must not trigger an immediate false alert."""

    def test_corrupt_file_resets_to_current_time(self, temp_data_dir: str) -> None:
        repo = FileWatchdogRepository(temp_data_dir, "corrupt.json", log_interval=60.0)
        filepath = os.path.join(temp_data_dir, "corrupt.json")
        with open(filepath, "w") as f:
            f.write("{ invalid json")

        before = time.time()
        state = repo.load()

        assert state.last_watchdog_time >= before
        assert state.last_status_notification >= before
        assert state.status == "waiting_for_first_alert"
        # The recovered state replaces the corrupt file so the timer keeps running
        with open(filepath) as f:
            reloaded = json.load(f)
        assert reloaded["last_watchdog_time"] == state.last_watchdog_time


class TestGroupedAndMalformedAlerts:
    """Finding 7: grouped payloads must be scanned; non-dict entries must not crash."""

    def test_watchdog_found_at_later_index(self, service: WatchdogService) -> None:
        payload = {
            "alerts": [
                {"labels": {"alertname": "SomethingElse"}},
                {"labels": {"alertname": "Watchdog"}, "status": "firing"},
            ]
        }

        success, message = service.process_watchdog_alert(payload)

        assert success is True
        persisted = service.repository.load()
        assert persisted.status == "ok"
        assert persisted.last_watchdog_time > 0

    def test_non_dict_alert_entry_is_rejected_not_crash(self, service: WatchdogService) -> None:
        success, message = service.process_watchdog_alert({"alerts": [None]})
        assert success is False

    def test_non_dict_alert_entry_returns_400(self, client: Any) -> None:
        response = client.post("/watchdog", json={"alerts": [None]})
        assert response.status_code == 400


class TestInvalidPayloadHttpStatus:
    """Finding 8: rejected payloads must return 400, not 200-with-warning."""

    def test_wrong_alertname_returns_400(self, client: Any, service: WatchdogService) -> None:
        response = client.post("/watchdog", json={"alerts": [{"labels": {"alertname": "Wrong"}}]})
        assert response.status_code == 400
        assert response.get_json()["status"] == "error"

    def test_invalid_format_returns_400(self, client: Any) -> None:
        response = client.post("/watchdog", json={"unexpected": "shape"})
        assert response.status_code == 400

    def test_valid_payload_still_returns_200(self, client: Any) -> None:
        response = client.post("/watchdog", json={"alerts": [{"labels": {"alertname": "Watchdog"}}]})
        assert response.status_code == 200
        assert response.get_json()["status"] == "success"


class TestInvalidAlertCountedOnce:
    """Finding 9: an invalid alert must increment total_received exactly once."""

    def test_single_invalid_post_counts_once(self, service: WatchdogService) -> None:
        success, _ = service.process_watchdog_alert({"alerts": []})
        assert success is False
        persisted = service.repository.load()
        assert persisted.total_received == 1
        assert persisted.invalid_received == 1

    def test_mixed_traffic_counts_correctly(self, service: WatchdogService) -> None:
        valid = {"alerts": [{"labels": {"alertname": "Watchdog"}}]}
        invalid: Dict[str, Any] = {"alerts": []}
        for _ in range(2):
            service.process_watchdog_alert(valid)
        for _ in range(3):
            service.process_watchdog_alert(invalid)

        persisted = service.repository.load()
        assert persisted.total_received == 5
        assert persisted.invalid_received == 3


class TestNotificationsSentOutsideLocks:
    """Finding 10: network I/O must not run while holding the state/file locks."""

    def test_recovery_sent_after_locks_released(self, service: WatchdogService) -> None:
        _set_state(service, status="alert", last_watchdog_time=time.time())
        seen: Dict[str, Any] = {}
        service.notifier.send_recovery.side_effect = _lock_free_probe(service, seen)  # type: ignore[attr-defined]

        payload = {"alerts": [{"labels": {"alertname": "Watchdog"}, "status": "firing"}]}
        success, _ = service.process_watchdog_alert(payload)

        assert success is True
        service.notifier.send_recovery.assert_called_once()  # type: ignore[attr-defined]
        assert seen["lock_free"] is True

    def test_initial_alert_sent_without_holding_locks(self, monitor: WatchdogMonitor, service: WatchdogService) -> None:
        now = time.time()
        _set_state(service, last_watchdog_time=now - 120, status="ok")
        seen: Dict[str, Any] = {}
        monitor.notifier.send_alert.side_effect = _lock_free_probe(service, seen)  # type: ignore[attr-defined]

        monitor._tick(now)

        monitor.notifier.send_alert.assert_called_once()  # type: ignore[attr-defined]
        assert seen["lock_free"] is True
