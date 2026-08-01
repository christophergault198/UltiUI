import sys
from pathlib import Path

import pytest

# The app's modules use flat imports (e.g. `from auth import ...`) rather
# than a package layout, so `src/` needs to be importable. pyproject.toml
# sets `pythonpath = ["src"]` for pytest, but this is kept as a fallback for
# test runners that don't honor that ini option.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Run a test from an empty temp directory with a clean environment.

    Several modules (config.py, setup_service.py) read/write a `.env` file
    using a relative path and fall back to process environment variables.
    Without this fixture, tests could read or clobber the real project
    .env, or pass/fail depending on what's already in os.environ.
    """
    monkeypatch.chdir(tmp_path)
    for key in (
        'ULTIUI_SECRET_KEY', 'ULTIUI_USERNAME', 'ULTIUI_PASSWORD',
        'PRINTER_IP', 'PRINTER_AUTH_USERNAME', 'PRINTER_AUTH_PASSWORD',
        'PRINTER_API_KEY', 'ULTIUI_ENV_PATH',
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path
