import os
import secrets

from dotenv import load_dotenv

from logger import logger

load_dotenv()

# Legacy hardcoded value that used to ship as the default secret key. Any
# instance still using this value has a forgeable session cookie and must be
# migrated to a generated key.
_LEGACY_INSECURE_SECRET_KEY = 'your-secret-key-here'


def get_printer_ip():
    return os.getenv('PRINTER_IP', '')


def get_printer_auth():
    return {
        'username': os.getenv('PRINTER_AUTH_USERNAME') or None,
        'password': os.getenv('PRINTER_AUTH_PASSWORD') or None,
        'api_key': os.getenv('PRINTER_API_KEY') or None,
    }


def get_ui_credentials():
    return {
        'username': os.getenv('ULTIUI_USERNAME', 'admin'),
        'password': os.getenv('ULTIUI_PASSWORD', 'admin'),
    }


def get_env_path():
    return os.getenv('ULTIUI_ENV_PATH', '.env')


def _persist_secret_key(key: str) -> None:
    """Write a generated secret key to the .env file so it survives restarts."""
    env_path = get_env_path()
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith('ULTIUI_SECRET_KEY='):
            lines[i] = f'ULTIUI_SECRET_KEY={key}\n'
            found = True
            break
    if not found:
        lines.append(f'ULTIUI_SECRET_KEY={key}\n')
    with open(env_path, 'w') as f:
        f.writelines(lines)


def get_secret_key():
    """Return the session-signing secret key.

    If no key is configured, or the old hardcoded placeholder key is still in
    use, a new random key is generated and persisted to .env. Using a known,
    predictable secret key lets anyone forge an authenticated session cookie,
    so this must never silently fall back to a fixed value.
    """
    key = os.getenv('ULTIUI_SECRET_KEY', '')
    if key and key != _LEGACY_INSECURE_SECRET_KEY:
        return key

    key = secrets.token_hex(32)
    os.environ['ULTIUI_SECRET_KEY'] = key
    try:
        _persist_secret_key(key)
        logger.warning('Generated a new random ULTIUI_SECRET_KEY and saved it to %s', get_env_path())
    except OSError:
        logger.exception('Could not persist generated ULTIUI_SECRET_KEY to disk; a new one will be generated on restart')
    return key
