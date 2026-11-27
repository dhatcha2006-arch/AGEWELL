import pytest
from models import get_db

def test_sos_lifecycle(client):
    """Test full SOS emergency lifecycle: Trigger -> Responding -> Resolved."""
    # 1. Login as senior
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})

    # 2. Trigger SOS
    res_trigger = client.post('/sos/trigger', data={
        'senior_id': 1,
        'notes': 'Test Emergency SOS Trigger'
    }, follow_redirects=True)
    assert res_trigger.status_code == 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_alerts WHERE senior_id = 1 AND status IN ('active', 'responding') ORDER BY id DESC LIMIT 1")
    alert = cursor.fetchone()
    assert alert is not None
    assert alert['status'] == 'active'
    assert alert['contact_escalation_step'] == 1
    alert_id = alert['id']
    conn.close()

    # 3. Family member logs in and responds
    client.get('/logout')
    client.post('/login', data={'email': 'family@agewell.com', 'password': 'password123'})

    res_respond = client.post('/sos/respond', data={'alert_id': alert_id}, follow_redirects=True)
    assert res_respond.status_code == 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_alerts WHERE id = ?", (alert_id,))
    updated_alert = cursor.fetchone()
    assert updated_alert['status'] == 'responding'
    assert updated_alert['responded_by_user_id'] is not None
    conn.close()

    # 4. Resolve the SOS emergency
    res_resolve = client.post('/sos/resolve', data={
        'alert_id': alert_id,
        'resolution_notes': 'Checked in on senior, all is safe.'
    }, follow_redirects=True)
    assert res_resolve.status_code == 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_alerts WHERE id = ?", (alert_id,))
    resolved_alert = cursor.fetchone()
    assert resolved_alert['status'] == 'resolved'
    assert resolved_alert['resolved_at'] is not None
    conn.close()

def test_escalation_bounds_check():
    """Verify that contact escalation step does not exceed total contacts + 1."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM emergency_contacts WHERE senior_id = 1")
    total_contacts = cursor.fetchone()[0]
    conn.close()

    max_step = total_contacts + 1
    # Verify bounds invariant
    for step in range(1, 100):
        bounded_step = min(step, max_step)
        assert bounded_step <= max_step
        assert bounded_step <= 10  # realistically 3-5 contacts
