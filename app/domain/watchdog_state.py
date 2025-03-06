import time
from datetime import datetime


class WatchdogState:
    """Domain entity representing the watchdog state"""

    def __init__(self):
        self.last_watchdog_time = 0
        self.last_watchdog_details = {}
        self.status = "initializing"
        self.total_received = 0
        self.invalid_received = 0
        self.last_status_notification = 0
        self.last_alert_notification = 0

    def to_dict(self):
        """Convert state to a dictionary for serialization"""
        return {
            "last_watchdog_time": self.last_watchdog_time,
            "last_watchdog_details": self.last_watchdog_details,
            "status": self.status,
            "total_received": self.total_received,
            "invalid_received": self.invalid_received,
            "last_status_notification": self.last_status_notification,
            "last_alert_notification": self.last_alert_notification,
        }

    def from_dict(self, data):
        """Update state from a dictionary"""
        if not data:
            return self

        self.last_watchdog_time = data.get(
            "last_watchdog_time", self.last_watchdog_time
        )
        self.last_watchdog_details = data.get(
            "last_watchdog_details", self.last_watchdog_details
        )
        self.status = data.get("status", self.status)
        self.total_received = data.get("total_received", self.total_received)
        self.invalid_received = data.get("invalid_received", self.invalid_received)
        self.last_status_notification = data.get(
            "last_status_notification", self.last_status_notification
        )
        self.last_alert_notification = data.get(
            "last_alert_notification", self.last_alert_notification
        )
        return self

    def record_watchdog_alert(self, alert_data):
        """Record a received watchdog alert"""
        current_time = time.time()
        self.last_watchdog_time = current_time
        self.last_watchdog_details = {
            "alertname": alert_data.get("labels", {}).get("alertname", "unknown"),
            "status": alert_data.get("status", "unknown"),
            "summary": alert_data.get("annotations", {}).get(
                "summary", "No summary provided"
            ),
            "description": alert_data.get("annotations", {}).get(
                "description", "No description provided"
            ),
            "received_at": self.format_timestamp(current_time),
        }
        self.status = "ok"
        return self

    def record_invalid_alert(self):
        """Record receipt of an invalid alert"""
        self.invalid_received += 1
        self.total_received += 1
        return self

    def update_status_notification(self):
        """Update the last status notification time"""
        self.last_status_notification = time.time()
        return self

    def update_alert_notification(self):
        """Update the last alert notification time"""
        self.last_alert_notification = time.time()
        return self

    def set_alert_status(self):
        """Set the status to alert"""
        self.status = "alert"
        return self

    def time_since_last_watchdog(self):
        """Calculate time since last watchdog message"""
        return time.time() - self.last_watchdog_time

    def time_since_last_status_notification(self):
        """Calculate time since last status notification"""
        return time.time() - self.last_status_notification

    def time_since_last_alert_notification(self):
        """Calculate time since last alert notification"""
        return time.time() - self.last_alert_notification

    @staticmethod
    def format_timestamp(timestamp):
        """Format a timestamp as a human-readable string"""
        if timestamp == 0:
            return "never"
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
