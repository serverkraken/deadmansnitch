import contextlib
import fcntl
import logging
import os
from threading import RLock
from typing import Any, Dict, Generator, List, Optional, Tuple

from app.config import Config
from app.domain.watchdog_state import WatchdogState
from app.notifications.notifier import Notifier
from app.persistence.repository import StatePersistenceError, WatchdogRepository

logger = logging.getLogger("watchdog_service")


class WatchdogService:
    """Service for managing watchdog alerts"""

    # Singleton instance
    _instance: Optional["WatchdogService"] = None
    _lock = RLock()

    @classmethod
    def get_instance(
        cls,
        repository: Optional[WatchdogRepository] = None,
        notifier: Optional[Notifier] = None,
        config: Optional[Config] = None,
    ) -> "WatchdogService":
        with cls._lock:
            if cls._instance is None:
                if repository is None or notifier is None or config is None:
                    raise ValueError("Service must be initialized with repository, notifier and config")
                cls._instance = cls(repository, notifier, config)
            return cls._instance

    def __init__(self, repository: WatchdogRepository, notifier: Notifier, config: Config) -> None:
        """Initialize watchdog service"""
        self.repository = repository
        self.notifier = notifier
        self.config = config
        self.state: Optional[WatchdogState] = None
        # RLock for in-process synchronization
        self.state_lock = RLock()

    def initialize(self) -> None:
        """Initialize the service state"""
        # Ensure data directory exists
        if not os.path.exists(self.repository.data_dir):
            os.makedirs(self.repository.data_dir, exist_ok=True)

        # Load state safely
        with self.atomic_update() as _:
            pass  # Just loading is enough as atomic_update loads state
        logger.info("Watchdog service initialized")

    @contextlib.contextmanager
    def atomic_update(self) -> Generator[WatchdogState, None, None]:
        """Context manager for atomic state updates with file locking"""
        filepath = os.path.join(self.repository.data_dir, self.repository.filename)
        lock_file = f"{filepath}.lock"

        # 1. Acquire process lock
        with self.state_lock:
            # 2. Acquire file lock
            with open(lock_file, "w") as f_lock:
                fcntl.flock(f_lock, fcntl.LOCK_EX)
                try:
                    # 3. Refresh state from disk
                    self.state = self.repository.load()

                    # 4. Yield state for modification
                    yield self.state

                    # 5. Save state to disk
                    if not self.repository.save(self.state):
                        raise StatePersistenceError(f"Failed to save watchdog state to {filepath}")
                finally:
                    fcntl.flock(f_lock, fcntl.LOCK_UN)

    def process_watchdog_alert(self, payload: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """Process an incoming alert from Alertmanager"""
        if payload is None:
            return False, "Invalid payload: None"

        if not isinstance(payload, dict):
            return False, "Invalid payload: Not a dictionary"

        send_recovery = False
        with self.atomic_update() as state:
            # Increment total counter
            state.total_received += 1

            # Validate watchdog alert format
            if not self._validate_watchdog_alert(payload):
                state.record_invalid_alert()
                return False, "Invalid watchdog alert format"

            # Find the watchdog alert (grouped payloads may carry it at any index)
            alert = self._find_watchdog_alert(payload)
            if alert is None:
                received = self._received_alertnames(payload)
                logger.warning(f"Received non-watchdog alert(s): {received}")
                state.record_invalid_alert()
                return (
                    False,
                    f"Expected '{self.config.expected_alertname}', got '{received}'",
                )

            # A resolved watchdog means the alerting pipeline stopped firing -
            # treating it as a liveness ping would reset the timer at exactly
            # the moment the pipeline breaks
            alert_status = str(alert.get("status", payload.get("status", "firing"))).lower()
            if alert_status == "resolved":
                logger.info("Ignoring resolved watchdog alert - not a liveness ping")
                return True, "Resolved watchdog alert ignored"

            # Valid watchdog alert received - update state
            was_in_alert = state.status == "alert"
            state.record_watchdog_alert(alert)
            send_recovery = was_in_alert

        # Network I/O happens after the state locks are released
        if send_recovery:
            logger.info("Watchdog alert received after previous failure - sending recovery notification")
            self.notifier.send_recovery()

        return True, "Watchdog alert received and processed"

    def _find_watchdog_alert(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the first alert matching the expected alertname, if any"""
        for alert in self._candidate_alerts(payload):
            labels = alert.get("labels")
            if isinstance(labels, dict) and labels.get("alertname", "") == self.config.expected_alertname:
                return alert
        return None

    def _candidate_alerts(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        alerts = payload.get("alerts")
        if isinstance(alerts, list):
            return [alert for alert in alerts if isinstance(alert, dict)]
        return [payload]

    def _received_alertnames(self, payload: Dict[str, Any]) -> str:
        names = []
        for alert in self._candidate_alerts(payload):
            labels = alert.get("labels")
            if isinstance(labels, dict):
                names.append(labels.get("alertname", ""))
        return ", ".join(names) if names else "none"

    def _validate_watchdog_alert(self, payload: Any) -> bool:
        """Validate the alert has the expected format"""
        if isinstance(payload, dict):
            if "alerts" in payload:
                # Format from Alertmanager
                alerts = payload["alerts"]
                if isinstance(alerts, list) and len(alerts) > 0:
                    return True
            elif "labels" in payload:
                # Direct alert format
                return True
        return False

    def _load_snapshot(self) -> WatchdogState:
        """Load a read-only state snapshot (save() is atomic via rename)"""
        with self.state_lock:
            state = self.repository.load()
            self.state = state
        return state

    def get_health_status(self) -> Dict[str, Any]:
        """Get system health status (read-only, never mutates persisted state)"""
        state = self._load_snapshot()
        time_since_last = state.time_since_last_watchdog()
        status = state.status

        # Report a derived alert status if the timeout is exceeded, but leave
        # persisting and notifying to the monitor thread - otherwise a health
        # probe would silently skip the monitor's initial-alert branch
        if time_since_last > self.config.watchdog_timeout and status not in (
            "alert",
            "initializing",
            "waiting_for_first_alert",
        ):
            logger.warning(
                f"Watchdog timeout exceeded in health check: {time_since_last:.1f}s > {self.config.watchdog_timeout}s"
            )
            status = "alert"

        return {
            "status": status,
            "is_healthy": status == "ok",
            "last_ping": state.last_watchdog_time,
            "last_ping_formatted": state.format_timestamp(state.last_watchdog_time),
            "time_since_last_ping": time_since_last,
            "timeout": self.config.watchdog_timeout,
        }

    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed system status"""
        detailed_status = self.get_health_status()
        state = self.state or self._load_snapshot()

        detailed_status.update(
            {
                "total_received": state.total_received,
                "invalid_received": state.invalid_received,
                "last_watchdog_details": state.last_watchdog_details,
                "last_status_notification": state.format_timestamp(state.last_status_notification),
                "last_alert_notification": state.format_timestamp(state.last_alert_notification),
                "config": {
                    "watchdog_timeout": self.config.watchdog_timeout,
                    "expected_alertname": self.config.expected_alertname,
                    "alert_resend_interval": self.config.alert_resend_interval,
                },
            }
        )

        return detailed_status
