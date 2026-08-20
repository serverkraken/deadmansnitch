import logging
import os
import threading
import time
from typing import Optional

from app.config import Config
from app.domain.watchdog_state import WatchdogState
from app.notifications.notifier import Notifier
from app.services.watchdog_service import WatchdogService

logger = logging.getLogger("watchdog_monitor")


class WatchdogMonitor:
    """Monitor thread that checks watchdog status and sends notifications"""

    HEARTBEAT_FILENAME = "monitor_heartbeat"
    # Minimum wait before retrying a notification send that just failed
    SEND_RETRY_INTERVAL = 30.0
    DAILY_STATUS_INTERVAL = 86400.0

    def __init__(self, watchdog_service: WatchdogService, notifier: Notifier, config: Config) -> None:
        self.watchdog_service = watchdog_service
        self.notifier = notifier
        self.config = config
        self.thread: Optional[threading.Thread] = None
        # In-memory delivery markers: the source of truth is the persisted
        # state, but if persistence breaks (full disk, read-only fs) these
        # keep the monitor from re-sending an already-delivered alert
        self._alert_active = False
        self._last_alert_sent = 0.0
        self._last_status_sent = 0.0
        self._last_failed_send = 0.0

    def start(self) -> None:
        """Start the monitor thread"""
        if self.thread is not None and self.thread.is_alive():
            logger.info("Monitor thread already running")
            return

        self.thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.thread.start()
        logger.info("Started watchdog monitor thread")

    @property
    def heartbeat_path(self) -> str:
        return os.path.join(self.watchdog_service.repository.data_dir, self.HEARTBEAT_FILENAME)

    def _write_heartbeat(self, now: float) -> None:
        """Write a heartbeat timestamp so probes in other processes can
        verify the monitor is alive (thread introspection cannot cross the
        gunicorn master/worker boundary)"""
        try:
            with open(self.heartbeat_path, "w") as f:
                f.write(str(now))
        except OSError as e:
            logger.warning(f"Could not write monitor heartbeat: {e}")

    def _tick(self, now: float) -> None:
        """Run one monitor iteration.

        Reads a state snapshot without holding locks, performs notification
        network I/O outside any lock, and only records a notification as
        delivered after the send succeeded.
        """
        state = self.watchdog_service.repository.load()
        time_since_last = now - state.last_watchdog_time
        in_alert = state.status == "alert" or self._alert_active
        effective_last_alert = max(state.last_alert_notification, self._last_alert_sent)
        effective_last_status = max(state.last_status_notification, self._last_status_sent)

        if time_since_last > self.config.watchdog_timeout:
            if now - self._last_failed_send < self.SEND_RETRY_INTERVAL:
                return
            last_received = WatchdogState.format_timestamp(state.last_watchdog_time)

            # Case 1: First alert
            if not in_alert:
                if self.notifier.send_alert(time_since_last, last_received):
                    self._alert_active = True
                    self._last_alert_sent = now
                    self._persist_alert_notification(now)
                else:
                    self._last_failed_send = now
                    logger.error("Failed to deliver watchdog alert - will retry")

            # Case 2: Repeat alert
            elif now - effective_last_alert >= self.config.alert_resend_interval:
                if self.notifier.send_repeated_alert(time_since_last, last_received):
                    self._alert_active = True
                    self._last_alert_sent = now
                    self._persist_alert_notification(now)
                else:
                    self._last_failed_send = now
                    logger.error("Failed to deliver repeated watchdog alert - will retry")

        else:
            self._alert_active = False

            # Send daily status update if everything is ok
            if state.status == "ok" and now - effective_last_status >= self.DAILY_STATUS_INTERVAL:
                last_received = WatchdogState.format_timestamp(state.last_watchdog_time)
                if self.notifier.send_status_update(last_received):
                    self._last_status_sent = now
                    self._persist_status_notification()

    def _persist_alert_notification(self, now: float) -> None:
        """Best-effort persistence of the delivered alert; the in-memory
        markers cover the case where the state file cannot be written"""
        try:
            with self.watchdog_service.atomic_update() as state:
                # Re-check under the lock: a ping may have arrived meanwhile
                if now - state.last_watchdog_time > self.config.watchdog_timeout:
                    state.set_alert_status()
                    state.update_alert_notification()
        except Exception as e:
            logger.error(f"Could not persist alert notification state: {e} - relying on in-memory tracking")

    def _persist_status_notification(self) -> None:
        try:
            with self.watchdog_service.atomic_update() as state:
                state.update_status_notification()
        except Exception as e:
            logger.error(f"Could not persist status notification state: {e} - relying on in-memory tracking")

    def _run_monitor(self) -> None:
        """Run the monitor loop"""
        logger.info("Starting watchdog monitor loop")
        # Ensure service is initialized; a failure (e.g. read-only filesystem)
        # must not kill the monitor - alerting still works read-only
        try:
            if self.watchdog_service.state is None:
                self.watchdog_service.initialize()
        except Exception as e:
            logger.error(f"Service initialization failed: {e} - monitor continues read-only")

        logger.debug(f"Monitor running with service instance {id(self.watchdog_service)}")

        # Add a startup grace period to allow watchdog messages to arrive
        startup_time = time.time()
        startup_grace_period = float(self.config.watchdog_timeout)

        while True:
            try:
                current_time = time.time()
                self._write_heartbeat(current_time)

                # Skip timeout checks during grace period after startup
                if current_time - startup_time < startup_grace_period:
                    logger.debug(
                        f"In startup grace period ({int(current_time - startup_time)} / {startup_grace_period} seconds)"
                    )
                    time.sleep(30)
                    continue

                self._tick(current_time)

                # Sleep for a while
                sleep_time = 1.0
                logger.debug(f"Monitor sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in watchdog monitor thread: {e}")
                time.sleep(5.0)  # Bei Fehlern kürzere Wartezeit
