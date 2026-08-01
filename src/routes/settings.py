"""UI login credential settings API."""
from aiohttp import web

from auth import authenticate, get_credentials
from middleware import error_handler
from setup_service import reload_env, write_env

routes = web.RouteTableDef()


@routes.post('/api/settings/credentials')
@error_handler
async def api_settings_credentials(request):
    data = await request.json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return web.json_response({'error': 'Username and password are required'}, status=400)
    current = get_credentials()
    if username == current['username'] and password == current['password']:
        return web.json_response({'status': 'ok', 'message': 'No changes needed'})
    write_env({'ULTIUI_USERNAME': username, 'ULTIUI_PASSWORD': password})
    reload_env()
    return web.json_response({'status': 'ok', 'message': 'Credentials updated'})


@routes.post('/api/settings/credentials/check')
@error_handler
async def api_settings_credentials_check(request):
    data = await request.json() if request.can_read_body else {}
    username = data.get('username', '')
    password = data.get('password', '')
    if await authenticate(username, password):
        return web.json_response({'valid': True})
    return web.json_response({'valid': False})
