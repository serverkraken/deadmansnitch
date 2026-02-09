import contextlib
import fcntl
import logging
import os
from threading import RLock
from typing import Any, Dict, Generator, Optional, Tuple

from app.config import Config
from app.domain.watchdog_state import WatchdogState
from app.notifications.notifier import Notifier
from app.persistence.repository import WatchdogRepository

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
                    self.repository.save(self.state)
                finally:
                    fcntl.flock(f_lock, fcntl.LOCK_UN)

    def process_watchdog_alert(self, payload: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """Process an incoming alert from Alertmanager"""
        if payload is None:
            return False, "Invalid payload: None"

        if not isinstance(payload, dict):
            return False, "Invalid payload: Not a dictionary"

        with self.atomic_update() as state:
            # Increment total counter
            state.total_received += 1

            # Validate watchdog alert format
            if not self._validate_watchdog_alert(payload):
                state.record_invalid_alert()
                return False, "Invalid watchdog alert format"

            # Get the alert safely
            alerts = payload.get("alerts", [])
            alert = alerts[0] if (isinstance(alerts, list) and len(alerts) > 0) else payload

            # Check if it's a watchdog alert
            alertname = alert.get("labels", {}).get("alertname", "")
            if alertname != self.config.expected_alertname:
                logger.warning(f"Received non-watchdog alert: {alertname}")
                state.record_invalid_alert()
                return (
                    False,
                    f"Expected '{self.config.expected_alertname}', got '{alertname}'",
                )

            # Valid watchdog alert received - update state
            was_in_alert = state.status == "alert"
            state.record_watchdog_alert(alert)

            # If we were in alert state, send recovery notification
            if was_in_alert:
                logger.info("Watchdog alert received after previous failure - sending recovery notification")
                self.notifier.send_recovery()

        return True, "Watchdog alert received and processed"

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

    def get_health_status(self) -> Dict[str, Any]:
        """Get system health status"""
        # Read-only access doesn't strictly need exclusive lock for consistency
        # but for simplicity and safety we use it to avoid reading partial writes
        with self.atomic_update() as state:
            time_since_last = state.time_since_last_watchdog()

            # Status update if timeout exceeded
            if time_since_last > self.config.watchdog_timeout and state.status != "alert":
                # Check for startup grace period
                # We assume a grace period of 2 * timeout to avoid false positives on restart
                # if we just lost state or it's a fresh start
                if state.status == "initializing" or state.status == "waiting_for_first_alert":
                    # Allow some time for hydration
                    pass
                else:
                    logger.warning(
                        f"Watchdog timeout exceeded in health check: "
                        f"{time_since_last:.1f}s > {self.config.watchdog_timeout}s"
                    )
                    state.set_alert_status()

            # Calculate health
            is_healthy = state.status == "ok"

            health_status = {
                "status": state.status,
                "is_healthy": is_healthy,
                "last_ping": state.last_watchdog_time,
                "last_ping_formatted": state.format_timestamp(state.last_watchdog_time),
                "time_since_last_ping": state.time_since_last_watchdog(),
                "timeout": self.config.watchdog_timeout,
            }

        return health_status

    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed system status"""
        health_status = self.get_health_status()

        with self.atomic_update() as state:
            detailed_status = health_status.copy()
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
