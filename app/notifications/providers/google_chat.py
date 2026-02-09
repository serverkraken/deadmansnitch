import logging

import requests

from app.notifications.providers.base_provider import NotificationProvider

logger = logging.getLogger("watchdog_service")


class GoogleChatProvider(NotificationProvider):
    """Google Chat notification provider implementation"""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def name(self) -> str:
        return "Google Chat"

    def send(self, message: str) -> bool:
        """Send a notification to Google Chat"""
        if not self.webhook_url:
            logger.error("GOOGLE_CHAT_WEBHOOK_URL environment variable is not set.")
            return False

        headers = {"Content-Type": "application/json; charset=UTF-8"}
        data = {"text": message}

        try:
            response = requests.post(self.webhook_url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                logger.info("Notification sent successfully")
                logger.debug(f"Notification content: {message}")
                return True
            else:
                logger.error(f"Failed to send notification. Status code: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Exception sending notification: {e}")
            return False
