"""Central paid-API killswitch — galactica side.

Reads/writes the same `kumori_api_killswitch` config table that kumori owns,
in the shared kumori-404602 Cloud SQL instance. Galactica calls
`check_killswitch(provider)` before every paid Anthropic / Replicate call.
If MTD spend across ALL apps for that provider has crossed the cap, the row
is flipped to disabled, an alert email is sent (once), and the call is
blocked here in galactica.

Same logic, same table, same alert path as kumori's
`utilities/killswitch.py`. Shape mirrors the canonical version.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from utilities.anthropic_logger import _get_db_creds  # reuse cached creds

logger = logging.getLogger('galactica.killswitch')


class KillswitchTripped(RuntimeError):
    def __init__(self, provider: str, reason: str):
        super().__init__(f"[killswitch] {provider} blocked: {reason}")
        self.provider = provider
        self.reason = reason


def _connect():
    """Open a psycopg2 connection to kumori's Cloud SQL."""
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


def check_killswitch(provider: str, est_cost: float = 0.0) -> None:
    """Raise KillswitchTripped if `provider` is disabled OR MTD + est >= cap.
    Call this BEFORE every paid-API call."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT monthly_cap_usd, enabled, trip_reason "
            "FROM kumori_api_killswitch WHERE provider = %s",
            (provider,),
        )
        row = cur.fetchone()
        if not row:
            return  # not configured = no enforcement
        cap, enabled, trip_reason = float(row[0]), bool(row[1]), row[2]

        if not enabled:
            raise KillswitchTripped(provider, trip_reason or 'manually disabled')

        cur.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM kumori_api_usage "
            "WHERE provider = %s AND created_at >= date_trunc('month', NOW())",
            (provider,),
        )
        mtd = float(cur.fetchone()[0] or 0)

        if mtd + est_cost >= cap:
            reason = (f"MTD ${mtd:.2f} + est ${est_cost:.4f} >= cap ${cap:.2f} "
                      f"(galactica detected, UTC {datetime.utcnow().isoformat(timespec='seconds')})")
            cur.execute(
                "UPDATE kumori_api_killswitch SET enabled = FALSE, trip_reason = %s, "
                "tripped_at = NOW(), updated_at = NOW() "
                "WHERE provider = %s AND enabled = TRUE",
                (reason, provider),
            )
            just_tripped = cur.rowcount > 0
            conn.commit()
            if just_tripped:
                _send_trip_alert(provider, mtd, cap, reason)
                logger.error(f"[killswitch] {provider} TRIPPED by galactica: {reason}")
            raise KillswitchTripped(provider, reason)
    finally:
        if conn:
            conn.close()


def _send_trip_alert(provider: str, mtd: float, cap: float, reason: str) -> None:
    """Send the trip alert via Gmail API. Best-effort, never raises."""
    try:
        import base64
        from email.mime.text import MIMEText
        from googleapiclient.discovery import build
        from utilities.google_secret_utils import get_secret

        creds_pickle = get_secret('GOOGLE_TOKEN_PICKLE')
        if not creds_pickle:
            logger.warning("[killswitch] GOOGLE_TOKEN_PICKLE not available; skip email")
            return
        import pickle
        creds = pickle.loads(creds_pickle if isinstance(creds_pickle, bytes) else creds_pickle.encode('latin-1'))
        gmail = build('gmail', 'v1', credentials=creds)

        body_html = (
            '<div style="font-family:-apple-system,sans-serif;font-size:14px;line-height:1.55;color:#0f172a">'
            f'<p>The <b>{provider}</b> killswitch just tripped.</p>'
            f'<p><b>MTD spent:</b> ${mtd:.2f}<br>'
            f'<b>Cap:</b> ${cap:.2f}<br>'
            f'<b>Detected by:</b> galactica<br>'
            f'<b>Reason:</b> {reason}</p>'
            f'<p>All future {provider} calls from every kumori-family app are now blocked. '
            f'Re-enable at <code>https://kumori.ai/admin/killswitch</code>.</p>'
            '</div>'
        )
        msg = MIMEText(body_html, 'html', 'utf-8')
        msg['To'] = 'andy.tillo@gmail.com'
        msg['From'] = 'Kumori Killswitch <andy.tillo@gmail.com>'
        msg['Subject'] = f"🚨 KUMORI KILLSWITCH TRIPPED — {provider} (${mtd:.2f} of ${cap:.2f})"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    except Exception as e:
        logger.warning(f"[killswitch] trip alert email failed: {e}")
