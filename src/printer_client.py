import aiohttp

from config import get_printer_auth, get_printer_ip
from logger import logger

_printer_session: aiohttp.ClientSession | None = None


def _make_session():
    auth_config = get_printer_auth()
    headers = {}
    if auth_config['api_key']:
        headers['X-Api-Key'] = auth_config['api_key']
    auth = None
    if auth_config['username']:
        auth = aiohttp.BasicAuth(auth_config['username'], auth_config['password'] or '')
    logger.debug('Created printer ClientSession (api_key=%s, basic_auth=%s)',
                 bool(auth_config['api_key']), bool(auth))
    return aiohttp.ClientSession(headers=headers, auth=auth)


async def get_printer_session() -> aiohttp.ClientSession:
    global _printer_session
    if _printer_session is None or _printer_session.closed:
        _printer_session = _make_session()
    return _printer_session


async def close_printer_session():
    global _printer_session
    if _printer_session and not _printer_session.closed:
        await _printer_session.close()
    _printer_session = None


def get_printer_base_url() -> str:
    ip = get_printer_ip()
    return f'http://{ip}' if ip else ''


async def printer_request(path: str, method: str = 'GET', **kwargs) -> tuple[int, any]:
    session = await get_printer_session()
    url = f'{get_printer_base_url()}{path}'
    logger.debug('Printer request: %s %s', method, url)
    async with session.request(method, url, **kwargs) as resp:
        body = await resp.read() if resp.content_type == 'application/gzip' else await resp.json()
        return resp.status, body


def printer_url(path: str) -> str:
    return f'{get_printer_base_url()}{path}'
