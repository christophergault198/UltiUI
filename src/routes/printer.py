"""Printer proxy and diagnostics API routes.

These endpoints talk directly to the Ultimaker printer's local REST API
(read-only stats/diagnostics plus a small number of control actions like
pause/resume/abort and LED brightness).
"""
import asyncio
import json
import os
import re
from datetime import datetime

import numpy as np
import requests
from aiohttp import web
from requests.auth import HTTPDigestAuth

from config import get_printer_auth, get_printer_ip
from logger import logger
from middleware import error_handler, require_printer_ip
from printer_client import get_printer_session
from setup_service import reload_env, save_printer_ip

routes = web.RouteTableDef()

# Bed-leveling tolerance threshold (mm). In-memory only - resets to the
# default on restart, same as before this refactor.
config = {
    'tolerance_threshold': 1.0,
}


def _get_printer_ip():
    return get_printer_ip()


def _digest_auth():
    auth = get_printer_auth()
    return HTTPDigestAuth(
        auth['username'] or 'ultimaker',
        auth['password'] or ''
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
@error_handler
async def set_led_brightness(request):
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
@error_handler
async def control_print_job(request):
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


# --- Manual controls: temperature setpoints and head jog/home -----------
#
# These are the only controls in this module that can make the printer's
# nozzle/bed heat up or the gantry move on its own, so they get extra
# validation (clamped ranges) and, for movement, a hard safety guard
# against moving the head while a print is physically on the bed.

BED_TEMP_RANGE = (0.0, 120.0)
NOZZLE_TEMP_RANGE = (0.0, 280.0)
JOG_MAX_STEP_MM = 50.0
JOG_DEFAULT_SPEED_MM_S = 30.0  # deliberately slower than the API's own
# default (150mm/s) since a human is watching and jogging interactively.

# print_job.state values that mean a job is physically present on the bed
# (printing, paused, or in one of the surrounding transitional states).
# Anything other than "no job at all" blocks head movement - fail safe
# rather than trying to enumerate every state that's "probably fine".
_JOG_UNSAFE_PRINT_STATES = {
    'printing', 'pausing', 'paused', 'resuming',
    'pre_print', 'post_print', 'wait_cleanup', 'wait_user_action',
}


def _clamp(value: float, bounds: tuple) -> float:
    low, high = bounds
    return max(low, min(high, value))


async def _current_print_job_state():
    """Return the printer's print_job state, or None if there's no job."""
    session = await get_printer_session()
    try:
        async with session.get(f'http://{_get_printer_ip()}/api/v1/print_job') as response:
            if response.status == 200:
                data = await response.json()
                return data.get('state')
    except Exception:
        logger.exception('Failed to check print job state before a movement command')
        return 'unknown'  # fail safe: treat "couldn't check" as unsafe
    return None


async def _reject_if_unsafe_to_move():
    """Return a 409 JSON response if it's not safe to home/jog right now,
    otherwise None."""
    state = await _current_print_job_state()
    if state in _JOG_UNSAFE_PRINT_STATES or state == 'unknown':
        return web.json_response(
            {'error': f'Refusing to move the head while a print job is active (state: {state})'},
            status=409
        )
    return None


@routes.put('/api/printer/bed/temperature')
@require_printer_ip
@error_handler
async def set_bed_temperature(request):
    data = await request.json()
    temperature = _clamp(float(data.get('temperature', 0)), BED_TEMP_RANGE)
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: requests.put(
            f'http://{_get_printer_ip()}/api/v1/printer/bed/temperature/target',
            json=temperature,
            auth=_digest_auth(),
            timeout=10
        )
    )
    if resp.status_code in (200, 204):
        logger.info('Bed temperature set to %.1f', temperature)
        return web.json_response({'status': 'ok', 'temperature': temperature})
    return web.json_response(
        {'error': f'Failed to set bed temperature: {resp.status_code}', 'detail': resp.text},
        status=resp.status_code
    )


@routes.put('/api/printer/extruder/{extruder_id}/temperature')
@require_printer_ip
@error_handler
async def set_extruder_temperature(request):
    extruder_id = request.match_info['extruder_id']
    if extruder_id not in ('0', '1'):
        return web.json_response({'error': 'Invalid extruder id'}, status=400)
    data = await request.json()
    temperature = _clamp(float(data.get('temperature', 0)), NOZZLE_TEMP_RANGE)
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: requests.put(
            f'http://{_get_printer_ip()}/api/v1/printer/heads/0/extruders/{extruder_id}/hotend/temperature/target',
            json=temperature,
            auth=_digest_auth(),
            timeout=10
        )
    )
    if resp.status_code in (200, 204):
        logger.info('Extruder %s temperature set to %.1f', extruder_id, temperature)
        return web.json_response({'status': 'ok', 'temperature': temperature})
    return web.json_response(
        {'error': f'Failed to set extruder temperature: {resp.status_code}', 'detail': resp.text},
        status=resp.status_code
    )


@routes.post('/api/printer/home')
@require_printer_ip
@error_handler
async def home_printer(request):
    unsafe = await _reject_if_unsafe_to_move()
    if unsafe:
        return unsafe
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: requests.post(
            f'http://{_get_printer_ip()}/api/v1/printer/heads/0/position',
            json='home',
            auth=_digest_auth(),
            timeout=15
        )
    )
    if resp.status_code in (200, 204):
        logger.info('Head homed')
        return web.json_response({'status': 'ok'})
    return web.json_response(
        {'error': f'Failed to home head: {resp.status_code}', 'detail': resp.text},
        status=resp.status_code
    )


@routes.post('/api/printer/jog')
@require_printer_ip
@error_handler
async def jog_printer(request):
    data = await request.json()
    axis = data.get('axis')
    if axis not in ('x', 'y', 'z'):
        return web.json_response({'error': "axis must be 'x', 'y', or 'z'"}, status=400)
    try:
        delta = float(data.get('delta', 0))
    except (TypeError, ValueError):
        return web.json_response({'error': 'delta must be a number'}, status=400)
    delta = max(-JOG_MAX_STEP_MM, min(JOG_MAX_STEP_MM, delta))

    unsafe = await _reject_if_unsafe_to_move()
    if unsafe:
        return unsafe

    session = await get_printer_session()
    async with session.get(f'http://{_get_printer_ip()}/api/v1/printer/heads/0/position') as response:
        if response.status != 200:
            return web.json_response(
                {'error': f'Could not read current head position: {response.status}'},
                status=502
            )
        current = await response.json()

    target = {
        'x': current.get('x', 0),
        'y': current.get('y', 0),
        'z': current.get('z', 0),
        'speed': JOG_DEFAULT_SPEED_MM_S,
    }
    target[axis] = target[axis] + delta

    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: requests.put(
            f'http://{_get_printer_ip()}/api/v1/printer/heads/0/position',
            json=target,
            auth=_digest_auth(),
            timeout=15
        )
    )
    if resp.status_code in (200, 204):
        logger.info('Jogged %s by %.2fmm', axis, delta)
        return web.json_response({'status': 'ok', 'axis': axis, 'target': target[axis]})
    return web.json_response(
        {'error': f'Failed to jog head: {resp.status_code}', 'detail': resp.text},
        status=resp.status_code
    )


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
    log_manager = request.app['log_manager']
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


DEFAULT_PROBE_REPORT_FILENAME = 'probe_report.json'


def _parse_probe_report_filename(content_disposition: str) -> str:
    """Extract a filename from a Content-Disposition header value.

    Falls back to DEFAULT_PROBE_REPORT_FILENAME on any parsing failure.
    """
    if 'filename=' not in content_disposition:
        return DEFAULT_PROBE_REPORT_FILENAME
    try:
        filename_part = content_disposition.split('filename=')[1].strip()
        if filename_part.startswith('"') and filename_part.endswith('"'):
            return filename_part[1:-1]
        return filename_part.split(';')[0].strip()
    except Exception:
        return DEFAULT_PROBE_REPORT_FILENAME


def _sanitize_probe_filename(filename: str) -> str:
    """Reduce a (not trusted) filename to a safe basename.

    The filename comes from a header on the printer's HTTP response, which
    is not trusted input. Strip any path components and reject anything
    that isn't a plain filename, to prevent writing outside of the reports
    directory (path traversal).
    """
    filename = os.path.basename(filename).strip()
    if not filename or filename in ('.', '..'):
        return DEFAULT_PROBE_REPORT_FILENAME
    return filename


def _is_within_directory(directory: str, path: str) -> bool:
    """True if the resolved `path` is inside `directory`."""
    directory = os.path.abspath(directory)
    path = os.path.abspath(path)
    return os.path.commonpath([directory, path]) == directory


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
            filename = _sanitize_probe_filename(_parse_probe_report_filename(content_disp))

            raw_data = await response.read()
            logger.info('Received %d bytes', len(raw_data))

            reports_dir = os.path.join('data', 'probe_reports')
            os.makedirs(reports_dir, exist_ok=True)
            file_path = os.path.join(reports_dir, filename)

            # Belt-and-suspenders: confirm the resolved path still lives inside
            # reports_dir before writing.
            if not _is_within_directory(reports_dir, file_path):
                logger.warning('Rejected probe report with unsafe filename: %r', filename)
                return web.json_response({'error': 'Invalid probe report filename'}, status=400)

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
@error_handler
async def update_tolerance_threshold(request):
    data = await request.json()
    if 'tolerance_threshold' in data:
        new_tolerance = float(data['tolerance_threshold'])
        if new_tolerance <= 0:
            return web.json_response({'error': 'Tolerance threshold must be positive'}, status=400)
        config['tolerance_threshold'] = new_tolerance
        logger.info('Tolerance threshold updated to %f', new_tolerance)
        return web.json_response({'status': 'success', 'tolerance_threshold': new_tolerance})
    return web.json_response({'error': 'Invalid request data'}, status=400)


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
            # Delegate to setup_service, which both persists the value to
            # .env and updates os.environ immediately - a hand-rolled write
            # here previously only touched .env, so get_printer_ip() kept
            # returning the stale value until the process restarted.
            save_printer_ip(data['printer_ip'])
            reload_env()
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
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e), 'connected': False})


@routes.get('/api/camera/stream')
async def camera_stream(request):
    ip = _get_printer_ip()
    if not ip:
        return web.Response(status=400, text='Printer IP not configured')
    return web.HTTPFound(f"http://{ip}:8080/?action=stream")


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
