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
        self._tick_interval = float(config.monitor_interval)
        # In-memory delivery markers: the source of truth is the persisted
        # state, but if persistence breaks (full disk, read-only fs) these
        # keep the monitor from re-sending an already-delivered alert
        self._alert_active = False
        # Whether the delivered alert reached the persisted state; if not,
        # the webhook handler can never see status "alert" and the recovery
        # notification becomes the monitor's job
        self._alert_persisted = False
        self._last_alert_sent = 0.0
        self._last_status_sent = 0.0
        # Monotonic timestamp: retry gating must not be affected by NTP
        # steps or clock corrections
        self._last_failed_send = float("-inf")

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
        # A send just failed: wait out the retry interval before attempting
        # any notification again (alert, recovery and status sends alike)
        if time.monotonic() - self._last_failed_send < self.SEND_RETRY_INTERVAL:
            return

        state = self.watchdog_service.repository.load()
        time_since_last = now - state.last_watchdog_time
        in_alert = state.status == "alert" or self._alert_active
        effective_last_alert = max(state.last_alert_notification, self._last_alert_sent)
        effective_last_status = max(state.last_status_notification, self._last_status_sent)

        if time_since_last > self.config.watchdog_timeout:
            last_received = WatchdogState.format_timestamp(state.last_watchdog_time)

            # Case 1: First alert
            if not in_alert:
                if self.notifier.send_alert(time_since_last, last_received):
                    self._alert_active = True
                    self._last_alert_sent = now
                    self._alert_persisted = self._persist_alert_notification(now)
                else:
                    self._record_failed_send()
                    logger.error("Failed to deliver watchdog alert - will retry")

            # Case 2: Repeat alert
            elif now - effective_last_alert >= self.config.alert_resend_interval:
                if self.notifier.send_repeated_alert(time_since_last, last_received):
                    self._alert_active = True
                    self._last_alert_sent = now
                    self._alert_persisted = self._persist_alert_notification(now)
                else:
                    self._record_failed_send()
                    logger.error("Failed to deliver repeated watchdog alert - will retry")

        else:
            self._handle_recovery(state)

            # Send daily status update if everything is ok
            if state.status == "ok" and now - effective_last_status >= self.DAILY_STATUS_INTERVAL:
                last_received = WatchdogState.format_timestamp(state.last_watchdog_time)
                if self.notifier.send_status_update(last_received):
                    self._last_status_sent = now
                    self._persist_status_notification()
                else:
                    self._record_failed_send()
                    logger.error("Failed to deliver status update - will retry")

    def _handle_recovery(self, state: WatchdogState) -> None:
        """Deliver an owed recovery notification once pings are back.

        Owed means: the webhook handler failed its send (recovery_pending
        persisted), a ping raced the alert send (also recovery_pending), or
        the alert never reached persisted state so the webhook handler could
        not know one was delivered (_alert_active without _alert_persisted).
        """
        if state.recovery_pending or (self._alert_active and not self._alert_persisted):
            if self.notifier.send_recovery():
                logger.info("Recovery notification delivered")
                self._alert_active = False
                self._alert_persisted = False
                self._clear_recovery_pending()
            else:
                self._record_failed_send()
                logger.error("Failed to deliver recovery notification - will retry")
        elif self._alert_active:
            # Persisted status was "alert", so the webhook handler already
            # sent the recovery when the ping arrived
            self._alert_active = False
            self._alert_persisted = False

    def _clear_recovery_pending(self) -> None:
        try:
            with self.watchdog_service.atomic_update() as state:
                state.recovery_pending = False
        except Exception as e:
            logger.error(f"Could not clear recovery_pending: {e} - a duplicate recovery may be sent")

    def _record_failed_send(self) -> None:
        self._last_failed_send = time.monotonic()

    def _persist_alert_notification(self, now: float) -> bool:
        """Best-effort persistence of the delivered alert; the in-memory
        markers cover the case where the state file cannot be written"""
        try:
            with self.watchdog_service.atomic_update() as state:
                # Re-check under the lock: a ping may have arrived meanwhile
                if now - state.last_watchdog_time > self.config.watchdog_timeout:
                    state.set_alert_status()
                    state.update_alert_notification()
                else:
                    # The alert was delivered but a ping landed during the
                    # send - a recovery notification is owed
                    state.recovery_pending = True
            return True
        except Exception as e:
            logger.error(f"Could not persist alert notification state: {e} - relying on in-memory tracking")
            return False

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

        # Startup grace period: monotonic so clock steps cannot stretch or
        # collapse it
        startup_grace_period = self._compute_grace_period()
        grace_deadline = time.monotonic() + startup_grace_period
        logger.info(f"Monitor startup grace period: {startup_grace_period:.0f}s")

        while True:
            try:
                current_time = time.time()
                self._write_heartbeat(current_time)

                # Skip timeout checks during grace period after startup
                remaining_grace = grace_deadline - time.monotonic()
                if remaining_grace > 0:
                    logger.debug(f"In startup grace period ({remaining_grace:.0f} seconds remaining)")
                    time.sleep(min(30.0, self._tick_interval))
                    continue

                self._tick(current_time)

                logger.debug(f"Monitor sleeping for {self._tick_interval} seconds")
                time.sleep(self._tick_interval)

            except Exception as e:
                logger.error(f"Error in watchdog monitor thread: {e}")
                time.sleep(5.0)  # Bei Fehlern kürzere Wartezeit

    def _compute_grace_period(self) -> float:
        """Startup grace derived from persisted state: the pipeline gets the
        REMAINDER of its timeout window, not a fresh one - a restart during
        an outage must not push detection out by another full timeout"""
        timeout = float(self.config.watchdog_timeout)
        try:
            state = self.watchdog_service.repository.load()
        except Exception as e:
            logger.error(f"Could not load state for grace period: {e} - using full grace period")
            return timeout
        if state.last_watchdog_time <= 0:
            return timeout
        remaining = timeout - (time.time() - state.last_watchdog_time)
        return max(0.0, min(timeout, remaining))
