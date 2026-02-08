import os
from unittest.mock import MagicMock, patch

from flask import Flask

from app import create_app
from app.config import Config
from app.notifications.providers.google_chat import GoogleChatProvider


class TestAppInit:
    @patch("app.WatchdogMonitor")
    @patch("app.WatchdogService")
    @patch("app.Notifier")
    @patch("app.FileWatchdogRepository")
    def test_create_app_basic(
        self,
        mock_repo_cls: MagicMock,
        mock_notifier_cls: MagicMock,
        mock_service_cls: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Test basic app creation with default configuration"""
        # Setup mocks
        mock_service_instance = mock_service_cls.get_instance.return_value

        with patch.dict(
            os.environ,
            {"DATA_DIR": "/tmp/test_data", "PERSISTENCE_FILE": "watchdog.json", "WATCHDOG_TIMEOUT_SECONDS": "60"},
            clear=True,
        ):
            # Ensure Config singleton is reset or updated
            Config._instance = None

            app = create_app()

            assert isinstance(app, Flask)
            assert mock_monitor_cls.called  # Should start monitor by default (dev/test env)

            # Verify dependencies initialization
            mock_repo_cls.assert_called_once()
            mock_notifier_cls.assert_called_once()
            mock_service_cls.get_instance.assert_called_once()
            mock_service_instance.initialize.assert_called_once()

    @patch("app.WatchdogMonitor")
    @patch("app.WatchdogService")
    @patch("app.Notifier")
    @patch("app.FileWatchdogRepository")
    def test_create_app_with_google_chat(
        self,
        mock_repo_cls: MagicMock,
        mock_notifier_cls: MagicMock,
        mock_service_cls: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Test app creation with Google Chat configured"""
        mock_notifier_instance = mock_notifier_cls.return_value

        with patch.dict(os.environ, {"GOOGLE_CHAT_WEBHOOK_URL": "https://chat.googleapis.com/..."}):
            Config._instance = None
            create_app()

            # Verify provider was added
            mock_notifier_instance.add_provider.assert_called()
            args, _ = mock_notifier_instance.add_provider.call_args
            assert isinstance(args[0], GoogleChatProvider)

    @patch("app.WatchdogMonitor")
    @patch("app.WatchdogService")
    @patch("app.Notifier")
    @patch("app.FileWatchdogRepository")
    def test_create_app_standalone_mode(
        self,
        mock_repo_cls: MagicMock,
        mock_notifier_cls: MagicMock,
        mock_service_cls: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Test app creation in standalone mode (starts monitor)"""
        # The condition in __init__.py is: if not os.environ.get("RUNNING_IN_GUNICORN", ""):
        # So we need to ensure RUNNING_IN_GUNICORN is NOT set.
        # However, pytest environment might be tricky.

        with patch.dict(os.environ, {}, clear=True):
            Config._instance = None  # Reset config

            create_app()

            mock_monitor_cls.assert_called_once()
            mock_monitor_cls.return_value.start.assert_called_once()

    @patch("app.WatchdogMonitor")
    @patch("app.WatchdogService")
    @patch("app.Notifier")
    @patch("app.FileWatchdogRepository")
    def test_create_app_gunicorn_mode(
        self,
        mock_repo_cls: MagicMock,
        mock_notifier_cls: MagicMock,
        mock_service_cls: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """Test app creation in Gunicorn mode (skips monitor start)"""
        with patch.dict(os.environ, {"RUNNING_IN_GUNICORN": "true"}):
            Config._instance = None

            create_app()

            mock_monitor_cls.assert_not_called()
