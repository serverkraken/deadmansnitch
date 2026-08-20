import json
import logging
import os
import time

from app.domain.watchdog_state import WatchdogState
from app.persistence.repository import WatchdogRepository

logger = logging.getLogger("watchdog_service")


class FileWatchdogRepository(WatchdogRepository):
    """File-based implementation of the watchdog repository"""

    def __init__(self, data_dir: str, filename: str, log_interval: float = 300.0) -> None:
        super().__init__(data_dir, filename)
        self.log_interval = log_interval
        self._last_log_time = 0.0
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
        filepath = self.filepath

        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    saved_state = json.load(f)
                    state.from_dict(saved_state)

                current_time = time.time()
                if current_time - self._last_log_time >= self.log_interval:
                    logger.info(
                        f"Loaded watchdog state: Last alert received at "
                        f"{WatchdogState.format_timestamp(state.last_watchdog_time)}"
                    )
                    self._last_log_time = current_time
                else:
                    logger.debug(
                        f"Loaded watchdog state: Last alert received at "
                        f"{WatchdogState.format_timestamp(state.last_watchdog_time)}"
                    )

            except Exception as e:
                # Resetting the timer buys a full extra timeout during which
                # a live outage stays invisible - this must be loud and the
                # evidence must survive for forensics
                logger.critical(
                    f"Watchdog state file corrupt ({e}) - resetting timer; a "
                    f"running outage stays undetected until a full timeout "
                    f"elapses again. Corrupt file preserved as {filepath}.corrupt"
                )
                self._preserve_corrupt_file(filepath)
                state = WatchdogState()
                current_time = time.time()
                state.last_watchdog_time = current_time
                state.last_status_notification = current_time
                state.status = "waiting_for_first_alert"
                # Replace the corrupt file, otherwise every load would reset
                # the timer again and the watchdog could never time out
                self.save(state)
        else:
            # Initialize with current time for new state
            current_time = time.time()
            state.last_watchdog_time = current_time
            state.last_status_notification = current_time
            state.status = "waiting_for_first_alert"
            self.save(state)

        return state

    def _preserve_corrupt_file(self, filepath: str) -> None:
        """Move the corrupt file aside so its content and mtime survive for
        forensics (best effort)"""
        try:
            os.replace(filepath, f"{filepath}.corrupt")
        except OSError as e:
            logger.error(f"Could not preserve corrupt state file: {e}")

    def save(self, state: WatchdogState) -> bool:
        """Save watchdog state to file atomically"""
        try:
            filepath = self.filepath
            tmp_filepath = f"{filepath}.tmp"

            # Write to temp file first
            with open(tmp_filepath, "w") as f:
                json.dump(state.to_dict(), f)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Rename temp file to actual file (atomic operation on POSIX)
            os.replace(tmp_filepath, filepath)
            self._fsync_directory()

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

    def _fsync_directory(self) -> None:
        """Make the rename durable: without an fsync on the directory the
        new directory entry may be lost on power failure (best effort -
        not every filesystem supports it)"""
        try:
            dir_fd = os.open(self.data_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as e:
            logger.debug(f"Directory fsync not possible: {e}")
