import shutil
import tempfile
from typing import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.config import Config
from app.persistence.file_repository import FileWatchdogRepository
from app.services.watchdog_service import WatchdogService


@pytest.fixture
def temp_data_dir() -> Generator[str, None, None]:
    """Create a temporary data directory for tests"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_config(temp_data_dir: str) -> Config:
    """Mock configuration with temp data dir"""
    config = Config.get_instance()
    # Override values for testing
    config.data_dir = temp_data_dir
    config.watchdog_timeout = 60
    config.expected_alertname = "Watchdog"
    config.alert_resend_interval = 300
    return config


@pytest.fixture
def repository(temp_data_dir: str) -> FileWatchdogRepository:
    """File repository using temp dir"""
    return FileWatchdogRepository(temp_data_dir, "watchdog_state.json")


@pytest.fixture
def service(repository: FileWatchdogRepository, mock_config: Config) -> WatchdogService:
    """Watchdog service initialized with repo and mock config"""
    from unittest.mock import MagicMock

    notifier = MagicMock()
    service_instance = WatchdogService(repository, notifier, mock_config)
    service_instance.initialize()
    return service_instance


@pytest.fixture
def app(service: WatchdogService) -> Generator[Flask, None, None]:
    """Flask application fixture"""
    from flask import Flask

    from app.web.routes import init_routes

    app = Flask(__name__)
    app.register_blueprint(init_routes(service))
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Flask test client fixture"""
    return app.test_client()
