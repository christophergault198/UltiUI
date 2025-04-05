import os
import json
import aiohttp
from aiohttp import web
from aiohttp_cors import CorsConfig, ResourceOptions
from dotenv import load_dotenv
import aiohttp_cors
import re
from datetime import datetime

# Load environment variables
load_dotenv()

# Global configuration
config = {
    'printer_ip': os.getenv('PRINTER_IP', '')
}

routes = web.RouteTableDef()

@routes.get('/api/printer-stats')
async def get_printer_stats(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{printer_ip}/api/v1/printer') as response:
                if response.status == 200:
                    data = await response.json()
                    return web.json_response(data)
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch printer stats: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch printer stats: {str(e)}'}, 
            status=500
        )

@routes.get('/api/print-job')
async def get_print_job(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{printer_ip}/api/v1/print_job') as response:
                if response.status == 200:
                    data = await response.json()
                    return web.json_response(data)
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch print job: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch print job: {str(e)}'}, 
            status=500
        )

@routes.get('/api/print-cores')
async def get_print_cores(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{printer_ip}/api/v1/system/log') as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Initialize print core stats
                    print_cores = {
                        '0': {'last_extrusion': None, 'remaining_length': None, 'usage_duration': None},
                        '1': {'last_extrusion': None, 'remaining_length': None, 'usage_duration': None}
                    }
                    
                    # Regular expression pattern for print core info
                    pattern = r"PrintCore (\d+) extruded ([\d.]+) mm in ([\d.]+) s, remaining length = ([\d.]+) mm, stat record usage duration: ([\d.]+) s"
                    
                    # Process log entries in reverse to get the most recent data
                    for log_entry in reversed(data):
                        if "PrintCore" in log_entry and "extruded" in log_entry:
                            match = re.search(pattern, log_entry)
                            if match:
                                core_num = match.group(1)
                                if print_cores[core_num]['last_extrusion'] is None:
                                    print_cores[core_num] = {
                                        'last_extrusion': {
                                            'amount': float(match.group(2)),
                                            'time': float(match.group(3))
                                        },
                                        'remaining_length': float(match.group(4)),
                                        'usage_duration': float(match.group(5))
                                    }
                                    
                                # If we have data for both cores, break
                                if all(core['last_extrusion'] is not None for core in print_cores.values()):
                                    break
                    
                    return web.json_response(print_cores)
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch system log: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch system log: {str(e)}'}, 
            status=500
        )

@routes.get('/api/system-log')
async def get_system_log(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{printer_ip}/api/v1/system/log') as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Process log entries to remove hostname and simplify
                    processed_logs = []
                    seen_messages = set()  # Track unique messages
                    
                    for log_entry in data:
                        # Extract timestamp and message parts
                        match = re.match(r"(\w+ \d+ \d+:\d+:\d+) \S+ (.+)", log_entry)
                        if match:
                            timestamp, message = match.groups()
                            # Only add if we haven't seen this exact message before
                            if message not in seen_messages:
                                seen_messages.add(message)
                                processed_logs.append({
                                    'timestamp': timestamp,
                                    'message': message,
                                    'raw': log_entry
                                })
                    
                    return web.json_response(processed_logs[-100:])  # Return last 100 unique messages
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch system log: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch system log: {str(e)}'}, 
            status=500
        )

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
    app.router.add_get('/api/printer-stats', get_printer_stats)
    app.router.add_get('/api/print-job', get_print_job)
    app.router.add_get('/api/print-cores', get_print_cores)
    app.router.add_get('/api/system-log', get_system_log)
    app.router.add_static('/static', 'src/static')
    
    # Configure CORS for all routes
    for route in list(app.router.routes()):
        cors.add(route)
    
    return app

if __name__ == '__main__':
    app = init_app()
    print("Starting UltiUI server on http://localhost:8080")
    web.run_app(app, host='0.0.0.0', port=8080) 