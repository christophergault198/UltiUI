import os
import json
import aiohttp
from aiohttp import web
from aiohttp_cors import CorsConfig, ResourceOptions
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Global configuration
config = {
    'printer_ip': os.getenv('PRINTER_IP', '')
}

async def get_config(request):
    """Get current configuration"""
    return web.json_response(config)

async def update_config(request):
    """Update configuration"""
    try:
        data = await request.json()
        if 'printer_ip' in data:
            config['printer_ip'] = data['printer_ip']
            # Update .env file
            with open('.env', 'w') as f:
                f.write(f"PRINTER_IP={config['printer_ip']}\n")
            return web.json_response({'status': 'success'})
        return web.json_response({'status': 'error', 'message': 'Invalid configuration'}, status=400)
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def test_connection(request):
    """Test connection to the printer"""
    if not config['printer_ip']:
        return web.json_response({
            'status': 'error',
            'message': 'Printer IP not configured',
            'connected': False
        })

    try:
        async with aiohttp.ClientSession() as session:
            # Try to connect to the printer's camera stream
            url = f"http://{config['printer_ip']}:8080/?action=stream"
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    return web.json_response({
                        'status': 'success',
                        'message': 'Connected to printer',
                        'connected': True
                    })
                else:
                    return web.json_response({
                        'status': 'error',
                        'message': f'Printer responded with status {response.status}',
                        'connected': False
                    })
    except aiohttp.ClientError as e:
        return web.json_response({
            'status': 'error',
            'message': str(e),
            'connected': False
        })
    except Exception as e:
        return web.json_response({
            'status': 'error',
            'message': str(e),
            'connected': False
        })

async def camera_stream(request):
    """Proxy the camera stream from the printer"""
    if not config['printer_ip']:
        return web.Response(status=400, text='Printer IP not configured')

    try:
        # Instead of proxying the stream, redirect to the printer's camera stream
        return web.HTTPFound(f"http://{config['printer_ip']}:8080/?action=stream")
    except Exception as e:
        return web.Response(status=500, text=str(e))

async def index(request):
    """Serve the main page"""
    return web.FileResponse('src/templates/index.html')

def init_app():
    """Initialize the application"""
    app = web.Application()
    
    # Setup CORS
    cors = CorsConfig(app, defaults={
        "*": ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    # Configure routes
    app.router.add_get('/', index)
    app.router.add_get('/api/config', get_config)
    app.router.add_post('/api/config', update_config)
    app.router.add_get('/api/test-connection', test_connection)
    app.router.add_get('/api/camera/stream', camera_stream)
    app.router.add_static('/static', 'src/static')
    
    # Configure CORS for all routes
    for route in list(app.router.routes()):
        cors.add(route)
    
    return app

if __name__ == '__main__':
    app = init_app()
    print("Starting UltiUI server on http://localhost:8080")
    web.run_app(app, host='0.0.0.0', port=8080) 