import os
import logging

class Config:
    """Centralized configuration management"""
    
    # Singleton instance
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        # Logger configuration
        self.log_level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
        self.log_level = getattr(logging, self.log_level_name, logging.DEBUG)
        
        # Persistence configuration
        self.data_dir = os.getenv("DATA_DIR", "/app/data")
        self.persistence_file = os.path.join(self.data_dir, "watchdog_state.json")
        
        # Notification configuration
        self.google_chat_webhook_url = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
        
        # Watchdog configuration
        self.watchdog_timeout = int(os.getenv("WATCHDOG_TIMEOUT", 3600))  # Default 1 hour
        self.expected_alertname = os.getenv("EXPECTED_ALERTNAME", "Watchdog")
        self.alert_resend_interval = int(os.getenv("ALERT_RESEND_INTERVAL", 21600))  # Default 6 hours
        
    def configure_logging(self):
        logging.basicConfig(
            level=self.log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()],
        )
        logger = logging.getLogger("watchdog_service")
        logger.info(f"Logger initialized with level: {self.log_level_name}")
        return logger