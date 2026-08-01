"""Alert API routes (active alerts, history, resolution, SSE stream).

Alerts are derived server-side from the printer's system log by
LogManager/AlertsService and shared via `request.app['log_manager']`.
"""
import asyncio
import json

from aiohttp import web

from logger import logger

routes = web.RouteTableDef()


@routes.get('/api/alerts')
async def get_alerts(request):
    log_manager = request.app['log_manager']
    alerts = log_manager.alerts_service.get_active_alerts()
    return web.json_response(alerts)


@routes.get('/api/alerts/history')
async def get_alert_history(request):
    log_manager = request.app['log_manager']
    limit = request.query.get('limit', '100')
    try:
        limit = int(limit)
    except ValueError:
        limit = 100
    alerts = log_manager.alerts_service.get_alert_history(limit)
    return web.json_response(alerts)


@routes.post('/api/alerts/{alert_id}/resolve')
async def resolve_alert(request):
    log_manager = request.app['log_manager']
    alert_id = request.match_info['alert_id']
    alert = await log_manager.alerts_service.resolve_alert(alert_id)
    if alert:
        return web.json_response(alert)
    return web.json_response({'error': 'Alert not found'}, status=404)


@routes.get('/api/alerts/stream')
async def alert_stream(request):
    log_manager = request.app['log_manager']
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'

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
