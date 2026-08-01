import os

import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp_session import session_middleware

from auth import get_session_storage, login_handler, login_page, logout_handler
from config import get_secret_key
from event_log_service import EventLogService
from log_manager import LogManager
from logger import logger
from middleware import auth_middleware, security_headers_middleware
from print_jobs_service import PrintJobsService
from printer_client import close_printer_session, get_printer_base_url
from routes import alerts as alerts_routes
from routes import history as history_routes
from routes import pages
from routes import printer as printer_routes
from routes import settings as settings_routes
from routes import setup as setup_routes


def init_app():
    base_url = get_printer_base_url()
    auth_config = {
        'api_key': os.getenv('PRINTER_API_KEY') or None,
        'username': os.getenv('PRINTER_AUTH_USERNAME') or None,
        'password': os.getenv('PRINTER_AUTH_PASSWORD') or None,
    }

    log_manager = LogManager()
    event_log_service = EventLogService(
        base_url=base_url,
        api_key=auth_config['api_key'],
        auth_username=auth_config['username'],
        auth_password=auth_config['password']
    )
    print_jobs_service = PrintJobsService(
        base_url=base_url,
        api_key=auth_config['api_key'],
        auth_username=auth_config['username'],
        auth_password=auth_config['password']
    )

    app = web.Application(middlewares=[
        security_headers_middleware,
        session_middleware(get_session_storage()),
        auth_middleware,
    ])

    # Shared services, looked up by route handlers via request.app[...]
    # instead of module-level globals, so each route module stays
    # independently testable/importable.
    app['log_manager'] = log_manager
    app['event_log_service'] = event_log_service
    app['print_jobs_service'] = print_jobs_service

    app['session_secret_key'] = get_secret_key().encode('utf-8')

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader('src/templates')
    )

    # No CORS setup: UltiUI is a same-origin app (this server renders the UI
    # and serves the API on the same host/port), so cross-origin requests are
    # never legitimate here. A wildcard CORS policy combined with
    # allow_credentials=True would let any page a user has open in their
    # browser make authenticated requests against this app using the user's
    # session cookie - that's a real CSRF-style vulnerability on a device
    # control API, so it's intentionally not enabled.

    app.router.add_get('/', pages.index)
    app.router.add_get('/setup', pages.setup_page)
    app.router.add_get('/settings', pages.settings_page)
    app.router.add_get('/login', login_page)
    app.router.add_post('/login', login_handler)
    app.router.add_get('/logout', logout_handler)
    app.router.add_get('/event-log', pages.event_log_page)
    app.router.add_get('/print-jobs', pages.print_jobs_page)
    app.router.add_get('/diagnostics', pages.diagnostics_page)

    app.router.add_routes(setup_routes.routes)
    app.router.add_routes(settings_routes.routes)
    app.router.add_routes(printer_routes.routes)
    app.router.add_routes(alerts_routes.routes)
    app.router.add_routes(history_routes.routes)

    app.router.add_static('/static', 'src/static')

    app.on_shutdown.append(lambda _: close_printer_session())

    return app


if __name__ == '__main__':
    app = init_app()
    logger.info('Starting UltiUI server on http://localhost:8081')
    web.run_app(app, host='0.0.0.0', port=8081)
