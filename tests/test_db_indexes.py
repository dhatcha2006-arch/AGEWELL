import pytest
from models import get_db, init_db

def test_sqlite_foreign_keys_enabled():
    """Verify that SQLite foreign keys pragma is active."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys")
    fk_status = cursor.fetchone()[0]
    conn.close()
    assert fk_status == 1

def test_performance_indexes_created():
    """Verify that strategic query indexes exist in sqlite_master."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = [row[0] for row in cursor.fetchall()]
    conn.close()

    expected_indexes = [
        'idx_alerts_senior_status',
        'idx_meds_senior_active',
        'idx_medlogs_senior_date',
        'idx_checkins_senior_date',
        'idx_messages_participants',
        'idx_notifications_user_read'
    ]

    for idx in expected_indexes:
        assert idx in indexes, f"Index {idx} was not found in sqlite_master"
