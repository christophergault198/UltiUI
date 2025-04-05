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

@routes.get('/api/flow-data/{samples}')
async def get_flow_data(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        samples = request.match_info['samples']
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://{printer_ip}/api/v1/printer/diagnostics/temperature_flow/{samples}') as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Process the data to get the latest values and calculate averages
                    if len(data) > 1:  # Check if we have the header and at least one data point
                        headers = data[0]
                        values = data[1:]  # Skip header row
                        
                        # Calculate statistics for each metric
                        stats = {
                            'extruder0': {
                                'current_temp': values[-1][headers.index('temperature0')],
                                'target_temp': values[-1][headers.index('target0')],
                                'heater_power': values[-1][headers.index('heater0')],
                                'flow_rate': values[-1][headers.index('flow_sensor0')],
                                'total_steps': values[-1][headers.index('flow_steps0')]
                            },
                            'extruder1': {
                                'current_temp': values[-1][headers.index('temperature1')],
                                'target_temp': values[-1][headers.index('target1')],
                                'heater_power': values[-1][headers.index('heater1')],
                                'flow_rate': values[-1][headers.index('flow_sensor1')],
                                'total_steps': values[-1][headers.index('flow_steps1')]
                            },
                            'bed': {
                                'current_temp': values[-1][headers.index('bed_temperature')],
                                'target_temp': values[-1][headers.index('bed_target')],
                                'heater_power': values[-1][headers.index('bed_heater')]
                            },
                            'active_extruder': values[-1][headers.index('active_hotend_or_state')],
                            'history': {
                                'timestamps': [row[0] for row in values],
                                'extruder0_temp': [row[headers.index('temperature0')] for row in values],
                                'extruder1_temp': [row[headers.index('temperature1')] for row in values],
                                'bed_temp': [row[headers.index('bed_temperature')] for row in values],
                                'flow0': [row[headers.index('flow_sensor0')] for row in values],
                                'flow1': [row[headers.index('flow_sensor1')] for row in values]
                            }
                        }
                        
                        return web.json_response(stats)
                    else:
                        return web.json_response({'error': 'Insufficient data points'}, status=400)
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch flow data: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch flow data: {str(e)}'}, 
            status=500
        )

@routes.get('/api/material-remaining')
async def get_material_remaining(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch data for both extruders
            results = {}
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            for extruder in [0, 1]:
                url = f'http://{printer_ip}/api/v1/printer/heads/0/extruders/{extruder}/active_material/length_remaining'
                async with session.get(url) as response:
                    if response.status == 200:
                        length = await response.json()
                        results[f'extruder{extruder}'] = {
                            'length_remaining': length,
                            'timestamp': timestamp
                        }
                    else:
                        results[f'extruder{extruder}'] = {
                            'error': f'Failed to fetch data: {response.status}',
                            'timestamp': timestamp
                        }
            
            return web.json_response(results)
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch material data: {str(e)}'}, 
            status=500
        )

@routes.get('/api/toolhead-calibration')
async def get_toolhead_calibration(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch data for both extruders
            results = {}
            for extruder in [0, 1]:
                url = f'http://{printer_ip}/api/v1/printer/heads/0/extruders/{extruder}/hotend/offset'
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        results[f'extruder{extruder}'] = data
                    else:
                        results[f'extruder{extruder}'] = {
                            'error': f'Failed to fetch data: {response.status}'
                        }
            
            return web.json_response(results)
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch calibration data: {str(e)}'}, 
            status=500
        )

@routes.get('/api/probing-report')
async def get_probing_report(request):
    printer_ip = os.getenv('PRINTER_IP')
    if not printer_ip:
        return web.json_response({'error': 'Printer IP not configured'}, status=400)
    
    try:
        async with aiohttp.ClientSession() as session:
            headers = {'Accept': 'application/gzip'}  # Add Accept header as shown in the curl command
            async with session.get(f'http://{printer_ip}/api/v1/printer/diagnostics/probing_report', headers=headers) as response:
                if response.status == 200:
                    # Read the raw data as bytes
                    raw_data = await response.read()
                    
                    try:
                        # Parse the JSON data
                        data = json.loads(raw_data)
                        
                        # Process the probing data
                        result = {
                            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # Use current time as timestamp
                            'measurements': [],
                            'statistics': {
                                'min_deviation': 0,
                                'max_deviation': 0,
                                'average_deviation': 0
                            },
                            'out_of_tolerance': False,
                            'tolerance_threshold': 0.2  # 0.2mm tolerance threshold
                        }
                        
                        # Extract measurements from the data
                        if isinstance(data, dict) and 'points' in data:
                            result['measurements'] = [
                                {'deviation': point.get('deviation', 0)} 
                                for point in data['points']
                            ]
                            
                            # Calculate statistics
                            deviations = [m['deviation'] for m in result['measurements']]
                            if deviations:
                                result['statistics']['min_deviation'] = min(deviations)
                                result['statistics']['max_deviation'] = max(deviations)
                                result['statistics']['average_deviation'] = sum(deviations) / len(deviations)
                                
                                # Check if any measurements are out of tolerance
                                max_abs_deviation = max(abs(d) for d in deviations)
                                result['out_of_tolerance'] = max_abs_deviation > result['tolerance_threshold']
                        
                        return web.json_response(result)
                    except json.JSONDecodeError:
                        return web.json_response(
                            {'error': 'Failed to parse probing report data'}, 
                            status=500
                        )
                elif response.status == 204:
                    return web.json_response(
                        {'error': 'No probing report available'}, 
                        status=204
                    )
                else:
                    return web.json_response(
                        {'error': f'Failed to fetch probing report: {response.status}'}, 
                        status=response.status
                    )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch probing report: {str(e)}'}, 
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
    app.router.add_get('/api/flow-data/{samples}', get_flow_data)
    app.router.add_get('/api/material-remaining', get_material_remaining)
    app.router.add_get('/api/toolhead-calibration', get_toolhead_calibration)
    app.router.add_get('/api/probing-report', get_probing_report)
    app.router.add_static('/static', 'src/static')
    
    # Configure CORS for all routes
    for route in list(app.router.routes()):
        cors.add(route)
    
    return app

if __name__ == '__main__':
    app = init_app()
    print("Starting UltiUI server on http://localhost:8080")
    web.run_app(app, host='0.0.0.0', port=8080) 