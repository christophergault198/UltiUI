import hashlib
import hmac

import aiohttp_jinja2
from aiohttp import web
from aiohttp_session import get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from config import get_secret_key, get_ui_credentials
from logger import logger

SESSION_MAX_AGE = 86400


def _make_aes_key(secret: str) -> bytes:
    key = hashlib.sha256(secret.encode('utf-8')).digest()
    return key


def get_session_storage():
    secret = get_secret_key()
    aes_key = _make_aes_key(secret)
    return EncryptedCookieStorage(aes_key, max_age=SESSION_MAX_AGE)


def get_credentials():
    return get_ui_credentials()


def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(password, hashed_password):
    return hmac.compare_digest(hash_password(password), hashed_password)


def get_hashed_password(username):
    creds = get_credentials()
    if username == creds['username']:
        return hash_password(creds['password'])
    return None


async def authenticate(username, password):
    hashed_password = get_hashed_password(username)
    if hashed_password and verify_password(password, hashed_password):
        return True
    return False


async def login_required(request):
    session = await get_session(request)
    if not session.get('authenticated', False):
        if request.path.startswith('/api/'):
            return web.json_response({'error': 'Authentication required'}, status=401)
        return web.HTTPFound('/login')
    last = session.get('last_activity', 0)
    import time
    if time.time() - last > SESSION_MAX_AGE:
        session['authenticated'] = False
        session['username'] = None
        if request.path.startswith('/api/'):
            return web.json_response({'error': 'Session expired'}, status=401)
        return web.HTTPFound('/login')
    session['last_activity'] = time.time()
    return None


def _safe_redirect_target(raw: str) -> str:
    """Only allow redirecting to a local path after login, never an external URL.

    Rejects protocol-relative ("//evil.com") and absolute-with-scheme
    ("https://evil.com") targets to prevent open-redirect abuse of the
    login flow.
    """
    if not raw or not raw.startswith('/') or raw.startswith('//'):
        return '/'
    return raw


async def login_handler(request):
    try:
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')

        if await authenticate(username, password):
            session = await get_session(request)
            session['authenticated'] = True
            session['username'] = username
            import time
            session['last_activity'] = time.time()

            redirect_to = _safe_redirect_target(request.query.get('redirect', '/'))
            return web.HTTPFound(redirect_to)
        else:
            return aiohttp_jinja2.render_template(
                'login.html',
                request,
                {'error': 'Invalid username or password'}
            )
    except Exception:
        # Log the full exception server-side, but never show internal
        # details (paths, exception text) on the login page - this is the
        # one page an unauthenticated visitor can always reach.
        logger.exception('Login error')
        return aiohttp_jinja2.render_template(
            'login.html',
            request,
            {'error': 'Login error - please try again'}
        )


async def logout_handler(request):
    session = await get_session(request)
    session['authenticated'] = False
    session['username'] = None
    session.invalidate()
    return web.HTTPFound('/login')


async def login_page(request):
    return aiohttp_jinja2.render_template('login.html', request, {})
