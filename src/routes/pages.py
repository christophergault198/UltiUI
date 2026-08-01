"""Server-rendered page routes (as opposed to the JSON API routes)."""
import aiohttp_jinja2
from aiohttp import web


async def index(request):
    return web.FileResponse('src/templates/index.html')


async def setup_page(request):
    return web.FileResponse('src/templates/setup.html')


async def settings_page(request):
    return aiohttp_jinja2.render_template('settings.html', request, {})


async def diagnostics_page(request):
    return aiohttp_jinja2.render_template('diagnostics.html', request, {})


async def event_log_page(request):
    event_log_service = request.app['event_log_service']
    try:
        events = await event_log_service.get_formatted_events()
        return aiohttp_jinja2.render_template('event_log.html', request, {'events': events})
    except Exception as e:
        return web.Response(text=f"Error loading event log: {str(e)}", status=500)


async def print_jobs_page(request):
    print_jobs_service = request.app['print_jobs_service']
    try:
        print_jobs = await print_jobs_service.get_formatted_print_jobs(50)
        return aiohttp_jinja2.render_template('print_jobs.html', request, {'print_jobs': print_jobs})
    except Exception as e:
        return web.Response(text=f"Error loading print jobs: {str(e)}", status=500)
