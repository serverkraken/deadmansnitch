import time

from app.domain.watchdog_state import WatchdogState


class TestWatchdogState:
    def test_initialization(self) -> None:
        state = WatchdogState()
        assert state.status == "initializing"
        assert state.last_watchdog_time == 0
        assert state.total_received == 0

    def test_from_dict_empty(self) -> None:
        state = WatchdogState()
        # Should return self unchanged
        assert state.from_dict(None) is state
        assert state.from_dict({}) is state

    def test_time_calculations(self) -> None:
        state = WatchdogState()
        current_time = time.time()

        state.last_status_notification = current_time - 100
        state.last_alert_notification = current_time - 200

        # Allow small delta
        assert abs(state.time_since_last_status_notification() - 100) < 1.0
        assert abs(state.time_since_last_alert_notification() - 200) < 1.0

    def test_record_watchdog_alert(self) -> None:
        state = WatchdogState()
        alert_data = {
            "labels": {"alertname": "Watchdog"},
            "status": "firing",
            "annotations": {"summary": "test", "description": "desc"},
        }
        state.record_watchdog_alert(alert_data)
        assert state.status == "ok"
        assert state.last_watchdog_details["alertname"] == "Watchdog"
        assert state.last_watchdog_time > 0

    def test_record_invalid_alert(self) -> None:
        state = WatchdogState()
        state.record_invalid_alert()
        assert state.invalid_received == 1
        assert state.total_received == 1

    def test_update_notifications(self) -> None:
        state = WatchdogState()
        state.update_status_notification()
        assert state.last_status_notification > 0

        state.update_alert_notification()
        assert state.last_alert_notification > 0

    def test_set_alert_status(self) -> None:
        state = WatchdogState()
        state.set_alert_status()
        assert state.status == "alert"

    def test_format_timestamp(self) -> None:
        assert WatchdogState.format_timestamp(0) == "never"
        assert WatchdogState.format_timestamp(1700000000) == "2023-11-14 22:13:20"
