import pytest
from datetime import date
from models import get_db

def test_daily_checkin_upsert(client):
    """Test senior daily check-in creates record and repeated check-in updates cleanly."""
    # 1. Login as senior
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})

    # 2. Perform checkin
    res1 = client.post('/senior/checkin', data={'note': 'Morning checkin 1'}, follow_redirects=True)
    assert res1.status_code == 200

    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_checkins WHERE senior_id = 1 AND checkin_date = ?", (today_str,))
    checkin1 = cursor.fetchone()
    assert checkin1 is not None
    assert checkin1['status'] == 'ok'
    conn.close()

    # 3. Perform second checkin on same day (verify ON CONFLICT upsert works without error)
    res2 = client.post('/senior/checkin', data={'note': 'Afternoon update 2'}, follow_redirects=True)
    assert res2.status_code == 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM daily_checkins WHERE senior_id = 1 AND checkin_date = ?", (today_str,))
    count = cursor.fetchone()[0]
    assert count == 1, "Expected exactly 1 checkin row due to UNIQUE(senior_id, checkin_date)"
    conn.close()
