import os
import json
import pytest
from app.persistence.file_repository import FileWatchdogRepository
from app.domain.watchdog_state import WatchdogState

class TestFileWatchdogRepository:

    def test_ensure_data_directory(self, temp_data_dir: str) -> None:
        """Test that data directory is created if missing"""
        new_dir = os.path.join(temp_data_dir, "new_subdir")
        repo = FileWatchdogRepository(new_dir, "test.json")
        assert os.path.exists(new_dir)

    def test_save_and_load(self, repository: FileWatchdogRepository) -> None:
        """Test basic save and load operations"""
        state = WatchdogState()
        state.status = "ok"
        state.total_received = 42
        state.last_watchdog_time = 123456789.0
        
        success = repository.save(state)
        assert success is True
        
        loaded_state = repository.load()
        assert loaded_state.status == "ok"
        assert loaded_state.total_received == 42
        assert loaded_state.last_watchdog_time == 123456789.0

    def test_load_non_existent_file(self, temp_data_dir: str) -> None:
        """Test loading when the file doesn't exist (initialization)"""
        repo = FileWatchdogRepository(temp_data_dir, "missing.json")
        state = repo.load()
        assert state.status == "waiting_for_first_alert"
        assert os.path.exists(os.path.join(temp_data_dir, "missing.json"))

    def test_load_corrupted_json(self, temp_data_dir: str) -> None:
        """Test recovery from corrupted JSON file"""
        repo = FileWatchdogRepository(temp_data_dir, "corrupt.json")
        filepath = os.path.join(temp_data_dir, "corrupt.json")
        
        with open(filepath, "w") as f:
            f.write("{ invalid json")
            
        state = repo.load()
        # Should return a default state (last_watchdog_time = 0.0)
        assert state.last_watchdog_time == 0.0

    def test_save_failure_directory_removed(self, temp_data_dir: str) -> None:
        """Test save behavior when directory is read-only or invalid"""
        # Create a subdirectory we can mess with
        sub_dir = os.path.join(temp_data_dir, "bad_dir")
        os.makedirs(sub_dir)
        
        repo = FileWatchdogRepository(sub_dir, "test.json")
        state = WatchdogState()
        
        # Replace directory with a file to cause write error
        os.rmdir(sub_dir)
        with open(sub_dir, "w") as f:
            f.write("now I am a file")
            
        success = repo.save(state)
        assert success is False

    @pytest.mark.parametrize("status", ["ok", "alert", "initializing", "waiting_for_first_alert"])
    def test_save_all_statuses(self, repository: FileWatchdogRepository, status: str) -> None:
        state = WatchdogState()
        state.status = status
        repository.save(state)
        loaded = repository.load()
        assert loaded.status == status
