import os
import hashlib
import hmac
import base64
from aiohttp import web
from aiohttp_session import get_session
import json
import aiohttp_jinja2

# Default credentials - in a production environment, these should be stored securely
# and loaded from environment variables or a secure database
DEFAULT_USERNAME = os.getenv('ULTIUI_USERNAME', 'admin')
DEFAULT_PASSWORD = os.getenv('ULTIUI_PASSWORD', 'admin')

# Secret key for session encryption - should be a secure random value in production
SECRET_KEY = os.getenv('ULTIUI_SECRET_KEY', 'your-secret-key-here')

def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(password, hashed_password):
    """Verify a password against its hash"""
    return hmac.compare_digest(hash_password(password), hashed_password)

def get_hashed_password(username):
    """Get the hashed password for a username"""
    if username == DEFAULT_USERNAME:
        return hash_password(DEFAULT_PASSWORD)
    return None

async def authenticate(username, password):
    """Authenticate a user with username and password"""
    hashed_password = get_hashed_password(username)
    if hashed_password and verify_password(password, hashed_password):
        return True
    return False

async def login_required(request):
    """Middleware to check if a user is authenticated"""
    session = await get_session(request)
    if not session.get('authenticated', False):
        # If it's an API request, return a JSON response
        if request.path.startswith('/api/'):
            return web.json_response({'error': 'Authentication required'}, status=401)
        # Otherwise, redirect to the login page
        return web.HTTPFound('/login')
    return None

async def login_handler(request):
    """Handle login requests"""
    try:
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        
        if await authenticate(username, password):
            session = await get_session(request)
            session['authenticated'] = True
            session['username'] = username
            
            # Redirect to the requested page or home
            redirect_to = request.query.get('redirect', '/')
            return web.HTTPFound(redirect_to)
        else:
            # Render login page with error
            return aiohttp_jinja2.render_template(
                'login.html',
                request,
                {'error': 'Invalid username or password'}
            )
    except Exception as e:
        return aiohttp_jinja2.render_template(
            'login.html',
            request,
            {'error': f'Login error: {str(e)}'}
        )

async def logout_handler(request):
    """Handle logout requests"""
    session = await get_session(request)
    session['authenticated'] = False
    session['username'] = None
    return web.HTTPFound('/login')

async def login_page(request):
    """Render the login page"""
    return aiohttp_jinja2.render_template('login.html', request, {}) 