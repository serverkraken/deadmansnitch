import logging
import os
import time
import traceback
from typing import Tuple

from app.services.watchdog_monitor import WatchdogMonitor
from app.services.watchdog_service import WatchdogService

logger = logging.getLogger("watchdog_service.kubernetes")


class KubernetesProbes:
    """Handle Kubernetes liveness and readiness probes"""

    # Monitor writes its heartbeat at least every 30s; anything older means
    # the monitor thread is dead or stuck. Deliberately wall-clock: the
    # heartbeat file crosses process (and potentially reboot) boundaries,
    # where monotonic clocks are not comparable
    HEARTBEAT_MAX_AGE = 90.0

    def __init__(self, watchdog_service: WatchdogService) -> None:
        self.watchdog_service = watchdog_service
        # Monotonic: the startup grace window must not stretch or collapse
        # on NTP steps or clock corrections
        self.startup_time: float = time.monotonic()
        # Initial phase: 30 seconds for startup processes
        self.startup_grace_period: int = 30

    def check_liveness(self) -> Tuple[bool, str]:
        """
        Liveness probe checks if the service is running and
        has not entered an undefined state.

        Returns:
            tuple: (is_alive, message)
        """
        try:
            # 1. Check if the service is initialized
            if self.watchdog_service.state is None:
                return False, "Service not initialized"

            # 2. Check if all necessary components are present
            if not self.watchdog_service.repository:
                return False, "Repository not available"

            if not self.watchdog_service.config:
                return False, "Configuration not available"

            # The basic checks pass - service process is alive
            return True, "Service is alive"

        except Exception as e:
            logger.error(f"Liveness check error: {str(e)}\n{traceback.format_exc()}")
            return False, f"Liveness check failed: {str(e)}"

    def is_monitor_thread_running(self) -> Tuple[bool, str]:
        """Check monitor liveness via its heartbeat file.

        The monitor may live in the gunicorn master while probes run in a
        worker, so thread introspection cannot see it - the heartbeat file
        works across process boundaries.
        """
        heartbeat_path = os.path.join(self.watchdog_service.repository.data_dir, WatchdogMonitor.HEARTBEAT_FILENAME)
        try:
            with open(heartbeat_path) as f:
                heartbeat = float(f.read().strip())
        except (OSError, ValueError) as e:
            return False, f"No monitor heartbeat found: {e}"

        age = time.time() - heartbeat
        if age > self.HEARTBEAT_MAX_AGE:
            return False, f"Monitor heartbeat stale ({age:.0f}s old)"
        return True, f"Monitor heartbeat fresh ({age:.0f}s old)"

    def check_readiness(self) -> Tuple[bool, str]:
        """
        Readiness probe checks if the service is ready
        to process requests and function properly.

        Returns:
            tuple: (is_ready, message)
        """
        try:
            # 1. First perform liveness check
            is_alive, message = self.check_liveness()
            if not is_alive:
                return False, f"Not ready: {message}"

            # 2. Check if the startup phase is complete
            if time.monotonic() - self.startup_time < self.startup_grace_period:
                return (
                    False,
                    f"Service still in startup phase "
                    f"({int(time.monotonic() - self.startup_time)}s/{self.startup_grace_period}s)",
                )

            # 3. Check access to file system
            try:
                repo = self.watchdog_service.repository
                test_file_path = os.path.join(repo.data_dir, ".probe_test")
                with open(test_file_path, "w") as f:
                    f.write("probe")
                os.remove(test_file_path)
            except Exception as e:
                logger.warning(f"File system check failed: {str(e)}")
                # An unwritable data dir means state and alerts cannot be
                # persisted - the pod must not receive traffic
                return False, f"File system not writable: {str(e)}"

            # 4. Check if the monitor thread is running (via heartbeat)
            # Only after grace period to allow for startup
            if time.monotonic() - self.startup_time > self.startup_grace_period:
                thread_running, thread_msg = self.is_monitor_thread_running()
                if not thread_running:
                    logger.warning(f"Monitor thread check: {thread_msg}")
                    return False, f"Not ready: Watchdog monitor thread not running ({thread_msg})"

            # 5. Validate that the service is in a valid status
            if self.watchdog_service.state and self.watchdog_service.state.status == "initializing":
                if time.monotonic() - self.startup_time > 60:  # Should be initialized after 60s
                    return False, "Service stuck in initializing state"

            # 6. Check if state lock is functioning
            try:
                with self.watchdog_service.state_lock:
                    pass  # Simple lock test
            except Exception as e:
                return False, f"State lock not functioning: {str(e)}"

            return True, "Service is ready to receive traffic"

        except Exception as e:
            logger.error(f"Readiness check error: {str(e)}\n{traceback.format_exc()}")
            return False, f"Readiness check failed: {str(e)}"
