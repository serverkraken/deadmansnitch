import os
from typing import Optional


class Config:
    """Centralized configuration management"""

    # Singleton instance
    _instance: Optional["Config"] = None

    @classmethod
    def get_instance(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        # Persistence configuration
        self.data_dir: str = os.getenv("DATA_DIR", "/app/data")
        self.persistence_file: str = os.path.join(self.data_dir, "watchdog_state.json")

        # Notification configuration
        self.google_chat_webhook_url: Optional[str] = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")

        # Watchdog configuration
        self.watchdog_timeout: int = int(os.getenv("WATCHDOG_TIMEOUT", "3600"))  # Default 1 hour
        self.expected_alertname: str = os.getenv("EXPECTED_ALERTNAME", "Watchdog")
        self.alert_resend_interval: int = int(os.getenv("ALERT_RESEND_INTERVAL", "21600"))  # Default 6 hours
        self.monitor_interval: float = float(os.getenv("MONITOR_INTERVAL", "15"))  # Monitor tick cadence

        # Web configuration
        # Alertmanager payloads are a few KB; anything bigger is not a ping
        self.max_content_length: int = int(os.getenv("MAX_CONTENT_LENGTH", "65536"))
        # Optional shared secret: when set, POST /watchdog requires
        # "Authorization: Bearer <token>" (Alertmanager: http_config.authorization)
        self.auth_token: Optional[str] = os.getenv("WATCHDOG_AUTH_TOKEN")
