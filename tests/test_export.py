import pytest

def test_export_medications_csv(client):
    """Test exporting senior medication logs as CSV."""
    # Login as senior
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})
    response = client.get('/senior/export/medications')
    assert response.status_code == 200
    assert response.headers.get('Content-Type') == 'text/csv; charset=utf-8'
    assert b'Date,Scheduled Time,Medicine Name,Dosage,Adherence Status' in response.data

def test_export_appointments_csv(client):
    """Test exporting doctor appointments as CSV."""
    # Login as doctor
    client.post('/login', data={'email': 'doctor@agewell.com', 'password': 'password123'})
    response = client.get('/doctor/export/appointments')
    assert response.status_code == 200
    assert response.headers.get('Content-Type') == 'text/csv; charset=utf-8'
    assert b'Date,Time,Patient Name,Title / Reason,Status' in response.data

def test_export_audit_logs_csv(client):
    """Test exporting system audit logs as CSV for administrators."""
    # Login as admin
    client.post('/login', data={'email': 'admin@agewell.com', 'password': 'password123'})
    response = client.get('/admin/export/audit-logs')
    assert response.status_code == 200
    assert response.headers.get('Content-Type') == 'text/csv; charset=utf-8'
    assert b'Timestamp,Actor Name,Action,Target Type,Target ID' in response.data
