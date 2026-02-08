from abc import ABC, abstractmethod


class NotificationProvider(ABC):
    """Abstract base class for notification providers (Strategy pattern)"""

    @abstractmethod
    def send(self, message: str) -> bool:
        """Send a notification message"""
        pass

    @abstractmethod
    def name(self) -> str:
        """Get the provider name"""
        pass
