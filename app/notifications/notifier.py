import logging
from app.notifications.message_factory import MessageFactory

logger = logging.getLogger("watchdog_service")

class Notifier:
    """Notification service using Observer pattern"""
    
    def __init__(self):
        self.providers = []
        
    def add_provider(self, provider):
        """Add a notification provider"""
        self.providers.append(provider)
        logger.info(f"Added notification provider: {provider.name()}")
        
    def notify_all(self, message):
        """Send notification to all providers"""
        if not self.providers:
            logger.warning("No notification providers configured")
            return False
            
        success = False
        for provider in self.providers:
            if provider.send(message):
                success = True
                
        return success
        
    def send_alert(self, time_since_last, last_received):
        """Send an initial alert notification"""
        message = MessageFactory.create_alert_message(time_since_last, last_received)
        return self.notify_all(message)
        
    def send_repeated_alert(self, time_since_last, last_received):
        """Send a repeated alert notification"""
        message = MessageFactory.create_repeated_alert_message(time_since_last, last_received)
        return self.notify_all(message)
        
    def send_recovery(self):
        """Send a recovery notification"""
        message = MessageFactory.create_recovery_message()
        return self.notify_all(message)
        
    def send_status_update(self, last_received):
        """Send a status update notification"""
        message = MessageFactory.create_status_message(last_received)
        return self.notify_all(message)