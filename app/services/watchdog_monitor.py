import logging
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

    def __init__(self, watchdog_service: WatchdogService, notifier: Notifier, config: Config) -> None:
        self.watchdog_service = watchdog_service
        self.notifier = notifier
        self.config = config
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the monitor thread"""
        if self.thread is not None and self.thread.is_alive():
            logger.info("Monitor thread already running")
            return

        self.thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.thread.start()
        logger.info("Started watchdog monitor thread")

    def _run_monitor(self) -> None:
        """Run the monitor loop"""
        logger.info("Starting watchdog monitor loop")
        # Ensure service is initialized
        if self.watchdog_service.state is None:
            self.watchdog_service.initialize()

        logger.debug(f"Monitor running with service instance {id(self.watchdog_service)}")

        # Add a startup grace period to allow watchdog messages to arrive
        startup_time = time.time()
        startup_grace_period = float(self.config.watchdog_timeout)

        while True:
            try:
                current_time = time.time()

                # Skip timeout checks during grace period after startup
                if current_time - startup_time < startup_grace_period:
                    logger.debug(
                        f"In startup grace period ({int(current_time - startup_time)} / {startup_grace_period} seconds)"
                    )
                    time.sleep(30)
                    continue

                # Use atomic update to check and update state
                with self.watchdog_service.atomic_update() as state:
                    last_watchdog_time = state.last_watchdog_time
                    last_status_notification = state.last_status_notification
                    last_alert_notification = state.last_alert_notification
                    current_status = state.status

                    time_since_last = current_time - last_watchdog_time
                    time_since_last_notification = current_time - last_status_notification
                    time_since_last_alert = current_time - last_alert_notification

                    logger.debug(
                        f"time_since_last: ({time_since_last}), watchdog_timeout ({self.config.watchdog_timeout})"
                    )

                    # Check for watchdog timeout
                    if time_since_last > self.config.watchdog_timeout:
                        # Case 1: First alert
                        if current_status != "alert":
                            logger.debug("Setting alert state")
                            state.set_alert_status()
                            state.update_alert_notification()
                            last_received = WatchdogState.format_timestamp(state.last_watchdog_time)

                            # Send notification (OUTSIDE lock? No, keep inside to be consistent with state, but quick)
                            # Actually better to send outside lock to avoid holding it during network IO?
                            # But we want to ensure we don't send duplicate alerts if multiple threads race
                            # Holding lock is safer for consistency. Network timeout should be short.
                            self.notifier.send_alert(time_since_last, last_received)

                        # Case 2: Repeat alert
                        elif time_since_last_alert >= self.config.alert_resend_interval:
                            logger.debug("Resending alert notification")
                            state.update_alert_notification()
                            last_received = WatchdogState.format_timestamp(last_watchdog_time)
                            self.notifier.send_repeated_alert(time_since_last, last_received)

                    # Send daily status update if everything is ok
                    elif current_status == "ok" and time_since_last_notification >= 86400:
                        logger.debug("Sending daily status update")
                        state.update_status_notification()
                        last_received = WatchdogState.format_timestamp(last_watchdog_time)
                        self.notifier.send_status_update(last_received)

                # Sleep for a while
                sleep_time = 1.0
                logger.debug(f"Monitor sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in watchdog monitor thread: {e}")
                time.sleep(5.0)  # Bei Fehlern kürzere Wartezeit
