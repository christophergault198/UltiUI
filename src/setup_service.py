import os

import aiohttp
from dotenv import load_dotenv

from logger import logger

ENV_PATH = '.env'


def reload_env():
    load_dotenv(ENV_PATH, override=True)


def read_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    for key in ['PRINTER_IP', 'PRINTER_AUTH_USERNAME', 'PRINTER_AUTH_PASSWORD',
                'ULTIUI_USERNAME', 'ULTIUI_PASSWORD', 'ULTIUI_SECRET_KEY']:
        if key not in env or not env[key]:
            val = os.environ.get(key, '')
            if val:
                env[key] = val
    return env


def write_env(updates):
    lines = []
    updated_keys = set()
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        for key, value in updates.items():
            if stripped.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                updated_keys.add(key)
    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f'{key}={value}\n')
        os.environ[key] = value
    with open(ENV_PATH, 'w') as f:
        f.writelines(lines)
    logger.info('Updated .env with keys: %s', list(updates.keys()))


async def request_auth(printer_ip, application='UltiUI', user='admin'):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f'http://{printer_ip}/api/v1/auth/request',
            data={'application': application, 'user': user}
        ) as response:
            if response.status == 200:
                return await response.json()
            return None


async def check_auth(printer_ip, auth_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f'http://{printer_ip}/api/v1/auth/check/{auth_id}'
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('message')
            return None


def save_auth(id, key):
    write_env({
        'PRINTER_AUTH_USERNAME': id,
        'PRINTER_AUTH_PASSWORD': key,
    })


def save_printer_ip(ip):
    write_env({'PRINTER_IP': ip})


def get_status():
    env = read_env()
    return {
        'printer_configured': bool(env.get('PRINTER_IP')),
        'printer_ip': env.get('PRINTER_IP', ''),
        'auth_configured': bool(env.get('PRINTER_AUTH_USERNAME')) and bool(env.get('PRINTER_AUTH_PASSWORD')),
        'login_username': env.get('ULTIUI_USERNAME', 'admin'),
    }


def reset_printer_auth():
    write_env({
        'PRINTER_AUTH_USERNAME': '',
        'PRINTER_AUTH_PASSWORD': '',
    })


def reset_all():
    write_env({
        'PRINTER_IP': '',
        'PRINTER_AUTH_USERNAME': '',
        'PRINTER_AUTH_PASSWORD': '',
        'ULTIUI_USERNAME': 'admin',
        'ULTIUI_PASSWORD': 'admin',
        'ULTIUI_SECRET_KEY': 'your-secret-key-here',
    })
