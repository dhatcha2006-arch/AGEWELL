import pytest
from datetime import datetime, timedelta, date
from scheduler import check_missed_medicines
from models import get_db

def test_medication_grace_window_logic():
    """Verify that medication is not flagged missed during grace period and is flagged after."""
    conn = get_db()
    cursor = conn.cursor()
    today_str = date.today().strftime('%Y-%m-%d')
    
    # Insert test medicine scheduled for 35 minutes ago
    now = datetime.now()
    past_time_str = (now - timedelta(minutes=35)).strftime('%H:%M')
    
    cursor.execute("""
        INSERT INTO medicines (senior_id, name, dose, timings, instructions, is_active)
        VALUES (1, 'Test Cardio Pill', '5mg', ?, 'Test grace window', 1)
    """, (past_time_str,))
    med_id = cursor.lastrowid
    conn.commit()

    # Run check
    check_missed_medicines()

    # Verify log entry was auto-created as 'missed'
    cursor.execute("""
        SELECT status FROM medicine_logs
        WHERE medicine_id = ? AND scheduled_date = ? AND scheduled_time = ?
    """, (med_id, today_str, past_time_str))
    log = cursor.fetchone()
    assert log is not None
    assert log['status'] == 'missed'

    # Clean up test medicine
    cursor.execute("DELETE FROM medicine_logs WHERE medicine_id = ?", (med_id,))
    cursor.execute("DELETE FROM medicines WHERE id = ?", (med_id,))
    conn.commit()
    conn.close()
