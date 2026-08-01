import asyncio
import json
import os
import re
from datetime import datetime

import aiohttp
import aiohttp_cors
import aiohttp_jinja2
import jinja2
import numpy as np
import requests
from aiohttp import web
from aiohttp_session import session_middleware
from requests.auth import HTTPDigestAuth

from auth import get_credentials, get_session_storage, login_handler, login_page, login_required, logout_handler
from config import get_printer_ip, get_secret_key
from event_log_service import EventLogService
from log_manager import LogManager
from logger import logger
from middleware import require_printer_ip
from print_jobs_service import PrintJobsService
from printer_client import close_printer_session, get_printer_base_url, get_printer_session
from setup_service import (
    check_auth,
    get_status,
    reload_env,
    request_auth,
    reset_all,
    reset_printer_auth,
    save_auth,
    save_printer_ip,
    write_env,
)

routes = web.RouteTableDef()
config = {
    'tolerance_threshold': 1.0,
}

printer_auth = {
    'username': os.getenv('PRINTER_AUTH_USERNAME') or None,
    'password': os.getenv('PRINTER_AUTH_PASSWORD') or None,
    'api_key': os.getenv('PRINTER_API_KEY') or None,
}


def _get_printer_ip():
    return get_printer_ip()


def _digest_auth():
    return HTTPDigestAuth(
        printer_auth['username'] or 'ultimaker',
        printer_auth['password'] or ''
    )


@routes.get('/api/printer-stats')
@require_printer_ip
async def get_printer_stats(request):
    session = await get_printer_session()
    async with session.get(f'http://{_get_printer_ip()}/api/v1/printer') as response:
        if response.status == 200:
            data = await response.json()
            return web.json_response(data)
        return web.json_response(
            {'error': f'Failed to fetch printer stats: {response.status}'},
            status=response.status
        )


@routes.get('/api/ambient-temperature')
@require_printer_ip
async def get_ambient_temperature(request):
    try:
        session = await get_printer_session()
        async with session.get(f'http://{_get_printer_ip()}/api/v1/ambient_temperature') as response:
            if response.status == 200:
                data = await response.json()
                return web.json_response(data)
            return web.json_response({'current': None}, status=200)
    except Exception:
        return web.json_response({'current': None}, status=200)


@routes.get('/api/printer/led/brightness')
@require_printer_ip
async def get_led_brightness(request):
    try:
        session = await get_printer_session()
        async with session.get(f'http://{_get_printer_ip()}/api/v1/printer/led/brightness') as response:
            if response.status == 200:
                text = await response.text()
                return web.json_response({'brightness': float(text.strip())})
            return web.json_response({'brightness': None}, status=200)
    except Exception:
        return web.json_response({'brightness': None}, status=200)


@routes.post('/api/printer/led/brightness')
@require_printer_ip
async def set_led_brightness(request):
    try:
        data = await request.json()
        brightness = float(data.get('brightness', 0))
        brightness = max(0.0, min(100.0, brightness))
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.put(
                f'http://{_get_printer_ip()}/api/v1/printer/led/brightness',
                json=brightness,
                auth=_digest_auth(),
                timeout=10
            )
        )
        if resp.status_code == 200:
            return web.json_response({'status': 'ok', 'brightness': brightness})
        return web.json_response(
            {'error': f'Failed to set LED brightness: {resp.status_code}', 'detail': resp.text},
            status=resp.status_code
        )
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


@routes.get('/api/print-job')
@require_printer_ip
async def get_print_job(request):
    try:
        session = await get_printer_session()
        ip = _get_printer_ip()
        async with session.get(f'http://{ip}/api/v1/print_job') as response:
            if response.status == 200:
                data = await response.json()
                return web.json_response(data)
            elif response.status in (404, 204):
                return web.json_response({'state': None, 'message': 'No print job is currently running'})
            elif response.status == 401:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f'http://{ip}/api/v1/print_job',
                        auth=_digest_auth(),
                        timeout=10
                    )
                )
                if resp.status_code == 200:
                    return web.json_response(resp.json())
                elif resp.status_code == 404:
                    return web.json_response({'state': None, 'message': 'No print job is currently running'})
                return web.json_response(
                    {'error': f'Failed to fetch print job: {resp.status_code}'},
                    status=resp.status_code
                )
            return web.json_response(
                {'error': f'Failed to fetch print job: {response.status}'},
                status=response.status
            )
    except Exception as e:
        return web.json_response(
            {'error': f'Failed to fetch print job: {str(e)}'},
            status=500
        )


@routes.post('/api/print/control')
@require_printer_ip
async def control_print_job(request):
    try:
        data = await request.json()
        action = data.get('action', '')
        if action not in ('pause', 'resume', 'abort'):
            return web.json_response({'error': 'Invalid action. Use pause, resume, or abort'}, status=400)
        target = 'pause' if action == 'pause' else ('print' if action == 'resume' else 'abort')
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.put(
                f'http://{_get_printer_ip()}/api/v1/print_job/state',
                json={'target': target},
                auth=_digest_auth(),
                timeout=10
            )
        )
        if resp.status_code in (200, 204):
            logger.info('Print job %sd', action)
            return web.json_response({'status': 'ok', 'message': f'Print job {action}d'})
        return web.json_response(
            {'error': f'Failed to {action} print: {resp.status_code}', 'detail': resp.text},
            status=resp.status_code
        )
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


@routes.get('/api/print-cores')
@require_printer_ip
async def get_print_cores(request):
    session = await get_printer_session()
    async with session.get(f'http://{_get_printer_ip()}/api/v1/system/log') as response:
        if response.status == 200:
            data = await response.json()
            print_cores = {
                '0': {'last_extrusion': None, 'remaining_length': None, 'usage_duration': None},
                '1': {'last_extrusion': None, 'remaining_length': None, 'usage_duration': None}
            }
            pattern = (
                r"PrintCore (\d+) extruded ([\d.]+) mm in ([\d.]+) s, "
                r"remaining length = ([\d.]+) mm, stat record usage duration: ([\d.]+) s"
            )
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
                        if all(core['last_extrusion'] is not None for core in print_cores.values()):
                            break
            return web.json_response(print_cores)
        return web.json_response(
            {'error': f'Failed to fetch system log: {response.status}'},
            status=response.status
        )


@routes.get('/api/system-log')
@require_printer_ip
async def get_system_log(request):
    session = await get_printer_session()
    async with session.get(f'http://{_get_printer_ip()}/api/v1/system/log') as response:
        if response.status == 200:
            data = await response.json()
            processed_logs = await log_manager.process_logs(data)
            await log_manager.clear_old_data()
            return web.json_response(processed_logs[-100:])
        return web.json_response(
            {'error': f'Failed to fetch system log: {response.status}'},
            status=response.status
        )


@routes.get('/api/flow-data/{samples}')
@require_printer_ip
async def get_flow_data(request):
    samples = request.match_info['samples']
    session = await get_printer_session()
    async with session.get(
        f'http://{_get_printer_ip()}/api/v1/printer/diagnostics/temperature_flow/{samples}'
    ) as response:
        if response.status == 200:
            data = await response.json()
            if len(data) > 1:
                headers = data[0]
                values = data[1:]
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
            return web.json_response({'error': 'Insufficient data points'}, status=400)
        return web.json_response(
            {'error': f'Failed to fetch flow data: {response.status}'},
            status=response.status
        )


@routes.get('/api/material-remaining')
@require_printer_ip
async def get_material_remaining(request):
    session = await get_printer_session()
    results = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for extruder in [0, 1]:
        url = f'http://{_get_printer_ip()}/api/v1/printer/heads/0/extruders/{extruder}/active_material/length_remaining'
        async with session.get(url) as response:
            if response.status == 200:
                length = await response.json()
                results[f'extruder{extruder}'] = {'length_remaining': length, 'timestamp': timestamp}
            else:
                results[f'extruder{extruder}'] = {
                    'error': f'Failed to fetch data: {response.status}', 'timestamp': timestamp
                }
    return web.json_response(results)


@routes.get('/api/toolhead-calibration')
@require_printer_ip
async def get_toolhead_calibration(request):
    session = await get_printer_session()
    results = {}
    for extruder in [0, 1]:
        url = f'http://{_get_printer_ip()}/api/v1/printer/heads/0/extruders/{extruder}/hotend/offset'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                results[f'extruder{extruder}'] = data
            else:
                results[f'extruder{extruder}'] = {'error': f'Failed to fetch data: {response.status}'}
    return web.json_response(results)


@routes.get('/api/probing-report')
@require_printer_ip
async def get_probing_report(request):
    session = await get_printer_session()
    headers = {'Accept': 'application/gzip'}
    url = f'http://{_get_printer_ip()}/api/v1/printer/diagnostics/probing_report'
    logger.info('Fetching probing report from: %s', url)

    async with session.get(url, headers=headers) as response:
        logger.info('Probing report response status: %s', response.status)

        if response.status == 200:
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

            raw_data = await response.read()
            logger.info('Received %d bytes', len(raw_data))

            reports_dir = os.path.join('data', 'probe_reports')
            os.makedirs(reports_dir, exist_ok=True)
            file_path = os.path.join(reports_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(raw_data)
            logger.info('Saved probe report to %s', file_path)

            try:
                data = json.loads(raw_data)
                if '0' not in data:
                    logger.warning('No recent probe report found, keys: %s', list(data.keys()))
                    return web.json_response({'error': 'No recent probe report found'}, status=400)

                report = data['0']
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
                            bed_temp = point['_ProbePoint__bed_temp']
                            nozzle_temp = point['_ProbePoint__nozzle_temp']
                            points.append([x, y])
                            z_values.append(z)
                        except KeyError as e:
                            logger.warning('Error processing point: %s', e)
                            continue

                    if points:
                        points_arr = np.array(points)
                        z_arr = np.array(z_values)

                        z_mean = float(np.mean(z_arr))
                        z_min = float(np.min(z_arr - z_mean))
                        z_max = float(np.max(z_arr - z_mean))
                        z_std = float(np.std(z_arr))
                        z_variance = z_max - z_min

                        x_correlation = float(np.corrcoef(points_arr[:, 0], z_arr)[0, 1])
                        y_correlation = float(np.corrcoef(points_arr[:, 1], z_arr)[0, 1])

                        relative_values = z_arr - z_mean
                        min_idx = np.argmin(relative_values)
                        max_idx = np.argmax(relative_values)
                        min_point = points_arr[min_idx].tolist()
                        max_point = points_arr[max_idx].tolist()

                        tolerance = config['tolerance_threshold']
                        half_tolerance = tolerance / 2

                        if z_variance < half_tolerance:
                            assessment = "well-leveled"
                            message = f"Bed is well-leveled (variance < {half_tolerance:.1f}mm)"
                        elif z_variance < tolerance:
                            assessment = "acceptable"
                            message = "Bed leveling is acceptable but could be improved"
                        else:
                            assessment = "needs attention"
                            message = f"Bed requires leveling attention (variance > {tolerance:.1f}mm)"

                        recommendations = []
                        if abs(x_correlation) > 0.3 or abs(y_correlation) > 0.3:
                            if abs(x_correlation) > abs(y_correlation):
                                if x_correlation > 0:
                                    recommendations.append(
                                        "Bed tilted up towards the right side - adjust right leveling screws lower"
                                    )
                                else:
                                    recommendations.append(
                                        "Bed tilted up towards the left side - adjust left leveling screws lower"
                                    )
                            else:
                                if y_correlation > 0:
                                    recommendations.append(
                                        "Bed tilted up towards the back - adjust back leveling screws lower"
                                    )
                                else:
                                    recommendations.append(
                                        "Bed tilted up towards the front - adjust front leveling screws lower"
                                    )

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
                                    'x': float(point[0]), 'y': float(point[1]),
                                    'height': float(z - z_mean), 'deviation': float(z - z_mean)
                                }
                                for point, z in zip(points, z_arr)
                            ],
                            'statistics': {
                                'min_height': z_min,
                                'max_height': z_max,
                                'std_deviation': z_std,
                                'max_deviation': z_variance,
                                'point_count': len(points),
                                'reference_height': float(z_mean)
                            },
                            'analysis': {
                                'assessment': assessment,
                                'message': message,
                                'recommendations': recommendations,
                                'min_point': {'x': float(min_point[0]), 'y': float(min_point[1]), 'z': float(z_min)},
                                'max_point': {'x': float(max_point[0]), 'y': float(max_point[1]), 'z': float(z_max)},
                                'correlations': {'x_tilt': x_correlation, 'y_tilt': y_correlation}
                            },
                            'temperatures': {'bed': bed_temp, 'nozzle': nozzle_temp},
                            'tolerance_threshold': config['tolerance_threshold'],
                            'out_of_tolerance': z_variance >= config['tolerance_threshold']
                        }

                        logger.info(
                            'Processed %d probe points - %s (variance: %.3fmm)',
                            len(points), assessment, z_variance
                        )
                        return web.json_response(result)

                    return web.json_response({'error': 'No valid probe points found in data'}, status=400)

                logger.warning('No probe points found in report')
                return web.json_response({'error': 'Invalid probing report format - no probe points found'}, status=400)

            except Exception as e:
                logger.exception('Error processing probe report')
                return web.json_response({
                    'error': 'Failed to process probe report',
                    'details': str(e),
                    'file_path': file_path,
                    'file_size': len(raw_data)
                }, status=500)

        elif response.status == 204:
            return web.json_response({'error': 'No probing report available'}, status=204)
        else:
            return web.json_response(
                {'error': f'Failed to fetch probing report: {response.status}'},
                status=response.status
            )


@routes.get('/api/tolerance-threshold')
async def get_tolerance_threshold(request):
    return web.json_response({'tolerance_threshold': config['tolerance_threshold']})


@routes.post('/api/tolerance-threshold')
async def update_tolerance_threshold(request):
    try:
        data = await request.json()
        if 'tolerance_threshold' in data:
            new_tolerance = float(data['tolerance_threshold'])
            if new_tolerance <= 0:
                return web.json_response({'error': 'Tolerance threshold must be positive'}, status=400)
            config['tolerance_threshold'] = new_tolerance
            logger.info('Tolerance threshold updated to %f', new_tolerance)
            return web.json_response({'status': 'success', 'tolerance_threshold': new_tolerance})
        return web.json_response({'error': 'Invalid request data'}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


@routes.get('/api/config')
async def get_config(request):
    return web.json_response({
        **config,
        'printer_ip': get_printer_ip(),
    })


@routes.post('/api/config')
async def update_config(request):
    try:
        data = await request.json()
        if 'printer_ip' in data:
            config['printer_ip'] = data['printer_ip']
            env_path = '.env'
            lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith('PRINTER_IP='):
                    lines[i] = f"PRINTER_IP={config['printer_ip']}\n"
                    found = True
                    break
            if not found:
                lines.append(f"PRINTER_IP={config['printer_ip']}\n")
            with open(env_path, 'w') as f:
                f.writelines(lines)
            return web.json_response({'status': 'success'})
        return web.json_response({'status': 'error', 'message': 'Invalid configuration'}, status=400)
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)


@routes.get('/api/test-connection')
@require_printer_ip
async def test_connection(request):
    try:
        session = await get_printer_session()
        url = f"http://{_get_printer_ip()}:8080/?action=stream"
        async with session.get(url, timeout=5) as response:
            if response.status == 200:
                return web.json_response(
                    {'status': 'success', 'message': 'Connected to printer', 'connected': True}
                )
            return web.json_response(
                {
                    'status': 'error',
                    'message': f'Printer responded with status {response.status}',
                    'connected': False,
                }
            )
    except aiohttp.ClientError as e:
        return web.json_response({'status': 'error', 'message': str(e), 'connected': False})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e), 'connected': False})


@routes.get('/api/camera/stream')
async def camera_stream(request):
    ip = _get_printer_ip()
    if not ip:
        return web.Response(status=400, text='Printer IP not configured')
    return web.HTTPFound(f"http://{ip}:8080/?action=stream")


@routes.get('/api/events')
async def get_events(request):
    count = None
    if 'count' in request.query:
        try:
            count = int(request.query['count'])
            count = max(1, min(count, 1000))
        except ValueError:
            pass
    events = await event_log_service.get_formatted_events(count)
    return web.json_response(events)


@routes.get('/api/print-jobs')
async def get_print_jobs(request):
    count = None
    if 'count' in request.query:
        try:
            count = int(request.query['count'])
            count = max(1, min(count, 1000))
        except ValueError:
            pass
    print_jobs = await print_jobs_service.get_formatted_print_jobs(count)
    return web.json_response(print_jobs)


@routes.get('/api/alerts')
async def get_alerts(request):
    alerts = log_manager.alerts_service.get_active_alerts()
    return web.json_response(alerts)


@routes.get('/api/alerts/history')
async def get_alert_history(request):
    limit = request.query.get('limit', '100')
    try:
        limit = int(limit)
    except ValueError:
        limit = 100
    alerts = log_manager.alerts_service.get_alert_history(limit)
    return web.json_response(alerts)


@routes.post('/api/alerts/{alert_id}/resolve')
async def resolve_alert(request):
    alert_id = request.match_info['alert_id']
    alert = await log_manager.alerts_service.resolve_alert(alert_id)
    if alert:
        return web.json_response(alert)
    return web.json_response({'error': 'Alert not found'}, status=404)


@routes.get('/api/alerts/stream')
async def alert_stream(request):
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'

    if request.method == 'OPTIONS':
        return response

    await response.prepare(request)

    try:
        alerts = log_manager.alerts_service.get_active_alerts()
        data = json.dumps(alerts)
        await response.write(f'event: message\ndata: {data}\n\n'.encode())

        while True:
            await asyncio.sleep(1)
            if log_manager.alerts_service._alerts_changed():
                alerts = log_manager.alerts_service.get_active_alerts()
                data = json.dumps(alerts)
                await response.write(f'event: message\ndata: {data}\n\n'.encode())
            await response.write(b'event: heartbeat\ndata: ping\n\n')
    except ConnectionResetError:
        logger.info('Client disconnected from alert stream')
    except asyncio.CancelledError:
        logger.info('Alert stream cancelled')
    except Exception:
        logger.exception('Error in alert stream')

    return response


@routes.get('/api/health-score')
@require_printer_ip
async def get_health_score(request):
    issues = []
    printer_data = None
    ip = _get_printer_ip()

    try:
        session = await get_printer_session()
        temp_score = 100
        printer_status_score = 100
        core_score = 100
        calibration_score = 100

        try:
            async with session.get(f'http://{ip}/api/v1/printer') as resp:
                if resp.status == 200:
                    printer_data = await resp.json()
                    status = printer_data.get('status', '')
                    if status in ('error', 'maintenance'):
                        printer_status_score = 20
                        issues.append(f'Printer in {status} state')
                    elif status == 'paused':
                        printer_status_score = 50
                        issues.append('Printer is paused')

                    deviations = []
                    if printer_data.get('bed', {}).get('temperature'):
                        t = printer_data['bed']['temperature']
                        if t.get('target', 0) > 0:
                            dev = abs(t['current'] - t['target']) / t['target']
                            deviations.append(dev)
                            if dev > 0.15:
                                issues.append(f'Bed temperature deviation: {t["current"]}°C from {t["target"]}°C')
                    heads = printer_data.get('heads', [])
                    if heads:
                        for i, ext in enumerate(heads[0].get('extruders', [])):
                            ht = ext.get('hotend', {}).get('temperature', {})
                            if ht.get('target', 0) > 0:
                                dev = abs(ht['current'] - ht['target']) / ht['target']
                                deviations.append(dev)
                                if dev > 0.15:
                                    issues.append(
                                        f'Extruder {i} temperature deviation: '
                                        f'{ht["current"]}°C from {ht["target"]}°C'
                                    )

                            stats = ext.get('hotend', {}).get('statistics', {})
                            max_exp = stats.get('max_temperature_exposed', 0)
                            if max_exp > 280:
                                issues.append(f'Extruder {i} exceeded 280°C (max: {max_exp}°C)')

                            remaining = ext.get('active_material', {}).get('length_remaining', -1)
                            if isinstance(remaining, (int, float)) and remaining == -1:
                                issues.append(f'No spool detected on extruder {i}')

                    if deviations:
                        avg_dev = sum(deviations) / len(deviations)
                        temp_score = max(0, min(100, round(100 - avg_dev * 200)))
                        if temp_score < 70:
                            issues.append('Temperature deviations above threshold')

                    core_issues = 0
                    if heads:
                        for i, ext in enumerate(heads[0].get('extruders', [])):
                            stats = ext.get('hotend', {}).get('statistics', {})
                            prints = stats.get('prints_since_cleaned', '0')
                            try:
                                p = int(prints)
                                if p > 50:
                                    core_issues += 1
                                    issues.append(f'Print core {i} has {p} prints since last cleaning')
                            except ValueError:
                                pass
                    core_score = max(0, 100 - core_issues * 35)

                    cal_valid = True
                    if heads:
                        for i, ext in enumerate(heads[0].get('extruders', [])):
                            offset = ext.get('hotend', {}).get('offset', {})
                            if offset.get('state') == 'invalid':
                                cal_valid = False
                                issues.append(f'Extruder {i} calibration is invalid')
                    calibration_score = 0 if not cal_valid else 100

        except Exception:
            temp_score = 0
            printer_status_score = 0
            issues.append('Cannot read printer data')

        progress_score = 100
        try:
            async with session.get(f'http://{ip}/api/v1/print_job') as resp:
                if resp.status == 200:
                    job = await resp.json()
                    state = job.get('state', '')
                    pause_source = job.get('pause_source', '')
                    if state == 'paused':
                        progress_score = 30
                        if pause_source:
                            issues.append(f'Print paused: {pause_source}')
                        else:
                            issues.append('Print is paused')
                    elif state == 'printing' and job.get('time_elapsed', 0) > 60:
                        progress = job.get('progress', 0)
                        elapsed = job.get('time_elapsed', 1)
                        estimated = job.get('time_total', 1)
                        if estimated > 0:
                            expected = min(elapsed / estimated, 1)
                            gap = abs(progress - expected)
                            progress_score = max(0, min(100, round(100 - gap * 150)))
                            if gap > 0.3:
                                issues.append('Print progress behind schedule')
                elif resp.status == 404:
                    pass
        except Exception:
            progress_score = 0

        material_score = 50
        try:
            mat_scores = []
            for e in [0, 1]:
                async with session.get(
                    f'http://{ip}/api/v1/printer/heads/0/extruders/{e}/active_material/length_remaining'
                ) as resp:
                    if resp.status == 200:
                        val = await resp.json()
                        if isinstance(val, (int, float)):
                            if val < 0:
                                mat_scores.append(0)
                            elif val == 0:
                                mat_scores.append(5)
                            elif val < 1000:
                                mat_scores.append(25)
                            elif val < 10000:
                                mat_scores.append(60)
                            else:
                                mat_scores.append(100)
            if mat_scores:
                material_score = round(sum(mat_scores) / len(mat_scores))
                if material_score == 0:
                    issues.append('No material detected')
                elif material_score < 30:
                    issues.append('Material running low')
            else:
                material_score = 30
        except Exception:
            material_score = 30

        error_score = 100
        try:
            async with session.get(f'http://{ip}/api/v1/system/log') as resp:
                if resp.status == 200:
                    logs = await resp.json()
                    recent_errors = 0
                    for log_entry in logs[-100:]:
                        text = str(log_entry)
                        if 'ERR' in text:
                            recent_errors += 1
                            if 'temperature' in text.lower():
                                issues.append('System log: temperature error')
                            elif 'communication' in text.lower():
                                issues.append('System log: communication error')
                            elif 'heater' in text.lower():
                                issues.append('System log: heater error')
                            elif 'movement' in text.lower():
                                issues.append('System log: movement error')
                    error_score = max(0, min(100, round(100 - recent_errors * 6)))
                    if recent_errors > 5:
                        issues.append(f'{recent_errors} recent system errors')
        except Exception:
            error_score = 50

        try:
            async with session.get(
                f'http://{ip}/api/v1/printer/diagnostics/probing_report',
                headers={'Accept': 'application/gzip'}
            ) as resp:
                if resp.status == 200:
                    raw = await resp.read()
                    report = json.loads(raw)
                    r0 = report.get('0', {})
                    points = r0.get('_ProbeReport__probe_points', [])
                    if points:
                        z_vals = [p['_ProbePoint__z_offset_from_bed_zero'] for p in points]
                        variance = max(z_vals) - min(z_vals)
                        if variance > 1.0:
                            issues.append(f'Bed variance high: {variance:.2f}mm')
        except Exception:
            pass

    except Exception:
        return web.json_response({'score': 0, 'components': {}, 'issues': ['Cannot connect to printer']})

    aggregate = round(
        temp_score * 0.20 +
        printer_status_score * 0.15 +
        progress_score * 0.20 +
        material_score * 0.15 +
        error_score * 0.15 +
        core_score * 0.08 +
        calibration_score * 0.07
    )

    return web.json_response({
        'score': aggregate,
        'components': {
            'temperature': temp_score,
            'status': printer_status_score,
            'progress': progress_score,
            'material': material_score,
            'errors': error_score,
            'cores': core_score,
            'calibration': calibration_score,
        },
        'issues': issues[:8],
    })


@web.middleware
async def auth_middleware(request, handler):
    skip_paths = ['/login', '/logout', '/setup']
    if request.path in skip_paths or request.path.startswith('/static/'):
        return await handler(request)
    auth_result = await login_required(request)
    if auth_result:
        return auth_result
    return await handler(request)


async def index(request):
    return web.FileResponse('src/templates/index.html')


async def setup_page(request):
    return web.FileResponse('src/templates/setup.html')


async def settings_page(request):
    return aiohttp_jinja2.render_template('settings.html', request, {})


async def diagnostics_page(request):
    return aiohttp_jinja2.render_template('diagnostics.html', request, {})


async def event_log_page(request):
    try:
        events = await event_log_service.get_formatted_events()
        return aiohttp_jinja2.render_template('event_log.html', request, {'events': events})
    except Exception as e:
        return web.Response(text=f"Error loading event log: {str(e)}", status=500)


async def print_jobs_page(request):
    try:
        print_jobs = await print_jobs_service.get_formatted_print_jobs(50)
        return aiohttp_jinja2.render_template('print_jobs.html', request, {'print_jobs': print_jobs})
    except Exception as e:
        return web.Response(text=f"Error loading print jobs: {str(e)}", status=500)


async def api_setup_auth_request(request):
    try:
        data = await request.json()
        printer_ip = data.get('printer_ip', os.getenv('PRINTER_IP', ''))
        if not printer_ip:
            return web.json_response({'error': 'Printer IP is required'}, status=400)
        result = await request_auth(printer_ip)
        if result:
            return web.json_response(result)
        return web.json_response({'error': 'Failed to request authorization from printer'}, status=500)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_setup_auth_status(request):
    try:
        printer_ip = os.getenv('PRINTER_IP', '')
        if not printer_ip:
            return web.json_response({'error': 'Printer IP not configured'}, status=400)
        auth_id = request.match_info['auth_id']
        status = await check_auth(printer_ip, auth_id)
        if status:
            return web.json_response({'status': status})
        return web.json_response({'error': 'Failed to check auth status'}, status=500)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_setup_save(request):
    try:
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
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_setup_status(request):
    try:
        status = get_status()
        return web.json_response(status)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_setup_reset(request):
    try:
        data = await request.json() if request.can_read_body else {}
        reset_type = data.get('type', 'all')
        if reset_type == 'auth':
            reset_printer_auth()
        else:
            reset_all()
        reload_env()
        return web.json_response({'status': 'ok'})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_settings_credentials(request):
    try:
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
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_settings_credentials_check(request):
    try:
        data = await request.json() if request.can_read_body else {}
        username = data.get('username', '')
        password = data.get('password', '')
        from auth import authenticate
        if await authenticate(username, password):
            return web.json_response({'valid': True})
        return web.json_response({'valid': False})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


log_manager: LogManager | None = None
event_log_service: EventLogService | None = None
print_jobs_service: PrintJobsService | None = None


def init_app():
    global log_manager, event_log_service, print_jobs_service

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
        session_middleware(get_session_storage()),
        auth_middleware,
    ])

    app['session_secret_key'] = get_secret_key().encode('utf-8')

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader('src/templates')
    )

    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["GET", "POST", "OPTIONS"],
            max_age=3600
        )
    })

    app.router.add_get('/', index)
    app.router.add_get('/setup', setup_page)
    app.router.add_get('/settings', settings_page)
    app.router.add_get('/login', login_page)
    app.router.add_post('/login', login_handler)
    app.router.add_get('/logout', logout_handler)
    app.router.add_get('/event-log', event_log_page)
    app.router.add_get('/print-jobs', print_jobs_page)
    app.router.add_get('/diagnostics', diagnostics_page)

    app.router.add_post('/api/setup/auth-request', api_setup_auth_request)
    app.router.add_get('/api/setup/auth-status/{auth_id}', api_setup_auth_status)
    app.router.add_post('/api/setup/save', api_setup_save)
    app.router.add_get('/api/setup/status', api_setup_status)
    app.router.add_post('/api/setup/reset', api_setup_reset)

    app.router.add_post('/api/settings/credentials', api_settings_credentials)
    app.router.add_post('/api/settings/credentials/check', api_settings_credentials_check)

    app.router.add_routes(routes)
    app.router.add_static('/static', 'src/static')

    for route in list(app.router.routes()):
        cors.add(route)

    app.on_shutdown.append(lambda _: close_printer_session())

    return app


if __name__ == '__main__':
    app = init_app()
    logger.info('Starting UltiUI server on http://localhost:8081')
    web.run_app(app, host='0.0.0.0', port=8081)
