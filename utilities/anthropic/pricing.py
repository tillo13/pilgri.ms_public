"""Claude model catalog, pricing, and kumori_api_usage logging.

Extracted from utilities/claude_utils.py (Round 5 refactor).
"""

import logging
from typing import Dict

logger = logging.getLogger("claude_utils")

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Latest Claude models with performance characteristics
CLAUDE_MODELS = {
    # Latest (2026)
    "opus-4.6": "claude-opus-4-6",               # 🆕 Latest flagship, best reasoning/coding
    "sonnet-4.5": "claude-sonnet-4-5-20250929",  # ✅ Best speed/intelligence balance
    "haiku-4.5": "claude-haiku-4-5-20251001",    # ⚡ Fastest, near-frontier intelligence
    # Legacy (still available)
    "opus-4.5": "claude-opus-4-5-20251101",      # Previous flagship
    "opus-4.1": "claude-opus-4-1-20250805",      # ✅ ~3.5s response time
    "opus-4": "claude-opus-4-20250514",          # ⚠️ ~35s response time - slow
    "sonnet-4": "claude-sonnet-4-20250514",      # ✅ Good for coding
    "sonnet-3.7": "claude-3-7-sonnet-20250219",  # Legacy
    "haiku-3": "claude-3-haiku-20240307",        # ⚡ Cheapest, very fast
}

# ACCURATE MODEL PRICING (per token, not per million tokens)
MODEL_PRICING = {
    # Claude 4.5/4.6 models
    'claude-opus-4-6': {'input': 0.000015, 'output': 0.000075},    # $15/$75 per million
    'claude-sonnet-4-5': {'input': 0.000003, 'output': 0.000015},  # $3/$15 per million
    'claude-haiku-4-5': {'input': 0.0000008, 'output': 0.000004},  # $0.80/$4 per million

    # Claude 4.1 models
    'claude-opus-4-1': {'input': 0.000020, 'output': 0.000080},  # $20/$80 per million

    # Claude 4 models
    'claude-opus-4': {'input': 0.000015, 'output': 0.000075},    # $15/$75 per million
    'claude-sonnet-4': {'input': 0.000003, 'output': 0.000015},  # $3/$15 per million

    # Claude 3.7 models
    'claude-3-7-sonnet': {'input': 0.000003, 'output': 0.000015}, # $3/$15 per million

    # Claude 3.5 models
    'claude-3-5-sonnet': {'input': 0.000003, 'output': 0.000015}, # $3/$15 per million
    'claude-3-5-haiku': {'input': 0.00000025, 'output': 0.00000125}, # $0.25/$1.25 per million

    # Claude 3 models
    'claude-3-haiku': {'input': 0.00000025, 'output': 0.00000125}, # $0.25/$1.25 per million

    # Default fallback (Sonnet pricing)
    'default': {'input': 0.000003, 'output': 0.000015}
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1
WEB_SEARCH_COST = 0.01
WEB_SEARCH_TOOL_VERSION = "web_search_20260209"  # update here when Anthropic releases newer version

APP_NAME = 'galactica'


def _get_kumori_connection():
    """Get a connection to the kumori DB specifically for usage logging."""
    import psycopg2
    from utilities.postgres.core import get_secret
    host = get_secret('KUMORI_POSTGRES_IP')
    dbname = get_secret('KUMORI_POSTGRES_DB_NAME')
    user = get_secret('KUMORI_POSTGRES_USERNAME')
    password = get_secret('KUMORI_POSTGRES_PASSWORD')
    return psycopg2.connect(host=host, dbname=dbname, user=user, password=password)


def log_api_usage(model, usage, feature=None, streaming=False,
                  image_count=0, user_id=None, duration_ms=None):
    """Log an API call to kumori_api_usage in a background thread.
    Never blocks the caller. Never raises."""
    import threading

    def _do_log():
        try:
            pricing = get_model_pricing(model)

            input_tokens = getattr(usage, 'input_tokens', None) or (usage.get('input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            output_tokens = getattr(usage, 'output_tokens', None) or (usage.get('output_tokens', 0) if isinstance(usage, dict) else 0) or 0
            cache_creation = getattr(usage, 'cache_creation_input_tokens', None) or (usage.get('cache_creation_input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            cache_read = getattr(usage, 'cache_read_input_tokens', None) or (usage.get('cache_read_input_tokens', 0) if isinstance(usage, dict) else 0) or 0
            thinking = getattr(usage, 'thinking_tokens', None) or (usage.get('thinking_tokens', 0) if isinstance(usage, dict) else 0) or 0

            server_tools = getattr(usage, 'server_tool_use', None) or (usage.get('server_tool_use') if isinstance(usage, dict) else None) or {}
            web_searches = getattr(server_tools, 'web_search_requests', None) or (server_tools.get('web_search_requests', 0) if isinstance(server_tools, dict) else 0) or 0
            web_fetches = getattr(server_tools, 'web_fetch_requests', None) or (server_tools.get('web_fetch_requests', 0) if isinstance(server_tools, dict) else 0) or 0
            code_exec = getattr(server_tools, 'code_execution_requests', None) or (server_tools.get('code_execution_requests', 0) if isinstance(server_tools, dict) else 0) or 0

            cost = (
                input_tokens * pricing['input']
                + output_tokens * pricing['output']
                + cache_creation * pricing['input'] * CACHE_WRITE_MULTIPLIER
                + cache_read * pricing['input'] * CACHE_READ_MULTIPLIER
                + thinking * pricing['output']
                + web_searches * WEB_SEARCH_COST
            )

            conn = _get_kumori_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO kumori_api_usage
                        (app_name, feature, model, input_tokens, output_tokens,
                         cache_creation_tokens, cache_read_tokens, thinking_tokens,
                         web_search_requests, web_fetch_requests, code_execution_requests,
                         image_count, estimated_cost_usd, streaming, user_id, duration_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (APP_NAME, feature, model, input_tokens, output_tokens,
                          cache_creation, cache_read, thinking,
                          web_searches, web_fetches, code_exec,
                          image_count, cost, streaming, user_id, duration_ms))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to log API usage: {e}")

    threading.Thread(target=_do_log, daemon=True).start()


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """Get accurate pricing per token for different Claude models"""
    model_lower = model_name.lower()

    # Find exact match first
    for model_key, prices in MODEL_PRICING.items():
        if model_key in model_lower:
            return prices

    # Fallback to partial matches (newest first)
    if 'haiku-4-5' in model_lower or 'haiku-4.5' in model_lower:
        return MODEL_PRICING['claude-haiku-4-5']
    elif 'haiku' in model_lower:
        return MODEL_PRICING['claude-3-haiku']
    elif 'sonnet-4-5' in model_lower or 'sonnet-4.5' in model_lower:
        return MODEL_PRICING['claude-sonnet-4-5']
    elif 'sonnet-4' in model_lower:
        return MODEL_PRICING['claude-sonnet-4']
    elif 'sonnet' in model_lower:
        return MODEL_PRICING['claude-3-5-sonnet']
    elif 'opus-4-6' in model_lower or 'opus-4.6' in model_lower:
        return MODEL_PRICING['claude-opus-4-6']
    elif 'opus-4-1' in model_lower:
        return MODEL_PRICING['claude-opus-4-1']
    elif 'opus' in model_lower:
        return MODEL_PRICING['claude-opus-4']

    return MODEL_PRICING['default']
