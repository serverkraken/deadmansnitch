import time
import logging
import threading
from app.domain.watchdog_state import WatchdogState

logger = logging.getLogger("watchdog_service")


class WatchdogMonitor:
    """Monitor thread that checks watchdog status and sends notifications"""

    def __init__(self, watchdog_service, notifier, config):
        self.watchdog_service = watchdog_service
        self.notifier = notifier
        self.config = config
        self.thread = None

    def start(self):
        """Start the monitor thread"""
        if self.thread is not None and self.thread.is_alive():
            logger.info("Monitor thread already running")
            return

        self.thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.thread.start()
        logger.info("Started watchdog monitor thread")

    def _run_monitor(self):
        """Run the monitor loop"""
        logger.info("Starting watchdog monitor loop")

        # Add a startup grace period to allow watchdog messages to arrive
        startup_time = time.time()
        startup_grace_period = self.config.watchdog_timeout

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

                # Get current state (with lock in service)
                service = self.watchdog_service
                service.state = service.repository.load()
                with service.state_lock:
                    last_watchdog_time = service.state.last_watchdog_time
                    last_status_notification = service.state.last_status_notification
                    last_alert_notification = service.state.last_alert_notification
                    current_status = service.state.status

                time_since_last = current_time - last_watchdog_time
                time_since_last_notification = current_time - last_status_notification
                time_since_last_alert = current_time - last_alert_notification

                # Check for watchdog timeout
                if time_since_last > self.config.watchdog_timeout:
                    logger.debug(
                        f"time_since_last ({time_since_last}) > watchdog_timeout ({self.config.watchdog_timeout})"
                    )

                    # Case 1: First alert
                    if current_status != "alert":
                        logger.debug("Setting alert state")
                        last_received = ""

                        with service.state_lock:
                            service.state.set_alert_status()
                            service.state.update_alert_notification()
                            last_received = WatchdogState.format_timestamp(
                                service.state.last_watchdog_time
                            )

                        # Save state
                        service.repository.save(service.state)

                        # Send notification
                        self.notifier.send_alert(time_since_last, last_received)

                    # Case 2: Repeat alert
                    elif time_since_last_alert >= self.config.alert_resend_interval:
                        logger.debug("Resending alert notification")
                        last_received = WatchdogState.format_timestamp(
                            last_watchdog_time
                        )

                        with service.state_lock:
                            service.state.update_alert_notification()

                        # Save state
                        service.repository.save(service.state)

                        # Send notification
                        self.notifier.send_repeated_alert(
                            time_since_last, last_received
                        )

                # Send daily status update if everything is ok
                elif current_status == "ok" and time_since_last_notification >= 86400:
                    logger.debug("Sending daily status update")
                    last_received = WatchdogState.format_timestamp(last_watchdog_time)

                    with service.state_lock:
                        service.state.update_status_notification()

                    # Save state
                    service.repository.save(service.state)

                    # Send notification
                    self.notifier.send_status_update(last_received)

                # Sleep for a while
                sleep_time = max(30, int(self.config.watchdog_timeout / 10))
                logger.debug(f"Monitor sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in watchdog monitor thread: {e}")
                time.sleep(30)  # Sleep on error, then continue
