"""Tests for security_headers_middleware: aiohttp sends a `Server:
Python/x.y aiohttp/x.y.z` header on every response by default (even
pre-login), fingerprinting the exact runtime version to anyone who can
reach the app. This middleware overrides it.
"""
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from middleware import security_headers_middleware


async def test_server_header_is_overridden_and_hides_version():
    async def handler(request):
        return web.json_response({'ok': True})

    app = web.Application(middlewares=[security_headers_middleware])
    app.router.add_get('/', handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get('/')
        assert resp.headers['Server'] == 'UltiUI'
        assert 'Python' not in resp.headers['Server']
        assert 'aiohttp' not in resp.headers['Server']
        assert resp.headers['X-Content-Type-Options'] == 'nosniff'
