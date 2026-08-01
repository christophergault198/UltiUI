"""Tests for setup_service.py, in particular that reset_all() no longer
reintroduces the known/hardcoded secret key (see config.py fix)."""
import os

import setup_service


def test_write_env_creates_file_and_updates_os_environ(isolated_env):
    setup_service.write_env({'PRINTER_IP': '192.168.1.50'})

    assert os.environ['PRINTER_IP'] == '192.168.1.50'
    with open(setup_service.ENV_PATH) as f:
        assert 'PRINTER_IP=192.168.1.50' in f.read()


def test_write_env_updates_existing_key_in_place(isolated_env):
    setup_service.write_env({'PRINTER_IP': '192.168.1.50'})
    setup_service.write_env({'PRINTER_IP': '10.0.0.5'})

    with open(setup_service.ENV_PATH) as f:
        lines = f.read().splitlines()
    assert lines.count('PRINTER_IP=10.0.0.5') == 1
    assert os.environ['PRINTER_IP'] == '10.0.0.5'


def test_reset_all_does_not_reintroduce_legacy_secret_key(isolated_env):
    setup_service.write_env({
        'PRINTER_IP': '192.168.1.50',
        'ULTIUI_SECRET_KEY': 'a-real-random-secret',
    })

    setup_service.reset_all()

    with open(setup_service.ENV_PATH) as f:
        content = f.read()
    # reset_all() clears printer config and UI credentials...
    assert 'PRINTER_IP=\n' in content
    assert 'ULTIUI_USERNAME=admin' in content
    # ...but must leave the secret key alone rather than writing back the
    # publicly-known placeholder value.
    assert 'a-real-random-secret' in content
    assert 'your-secret-key-here' not in content


def test_save_printer_ip_persists_and_updates_environ(isolated_env):
    setup_service.save_printer_ip('10.10.10.10')
    assert os.environ['PRINTER_IP'] == '10.10.10.10'


def test_get_status_reflects_current_env(isolated_env):
    setup_service.save_printer_ip('10.10.10.10')
    setup_service.save_auth('some-id', 'some-key')

    status = setup_service.get_status()

    assert status['printer_configured'] is True
    assert status['printer_ip'] == '10.10.10.10'
    assert status['auth_configured'] is True
