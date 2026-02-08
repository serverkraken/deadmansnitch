import json
import logging
import os

from app.domain.watchdog_state import WatchdogState
from app.persistence.repository import WatchdogRepository

logger = logging.getLogger("watchdog_service")


class FileWatchdogRepository(WatchdogRepository):
    """File-based implementation of the watchdog repository"""

    def __init__(self, data_dir: str, filename: str) -> None:
        super().__init__(data_dir, filename)
        self._ensure_data_directory()

    def _ensure_data_directory(self) -> None:
        """Ensure the data directory exists"""
        if not os.path.exists(self.data_dir):
            try:
                os.makedirs(self.data_dir, exist_ok=True)
                logger.info(f"Created data directory at {self.data_dir}")
            except Exception as e:
                logger.error(f"Failed to create data directory: {e}")

    def load(self) -> WatchdogState:
        """Load watchdog state from file"""
        state = WatchdogState()
        filepath = os.path.join(self.data_dir, self.filename)

        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    saved_state = json.load(f)
                    state.from_dict(saved_state)
                logger.info(
                    f"Loaded watchdog state: Last alert received at "
                    f"{WatchdogState.format_timestamp(state.last_watchdog_time)}"
                )
            except Exception as e:
                logger.error(f"Error loading watchdog state: {e}")
                # Initialize with current time as fallback
                state.last_watchdog_time = state.last_status_notification = state.last_alert_notification = 0.0
        else:
            # Initialize with current time for new state
            import time

            current_time = time.time()
            state.last_watchdog_time = current_time
            state.last_status_notification = current_time
            state.status = "waiting_for_first_alert"
            self.save(state)

        return state

    def save(self, state: WatchdogState) -> bool:
        """Save watchdog state to file atomically"""
        try:
            filepath = os.path.join(self.data_dir, self.filename)
            tmp_filepath = f"{filepath}.tmp"

            # Write to temp file first
            with open(tmp_filepath, "w") as f:
                json.dump(state.to_dict(), f)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Rename temp file to actual file (atomic operation on POSIX)
            os.replace(tmp_filepath, filepath)

            logger.debug(f"Saved watchdog state to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error saving watchdog state: {e}")
            if "tmp_filepath" in locals() and os.path.exists(tmp_filepath):
                try:
                    os.remove(tmp_filepath)
                except OSError:
                    pass
            return False
