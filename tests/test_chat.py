import pytest
import json

def test_chat_view_renders(client):
    """Test that chat view renders with active conversations."""
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})
    response = client.get('/chat')
    assert response.status_code == 200
    assert b'Care Chat & Family Messages' in response.data

def test_send_and_poll_message(client):
    """Test sending an authorized chat message and polling it."""
    # Senior logs in and sends message to Family member (User ID 2)
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})
    
    send_res = client.post('/api/chat/send', 
        data=json.dumps({'receiver_id': 2, 'message': 'Hello Sarah, I am doing great!'}),
        content_type='application/json'
    )
    assert send_res.status_code == 200
    res_data = json.loads(send_res.data)
    assert res_data['success'] is True
    assert res_data['message']['message'] == 'Hello Sarah, I am doing great!'

    # Family member logs in and polls
    client.get('/logout')
    client.post('/login', data={'email': 'family@agewell.com', 'password': 'password123'})
    
    poll_res = client.get('/api/chat/poll/1')
    assert poll_res.status_code == 200
    poll_data = json.loads(poll_res.data)
    assert poll_data['success'] is True
    assert len(poll_data['messages']) >= 1

def test_unauthorized_chat_recipient_blocked(client):
    """Test that messaging an unauthorized recipient is rejected with HTTP 403."""
    client.post('/login', data={'email': 'senior@agewell.com', 'password': 'password123'})
    
    # Try messaging arbitrary invalid/unlinked user id
    res = client.post('/api/chat/send', 
        data=json.dumps({'receiver_id': 99999, 'message': 'Spam attempt'}),
        content_type='application/json'
    )
    assert res.status_code == 403
