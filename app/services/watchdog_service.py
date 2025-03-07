import logging
from threading import Lock

logger = logging.getLogger("watchdog_service")


class WatchdogService:
    """Service for managing watchdog alerts"""

    # Singleton instance
    _instance = None
    _lock = Lock()

    @classmethod
    def get_instance(cls, repository=None, notifier=None, config=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(repository, notifier, config)
            return cls._instance

    def __init__(self, repository, notifier, config):
        """Initialize watchdog service"""
        self.repository = repository
        self.notifier = notifier
        self.config = config
        self.state = None
        # Fügen Sie das fehlende state_lock-Attribut hinzu
        self.state_lock = Lock()

    def initialize(self):
        """Initialize the service state"""
        with self.state_lock:
            self.state = self.repository.load()
        logger.info("Watchdog service initialized")
        return self.state

    def process_watchdog_alert(self, payload):
        """Process an incoming alert from Alertmanager"""
        if payload is None:
            return False, "Invalid payload: None"

        with self.state_lock:
            # Increment total counter
            self.state.total_received += 1

            # Validate watchdog alert format
            if not self._validate_watchdog_alert(payload):
                self.state.record_invalid_alert()
                self.repository.save(self.state)
                return False, "Invalid watchdog alert format"

            # Get the alert
            alert = payload.get("alerts", [{}])[0] if "alerts" in payload else payload

            # Check if it's a watchdog alert
            alertname = alert.get("labels", {}).get("alertname", "")
            if alertname != self.config.expected_alertname:
                logger.warning(f"Received non-watchdog alert: {alertname}")
                self.state.record_invalid_alert()
                self.repository.save(self.state)
                return (
                    False,
                    f"Expected '{self.config.expected_alertname}', got '{alertname}'",
                )

            # Valid watchdog alert received - update state
            was_in_alert = self.state.status == "alert"
            self.state.record_watchdog_alert(alert)
            self.repository.save(self.state)

            # If we were in alert state, send recovery notification
            if was_in_alert:
                logger.info(
                    "Watchdog alert received after previous failure - sending recovery notification"
                )
                self.notifier.send_recovery()

        return True, "Watchdog alert received and processed"

    def check_watchdog_status(self):
        """Check if the watchdog should be in alert state"""
        with self.state_lock:
            if (
                self.state.status == "initializing"
                or self.state.status == "waiting_for_first_alert"
            ):
                # Skip checking on first run
                return False

            time_since_last = self.state.time_since_last_watchdog()

            # If too much time has passed, enter alert state
            if time_since_last > self.config.watchdog_timeout:
                # Only update state if not already in alert
                if self.state.status != "alert":
                    logger.warning(
                        f"Watchdog timeout exceeded: {time_since_last:.1f}s > {self.config.watchdog_timeout}s"
                    )
                    self.state.set_alert_status()
                    self.repository.save(self.state)
                    return True

                # If in alert state, check if we should send another notification
                time_since_notification = (
                    self.state.time_since_last_alert_notification()
                )
                if time_since_notification > self.config.alert_resend_interval:
                    logger.info(
                        f"Sending repeated alert notification after {time_since_notification:.1f}s"
                    )
                    return True

        return False

    def _validate_watchdog_alert(self, payload):
        """Validate the alert has the expected format"""
        # Basic validation for required fields
        if isinstance(payload, dict):
            if "alerts" in payload:
                # Format from Alertmanager
                if isinstance(payload["alerts"], list) and len(payload["alerts"]) > 0:
                    return True
            elif "labels" in payload:
                # Direct alert format
                return True
        return False

    def get_health_status(self):
        """Get system health status - unified approach"""
        with self.state_lock:
            # Calculate health based on current state and timeout
            is_healthy = self.state.status == "ok"

            # Create a consistent health status object
            health_status = {
                "status": self.state.status,
                "is_healthy": is_healthy,
                "last_ping": self.state.last_watchdog_time,
                "last_ping_formatted": self.state.format_timestamp(
                    self.state.last_watchdog_time
                ),
                "time_since_last_ping": self.state.time_since_last_watchdog(),
                "timeout": self.config.watchdog_timeout,
            }

        return health_status

    def get_detailed_status(self):
        """Get detailed system status"""
        with self.state_lock:
            health_status = self.get_health_status()

            # Add more details to the basic health status
            detailed_status = health_status.copy()
            detailed_status.update(
                {
                    "total_received": self.state.total_received,
                    "invalid_received": self.state.invalid_received,
                    "last_watchdog_details": self.state.last_watchdog_details,
                    "last_status_notification": self.state.format_timestamp(
                        self.state.last_status_notification
                    ),
                    "last_alert_notification": self.state.format_timestamp(
                        self.state.last_alert_notification
                    ),
                    "config": {
                        "watchdog_timeout": self.config.watchdog_timeout,
                        "expected_alertname": self.config.expected_alertname,
                        "alert_resend_interval": self.config.alert_resend_interval,
                    },
                }
            )

        return detailed_status
