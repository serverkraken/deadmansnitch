import os
import logging
from unittest.mock import patch
from app.config import Config

class TestConfig:
    
    def test_singleton(self) -> None:
        """Test that Config is a singleton"""
        # Clear singleton for testing if it exists
        Config._instance = None
        c1 = Config.get_instance()
        c2 = Config.get_instance()
        assert c1 is c2
        assert Config._instance is c1

    def test_default_values(self) -> None:
        """Test default values when no environment variables are set"""
        Config._instance = None
        with patch.dict(os.environ, {}, clear=True):
            config = Config.get_instance()
            # Note: app/config.py defaults for log_level_name is DEBUG in __init__
            assert config.log_level_name == "DEBUG"
            assert config.data_dir == "/app/data"
            assert config.watchdog_timeout == 3600
            assert config.expected_alertname == "Watchdog"
            assert config.alert_resend_interval == 21600
            assert config.google_chat_webhook_url is None

    def test_env_overrides(self) -> None:
        """Test that environment variables override defaults"""
        Config._instance = None
        env = {
            "LOG_LEVEL": "INFO",
            "DATA_DIR": "/tmp/custom_data",
            "WATCHDOG_TIMEOUT": "60",
            "EXPECTED_ALERTNAME": "CustomWatchdog",
            "ALERT_RESEND_INTERVAL": "300",
            "GOOGLE_CHAT_WEBHOOK_URL": "http://example.com/webhook"
        }
        with patch.dict(os.environ, env):
            config = Config.get_instance()
            assert config.log_level_name == "INFO"
            assert config.data_dir == "/tmp/custom_data"
            assert config.watchdog_timeout == 60
            assert config.expected_alertname == "CustomWatchdog"
            assert config.alert_resend_interval == 300
            assert config.google_chat_webhook_url == "http://example.com/webhook"

    def test_persistence_file_path(self) -> None:
        """Test calculation of persistence file path"""
        Config._instance = None
        with patch.dict(os.environ, {"DATA_DIR": "/foo/bar"}):
            config = Config.get_instance()
            assert config.persistence_file == "/foo/bar/watchdog_state.json"
