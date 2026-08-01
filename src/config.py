import os

from dotenv import load_dotenv

from logger import logger

load_dotenv()

DEFAULT_SECRET_KEY = 'your-secret-key-here'


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


def get_secret_key():
    key = os.getenv('ULTIUI_SECRET_KEY', DEFAULT_SECRET_KEY)
    if key == DEFAULT_SECRET_KEY:
        logger.warning('Using default SECRET_KEY - generate a random one for production')
    return key


def is_secret_key_default():
    return get_secret_key() == DEFAULT_SECRET_KEY


def get_env_path():
    return os.getenv('ULTIUI_ENV_PATH', '.env')
