import logging
from typing import List

from app.notifications.message_factory import MessageFactory
from app.notifications.providers.base_provider import NotificationProvider

logger = logging.getLogger("watchdog_service")


class Notifier:
    """Notification service using Observer pattern"""

    def __init__(self) -> None:
        self.providers: List[NotificationProvider] = []

    def add_provider(self, provider: NotificationProvider) -> None:
        """Add a notification provider"""
        self.providers.append(provider)
        logger.info(f"Added notification provider: {provider.name()}")

    def notify_all(self, message: str) -> bool:
        """Send notification to all providers"""
        if not self.providers:
            logger.warning("No notification providers configured")
            return False

        success = False
        for provider in self.providers:
            try:
                if provider.send(message):
                    success = True
            except Exception as e:
                logger.error(f"Error sending notification via {provider.name()}: {e}")

        return success

    def send_alert(self, time_since_last: float, last_received: str) -> bool:
        """Send an initial alert notification"""
        message = MessageFactory.create_alert_message(time_since_last, last_received)
        return self.notify_all(message)

    def send_repeated_alert(self, time_since_last: float, last_received: str) -> bool:
        """Send a repeated alert notification"""
        message = MessageFactory.create_repeated_alert_message(time_since_last, last_received)
        return self.notify_all(message)

    def send_recovery(self) -> bool:
        """Send a recovery notification"""
        message = MessageFactory.create_recovery_message()
        return self.notify_all(message)

    def send_status_update(self, last_received: str) -> bool:
        """Send a status update notification"""
        message = MessageFactory.create_status_message(last_received)
        return self.notify_all(message)
