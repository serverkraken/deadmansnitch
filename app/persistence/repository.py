from abc import ABC, abstractmethod

class WatchdogRepository(ABC):
    """Abstract repository for persisting watchdog state"""
    
    @abstractmethod
    def load(self):
        """Load watchdog state from storage"""
        pass
        
    @abstractmethod
    def save(self, state):
        """Save watchdog state to storage"""
        pass