"""Replicate usage logger — galactica side.

Writes spend rows to the shared kumori_api_usage table with provider='replicate'
so kumori's killswitch can see MTD across every app.

Mirror of kumori/utilities/replicate_logger.py. Pricing dict is shared truth.
Refresh annually from replicate.com/pricing.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from utilities.anthropic_logger import _get_db_creds  # reuse cached creds

logger = logging.getLogger('galactica.replicate_logger')


PER_IMAGE_PRICES = {
    'black-forest-labs/flux-kontext-pro':   0.04,
    'black-forest-labs/flux-kontext-max':   0.08,
    'black-forest-labs/flux-1.1-pro':       0.04,
    'black-forest-labs/flux-1.1-pro-ultra': 0.06,
    'black-forest-labs/flux-pro':           0.055,
    'black-forest-labs/flux-2-pro':         0.06,
    'black-forest-labs/flux-dev':           0.025,
    'black-forest-labs/flux-schnell':       0.003,
    'google/nano-banana':                   0.04,
    'google/nano-banana-pro':               0.06,
}

PER_SECOND_PRICES = {
    'bytedance/seedance-1-pro':  0.011,
    'bytedance/seedance-1-lite': 0.005,
    'meta/sdxl':                 0.000725,
}

DEFAULT_PER_IMAGE_PRICE = 0.05


def estimate_cost(model: str, image_count: int = 1, duration_seconds: float = 0) -> float:
    base = (model or '').split(':')[0]
    if base in PER_IMAGE_PRICES:
        return PER_IMAGE_PRICES[base] * max(1, image_count)
    if base in PER_SECOND_PRICES and duration_seconds > 0:
        return PER_SECOND_PRICES[base] * duration_seconds
    return DEFAULT_PER_IMAGE_PRICE * max(1, image_count)


def _connect():
    import psycopg2
    creds = _get_db_creds()
    is_gcp = os.environ.get('GAE_ENV', '').startswith('standard') or os.path.exists('/cloudsql')
    if is_gcp:
        socket_dir = os.environ.get('DB_SOCKET_DIR', '/cloudsql')
        host = f"{socket_dir}/{creds['connection_name']}"
        return psycopg2.connect(host=host, dbname=creds['dbname'],
                                user=creds['user'], password=creds['password'])
    return psycopg2.connect(host=creds['host'], dbname=creds['dbname'],
                            user=creds['user'], password=creds['password'])


def log_replicate_async(*, app_name: str = 'galactica', model: str, image_count: int = 1,
                        duration_seconds: float = 0, feature: Optional[str] = None,
                        user_id: Optional[str] = None) -> float:
    cost = estimate_cost(model, image_count=image_count, duration_seconds=duration_seconds)
    duration_ms = int(duration_seconds * 1000)

    def _do():
        conn = None
        try:
            conn = _connect()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO kumori_api_usage
                (provider, app_name, feature, model, image_count,
                 estimated_cost_usd, streaming, user_id, duration_ms)
                VALUES ('replicate', %s, %s, %s, %s, %s, FALSE, %s, %s)
            """, (app_name, feature, model, image_count, cost, user_id, duration_ms))
            conn.commit()
            logger.info(f"replicate_logger: logged {app_name}/{model} ${cost:.4f}")
        except Exception as e:
            logger.warning(f"replicate_logger: kumori_api_usage INSERT failed: {e}")
        finally:
            if conn:
                conn.close()

    threading.Thread(target=_do, daemon=True).start()
    return cost


__all__ = ['estimate_cost', 'log_replicate_async']
