import os
import pytest
from scripts.backup_db import perform_backup

def test_perform_database_backup(tmp_path):
    """Test creating an atomic SQLite database backup."""
    backup_file = perform_backup(target_dir=str(tmp_path))
    assert os.path.exists(backup_file)
    assert os.path.getsize(backup_file) > 0
