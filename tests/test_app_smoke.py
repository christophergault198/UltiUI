"""Smoke test that init_app() wires up all route modules and shared
services correctly after the main.py -> routes/* split."""
import main


def test_init_app_registers_expected_routes(isolated_env, monkeypatch):
    monkeypatch.setenv('ULTIUI_SECRET_KEY', 'a-fixed-key-for-this-test-only')

    app = main.init_app()

    paths = {
        route.resource.canonical
        for route in app.router.routes()
        if route.resource is not None
    }

    expected_paths = {
        # pages
        '/', '/setup', '/settings', '/login', '/logout',
        '/event-log', '/print-jobs', '/diagnostics',
        # setup API
        '/api/setup/save', '/api/setup/status', '/api/setup/reset',
        # settings API
        '/api/settings/credentials', '/api/settings/credentials/check',
        # printer API
        '/api/printer-stats', '/api/health-score', '/api/config',
        '/api/print/control', '/api/probing-report',
        # alerts + history API
        '/api/alerts', '/api/alerts/history', '/api/events',
    }
    missing = expected_paths - paths
    assert not missing, f'Routes missing after refactor: {missing}'


def test_init_app_shares_services_via_app_state(isolated_env, monkeypatch):
    monkeypatch.setenv('ULTIUI_SECRET_KEY', 'a-fixed-key-for-this-test-only')

    app = main.init_app()

    assert app['log_manager'] is not None
    assert app['event_log_service'] is not None
    assert app['print_jobs_service'] is not None
