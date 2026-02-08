from abc import ABC, abstractmethod

from app.domain.watchdog_state import WatchdogState


class WatchdogRepository(ABC):
    """Abstract repository for persisting watchdog state"""

    def __init__(self, data_dir: str, filename: str) -> None:
        self.data_dir = data_dir
        self.filename = filename

    @abstractmethod
    def load(self) -> WatchdogState:
        """Load watchdog state from storage"""
        pass

    @abstractmethod
    def save(self, state: WatchdogState) -> bool:
        """Save watchdog state to storage"""
        pass
