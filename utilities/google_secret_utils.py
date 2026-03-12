"""
Google Secret Manager Utilities - Obfuscated Variable Names
Handles secure retrieval of sensitive configuration data
"""

import os
import logging
from google.cloud import secretmanager
from google.api_core import exceptions

logger = logging.getLogger(__name__)

# CRITICAL: All secrets stored in kumori-404602 project
SECRETS_PROJECT_ID = "kumori-404602"

_cache = {}
_client = None

def get_credential_blob(secret_id=None, project_id=None, version_id="latest"):
    """
    Retrieves a secret from Google Secret Manager (cached)
    """
    # Default to the primary credential if none specified
    if secret_id is None:
        secret_id = 'SEPOLIA_HUB_WHALE_RANDOMIZER'

    if project_id is None:
        project_id = SECRETS_PROJECT_ID

    cache_key = f"{project_id}:{secret_id}:{version_id}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        global _client
        if _client is None:
            _client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = _client.access_secret_version(request={"name": name})

        data_payload = response.payload.data.decode('UTF-8').strip()

        # Ensure hex format for credential blobs
        if not data_payload.startswith('0x'):
            data_payload = '0x' + data_payload

        logger.info(f"Successfully retrieved credential blob: {secret_id[:8]}...")
        _cache[cache_key] = data_payload
        return data_payload

    except Exception as e:
        logger.error(f"Error retrieving credential blob: {str(e)[:50]}")
        raise


def load_wallet_credentials(project_id=None):
    """
    Loads wallet authentication credentials from Secret Manager
    
    Args:
        project_id: GCP project ID (optional)
        
    Returns:
        str: Wallet credential data as JSON string
    """
    try:
        credential_data = get_credential_blob(
            secret_id='wallet-auth-data',
            project_id=project_id
        )
        logger.info("Wallet credentials loaded successfully")
        return credential_data
        
    except Exception as e:
        logger.error(f"Failed to load wallet credentials: {str(e)}")
        raise Exception(f"Could not load wallet authentication data: {str(e)}")


def get_auth_token(secret_id='api-auth-token', project_id=None):
    """
    Retrieves an authentication token from Secret Manager
    
    Args:
        secret_id: The secret ID containing the token
        project_id: GCP project ID (optional)
        
    Returns:
        str: Authentication token value
    """
    try:
        token_value = get_credential_blob(
            secret_id=secret_id,
            project_id=project_id
        )
        logger.info(f"Auth token retrieved: {secret_id}")
        return token_value.strip()
        
    except Exception as e:
        logger.error(f"Failed to retrieve auth token: {str(e)}")
        raise


def verify_credential_access(project_id=None):
    """
    Verifies that Secret Manager is accessible and configured correctly
    
    Args:
        project_id: GCP project ID (optional)
        
    Returns:
        bool: True if access is verified
    """
    try:
        if project_id is None:
            project_id = SECRETS_PROJECT_ID

        global _client
        if _client is None:
            _client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}"
        
        # Test access by listing secrets
        request = secretmanager.ListSecretsRequest(parent=parent)
        list(_client.list_secrets(request=request, page_size=1))
        
        logger.info("Secret Manager access verified")
        return True
        
    except Exception as e:
        logger.error(f"Secret Manager access verification failed: {str(e)}")
        return False


# Cache for frequently accessed credentials (optional)
_credential_cache = {}

def get_cached_credential(secret_id, project_id=None, cache_duration=300):
    """
    Retrieves a credential with simple in-memory caching
    
    Args:
        secret_id: The ID of the secret
        project_id: GCP project ID (optional)
        cache_duration: How long to cache in seconds (default 5 minutes)
        
    Returns:
        str: The secret value
    """
    import time
    
    cache_key = f"{project_id or 'default'}:{secret_id}"
    current_time = time.time()
    
    # Check cache
    if cache_key in _credential_cache:
        cached_value, timestamp = _credential_cache[cache_key]
        if current_time - timestamp < cache_duration:
            logger.debug(f"Returning cached credential: {secret_id}")
            return cached_value
    
    # Fetch new value
    credential_value = get_credential_blob(secret_id, project_id)
    _credential_cache[cache_key] = (credential_value, current_time)
    
    return credential_value


def clear_credential_cache():
    """Clears the in-memory credential cache"""
    global _credential_cache
    _credential_cache = {}
    logger.info("Credential cache cleared")