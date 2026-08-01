import functools

from aiohttp import web

from config import get_printer_ip
from logger import logger


def require_printer_ip(handler):
    @functools.wraps(handler)
    async def wrapper(request):
        ip = get_printer_ip()
        if not ip:
            return web.json_response({'error': 'Printer IP not configured'}, status=400)
        return await handler(request)
    return wrapper


def error_handler(handler):
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


def route( method: str, path: str):
    def decorator(handler):
        handler._route = (method, path)
        return handler
    return decorator


def register_routes(app, handler):
    routes = web.RouteTableDef()

    for name in dir(handler):
        fn = getattr(handler, name)
        if hasattr(fn, '_route'):
            method, path = fn._route

            wrapped = error_handler(fn)
            if hasattr(fn, '_skip_auth'):
                wrapped._skip_auth = True

            routes._append(web.RouteDef(method.upper(), path, wrapped, {}))

    app.router.add_routes(routes)
    return routes
