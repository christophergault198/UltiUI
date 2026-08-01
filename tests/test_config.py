"""Tests for config.get_secret_key(), which guards against the app ever
running with a known/predictable session-signing key (see security fix:
forged-session-cookie vulnerability from the old hardcoded default key).
"""
import importlib

import config as config_module


def test_get_secret_key_generates_and_persists_when_missing(isolated_env):
    importlib.reload(config_module)

    key1 = config_module.get_secret_key()
    assert key1
    assert key1 != config_module._LEGACY_INSECURE_SECRET_KEY

    # A second call within the same process must return the *same* key
    # (it should have been persisted, not regenerated).
    key2 = config_module.get_secret_key()
    assert key2 == key1

    with open(config_module.get_env_path()) as f:
        content = f.read()
    assert f'ULTIUI_SECRET_KEY={key1}' in content


def test_get_secret_key_replaces_legacy_default(isolated_env, monkeypatch):
    importlib.reload(config_module)
    monkeypatch.setenv('ULTIUI_SECRET_KEY', config_module._LEGACY_INSECURE_SECRET_KEY)

    key = config_module.get_secret_key()

    assert key != config_module._LEGACY_INSECURE_SECRET_KEY
    assert len(key) >= 32


def test_get_secret_key_keeps_a_real_configured_key(isolated_env, monkeypatch):
    importlib.reload(config_module)
    monkeypatch.setenv('ULTIUI_SECRET_KEY', 'a-real-configured-value')

    assert config_module.get_secret_key() == 'a-real-configured-value'


def test_generated_keys_are_not_reused_across_installs(isolated_env, monkeypatch):
    importlib.reload(config_module)
    key_a = config_module.get_secret_key()

    # Simulate a fresh install in another empty directory: a real second
    # install would be a separate process with no ULTIUI_SECRET_KEY set.
    other_dir = isolated_env / 'other-install'
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    monkeypatch.delenv('ULTIUI_SECRET_KEY', raising=False)

    key_b = config_module.get_secret_key()

    assert key_a != key_b
