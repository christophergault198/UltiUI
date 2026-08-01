import functools

from aiohttp import web

from auth import login_required
from config import get_printer_ip
from logger import logger

# Paths reachable without an authenticated session.
_AUTH_SKIP_PATHS = ('/login', '/logout', '/setup')


@web.middleware
async def auth_middleware(request, handler):
    if request.path in _AUTH_SKIP_PATHS or request.path.startswith('/static/'):
        return await handler(request)
    auth_result = await login_required(request)
    if auth_result is not None:
        return auth_result
    return await handler(request)


def require_printer_ip(handler):
    @functools.wraps(handler)
    async def wrapper(request):
        ip = get_printer_ip()
        if not ip:
            return web.json_response({'error': 'Printer IP not configured'}, status=400)
        return await handler(request)
    return wrapper


def error_handler(handler):
    """Wrap a handler so unexpected exceptions become a JSON 500 response
    instead of an unhandled traceback, without swallowing intentional
    aiohttp HTTP responses/errors (redirects, 404s, etc.)."""
    @functools.wraps(handler)
    async def wrapper(request):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:
            logger.exception('Unhandled error in %s %s', request.method, request.path)
            return web.json_response({'error': str(e)}, status=500)
    return wrapper
