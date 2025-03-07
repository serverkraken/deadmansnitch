import time
import logging
import threading
from app.domain.watchdog_state import WatchdogState

logger = logging.getLogger("watchdog_service")


class WatchdogService:
    """Core watchdog service implementation (Singleton pattern)"""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, repository=None, notifier=None, config=None):
        """Get the singleton instance of the watchdog service"""
        with cls._lock:
            if cls._instance is None:
                if repository is None or notifier is None or config is None:
                    raise ValueError(
                        "Repository, notifier, and config must be provided when creating instance"
                    )
                cls._instance = cls(repository, notifier, config)
            return cls._instance

    def __init__(self, repository, notifier, config):
        """Initialize the watchdog service"""
        self.repository = repository
        self.notifier = notifier
        self.config = config
        self.state = None
        self.state_lock = threading.Lock()
        self.start_time = time.time()

    def initialize(self):
        """Initialize the service state"""
        self.state = self.repository.load()
        return self

    def validate_watchdog_alert(self, payload):
        """Validate that a received alert is a valid watchdog alert"""
        try:
            if "alerts" not in payload:
                logger.warning("Received payload without 'alerts' key")
                return False

            alerts = payload["alerts"]
            if not alerts or not isinstance(alerts, list):
                logger.warning("Received empty or invalid 'alerts' array")
                return False

            for alert in alerts:
                if "labels" in alert and "alertname" in alert["labels"]:
                    alertname = alert["labels"]["alertname"]
                    status = alert.get("status", "unknown")

                    if (
                        alertname == self.config.expected_alertname
                        and status == "firing"
                    ):
                        logger.info(
                            f"Valid Watchdog alert received: {alertname} (status: {status})"
                        )
                        return alert

            logger.warning("No valid Watchdog alert found in payload")
            return False

        except Exception as e:
            logger.error(f"Error validating watchdog alert: {str(e)}")
            return False

    def process_watchdog_alert(self, payload):
        """Process a received webhook payload"""
        with self.state_lock:
            self.state.total_received += 1

        if not payload:
            with self.state_lock:
                self.state.invalid_received += 1
            logger.warning("Received empty payload")
            return False, "Invalid payload"

        valid_alert = self.validate_watchdog_alert(payload)
        if not valid_alert:
            with self.state_lock:
                self.state.invalid_received += 1
            return False, "Received alert is not a valid watchdog alert"

        # Capture current status before updating
        with self.state_lock:
            current_status = self.state.status

        # Update state with new alert data
        with self.state_lock:
            self.state.record_watchdog_alert(valid_alert)
            # Explicitly update status to 'ok' when we receive a valid watchdog
            self.state.status = "ok"

        # Save updated state
        self.repository.save(self.state)

        # Send recovery notification if we were previously in alert state
        if current_status == "alert":
            self.notifier.send_recovery()

        return True, "Valid watchdog alert processed"

    def get_health_status(self):
        """Get the current health status"""
        current_time = time.time()

        with self.state_lock:
            last_watchdog_time = self.state.last_watchdog_time
            status = self.state.status
            total_received = self.state.total_received
            invalid_received = self.state.invalid_received

        time_since_last = current_time - last_watchdog_time

        return {
            "status": status,
            "last_watchdog_received": WatchdogState.format_timestamp(
                last_watchdog_time
            ),
            "seconds_since_last_watchdog": int(time_since_last),
            "timeout_threshold": self.config.watchdog_timeout,
            "is_healthy": time_since_last <= self.config.watchdog_timeout,
            "total_alerts_received": total_received,
            "invalid_alerts_received": invalid_received,
        }

    def get_detailed_status(self):
        """Get detailed status information"""
        current_time = time.time()

        with self.state_lock:
            state_copy = self.state.to_dict()

        return {
            "current_time": WatchdogState.format_timestamp(current_time),
            "watchdog_state": state_copy,
            "config": {
                "timeout": self.config.watchdog_timeout,
                "expected_alertname": self.config.expected_alertname,
                "has_webhook_url": self.config.google_chat_webhook_url is not None,
                "data_directory": self.config.data_dir,
                "persistence_file": self.config.persistence_file,
                "alert_resend_interval": self.config.alert_resend_interval,
            },
            "uptime": int(current_time - self.start_time),
        }
