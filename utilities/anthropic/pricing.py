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
    "opus-4.8": "claude-opus-4-8",               # 🆕 Current flagship (PilgrimBot deep/math, #1493)
    "sonnet-4.6": "claude-sonnet-4-6",           # ✅ Current Sonnet — speed/intelligence balance
    "haiku-4.5": "claude-haiku-4-5-20251001",    # ⚡ Fastest, near-frontier intelligence
    # Superseded — kept for historical pricing refs; do NOT point live paths here.
    "opus-4.6": "claude-opus-4-6",               # superseded flagship
    "sonnet-4.5": "claude-sonnet-4-5-20250929",  # superseded (#1493)
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
    # Claude 4.8 / 4.6 (current) — MUST precede the shorter 'claude-opus-4'/'claude-sonnet-4'
    # keys: the exact-match loop uses substring `in`, and 'claude-opus-4' is a substring of
    # 'claude-opus-4-8' (#1493). Rates LiteLLM-verified, match utilities/anthropic_logger.py.
    'claude-opus-4-8': {'input': 0.000005, 'output': 0.000025},    # $5/$25 per million
    'claude-sonnet-4-6': {'input': 0.000003, 'output': 0.000015},  # $3/$15 per million

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


def log_api_usage(model, usage, feature=None, streaming=False,
                  image_count=0, user_id=None, duration_ms=None):
    """Thin compatibility shim — routes to the canonical kumori logger.

    Bug #1477 (Andy 2026-05-14): used to be 60 lines of duplicate logging
    machinery that paralleled utilities/anthropic_logger.py::log_usage_async.
    Both wrote to the same kumori_api_usage table with the same column shape,
    same cost formula, same DB connection pattern — and the parallel impl is
    exactly what made the streaming cache-token leak possible (stream_chat
    passed a partial dict that this function silently logged as zeros for
    every cache field). One canonical logger means one place to fix it.

    Pattern: kumori-canonical (see ~/.claude/skills/kumori-infrastructure/).
    When kumori exports a utility for a cross-cutting concern (Anthropic
    logging, Postgres connection, Gmail send, GCP secrets), every downstream
    in ~/Desktop/code/* routes through it. Local re-implementations are
    DRY violations that produce reconciliation drift — exhibit A: this bug.

    All 9 historical callers keep their imports + signatures unchanged.
    """
    from utilities.anthropic_logger import log_usage_async
    log_usage_async(
        app_name=APP_NAME, model=model, usage=usage,
        feature=feature, user_id=user_id,
        duration_ms=duration_ms, streaming=streaming,
        image_count=image_count,
    )


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """Get accurate pricing per token for different Claude models"""
    model_lower = model_name.lower()

    # Find exact match first
    for model_key, prices in MODEL_PRICING.items():
        if model_key in model_lower:
            return prices

    # Fallback to partial matches (newest first)
    if 'opus-4-8' in model_lower or 'opus-4.8' in model_lower:
        return MODEL_PRICING['claude-opus-4-8']
    elif 'sonnet-4-6' in model_lower or 'sonnet-4.6' in model_lower:
        return MODEL_PRICING['claude-sonnet-4-6']
    elif 'haiku-4-5' in model_lower or 'haiku-4.5' in model_lower:
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
