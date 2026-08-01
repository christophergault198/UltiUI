import asyncio

import requests
from requests.auth import HTTPDigestAuth

from config import get_printer_auth, get_printer_ip
from logger import logger

_printer_session = None


class PrinterResponse:
    def __init__(self, resp: requests.Response):
        self._resp = resp
        self.status = resp.status_code
        self.reason = resp.reason
        self.headers = resp.headers

    async def json(self):
        return self._resp.json()

    async def text(self):
        return self._resp.text

    async def read(self):
        return self._resp.content


class _RequestContextManager:
    def __init__(self, coro):
        self._coro = coro
        self._resp = None

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        self._resp = await self._coro
        return self._resp

    async def __aexit__(self, exc_type, exc, tb):
        if self._resp is not None:
            self._resp._resp.close()
        return False


class _PrinterSession:
    def __init__(self):
        self.closed = False

    def request(self, method, url, **kwargs):
        return _RequestContextManager(self._request(method, url, **kwargs))

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def put(self, url, **kwargs):
        return self.request('PUT', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    async def _request(self, method, url, **kwargs):
        headers = dict(kwargs.pop('headers', None) or {})
        timeout = kwargs.pop('timeout', 15)
        kwargs.setdefault('stream', True)

        def _do():
            auth_config = get_printer_auth()
            if auth_config['api_key']:
                headers.setdefault('X-Api-Key', auth_config['api_key'])
            auth = None
            if auth_config['username']:
                auth = HTTPDigestAuth(auth_config['username'], auth_config['password'] or '')
            return requests.request(method, url, auth=auth, headers=headers, timeout=timeout, **kwargs)

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(None, _do)
        return PrinterResponse(resp)

    async def close(self):
        self.closed = True


async def get_printer_session():
    global _printer_session
    if _printer_session is None or _printer_session.closed:
        _printer_session = _PrinterSession()
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
        content_type = resp.headers.get('Content-Type', '')
        body = await resp.read() if 'gzip' in content_type else await resp.json()
        return resp.status, body


def printer_url(path: str) -> str:
    return f'{get_printer_base_url()}{path}'
