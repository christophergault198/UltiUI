import os
import json
import aiohttp
from aiohttp import web
from aiohttp_cors import CorsConfig, ResourceOptions
from dotenv import load_dotenv
import aiohttp_cors
import re
from datetime import datetime
from log_manager import LogManager
from event_log_service import EventLogService
from print_jobs_service import PrintJobsService
import numpy as np
import aiohttp_jinja2
import jinja2
from aiohttp_session import setup, SimpleCookieStorage, session_middleware
from auth import login_handler, logout_handler, login_page, login_required, SECRET_KEY
import asyncio

# Load environment variables
load_dotenv()

# Global configuration
config = {
    'printer_ip': os.getenv('PRINTER_IP', ''),
    'tolerance_threshold': 1.0  # Default tolerance threshold in mm
}

# Initialize log manager and event log service as global instances
log_manager = LogManager()
event_log_service = EventLogService()
print_jobs_service = PrintJobsService()

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
                elif response.status == 404:
                    # Return a specific response for "no job" case
                    return web.json_response({'state': None, 'message': 'No print job is currently running'})
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
                    
                    # Process logs using the log manager
                    processed_logs = await log_manager.process_logs(data)
                    
                    # Sort by timestamp, newest first
                    processed_logs.sort(key=lambda x: datetime.strptime(x['timestamp'], '%b %d %H:%M:%S'), reverse=True)
                    
                    # Clean up old data periodically
                    await log_manager.clear_old_data()
                    
                    return web.json_response(processed_logs[-100:])  # Return last 100 messages
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
            headers = {'Accept': 'application/gzip'}
            url = f'http://{printer_ip}/api/v1/printer/diagnostics/probing_report'
            print(f"Fetching probing report from: {url}")
            
            async with session.get(url, headers=headers) as response:
                print(f"Response status: {response.status}")
                print(f"Response headers: {response.headers}")
                
                if response.status == 200:
                    # Get filename from Content-Disposition header
                    content_disp = response.headers.get('Content-Disposition', '')
                    filename = 'probe_report.json'
                    if 'filename=' in content_disp:
                        try:
                            filename_part = content_disp.split('filename=')[1].strip()
                            if filename_part.startswith('"') and filename_part.endswith('"'):
                                filename = filename_part[1:-1]
                            else:
                                filename = filename_part.split(';')[0].strip()
                        except Exception:
                            filename = 'probe_report.json'
                    
                    # Read the raw data
                    raw_data = await response.read()
                    print(f"Received {len(raw_data)} bytes")
                    
                    # Save the file
                    reports_dir = os.path.join('data', 'probe_reports')
                    os.makedirs(reports_dir, exist_ok=True)
                    file_path = os.path.join(reports_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(raw_data)
                    print(f"Saved probe report to {file_path}")
                    
                    try:
                        # Parse the JSON data
                        data = json.loads(raw_data)
                        print("Successfully parsed JSON data")
                        
                        # Get the most recent report (key '0')
                        if '0' not in data:
                            print("No recent probe report found")
                            print(f"Available keys: {list(data.keys())}")
                            return web.json_response({
                                'error': 'No recent probe report found'
                            }, status=400)
                        
                        report = data['0']  # Get most recent report
                        print("Processing most recent probe report")
                        
                        # Process probe points
                        points = []
                        z_values = []
                        
                        if '_ProbeReport__probe_points' in report:
                            probe_points = report['_ProbeReport__probe_points']
                            
                            for point in probe_points:
                                try:
                                    location = point['_ProbePoint__location']
                                    x = location['_Vector2__x']
                                    y = location['_Vector2__y']
                                    z = point['_ProbePoint__z_offset_from_bed_zero']
                                    timestamp = point['_ProbePoint__date_time']
                                    bed_temp = point['_ProbePoint__bed_temp']
                                    nozzle_temp = point['_ProbePoint__nozzle_temp']
                                    
                                    points.append([x, y])
                                    z_values.append(z)
                                except KeyError as e:
                                    print(f"Error processing point: {e}")
                                    continue
                            
                            if points:
                                points = np.array(points)
                                z_values = np.array(z_values)
                                
                                # Calculate statistics
                                z_mean = float(np.mean(z_values))
                                z_min = float(np.min(z_values - z_mean))  # Relative min deviation
                                z_max = float(np.max(z_values - z_mean))  # Relative max deviation
                                z_std = float(np.std(z_values))
                                z_variance = z_max - z_min  # This is now the total relative variance
                                
                                # Analyze bed tilt
                                x_correlation = float(np.corrcoef(points[:, 0], z_values)[0, 1])
                                y_correlation = float(np.corrcoef(points[:, 1], z_values)[0, 1])
                                
                                # Find min/max point locations
                                relative_values = z_values - z_mean
                                min_idx = np.argmin(relative_values)
                                max_idx = np.argmax(relative_values)
                                min_point = points[min_idx].tolist()
                                max_point = points[max_idx].tolist()
                                
                                # Determine bed leveling status
                                tolerance = config['tolerance_threshold']
                                half_tolerance = tolerance / 2
                                
                                if z_variance < half_tolerance:
                                    assessment = "well-leveled"
                                    message = f"Bed is well-leveled (variance < {half_tolerance:.1f}mm)"
                                elif z_variance < tolerance:
                                    assessment = "acceptable"
                                    message = f"Bed leveling is acceptable but could be improved"
                                else:
                                    assessment = "needs attention"
                                    message = f"Bed requires leveling attention (variance > {tolerance:.1f}mm)"
                                
                                # Generate recommendations
                                recommendations = []
                                if abs(x_correlation) > 0.3 or abs(y_correlation) > 0.3:
                                    if abs(x_correlation) > abs(y_correlation):
                                        if x_correlation > 0:
                                            recommendations.append("Bed appears tilted up towards the right side - adjust right side leveling screws slightly lower")
                                        else:
                                            recommendations.append("Bed appears tilted up towards the left side - adjust left side leveling screws slightly lower")
                                    else:
                                        if y_correlation > 0:
                                            recommendations.append("Bed appears tilted up towards the back - adjust back leveling screws slightly lower")
                                        else:
                                            recommendations.append("Bed appears tilted up towards the front - adjust front leveling screws slightly lower")
                                
                                if z_variance > half_tolerance:
                                    if z_variance > tolerance:
                                        recommendations.append("Perform a complete bed leveling procedure")
                                        recommendations.append("Focus on the areas with extreme values first")
                                    else:
                                        recommendations.append("Fine-tune the leveling near the highest and lowest points")
                                
                                if z_std > half_tolerance:
                                    recommendations.append("Check for debris or buildup on the bed surface")
                                    recommendations.append("Consider cleaning the bed with IPA")
                                
                                result = {
                                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    'file_path': file_path,
                                    'file_size': len(raw_data),
                                    'measurements': [
                                        {
                                            'x': float(point[0]),
                                            'y': float(point[1]),
                                            'height': float(z - z_mean),  # Relative height
                                            'deviation': float(z - z_mean)  # Same as height for clarity
                                        }
                                        for point, z in zip(points, z_values)
                                    ],
                                    'statistics': {
                                        'min_height': z_min,  # Now relative to mean
                                        'max_height': z_max,  # Now relative to mean
                                        'std_deviation': z_std,
                                        'max_deviation': z_variance,
                                        'point_count': len(points),
                                        'reference_height': float(z_mean)  # Include the reference height
                                    },
                                    'analysis': {
                                        'assessment': assessment,
                                        'message': message,
                                        'recommendations': recommendations,
                                        'min_point': {
                                            'x': float(min_point[0]),
                                            'y': float(min_point[1]),
                                            'z': float(z_min)
                                        },
                                        'max_point': {
                                            'x': float(max_point[0]),
                                            'y': float(max_point[1]),
                                            'z': float(z_max)
                                        },
                                        'correlations': {
                                            'x_tilt': x_correlation,
                                            'y_tilt': y_correlation
                                        }
                                    },
                                    'temperatures': {
                                        'bed': bed_temp,
                                        'nozzle': nozzle_temp
                                    },
                                    'tolerance_threshold': config['tolerance_threshold'],  # Use config value
                                    'out_of_tolerance': z_variance >= config['tolerance_threshold']
                                }
                                
                                print(f"Processed {len(points)} probe points")
                                print(f"Analysis: {assessment} (variance: {z_variance:.3f}mm)")
                                
                                return web.json_response(result)
                            else:
                                return web.json_response({
                                    'error': 'No valid probe points found in data'
                                }, status=400)
                        else:
                            print("No probe points found in report")
                            print(f"Available keys in report: {list(report.keys())}")
                            return web.json_response({
                                'error': 'Invalid probing report format - no probe points found'
                            }, status=400)
                    except Exception as e:
                        print(f"Error processing probe report: {e}")
                        return web.json_response({
                            'error': 'Failed to process probe report',
                            'details': str(e),
                            'file_path': file_path,
                            'file_size': len(raw_data)
                        }, status=500)
                elif response.status == 204:
                    return web.json_response({
                        'error': 'No probing report available'
                    }, status=204)
                else:
                    return web.json_response({
                        'error': f'Failed to fetch probing report: {response.status}'
                    }, status=response.status)
    except Exception as e:
        print(f"Error: {str(e)}")
        return web.json_response({
            'error': f'Failed to fetch probing report: {str(e)}'
        }, status=500)

@routes.get('/api/tolerance-threshold')
async def get_tolerance_threshold(request):
    """Get the current tolerance threshold"""
    return web.json_response({'tolerance_threshold': config['tolerance_threshold']})

@routes.post('/api/tolerance-threshold')
async def update_tolerance_threshold(request):
    """Update the tolerance threshold"""
    try:
        data = await request.json()
        if 'tolerance_threshold' in data:
            new_tolerance = float(data['tolerance_threshold'])
            if new_tolerance <= 0:
                return web.json_response({'error': 'Tolerance threshold must be positive'}, status=400)
            
            config['tolerance_threshold'] = new_tolerance
            return web.json_response({'status': 'success', 'tolerance_threshold': new_tolerance})
        return web.json_response({'error': 'Invalid request data'}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

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

@routes.get('/api/events')
async def get_events(request):
    try:
        # Get count parameter from query string if present
        count = None
        if 'count' in request.query:
            try:
                count = int(request.query['count'])
                # Limit to reasonable values
                if count < 1:
                    count = 1
                elif count > 1000:
                    count = 1000
            except ValueError:
                # If count is not a valid integer, ignore it
                pass
                
        events = await event_log_service.get_formatted_events(count)
        return web.json_response(events)
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch events: {str(e)}'}, 
            status=500
        )

@routes.get('/event-log')
async def event_log_page(request):
    try:
        events = await event_log_service.get_formatted_events()
        response = aiohttp_jinja2.render_template(
            'event_log.html',
            request,
            {'events': events}
        )
        return response
    except Exception as e:
        return web.Response(
            text=f"Error loading event log: {str(e)}",
            status=500
        )

@routes.get('/api/print-jobs')
async def get_print_jobs(request):
    try:
        # Get count parameter from query string if present
        count = None
        if 'count' in request.query:
            try:
                count = int(request.query['count'])
                # Limit to reasonable values
                if count < 1:
                    count = 1
                elif count > 1000:
                    count = 1000
            except ValueError:
                # If count is not a valid integer, ignore it
                pass
                
        print_jobs = await print_jobs_service.get_formatted_print_jobs(count)
        return web.json_response(print_jobs)
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch print jobs: {str(e)}'}, 
            status=500
        )

@routes.get('/print-jobs')
async def print_jobs_page(request):
    try:
        print_jobs = await print_jobs_service.get_formatted_print_jobs(50)  # Default to 50 jobs
        response = aiohttp_jinja2.render_template(
            'print_jobs.html',
            request,
            {'print_jobs': print_jobs}
        )
        return response
    except Exception as e:
        return web.Response(
            text=f"Error loading print jobs: {str(e)}",
            status=500
        )

@routes.get('/api/alerts')
async def get_alerts(request):
    """Get all active alerts"""
    alerts = log_manager.alerts_service.get_active_alerts()
    return web.json_response(alerts)

@routes.get('/api/alerts/history')
async def get_alert_history(request):
    """Get alert history"""
    limit = request.query.get('limit', '100')
    try:
        limit = int(limit)
    except ValueError:
        limit = 100
    alerts = log_manager.alerts_service.get_alert_history(limit)
    return web.json_response(alerts)

@routes.post('/api/alerts/{alert_id}/resolve')
async def resolve_alert(request):
    """Resolve an alert"""
    alert_id = request.match_info['alert_id']
    alert = await log_manager.alerts_service.resolve_alert(alert_id)
    if alert:
        return web.json_response(alert)
    return web.json_response({'error': 'Alert not found'}, status=404)

@routes.get('/api/alerts/stream')
async def alert_stream(request):
    """Stream alert updates to clients"""
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'
    
    # Add CORS preflight handling
    if request.method == 'OPTIONS':
        return response
        
    await response.prepare(request)

    try:
        # Send initial data
        alerts = log_manager.alerts_service.get_active_alerts()
        data = json.dumps(alerts)
        await response.write(f'event: message\ndata: {data}\n\n'.encode())
        await response.drain()

        # Keep connection alive and send updates
        while True:
            # Get current alerts
            alerts = log_manager.alerts_service.get_active_alerts()
            
            # Send alerts as SSE
            data = json.dumps(alerts)
            await response.write(f'event: message\ndata: {data}\n\n'.encode())
            await response.drain()
            
            # Add a heartbeat event to keep connection alive
            await response.write(b'event: heartbeat\ndata: ping\n\n')
            await response.drain()
            
            # Wait before sending next update
            await asyncio.sleep(1)
    except ConnectionResetError:
        print("Client disconnected from alert stream")
    except asyncio.CancelledError:
        print("Alert stream cancelled")
    except Exception as e:
        print(f"Error in alert stream: {str(e)}")
    finally:
        return response

# Authentication middleware
@web.middleware
async def auth_middleware(request, handler):
    # Skip authentication for login-related routes and static files
    if request.path in ['/login', '/logout'] or request.path.startswith('/static/'):
        return await handler(request)
    
    # Check if the user is authenticated
    auth_result = await login_required(request)
    if auth_result:
        return auth_result
    
    # User is authenticated, proceed with the request
    return await handler(request)

def init_app():
    """Initialize the application"""
    # Create the application with both middlewares
    app = web.Application(middlewares=[
        session_middleware(SimpleCookieStorage()),
        auth_middleware
    ])
    
    # Set the secret key for the session
    app['session_secret_key'] = SECRET_KEY.encode('utf-8')
    
    # Setup template engine
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader('src/templates')
    )
    
    # Setup CORS with more permissive settings
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["GET", "POST", "OPTIONS"],
            max_age=3600
        )
    })
    
    # Configure routes
    app.router.add_get('/', index)
    app.router.add_get('/login', login_page)
    app.router.add_post('/login', login_handler)
    app.router.add_get('/logout', logout_handler)
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
    app.router.add_get('/api/tolerance-threshold', get_tolerance_threshold)
    app.router.add_post('/api/tolerance-threshold', update_tolerance_threshold)
    app.router.add_get('/api/events', get_events)
    app.router.add_get('/api/alerts', get_alerts)
    app.router.add_get('/api/alerts/history', get_alert_history)
    app.router.add_post('/api/alerts/{alert_id}/resolve', resolve_alert)
    app.router.add_get('/api/alerts/stream', alert_stream)
    
    # Add event log route directly without using @routes decorator
    app.router.add_get('/event-log', event_log_page)
    
    app.router.add_get('/api/print-jobs', get_print_jobs)
    app.router.add_get('/print-jobs', print_jobs_page)
    
    app.router.add_static('/static', 'src/static')
    
    # Configure CORS for all routes
    for route in list(app.router.routes()):
        cors.add(route)
    
    return app

if __name__ == '__main__':
    app = init_app()
    print("Starting UltiUI server on http://localhost:8081")
    web.run_app(app, host='0.0.0.0', port=8081) 