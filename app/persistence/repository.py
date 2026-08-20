import os
from abc import ABC, abstractmethod

from app.domain.watchdog_state import WatchdogState


class StatePersistenceError(Exception):
    """Raised when the watchdog state cannot be persisted"""


class WatchdogRepository(ABC):
    """Abstract repository for persisting watchdog state"""

    def __init__(self, data_dir: str, filename: str) -> None:
        self.data_dir = data_dir
        self.filename = filename

    @property
    def filepath(self) -> str:
        """Canonical path of the state file; derived paths (lock file,
        corrupt backup) must build on this single join"""
        return os.path.join(self.data_dir, self.filename)

    @abstractmethod
    def load(self) -> WatchdogState:
        """Load watchdog state from storage"""
        pass  # pragma: no cover

    @abstractmethod
    def save(self, state: WatchdogState) -> bool:
        """Save watchdog state to storage"""
        pass  # pragma: no cover
