from abc import ABC, abstractmethod

class NotificationProvider(ABC):
    """Abstract base class for notification providers (Strategy pattern)"""
    
    @abstractmethod
    def send(self, message):
        """Send a notification message"""
        pass
    
    @abstractmethod
    def name(self):
        """Get the provider name"""
        pass