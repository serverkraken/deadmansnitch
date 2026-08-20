"""Tests for the findings of the 2026-08 full-codebase audit.

Each test class maps to one audit finding; see the PR description for the
finding numbers.
"""

import os
import time
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.domain.watchdog_state import WatchdogState
from app.persistence.file_repository import FileWatchdogRepository
from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService


def _watchdog_payload(**alert_overrides: Any) -> Dict[str, Any]:
    alert: Dict[str, Any] = {
        "labels": {"alertname": "Watchdog"},
        "annotations": {"summary": "ok"},
        "status": "firing",
    }
    alert.update(alert_overrides)
    return {"alerts": [alert], "status": "firing"}


@pytest.fixture
def monitor(service: WatchdogService, mock_config: Config) -> WatchdogMonitor:
    return WatchdogMonitor(service, MagicMock(), mock_config)


class TestMalformedAlertFields:
    """A valid watchdog ping must be recorded even when optional fields
    carry null or non-dict values (finding: annotations crash)."""

    def test_null_annotations_ping_is_recorded(self, service: WatchdogService) -> None:
        success, message = service.process_watchdog_alert(_watchdog_payload(annotations=None))
        assert success

    def test_string_annotations_ping_is_recorded(self, service: WatchdogService) -> None:
        success, message = service.process_watchdog_alert(_watchdog_payload(annotations="broken"))
        assert success

    def test_null_annotations_updates_last_watchdog_time(self, service: WatchdogService) -> None:
        before = time.time()
        service.process_watchdog_alert(_watchdog_payload(annotations=None))
        state = service.repository.load()
        assert state.last_watchdog_time >= before

    def test_record_watchdog_alert_with_non_dict_labels(self) -> None:
        state = WatchdogState()
        state.record_watchdog_alert({"labels": None, "annotations": None})
        assert state.status == "ok"
        assert state.last_watchdog_details["alertname"] == "unknown"


class TestStartupGracePeriod:
    """The monitor must not re-arm a full grace period when persisted state
    already shows the pipeline silent (finding: restart resets detection)."""

    def test_grace_zero_when_persisted_ping_already_timed_out(
        self, service: WatchdogService, monitor: WatchdogMonitor, mock_config: Config
    ) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time() - (mock_config.watchdog_timeout + 10)
            state.status = "ok"
        assert monitor._compute_grace_period() == 0.0

    def test_grace_is_remaining_window_when_ping_is_recent(
        self, service: WatchdogService, monitor: WatchdogMonitor, mock_config: Config
    ) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time() - (mock_config.watchdog_timeout / 2)
            state.status = "ok"
        grace = monitor._compute_grace_period()
        assert 0 < grace <= mock_config.watchdog_timeout / 2 + 1

    def test_grace_is_full_timeout_for_fresh_state(
        self, service: WatchdogService, monitor: WatchdogMonitor, mock_config: Config
    ) -> None:
        # conftest initializes a brand-new state with last_watchdog_time=now
        grace = monitor._compute_grace_period()
        assert mock_config.watchdog_timeout - 1 <= grace <= mock_config.watchdog_timeout

    def test_grace_is_full_timeout_when_state_unreadable(
        self, service: WatchdogService, monitor: WatchdogMonitor, mock_config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service.repository, "load", MagicMock(side_effect=OSError("boom")))
        assert monitor._compute_grace_period() == float(mock_config.watchdog_timeout)


class TestRecoveryNotificationDelivery:
    """A delivered MISSING alert must always be followed by exactly one
    recovery notification (findings: recovery lost via race/persistence
    failure, failed recovery never retried)."""

    def _put_in_alert(self, service: WatchdogService) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time() - 10
            state.set_alert_status()

    def test_failed_service_recovery_marks_pending(self, service: WatchdogService) -> None:
        self._put_in_alert(service)
        service.notifier.send_recovery.return_value = False
        success, _ = service.process_watchdog_alert(_watchdog_payload())
        assert success
        assert service.repository.load().recovery_pending is True

    def test_successful_service_recovery_clears_pending(self, service: WatchdogService) -> None:
        self._put_in_alert(service)
        service.notifier.send_recovery.return_value = True
        service.process_watchdog_alert(_watchdog_payload())
        assert service.repository.load().recovery_pending is False

    def test_monitor_retries_pending_recovery(self, service: WatchdogService, monitor: WatchdogMonitor) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time()
            state.status = "ok"
            state.recovery_pending = True
        monitor.notifier.send_recovery.return_value = True
        monitor._tick(time.time())
        monitor.notifier.send_recovery.assert_called_once()
        assert service.repository.load().recovery_pending is False

    def test_monitor_keeps_pending_when_retry_fails(self, service: WatchdogService, monitor: WatchdogMonitor) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time()
            state.status = "ok"
            state.recovery_pending = True
        monitor.notifier.send_recovery.return_value = False
        monitor._tick(time.time())
        assert service.repository.load().recovery_pending is True

    def test_monitor_sends_recovery_when_alert_was_never_persisted(
        self, service: WatchdogService, monitor: WatchdogMonitor
    ) -> None:
        # The monitor delivered an alert but could not persist it; the
        # webhook never saw status "alert", so only the monitor can recover.
        monitor._alert_active = True
        monitor._alert_persisted = False
        monitor.notifier.send_recovery.return_value = True
        monitor._tick(time.time())
        monitor.notifier.send_recovery.assert_called_once()
        assert monitor._alert_active is False

    def test_monitor_skips_recovery_when_service_already_handled_it(
        self, service: WatchdogService, monitor: WatchdogMonitor
    ) -> None:
        # Persisted path: the webhook saw status "alert" and sent the
        # recovery itself (recovery_pending already cleared).
        monitor._alert_active = True
        monitor._alert_persisted = True
        monitor._tick(time.time())
        monitor.notifier.send_recovery.assert_not_called()
        assert monitor._alert_active is False

    def test_race_ping_during_alert_send_marks_recovery_pending(
        self, service: WatchdogService, monitor: WatchdogMonitor
    ) -> None:
        # Alert was delivered, but a ping landed during the blocking send:
        # the re-check must schedule a recovery instead of dropping it.
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time()
            state.status = "ok"
        monitor._persist_alert_notification(time.time())
        assert service.repository.load().recovery_pending is True

    def test_recovery_pending_survives_serialization(self) -> None:
        state = WatchdogState()
        state.recovery_pending = True
        restored = WatchdogState().from_dict(state.to_dict())
        assert restored.recovery_pending is True


class TestStatusUpdateRetryGate:
    """A failed daily status send must respect the retry interval instead
    of being retried every tick (finding: 1s retry storm)."""

    def _age_status(self, service: WatchdogService) -> None:
        with service.atomic_update() as state:
            state.last_watchdog_time = time.time()
            state.status = "ok"
            state.last_status_notification = time.time() - (WatchdogMonitor.DAILY_STATUS_INTERVAL + 60)

    def test_failed_status_send_is_not_retried_immediately(
        self, service: WatchdogService, monitor: WatchdogMonitor
    ) -> None:
        self._age_status(service)
        monitor.notifier.send_status_update.return_value = False
        monitor._tick(time.time())
        monitor._tick(time.time())
        assert monitor.notifier.send_status_update.call_count == 1

    def test_failed_status_send_is_retried_after_interval(
        self, service: WatchdogService, monitor: WatchdogMonitor, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._age_status(service)
        monitor.notifier.send_status_update.return_value = False
        monitor._tick(time.time())
        # Advance the monotonic clock past the retry interval
        real_monotonic = time.monotonic
        offset = WatchdogMonitor.SEND_RETRY_INTERVAL + 1
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + offset)
        monitor._tick(time.time())
        assert monitor.notifier.send_status_update.call_count == 2


class TestMonitorTickInterval:
    """The monitor cadence must be configurable and default well above the
    former 1s busy-loop (finding: ~86k state reads per day)."""

    def test_config_default_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MONITOR_INTERVAL", raising=False)
        config = Config()
        assert config.monitor_interval == 15.0

    def test_config_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONITOR_INTERVAL", "30")
        config = Config()
        assert config.monitor_interval == 30.0

    def test_monitor_uses_configured_interval(self, service: WatchdogService, mock_config: Config) -> None:
        mock_config.monitor_interval = 20.0
        monitor = WatchdogMonitor(service, MagicMock(), mock_config)
        assert monitor._tick_interval == 20.0


class TestBootResilience:
    """An unwritable data dir at boot must degrade, not crash the gunicorn
    master and workers (finding: read-only boot crash)."""

    def test_build_services_survives_initialize_failure(
        self, temp_data_dir: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.bootstrap import build_services

        Config._instance = None
        WatchdogService._instance = None
        monkeypatch.setenv("DATA_DIR", temp_data_dir)
        monkeypatch.setattr(WatchdogService, "initialize", MagicMock(side_effect=PermissionError("read-only fs")))
        config, notifier, service = build_services()
        assert service is not None

    def test_create_app_survives_initialize_failure(self, temp_data_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import create_app

        Config._instance = None
        WatchdogService._instance = None
        monkeypatch.setenv("DATA_DIR", temp_data_dir)
        monkeypatch.setenv("RUNNING_IN_GUNICORN", "true")
        monkeypatch.setattr(WatchdogService, "initialize", MagicMock(side_effect=PermissionError("read-only fs")))
        app = create_app()
        assert app is not None


class TestRequestBodyLimit:
    """Unbounded POST bodies must be rejected before they can occupy the
    worker threads or RAM (finding: no MAX_CONTENT_LENGTH)."""

    def test_config_default_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAX_CONTENT_LENGTH", raising=False)
        config = Config()
        assert config.max_content_length == 65536

    def test_create_app_sets_flask_limit(self, temp_data_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import create_app

        Config._instance = None
        WatchdogService._instance = None
        monkeypatch.setenv("DATA_DIR", temp_data_dir)
        monkeypatch.setenv("RUNNING_IN_GUNICORN", "true")
        app = create_app()
        assert app.config["MAX_CONTENT_LENGTH"] == 65536

    def test_oversized_body_is_rejected(self, temp_data_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import create_app

        Config._instance = None
        WatchdogService._instance = None
        monkeypatch.setenv("DATA_DIR", temp_data_dir)
        monkeypatch.setenv("RUNNING_IN_GUNICORN", "true")
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.post("/watchdog", data=b"x" * (65536 + 1), content_type="application/json")
        assert response.status_code == 413


class TestWebhookAuthentication:
    """POST /watchdog must support a shared-secret token so liveness pings
    cannot be forged (finding: unauthenticated dead-man reset)."""

    def test_config_default_is_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WATCHDOG_AUTH_TOKEN", raising=False)
        config = Config()
        assert config.auth_token is None

    def test_without_configured_token_requests_pass(self, client: Any, mock_config: Config) -> None:
        mock_config.auth_token = None
        response = client.post("/watchdog", json=_watchdog_payload())
        assert response.status_code == 200

    def test_missing_token_is_rejected(self, client: Any, mock_config: Config) -> None:
        mock_config.auth_token = "s3cret"
        response = client.post("/watchdog", json=_watchdog_payload())
        assert response.status_code == 401

    def test_wrong_token_is_rejected(self, client: Any, mock_config: Config) -> None:
        mock_config.auth_token = "s3cret"
        response = client.post("/watchdog", json=_watchdog_payload(), headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_correct_token_is_accepted(self, client: Any, mock_config: Config) -> None:
        mock_config.auth_token = "s3cret"
        response = client.post("/watchdog", json=_watchdog_payload(), headers={"Authorization": "Bearer s3cret"})
        assert response.status_code == 200


class TestErrorResponses:
    """Internal error details must not leak to unauthenticated callers
    (finding: str(e) in 500 bodies)."""

    def test_exception_details_are_not_returned(self, client: Any, service: WatchdogService) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(service, "process_watchdog_alert", MagicMock(side_effect=RuntimeError("secret detail")))
            response = client.post("/watchdog", json=_watchdog_payload())
        assert response.status_code == 500
        assert b"secret detail" not in response.data


class TestVersionReporting:
    """The root endpoint must report the released version, not a hardcoded
    stale one (finding: 2.0.0 vs pyproject)."""

    def test_root_version_matches_package_version(self, client: Any) -> None:
        from app.version import __version__

        response = client.get("/")
        assert response.get_json()["version"] == __version__
        assert response.get_json()["version"] != "2.0.0"

    def test_version_matches_pyproject(self) -> None:
        import tomllib

        from app.version import __version__

        with open("pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)
        assert __version__ == pyproject["project"]["version"]


class TestCorruptStateFileHandling:
    """A corrupt state file resets the dead-man timer at exactly the moment
    it matters; that reset must be loud and forensically traceable
    (finding: outage masking)."""

    def _corrupt(self, temp_data_dir: str) -> str:
        path = os.path.join(temp_data_dir, "watchdog_state.json")
        with open(path, "w") as f:
            f.write("{this is not json")
        return path

    def test_corrupt_file_is_preserved_for_forensics(self, temp_data_dir: str) -> None:
        path = self._corrupt(temp_data_dir)
        repo = FileWatchdogRepository(temp_data_dir, "watchdog_state.json")
        state = repo.load()
        assert state.status == "waiting_for_first_alert"
        assert os.path.exists(f"{path}.corrupt")

    def test_corruption_is_logged_critical(self, temp_data_dir: str, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        self._corrupt(temp_data_dir)
        repo = FileWatchdogRepository(temp_data_dir, "watchdog_state.json")
        with caplog.at_level(logging.CRITICAL, logger="watchdog_service"):
            repo.load()
        assert any(r.levelno == logging.CRITICAL for r in caplog.records)


class TestPersistencePathsAndDurability:
    """Lock path must derive from the repository's own path joins, and the
    rename must be made durable with a directory fsync (findings: lock/file
    divergence, missing dir fsync)."""

    def test_repository_exposes_filepath(self, repository: FileWatchdogRepository, temp_data_dir: str) -> None:
        assert repository.filepath == os.path.join(temp_data_dir, "watchdog_state.json")

    def test_atomic_update_lock_derives_from_repository_filepath(self, service: WatchdogService) -> None:
        with service.atomic_update():
            assert os.path.exists(f"{service.repository.filepath}.lock")

    def test_save_fsyncs_the_directory(
        self, repository: FileWatchdogRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        synced_fds = []
        real_fsync = os.fsync

        def tracking_fsync(fd: int) -> None:
            synced_fds.append(fd)
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", tracking_fsync)
        assert repository.save(WatchdogState()) is True
        # One fsync for the temp file, one for the containing directory -
        # without the latter the rename is not durable across power loss
        assert len(synced_fds) >= 2


class TestHealthcheckLogFilter:
    """The Docker healthcheck polls /health every 30s; those hits must not
    spam the access log (finding: filter only covers /probe/)."""

    def test_health_hits_are_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import logging

        from gunicorn_config import HealthCheckFilter

        monkeypatch.setenv("LOG_LEVEL", "info")
        record = logging.LogRecord("gunicorn.access", logging.INFO, "", 0, 'GET /health HTTP/1.1" 200', None, None)
        assert HealthCheckFilter().filter(record) is False

    def test_probe_hits_are_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import logging

        from gunicorn_config import HealthCheckFilter

        monkeypatch.setenv("LOG_LEVEL", "info")
        record = logging.LogRecord(
            "gunicorn.access", logging.INFO, "", 0, 'GET /probe/liveness HTTP/1.1" 200', None, None
        )
        assert HealthCheckFilter().filter(record) is False

    def test_other_requests_are_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import logging

        from gunicorn_config import HealthCheckFilter

        monkeypatch.setenv("LOG_LEVEL", "info")
        record = logging.LogRecord("gunicorn.access", logging.INFO, "", 0, 'POST /watchdog HTTP/1.1" 200', None, None)
        assert HealthCheckFilter().filter(record) is True
