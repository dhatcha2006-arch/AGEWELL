import pytest
from app import normalize_email, app

def test_normalize_email():
    """Verify that email addresses are trimmed and lowercased."""
    assert normalize_email('  Senior@AgeWell.COM ') == 'senior@agewell.com'
    assert normalize_email('Doctor@Test.Org') == 'doctor@test.org'
    assert normalize_email('') == ''
    assert normalize_email(None) == ''

def test_max_content_length_configured():
    """Verify that MAX_CONTENT_LENGTH DOS protection is set."""
    assert app.config['MAX_CONTENT_LENGTH'] == 16 * 1024 * 1024
