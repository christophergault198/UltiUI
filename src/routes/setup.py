"""First-run setup API: configuring the printer IP and requesting/saving
printer API auth credentials.
"""
import os

from aiohttp import web

from middleware import error_handler
from setup_service import (
    check_auth,
    get_status,
    reload_env,
    request_auth,
    reset_all,
    reset_printer_auth,
    save_auth,
    save_printer_ip,
)

routes = web.RouteTableDef()


@routes.post('/api/setup/auth-request')
@error_handler
async def api_setup_auth_request(request):
    data = await request.json()
    printer_ip = data.get('printer_ip', os.getenv('PRINTER_IP', ''))
    if not printer_ip:
        return web.json_response({'error': 'Printer IP is required'}, status=400)
    result = await request_auth(printer_ip)
    if result:
        return web.json_response(result)
    return web.json_response({'error': 'Failed to request authorization from printer'}, status=500)


@routes.get('/api/setup/auth-status/{auth_id}')
@error_handler
async def api_setup_auth_status(request):
    printer_ip = os.getenv('PRINTER_IP', '')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    auth_id = request.match_info['auth_id']
    status = await check_auth(printer_ip, auth_id)
    if status:
        return web.json_response({'status': status})
    return web.json_response({'error': 'Failed to check auth status'}, status=500)


@routes.post('/api/setup/save')
@error_handler
async def api_setup_save(request):
    data = await request.json()
    printer_ip = data.get('printer_ip')
    auth_id = data.get('auth_id')
    auth_key = data.get('auth_key')
    if printer_ip:
        save_printer_ip(printer_ip)
    if auth_id and auth_key:
        save_auth(auth_id, auth_key)
    reload_env()
    return web.json_response({'status': 'ok'})


@routes.get('/api/setup/status')
@error_handler
async def api_setup_status(request):
    status = get_status()
    return web.json_response(status)


@routes.post('/api/setup/reset')
@error_handler
async def api_setup_reset(request):
    data = await request.json() if request.can_read_body else {}
    reset_type = data.get('type', 'all')
    if reset_type == 'auth':
        reset_printer_auth()
    else:
        reset_all()
    reload_env()
    return web.json_response({'status': 'ok'})
