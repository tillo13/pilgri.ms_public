"""
Simple Google OAuth2 authentication utility
Uses Google Secret Manager for credentials
"""

import os
import requests
from flask import session, redirect, url_for, request
from authlib.integrations.flask_client import OAuth
from functools import wraps
from google.cloud import secretmanager
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

_secrets_cache = {}
_sm_client = None

def get_secret(secret_name, project_id="galactica-character-game"):
    """Get secret from environment variable first, then Google Secret Manager (cached)"""
    env_value = os.getenv(secret_name)
    if env_value:
        return env_value
    cache_key = f"{project_id}:{secret_name}"
    if cache_key in _secrets_cache:
        return _secrets_cache[cache_key]
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = _sm_client.access_secret_version(request={"name": name})
    val = response.payload.data.decode("UTF-8")
    _secrets_cache[cache_key] = val
    return val

class SimpleGoogleAuth:
    def __init__(self, app):
        self.app = app
        self.oauth = OAuth(app)
        
        # Configure Google OAuth using Secret Manager
        self.google = self.oauth.register(
            name='google',
            client_id=get_secret('GOOGLE_CLIENT_ID'),
            client_secret=get_secret('GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
    
    def login(self):
        """Start Google OAuth flow"""
        redirect_uri = url_for('auth_callback', _external=True)
        return self.google.authorize_redirect(redirect_uri)


    def handle_callback(self):
        """Handle OAuth callback and store user info in session"""
        try:
            token = self.google.authorize_access_token()
            if token:
                user_info = token.get('userinfo')
                if user_info:
                    # Make session permanent (uses PERMANENT_SESSION_LIFETIME from app config)
                    # This keeps users logged in across browser restarts
                    session.permanent = True

                    # Store in session
                    session['user'] = {
                        'email': user_info.get('email'),
                        'name': user_info.get('name'),
                        'picture': user_info.get('picture'),
                        'google_id': user_info.get('sub')
                    }
                    
                    # Save to database
                    from utilities.postgres.users import upsert_user
                    from utilities.postgres.wallets import get_user_primary_sepolia_wallet, claim_anonymous_wallet
                    user_id = upsert_user(user_info)
                    if user_id:
                        session['user_id'] = user_id
                        print(f"User {user_id} logged in successfully")
                        
                        # CLAIM ANONYMOUS WALLET IF EXISTS (check both new and legacy formats)
                        wallet_address = session.get('_wal_addr')
                        session_wallet = session.get('_wal')
                        if not wallet_address and session_wallet and 'wallet' in session_wallet:
                            wallet_address = session_wallet['wallet']['address']

                        if wallet_address:
                            # Check if they already have a wallet in DB
                            existing_wallet = get_user_primary_sepolia_wallet(user_id)
                            if not existing_wallet:
                                # Claim the anonymous wallet
                                if claim_anonymous_wallet(wallet_address, user_id):
                                    print(f"✅ Claimed anonymous wallet for user {user_id}")
                            # Clear session wallet since it's now in DB (or they have one)
                            session.pop('_wal', None)
                            session.pop('_wal_addr', None)
                    
                    return True
        except Exception as e:
            print(f"Auth error: {e}")
        return False
    
    def logout(self):
        """Clear session and all cached data"""
        session.pop('user', None)
        session.pop('_hyd', None)
        session.pop('_bal', None)
        session.pop('_nav', None)
        session.pop('_cmd', None)
    
    def get_current_user(self):
        """Get current user from session"""
        return session.get('user')
    
    def is_authenticated(self):
        """Check if user is logged in"""
        return 'user' in session

# Decorator for protecting routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def welcome_message():
    """Generate welcome message for logged in user"""
    user = session.get('user')
    if user:
        return f"Welcome back, {user.get('name', 'Player')}!"
    return "Welcome, Guest!"