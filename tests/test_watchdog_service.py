import threading
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.persistence.file_repository import FileWatchdogRepository
from app.services.watchdog_service import WatchdogService
from app.domain.watchdog_state import WatchdogState

class TestWatchdogService:
    
    @pytest.fixture
    def notifier(self) -> MagicMock:
        return MagicMock()

    def test_process_watchdog_alert_valid(self, service: WatchdogService, notifier: MagicMock) -> None:
        """Test processing a valid watchdog alert"""
        payload: Dict[str, Any] = {
            "alerts": [
                {
                    "labels": {"alertname": "Watchdog"},
                    "status": "firing",
                    "annotations": {"summary": "Watchdog alert"}
                }
            ]
        }
        
        success, message = service.process_watchdog_alert(payload)
        
        assert success is True
        assert service.state is not None
        assert service.state.status == "ok"
        assert service.state.total_received == 1

    def test_process_watchdog_alert_empty_list(self, service: WatchdogService) -> None:
        """Test processing payload with empty alerts list (Fix for IndexError)"""
        # This was causing IndexError before fix
        payload: Dict[str, Any] = {"alerts": []}
        
        success, message = service.process_watchdog_alert(payload)
        
        # Should fail validation but NOT raise IndexError
        assert success is False
        assert "Invalid watchdog alert format" in message

    def test_process_watchdog_alert_invalid_alertname(self, service: WatchdogService) -> None:
        """Test processing alert with wrong name"""
        payload: Dict[str, Any] = {
            "alerts": [
                {
                    "labels": {"alertname": "WrongName"},
                    "status": "firing"
                }
            ]
        }
        
        success, message = service.process_watchdog_alert(payload)
        
        assert success is False
        assert "Expected 'Watchdog'" in message

    def test_health_check_timeout(self, service: WatchdogService, mock_config: Config) -> None:
        """Test health check detects timeout"""
        # Simulate last ping was long ago
        state = service.state or WatchdogState()
        state.last_watchdog_time = time.time() - (mock_config.watchdog_timeout + 10)
        state.status = "ok"
        service.repository.save(state)
        
        health = service.get_health_status()
        
        assert health["is_healthy"] is False
        assert health["status"] == "alert"

    def test_concurrent_access(self, service: WatchdogService, notifier: MagicMock) -> None:
        """Test concurrent updates don't crash (basic smoke test for locking)"""
        
        def update_worker() -> None:
            for _ in range(10):
                payload: Dict[str, Any] = {
                    "alerts": [{"labels": {"alertname": "Watchdog"}}]
                }
                service.process_watchdog_alert(payload)
                
        threads: List[threading.Thread] = []
        for _ in range(5):
            t = threading.Thread(target=update_worker)
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        assert service.state is not None
        assert service.state.total_received == 50

    def test_get_instance(self, repository: FileWatchdogRepository, mock_config: Config) -> None:
        """Test singleton behavior of get_instance"""
        WatchdogService._instance = None
        notifier = MagicMock()
        s1 = WatchdogService.get_instance(repository, notifier, mock_config)
        s2 = WatchdogService.get_instance(repository, notifier, mock_config)
        assert s1 is s2

    def test_initialize_with_existing_state(self, repository: FileWatchdogRepository, mock_config: Config) -> None:
        """Test initialization when repository already has state"""
        existing_state = WatchdogState()
        existing_state.total_received = 100
        repository.save(existing_state)
        
        notifier = MagicMock()
        service = WatchdogService(repository, notifier, mock_config)
        service.initialize()
        assert service.state.total_received == 100

    def test_process_watchdog_alert_recovery(self, service: WatchdogService) -> None:
        """Test recovery notification when switching from alert to ok"""
        state = service.state or WatchdogState()
        state.status = "alert"
        service.repository.save(state)
        
        payload = {"alerts": [{"labels": {"alertname": "Watchdog"}}]}
        service.process_watchdog_alert(payload)
        assert service.state.status == "ok"
        service.notifier.send_recovery.assert_called_once()

    def test_get_health_status_initial(self, service: WatchdogService) -> None:
        """Test health status at start"""
        status = service.get_health_status()
        assert status["status"] == "waiting_for_first_alert"

    def test_get_detailed_status(self, service: WatchdogService) -> None:
        """Test detailed status information"""
        state = service.state or WatchdogState()
        state.total_received = 5
        state.status = "ok"
        service.repository.save(state)
        
        status = service.get_detailed_status()
        assert status["status"] == "ok"
        assert status["total_received"] == 5
        assert "config" in status

    def test_initialize_creates_directory(self, repository: FileWatchdogRepository, mock_config: Config) -> None:
        """Test initialize creates data directory if missing"""
        notifier = MagicMock()
        service = WatchdogService(repository, notifier, mock_config)
        with patch("os.path.exists", return_value=False):
            with patch("os.makedirs") as mock_makedirs:
                service.initialize()
                mock_makedirs.assert_called_once()

    def test_health_check_grace_period(self, service: WatchdogService) -> None:
        """Test timeout is ignored during initialization/waiting phase"""
        state = service.state or WatchdogState()
        state.status = "initializing"
        state.last_watchdog_time = time.time() - 1000
        service.repository.save(state)
        
        service.config.watchdog_timeout = 60
        
        status = service.get_health_status()
        assert status["status"] == "initializing"
        assert status["is_healthy"] is False
