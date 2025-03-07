import logging
from threading import RLock  # RLock statt Lock verwenden

logger = logging.getLogger("watchdog_service")


class WatchdogService:
    """Service for managing watchdog alerts"""

    # Singleton instance
    _instance = None
    _lock = RLock()  # RLock für Singleton-Pattern

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
        # RLock verwenden, damit derselbe Thread den Lock mehrfach erwerben kann
        self.state_lock = RLock()

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

        # Zusätzliche Validierung
        if not isinstance(payload, dict):
            return False, "Invalid payload: Not a dictionary"

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
            # Direkter Zugriff auf state innerhalb des Locks, statt get_health_status() aufzurufen
            is_healthy = self.state.status == "ok"

            # Basis-Health-Status erstellen
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

            # Zusätzliche Informationen
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

