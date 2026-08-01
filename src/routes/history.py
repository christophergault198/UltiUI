"""Historical data API routes: printer event log and past print jobs.

These are formatted/aggregated by EventLogService and PrintJobsService,
shared via `request.app`.
"""
from aiohttp import web

routes = web.RouteTableDef()


def _parse_count(request):
    if 'count' not in request.query:
        return None
    try:
        return max(1, min(int(request.query['count']), 1000))
    except ValueError:
        return None


@routes.get('/api/events')
async def get_events(request):
    event_log_service = request.app['event_log_service']
    events = await event_log_service.get_formatted_events(_parse_count(request))
    return web.json_response(events)


@routes.get('/api/print-jobs')
async def get_print_jobs(request):
    print_jobs_service = request.app['print_jobs_service']
    print_jobs = await print_jobs_service.get_formatted_print_jobs(_parse_count(request))
    return web.json_response(print_jobs)
