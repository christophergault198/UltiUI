"""Tests for auth.py: password hashing and the login open-redirect fix."""
import pytest

import auth


def test_hash_and_verify_password_roundtrip():
    hashed = auth.hash_password('correct horse battery staple')
    assert auth.verify_password('correct horse battery staple', hashed)
    assert not auth.verify_password('wrong password', hashed)


@pytest.mark.parametrize(('username', 'password', 'expected'), [
    ('admin', 'admin', True),
    ('admin', 'wrong-password', False),
    ('someone-else', 'admin', False),
])
async def test_authenticate_against_configured_credentials(monkeypatch, username, password, expected):
    monkeypatch.setattr(auth, 'get_credentials', lambda: {'username': 'admin', 'password': 'admin'})
    assert await auth.authenticate(username, password) is expected


@pytest.mark.parametrize(('raw', 'expected'), [
    ('/print-jobs', '/print-jobs'),
    ('/', '/'),
    ('', '/'),
    (None, '/'),
    # These are the open-redirect payloads the fix needs to block.
    ('//evil.com', '/'),
    ('///evil.com', '/'),
    ('https://evil.com', '/'),
    ('http://evil.com/', '/'),
    ('javascript:alert(1)', '/'),
])
def test_safe_redirect_target_blocks_external_urls(raw, expected):
    assert auth._safe_redirect_target(raw) == expected
