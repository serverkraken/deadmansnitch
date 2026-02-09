class MessageFactory:
    """Factory for creating notification messages"""

    @staticmethod
    def create_alert_message(time_since_last: float, last_received: str) -> str:
        """Create an initial alert message"""
        return (
            f"*(ERROR) Watchdog alert - Missing*\n"
            f"Description: No Alertmanager Watchdog messages received in the last {int(time_since_last)} seconds.\n"
            f"Last watchdog message was received at: {last_received}\n"
            f"Summary: Alerting pipeline might be broken or Alertmanager unreachable"
        )

    @staticmethod
    def create_repeated_alert_message(time_since_last: float, last_received: str) -> str:
        """Create a repeated alert message"""
        return (
            f"*(ERROR) Watchdog alert - Still Missing*\n"
            f"Description: No Alertmanager Watchdog messages received in the last {int(time_since_last)} seconds.\n"
            f"Last watchdog message was received at: {last_received}\n"
            f"Summary: Alerting pipeline might still be broken or Alertmanager unreachable"
        )

    @staticmethod
    def create_recovery_message() -> str:
        """Create a recovery message"""
        return (
            "*(INFO) Watchdog recovered*\n"
            "Description: Alertmanager Watchdog messages are being received again.\n"
            "Summary: Alerting pipeline has recovered"
        )

    @staticmethod
    def create_status_message(last_received: str) -> str:
        """Create a status message"""
        return (
            f"*(INFO) Watchdog status - OK*\n"
            f"Description: Alertmanager Watchdog messages are being received normally.\n"
            f"Last received: {last_received}\n"
            f"Summary: Alerting pipeline is functioning correctly"
        )
